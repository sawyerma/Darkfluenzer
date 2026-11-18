from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from darkfluenzer import config

# Minimaler ComfyUI-Ersatz: gleiche CLI-Argumente, echtes HTTP /system_stats.
FAKE_MAIN = textwrap.dedent(
    """
    import argparse, json, os, sys, time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    p = argparse.ArgumentParser()
    p.add_argument("--listen"); p.add_argument("--port", type=int)
    p.add_argument("--disable-auto-launch", action="store_true")
    a, _ = p.parse_known_args()
    mode = os.environ.get("FAKE_MODE", "ok")
    if mode == "crash":
        print("Traceback: fake crash"); sys.exit(3)
    if mode == "hang":
        time.sleep(3600)
    time.sleep(float(os.environ.get("FAKE_DELAY", "0.3")))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/system_stats":
                self.send_response(404); self.end_headers(); return
            body = json.dumps({"system": {"comfyui_version": "fake-1.0", "pytorch_version": "x",
                               "python_version": sys.version, "argv": sys.argv},
                               "devices": [{"name": "fake", "type": "cpu"}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *args): pass
    print("fake comfy ready", flush=True)
    ThreadingHTTPServer((a.listen, a.port), H).serve_forever()
    """
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_config(root: Path, **overrides: object) -> None:
    values = {
        "path": "local/fake_comfy",
        "python": sys.executable,
        "host": "127.0.0.1",
        "port": free_port(),
        "startup_timeout_s": 15,
        "stop_timeout_s": 5,
    }
    values.update(overrides)
    lines = ["[server]", 'host = "127.0.0.1"', f"port = {free_port()}", "", "[comfyui]"]
    for key, val in values.items():
        lines.append(f"{key} = {val}" if isinstance(val, int | float) else f'{key} = "{val}"')
    lines += ["extra_args = []", "path_prepend = []", "", "[comfyui.env]"]
    (root / "local").mkdir(parents=True, exist_ok=True)
    (root / "local" / "config.toml").write_text("\n".join(lines) + "\n")


def fake_comfy_pids(root: Path) -> list[int]:
    """Fake-ComfyUI-Prozesse dieses Testlaufs unter ``root``: Interpreter des Testlaufs, argv
    ``main.py``, Arbeitsverzeichnis unter ``root``. Die produktiven Instanzen (eigener Interpreter,
    Arbeitsverzeichnis local/ComfyUI) erfüllen das nie."""
    root = root.resolve()
    me = os.path.normpath(sys.executable)  # „backend/../local/…“ und „local/…“ sind derselbe
    rows = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    found = []
    for line in rows.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        argv = cmd.split()
        if len(argv) < 2 or argv[1] != "main.py" or os.path.normpath(argv[0]) != me:
            continue
        out = subprocess.run(
            ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True
        ).stdout
        cwd = next((ln[1:] for ln in out.splitlines() if ln.startswith("n")), "")
        cwd = cwd.removesuffix(" (deleted)")
        if cwd and Path(cwd).resolve().is_relative_to(root):
            found.append(int(pid))
    return found


def reap_fake_comfy(root: Path) -> list[int]:
    """Beendet die Fake-ComfyUI-Prozesse unter ``root`` samt ihrer Prozessgruppe (``runtime.start``
    startet ComfyUI mit eigener Session, damit sie Cockpit-Neustarts übersteht): SIGTERM, nach
    kurzer Frist SIGKILL. Liefert die beendeten PIDs."""
    pids = fake_comfy_pids(root)
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        alive = []
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                pgid = os.getpgid(pid)
                if pgid == pid:
                    os.killpg(pgid, sig)
                else:
                    os.kill(pid, sig)
                alive.append(pid)
        deadline = time.monotonic() + wait
        while alive and time.monotonic() < deadline:
            alive = [p for p in alive if _alive(p)]
            time.sleep(0.05)
        if not alive:
            break
    return pids


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    with contextlib.suppress(ChildProcessError):  # eigenes Kind: Zombie einsammeln
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    return True


@pytest.fixture(autouse=True, scope="session")
def _no_fake_comfy_left(tmp_path_factory):
    """Sicherheitsnetz am Sitzungsende: keine Fake-ComfyUI dieses Testlaufs bleibt zurück."""
    yield
    reap_fake_comfy(tmp_path_factory.getbasetemp())


@pytest.fixture
def project(tmp_path: Path):
    fake = tmp_path / "local" / "fake_comfy"
    fake.mkdir(parents=True)
    (fake / "main.py").write_text(FAKE_MAIN)
    write_config(tmp_path)
    yield tmp_path
    reap_fake_comfy(tmp_path)  # Tests, die über Cockpit oder Pipeline rendern, starten sie


@pytest.fixture
def cfg(project: Path) -> config.Config:
    return config.load(project)


@pytest.fixture
def write_cfg():
    return write_config
