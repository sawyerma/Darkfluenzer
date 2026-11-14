"""Registry-Vertrag: echtes Manifest muss gültig sein; Fehler im Manifest werden abgewiesen."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from darkfluenzer import models

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_manifest_is_valid():
    man = models.load_manifest(REPO_ROOT)
    assert "flux3_klein_base" in man.engines
    # gemeinsam genutzte Dateien existieren nur einmal (Dedupe über SHA-256 im Loader erzwungen)
    assert man.engines["flux2_dev"].files[-1] == man.engines["flux3_klein_base"].files[-1]
    for eng in man.engines.values():
        assert eng.usage == "evaluation" or all(v == "PASS" for v in eng.gates.values())


def _mini(tmp_path: Path, extra: str = "", content: bytes = b"weights") -> Path:
    (tmp_path / "workflows").mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / "workflows" / "manifest.toml").write_text(
        f"""
schema = 1
reserve_gb = 0
[roles]
image_master = ""
[engines.e1]
title = "E1"
kind = "image"
role = "master"
arch = "sdxl"
precision = "fp16"
wave = 1
files = ["f1"]
license = "x"
usage = "evaluation"
gates = {{ load = "OFFEN", render = "OFFEN", quality = "OFFEN", license_pass = "OFFEN" }}
[files.f1]
repo = "org/repo"
revision = "{"a" * 40}"
source = "model.safetensors"
target = "checkpoints/fam/model.safetensors"
size = {len(content)}
sha256 = "{sha}"
{extra}
"""
    )
    return tmp_path


def test_status_orphans_verify(tmp_path):
    root = _mini(tmp_path)
    man = models.load_manifest(root)
    base = models.models_dir(root)
    assert models.status(man, base)["engines"]["e1"]["ready"] is False
    target = base / "checkpoints" / "fam" / "model.safetensors"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"weights")
    (base / "checkpoints" / "fam" / "alt.safetensors").write_bytes(b"x")
    st = models.status(man, base)["engines"]["e1"]
    assert st["ready"] is True and st["files"] == {"f1": "present"}
    assert models.orphans(man, base) == ["checkpoints/fam/alt.safetensors"]
    assert models.verify(man, base, ["f1"]) == {"f1": "ok"}
    target.write_bytes(b"WEIGHTS")  # gleiche Größe, anderer Inhalt
    assert models.verify(man, base, ["f1"]) == {"f1": "MISMATCH"}


def test_production_requires_all_gates(tmp_path):
    root = _mini(tmp_path)
    path = root / "workflows" / "manifest.toml"
    path.write_text(path.read_text().replace('usage = "evaluation"', 'usage = "production"'))
    with pytest.raises(models.ManifestError, match="production"):
        models.load_manifest(root)


def test_role_must_point_to_production_engine(tmp_path):
    root = _mini(tmp_path)
    path = root / "workflows" / "manifest.toml"
    path.write_text(path.read_text().replace('image_master = ""', 'image_master = "e1"'))
    with pytest.raises(models.ManifestError, match="Produktions-Engine"):
        models.load_manifest(root)


def test_duplicate_file_content_rejected(tmp_path):
    root = _mini(tmp_path)
    path = root / "workflows" / "manifest.toml"
    text = path.read_text()
    block = text[text.index("[files.f1]") :]
    path.write_text(
        text
        + block.replace("[files.f1]", "[files.f2]").replace("checkpoints/fam/", "checkpoints/x/")
    )
    with pytest.raises(models.ManifestError, match="dieselbe Datei"):
        models.load_manifest(root)


def _with_workflow(root: Path, graph: dict, params: str) -> None:
    wf = root / "workflows" / "image"
    wf.mkdir(exist_ok=True)
    (wf / "e1.api.json").write_text(json.dumps(graph))
    (wf / "e1.ui.json").write_text("{}")
    path = root / "workflows" / "manifest.toml"
    path.write_text(
        path.read_text()
        + '[workflows.e1_t2i]\nengine = "e1"\nui = "image/e1.ui.json"\napi = "image/e1.api.json"\n'
        + f'status = "OFFEN"\n{params}'
    )


GRAPH = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "fam/model.safetensors"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "x", "clip": ["1", 1]}},
}


def test_workflow_params_validated_against_graph(tmp_path):
    root = _mini(tmp_path)
    _with_workflow(
        root,
        GRAPH,
        '[workflows.e1_t2i.params]\nprompt = { node = "2", input = "text", type = "str" }\n',
    )
    man = models.load_manifest(root)
    assert man.workflows["e1_t2i"].params["prompt"].node == "2"

    root2 = _mini(tmp_path / "b")
    _with_workflow(
        root2,
        GRAPH,
        '[workflows.e1_t2i.params]\nprompt = { node = "9", input = "text", type = "str" }\n',
    )
    with pytest.raises(models.ManifestError, match="fehlt im API-Graph"):
        models.load_manifest(root2)


def test_workflow_must_only_load_engine_files(tmp_path):
    root = _mini(tmp_path)
    graph = json.loads(json.dumps(GRAPH))
    graph["1"]["inputs"]["ckpt_name"] = "other/foreign.safetensors"
    _with_workflow(root, graph, "")
    with pytest.raises(models.ManifestError, match="nicht zur Engine"):
        models.load_manifest(root)


def test_select_orders_smallest_remaining_engine_first(tmp_path):
    man = models.load_manifest(REPO_ROOT)
    keys = models.select(man, wave=1, base=tmp_path)
    first_engine = {"lustify_v20", "realcore_illustrious_v10"}
    assert set(keys[:2]) == first_engine
    assert len(keys) == len(set(keys))
    with pytest.raises(models.ModelError):
        models.select(man, engines=["gibt_es_nicht"])


def test_download_verifies_hash_and_never_keeps_bad_file(tmp_path, monkeypatch):
    root = _mini(tmp_path)
    man = models.load_manifest(root)
    base = models.models_dir(root)
    payload = {"data": b"corrupt"}

    def fake_download(repo_id, filename, revision, local_dir):
        p = Path(local_dir) / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(payload["data"])
        return str(p)

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_download)
    assert models.download(man, base, ["f1"]) == {"f1": "MISMATCH"}
    assert not (base / "checkpoints/fam/model.safetensors").exists()
    payload["data"] = b"weights"
    assert models.download(man, base, ["f1"]) == {"f1": "downloaded"}
    assert (base / "checkpoints/fam/model.safetensors").read_bytes() == b"weights"
    assert not (base / models.STAGING / "f1").exists()
    assert models.download(man, base, ["f1"]) == {"f1": "present"}
    shutil.rmtree(base)


def test_download_refuses_without_disk_reserve(tmp_path):
    root = _mini(tmp_path)
    path = root / "workflows" / "manifest.toml"
    path.write_text(path.read_text().replace("reserve_gb = 0", "reserve_gb = 1000000"))
    man = models.load_manifest(root)
    with pytest.raises(models.ModelError, match="Zu wenig Speicher"):
        models.download(man, models.models_dir(root), ["f1"])
