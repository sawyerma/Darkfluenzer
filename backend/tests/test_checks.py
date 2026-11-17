"""SP3 Schritt 7: Gesichtsprüfung als ComfyUI-Knoten. Engine ``identity`` mit den drei Dateien
(BUG-091), Prüf-Workflow mit Referenzordner der Figur, Messwerte aus der ComfyUI-Historie je Medium
in ``media_checks`` und im EVENT job.completed; der Knoten selbst mit den echten Modellen."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from darkfluenzer.config import project_root
from darkfluenzer.media import models, pipeline
from darkfluenzer.nodes import comfy
from darkfluenzer.store import Store
from darkfluenzer.v1 import comfy_pb2
from darkfluenzer.web.mappers import _job_completed

VALUES = [{"check": "identity", "references": 3, "status": "ok", "sface": 0.71, "auraface": 0.64,
           "face_px": 180, "score": 0.9}]  # fmt: skip


@pytest.fixture
def setup(cfg):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    store = Store(cfg.local)
    yield cfg, store, models.load_manifest(cfg.root)
    store.close()


def test_identity_engine_and_check_workflow_in_the_registry(setup):
    _, _, man = setup
    assert man.engines["identity"].files == ("face_yunet", "face_sface", "face_auraface")
    wf = man.workflows["identity_check"]
    assert wf.identity == "2" and ("2", "reference_dir") in wf.runtime_inputs
    graph = comfy.load_graph(man, wf)
    assert graph["2"]["class_type"] == "DarkfluenzerFaceIdentity"
    assert set(models.IDENTITY_INPUTS) <= set(graph["2"]["inputs"])


def test_collect_reads_check_values_and_accepts_a_run_without_files(cfg, monkeypatch, tmp_path):
    entry = {"outputs": {"2": {comfy.CHECKS_KEY: [json.dumps(VALUES)]}}}
    monkeypatch.setattr(comfy.ComfyClient, "wait", lambda self, *a, **k: entry)
    monkeypatch.setattr(comfy.MemoryTrace, "sample", lambda self: None)
    base = comfy.RenderResult(
        prompt_id="p", workflow="identity_check", engine="identity", params={}
    )
    result = comfy.collect_graph(cfg.comfyui, "p", tmp_path, stem="s", timeout_s=5, base=base)
    assert result.outputs == [] and result.checks == [{**VALUES[0], "node": "2"}]
    entry["outputs"] = {"2": {comfy.CHECKS_KEY: ["kein json"]}}
    base = comfy.RenderResult(
        prompt_id="p", workflow="identity_check", engine="identity", params={}
    )
    with pytest.raises(comfy.ComfyError, match="unlesbar"):
        comfy.collect_graph(cfg.comfyui, "p", tmp_path, stem="s", timeout_s=5, base=base)


def test_check_job_uses_the_figures_reference_set_and_stores_values(setup, monkeypatch):
    cfg, store, man = setup
    store.save_character(0, 0, "Clara", "dfchar", "woman", "clara")
    image = cfg.local / "evaluation" / "probe.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (120, 80, 60)).save(image)
    media = store.add_media(
        "evaluation/probe.png", pipeline.sha256_file(image), image.stat().st_size
    )
    with pytest.raises(pipeline.PipelineError, match="Figur wählen"):
        pipeline.create_render(store, man, "identity_check", {}, {"image": "evaluation/probe.png"})
    job = pipeline.create_render(
        store, man, "identity_check", {}, {"image": "evaluation/probe.png"},
        parent_media_id=media, character="clara",
    )  # fmt: skip
    seen: dict = {}

    def run_workflow(cfg_, man_, key, values, dest, **kw):
        dest.mkdir(parents=True, exist_ok=True)  # wie collect_graph
        seen.update(kw["overrides"])
        return comfy.RenderResult(
            prompt_id="p1", workflow=key, engine="identity", params=values,
            checks=[{**VALUES[0], "node": "2"}],
        )  # fmt: skip

    monkeypatch.setattr(comfy.ComfyClient, "upload_image", lambda self, path: path.name)
    monkeypatch.setattr(comfy, "run_workflow", run_workflow)
    pipeline.run_render(cfg, man, job)
    assert seen[("2", "reference_dir")] == str(cfg.local / "characters" / "clara" / "reference")
    assert seen[("2", "min_face_px")] == cfg.identity.min_face_px
    assert seen[("2", "min_score")] == cfg.identity.min_score
    (check,) = store.media_checks(media)
    assert (check["check_name"], check["status"], check["reference"]) == ("identity", "ok", "clara")
    assert check["data"]["sface"] == 0.71 and check["job_id"] == job
    rows, _ = store.finished_jobs(0, 10)
    msg = comfy_pb2.JobCompleted.FromString(_job_completed(rows[-1], {}))
    assert msg.result == comfy_pb2.JOB_RESULT_DONE
    assert (msg.checks[0].status, round(msg.checks[0].auraface, 2)) == ("ok", 0.64)


def _node_module(face_dir: Path):
    """Den ComfyUI-Knoten mit einem Ersatz für ComfyUIs ``folder_paths`` laden."""
    fake = types.ModuleType("folder_paths")
    fake.get_full_path_or_raise = lambda folder, name: str(face_dir / name)
    fake.get_filename_list = lambda folder: []
    sys.modules["folder_paths"] = fake
    path = project_root() / "comfy_nodes" / "darkfluenzer" / "face.py"
    spec = importlib.util.spec_from_file_location("df_face_node", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Tensor(np.ndarray):
    """Kleinster Ersatz für ComfyUIs Bild-Tensor (``.cpu().numpy()``)."""

    def cpu(self):
        return self

    def numpy(self):
        return np.asarray(self)


def _images(*arrays: np.ndarray) -> _Tensor:
    return np.stack(arrays).astype(np.float32).view(_Tensor)


def test_face_node_with_the_real_models(tmp_path):
    """Echte Modelle (local/models/face): ohne Referenz „keine_referenz“, ohne Gesicht
    „kein_gesicht“, ein Gesicht gegen sich selbst ≈ 1. Fehlen die Modelle, wird übersprungen."""
    face_dir = models.models_dir(project_root()) / "face"
    names = (
        "opencv/face_detection_yunet_2023mar.onnx",
        "opencv/face_recognition_sface_2021dec.onnx",
        "auraface/glintr100.onnx",
    )
    if not all((face_dir / n).is_file() for n in names):
        pytest.skip("Gesichtsmodelle fehlen (models download --engine identity)")
    node = _node_module(face_dir).FaceIdentity()
    blank = _images(np.zeros((64, 64, 3)))
    (out,) = node.measure(blank, str(tmp_path / "leer"), *names, 64, 0.8)["result"]
    assert json.loads(out)[0]["status"] == "keine_referenz"
    sample = next(
        iter(sorted((project_root() / "local" / "evaluation").rglob("*_t2i_*.png"))), None
    )
    if sample is None:
        pytest.skip("kein erzeugtes Bild mit Gesicht vorhanden")
    refs = tmp_path / "ref"
    refs.mkdir()
    shutil.copy(sample, refs / "a.png")
    (out,) = node.measure(blank, str(refs), *names, 64, 0.8)["result"]
    assert json.loads(out)[0]["status"] in ("kein_gesicht", "keine_referenz")
    picture = _images(np.asarray(Image.open(sample).convert("RGB"), np.float32) / 255.0)
    (out,) = node.measure(picture, str(refs), *names, 64, 0.8)["result"]
    value = json.loads(out)[0]
    if value["status"] == "keine_referenz":
        pytest.skip("im erzeugten Bild ist kein Gesicht erkennbar")
    assert value["status"] == "ok" and value["sface"] > 0.99 and value["auraface"] > 0.99


def test_check_chain_is_injected_before_every_saved_image_but_the_mask(setup):
    """E16/E17: Prüfknoten zwischen Dekodieren und SaveImage; die Maske wird nicht geprüft, das
    gespeicherte Bild bleibt unverändert."""
    _, _, man = setup
    spec = man.checks["content"]
    for key in ("lustify_sdxl_t2i", "lustify_sam31_edit"):
        wf = man.workflows[key]
        graph = comfy.load_graph(man, wf)
        out = comfy.inject_checks(graph, wf, [(spec, {})])
        added = {k: v for k, v in out.items() if k not in graph}
        saves = [
            k for k, n in graph.items() if n["class_type"] == "SaveImage" and k != wf.mask_output
        ]
        assert sorted(comfy.check_targets(out).values()) == sorted(saves)
        for node in added.values():
            target = node["_meta"][comfy.CHECK_TARGET]
            assert node["class_type"] == "DarkfluenzerContentRating"
            assert node["inputs"]["image"] == graph[target]["inputs"]["images"]
            assert node["inputs"]["detector"] == "nudenet/640m.onnx"
        assert all(out[k] == graph[k] for k in graph)  # nichts am Bildweg geändert


def test_check_plan_needs_models_and_a_figure_for_identity(setup, monkeypatch):
    cfg, _, man = setup
    wf = man.workflows["lustify_sdxl_t2i"]
    # ohne Modelldateien (Testprojekt) nur die modellfreie technische Qualitätsprüfung
    assert [s.name for s, _ in pipeline.check_plan(cfg, man, wf, None)] == ["quality"]
    monkeypatch.setattr(models, "file_state", lambda mf, base: "present")
    assert [s.name for s, _ in pipeline.check_plan(cfg, man, wf, None)] == ["content", "quality"]
    lora = models.Lora(
        key="k", target="loras/characters/clara/k.safetensors", size=1, sha256="a" * 64,
        base_engine="lustify_sdxl", base_file=man.engines["lustify_sdxl"].files[0], dataset="d",
        trigger="dfchar", steps=1, rank=4, learning_rate=1e-4, strength=1.0, status="OFFEN",
        created_at="t", trainer="t", character="clara",
    )  # fmt: skip
    plan = dict((s.name, r) for s, r in pipeline.check_plan(cfg, man, wf, comfy.LoraUse(lora, "")))
    assert plan["identity"]["reference_dir"] == str(
        cfg.local / "characters" / "clara" / "reference"
    )
    for key in ("identity_check", "lustify_sdxl_lora_train", "sdpose_pose"):
        assert pipeline.check_plan(cfg, man, man.workflows[key], None) == []  # Analyse, Training


def test_check_values_land_on_the_checked_output(setup, monkeypatch):
    cfg, store, man = setup
    job = pipeline.create_render(store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {})
    content = {
        "check": "content",
        "status": "ok",
        "rating": "medium",
        "neutral": 0.01,
        "low": 0.02,
        "medium": 0.9,
        "high": 0.07,
        "regions": {"FEMALE_BREAST_EXPOSED": 0.36},
    }

    def run_workflow(cfg_, man_, key, values, dest, **kw):
        dest.mkdir(parents=True, exist_ok=True)
        image = dest / "out.png"
        Image.new("RGB", (40, 30), (1, 2, 3)).save(image)
        check_node = {"class_type": "X", "inputs": {}, "_meta": {comfy.CHECK_TARGET: "7"}}
        kw["on_submit"]("p1", {"7": {"class_type": "SaveImage", "inputs": {}}, "20": check_node})
        sha = pipeline.sha256_file(image)
        out = comfy.OutputFile(node="7", path=image, sha256=sha, size=image.stat().st_size)
        return comfy.RenderResult(
            prompt_id="p1", workflow=key, engine="lustify_sdxl", params=values, outputs=[out],
            checks=[{**content, "node": "20"}],
        )  # fmt: skip

    monkeypatch.setattr(comfy, "run_workflow", run_workflow)
    pipeline.run_render(cfg, man, job)
    media = store.job(job)["media_id"]
    (row,) = store.media_checks(media)
    assert (row["check_name"], row["data"]["save_node"], row["data"]["regions"]) == (
        "content", "7", {"FEMALE_BREAST_EXPOSED": 0.36},
    )  # fmt: skip
    rows, _ = store.finished_jobs(0, 10)
    msg = comfy_pb2.JobCompleted.FromString(_job_completed(rows[-1], {}))
    check = msg.checks[0]
    assert check.labels["rating"] == "medium" and round(check.values["medium"], 2) == 0.9
    assert round(check.values["regions.FEMALE_BREAST_EXPOSED"], 2) == 0.36


def test_quality_node_measures_blur_noise_and_clipping():
    """E17 Teil 1: Schärfe fällt bei Unschärfe, Rauschen wird in Grauwerten getroffen, Beschnitt
    zählt dunkle und helle Pixel."""
    import cv2

    path = project_root() / "comfy_nodes" / "darkfluenzer" / "quality.py"
    spec = importlib.util.spec_from_file_location("df_quality_node", path)
    quality = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quality)
    rng = np.random.default_rng(1)
    base = cv2.resize(
        rng.integers(0, 256, (64, 64), dtype=np.uint8), (512, 512), interpolation=cv2.INTER_CUBIC
    )
    sharp = quality.measure_gray(base)
    blurred = quality.measure_gray(cv2.GaussianBlur(base, (0, 0), 4))
    assert blurred["sharpness"] < sharp["sharpness"] / 5
    flat = np.full((256, 256), 128, np.uint8)
    noisy = np.clip(flat + rng.normal(0, 10, flat.shape), 0, 255).astype(np.uint8)
    assert quality.measure_gray(flat)["noise"] == 0.0
    assert abs(quality.measure_gray(noisy)["noise"] - 10) < 1.0
    clipped = flat.copy()
    clipped[:64] = 0
    clipped[64:96] = 255
    values = quality.measure_gray(clipped)
    assert values["clipped_dark"] == 0.25 and values["clipped_bright"] == 0.125
