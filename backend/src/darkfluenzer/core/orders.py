"""Aufträge mit Stufen: anlegen, fortschreiben, Kandidat wählen, Stufe wiederholen (SP0 Schritt 2,
bisher ``pipeline.py``)."""

from __future__ import annotations

import asyncio
import json

from ..config import Config
from ..media.models import Manifest
from ..media.pipeline import (
    KEYFRAMES_KEY,
    LORA_KEY,
    VIDEO_KEYS,
    PipelineError,
    check_lora,
    create_render,
    input_from_media,
)
from ..nodes import comfy
from ..store import Store
from ..store.schema import OPERATOR_TRANSITIONS
from ..v1 import commands_pb2, order_pb2
from ..v1 import stream_pb2 as spb
from .base import _Call, _unix_ms, log


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
    finish_values: dict | None = None,
    parent_media_id: int | None = None,
    command: dict | None = None,
    source: str = "operator",
    origin: int | None = None,
    customer_order_no: str = "",
    video_max_s: float | None = None,
    lora: str = "",
    character_id: int | None = None,
    keyframes: list[dict] | None = None,
    keyframes_max: int = 0,
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
    if lora and character_id is not None:  # Auftrag für eine Figur: nur deren LoRA (SP3 Schritt 6)
        check_lora(man, wf, lora, character=store.character(character_id)["slug"])
    seed = wf.params.get("seed")
    if count < 1 or (count > 1 and seed is None):
        raise PipelineError(f"{workflow_key}: mehrere Kandidaten brauchen einen Seed-Parameter.")
    if finish_workflow:
        fw = man.workflows.get(finish_workflow)
        if fw is None or "image" not in fw.params or not fw.params["image"].upload or fw.training:
            raise PipelineError(f"Fertigstellen mit '{finish_workflow}' ist nicht möglich.")
        extra = [
            n
            for n, p in fw.params.items()
            if p.required and n != "image" and n not in (finish_values or {})
        ]
        if extra:
            raise PipelineError(f"Fertigstellen mit {fw.title} braucht zusätzlich: {extra}.")
        # Werte der Fertigstellen-Stufe gleich hier prüfen (Typen, Grenzen, Namen; BUG-090)
        probe = {k: v for k, v in (finish_values or {}).items() if k not in VIDEO_KEYS}
        comfy.apply_params(comfy.load_graph(man, fw), fw, {**probe, "image": "pruefung.png"})
    elif finish_values:
        raise PipelineError(
            "Werte für das Fertigstellen gibt es nur mit einem Fertigstellen-Workflow."
        )
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
        if wf.lora is not None and not lora:  # SP3 Schritt 5
            raise PipelineError("Kundenaufträge laufen nie ohne Charakter-LoRA.")
    graph = comfy.load_graph(man, wf)
    base = int(values.get("seed", graph[seed.node]["inputs"][seed.input])) if seed else 0
    top = int(seed.max) if seed and seed.max is not None else 2**32 - 1
    params = {
        "values": values,
        "inputs": inputs,
        "finish": finish_workflow,
        "finish_values": dict(finish_values or {}),
        "origin": origin,
        **({LORA_KEY: lora} if lora else {}),
    }
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
                lora=lora,
                keyframes=keyframes,
                keyframes_max=keyframes_max,
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
    finish_values = dict(stage.params.get("finish_values") or {})  # BUG-090
    image = input_from_media(cfg, media_id) if finish else ""
    lora = _finish_lora(man, finish, str(stage.params.get(LORA_KEY) or ""))
    with store.tx():
        store.set_stage(stage.id, "done", selected_media_id=media_id)
        jobs = []
        if finish:
            params = {"inputs": {"image": image}, "values": finish_values}
            nxt = store.add_stage(
                order.id, "finish", finish, {**params, **({LORA_KEY: lora} if lora else {})}, 1
            )
            jobs.append(
                create_render(
                    store,
                    man,
                    finish,
                    finish_values,
                    {"image": image},
                    parent_media_id=media_id,
                    stage_id=nxt.id,
                    video_max_s=cfg.production.video_max_s,
                    lora=lora,
                )
            )
        else:
            store.transition(order_no, "review")
        _journal(store, command, f"order:{order_no}")
    return jobs


def _finish_lora(man: Manifest, finish: str, lora: str) -> str:
    """Die Fertigstellen-Stufe nutzt die LoRA des Auftrags, wenn ihr Workflow einen Lader hat und
    seine Engine sie laden darf; sonst läuft sie ohne (z. B. Hochskalieren)."""
    if not finish or not lora:
        return ""
    try:
        check_lora(man, man.workflows[finish], lora)
    except PipelineError:
        return ""
    return lora


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
                    inherit_tier=old["content_tier"],  # „Wiederholen“ erbt die Stufe
                    lora=str(old["params"].get(LORA_KEY) or ""),
                    keyframes=old["params"].get(KEYFRAMES_KEY),
                    keyframes_max=len(old["params"].get(KEYFRAMES_KEY) or []),
                )
            )
            store.copy_segments(j["id"], jobs[-1])  # Langvideo: fertige Abschnitte behalten
        _journal(store, command, f"order:{order_no}")
    return jobs


def _fill_order(item: order_pb2.ActiveOrder, store: Store, order) -> None:
    """Auftrag mit Stufen, Jobs und Kandidaten (STATE orders.active, Systemkarte)."""
    item.order_no, item.source, item.kind = order.order_no, order.source, order.kind
    item.request, item.status = order.request, order.status
    for st in store.stages(order.id):
        stage = item.stages.add(
            seq=st.seq,
            kind=st.kind,
            status=st.status,
            workflow=st.workflow,
            count=st.count,
            selected_media_id=st.selected_media_id or 0,
            error=st.error or "",
            finish_workflow=str(st.params.get("finish") or ""),
            attempts=st.attempts,
            lora=str(st.params.get(LORA_KEY) or ""),
        )
        for j in store.stage_jobs(st.id):
            stage.jobs.add(
                job_id=j["id"],
                seed=int(j["seeds"][0]) if j["seeds"] else 0,
                status=j["status"],
                media_id=j["media_id"] or 0,
                path=j["path"] or "",
                error=j["error"] or "",
                content_tier=j["content_tier"] or "",
            )
        if st.status == "done" and st.selected_media_id:
            media = store.media_by_id(st.selected_media_id)
            item.result_media_id = st.selected_media_id
            item.result_path = media["path"] if media else ""
            item.result_tier = (media["content_tier"] if media else "") or ""
    if order.source != "customer":
        return
    item.customer_id, item.customer_no = order.customer_id or 0, order.customer_no or ""
    offer = store.offer(order.id)
    if offer is not None:
        item.offer.product, item.offer.hd = offer["product"], bool(offer["hd"])
        item.offer.price_cents, item.offer.expires_ms = (
            offer["price_cents"],
            _unix_ms(offer["expires_at"]),
        )
        item.offer.conversation_id = offer["conversation_id"]
        for row in store.offer_amount_rows(order.id):
            network = "bitcoin" if row["method"] == "btc" else "bsc"
            item.offer.amounts.add(
                method=row["method"],
                asset=row["method"].upper(),
                amount=row["amount"],
                address=row["address"],
                network=network,
                rate=row["rate"],
                rate_ms=row["rate_ms"],
            )
    for d in store.deliveries(order.id):
        status = d["status"]
        if status == "pending" and d["message_status"] == "unknown":
            status = "unknown"
        atts = json.loads(d["attachments"] or "[]")
        item.deliveries.add(
            delivery_id=d["id"],
            status=status,
            message_id=d["message_id"] or 0,
            error=d["message_error"] or "",
            at_ms=_unix_ms(d["sent_at"] or d["created_at"]),
            path=atts[0]["path"] if atts else "",
        )


class OrdersMixin:
    """Aufträge als Cockpit-Befehle; Teil von ``Cockpit``."""

    def _orders_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_ORDERS_ACTIVE, self._orders_active())
        self.hub.push_events(spb.TOPIC_ORDER_UPDATED)
        self.hub.push_events(spb.TOPIC_CONVERSATION_EVENT)  # Systemkarten der Aufträge
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    async def _create_order(self, msg: commands_pb2.CreateOrder, call: _Call) -> str:
        """Auftrag mit Kandidaten (V0 §4.3); Auftrag, Stufe, Jobs und Befehl in einem Commit."""
        wf = self._workflow(msg.workflow)
        call.entity = f"workflow:{wf.key}"
        prod = self.cfg.production
        count = msg.candidates or prod.candidates_default
        if count > prod.candidates_max:
            return f"Höchstens {prod.candidates_max} Kandidaten je Auftrag."
        for key in filter(None, (wf.key, msg.finish_workflow)):
            target = self._workflow(key)
            if self._lane_of(target) is None:
                return "Die ausführende ComfyUI-Instanz ist nicht eingerichtet."
            if reason := await asyncio.to_thread(self._not_startable, target):
                return f"{target.title}: {reason}"
        values = {
            v.name: getattr(v, v.WhichOneof("value")) for v in msg.values if v.WhichOneof("value")
        }
        inputs = await self._inputs(wf, msg.files)
        finish_values = {
            v.name: getattr(v, v.WhichOneof("value"))
            for v in msg.finish_values
            if v.WhichOneof("value")
        }
        order_no, jobs = create_order(
            self.store,
            self.manifest,
            wf.key,
            values,
            inputs,
            count=count,
            finish_workflow=msg.finish_workflow,
            finish_values=finish_values,
            parent_media_id=msg.parent_media_id or None,
            command=self._journal_entry(call),
            customer_order_no=msg.customer_order_no,
            lora=msg.lora,
            keyframes=await self._keyframes(msg.keyframes),
            keyframes_max=self.cfg.production.keyframes_max,
            video_max_s=self.cfg.production.video_max_s,
        )
        call.entity, call.recorded = f"order:{order_no}", True
        log.info("Auftrag %s: %d Kandidaten von %s eingereiht", order_no, len(jobs), wf.key)
        self._enqueue(jobs)
        self._orders_changed()
        if msg.customer_order_no:
            self._message_changed(0)  # Auftragskarte im Kundenverlauf
        return ""

    async def _select_candidate(self, msg: commands_pb2.SelectCandidate, call: _Call) -> str:
        call.entity = f"order:{msg.order_no}"
        jobs = select_candidate(
            self.cfg,
            self.store,
            self.manifest,
            msg.order_no,
            msg.media_id,
            self._journal_entry(call),
        )
        call.recorded = True
        log.info("Auftrag %s: Medium %s ausgewählt", msg.order_no, msg.media_id)
        if not jobs:  # ohne Fertigstellen: das Gewählte geht ggf. an den Default-Nutzer
            await self._cloner_delivery(self.store.order(msg.order_no).id, selected=msg.media_id)
        self._enqueue(jobs)
        self._orders_changed()
        return ""

    async def _order_cancel(self, msg: commands_pb2.OrderCancel, call: _Call) -> str:
        """Auftrag als Ganzes abbrechen (Befehl 59, SP1 Schritt 11): alle wartenden und laufenden
        Jobs mit der Logik von ``_cancel``; Betreiber- und Kloner-Aufträge gehen auf abgebrochen,
        bezahlte Kundenaufträge bleiben offen (Neuauflage oder Erstattung entscheidet der
        Betreiber)."""
        call.entity = f"order:{msg.order_no}"
        order = self.store.order(msg.order_no)
        jobs = [
            j["id"]
            for stage in self.store.stages(order.id)
            for j in self.store.stage_jobs(stage.id)
            if j["status"] in ("queued", "running")
        ]
        if not jobs:
            return f"{msg.order_no} hat keine wartenden oder laufenden Jobs."
        for job_id in jobs:
            await self._cancel_job(job_id)
        order = self.store.order(msg.order_no)
        if order.source != "customer" and "cancelled" in OPERATOR_TRANSITIONS.get(order.status, ()):
            self.store.transition(order.order_no, "cancelled", reason="Betreiber")
        self._card(order, f"ABGEBROCHEN · {order.order_no} · {len(jobs)} Job(s)")
        log.info("Auftrag %s abgebrochen (%d Jobs)", order.order_no, len(jobs))
        self._orders_changed()
        return ""

    async def _retry_stage(self, msg: commands_pb2.RetryStage, call: _Call) -> str:
        call.entity = f"order:{msg.order_no}"
        jobs = retry_stage(
            self.store,
            self.manifest,
            msg.order_no,
            msg.seq,
            self.cfg.production.stage_attempts_max,
            self._journal_entry(call),
            video_max_s=self.cfg.production.video_max_s,
        )
        call.recorded = True
        log.info("Auftrag %s: Stufe %s wiederholt (%d Jobs)", msg.order_no, msg.seq, len(jobs))
        self._enqueue(jobs)
        self._orders_changed()
        return ""

    def _orders_active(self) -> bytes:
        """STATE orders.active: Aufträge in Produktion mit Stufen und deren Jobs/Kandidaten."""
        prod = self.cfg.production
        msg = order_pb2.OrdersActive(
            version=self.store.domain_version("orders"),
            candidates_default=prod.candidates_default,
            candidates_max=prod.candidates_max,
        )
        for order in self.store.active_orders():
            _fill_order(msg.orders.add(), self.store, order)
        for order in self.store.active_orders("paid"):
            _fill_order(msg.awaiting_production.add(), self.store, order)
        return msg.SerializeToString()

    def _order_result(self, order) -> dict | None:
        """Ergebnis eines Auftrags in Prüfung: Medium der letzten fertigen Stufe."""
        stages = self.store.stages(order.id)
        last = stages[-1] if stages else None
        if last is None or last.status != "done" or not last.selected_media_id:
            return None
        media = self.store.media_by_id(last.selected_media_id)
        return media
