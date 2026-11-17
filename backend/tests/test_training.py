"""Ein-Ordner-Datensatz: Prüfung, Dubletten, unfertige Kopien, Versionierung, Originale."""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from darkfluenzer.config import TrainingConfig
from darkfluenzer.media import training


def _img(path: Path, w: int, h: int, seed: int) -> Path:
    rng = np.random.default_rng(seed)
    Image.fromarray(rng.integers(0, 256, (h, w, 3), dtype=np.uint8)).save(path)
    old = time.time() - 60  # "fertig kopiert"
    os.utime(path, (old, old))
    return path


@pytest.fixture
def photos(tmp_path: Path) -> Path:
    folder = tmp_path / "character" / "photos"
    folder.mkdir(parents=True)
    return folder


RULES = TrainingConfig(
    min_side=768, recommended_side=1024, min_images=15, settle_s=10.0,
    suffixes=(".jpg", ".jpeg", ".png", ".webp"),
)  # fmt: skip


def _folders(photos: Path) -> training.Folders:
    root = photos.parent
    return training.Folders(photos, root / "reference", root / "dataset", root / "training")


def test_scan_classifies_every_file(tmp_path, photos):
    _img(photos / "a.png", 1024, 1024, 1)
    _img(photos / "b.jpg", 1200, 1600, 2)
    (photos / "dup.png").write_bytes((photos / "a.png").read_bytes())
    os.utime(photos / "dup.png", (time.time() - 60,) * 2)
    _img(photos / "klein.png", 512, 512, 3)
    (photos / "kaputt.png").write_bytes(b"kein bild")
    os.utime(photos / "kaputt.png", (time.time() - 60,) * 2)
    (photos / "notiz.txt").write_text("x")
    Image.new("RGB", (1024, 1024)).save(photos / "frisch.png")  # gerade erst kopiert
    status = {p.name: p.status for p in training.scan(photos, RULES)}
    assert status == {
        "a.png": "ok",
        "b.jpg": "ok",
        "dup.png": "duplicate",
        "klein.png": "too_small",
        "kaputt.png": "unreadable",
        "notiz.txt": "unsupported",
        "frisch.png": "incomplete",
    }


def test_dataset_requires_minimum(tmp_path, photos):
    _img(photos / "a.png", 1024, 1024, 1)
    with pytest.raises(training.DatasetIncomplete, match="1 geeignete"):
        training.build_dataset(_folders(photos), RULES, "dfchar", "woman")


def test_dataset_is_versioned_and_leaves_originals_untouched(tmp_path, photos):
    srcs = [_img(photos / f"{i}.png", 1200 + 40 * i, 1600, i) for i in range(4)]
    before = {p.name: p.read_bytes() for p in srcs}
    folders = _folders(photos)
    ds = training.build_dataset(
        folders, dataclasses.replace(RULES, min_images=4), "dfchar", "woman"
    )
    meta = json.loads((ds / "dataset.json").read_text())
    assert len(meta["items"]) == 4 and ds.name == f"ds_{meta['id']}"
    for item in meta["items"]:
        w, h = Image.open(ds / item["file"]).size
        assert (w, h) == tuple(reversed(item["target_size"])) and (w, h) in training.BUCKETS
        assert item["caption"] == "photo of dfchar woman"
    assert {p.name: p.read_bytes() for p in srcs} == before, "Originale dürfen sich nie ändern"
    assert (
        training.build_dataset(folders, dataclasses.replace(RULES, min_images=4), "dfchar", "woman")
        == ds
    ), "gleiche Menge = gleiche Version"
    _img(photos / "neu.png", 1024, 1024, 99)
    assert (
        training.build_dataset(folders, dataclasses.replace(RULES, min_images=4), "dfchar", "woman")
        != ds
    ), "neue Bilder = neue Version"


def test_bucket_picks_nearest_aspect():
    assert training.bucket(1000, 1000) == (1024, 1024)
    assert training.bucket(3000, 4000) == (896, 1152)
    assert training.bucket(4000, 3000) == (1152, 896)
    assert training.bucket(1080, 1920) == (768, 1344)


def test_captions_from_txt_and_dataset_id_covers_trigger_class_captions(tmp_path, photos):
    """SP3 Schritt 2: gleichnamige .txt ist die Beschriftung; Trigger, Klasse und Beschriftungen
    bestimmen die Datensatz-ID; die .txt erscheint nicht als ungeeignete Datei."""
    import json

    rules = dataclasses.replace(RULES, min_images=4)
    folders = _folders(photos)
    for i in range(4):
        Image.new("RGB", (1024, 1024), (i * 50, 9, 9)).save(photos / f"p{i}.png")
        os.utime(photos / f"p{i}.png", (1, 1))
    (photos / "p0.txt").write_text("am Strand, Abendlicht")
    (photos / "p1.txt").write_text("clara01 woman im Café")
    os.utime(photos / "p0.txt", (1, 1))
    os.utime(photos / "p1.txt", (1, 1))
    assert all(p.status == "ok" for p in training.scan(photos, rules))
    ds = training.build_dataset(folders, rules, "clara01", "woman")
    caps = {
        i["source"]: i["caption"] for i in json.loads((ds / "dataset.json").read_text())["items"]
    }
    assert caps["p0.png"] == "photo of clara01 woman, am Strand, Abendlicht"
    assert caps["p1.png"] == "clara01 woman im Café"  # Trigger schon drin: unverändert
    assert caps["p2.png"] == "photo of clara01 woman"
    assert training.build_dataset(folders, rules, "clara01", "girl") != ds  # Klasse zählt
    assert training.build_dataset(folders, rules, "mia01", "woman") != ds  # Trigger zählt
    (photos / "p2.txt").write_text("neu beschriftet")
    os.utime(photos / "p2.txt", (1, 1))
    assert training.build_dataset(folders, rules, "clara01", "woman") != ds  # Beschriftung zählt


def test_checkpoint_folder_per_figure_dataset_and_settings(cfg):
    """SP3 Schritt 3: derselbe Ordner für dieselbe Figur, denselben Datensatz und dieselben
    Einstellungen (fehlende aus dem Graphen), unabhängig von Gesamtschritten und Abstand; andere
    Einstellungen bekommen einen eigenen Ordner. Der Trainingsknoten bekommt ihn als Eingang."""
    import shutil

    from darkfluenzer.config import project_root
    from darkfluenzer.media import models, pipeline
    from darkfluenzer.nodes import comfy

    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    man = models.load_manifest(cfg.root)
    wf = man.workflows["lustify_sdxl_lora_train"]
    ds = "characters/clara/datasets/ds_abc"
    seed = comfy.load_graph(man, wf)[wf.params["seed"].node]["inputs"]["seed"]
    first = pipeline.checkpoint_dir(cfg, man, wf, ds, {"steps": 1500})
    assert first.parent == cfg.local / "characters" / "clara" / "training"
    assert first.name.startswith("ds_abc_")
    assert pipeline.checkpoint_dir(cfg, man, wf, ds, {"steps": 300, "seed": seed}) == first
    assert pipeline.checkpoint_dir(cfg, man, wf, ds, {"checkpoint_every": 5}) == first
    assert pipeline.checkpoint_dir(cfg, man, wf, ds, {"seed": seed + 1}) != first
    assert pipeline.checkpoint_dir(cfg, man, wf, ds, {"rank": 32}) != first
    with pytest.raises(pipeline.PipelineError, match="Charakterschema"):
        pipeline.checkpoint_dir(cfg, man, wf, "datasets/ds_abc", {})
    assert wf.train_checkpoint and (wf.train_checkpoint, "checkpoint_dir") in wf.runtime_inputs
    node = comfy.load_graph(man, wf)[wf.train_checkpoint]
    assert node["class_type"] == "DarkfluenzerTrainLora" and "checkpoint_every" in node["inputs"]


def test_checkpoints_appear_with_their_training_job(cfg):
    """SP3 Schritt 3: der STATE characters nennt je Lauf den letzten Checkpoint (Schritt, Gesamt,
    Verlust) und den Trainingsjob, den Fortsetzen/Beenden wiederholen."""
    import asyncio

    from test_server import _run

    from darkfluenzer.media import pipeline
    from darkfluenzer.v1 import character_pb2
    from darkfluenzer.v1 import stream_pb2 as spb
    from darkfluenzer.web import http as server

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        slug = cockpit.store.character(1)["slug"]
        wf = cockpit.manifest.workflows["lustify_sdxl_lora_train"]
        params = {"dataset": f"characters/{slug}/datasets/ds_x", "steps": 400, "seed": 7}
        job = cockpit.store.create_job(
            None, wf.engine, wf.key, "", params, [7], priority="training"
        )
        folder = pipeline.checkpoint_dir(cfg, cockpit.manifest, wf, params["dataset"], params)
        folder.mkdir(parents=True)
        status = {"step": 200, "total": 400, "file": "checkpoint_00000200.pt", "loss": 0.125,
                  "saved_at": 1794944000.5}  # fmt: skip
        (folder / "checkpoint.json").write_text(json.dumps(status))
        (folder.parent / "kaputt").mkdir()
        (folder.parent / "kaputt" / "checkpoint.json").write_text("{")  # unlesbar: entfällt
        await cockpit.refresh_characters()
        payload = app[server.HUB_KEY]._states[spb.TOPIC_CHARACTERS].payload
        char = next(
            c for c in character_pb2.Characters.FromString(payload).characters if c.id == "1"
        )
        (cp,) = char.checkpoints
        assert (cp.run, cp.step, cp.total, cp.job_id, cp.workflow) == (
            folder.name, 200, 400, job, wf.key,
        )  # fmt: skip
        assert round(cp.loss, 3) == 0.125 and cp.saved_ms == 1794944000500
        await asyncio.sleep(0)

    _run(cfg, scenario)
