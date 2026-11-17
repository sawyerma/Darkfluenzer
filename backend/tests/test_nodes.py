"""Rechenknoten-Schnittstelle (SP0 Schritt 3): LocalNode erfüllt Node vollständig, Ordnerzugriffe
laufen über die Instanz, ein nicht laufender Knoten meldet sich mit ComfyError."""

from __future__ import annotations

import json

import pytest

from darkfluenzer.nodes import comfy
from darkfluenzer.nodes.base import Node, node_for
from darkfluenzer.nodes.local import LocalNode


def test_local_node_implements_the_interface(cfg):
    node = node_for(cfg, cfg.comfyui)
    assert isinstance(node, LocalNode) and isinstance(node, Node)
    assert node.name == cfg.comfyui.name and node.url == cfg.comfyui.url
    assert not getattr(LocalNode, "__abstractmethods__", set())
    assert node.output_dir() == cfg.comfyui.folder("output")


def test_editor_copy_install_keeps_edits_until_replace_and_remove_cleans_up(cfg, tmp_path):
    node = node_for(cfg, cfg.comfyui)
    ui = tmp_path / "wf.ui.json"
    ui.write_text(json.dumps({"nodes": [1]}))
    target = node.install_editor_copy(ui, "probe")
    assert target == node.editor_file("probe") and json.loads(target.read_text()) == {"nodes": [1]}
    target.write_text(json.dumps({"nodes": [2]}))  # im Editor bearbeitet, noch nicht übernommen
    node.install_editor_copy(ui, "probe")
    assert json.loads(target.read_text()) == {"nodes": [2]}
    node.install_editor_copy(ui, "probe", replace=True)
    assert json.loads(target.read_text()) == {"nodes": [1]}
    node.remove_editor_copy("probe")
    assert not target.exists() and not target.parent.exists()


def test_stage_dataset_goes_into_the_instance_input(cfg, tmp_path):
    dataset = tmp_path / "ds1"
    dataset.mkdir()
    (dataset / "a.png").write_bytes(b"png")
    (dataset / "dataset.json").write_text(
        json.dumps({"items": [{"file": "a.png", "caption": "dfchar woman"}]})
    )
    node = node_for(cfg, cfg.comfyui)
    rel = node.stage_dataset(dataset)
    staged = cfg.comfyui.folder("input") / rel
    assert (staged / "a.png").read_bytes() == b"png"
    assert (staged / "a.txt").read_text() == "dfchar woman"


def test_memory_of_a_stopped_node_raises(cfg):
    with pytest.raises(comfy.ComfyError):
        node_for(cfg, cfg.comfyui).memory(timeout=0.5)
