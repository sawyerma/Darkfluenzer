"""Ein-Ordner-Datensatz: Prüfung, Dubletten, unfertige Kopien, Versionierung, Originale."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from darkfluenzer import training


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


def _folders(photos: Path) -> training.Folders:
    return training.Folders(photos, photos.parent / "dataset")


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
    status = {p.name: p.status for p in training.scan(photos)}
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
        training.build_dataset(_folders(photos))


def test_dataset_is_versioned_and_leaves_originals_untouched(tmp_path, photos):
    srcs = [_img(photos / f"{i}.png", 1200 + 40 * i, 1600, i) for i in range(4)]
    before = {p.name: p.read_bytes() for p in srcs}
    folders = _folders(photos)
    ds = training.build_dataset(folders, min_images=4)
    meta = json.loads((ds / "dataset.json").read_text())
    assert len(meta["items"]) == 4 and ds.name == f"ds_{meta['id']}"
    for item in meta["items"]:
        w, h = Image.open(ds / item["file"]).size
        assert (w, h) == tuple(reversed(item["target_size"])) and (w, h) in training.BUCKETS
        assert item["caption"] == "photo of dfchar woman"
    assert {p.name: p.read_bytes() for p in srcs} == before, "Originale dürfen sich nie ändern"
    assert training.build_dataset(folders, min_images=4) == ds, "gleiche Menge = gleiche Version"
    _img(photos / "neu.png", 1024, 1024, 99)
    assert training.build_dataset(folders, min_images=4) != ds, "neue Bilder = neue Version"


def test_bucket_picks_nearest_aspect():
    assert training.bucket(1000, 1000) == (1024, 1024)
    assert training.bucket(3000, 4000) == (896, 1152)
    assert training.bucket(4000, 3000) == (1152, 896)
    assert training.bucket(1080, 1920) == (768, 1344)
