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
    assert result.outputs == [] and result.checks == [{**VALUES[0], "node": "2", "item": 0}]
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
    package = types.ModuleType("df_nodes")  # Paket-Rahmen für ``from .memory import register``
    package.__path__ = []
    memory = types.ModuleType("df_nodes.memory")
    memory.register = lambda cache: cache
    sys.modules |= {"df_nodes": package, "df_nodes.memory": memory}
    path = project_root() / "comfy_nodes" / "darkfluenzer" / "face.py"
    spec = importlib.util.spec_from_file_location("df_nodes.face", path)
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
    plan = pipeline.check_plan(cfg, man, wf, None, {"prompt": "woman in a garden"})
    assert [s.name for s, _ in plan] == [
        "content", "quality", "quality_score", "prompt_fidelity", "hands",
    ]  # fmt: skip
    assert dict((s.name, r) for s, r in plan)["prompt_fidelity"] == {"prompt": "woman in a garden"}
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


def test_prompt_fidelity_splits_long_prompts():
    """VQAScore je Teil: kurze Prompts bleiben ganz, lange werden an Satz-/Kommagrenzen geteilt."""
    package = types.ModuleType("df_nodes")
    package.__path__ = []
    memory = types.ModuleType("df_nodes.memory")
    memory.register = lambda cache: cache
    fake = types.ModuleType("folder_paths")
    fake.get_filename_list = lambda folder: []
    mm = types.ModuleType("comfy.model_management")
    comfy_pkg = types.ModuleType("comfy")
    comfy_pkg.model_management = mm
    sys.modules |= {"df_nodes": package, "df_nodes.memory": memory, "folder_paths": fake,
                    "comfy": comfy_pkg, "comfy.model_management": mm}  # fmt: skip
    try:
        path = project_root() / "comfy_nodes" / "darkfluenzer" / "promptfidelity.py"
        spec = importlib.util.spec_from_file_location("df_nodes.promptfidelity", path)
        node = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(node)
    finally:
        for name in ("comfy", "comfy.model_management"):
            sys.modules.pop(name, None)
    assert node.parts_of("  a woman   in a garden ") == ["a woman in a garden"]
    assert node.parts_of("") == []
    long = ", ".join(f"detail number {i} of the scene" for i in range(20))
    parts = node.parts_of(long)
    assert len(parts) > 1 and all(len(p) <= node.MAX_PART_CHARS for p in parts)
    assert " ".join(parts).replace(", ", ",").count("detail number") == 20


def test_hand_node_anchors_and_crop_geometry():
    """Handprüfung: 2016 berechnete Anker wie die MediaPipe-Tabelle (Anfang, Ende); der Ausschnitt
    ist quadratisch, 2,6-mal die Handfläche und Richtung Finger verschoben, auch am Bildrand."""
    import cv2  # noqa: F401  (Knoten braucht OpenCV)

    package = types.ModuleType("df_nodes")
    package.__path__ = []
    memory = types.ModuleType("df_nodes.memory")
    memory.register = lambda cache: cache
    fake = types.ModuleType("folder_paths")
    fake.get_filename_list = lambda folder: []
    mm = types.ModuleType("comfy.model_management")
    comfy_pkg = types.ModuleType("comfy")
    comfy_pkg.model_management = mm
    sys.modules |= {"df_nodes": package, "df_nodes.memory": memory, "folder_paths": fake,
                    "comfy": comfy_pkg, "comfy.model_management": mm}  # fmt: skip
    try:
        pytest.importorskip("timm")
        path = project_root() / "comfy_nodes" / "darkfluenzer" / "hands.py"
        spec = importlib.util.spec_from_file_location("df_nodes.hands", path)
        hands = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hands)
    finally:
        for name in ("comfy", "comfy.model_management"):
            sys.modules.pop(name, None)
    anchors = hands.palm_anchors()
    assert anchors.shape == (2016, 2)
    assert np.allclose(anchors[0], [1 / 48, 1 / 48]) and np.allclose(
        anchors[-1], [23 / 24, 23 / 24]
    )
    image = np.zeros((400, 600, 3), np.uint8)
    box = np.array([100.0, 200.0, 140.0, 240.0])  # Handfläche 40 px
    marks = np.zeros((7, 2))
    marks[0], marks[2] = [120, 240], [120, 200]  # Finger zeigen nach oben
    crop = hands.hand_crop(image, box, marks)
    assert crop.shape[:2] == (104, 104)  # 2,6 × 40 px
    edge = hands.hand_crop(image, np.array([0.0, 0.0, 40.0, 40.0]), marks)
    assert edge.shape[:2] == (104, 104)  # am Rand mit Rand aufgefüllt


def test_video_checks_sample_frames_before_create_video(setup):
    """SP5 Schritt 7 (Video): Stichprobe vor CreateVideo, Prüfungen „frames“ auf der Stichprobe,
    zeitliche Konsistenz auf allen Frames; Ziel ist SaveVideo, der Videoweg bleibt gleich."""
    _, _, man = setup
    specs = [(man.checks[n], {}) for n in ("content", "temporal")]
    for key in ("wan22_i2v", "wan22_remix_v30_i2v", "ltx25_i2v", "ltx25_flf2v"):
        wf = man.workflows[key]
        graph = comfy.load_graph(man, wf)
        ((save, frames),) = comfy.video_saves(graph)
        out = comfy.inject_checks(graph, wf, specs, man.check_frames)
        added = {v["class_type"]: (k, v) for k, v in out.items() if k not in graph}
        sample_id, sample = added["DarkfluenzerFrameSample"]
        assert sample["inputs"] == {"image": frames, "every": 8, "max_frames": 12}
        assert added["DarkfluenzerContentRating"][1]["inputs"]["image"] == [sample_id, 0]
        assert added["DarkfluenzerTemporal"][1]["inputs"]["image"] == frames
        assert set(comfy.check_targets(out).values()) == {save}
        assert all(out[k] == graph[k] for k in graph)  # nichts am Videoweg geändert
    # ohne Prüfung auf der Stichprobe kein Stichprobenknoten
    wf = man.workflows["wan22_i2v"]
    graph = comfy.load_graph(man, wf)
    out = comfy.inject_checks(graph, wf, [(man.checks["temporal"], {})], man.check_frames)
    assert [v["class_type"] for k, v in out.items() if k not in graph] == ["DarkfluenzerTemporal"]


def test_check_plan_for_video_takes_frame_and_temporal_checks(setup, monkeypatch):
    cfg, _, man = setup
    wf = man.workflows["wan22_i2v"]
    assert [s.name for s, _ in pipeline.check_plan(cfg, man, wf, None)] == ["quality", "temporal"]
    monkeypatch.setattr(models, "file_state", lambda mf, base: "present")
    plan = [s.name for s, _ in pipeline.check_plan(cfg, man, wf, None, {"prompt": "p"})]
    assert plan == ["content", "quality", "temporal", "hands"]  # keine 8B/9B-VLM je Frame


def test_frame_sample_and_temporal_measures():
    """Stichprobe: jedes n-te und das letzte Frame, gleichmäßig ausgedünnt; zeitliche Konsistenz:
    ein Schnitt ist ein Sprung an seiner Stelle, unveränderte Frames zählen als Standbild."""
    path = project_root() / "comfy_nodes" / "darkfluenzer"
    loaded = {}
    for name in ("frames", "temporal"):
        spec = importlib.util.spec_from_file_location(f"df_{name}_node", path / f"{name}.py")
        loaded[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded[name])
    frames, temporal = loaded["frames"], loaded["temporal"]
    assert frames.frame_indices(81, 8, 12) == list(range(0, 81, 8))
    assert frames.frame_indices(81, 1, 5) == [0, 20, 40, 60, 80]
    assert frames.frame_indices(10, 4, 12) == [0, 4, 8, 9]
    assert frames.frame_indices(1, 8, 12) == [0] and frames.frame_indices(0, 8, 12) == []
    batch = np.arange(20, dtype=np.float32).reshape(20, 1, 1, 1) * np.ones((1, 4, 4, 3), np.float32)
    result = frames.FrameSample().sample(batch, 8, 12)
    (entry,) = json.loads(result["ui"]["darkfluenzer_checks"][0])
    assert entry == {"check": "frames", "status": "ok", "total": 20, "indices": [0, 8, 16, 19]}
    assert result["result"][0][:, 0, 0, 0].tolist() == [0, 8, 16, 19]

    rng = np.random.default_rng(3)
    a = rng.integers(0, 256, (64, 64), dtype=np.uint8)
    b = rng.integers(0, 256, (64, 64), dtype=np.uint8)
    cut = temporal.measure_frames([a] * 5 + [b] * 5, 4.0)
    assert (cut["jumps"], cut["max_step"], cut["frozen"], cut["frames"]) == (1, 4, 8, 10)
    smooth = temporal.measure_frames([np.roll(a, i, axis=1) for i in range(8)], 4.0)
    assert smooth["jumps"] == 0 and smooth["frozen"] == 0
    assert temporal.measure_frames([a], 4.0)["status"] == "zu_kurz"
