"""Aufträge mit Stufen: anlegen, fortschreiben, Kandidat wählen, Stufe wiederholen (SP0 Schritt 2,
bisher ``pipeline.py``)."""

from __future__ import annotations

from ..config import Config
from ..media.models import Manifest
from ..media.pipeline import VIDEO_KEYS, PipelineError, create_render, input_from_media
from ..nodes import comfy
from ..store import Store


def _journal(store: Store, command: dict | None, entity: str) -> None:
    """Befehl im selben Commit wie sein Effekt festhalten und abschließen."""
    if command:
        store.record_command(**command, entity=entity)
        store.finish_command(command["request_id"], "completed")


def create_order(
    store: Store,
    man: Manifest,
    workflow_key: str,
    values: dict,
    inputs: dict,
    *,
    count: int,
    finish_workflow: str = "",
    parent_media_id: int | None = None,
    command: dict | None = None,
    source: str = "operator",
    origin: int | None = None,
    customer_order_no: str = "",
    video_max_s: float | None = None,
) -> tuple[str, list[int]]:
    """Auftrag des Betreibers: Stufe 1 rendert ``count`` Kandidaten mit fortlaufenden Seeds und
    wartet dann auf die Auswahl; optional wird der ausgewählte Kandidat mit ``finish_workflow``
    (Eingang ``image``) fertiggestellt. Auftrag, Stufe, Jobs und Befehl in einem Commit.
    ``customer_order_no``: bezahlter Kundenauftrag, der so produziert wird (V0 §8.4 Punkt 5) –
    nur mit Workflows der Inhaltsstufe standard (Regel 13)."""
    wf = man.workflows.get(workflow_key)
    if wf is None:
        raise PipelineError(f"Workflow '{workflow_key}' ist nicht registriert.")
    if wf.training:
        raise PipelineError("Ein Training ist kein Kandidatenauftrag.")
    seed = wf.params.get("seed")
    if count < 1 or (count > 1 and seed is None):
        raise PipelineError(f"{workflow_key}: mehrere Kandidaten brauchen einen Seed-Parameter.")
    if finish_workflow:
        fw = man.workflows.get(finish_workflow)
        if fw is None or "image" not in fw.params or not fw.params["image"].upload or fw.training:
            raise PipelineError(f"Fertigstellen mit '{finish_workflow}' ist nicht möglich.")
        extra = [n for n, p in fw.params.items() if p.required and n != "image"]
        if extra:
            raise PipelineError(f"Fertigstellen mit {fw.title} braucht zusätzlich: {extra}.")
    if customer_order_no:
        for key in filter(None, (workflow_key, finish_workflow)):
            if man.workflows[key].content != "standard":
                raise PipelineError(
                    f"{man.workflows[key].title}: an Kunden nur Inhaltsstufe standard."
                )
        if parent_media_id is not None and store.media_tier(parent_media_id) != "standard":
            raise PipelineError("Ausgangsmedium ist nicht Inhaltsstufe standard.")
        existing = store.order(customer_order_no)
        if existing.source != "customer" or existing.status != "paid":
            raise PipelineError(f"{customer_order_no} ist kein bezahlter Kundenauftrag.")
    graph = comfy.load_graph(man, wf)
    base = int(values.get("seed", graph[seed.node]["inputs"][seed.input])) if seed else 0
    top = int(seed.max) if seed and seed.max is not None else 2**32 - 1
    params = {"values": values, "inputs": inputs, "finish": finish_workflow, "origin": origin}
    kind = man.engines[wf.engine].kind
    with store.tx():
        if customer_order_no:
            order = store.transition(customer_order_no, "producing", workflow=workflow_key)
            store.set_order_kind(customer_order_no, kind)
        else:
            order = store.create_production_order(
                source, kind, str(values.get("prompt", "")) or wf.title
            )
        stage = store.add_stage(order.id, "candidates", workflow_key, params, count)
        jobs = [
            create_render(
                store,
                man,
                workflow_key,
                {**values, "seed": (base + i) % (top + 1)} if seed else dict(values),
                inputs,
                parent_media_id=parent_media_id,
                stage_id=stage.id,
                video_max_s=video_max_s,
            )
            for i in range(count)
        ]
        _journal(store, command, f"order:{order.order_no}")
    return order.order_no, jobs


def advance_order(store: Store, job_id: int) -> None:
    """Nach dem Ende eines Jobs: ist seine Stufe vollständig, wartet sie auf die Auswahl
    (Kandidaten), ist fertig (Fertigstellen -> Auftrag zur Prüfung) oder fehlgeschlagen."""
    stage_id = store.job(job_id).get("stage_id")
    if not stage_id:
        return
    stage = store.stage(stage_id)
    jobs = store.stage_jobs(stage_id)
    if stage.status != "running" or any(j["status"] in ("queued", "running") for j in jobs):
        return
    done = [j for j in jobs if j["status"] == "done" and j["media_id"]]
    with store.tx():
        if not done:
            error = next((j["error"] for j in reversed(jobs) if j["error"]), "kein Ergebnis")
            store.set_stage(stage_id, "failed", error=error)
        elif stage.kind == "candidates":  # die kreative Auswahl trifft immer der Betreiber
            store.set_stage(stage_id, "waiting")
        else:
            store.set_stage(stage_id, "done", selected_media_id=done[-1]["media_id"])
            store.transition(store.order_by_id(stage.order_id).order_no, "review")


def select_candidate(
    cfg: Config, store: Store, man: Manifest, order_no: str, media_id: int, command: dict
) -> list[int]:
    """Auswahl des Betreibers; danach Fertigstellen (falls gewählt) mit genau diesem Medium,
    sonst geht der Auftrag zur Prüfung. Liefert neu angelegte Jobs."""
    order = store.order(order_no)
    stages = store.stages(order.id)
    stage = stages[-1] if stages else None
    if stage is None or stage.kind != "candidates" or stage.status != "waiting":
        raise PipelineError(f"{order_no} wartet nicht auf eine Auswahl.")
    if media_id not in {j["media_id"] for j in store.stage_jobs(stage.id)}:
        raise PipelineError(f"Medium {media_id} ist kein Kandidat von {order_no}.")
    finish = str(stage.params.get("finish") or "")
    image = input_from_media(cfg, media_id) if finish else ""
    with store.tx():
        store.set_stage(stage.id, "done", selected_media_id=media_id)
        jobs = []
        if finish:
            nxt = store.add_stage(order.id, "finish", finish, {"inputs": {"image": image}}, 1)
            jobs.append(
                create_render(
                    store,
                    man,
                    finish,
                    {},
                    {"image": image},
                    parent_media_id=media_id,
                    stage_id=nxt.id,
                )
            )
        else:
            store.transition(order_no, "review")
        _journal(store, command, f"order:{order_no}")
    return jobs


def retry_stage(
    store: Store,
    man: Manifest,
    order_no: str,
    seq: int,
    max_attempts: int,
    command: dict,
    video_max_s: float | None = None,
) -> list[int]:
    """Fehlgeschlagene Jobs einer Stufe mit denselben Parametern erneut anlegen."""
    order = store.order(order_no)
    stage = next((st for st in store.stages(order.id) if st.seq == seq), None)
    if stage is None or stage.status not in ("failed", "waiting"):
        raise PipelineError(f"{order_no}: Stufe {seq} ist nicht wiederholbar.")
    failed = [j for j in store.stage_jobs(stage.id) if j["status"] == "failed"]
    if not failed:
        raise PipelineError(f"{order_no}: Stufe {seq} hat keine fehlgeschlagenen Jobs.")
    if stage.attempts >= max_attempts:
        raise PipelineError(f"{order_no}: höchstens {max_attempts} Versuche je Stufe.")
    wf = man.workflows.get(stage.workflow)
    if wf is None:
        raise PipelineError(f"Workflow '{stage.workflow}' ist nicht mehr registriert.")
    with store.tx():
        store.set_stage(stage.id, "running", retry=True)
        jobs = []
        for j in failed:
            old = store.job(j["id"])
            uploads = {n for n, p in wf.params.items() if p.upload}
            jobs.append(
                create_render(
                    store,
                    man,
                    stage.workflow,
                    {
                        n: v
                        for n, v in old["params"].items()
                        if (n in wf.params or n in VIDEO_KEYS) and n not in uploads
                    },
                    {n: v for n, v in old["params"].items() if n in uploads},
                    parent_media_id=old["parent_media_id"],
                    stage_id=stage.id,
                    video_max_s=video_max_s,
                )
            )
            store.copy_segments(j["id"], jobs[-1])  # Langvideo: fertige Abschnitte behalten
        _journal(store, command, f"order:{order_no}")
    return jobs
