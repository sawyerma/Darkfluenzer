"""Registry-Vertrag: echtes Manifest muss gültig sein; Fehler im Manifest werden abgewiesen."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from darkfluenzer.config import project_root
from darkfluenzer.media import models

REPO_ROOT = project_root()


def test_repository_manifest_is_valid():
    man = models.load_manifest(REPO_ROOT)
    assert "flux3_klein_base" in man.engines
    # gemeinsam genutzte Dateien existieren nur einmal (Dedupe über SHA-256 im Loader erzwungen)
    assert man.engines["wan22_i2v"].files[-2:] == man.engines["wan22_remix_v30"].files[-2:]
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
    wave = [e for e in man.engines.values() if e.wave == 1]
    assert len(keys) == len(set(keys))
    assert set(keys) == {f for e in wave for f in e.files}
    smallest = min(wave, key=lambda e: sum(man.files[f].size for f in e.files))
    assert keys[: len(smallest.files)] == list(smallest.files)
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


def test_mask_output_must_be_a_save_node_of_the_graph(tmp_path):
    """Die im Graphen erzeugte Maske (Pixelprüfung) muss ein SaveImage-Ausgang sein."""
    graph = {
        **GRAPH,
        "3": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "m"}},
    }
    image = '[workflows.e1_t2i.params]\nimage = { node = "3", input = "image", type = "str" }\n'
    root = _mini(tmp_path)
    _with_workflow(root, graph, 'mask_output = "4"\n' + image)
    assert models.load_manifest(root).workflows["e1_t2i"].mask_output == "4"

    root2 = _mini(tmp_path / "b")
    _with_workflow(root2, graph, 'mask_output = "2"\n' + image)
    with pytest.raises(models.ManifestError, match="kein SaveImage"):
        models.load_manifest(root2)


def test_engine_formats_must_fit_every_workflow(tmp_path):
    """BUG-093: Wan hat benannte Formate wie LTX; ein Format außerhalb der Grenzen oder des Rasters
    eines Workflows wird bei der Registrierung abgewiesen."""
    import shutil

    from darkfluenzer.config import project_root

    shutil.copytree(project_root() / "workflows", tmp_path / "workflows")
    man = models.load_manifest(tmp_path)
    for engine in ("wan22_i2v", "wan22_remix_v30"):
        assert set(man.engines[engine].formats) == set(man.engines["ltx25"].formats)
    wf = man.workflows["wan22_i2v"]
    assert models.format_problems(wf, man.engines["wan22_i2v"].formats) == []
    probs = models.format_problems(wf, {"zu breit": (1296, 720), "schief": (1000, 720)})
    assert any("zu breit" in p and "außerhalb" in p for p in probs)
    assert any("schief" in p and "Vielfaches" in p for p in probs)


def test_local_registry_holds_loras_and_switches(tmp_path):
    """SP3 Schritt 4 (BUG-092, BUG-094): Schalter und LoRAs nur in local/registry.toml, das
    versionierte Manifest bleibt unverändert; eine LoRA lädt nur auf ihrer Trainings-Engine und
    auf ausdrücklich eingetragenen Engines."""
    shutil.copytree(project_root() / "workflows", tmp_path / "workflows")
    manifest = (tmp_path / "workflows" / "manifest.toml").read_bytes()
    man = models.set_workflow_enabled(tmp_path, "lustify_sdxl_t2i", False)
    assert man.workflows["lustify_sdxl_t2i"].enabled is False
    assert (tmp_path / "workflows" / "manifest.toml").read_bytes() == manifest
    assert "enabled = false" in (tmp_path / "local" / "registry.toml").read_text()
    lora = models.Lora(
        key="ds_x_r16_s10_t", target="loras/characters/clara/ds_x.safetensors", size=1,
        sha256="a" * 64, base_engine="krea2_raw", base_file=man.engines["krea2_raw"].files[0],
        dataset="ds_x", trigger="clara01", steps=10, rank=16, learning_rate=1e-4, strength=1.0,
        status="OFFEN", created_at="t", trainer="ComfyUI TrainLoraNode", character="clara",
        compatible=("krea2_turbo",),
    )  # fmt: skip
    man = models.register_lora(tmp_path, lora)
    assert man.loras["ds_x_r16_s10_t"].character == "clara"
    assert (tmp_path / "workflows" / "manifest.toml").read_bytes() == manifest
    names = lambda engine: models.engine_model_names(man.files, man.engines, man.loras, engine)  # noqa: E731
    assert lora.comfy_name in names("krea2_raw") and lora.comfy_name in names("krea2_turbo")
    assert lora.comfy_name not in names("lustify_sdxl")
    # ungültiger Eintrag -> lokale Registry bleibt unverändert
    registry = (tmp_path / "local" / "registry.toml").read_bytes()
    bad = dataclasses.replace(lora, key="ds_y", compatible=("gibt_es_nicht",))
    with pytest.raises(models.ManifestError, match="gibt_es_nicht unbekannt"):
        models.register_lora(tmp_path, bad)
    assert (tmp_path / "local" / "registry.toml").read_bytes() == registry
    # Löschen nimmt den Schalter mit; eine neue Kopie unter gleichem Schlüssel ist aktiviert
    man, copy = models.create_workflow(tmp_path, "lustify_sdxl_t2i", "Kopie Test")
    models.set_workflow_enabled(tmp_path, copy, False)
    models.delete_workflow(tmp_path, copy)
    assert copy not in (tmp_path / "local" / "registry.toml").read_text()
    man, again = models.create_workflow(tmp_path, "lustify_sdxl_t2i", "Kopie Test")
    assert again == copy and man.workflows[copy].enabled is True
    # versioniertes Manifest mit Schalter -> klare Ablehnung
    text = manifest.decode().replace(
        'title = "LUSTIFY · Text zu Bild"\n',
        'title = "LUSTIFY · Text zu Bild"\nenabled = true\n',
        1,
    )
    with pytest.raises(models.ManifestError, match="gehört nach local/registry.toml"):
        models.load_manifest(tmp_path, text=text)


def test_explicit_duplicate_file_is_allowed_and_copied(tmp_path):
    """Gleiche Konfiguration in zwei Modellordnern: nur mit ``duplicate_of`` erlaubt; der Download
    kopiert sie aus dem vorhandenen Ziel statt sie erneut zu laden."""
    shutil.copytree(project_root() / "workflows", tmp_path / "workflows")
    man = models.load_manifest(tmp_path)
    dup = man.files["qwen3vl8b_preprocessor_config"]
    twin = man.files[dup.duplicate_of]
    base = tmp_path / "models"
    src = base / twin.target
    src.parent.mkdir(parents=True)
    data = project_root() / "local" / "models" / twin.target
    if not data.is_file():
        pytest.skip("Vorlage der Datei fehlt (models download --engine quality_vlm)")
    src.write_bytes(data.read_bytes())
    assert models.download(man, base, [dup.key]) == {dup.key: "copied"}
    assert (base / dup.target).read_bytes() == data.read_bytes()
    text = (tmp_path / "workflows" / "manifest.toml").read_text()
    text = text.replace('duplicate_of = "qrealign_preprocessor"\n', "", 1)
    with pytest.raises(models.ManifestError, match="dieselbe Datei"):
        models.load_manifest(tmp_path, text=text)
