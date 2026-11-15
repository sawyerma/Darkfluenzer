"""Auftrag mit Stufen (V0 §4.3): Kandidaten -> Auswahl des Betreibers -> Fertigstellen."""

from __future__ import annotations

import hashlib
import shutil

import pytest
from PIL import Image

from darkfluenzer import models, pipeline
from darkfluenzer.config import project_root
from darkfluenzer.store import Store, StoreError


@pytest.fixture
def setup(cfg):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    store = Store(cfg.local)
    yield cfg, store, models.load_manifest(cfg.root)
    store.close()


def _finish(cfg, store: Store, job_id: int, ok: bool = True) -> int | None:
    """Job so abschließen, wie es der Renderweg tut (Ausgabe in der Galerie, dann Status)."""
    store.set_job_status(job_id, "running")
    if not ok:
        store.set_job_status(job_id, "failed", error="ComfyUI-Fehler")
        pipeline.advance_order(store, job_id)
        return None
    rel = f"evaluation/test/job{job_id}.png"
    (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (job_id * 40 % 255, 10, 10)).save(cfg.local / rel)
    sha = hashlib.sha256((cfg.local / rel).read_bytes()).hexdigest()
    media = store.add_media(rel, sha, (cfg.local / rel).stat().st_size, job_id=job_id)
    store.set_job_status(job_id, "done", outputs=[{"path": rel, "sha256": sha}])
    pipeline.advance_order(store, job_id)
    return media


def _command(name: str) -> dict:
    return {"request_id": name, "payload_sha": "0" * 64, "command": name, "status": "accepted"}


def test_candidates_selection_and_finish(setup):
    cfg, store, man = setup
    values = {"prompt": "portrait", "seed": 4294967294}
    order_no, jobs = pipeline.create_order(
        store,
        man,
        "lustify_sdxl_t2i",
        values,
        {},
        count=3,
        finish_workflow="lustify_sdxl_refine",
        command=_command("c1"),
    )
    assert [store.job(j)["params"]["seed"] for j in jobs] == [4294967294, 4294967295, 0]
    assert store.command("c1")["status"] == "completed"
    order = store.order(order_no)
    assert order.source == "operator" and order.customer_id is None and order.status == "producing"

    first = _finish(cfg, store, jobs[0])
    _finish(cfg, store, jobs[1], ok=False)
    (stage,) = store.stages(order.id)
    assert stage.status == "running"  # ein Kandidat läuft noch
    third = _finish(cfg, store, jobs[2])
    assert store.stages(order.id)[0].status == "waiting"

    with pytest.raises(pipeline.PipelineError, match="kein Kandidat"):
        pipeline.select_candidate(cfg, store, man, order_no, 999, _command("bad"))
    (finish_job,) = pipeline.select_candidate(cfg, store, man, order_no, third, _command("s1"))
    done, finishing = store.stages(order.id)
    assert done.status == "done" and done.selected_media_id == third != first
    assert finishing.kind == "finish" and finishing.status == "running"
    job = store.job(finish_job)
    assert job["workflow"] == "lustify_sdxl_refine" and job["parent_media_id"] == third
    with pytest.raises(pipeline.PipelineError, match="wartet nicht"):
        pipeline.select_candidate(cfg, store, man, order_no, first, _command("s2"))

    _finish(cfg, store, finish_job)
    assert store.stages(order.id)[1].status == "done"
    assert store.order(order_no).status == "review" and store.active_orders() == []


def test_failed_stage_retry_has_a_limit(setup):
    cfg, store, man = setup
    order_no, jobs = pipeline.create_order(
        store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {}, count=2
    )
    for job in jobs:
        _finish(cfg, store, job, ok=False)
    (stage,) = store.stages(store.order(order_no).id)
    assert stage.status == "failed" and stage.error == "ComfyUI-Fehler"
    again = pipeline.retry_stage(store, man, order_no, 1, 2, _command("r1"))
    assert len(again) == 2 and store.stages(stage.order_id)[0].attempts == 2
    for job in again:
        _finish(cfg, store, job, ok=False)
    with pytest.raises(pipeline.PipelineError, match="höchstens 2"):
        pipeline.retry_stage(store, man, order_no, 1, 2, _command("r2"))


def test_order_rules(setup):
    _, store, man = setup
    with pytest.raises(pipeline.PipelineError, match="kein Kandidatenauftrag"):
        pipeline.create_order(store, man, "lustify_sdxl_lora_train", {}, {}, count=1)
    with pytest.raises(pipeline.PipelineError, match="braucht zusätzlich"):
        pipeline.create_order(
            store,
            man,
            "lustify_sdxl_t2i",
            {"prompt": "p"},
            {},
            count=1,
            finish_workflow="lustify_sam31_edit",
        )
    with pytest.raises(StoreError):
        store.create_production_order("customer", "image", "x")
