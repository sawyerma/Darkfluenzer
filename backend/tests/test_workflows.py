"""Workflow-Verträge: Graphprüfung, UI-Export, Masken-Pixelgarantie."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from darkfluenzer.config import project_root
from darkfluenzer.media import models, pipeline
from darkfluenzer.nodes import comfy

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


def test_ui_to_api_inverts_export_takes_edits_and_handles_bypass_and_mute():
    ui = comfy.api_to_ui(GRAPH, OBJECT_INFO)
    assert comfy.ui_to_api(ui, OBJECT_INFO) == GRAPH
    edited = copy.deepcopy(ui)
    sampler = next(n for n in edited["nodes"] if n["id"] == 3)
    sampler["widgets_values"][2] = 20  # Schritte im Editor geändert (nach Seed + Seed-Steuerung)
    assert comfy.ui_to_api(edited, OBJECT_INFO)["3"]["inputs"]["steps"] == 20
    # stumm (mode 2) wie im Frontend: Node entfällt, sein Verbraucher verliert den Eingang
    next(n for n in edited["nodes"] if n["id"] == 2)["mode"] = 2
    api = comfy.ui_to_api(edited, OBJECT_INFO)
    assert "2" not in api and "positive" not in api["3"]["inputs"]
    sampler["mode"] = 4  # umgangen: Node entfällt (Ausgänge werden durchgereicht)
    assert "3" not in comfy.ui_to_api(edited, OBJECT_INFO)


def test_registered_ui_exports_match_api_structure():
    """Ohne laufende ComfyUI: jede UI-Datei hat dieselben Nodes und Typen wie die API – bei
    Untergraphen die aktiven inneren Nodes mit dem Präfix der Instanz (wie graphToPrompt),
    umgangene/stumme Nodes entfallen; flache Graphen zusätzlich mit gleicher Link-Zahl."""
    man = models.load_manifest(ROOT)
    assert man.workflows, "mindestens ein registrierter Workflow erwartet"
    for wf in man.workflows.values():
        api = json.loads((ROOT / "workflows" / wf.api).read_text())
        ui = json.loads((ROOT / "workflows" / wf.ui).read_text())
        subgraphs = {g["id"]: g for g in (ui.get("definitions") or {}).get("subgraphs") or []}
        expected = {}
        for n in ui["nodes"]:
            if n["type"] in subgraphs:
                for inner in subgraphs[n["type"]]["nodes"]:
                    if inner.get("mode", 0) == 0:
                        expected[f"{n['id']}:{inner['id']}"] = inner["type"]
            elif n.get("mode", 0) == 0:
                expected[str(n["id"])] = n["type"]
        assert expected == {k: v["class_type"] for k, v in api.items()}, wf.key
        if not subgraphs:
            api_links = sum(comfy._is_link(v) for n in api.values() for v in n["inputs"].values())
            assert len(ui["links"]) == api_links, wf.key


def test_unique_outputs_tags_every_save_node_only():
    graph = {
        "1": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "d/a"}},
        "2": {"class_type": "MaskToImage", "inputs": {"mask": ["3", 0]}},
        "3": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "d/v", "video": ["2", 0]}},
    }
    tagged = comfy.unique_outputs(graph, "job7")
    assert tagged["1"]["inputs"]["filename_prefix"] == "d/a_job7"
    assert tagged["3"]["inputs"]["filename_prefix"] == "d/v_job7"
    assert tagged["2"] == graph["2"] and graph["1"]["inputs"]["filename_prefix"] == "d/a"


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


def test_template_import_defaults_missing_dynamic_values_and_accepts_autogrow():
    """Offizielle Vorlage aus älterer Knotenfassung (17.11.): fehlende Werte einer dynamischen
    Auswahl werden wie im Frontend mit dem Standard bzw. der ersten Option gefüllt; wachsende
    Eingänge (``values.a``) gelten in der Prüfung als bekannt."""
    sub = {"codec": ["COMBO", {"options": ["auto", "h264"]}]}
    dyn = ["COMFY_DYNAMICCOMBO_V3", {"options": [
        {"key": "auto", "inputs": {"required": sub}}, {"key": "mp4", "inputs": {"required": {}}},
    ]}]  # fmt: skip
    codec = ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "auto", "inputs": {"required": {}}}]}]
    info = {
        "Out": {"input": {"required": {"prefix": ["STRING", {}], "format": dyn, "codec": codec}},
                "output": [], "output_node": True},
        "Math": {"input": {"required": {"values": ["COMFY_AUTOGROW_V3", {"template": {
            "input": {"required": {"value": ["INT", {}]}}, "names": ["a", "b"]}}]}},
                 "output": ["INT"], "output_node": False},
    }  # fmt: skip
    inputs: dict = {}
    values = ["out", "auto"]  # nur zwei von vier Werten gespeichert
    for name, spec in info["Out"]["input"]["required"].items():
        if comfy._is_dynamic_combo(spec):
            comfy._take_dynamic(name, spec, values, inputs)
        else:
            inputs[name] = values.pop(0)
    assert inputs == {"prefix": "out", "format": "auto", "format.codec": "auto", "codec": "auto"}
    graph = {"1": {"class_type": "Math", "inputs": {"values.a": 1, "values.b": 2}}}
    assert comfy.check_graph(graph, info, set()) == []
    graph["1"]["inputs"]["values.z"] = 3  # nicht in der Namensliste
    assert comfy.check_graph(graph, info, set()) == ["1 Math: unbekannter Eingang 'values.z'"]


def test_api_to_ui_keeps_every_used_autogrow_input():
    """Mehrere belegte Untereingänge einer wachsenden Gruppe (``values.a``, ``values.b``) bleiben
    beim UI-Export erhalten (Rundweg ohne Abweichung, LTX-Vorlage 17.11.)."""
    info = {
        "Num": {"input": {"required": {"value": ["INT", {"default": 1}]}}, "output": ["INT"],
                "output_name": ["INT"], "output_node": False, "name": "Num"},
        "Math": {"input": {"required": {
            "expression": ["STRING", {"default": "a"}],
            "values": ["COMFY_AUTOGROW_V3", {"template": {
                "input": {"required": {"value": ["INT", {}]}}, "names": ["a", "b", "c"]}}],
        }}, "output": ["INT"], "output_name": ["INT"], "output_node": False, "name": "Math"},
        "Show": {"input": {"required": {"value": ["INT", {}]}}, "output": [], "output_name": [],
                 "output_node": True, "name": "Show"},
    }  # fmt: skip
    graph = {
        "1": {"class_type": "Num", "inputs": {"value": 5}},
        "2": {"class_type": "Num", "inputs": {"value": 24}},
        "3": {"class_type": "Math", "inputs": {"expression": "a * b + 1", "values.a": ["1", 0],
                                                "values.b": ["2", 0]}},
        "4": {"class_type": "Show", "inputs": {"value": ["3", 0]}},
    }  # fmt: skip
    assert comfy.ui_to_api(comfy.api_to_ui(graph, info), info) == graph
