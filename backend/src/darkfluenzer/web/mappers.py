"""Protobuf-Abbildungen und Ereignisseiten für den Stream (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..channels.base import Channel
from ..core.base import _unix_ms
from ..core.orders import _fill_order
from ..media import gallery
from ..store import Store
from ..v1 import (
    channel_pb2,
    comfy_pb2,
    commands_pb2,
    media_pb2,
    order_pb2,
    reference_pb2,
    wallet_pb2,
)

if TYPE_CHECKING:
    from .http import Cockpit


_RECEIPT_STATUS = {
    "accepted": commands_pb2.COMMAND_STATUS_ACCEPTED,
    "rejected": commands_pb2.COMMAND_STATUS_REJECTED,
    "completed": commands_pb2.COMMAND_STATUS_COMPLETED,
    "failed": commands_pb2.COMMAND_STATUS_FAILED,
    "unknown": commands_pb2.COMMAND_STATUS_UNKNOWN,
    "cancelled": commands_pb2.COMMAND_STATUS_CANCELLED,
}


def _media_item(row: dict) -> media_pb2.MediaItem:
    """Galerie-Eintrag; Unterschrift: Kundenname (sonst Kundennummer) oder laufende Nummer."""
    if row["artifact_id"]:
        origin = media_pb2.MEDIA_ORIGIN_ORDER
    elif row["job_id"]:
        origin = media_pb2.MEDIA_ORIGIN_RENDER
    elif row["path"].startswith("ComfyUI/"):
        origin = media_pb2.MEDIA_ORIGIN_COMFYUI
    else:
        origin = media_pb2.MEDIA_ORIGIN_EVALUATION
    caption = (
        (row["display_name"] or row["customer_no"] or "")
        if row["order_id"]
        else f"{row['number']:04d}"
    )
    item = media_pb2.MediaItem(
        media_id=row["id"],
        kind=media_pb2.MEDIA_KIND_VIDEO if row["kind"] == "video" else media_pb2.MEDIA_KIND_IMAGE,
        caption=caption,
        path=row["path"],
        size=row["size"],
        sha256=row["sha256"],
        created_unix_ms=_unix_ms(row["created_at"]),
        origin=origin,
        workflow=row["workflow"] or "",
        job_id=row["job_id"] or 0,
        order_no=row["order_no"] or "",
        customer_no=row["customer_no"] or "",
        content_tier=row["content_tier"] or "",
        width=row.get("width") or 0,
        height=row.get("height") or 0,
        native_width=row.get("native_width") or 0,
        native_height=row.get("native_height") or 0,
    )
    item.params.update({k: str(v) for k, v in row["params"].items()})
    return item


def _provenance(cockpit: Cockpit, media_id: int) -> media_pb2.MediaProvenance | None:
    """Herkunft eines Mediums aus Job-Journal, Graph-Snapshot und Herkunftsdatei des Laufs."""
    store, man = cockpit.store, cockpit.manifest
    row = store.media_by_id(media_id)
    if row is None:
        return None
    msg = media_pb2.MediaProvenance(
        media_id=media_id, child_media_ids=store.media_children(media_id)
    )
    if not row["job_id"]:
        return msg
    job = store.job(row["job_id"])
    wf = man.workflows.get(job["workflow"])
    msg.job_id = job["id"]
    msg.workflow = job["workflow"]
    msg.workflow_title = wf.title if wf else ""
    msg.engine = job["engine"]
    msg.workflow_sha256 = job["workflow_sha256"] or ""
    msg.prompt_id = job["prompt_id"] or ""
    msg.parent_media_id = job["parent_media_id"] or 0
    msg.params.update({k: str(v) for k, v in job["params"].items()})
    done = next(
        (
            e["data"]
            for e in reversed(store.events("job", job["id"]))
            if e["event"] == "status" and e["data"].get("status") == "done"
        ),
        {},
    )
    msg.duration_s = float(done.get("duration_s") or 0)
    if memory := done.get("memory"):
        msg.memory.CopyFrom(media_pb2.MemoryTrace(**memory_fields(memory)))
    sidecar = gallery.sidecar_for(cockpit.cfg, row["path"]) or {}
    for param, inp in (sidecar.get("inputs") or {}).items():
        path = Path(inp["file"])
        rel = path.relative_to(cockpit.cfg.local).as_posix() if path.is_absolute() else str(path)
        msg.inputs.add(param=param, path=rel, sha256=inp["sha256"])
    for model in (sidecar.get("provenance") or {}).get("models") or []:
        msg.models.add(
            file=model["file"],
            repo=model["repo"],
            revision=model["revision"],
            sha256=model["sha256"],
        )
    for nid, node in (job["graph"] or {}).items():
        gnode = msg.graph.add(id=nid, class_type=node["class_type"])
        for name, value in node["inputs"].items():
            if not (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)):
                gnode.inputs.add(name=name, value=str(value))
    return msg


def memory_fields(memory: dict) -> dict:
    """Felder des Speicherverlaufs, die MemoryTrace kennt."""
    names = set(media_pb2.MemoryTrace.DESCRIPTOR.fields_by_name)
    return {k: float(v) for k, v in memory.items() if k in names}


def _job_completed(row: dict, indexed: dict[str, str]) -> bytes:
    """Abgeschlossener Job; Ausgaben verweisen auf die indizierte Datei gleichen Inhalts (eine
    bitgleiche Wiederholung zeigt auf das vorhandene Medium), gelöschte entfallen."""
    data = row["data"]
    msg = comfy_pb2.JobCompleted(
        job_id=row["job_id"],
        workflow=row["workflow"],
        engine=row["engine"],
        result=comfy_pb2.JOB_RESULT_DONE
        if data.get("status") == "done"
        else comfy_pb2.JOB_RESULT_CANCELLED
        if data.get("cancelled")
        else comfy_pb2.JOB_RESULT_FAILED,
        error=data.get("error") or "",
        duration_s=float(data.get("duration_s") or 0),
        order_no=row["order_no"] or "",
    )
    for out in data.get("outputs") or []:
        path = indexed.get(out["sha256"])
        if path is None:  # vom Betreiber gelöscht (oder nicht in der Galerie)
            continue
        msg.outputs.add(path=path, sha256=out["sha256"], size=out["size"])
    msg.params.update({k: str(v) for k, v in (row.get("params") or {}).items()})
    for c in data.get("checks") or []:
        msg.checks.add(
            check=str(c.get("check", "")),
            status=str(c.get("status", "")),
            sface=float(c.get("sface", 0.0)),
            auraface=float(c.get("auraface", 0.0)),
            references=int(c.get("references", 0)),
            face_px=int(c.get("face_px", 0)),
            score=float(c.get("score", 0.0)),
        )
    return msg.SerializeToString()


def _payment(row: dict) -> wallet_pb2.Payment:
    return wallet_pb2.Payment(
        payment_id=row["id"],
        method=row["method"],
        asset=row["asset"],
        amount=row["amount"],
        eur=row["eur"] or 0.0,
        rate=row["rate"] or 0.0,
        rate_ms=row["rate_ms"] or 0,
        txid=row["txid"],
        confirmations=row["confirmations"],
        required_confirmations=row["required"],
        status=row["status"],
        order_no=row["order_no"] or "",
        customer_id=row["customer_id"] or 0,
        customer_no=row["customer_no"] or "",
        at_ms=_unix_ms(row["detected_at"]),
        network=row["network"],
    )


def _reference_item(row: dict) -> reference_pb2.ReferenceItem:
    return reference_pb2.ReferenceItem(
        reference_id=row["id"],
        path=row["path"],
        sha256=row["sha256"],
        kind=row["kind"],
        source=row["source"],
        created_ms=_unix_ms(row["created_at"]),
        analysis=row["analysis"],
    )


def _customer_summary(row: dict) -> channel_pb2.CustomerSummary:
    return channel_pb2.CustomerSummary(
        customer_id=row["id"],
        customer_no=row["customer_no"],
        display_name=row["display_name"] or "",
        kind=row["kind"],
        platforms=sorted(filter(None, (row["platforms"] or "").split(","))),
        last_text=row["last_text"] or "",
        last_platform=row["last_platform"] or "",
        last_ms=_unix_ms(row["last_at"]) if row["last_at"] else 0,
        unread=row["unread"] or 0,
        age_mark=row["age_mark"],
        handles=sorted(
            {v for pair in (row["handles"] or "").split("\x1e") for v in pair.split("\x1f") if v}
        ),
    )


def _conversation_item(row: dict, store: Store) -> channel_pb2.ConversationItem:
    item = channel_pb2.ConversationItem(
        item_id=row["id"],
        customer_id=row["customer_id"],
        platform=row["platform"],
        direction=row["direction"],
        text=row["text"],
        status=row["status"],
        at_ms=_unix_ms(row["sent_at"]),
        sender=(row["handle"] or "") if row["direction"] == "in" else "Darkfluenzer",
        error=row["error"] or "",
        read=bool(row["read_at"]) or row["direction"] == "out",
        conversation_id=row["conversation_id"],
        awaiting_start=row["direction"] == "system"
        and bool(row["origin_message_id"])
        and not row["order_id"],
    )
    if row["order_id"]:
        _fill_order(item.order, store, store.order_by_id(row["order_id"]))
    for att in row["attachments"]:
        item.attachments.add(
            kind=str(att.get("kind", "")),
            path=str(att.get("path", "")),
            mime=str(att.get("mime", "")),
            size=int(att.get("size") or 0),
            sha256=str(att.get("sha256", "")),
            status=str(att.get("status", "")),
            note=str(att.get("note", "")),
        )
    return item


def _window(adapter: Channel | None, ident: dict) -> dict:
    """Antwortfenster einer Identität (Unix-ms bis wann offen); ohne Fenster: keine Angabe."""
    if (
        adapter is None
        or not adapter.capabilities().reply_window
        or not ident["platform_conversation_id"]
    ):
        return {}
    now_ms = int(time.time() * 1000)
    partner = ident["platform_conversation_id"]
    left = adapter.window_remaining_ms(partner)
    human = adapter.window_remaining_ms(partner, human_agent=True)
    return {
        "window_until_ms": now_ms + left if left else 0,
        "human_until_ms": now_ms + human if human else 0,
    }


def _command_receipt(row: dict) -> commands_pb2.CommandReceipt:
    """Quittung eines Befehls aus dem Befehlsjournal (Zeile der Tabelle ``commands``)."""
    return commands_pb2.CommandReceipt(
        request_id=row["request_id"],
        status=_RECEIPT_STATUS[row["status"]],
        command=row["command"],
        entity=row["entity"],
        detail=row["detail"],
        version=row["version"],
    )


class MappersMixin:
    """Protobuf-Abbildungen und Ereignisseiten für den Stream; Teil von ``Cockpit``."""

    def read_customers(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.customer_events(after, limit)
        out = []
        for r in rows:
            summary = self.store.customers_overview(r["customer_id"])
            customer = (
                _customer_summary(summary[0])
                if summary
                else channel_pb2.CustomerSummary(customer_id=r["customer_id"])
            )  # entfernte Akte: nur die ID
            out.append(
                (
                    r["cursor"],
                    _unix_ms(r["committed_at"]),
                    channel_pb2.CustomerUpdated(customer=customer).SerializeToString(),
                )
            )
        return out, gap

    def read_conversation(
        self, after: int, limit: int
    ) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.message_events(after, limit)
        out = []
        for r in rows:
            item = self.store.conversation_item(r["message_id"])
            if item is None:
                continue
            out.append(
                (
                    r["cursor"],
                    _unix_ms(r["committed_at"]),
                    channel_pb2.ConversationEvent(
                        item=_conversation_item(item, self.store)
                    ).SerializeToString(),
                )
            )
        return out, gap

    def read_orders(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.order_events(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                order_pb2.OrderUpdated(
                    order_no=r["order_no"],
                    event=r["event"],
                    status=str(r["data"].get("status") or r["data"].get("new") or r["status"]),
                    seq=int(r["data"].get("seq") or 0),
                    kind=str(r["data"].get("kind") or ""),
                    detail=str(r["data"].get("detail") or ""),
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_payments(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.payment_events(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                wallet_pb2.PaymentUpdated(
                    payment=_payment(self.store.payment(r["payment_id"]))
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_media(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.media_events(after, limit)
        return [
            (r["cursor"], _unix_ms(r["committed_at"]), _media_item(r).SerializeToString())
            for r in rows
        ], gap

    def read_references(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.reference_events(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                reference_pb2.ReferenceAdded(
                    reference=_reference_item(self.store.reference(r["reference_id"]))
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_removed(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.media_removed(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                media_pb2.MediaRemoved(media_id=r["media_id"], path=r["path"]).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_receipts(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.receipts(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                commands_pb2.CommandReceipt(
                    request_id=r["request_id"],
                    status=_RECEIPT_STATUS[r["status"]],
                    command=r["command"],
                    entity=r["entity"],
                    detail=r["detail"],
                    version=r["version"],
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_jobs(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.finished_jobs(after, limit)
        indexed = self.store.media_path_by_sha() if rows else {}
        return [(r["id"], _unix_ms(r["created_at"]), _job_completed(r, indexed)) for r in rows], gap
