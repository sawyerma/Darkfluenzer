"""API-Client gegen einen Fake-ComfyUI-HTTP-Server (echte HTTP-Kommunikation, kein Mocking)."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from darkfluenzer.models import Param, Workflow
from darkfluenzer.nodes import comfy

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeComfy:
    """Simuliert /prompt, /history, /queue, /interrupt, /view. ``mode`` steuert das Verhalten."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.prompts: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.interrupted: list[str] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body: object, raw: bytes | None = None) -> None:
                data = raw if raw is not None else json.dumps(body).encode()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlparse(self.path)
                if fake.mode == "down":
                    return self._send(503, {})
                if url.path == "/system_stats":
                    return self._send(200, {"system": {"comfyui_version": "fake"}})
                if url.path.startswith("/history/"):
                    pid = url.path.rsplit("/", 1)[1]
                    return self._send(200, fake.history(pid))
                if url.path == "/queue":
                    running = [[0, p, {}, {}, []] for p in fake.prompts if fake.mode == "hang"]
                    return self._send(200, {"queue_running": running, "queue_pending": []})
                if url.path == "/view":
                    q = parse_qs(url.query)
                    assert q["filename"] == ["df_00001_.png"]
                    return self._send(200, None, raw=PNG)
                self._send(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                if self.path == "/prompt":
                    if fake.mode == "reject":
                        return self._send(
                            400,
                            {
                                "error": {"message": "Prompt outputs failed validation"},
                                "node_errors": {
                                    "1": {
                                        "class_type": "CheckpointLoaderSimple",
                                        "errors": [{"message": "Value not in list"}],
                                    }
                                },
                            },
                        )
                    try:  # wie ComfyUI 0.45.3: prompt_id muss eine gültige UUID sein
                        uuid.UUID(body["prompt_id"], version=4)
                        assert "-" in body["prompt_id"]
                    except (ValueError, AssertionError):
                        return self._send(400, {"error": "prompt_id must be a valid UUID"})
                    fake.prompts[body["prompt_id"]] = body["prompt"]
                    return self._send(200, {"prompt_id": body["prompt_id"], "node_errors": {}})
                if self.path == "/queue":
                    fake.deleted += body.get("delete", [])
                    return self._send(200, {})
                if self.path == "/interrupt":
                    fake.interrupted.append(body.get("prompt_id"))
                    return self._send(200, {})
                self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def history(self, pid: str) -> dict:
        if pid not in self.prompts or self.mode in ("hang", "lost"):
            return {}
        if self.mode == "exec_error":
            status = {
                "status_str": "error",
                "completed": False,
                "messages": [
                    [
                        "execution_error",
                        {"node_id": "3", "node_type": "KSampler", "exception_message": "MPS OOM"},
                    ]
                ],
            }
            return {pid: {"status": status, "outputs": {}}}
        out = {"9": {"images": [{"filename": "df_00001_.png", "subfolder": "", "type": "output"}]}}
        return {pid: {"status": {"status_str": "success", "completed": True}, "outputs": out}}


@pytest.fixture
def fake():
    f = FakeComfy()
    yield f
    f.server.shutdown()


WF = Workflow(
    key="t2i",
    title="Test",
    engine="e1",
    ui="x",
    api="y",
    status="OFFEN",
    enabled=True,
    params={
        "prompt": Param(node="2", input="text", type="str", required=True),
        "seed": Param(node="3", input="seed", type="int", min=0, max=2**32),
        "width": Param(node="4", input="width", type="int", min=512, max=2048, multiple_of=64),
    },
)
GRAPH = {
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "default"}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024}},
}


def test_apply_params_whitelist_and_ranges():
    out = comfy.apply_params(GRAPH, WF, {"prompt": "a portrait", "seed": 7, "width": 896})
    assert out["2"]["inputs"]["text"] == "a portrait" and out["3"]["inputs"]["seed"] == 7
    assert GRAPH["2"]["inputs"]["text"] == "default", "Original darf nicht verändert werden"
    with pytest.raises(comfy.ComfyError, match="Nicht freigegebene"):
        comfy.apply_params(GRAPH, WF, {"prompt": "x", "ckpt_name": "evil.safetensors"})
    with pytest.raises(comfy.ComfyError, match="Pflichtparameter"):
        comfy.apply_params(GRAPH, WF, {"seed": 1})
    with pytest.raises(comfy.ComfyError, match="Vielfaches"):
        comfy.apply_params(GRAPH, WF, {"prompt": "x", "width": 900})
    with pytest.raises(comfy.ComfyError, match="Maximum"):
        comfy.apply_params(GRAPH, WF, {"prompt": "x", "seed": 2**40})
    with pytest.raises(comfy.ComfyError, match="int erwartet"):
        comfy.apply_params(GRAPH, WF, {"prompt": "x", "seed": True})


def test_submit_wait_fetch(fake):
    client = comfy.ComfyClient(fake.url)
    assert client.ready()
    pid = client.submit(GRAPH)
    assert fake.prompts[pid] == GRAPH
    entry = client.wait(pid, timeout_s=5, poll_s=0.05)
    image = entry["outputs"]["9"]["images"][0]
    assert client.fetch(image) == PNG


def test_rejected_workflow_reports_node_errors(fake):
    fake.mode = "reject"
    with pytest.raises(comfy.ComfyError, match="Value not in list") as exc:
        comfy.ComfyClient(fake.url).submit(GRAPH)
    assert "1" in exc.value.details["node_errors"]


def test_execution_error_is_raised(fake):
    fake.mode = "exec_error"
    client = comfy.ComfyClient(fake.url)
    pid = client.submit(GRAPH)
    with pytest.raises(comfy.ComfyError, match="KSampler.*MPS OOM"):
        client.wait(pid, timeout_s=5, poll_s=0.05)


def test_timeout_interrupts_only_own_prompt(fake):
    fake.mode = "hang"
    client = comfy.ComfyClient(fake.url)
    pid = client.submit(GRAPH)
    with pytest.raises(comfy.ComfyTimeout):
        client.wait(pid, timeout_s=0.3, poll_s=0.05)
    assert fake.interrupted == [pid]


def test_wait_without_deadline_survives_long_run(fake):
    """Ohne Frist kein Abbruch wegen der Dauer: läuft der Auftrag länger als die Toleranz, wird
    trotzdem gewartet, solange ComfyUI ihn in der Warteschlange führt."""
    fake.mode = "hang"
    client = comfy.ComfyClient(fake.url)
    pid = client.submit(GRAPH)
    threading.Timer(0.6, lambda: setattr(fake, "mode", "ok")).start()
    entry = client.wait(pid, timeout_s=None, poll_s=0.05, lost_after_s=0.2)
    assert entry["status"]["completed"] and fake.interrupted == []


def test_wait_without_deadline_stops_when_prompt_is_lost(fake):
    fake.mode = "lost"  # weder in der Warteschlange noch im Verlauf
    client = comfy.ComfyClient(fake.url)
    pid = client.submit(GRAPH)
    with pytest.raises(comfy.ComfyError, match="weder in der Warteschlange"):
        client.wait(pid, timeout_s=None, poll_s=0.05, lost_after_s=0.2)


def test_wait_without_deadline_keeps_waiting_while_comfy_is_unreachable(fake):
    """Verbindungsverlust ist ein unbekannter Zustand, kein Fehler: auch weit über die Toleranz
    hinaus wird gewartet und nach der Wiederverbindung abgeglichen."""
    fake.mode = "down"  # jede Abfrage antwortet mit HTTP 503
    client = comfy.ComfyClient(fake.url, timeout=1)
    pid = client.submit(GRAPH)
    threading.Timer(0.8, lambda: setattr(fake, "mode", "ok")).start()
    entry = client.wait(pid, timeout_s=None, poll_s=0.05, lost_after_s=0.2)
    assert entry["status"]["completed"] and fake.interrupted == []
    with pytest.raises(ValueError):
        client.wait(pid, timeout_s=None)


def test_unreachable_server_is_reported():
    client = comfy.ComfyClient("http://127.0.0.1:9", timeout=1)
    assert client.ready() is False
    with pytest.raises(comfy.ComfyError, match="nicht erreichbar"):
        client.submit(GRAPH)
