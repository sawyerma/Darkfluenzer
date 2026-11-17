"""Prozesssteuerung – die EINZIGE Start-/Stop-Logik für macOS-App und Backend:
verwaltete ComfyUI-Instanz und lokaler Cockpit-Server.

Identität der verwalteten Instanz: ``local/comfyui.json`` hält PID, Prozess-Startzeit und
Kommandozeile. Ein Prozess gilt nur dann als "eigene Instanz", wenn alle drei übereinstimmen.
Fremde ComfyUI-Prozesse (z. B. manuell im Terminal gestartet) werden erkannt, aber weder
übernommen noch beendet. Gestoppt wird ausschließlich die eigene Prozessgruppe – kein pkill.
Der Cockpit-Server gilt als eigener, wenn er auf dem konfigurierten Port lauscht und mit
``-m darkfluenzer serve`` gestartet wurde; alles andere auf dem Port ist fremd.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import DATA_DIR_ARGS, ComfyConfig, Config

log = logging.getLogger("darkfluenzer.runtime")

SERVER_LOG_NAME = "server.log"
LOG_KEEP = 3
SERVER_MARK = "-m darkfluenzer serve"
_POLL_S = 0.5
_ENV_DROP = ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__", "CONDA_PREFIX")


class RuntimeFailure(Exception):
    """Basisklasse; ``code`` ist maschinenlesbar, die Meldung für Menschen."""

    code = "error"
    exit_code = 1

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.details = details


class InvalidSetup(RuntimeFailure):
    code = "config_invalid"
    exit_code = 2


class ForeignInstance(RuntimeFailure):
    code = "foreign_instance"
    exit_code = 3


class StartFailed(RuntimeFailure):
    code = "start_failed"
    exit_code = 4


class Busy(RuntimeFailure):
    code = "busy"
    exit_code = 5


class StopFailed(RuntimeFailure):
    code = "stop_failed"
    exit_code = 6


@dataclass
class Instance:
    instance_id: str
    pid: int
    proc_start: str
    command: str
    host: str
    port: int
    status: str  # "starting" | "running"
    started_at: str
    log_path: str


# --------------------------------------------------------------------------- Prozess-Helfer


def _ps(pid: int, field: str) -> str | None:
    try:
        out = subprocess.run(
            ["/bin/ps", "-o", f"{field}=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip()
    return value or None


def process_start_time(pid: int) -> str | None:
    return _ps(pid, "lstart")


def process_command(pid: int) -> str | None:
    return _ps(pid, "command")


def pid_alive(pid: int) -> bool:
    _reap(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reap(pid: int) -> None:
    """Zombie einsammeln, falls der Prozess ein Kind dieses Python-Prozesses ist."""
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)


def listening_pids(port: int) -> list[int]:
    """PIDs, die auf ``port`` (TCP) lauschen. Leere Liste = Port frei."""
    try:
        out = subprocess.run(
            ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeFailure(f"Portprüfung mit lsof fehlgeschlagen: {exc}") from exc
    return sorted({int(x) for x in out.stdout.split() if x.strip().isdigit()})


def probe(host: str, port: int, timeout: float = 2.0) -> dict | None:
    """Echter Health-Check: ``GET /system_stats`` muss gültiges ComfyUI-JSON liefern."""
    hostpart = f"[{host}]" if ":" in host else host
    url = f"http://{hostpart}:{port}/system_stats"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    system = data.get("system") if isinstance(data, dict) else None
    if not isinstance(system, dict) or "comfyui_version" not in system:
        return None
    return data


def health_summary(stats: dict | None) -> dict | None:
    if not stats:
        return None
    system = stats.get("system", {})
    devices = stats.get("devices") or [{}]
    return {
        "comfyui_version": system.get("comfyui_version"),
        "pytorch_version": system.get("pytorch_version"),
        "python_version": (system.get("python_version") or "").split(" ")[0],
        "device": devices[0].get("name"),
        "device_type": devices[0].get("type"),
        "argv": system.get("argv"),
    }


# --------------------------------------------------------------------------- Zustand


def _state_path(cfg: Config, c: ComfyConfig) -> Path:
    return cfg.local / c.state_name


def read_state(cfg: Config, c: ComfyConfig) -> Instance | None:
    path = _state_path(cfg, c)
    if not path.exists():
        return None
    try:
        return Instance(**json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError) as exc:
        log.error("Zustandsdatei %s unlesbar (%s) – wird als veraltet behandelt", path, exc)
        return None


def _write_state(cfg: Config, c: ComfyConfig, inst: Instance) -> None:
    path = _state_path(cfg, c)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(inst), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _clear_state(cfg: Config, c: ComfyConfig) -> None:
    with contextlib.suppress(FileNotFoundError):
        _state_path(cfg, c).unlink()


def is_same_process(inst: Instance) -> bool:
    """PID lebt UND Startzeit UND Kommandozeile stimmen mit dem Start-Eintrag überein."""
    if not pid_alive(inst.pid):
        return False
    return (
        process_start_time(inst.pid) == inst.proc_start
        and process_command(inst.pid) == inst.command
    )


@contextlib.contextmanager
def _locked(cfg: Config, c: ComfyConfig, timeout: float) -> Iterator[None]:
    cfg.local.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.local / c.lock_name, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() > deadline:
                    raise Busy(
                        "Ein anderer Start/Stop-Vorgang läuft noch. Bitte kurz warten."
                    ) from exc
                time.sleep(0.2)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# --------------------------------------------------------------------------- Start / Stop


def validate_setup(c: ComfyConfig) -> None:
    if not (c.path / "main.py").is_file():
        raise InvalidSetup(
            f"ComfyUI nicht gefunden: {c.path}/main.py existiert nicht. "
            "comfyui.path in local/config.toml prüfen.",
            path=str(c.path),
        )
    if not c.python.is_file() or not os.access(c.python, os.X_OK):
        raise InvalidSetup(
            f"ComfyUI-Python nicht gefunden oder nicht ausführbar: {c.python}. "
            "comfyui.python in local/config.toml prüfen.",
            python=str(c.python),
        )


def build_command(c: ComfyConfig) -> list[str]:
    own_dirs = []
    if c.data_dir is not None:  # eigene Ordner der Instanz, gemeinsame Modellablage
        for flag, sub in DATA_DIR_ARGS.items():
            own_dirs += [flag, str(c.data_dir / sub)]
    return [
        str(c.python),
        "main.py",
        "--listen",
        c.host,
        "--port",
        str(c.port),
        "--disable-auto-launch",
        *own_dirs,
        *c.extra_args,
    ]


def build_env(c: ComfyConfig, base: dict[str, str] | None = None) -> dict[str, str]:
    """Umgebung wie nach ``conda activate``: Env-bin vorn im PATH, CONDA_PREFIX gesetzt."""
    env = dict(os.environ if base is None else base)
    for key in _ENV_DROP:
        env.pop(key, None)
    env_bin = c.python.parent
    system_path = env.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin"
    env["PATH"] = os.pathsep.join([str(env_bin), *c.path_prepend, system_path])
    prefix = env_bin.parent
    if (prefix / "conda-meta").is_dir():
        env["CONDA_PREFIX"] = str(prefix)
        env["CONDA_DEFAULT_ENV"] = prefix.name
    env.setdefault("LANG", "en_US.UTF-8")
    env["PYTHONUNBUFFERED"] = "1"
    env.update(c.env)
    return env


def _rotate_log(cfg: Config, name: str) -> Path:
    cfg.logs.mkdir(parents=True, exist_ok=True)
    current = cfg.logs / name
    for i in range(LOG_KEEP, 0, -1):
        src = current if i == 1 else cfg.logs / f"{name}.{i - 1}"
        if src.exists():
            os.replace(src, cfg.logs / f"{name}.{i}")
    return current


def log_tail(path: Path, lines: int = 25) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _terminate(pid: int, timeout: float) -> None:
    """Beendet die eigene Prozessgruppe (SIGTERM, dann SIGKILL). Nie fremde Prozesse."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return

    def send(sig: int) -> None:
        with contextlib.suppress(ProcessLookupError):
            if pgid == pid:  # eigene Session/Gruppe, beim Start via start_new_session angelegt
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)

    for sig, wait in ((signal.SIGTERM, timeout), (signal.SIGKILL, 10.0)):
        send(sig)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not pid_alive(pid):
                return
            time.sleep(0.2)
        if sig == signal.SIGTERM:
            log.warning("PID %s reagiert nicht auf SIGTERM – SIGKILL an eigene Gruppe", pid)
    raise StopFailed(f"Prozess {pid} ließ sich nicht beenden.", pid=pid)


def _await_ready(c: ComfyConfig, inst: Instance, proc: subprocess.Popen | None) -> dict:
    deadline = time.monotonic() + c.startup_timeout_s
    while True:
        exited = proc.poll() if proc is not None else (None if is_same_process(inst) else -1)
        if exited is not None:
            raise StartFailed(
                f"ComfyUI wurde beim Start beendet (Exit-Code {exited}). Details im Log.",
                exit_code=exited,
                log=inst.log_path,
                log_tail=log_tail(Path(inst.log_path)),
            )
        stats = probe(c.host, c.port)
        if stats is not None and inst.pid in listening_pids(c.port):
            return stats
        if time.monotonic() > deadline:
            raise StartFailed(
                f"ComfyUI war nach {c.startup_timeout_s:.0f} s nicht betriebsbereit.",
                log=inst.log_path,
                log_tail=log_tail(Path(inst.log_path)),
            )
        time.sleep(_POLL_S)


def _instance_payload(c: ComfyConfig, inst: Instance, stats: dict | None) -> dict:
    return {
        "pid": inst.pid,
        "instance_id": inst.instance_id,
        "url": c.url,
        "started_at": inst.started_at,
        "log": inst.log_path,
        "health": health_summary(stats),
    }


def start(cfg: Config, name: str = "media") -> dict:
    """Startet die verwaltete Instanz ``name`` oder meldet die bereits laufende. Idempotent."""
    c = cfg.instance(name)
    validate_setup(c)
    with _locked(cfg, c, timeout=c.startup_timeout_s + 30):
        inst = read_state(cfg, c)
        if inst is not None:
            if is_same_process(inst):
                stats = probe(c.host, c.port)
                if stats is not None and inst.pid in listening_pids(c.port):
                    log.info("Start angefragt: verwaltete Instanz PID %s läuft bereits", inst.pid)
                    return {"result": "already_running", **_instance_payload(c, inst, stats)}
                log.info("Verwaltete Instanz PID %s lebt, ist aber nicht bereit – warte", inst.pid)
                stats = _await_ready(c, inst, None)
                inst.status = "running"
                _write_state(cfg, c, inst)
                return {"result": "already_running", **_instance_payload(c, inst, stats)}
            log.warning("Veralteter Zustand für PID %s entfernt", inst.pid)
            _clear_state(cfg, c)

        foreign = listening_pids(c.port)
        if foreign:
            stats = probe(c.host, c.port)
            raise ForeignInstance(
                f"Port {c.port} ist bereits belegt (PID {', '.join(map(str, foreign))}). "
                + (
                    "Dort läuft eine nicht von Darkfluenzer gestartete ComfyUI. "
                    if stats
                    else "Der Prozess ist keine erreichbare ComfyUI. "
                )
                + "Sie wird weder übernommen noch beendet.",
                pids=foreign,
                is_comfyui=stats is not None,
                url=c.url,
                health=health_summary(stats),
            )

        log_path = _rotate_log(cfg, c.log_name)
        cmd = build_command(c)
        if c.data_dir is not None:
            for sub in DATA_DIR_ARGS.values():
                (c.data_dir / sub).mkdir(parents=True, exist_ok=True)
        log.info("Starte ComfyUI %s: cwd=%s cmd=%s", c.name, c.path, cmd)
        with open(log_path, "ab") as logf:
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=c.path,
                    env=build_env(c),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise StartFailed(f"ComfyUI-Prozess konnte nicht gestartet werden: {exc}") from exc

        proc_start = process_start_time(proc.pid)
        command = process_command(proc.pid)
        if proc_start is None or command is None:
            _terminate(proc.pid, c.stop_timeout_s)
            raise StartFailed(
                "ComfyUI wurde sofort beendet. Details im Log.",
                log=str(log_path),
                log_tail=log_tail(log_path),
            )
        inst = Instance(
            instance_id=uuid.uuid4().hex,
            pid=proc.pid,
            proc_start=proc_start,
            command=command,
            host=c.host,
            port=c.port,
            status="starting",
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            log_path=str(log_path),
        )
        _write_state(cfg, c, inst)
        t0 = time.monotonic()
        try:
            stats = _await_ready(c, inst, proc)
        except BaseException:
            log.error("Start fehlgeschlagen – beende eigene Instanz PID %s", proc.pid)
            with contextlib.suppress(RuntimeFailure):
                _terminate(proc.pid, c.stop_timeout_s)
            _clear_state(cfg, c)
            raise
        inst.status = "running"
        _write_state(cfg, c, inst)
        log.info(
            "ComfyUI bereit: PID %s nach %.1f s, Version %s",
            proc.pid,
            time.monotonic() - t0,
            stats["system"].get("comfyui_version"),
        )
        return {
            "result": "started",
            "startup_s": round(time.monotonic() - t0, 1),
            **_instance_payload(c, inst, stats),
        }


def stop(cfg: Config, name: str = "media") -> dict:
    """Beendet ausschließlich die eindeutig zugeordnete eigene Instanz ``name``."""
    c = cfg.instance(name)
    with _locked(cfg, c, timeout=c.startup_timeout_s + c.stop_timeout_s + 30):
        inst = read_state(cfg, c)
        if inst is None or not is_same_process(inst):
            if inst is not None:
                log.warning("Stop: veralteter Zustand für PID %s entfernt", inst.pid)
                _clear_state(cfg, c)
            foreign = listening_pids(c.port)
            if foreign:
                log.info("Stop: Port %s gehört fremder PID %s – nicht beendet", c.port, foreign)
                return {
                    "result": "not_managed",
                    "foreign_pids": foreign,
                    "message": "Laufende ComfyUI wurde nicht von Darkfluenzer gestartet "
                    "und wird nicht beendet.",
                }
            return {"result": "not_running"}
        log.info("Stoppe verwaltete Instanz PID %s", inst.pid)
        _terminate(inst.pid, c.stop_timeout_s)
        _clear_state(cfg, c)
        log.info("Verwaltete Instanz PID %s beendet", inst.pid)
        return {"result": "stopped", "pid": inst.pid}


def status(cfg: Config, name: str = "media") -> dict:
    """Nur lesend. Zustände: stopped | starting | running | unhealthy | foreign."""
    c = cfg.instance(name)
    inst = read_state(cfg, c)
    managed = inst is not None and is_same_process(inst)
    listeners = listening_pids(c.port)
    stats = probe(c.host, c.port) if listeners else None
    if managed:
        assert inst is not None
        if stats is not None and inst.pid in listeners:
            state = "running"
        elif inst.status == "starting":
            state = "starting"
        else:
            state = "unhealthy"
        return {"state": state, "managed": True, **_instance_payload(c, inst, stats)}
    payload: dict = {"managed": False, "url": c.url}
    if inst is not None:
        payload["stale_state"] = True
    if listeners:
        payload.update(
            state="foreign",
            foreign_pids=listeners,
            is_comfyui=stats is not None,
            health=health_summary(stats),
        )
    else:
        payload["state"] = "stopped"
    return payload


# --------------------------------------------------------------------------- Cockpit-Server


def cockpit_healthy(cfg: Config) -> bool:
    """Echter Health-Check des Cockpit-Servers: ``GET /healthz`` antwortet 204."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{cfg.server.url}/healthz", timeout=2.0) as resp:
            return resp.status == 204
    except (urllib.error.URLError, OSError):
        return False


def _cockpit_pids(cfg: Config) -> tuple[list[int], list[int]]:
    """(eigene, fremde) PIDs auf dem Cockpit-Port."""
    own: list[int] = []
    foreign: list[int] = []
    for pid in listening_pids(cfg.server.port):
        (own if SERVER_MARK in (process_command(pid) or "") else foreign).append(pid)
    return own, foreign


def cockpit_up(cfg: Config) -> dict:
    """Startet den Cockpit-Server, falls nötig, und wartet auf seinen Health-Check. Idempotent."""
    s = cfg.server
    with _locked(cfg, cfg.comfyui, timeout=s.timeout_s + 30):
        own, foreign = _cockpit_pids(cfg)
        if foreign:
            raise ForeignInstance(
                f"Cockpit-Port {s.port} ist von einem fremden Prozess belegt "
                f"(PID {', '.join(map(str, foreign))}). Port in local/config.toml [server] ändern.",
                pids=foreign,
                url=s.url,
            )
        if own and cockpit_healthy(cfg):
            return {"result": "already_running", "url": s.url, "pid": own[0]}
        proc = None
        log_path = cfg.logs / SERVER_LOG_NAME
        if not own:
            log_path = _rotate_log(cfg, SERVER_LOG_NAME)
            log.info("Starte Cockpit-Server auf %s", s.url)
            with open(log_path, "ab") as logf:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "darkfluenzer", "serve"],
                    cwd=cfg.root,
                    env={**os.environ, "DARKFLUENZER_ROOT": str(cfg.root)},
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        pid = proc.pid if proc else own[0]
        deadline = time.monotonic() + s.timeout_s
        while time.monotonic() < deadline:
            if cockpit_healthy(cfg):
                log.info("Cockpit-Server bereit: PID %s", pid)
                return {"result": "started", "url": s.url, "pid": pid}
            if proc is not None and proc.poll() is not None:
                raise StartFailed(
                    f"Cockpit-Server wurde beim Start beendet (Exit-Code {proc.returncode}).",
                    log=str(log_path),
                    log_tail=log_tail(log_path),
                )
            time.sleep(_POLL_S)
        if proc is not None:
            _terminate(proc.pid, s.timeout_s)
        raise StartFailed(
            f"Cockpit-Server nach {s.timeout_s:.0f} s nicht bereit.",
            log=str(log_path),
            log_tail=log_tail(log_path),
        )


def cockpit_restart(cfg: Config) -> dict:
    """Nur den eigenen Cockpit-Server neu starten (z. B. nach einem Update); ComfyUI bleibt
    unberührt. Verweigert, solange Renderjobs warten oder laufen – sie würden abbrechen."""
    from ..store import Store

    store = Store(cfg.local)
    try:
        busy = len(store.queued_jobs()) + sum(
            1 for _, pid in store.running_jobs() if pid and pid_alive(pid)
        )
    finally:
        store.close()
    if busy:
        raise Busy(
            f"{busy} Renderjob(s) warten oder laufen – ein Neustart würde sie abbrechen. "
            "Nach Abschluss erneut versuchen."
        )
    with _locked(cfg, cfg.comfyui, timeout=cfg.server.timeout_s + 30):
        own, _ = _cockpit_pids(cfg)
        for pid in own:
            log.info("Neustart: stoppe Cockpit-Server PID %s", pid)
            _terminate(pid, cfg.server.timeout_s)
    return cockpit_up(cfg)


def cockpit_down(cfg: Config) -> dict:
    """Beendet den eigenen Cockpit-Server und die eigenen ComfyUI-Instanzen; Fremdes bleibt."""
    with _locked(cfg, cfg.comfyui, timeout=cfg.server.timeout_s + 30):
        own, _ = _cockpit_pids(cfg)
        for pid in own:
            log.info("Stoppe Cockpit-Server PID %s", pid)
            _terminate(pid, cfg.server.timeout_s)
    stopped = {c.name: stop(cfg, c.name)["result"] for c in cfg.instances}
    return {
        "result": "stopped" if own else "not_running",
        "cockpit_pids": own,
        "comfyui": stopped,
    }
