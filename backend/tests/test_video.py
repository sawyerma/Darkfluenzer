"""Langvideo (V0 §10): Gesamtlänge in Abschnitte zerlegt, jeder Folgeabschnitt startet mit dem
letzten Bild des vorigen, danach zusammengesetzt; Einstellungen beider Wan-Sampler über eine
Bindung; fertige Abschnitte überstehen Fehler und Wiederholung. Ersatz-ComfyUI über echtes HTTP."""

from __future__ import annotations

import io
import json
import re
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from darkfluenzer import comfy, models, pipeline, runtime
from darkfluenzer.config import project_root
from darkfluenzer.store import Store


class FakeComfy:
    """/prompt, /history, /queue, /view, /upload/image, /free, /system_stats wie ComfyUI 0.45."""

    def __init__(self, port: int) -> None:
        self.prompts: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}
        self.fail_at: int | None = None  # n-ter eingereichter Auftrag scheitert (1-basiert)
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body: object = None, raw: bytes | None = None) -> None:
                data = raw if raw is not None else json.dumps(body).encode()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/system_stats":
                    return self._send(200, {"system": {"ram_total": 1, "ram_free": 1}})
                if url.path.startswith("/history/"):
                    return self._send(200, fake.history(url.path.rsplit("/", 1)[1]))
                if url.path == "/queue":
                    return self._send(200, {"queue_running": [], "queue_pending": []})
                if url.path == "/view":
                    return self._send(200, raw=fake.files[parse_qs(url.query)["filename"][0]])
                self._send(404, {})

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/upload/image":
                    name = re.search(rb'filename="([^"]+)"', body).group(1).decode()
                    return self._send(200, {"name": name, "subfolder": "darkfluenzer"})
                if self.path == "/free":
                    return self._send(200, {})
                if self.path == "/prompt":
                    req = json.loads(body)
                    fake.prompts[req["prompt_id"]] = req["prompt"]
                    return self._send(200, {"prompt_id": req["prompt_id"], "node_errors": {}})
                self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def history(self, pid: str) -> dict:
        if pid not in self.prompts:
            return {}
        n = list(self.prompts).index(pid) + 1
        if n == self.fail_at:
            status = {"status_str": "error", "completed": False, "messages": [[
                "execution_error", {"node_id": "11", "node_type": "KSamplerAdvanced",
                                    "exception_message": "MPS OOM"}]]}  # fmt: skip
            return {pid: {"status": status, "outputs": {}}}
        graph = self.prompts[pid]
        outputs = {}
        for node_id, node in graph.items():
            if node["class_type"] in ("SaveVideo", "SaveImage"):
                ext = ".mp4" if node["class_type"] == "SaveVideo" else ".png"
                name = f"p{n}_{node_id}{ext}"
                self.files[name] = f"{pid}:{node_id}".encode()
                outputs[node_id] = {
                    "images": [{"filename": name, "subfolder": "", "type": "output"}]
                }
        return {pid: {"status": {"status_str": "success", "completed": True}, "outputs": outputs}}


@pytest.fixture
def video_cfg(cfg, monkeypatch):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    monkeypatch.setattr(runtime, "start", lambda cfg, name: None)  # Ersatz-ComfyUI läuft schon
    fake = FakeComfy(cfg.comfyui.port)
    yield cfg, fake
    fake.server.shutdown()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (9, 8, 7)).save(buf, "PNG")
    return buf.getvalue()


def test_video_plan_splits_seconds_into_segments(video_cfg):
    cfg, _ = video_cfg
    man = models.load_manifest(cfg.root)
    wf = man.workflows["wan22_i2v"]
    graph = comfy.load_graph(man, wf)
    plan = lambda **v: pipeline.video_plan(wf, graph, dict(v), 120.0)  # noqa: E731
    assert plan()["frames"] == [49]  # ohne Angabe: wie der geprüfte Graph (3 s bei 16 fps)
    assert plan(duration_s=30.0)["frames"] == [81] * 6  # 30 s = 6 Abschnitte à 5 s
    assert plan(duration_s=12.0)["frames"] == [81, 81, 33]
    assert plan(duration_s=10.0, segment_s=2.5)["frames"] == [41] * 4
    with pytest.raises(pipeline.PipelineError, match="erlaubt"):
        plan(duration_s=121.0)
    with pytest.raises(pipeline.PipelineError, match="höchstens 3.33 s bei 24 fps"):
        plan(duration_s=10.0, segment_s=5.0, fps=24.0)
    with pytest.raises(pipeline.PipelineError, match="nur bei Video"):
        pipeline.video_plan(man.workflows["krea2_turbo_t2i"], {}, {"duration_s": 3.0}, 120.0)


def test_one_setting_drives_both_wan_samplers(video_cfg):
    cfg, _ = video_cfg
    man = models.load_manifest(cfg.root)
    wf = man.workflows["wan22_i2v"]
    out = comfy.apply_params(
        comfy.load_graph(man, wf), wf,
        {"image": "x.png", "prompt": "p", "steps": 30, "switch_step": 15, "cfg": 3.5,
         "shift": 8.0, "sampler": "uni_pc", "scheduler": "beta"},
    )  # fmt: skip
    hi, lo = out["11"]["inputs"], out["12"]["inputs"]
    got = (hi["steps"], hi["end_at_step"], lo["steps"], lo["start_at_step"], lo["end_at_step"])
    assert got == (30, 15, 30, 15, 30)
    assert hi["cfg"] == lo["cfg"] == 3.5 and out["3"]["inputs"]["shift"] == 8.0
    assert hi["sampler_name"] == lo["sampler_name"] == "uni_pc" and lo["scheduler"] == "beta"
    with pytest.raises(comfy.ComfyError, match="kleiner"):
        comfy.apply_params(
            comfy.load_graph(man, wf), wf, {"image": "x", "prompt": "p", "switch_step": 30}
        )
    with pytest.raises(comfy.ComfyError, match="nicht in"):
        comfy.apply_params(
            comfy.load_graph(man, wf), wf, {"image": "x", "prompt": "p", "sampler": "x"}
        )


def test_long_video_segments_resume_after_failure_and_join(video_cfg):
    cfg, fake = video_cfg
    man = models.load_manifest(cfg.root)
    store = Store(cfg.local)
    start = pipeline.store_input(cfg, _png(), "start.png")
    no, (job,) = pipeline.create_order(
        store, man, "wan22_i2v", {"prompt": "Strand", "duration_s": 12.0}, {"image": start},
        count=1, video_max_s=120.0,
    )  # fmt: skip
    assert store.job(job)["params"]["video"]["frames"] == [81, 81, 33]
    fake.fail_at = 2  # zweiter Abschnitt scheitert (z. B. Speicher)
    with pytest.raises(comfy.ComfyError, match="MPS OOM"):
        pipeline.run_render(cfg, man, job)
    assert store.job(job)["status"] == "failed"
    assert [i for i, r in store.job_segments(job).items() if r["done_at"]] == [0]
    pipeline.advance_order(store, job)
    (retry,) = pipeline.retry_stage(
        store, man, no, 1, 3, {"request_id": str(uuid.uuid4()), "payload_sha": "0" * 64,
                               "command": "retry_stage", "status": "accepted"},
        video_max_s=120.0,
    )  # fmt: skip
    assert list(store.job_segments(retry)) == [0]  # fertiger Abschnitt übernommen
    fake.fail_at = None
    before = len(fake.prompts)
    pipeline.run_render(cfg, man, retry)
    graphs = list(fake.prompts.values())[before:]
    assert len(graphs) == 3  # Abschnitt 2 und 3 neu, dann Zusammensetzen – Abschnitt 1 nicht
    seg2, seg3, joined = graphs
    assert seg2["8"]["inputs"]["length"] == 81 and seg3["8"]["inputs"]["length"] == 33
    segs = store.job_segments(retry)  # Startbild = gesichertes letztes Bild des Vorgängers
    assert seg2["1"]["inputs"]["image"].endswith(segs[0]["last_frame"].rsplit("/", 1)[1])
    assert seg3["1"]["inputs"]["image"].endswith(segs[1]["last_frame"].rsplit("/", 1)[1])
    assert seg3[pipeline.LAST_FRAME]["inputs"]["batch_index"] == 32
    assert seg2["15"]["inputs"]["filename_prefix"].startswith(pipeline.WORK_PREFIX)
    loads = [n for n in joined.values() if n["class_type"] == "LoadVideo"]
    trims = [n["inputs"] for n in joined.values() if n["class_type"] == "ImageFromBatch"]
    assert len(loads) == 3 and [(t["batch_index"], t["length"]) for t in trims] == [
        (1, 80),
        (1, 32),
    ]
    assert joined["create"]["inputs"]["fps"] == 16.0
    done = store.job(retry)
    assert done["status"] == "done"
    media = store.db.execute("SELECT path FROM media WHERE job_id = ?", (retry,)).fetchall()
    assert len(media) == 1 and media[0][0].startswith("evaluation/")  # nur das fertige Video
    assert not any(pipeline.WORK_PREFIX in p for (p,) in store.db.execute("SELECT path FROM media"))
    store.close()


def test_ltx25_registration_binds_subgraph_nodes(video_cfg):
    """LTX 2.5: Bindungen an Untergraph-Knoten (IDs mit Doppelpunkt), Dev + Distilled-LoRA."""
    cfg, _ = video_cfg
    man = models.load_manifest(cfg.root)
    wf = man.workflows["ltx25_i2v"]
    assert wf.params["sampler"].also == (("398:341", "sampler_name"),)
    assert {"ltx25_dev_bf16", "ltx25_distilled_lora"} <= set(man.engines["ltx25"].files)
    out = comfy.apply_params(
        comfy.load_graph(man, wf), wf,
        {"image": "x.png", "prompt": "p", "duration": 8, "fps": 16, "sampler": "euler"},
    )  # fmt: skip
    assert (
        out["398:362"]["inputs"]["value"] == 8
        and out["398:341"]["inputs"]["sampler_name"] == "euler"
    )
    assert out["398:388"]["inputs"]["model"] == ["398:405", 0] == out["398:391"]["inputs"]["model"]
    with pytest.raises(comfy.ComfyError, match="nicht in"):
        comfy.apply_params(comfy.load_graph(man, wf), wf, {"image": "x", "prompt": "p", "fps": 25})
