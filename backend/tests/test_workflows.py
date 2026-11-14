"""Workflow-Verträge: Graphprüfung, UI-Export, Masken-Pixelgarantie."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from darkfluenzer import comfy, models, pipeline
from darkfluenzer.config import project_root

ROOT = project_root()

# Ausschnitt echter /object_info-Definitionen (ComfyUI 0.45.3)
OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "input": {"required": {"ckpt_name": [["sdxl/a.safetensors"], {}]}},
        "output": ["MODEL", "CLIP", "VAE"],
        "output_name": ["MODEL", "CLIP", "VAE"],
    },
    "CLIPTextEncode": {
        "input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}},
        "output": ["CONDITIONING"],
        "output_name": ["CONDITIONING"],
    },
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "seed": ["INT", {"default": 0, "control_after_generate": True}],
                "steps": ["INT", {"default": 20}],
                "positive": ["CONDITIONING"],
            }
        },
        "output": ["LATENT"],
        "output_name": ["LATENT"],
    },
}
GRAPH = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl/a.safetensors"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "hi", "clip": ["1", 1]}},
    "3": {
        "class_type": "KSampler",
        "inputs": {"model": ["1", 0], "seed": 5, "steps": 30, "positive": ["2", 0]},
    },
}


def test_check_graph_finds_real_problems():
    assert comfy.check_graph(GRAPH, OBJECT_INFO, set()) == []
    bad = json.loads(json.dumps(GRAPH))
    bad["1"]["inputs"]["ckpt_name"] = "fehlt.safetensors"
    bad["3"]["inputs"]["bogus"] = 1
    bad["2"]["inputs"]["clip"] = ["9", 0]
    del bad["3"]["inputs"]["steps"]
    bad["4"] = {"class_type": "Unbekannt", "inputs": {}}
    problems = "\n".join(comfy.check_graph(bad, OBJECT_INFO, set()))
    for needle in (
        "nicht verfügbar",
        "unbekannter Eingang",
        "fehlenden Node 9",
        "'steps' fehlt",
        "Unbekannt",
    ):
        assert needle in problems
    # dynamische V3-Eingänge (AUTOGROW) dürfen fehlen
    info = json.loads(json.dumps(OBJECT_INFO))
    info["CLIPTextEncode"]["input"]["required"]["images"] = ["COMFY_AUTOGROW_V3", {}]
    assert comfy.check_graph(GRAPH, info, set()) == []
    # Laufzeit-Uploads werden nicht als COMBO geprüft
    assert comfy.check_graph(bad, OBJECT_INFO, {("1", "ckpt_name")}).count("nicht verfügbar") == 0


def test_api_to_ui_preserves_values_links_and_seed_control():
    ui = comfy.api_to_ui(GRAPH, OBJECT_INFO)
    nodes = {n["id"]: n for n in ui["nodes"]}
    assert nodes[3]["widgets_values"] == [5, "fixed", 30]
    assert nodes[1]["widgets_values"] == ["sdxl/a.safetensors"]
    assert len(ui["links"]) == 3
    # jeder Link ist auf beiden Seiten eingetragen
    for link_id, src, src_slot, dst, dst_slot, typ in ui["links"]:
        assert link_id in nodes[src]["outputs"][src_slot]["links"]
        assert nodes[dst]["inputs"][dst_slot]["link"] == link_id
        assert nodes[src]["outputs"][src_slot]["type"] == typ
    assert comfy.api_to_ui(GRAPH, OBJECT_INFO) == ui, "Export muss deterministisch sein"


def test_registered_ui_exports_match_api_structure():
    """Ohne laufende ComfyUI: jede UI-Datei hat dieselben Nodes, Typen und Links wie die API."""
    man = models.load_manifest(ROOT)
    assert man.workflows, "mindestens ein registrierter Workflow erwartet"
    for wf in man.workflows.values():
        api = json.loads((ROOT / "workflows" / wf.api).read_text())
        ui = json.loads((ROOT / "workflows" / wf.ui).read_text())
        assert {str(n["id"]): n["type"] for n in ui["nodes"]} == {
            k: v["class_type"] for k, v in api.items()
        }
        api_links = sum(comfy._is_link(v) for n in api.values() for v in n["inputs"].values())
        assert len(ui["links"]) == api_links


def _png(path: Path, array: np.ndarray) -> Path:
    Image.fromarray(array).save(path)
    return path


def test_unmasked_difference_detects_changes_outside_mask(tmp_path):
    rng = np.random.default_rng(0)
    master = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:30, 20:30] = 255
    edited = master.copy()
    edited[20:30, 20:30] = 0  # nur in der Maske
    edited[30:33, 20:30] = 7  # im erlaubten Übergangsrand (grow=4)
    m, e, k = (
        _png(tmp_path / "m.png", master),
        _png(tmp_path / "e.png", edited),
        _png(tmp_path / "k.png", mask),
    )
    assert pipeline.unmasked_difference(m, e, k, grow=4) == 0
    edited[60, 60] = master[60, 60] ^ 1  # ein Pixel weit außerhalb
    _png(tmp_path / "e.png", edited)
    assert pipeline.unmasked_difference(m, e, k, grow=4) == 1
    _png(tmp_path / "small.png", master[:32])
    with pytest.raises(pipeline.PipelineError, match="Formate"):
        pipeline.unmasked_difference(m, tmp_path / "small.png", k, grow=4)
