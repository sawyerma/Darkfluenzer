"""SP3 Schritt 5: Charakter-LoRA im Workflow. Lader gesetzt (Name, Stärke aus der LoRA, Trigger vor
dem Prompt) oder entfernt (Eingänge durchgereicht); der Auftrag trägt die LoRA durch Kandidaten,
Fertigstellen und Wiederholen; Kundenaufträge laufen nie ohne."""

from __future__ import annotations

import shutil

import pytest

from darkfluenzer.config import project_root
from darkfluenzer.core import orders
from darkfluenzer.media import models, pipeline
from darkfluenzer.nodes import comfy
from darkfluenzer.store import Store


@pytest.fixture
def setup(cfg):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    store = Store(cfg.local)
    yield cfg, store, models.load_manifest(cfg.root)
    store.close()


def _register(cfg, man, key: str, engine: str) -> tuple[models.Manifest, models.Lora]:
    lora = models.Lora(
        key=key, target=f"loras/characters/clara/{key}.safetensors", size=1, sha256="a" * 64,
        base_engine=engine, base_file=man.engines[engine].files[0], dataset="ds", trigger="dfchar",
        steps=10, rank=16, learning_rate=1e-4, strength=0.8, status="OFFEN", created_at="t",
        trainer="ComfyUI TrainLoraNode", character="clara",
    )  # fmt: skip
    return models.register_lora(cfg.root, lora), lora


def _links_to(graph: dict, node: str) -> list[str]:
    return [
        f"{nid}.{name}"
        for nid, n in graph.items()
        for name, v in n["inputs"].items()
        if isinstance(v, list) and v[0] == node
    ]


def test_without_lora_the_loader_is_removed_and_its_inputs_pass_through(setup):
    _, _, man = setup
    slotted = [wf for wf in man.workflows.values() if wf.lora]
    assert {wf.key for wf in slotted} >= {
        "krea2_raw_turbo_lora_t2i", "lustify_v10_krea_t2i", "lustify_sdxl_t2i",
        "lustify_sdxl_refine", "lustify_sdxl_inpaint", "lustify_sam31_edit",
    }  # fmt: skip
    for wf in slotted:
        graph = comfy.load_graph(man, wf)
        loader = graph[wf.lora.node]["inputs"]
        users = {
            ref: graph[ref.split(".")[0]]["inputs"][ref.split(".")[1]][1]
            for ref in _links_to(graph, wf.lora.node)
        }
        out = comfy.bind_lora(graph, wf, None, {})
        assert wf.lora.node not in out and not _links_to(out, wf.lora.node), wf.key
        for ref, index in users.items():  # jeder Verbraucher hängt jetzt am Eingang des Laders
            nid, name = ref.split(".")
            assert out[nid]["inputs"][name] == loader[wf.lora.through[index]], (wf.key, ref)


def test_with_lora_name_strength_from_the_lora_and_trigger_first(setup):
    cfg, _, man = setup
    man, lora = _register(cfg, man, "clara_sdxl", "lustify_sdxl")
    wf = man.workflows["lustify_sdxl_t2i"]
    use = comfy.LoraUse(lora, "dfchar woman")
    values = {"prompt": "portrait at the window"}
    graph = comfy.apply_params(comfy.load_graph(man, wf), wf, comfy.with_trigger(wf, values, use))
    graph = comfy.bind_lora(graph, wf, use, values)
    loader = graph[wf.lora.node]["inputs"]
    assert loader["lora_name"] == "characters/clara/clara_sdxl.safetensors"
    assert loader["strength_model"] == loader["strength_clip"] == 0.8  # Startwert aus der LoRA
    assert (
        graph[wf.params["prompt"].node]["inputs"]["text"] == "dfchar woman, portrait at the window"
    )
    # eigene Stärke des Betreibers gilt; ein Prompt mit Trigger bleibt unverändert
    values = {"prompt": "dfchar in the rain", "character_strength": 1.2}
    graph = comfy.apply_params(comfy.load_graph(man, wf), wf, comfy.with_trigger(wf, values, use))
    graph = comfy.bind_lora(graph, wf, use, values)
    assert graph[wf.lora.node]["inputs"]["strength_clip"] == 1.2
    assert graph[wf.params["prompt"].node]["inputs"]["text"] == "dfchar in the rain"
    # Workflow ohne Lader nimmt keine LoRA
    with pytest.raises(comfy.ComfyError, match="keinen Lader"):
        comfy.bind_lora({}, man.workflows["ltx25_i2v"], use, {})


def test_order_carries_the_lora_through_finish_and_retry(setup):
    cfg, store, man = setup
    man, _ = _register(cfg, man, "clara_sdxl", "lustify_sdxl")
    man, _ = _register(cfg, man, "clara_krea", "krea2_raw")
    with pytest.raises(pipeline.PipelineError, match="nicht registriert"):
        orders.create_order(store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {}, count=1, lora="x")
    with pytest.raises(pipeline.PipelineError, match="passt nicht zur Engine"):
        orders.create_order(
            store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {}, count=1, lora="clara_krea"
        )
    customer = store.customer_for_identity("telegram", "bot", "5")[0]
    paid = store.create_order(customer.id, "image", "Bild")
    store.db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (paid.id,))
    with pytest.raises(pipeline.PipelineError, match="nie ohne Charakter-LoRA"):
        orders.create_order(
            store, man, "krea2_raw_turbo_lora_t2i", {"prompt": "p"}, {}, count=1,
            customer_order_no=paid.order_no,
        )  # fmt: skip

    order_no, jobs = orders.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p", "seed": 1}, {}, count=2,
        finish_workflow="lustify_sdxl_refine", lora="clara_sdxl",
    )  # fmt: skip
    assert all(store.job(j)["params"][pipeline.LORA_KEY] == "clara_sdxl" for j in jobs)
    stage = store.stages(store.order(order_no).id)[0]
    assert stage.params[pipeline.LORA_KEY] == "clara_sdxl"
    from test_orders import _command, _finish

    media = _finish(cfg, store, jobs[0])
    _finish(cfg, store, jobs[1], ok=False)
    again = orders.retry_stage(store, man, order_no, 1, 3, _command("retry"))
    assert store.job(again[0])["params"][pipeline.LORA_KEY] == "clara_sdxl"
    _finish(cfg, store, again[0])
    (finish,) = orders.select_candidate(cfg, store, man, order_no, media, _command("select"))
    assert store.job(finish)["params"][pipeline.LORA_KEY] == "clara_sdxl"  # gleiche Engine

    # Krea-LoRA: das SDXL-Fertigstellen läuft ohne (anderer Lader-Typ, andere Engine)
    order_no, jobs = orders.create_order(
        store, man, "krea2_raw_turbo_lora_t2i", {"prompt": "p"}, {}, count=1,
        finish_workflow="lustify_sdxl_refine", lora="clara_krea",
    )  # fmt: skip
    media = _finish(cfg, store, jobs[0])
    (finish,) = orders.select_candidate(cfg, store, man, order_no, media, _command("select2"))
    assert pipeline.LORA_KEY not in store.job(finish)["params"]


def test_run_render_submits_the_graph_with_lora_and_profile_trigger(setup, monkeypatch):
    cfg, store, man = setup
    store.save_character(0, 0, "Clara", "dfchar", "woman", "clara")
    man, _ = _register(cfg, man, "clara_sdxl", "lustify_sdxl")
    with_lora = pipeline.create_render(
        store, man, "lustify_sdxl_t2i", {"prompt": "portrait"}, {}, lora="clara_sdxl"
    )
    without = pipeline.create_render(store, man, "lustify_sdxl_t2i", {"prompt": "portrait"}, {})
    sent: list[dict] = []

    def submit(self, graph, job_id=None):
        sent.append(graph)
        raise comfy.ComfyError("Probe: nur der eingereichte Graph zählt")

    monkeypatch.setattr(comfy.ComfyClient, "submit", submit)
    for job in (with_lora, without):
        with pytest.raises(Exception, match="Probe"):
            pipeline.run_render(cfg, man, job)
    wf = man.workflows["lustify_sdxl_t2i"]
    lora_graph, plain = sent
    name = lora_graph[wf.lora.node]["inputs"]["lora_name"]
    assert name == "characters/clara/clara_sdxl.safetensors"
    assert lora_graph[wf.params["prompt"].node]["inputs"]["text"] == "dfchar woman, portrait"
    assert (
        wf.lora.node not in plain
        and plain[wf.params["prompt"].node]["inputs"]["text"] == "portrait"
    )
