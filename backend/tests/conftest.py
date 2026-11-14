from __future__ import annotations

import socket
import sys
import textwrap
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
    lines = ["[comfyui]"]
    for key, val in values.items():
        lines.append(f"{key} = {val}" if isinstance(val, int | float) else f'{key} = "{val}"')
    lines += ["extra_args = []", "path_prepend = []", "", "[comfyui.env]"]
    (root / "local").mkdir(parents=True, exist_ok=True)
    (root / "local" / "config.toml").write_text("\n".join(lines) + "\n")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    fake = tmp_path / "local" / "fake_comfy"
    fake.mkdir(parents=True)
    (fake / "main.py").write_text(FAKE_MAIN)
    write_config(tmp_path)
    return tmp_path


@pytest.fixture
def cfg(project: Path) -> config.Config:
    return config.load(project)


@pytest.fixture
def write_cfg():
    return write_config
