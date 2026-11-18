"""Kloner-Methoden je Befehl vergleichen (SP3 Schritt 8) und Herkunft mit LoRA (Schritt 9): Plan
Vorlage × Workflow mit Bildanweisung, LoRA nur wenn ladbar; Bericht mit Identitätswerten je
Workflow; die Herkunft eines Laufs mit LoRA nennt Schlüssel, Datei und SHA; Manifest-Vorschlag
``cloner`` geprüft und im STATE."""

from __future__ import annotations

import shutil

import pytest
from PIL import Image

from darkfluenzer.config import project_root
from darkfluenzer.core import cloner_compare
from darkfluenzer.media import models
from darkfluenzer.nodes import comfy
from darkfluenzer.store import Store


@pytest.fixture
def setup(cfg, tmp_path):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    folder = tmp_path / "vorlagen"
    folder.mkdir()
    for n in range(3):
        Image.new("RGB", (32, 32), (n * 40, 10, 10)).save(folder / f"v{n}.png")
    (folder / "notiz.txt").write_text("keine Vorlage")
    store = Store(cfg.local)
    yield cfg, store, models.load_manifest(cfg.root), folder
    store.close()


def test_plan_and_report(setup):
    cfg, store, man, folder = setup
    files = cloner_compare.templates(folder, 2)
    assert [f.name for f in files] == ["v0.png", "v1.png"]
    runs = cloner_compare.plan(
        store, man, "clone", files, ["flux3_klein_reference", "lustify_sdxl_refine"], None
    )
    assert len(runs) == 4 and {r["slot"] for r in runs} == {"reference", "image"}
    flux = runs[0]
    assert flux["values"]["prompt"].startswith("Recreate <ref_image_0>") and flux["lora"] == ""
    with pytest.raises(ValueError, match="genau einen Bild-Eingang"):
        cloner_compare.plan(store, man, "clone", files, ["ltx25_flf2v"], None)
    with pytest.raises(ValueError, match="unbekannt"):
        cloner_compare.plan(store, man, "dance", files, ["lustify_sdxl_refine"], None)

    def fake(cfg, man, run):
        score = 0.6 if run["workflow"] == "flux3_klein_reference" else 0.3
        status = "kein_gesicht" if run["template"].name == "v1.png" else "ok"
        if run["workflow"] == "lustify_sdxl_refine" and run["template"].name == "v1.png":
            raise comfy.ComfyError("Lauf abgebrochen")
        return comfy.RenderResult(
            prompt_id="p", workflow=run["workflow"], engine="x", params={},
            checks=[{"check": "identity", "status": status, "sface": score, "auraface": score}],
        )  # fmt: skip

    report = cloner_compare.run(cfg, man, runs, render=fake)
    summary = report["summary"]
    assert summary["flux3_klein_reference"] == {
        "runs": 2, "errors": 0, "measured": 1, "not_measurable": 1,
        "auraface_median": 0.6, "auraface_min": 0.6, "lora": "",
    }  # fmt: skip
    assert summary["lustify_sdxl_refine"]["errors"] == 1
    path = cloner_compare.write_report(cfg, "clone", report | {"command": "clone"})
    assert path.parent == cfg.local / "evaluation" / "cloner" and path.read_text().count("v0.png")


def test_provenance_names_the_lora(setup):
    cfg, store, man, _ = setup
    wf = man.workflows["lustify_sdxl_t2i"]
    lora = models.Lora(
        key="clara_r16_s1500", target="loras/characters/clara/clara_r16_s1500.safetensors",
        size=1, sha256="b" * 64, base_engine="lustify_sdxl", base_file="x", dataset="d",
        trigger="clr", steps=1500, rank=16, learning_rate=1e-4, strength=0.9, status="OFFEN",
        created_at="t", trainer="t", character="clara",
    )  # fmt: skip
    prov = comfy.provenance(man, wf, {"character_strength": 0.8}, comfy.LoraUse(lora, "clr woman"))
    assert prov["character_lora"] == {
        "key": "clara_r16_s1500", "file": lora.target, "sha256": "b" * 64, "character": "clara",
        "trigger": "clr woman", "strength": 0.8,
    }  # fmt: skip
    assert comfy.provenance(man, wf, {})["character_lora"] is None


def test_manifest_cloner_suggestion(setup):
    cfg, _, man, _ = setup
    path = cfg.root / "workflows" / "manifest.toml"
    text = path.read_text()
    anchor = "[workflows.flux3_klein_reference]\n"
    path.write_text(text.replace(anchor, anchor + 'cloner = ["clone", "pose"]\n', 1))
    assert models.load_manifest(cfg.root).workflows["flux3_klein_reference"].cloner == (
        "clone", "pose",
    )  # fmt: skip
    path.write_text(text.replace(anchor, anchor + 'cloner = ["dance"]\n', 1))
    with pytest.raises(models.ManifestError, match="cloner nur aus"):
        models.load_manifest(cfg.root)
