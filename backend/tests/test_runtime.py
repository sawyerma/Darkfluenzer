"""Prozesssteuerung gegen einen echten Fake-ComfyUI-Prozess (kein Mocking von Prozessen/Ports)."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import replace

import pytest

from darkfluenzer.config import Config, project_root
from darkfluenzer.nodes import local as runtime
from darkfluenzer.store import Store


@pytest.fixture(autouse=True)
def _cleanup(cfg: Config):
    yield
    with contextlib.suppress(runtime.RuntimeFailure):
        runtime.stop(cfg)


def with_env(cfg: Config, **env: str) -> Config:
    return replace(cfg, comfyui=replace(cfg.comfyui, env={**cfg.comfyui.env, **env}))


def test_start_from_stopped_then_idempotent(cfg: Config):
    assert runtime.status(cfg)["state"] == "stopped"
    first = runtime.start(cfg)
    assert first["result"] == "started"
    assert first["health"]["comfyui_version"] == "fake-1.0"
    second = runtime.start(cfg)
    assert second["result"] == "already_running"
    assert second["pid"] == first["pid"]
    assert runtime.listening_pids(cfg.comfyui.port) == [first["pid"]]
    st = runtime.status(cfg)
    assert st["state"] == "running" and st["managed"] is True


def test_stop_then_restart(cfg: Config):
    pid = runtime.start(cfg)["pid"]
    assert runtime.stop(cfg) == {"result": "stopped", "pid": pid}
    assert not runtime.pid_alive(pid)
    assert runtime.listening_pids(cfg.comfyui.port) == []
    assert runtime.read_state(cfg, cfg.comfyui) is None
    assert runtime.stop(cfg)["result"] == "not_running"
    again = runtime.start(cfg)
    assert again["result"] == "started" and again["pid"] != pid


def test_foreign_instance_is_neither_adopted_nor_killed(cfg: Config):
    c = cfg.comfyui
    foreign = subprocess.Popen(
        [sys.executable, "main.py", "--listen", c.host, "--port", str(c.port)],
        cwd=c.path,
        stdout=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if runtime.probe(c.host, c.port):
                break
            subprocess.run(["sleep", "0.1"], check=True)
        with pytest.raises(runtime.ForeignInstance) as exc:
            runtime.start(cfg)
        assert exc.value.details["pids"] == [foreign.pid]
        assert exc.value.details["is_comfyui"] is True
        assert runtime.status(cfg)["state"] == "foreign"
        result = runtime.stop(cfg)
        assert result["result"] == "not_managed"
        assert foreign.poll() is None, "fremde Instanz darf nicht beendet werden"
    finally:
        foreign.terminate()
        foreign.wait(5)


def test_crashing_start_is_not_marked_running(cfg: Config):
    with pytest.raises(runtime.StartFailed) as exc:
        runtime.start(with_env(cfg, FAKE_MODE="crash"))
    assert exc.value.details["exit_code"] == 3
    assert "fake crash" in exc.value.details["log_tail"]
    assert runtime.read_state(cfg, cfg.comfyui) is None
    assert runtime.status(cfg)["state"] == "stopped"


def test_startup_timeout_kills_own_process(cfg: Config):
    hanging = with_env(cfg, FAKE_MODE="hang")
    hanging = replace(hanging, comfyui=replace(hanging.comfyui, startup_timeout_s=1.5))
    with pytest.raises(runtime.StartFailed, match="nicht betriebsbereit"):
        runtime.start(hanging)
    assert runtime.read_state(cfg, cfg.comfyui) is None
    out = subprocess.run(["pgrep", "-f", str(cfg.comfyui.path)], capture_output=True, text=True)
    assert out.stdout.strip() == "", "hängender eigener Prozess muss beendet sein"


def test_invalid_python_path_reported(cfg: Config, tmp_path):
    bad = replace(cfg, comfyui=replace(cfg.comfyui, python=tmp_path / "nope" / "python"))
    with pytest.raises(runtime.InvalidSetup, match="ComfyUI-Python nicht gefunden"):
        runtime.start(bad)
    assert runtime.read_state(cfg, cfg.comfyui) is None


def test_invalid_comfy_path_reported(cfg: Config, tmp_path):
    bad = replace(cfg, comfyui=replace(cfg.comfyui, path=tmp_path / "missing"))
    with pytest.raises(runtime.InvalidSetup, match="main.py"):
        runtime.start(bad)


def test_stale_state_is_not_trusted(cfg: Config):
    """Zustandsdatei zeigt auf fremden lebenden Prozess (PID-Wiederverwendung) -> nie anfassen."""
    other = subprocess.Popen(["sleep", "30"])
    try:
        fake = runtime.Instance(
            instance_id="x",
            pid=other.pid,
            proc_start="Thu Jan  1 00:00:00 1970",
            command="python main.py",
            host="127.0.0.1",
            port=cfg.comfyui.port,
            status="running",
            started_at="",
            log_path="",
        )
        (cfg.local / cfg.comfyui.state_name).write_text(json.dumps(fake.__dict__))
        assert runtime.status(cfg)["state"] == "stopped"
        assert runtime.stop(cfg)["result"] == "not_running"
        assert other.poll() is None, "fremder Prozess mit gleicher PID darf nicht beendet werden"
        assert runtime.read_state(cfg, cfg.comfyui) is None
    finally:
        other.terminate()
        other.wait(5)


def test_env_drops_foreign_python_vars(cfg: Config):
    env = runtime.build_env(
        cfg.comfyui, base={"PATH": "/usr/bin", "PYTHONPATH": "/x", "__PYVENV_LAUNCHER__": "/y"}
    )
    assert "PYTHONPATH" not in env and "__PYVENV_LAUNCHER__" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(cfg.comfyui.python.parent)
    assert env["PYTHONUNBUFFERED"] == "1"


def test_command_has_no_auto_launch_and_loopback(cfg: Config):
    cmd = runtime.build_command(cfg.comfyui)
    assert cmd[1] == "main.py"
    assert cmd[cmd.index("--listen") + 1] == "127.0.0.1"
    assert "--disable-auto-launch" in cmd


def test_cli_json_contract(project, cfg: Config):
    env = {**os.environ, "DARKFLUENZER_ROOT": str(project)}
    run = lambda *a: subprocess.run(  # noqa: E731
        [sys.executable, "-m", "darkfluenzer", "comfy", *a, "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    started = run("start")
    assert started.returncode == 0, started.stderr
    payload = json.loads(started.stdout)
    assert payload["ok"] is True and payload["result"] == "started"
    assert json.loads(run("health").stdout)["state"] == "running"
    assert json.loads(run("stop").stdout)["result"] == "stopped"
    unhealthy = run("health")
    assert unhealthy.returncode == 7


def test_cockpit_up_idempotent_down_stops_only_own(cfg: Config):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows")  # echte Registry
    try:
        first = runtime.cockpit_up(cfg)
        assert first["result"] == "started" and runtime.cockpit_healthy(cfg)
        assert runtime.cockpit_up(cfg)["result"] == "already_running"
        store = Store(cfg.local)  # wartender Renderjob: Neustart wird verweigert
        job = store.create_job(None, "lustify_sdxl", "lustify_sdxl_t2i", "p", {}, [])
        with pytest.raises(runtime.Busy):
            runtime.cockpit_restart(cfg)
        store.set_job_status(job, "failed", error="Test")
        store.close()
        restarted = runtime.cockpit_restart(cfg)
        assert restarted["result"] == "started" and restarted["pid"] != first["pid"]
    finally:
        down = runtime.cockpit_down(cfg)
    assert down["result"] == "stopped"
    assert runtime.listening_pids(cfg.server.port) == []

    with socket.socket() as foreign:  # fremder Prozess auf dem Cockpit-Port
        foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # TIME_WAIT der Checks
        foreign.bind(("127.0.0.1", cfg.server.port))
        foreign.listen()
        with pytest.raises(runtime.ForeignInstance):
            runtime.cockpit_up(cfg)
        assert runtime.cockpit_down(cfg)["result"] == "not_running"
