"""Freigabe, Zustellkopie, Liefer-Gate (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from .. import approval
from ..media import aimeta
from ..store import StoreError, sha256_file
from ..v1 import (
    commands_pb2,
)
from .base import _Call, _document_attachment, log


def _place_copy(src: Path, dst: Path, sha256: str) -> None:
    """Bytegleiche Kopie (Hash geprüft); eine vorhandene gleiche Kopie bleibt, eine mit anderem
    Inhalt wird nie überschrieben (Artefakte sind unveränderlich, FABLE-006)."""
    if dst.is_file():
        if sha256_file(dst) == sha256:
            return
        raise StoreError(f"{dst.name}: Ziel existiert mit anderem Inhalt.")
    if sha256_file(src) != sha256:
        raise StoreError(f"{src.name}: Datei weicht vom Galerie-Eintrag ab.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _copies_intact(local: Path, attachments: list[dict]) -> str:
    """Zustellkopien unverändert und gekennzeichnet; leer = in Ordnung (Arbeiter-Thread)."""
    for att in attachments:
        path = local / att["path"]
        if not path.is_file() or sha256_file(path) != att.get("sha256"):
            return "Zustellkopie fehlt oder wurde verändert."
        if not aimeta.is_marked(path):
            return "Zustellkopie ohne KI-Kennzeichnung."
    return ""


class DeliveryMixin:
    """Freigabe, Zustellkopie, Liefer-Gate; Teil von ``Cockpit``."""

    def _delivery_copy(self, order, master: Path, attempt: int) -> Path:
        """Gekennzeichnete Zustellkopie (Regel 12 d) im Ordner sent/<Versuch> des Auftrags: eine
        gesendete Kopie wird nie überschrieben (FABLE-006), der Dateiname bleibt die Nummer."""
        name = f"{order.order_no}{master.suffix.lower()}"
        copy = self.store.order_dir(order) / "sent" / str(attempt) / name
        aimeta.mark(master, copy)
        return copy

    def _queue_delivery(self, order, delivery_id: int, attachment: dict) -> int:
        """Zustellnachricht mit vorher (im Arbeiter-Thread) berechnetem Anhang einreihen."""
        offer = self.store.offer(order.id)
        assert offer is not None
        conv = offer["conversation_id"]
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
        conv, account = self.store.conversation_account(offer["conversation_id"])
        adapter = self._adapter(conv, account)
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
        # Name nach Inhalt: ein neues Ergebnis nach „Neu“ überschreibt nie den alten Master
        name = f"{order.order_no}_ergebnis_{result['sha256'][:12]}{src.suffix.lower()}"
        master = self.store.order_dir(order) / "work" / name
        attempt = len(self.store.deliveries(order.id)) + 1
        await asyncio.to_thread(_place_copy, src, master, result["sha256"])
        copy = await asyncio.to_thread(self._delivery_copy, order, master, attempt)
        attachment = await asyncio.to_thread(_document_attachment, self.cfg.local, copy)
        with self.store.tx():
            art = self.store.artifact_at(master) or self.store.add_artifact(
                order.order_no, "master", master, job_id=result["job_id"], sha256=result["sha256"]
            )  # Hash eben in _place_copy geprüft (FABLE-003); gleicher Inhalt: derselbe Master
            self.store.record_approval(order.order_no, art.id, "approved", "Betreiber")
            delivery = approval.prepare_delivery(
                self.store, order.order_no, art.id, order.customer_no, disk_sha=result["sha256"]
            )
            message_id = self._queue_delivery(order, delivery, attachment)
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
        disk_sha = await asyncio.to_thread(approval.file_sha, master)
        copy = await asyncio.to_thread(self._delivery_copy, order, master, len(deliveries) + 1)
        attachment = await asyncio.to_thread(_document_attachment, self.cfg.local, copy)
        with self.store.tx():
            delivery = approval.prepare_delivery(
                self.store, order.order_no, last["artifact_id"], order.customer_no,
                attempt=len(deliveries), disk_sha=disk_sha,
            )  # fmt: skip
            message_id = self._queue_delivery(order, delivery, attachment)
            self._card(order, f"ERNEUT GESENDET · {order.order_no} · Zustellung im Postausgang")
        call.entity = f"message:{message_id}"
        self._wake(order)
        self._orders_changed()
        self._message_changed(message_id)
        return ""

    async def _delivery_gate(self, item: dict) -> str:
        """Letzte Prüfung im Versandmoment (Postausgang): Gate frisch gegen Datenbank und Datei,
        Zustellkopie unverändert und gekennzeichnet. Leer = senden. Datenbank im Hauptstrang,
        Dateien im Arbeiter-Thread (SP0 Schritt 5)."""
        delivery = self.store.delivery(item["delivery_id"])
        if delivery is None or delivery["status"] != "pending":
            return "Zustellung ist nicht mehr offen."
        master = self.cfg.local / self.store.artifact(delivery["artifact_id"]).path
        disk_sha = await asyncio.to_thread(approval.file_sha, master)
        delivery = self.store.delivery(item["delivery_id"])  # nach dem Warten frisch
        if delivery is None or delivery["status"] != "pending":
            return "Zustellung ist nicht mehr offen."
        gate = approval.check_gate(
            self.store, delivery["order_no"], delivery["artifact_id"], delivery["customer_no"],
            disk_sha=disk_sha,
        )  # fmt: skip
        if not gate.ok:
            return "Zustellung gesperrt: " + "; ".join(gate.reasons)
        return await asyncio.to_thread(_copies_intact, self.cfg.local, item["attachments"])

    def _delivery_update(self, message_id: int) -> None:
        """Versandausgang einer Zustellnachricht festschreiben (Karte VERSENDET bzw. Fehler)."""
        delivery = self.store.delivery_by_message(message_id)
        if delivery is None or delivery["status"] != "pending":
            return
        msg = self.store.message(message_id)
        order = self.store.order_by_id(delivery["order_id"])
        if msg["status"] == "sent":
            self._confirm_delivery(delivery["id"], msg["platform_message_id"] or "", order)
        elif msg["status"] == "failed":
            if self.store.fail_delivery(delivery["id"], msg["error"] or ""):
                self._card(
                    order, f"ZUSTELLUNG FEHLGESCHLAGEN · {order.order_no} · {msg['error'] or ''}"
                )
        else:
            return
        self._orders_changed()

    def _confirm_delivery(self, delivery_id: int, external_id: str, order=None) -> None:
        """Von der Plattform angenommen: festschreiben; ein danach verletztes Gate erscheint als
        Karte statt die Zustellung offen zu lassen (FABLE-012)."""
        reasons = approval.confirm_sent(self.store, delivery_id, external_id)
        if order is None:
            order = self.store.order(self.store.delivery(delivery_id)["order_no"])
        text = f"VERSENDET · {order.order_no}"
        if reasons:
            text += " · GATE NACH VERSAND: " + "; ".join(reasons)
        self._card(order, text)

    def _settle_deliveries(self) -> None:
        """Nach einem Neustart: gesendete Zustellnachricht, deren Bestätigung fehlt."""
        for delivery_id, external in self.store.pending_sent_deliveries():
            try:
                self._confirm_delivery(delivery_id, external)
            except StoreError as exc:
                log.error("Zustellung %s: %s", delivery_id, exc)
