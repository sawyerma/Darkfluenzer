"""SPEC-018 (Regel 12 e): Sitzungsdateien des Sprachknotens bleiben nie liegen – isolierter
Ordner je Lauf, Löschen nach Abschluss, Fehler, Zeitüberschreitung, Abbruch; Bereinigung beim Start
(Neustart), späte Schreibzugriffe, aktiver Lauf eines anderen Prozesses, parallele Kunden.
Ersatz-ComfyUI über echtes HTTP, die wie der Knoten in ``history_dir`` schreibt."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import free_port

from darkfluenzer.nodes import comfy, llm


class FakeAi:
    """/prompt, /history, /queue, /interrupt, /system_stats; schreibt je Sitzungsknoten eine
    Verlaufsdatei nach history_dir (wie LLMSessionChatNode) und meldet einen PreviewAny-Text."""

    def __init__(self, port: int) -> None:
        self.mode = "ok"  # ok | error | hang
        self.entries: dict[str, dict] = {}
        self.running: set[str] = set()
        self.cancelled: list[str] = []
        self.written: list[Path] = []
        self.pending: dict[str, list[Path]] = {}
        self.late: list[Path] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body: object) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/system_stats":
                    return self._send({"system": {"ram_free": 1}})
                if self.path.startswith("/history/"):
                    pid = self.path.rsplit("/", 1)[1]
                    return self._send({pid: fake.entries[pid]} if pid in fake.entries else {})
                if self.path == "/queue":
                    running = [[0, p, {}, {}, []] for p in sorted(fake.running)]
                    return self._send({"queue_running": running, "queue_pending": []})
                self._send({})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                if self.path == "/prompt":
                    fake.run(body["prompt_id"], body["prompt"])
                    return self._send({"prompt_id": body["prompt_id"], "node_errors": {}})
                if self.path == "/interrupt":
                    fake.interrupt(body.get("prompt_id", ""))
                self._send({})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def interrupt(self, pid: str) -> None:
        """Wie llama.cpp im Knoten: generiert nach dem Interrupt zu Ende, legt den (inzwischen
        gelöschten) Sitzungsordner neu an und schreibt dann die Verlaufsdatei (spätes Schreiben)."""
        self.cancelled.append(pid)

        def finish() -> None:
            time.sleep(0.4)
            for path in self.pending.pop(pid, []):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"turns": ["spät"]}')
                self.late.append(path)
            self.running.discard(pid)

        threading.Thread(target=finish, daemon=True).start()

    def run(self, pid: str, graph: dict) -> None:
        start = time.time() * 1000
        for node in graph.values():
            if node["class_type"] == llm.SESSION_NODE:
                inputs = node["inputs"]
                path = Path(inputs["history_dir"]) / f"{inputs['session_id']}.json"
                path.write_text(json.dumps({"turns": [inputs["user_text"]]}))  # Gesprächsinhalt
                self.written.append(path)
        if self.mode == "hang":
            self.running.add(pid)
            self.pending[pid] = list(
                self.written[-sum(n["class_type"] == llm.SESSION_NODE for n in graph.values()) :]
            )
            return
        if self.mode == "error":
            error = {"node_id": "1", "node_type": llm.SESSION_NODE,
                     "exception_message": "llama.cpp: Kontext zu klein"}  # fmt: skip
            self.entries[pid] = {"status": {"status_str": "error", "completed": False,
                                            "messages": [["execution_error", error]]}}  # fmt: skip
            return
        self.entries[pid] = {
            "status": {"status_str": "success", "completed": True, "messages": [
                ["execution_start", {"timestamp": start + 5}],
                ["execution_success", {"timestamp": start + 105}]]},
            "outputs": {"2": {"text": [f"Antwort auf: {graph['1']['inputs']['user_text']}"]}},
        }  # fmt: skip


def _graph(text: str = "Hallo") -> dict:
    return {
        "1": {"class_type": llm.SESSION_NODE, "inputs": {"user_text": text, "session_id": "x",
              "history_dir": "", "reset_session": False, "max_turns": 12}},
        "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}},
    }  # fmt: skip


@pytest.fixture
def ai(cfg, tmp_path):
    port = free_port()
    fake = FakeAi(port)
    inst = dataclasses.replace(cfg.comfyui, name="ai", port=port, data_dir=tmp_path / "ai")
    yield dataclasses.replace(cfg, comfyui_ai=inst), fake
    fake.server.shutdown()


def _left(cfg) -> list[Path]:
    root = llm.session_root(cfg)
    default = cfg.instance("ai").folder("output") / llm.NODE_DEFAULT_DIR
    return [p for base in (root, default) if base.exists() for p in base.rglob("*")]


def test_isolate_binds_every_session_node_to_the_run_and_drops_node_history(tmp_path):
    graph = _graph() | {"3": {"class_type": llm.SESSION_NODE, "inputs": {"user_text": "b"}}}
    out = llm.isolate_sessions(graph, tmp_path / "run")
    a, b = out["1"]["inputs"], out["3"]["inputs"]
    for inputs in (a, b):
        assert inputs["history_dir"] == str(tmp_path / "run") and inputs["reset_session"] is True
        assert inputs["max_turns"] == 0 and inputs["persistent_cache"] == "off"
        assert inputs["summarize_old_history"] is False
    assert a["session_id"] != b["session_id"] != "x"
    assert out["2"] == graph["2"] and graph["1"]["inputs"]["history_dir"] == ""  # Original bleibt


def test_run_leaves_no_session_file_after_success_error_and_timeout(ai):
    cfg, fake = ai
    result = llm.run_graph(cfg, _graph("Hallo Clara"), timeout_s=5)
    assert result.texts == {"2": "Antwort auf: Hallo Clara"}
    assert result.wait_s >= 0 and abs(result.duration_s - 0.1) < 0.01
    assert fake.written and not any(p.exists() for p in fake.written) and _left(cfg) == []

    fake.mode = "error"
    with pytest.raises(comfy.ComfyError, match="Kontext zu klein"):
        llm.run_graph(cfg, _graph(), timeout_s=5)
    assert _left(cfg) == []

    fake.mode = "hang"  # Zeitüberschreitung: Lauf in ComfyUI abgebrochen, Ordner weg
    with pytest.raises(comfy.ComfyTimeout):
        llm.run_graph(cfg, _graph(), timeout_s=0.5)
    assert fake.cancelled and _left(cfg) == []
    # spätes Schreiben nach dem Interrupt: ohne weiteren Lauf entfernt, sobald der Auftrag endet
    for _ in range(50):
        if fake.late and not fake.running:
            break
        time.sleep(0.1)
    time.sleep(llm.LATE_POLL_S + 0.3)
    assert fake.late and not any(p.exists() for p in fake.late) and _left(cfg) == []


def test_abort_of_the_waiting_caller_cancels_and_cleans(ai, monkeypatch):
    """Abbruch (z. B. CancelledError/KeyboardInterrupt beim Warten): Lauf in ComfyUI beendet,
    Sitzungsordner gelöscht."""
    cfg, fake = ai
    fake.mode = "hang"
    real_wait = comfy.ComfyClient.wait

    def aborted_wait(self, *a, **k):
        time.sleep(0.2)
        raise KeyboardInterrupt

    monkeypatch.setattr(comfy.ComfyClient, "wait", aborted_wait)
    with pytest.raises(KeyboardInterrupt):
        llm.run_graph(cfg, _graph(), timeout_s=5)
    monkeypatch.setattr(comfy.ComfyClient, "wait", real_wait)
    assert len(fake.cancelled) == 1 and _left(cfg) == []


def test_restart_and_late_writes_are_swept(ai):
    """Neustart nach Absturz (Ordner ohne Sperre) und spätes Schreiben eines abgebrochenen Laufs
    in einen schon gelöschten Ordner: beides entfernt der Sweep; der Standardordner des Knotens
    ebenso."""
    cfg, _ = ai
    crashed = llm.session_root(cfg) / "crashed"
    crashed.mkdir(parents=True)
    (crashed / llm.LOCK_NAME).touch()
    (crashed / "df-1.json").write_text('{"turns": ["Kunde"]}')
    late = llm.session_root(cfg) / "late"  # vom Knoten nach dem Löschen neu angelegt, ohne Sperre
    late.mkdir()
    (late / "df-2.json").write_text("{}")
    default = cfg.instance("ai").folder("output") / llm.NODE_DEFAULT_DIR
    default.mkdir(parents=True)
    (default / "x.json").write_text("{}")
    assert llm.sweep(cfg) == 3 and _left(cfg) == []


def test_sweep_never_touches_an_active_run_of_another_process(ai):
    cfg, _ = ai
    run = llm.session_root(cfg) / "active"
    run.mkdir(parents=True)
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR);"
         " fcntl.flock(fd, fcntl.LOCK_EX); print('ok', flush=True); time.sleep(30)",
         str(run / llm.LOCK_NAME)],
        stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert holder.stdout.readline().strip() == "ok"
        assert llm.sweep(cfg) == 0 and run.is_dir()
    finally:
        holder.kill()
        holder.wait()
    assert llm.sweep(cfg) == 1 and not run.exists()  # nach dem „Absturz“ verwaist


def test_parallel_customers_keep_their_own_sessions(ai):
    """Parallele Läufe: je eigener Ordner und eigene Antwort; der Sweep nach einem Lauf löscht
    nie den noch laufenden anderen; danach bleibt nichts."""
    cfg, fake = ai
    results: dict[str, str] = {}
    errors: list[BaseException] = []

    def customer(name: str) -> None:
        try:
            out = llm.run_graph(cfg, _graph(f"Kunde {name}"), timeout_s=10)
            results[name] = out.texts["2"]
        except BaseException as exc:  # noqa: BLE001 – im Test sichtbar machen
            errors.append(exc)

    threads = [threading.Thread(target=customer, args=(str(i),)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert results == {str(i): f"Antwort auf: Kunde {i}" for i in range(8)}
    assert len({p.parent for p in fake.written}) == 8 and _left(cfg) == []


def test_cockpit_start_sweeps_orphaned_sessions(ai):
    """Neustart des Cockpits: verwaiste Sitzungsdateien sind nach dem Start entfernt."""
    from test_server import _run

    cfg, _ = ai
    orphan = llm.session_root(cfg) / "vor-dem-neustart"
    orphan.mkdir(parents=True)
    (orphan / "df-9.json").write_text('{"turns": ["Kundentext"]}')

    async def scenario(client, app, origin):
        assert not orphan.exists()

    _run(cfg, scenario)
