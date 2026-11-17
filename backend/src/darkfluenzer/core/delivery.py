"""Freigabe, Zustellkopie, Liefer-Gate (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
from pathlib import Path

from .. import approval
from ..media import aimeta
from ..store import StoreError, sha256_file
from ..v1 import (
    commands_pb2,
)
from .base import _Call, log


def _place_copy(src: Path, dst: Path, sha256: str) -> None:
    """Bytegleiche Kopie (Hash geprüft); eine vorhandene gleiche Kopie bleibt."""
    if dst.is_file() and sha256_file(dst) == sha256:
        return
    if sha256_file(src) != sha256:
        raise StoreError(f"{src.name}: Datei weicht vom Galerie-Eintrag ab.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


class DeliveryMixin:
    """Freigabe, Zustellkopie, Liefer-Gate; Teil von ``Cockpit``."""

    def _delivery_copy(self, order, master: Path) -> Path:
        """Gekennzeichnete Zustellkopie (Regel 12 d) im Ordner sent des Auftrags."""
        copy = self.store.order_dir(order) / "sent" / f"{order.order_no}{master.suffix.lower()}"
        aimeta.mark(master, copy)
        return copy

    def _queue_delivery(self, order, delivery_id: int, copy: Path) -> int:
        offer = self.store.offer(order.id)
        assert offer is not None
        conv = offer["conversation_id"]
        rel = copy.relative_to(self.cfg.local).as_posix()
        attachment = {
            "kind": "document",
            "path": rel,
            "status": "saved",
            "sha256": sha256_file(copy),
            "size": copy.stat().st_size,
            "mime": mimetypes.guess_type(copy.name)[0] or "",
        }
        return self.store.queue_outbound(
            order.customer_id,
            conv,
            "",
            revision=self.store.conversation_revision(conv),
            attachments=[attachment],
            delivery_id=delivery_id,
        )

    def _send_ready(self, order) -> str:
        offer = self.store.offer(order.id)
        if offer is None:
            return "Auftrag ohne Angebot – kein Zustellkanal."
        conv = self.store.conversation_platform(offer["conversation_id"])
        adapter = self._adapter(conv)
        if adapter is None or adapter.state != "READY":
            return f"{conv} ist nicht verbunden."
        return ""

    async def _approve_artifact(self, msg: commands_pb2.ApproveArtifact, call: _Call) -> str:
        """„Freigeben & senden“ (Befehl 34, V0 §8.4 Punkte 8–9): Freigabe und Zustellung hinter
        approval.py in einer Transaktion; Versand über den Postausgang."""
        call.entity = f"order:{msg.order_no}"
        order = self.store.order(msg.order_no)
        if order.source != "customer" or order.status != "review":
            return f"{msg.order_no} wartet nicht auf die Freigabe ({order.status})."
        if not msg.not_explicit:
            return "Bitte bestätigen: das Ergebnis ist nicht explizit."
        result = self._order_result(order)
        if result is None or result["id"] != msg.media_id:
            return "Freigeben lässt sich nur das fertige Ergebnis dieses Auftrags."
        if result["content_tier"] != "standard":
            return "Inhaltsstufe nicht standard – an Kunden nicht zustellbar (Regel 13)."
        if reason := self._send_ready(order):
            return reason
        src = self.cfg.local / result["path"]
        master = (
            self.store.order_dir(order) / "work" / f"{order.order_no}_ergebnis{src.suffix.lower()}"
        )
        await asyncio.to_thread(_place_copy, src, master, result["sha256"])
        copy = await asyncio.to_thread(self._delivery_copy, order, master)
        with self.store.tx():
            art = self.store.add_artifact(order.order_no, "master", master, job_id=result["job_id"])
            self.store.record_approval(order.order_no, art.id, "approved", "Betreiber")
            delivery = approval.prepare_delivery(
                self.store, order.order_no, art.id, order.customer_no
            )
            message_id = self._queue_delivery(order, delivery, copy)
            self._card(order, f"FREIGEGEBEN · {order.order_no} · Zustellung im Postausgang")
        call.entity = f"message:{message_id}"
        self._wake(order)
        self._orders_changed()
        self._message_changed(message_id)
        return ""

    async def _retry_delivery(self, msg: commands_pb2.RetryDelivery, call: _Call) -> str:
        """Erneut senden (Befehl 47) – nur nach endgültig fehlgeschlagener Zustellung."""
        call.entity = f"order:{msg.order_no}"
        order = self.store.order(msg.order_no)
        deliveries = self.store.deliveries(order.id)
        if order.status != "approved" or not deliveries or deliveries[-1]["status"] != "failed":
            return "Erneut senden nur nach endgültig fehlgeschlagener Zustellung."
        if reason := self._send_ready(order):
            return reason
        last = deliveries[-1]
        master = self.cfg.local / self.store.artifact(last["artifact_id"]).path
        copy = await asyncio.to_thread(self._delivery_copy, order, master)
        with self.store.tx():
            delivery = approval.prepare_delivery(
                self.store, order.order_no, last["artifact_id"], order.customer_no,
                attempt=len(deliveries),
            )  # fmt: skip
            message_id = self._queue_delivery(order, delivery, copy)
            self._card(order, f"ERNEUT GESENDET · {order.order_no} · Zustellung im Postausgang")
        call.entity = f"message:{message_id}"
        self._wake(order)
        self._orders_changed()
        self._message_changed(message_id)
        return ""

    def _delivery_gate(self, item: dict) -> str:
        """Letzte Prüfung im Versandmoment (Postausgang): Gate frisch gegen Datenbank und Datei,
        Zustellkopie unverändert und gekennzeichnet. Leer = senden."""
        delivery = self.store.delivery(item["delivery_id"])
        if delivery is None or delivery["status"] != "pending":
            return "Zustellung ist nicht mehr offen."
        gate = approval.check_gate(
            self.store, delivery["order_no"], delivery["artifact_id"], delivery["customer_no"]
        )
        if not gate.ok:
            return "Zustellung gesperrt: " + "; ".join(gate.reasons)
        for att in item["attachments"]:
            path = self.cfg.local / att["path"]
            if not path.is_file() or sha256_file(path) != att.get("sha256"):
                return "Zustellkopie fehlt oder wurde verändert."
            if not aimeta.is_marked(path):
                return "Zustellkopie ohne KI-Kennzeichnung."
        return ""

    def _delivery_update(self, message_id: int) -> None:
        """Versandausgang einer Zustellnachricht festschreiben (Karte VERSENDET bzw. Fehler)."""
        delivery = self.store.delivery_by_message(message_id)
        if delivery is None or delivery["status"] != "pending":
            return
        msg = self.store.message(message_id)
        order = self.store.order_by_id(delivery["order_id"])
        if msg["status"] == "sent":
            approval.confirm_sent(self.store, delivery["id"], msg["platform_message_id"] or "")
            self._card(order, f"VERSENDET · {order.order_no}")
        elif msg["status"] == "failed":
            if self.store.fail_delivery(delivery["id"], msg["error"] or ""):
                self._card(
                    order, f"ZUSTELLUNG FEHLGESCHLAGEN · {order.order_no} · {msg['error'] or ''}"
                )
        else:
            return
        self._orders_changed()

    def _settle_deliveries(self) -> None:
        """Nach einem Neustart: gesendete Zustellnachricht, deren Bestätigung fehlt."""
        for delivery_id, external in self.store.pending_sent_deliveries():
            try:
                approval.confirm_sent(self.store, delivery_id, external)
            except StoreError as exc:
                log.error("Zustellung %s: %s", delivery_id, exc)
