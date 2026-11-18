"""Freigabe, Zustellkopie, Liefer-Gate (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from PIL import Image

from .. import approval
from ..media import aimeta, models
from ..store import StoreError, sha256_file
from ..v1 import (
    commands_pb2,
)
from . import dialog
from .base import _Call, _document_attachment, log

MB = 1024 * 1024


def _media_attachment(
    local: Path, path: Path, kind: str, *, self_destruct_s: int = 0, limit_mb: float | None = None
) -> dict:
    """Anhang der Zustellkopie nach Anhangart (SP5 Schritt 9: photo, video, document) mit
    Kanalgrenze; Arbeiter-Thread (liest die Datei)."""
    att = _document_attachment(local, path) | {"kind": kind}
    if kind == "photo":
        with Image.open(path) as im:
            att["width"], att["height"] = im.size
    if self_destruct_s:
        att["self_destruct_s"] = self_destruct_s
    size_mb = att["size"] / MB
    if limit_mb is not None and size_mb > limit_mb:
        raise StoreError(f"Zu groß für den Kanal ({size_mb:.1f} MB, Grenze {limit_mb:g} MB).")
    return att


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
        gesendete Kopie wird nie überschrieben (FABLE-006), der Dateiname bleibt die Nummer.
        Kanalformat (SP5 Schritt 9): WebP wird vor der Kennzeichnung zu PNG, WebM abgewiesen."""
        suffix = master.suffix.lower()
        if suffix == ".webm":
            raise StoreError("WebM wird nicht zugestellt – Video als MP4 erzeugen.")
        work = self.store.order_dir(order) / "sent" / str(attempt)
        if suffix == ".webp":
            converted = work / f"{order.order_no}_umgewandelt.png"
            converted.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(master) as im:
                im.save(converted, "PNG")
            master, suffix = converted, ".png"
        copy = work / f"{order.order_no}{suffix}"
        aimeta.mark(master, copy)
        return copy

    def _queue_delivery(self, order, delivery_id: int, attachment: dict, text: str = "") -> int:
        """Zustellnachricht mit vorher (im Arbeiter-Thread) berechnetem Anhang und Begleittext
        einreihen; Testaufträge im Testverlauf."""
        offer = self.store.offer(order.id)
        assert offer is not None
        conv = offer["conversation_id"]
        return self.store.queue_outbound(
            order.customer_id,
            conv,
            text,
            revision=self.store.conversation_revision(conv),
            attachments=[attachment],
            delivery_id=delivery_id,
            test=order.test,
        )

    def _delivery_kind(self, order, product: dict | None, caps) -> tuple[str, int]:
        """Anhangart aus dem Produkt (SP5 Schritt 9): Foto bzw. Video, Dokument nur mit der
        Zusatzleistung Originaldatei und nur, wo der Kanal Dateien kennt; selbstlöschend, wo der
        Kanal es kann (Zeit aus [telegram] self_destruct_s)."""
        kind = "video" if order.kind == "video" else "photo"
        if product and product.get("original_file") and caps.document:
            kind = "document"
        destruct = 0
        if product and product.get("self_destruct") and caps.self_destruct and self.cfg.telegram:
            destruct = self.cfg.telegram.self_destruct_s
        return kind, destruct

    async def _delivery_caption(self, order, offer: dict) -> str:
        """Begleittext: Formulierung aus dem Profilblock „delivery“ (E19), danach der KI-Hinweis
        der Influencerin wörtlich (Pflichtangabe, weil der Medienversand Metadaten entfernen
        kann). Ohne Block, bei Fehler oder verletztem Betrags-/Zahlungsweg-Gate nur der Hinweis."""
        _product, figure = self._order_figure(offer)
        if figure is None:
            return ""
        notice = (figure.get("ai_notice") or "").strip()
        persona = self.store.active_persona(figure["id"])
        block = (persona["blocks"].get("delivery", "") if persona else "").strip()
        answer = ""
        if persona is not None and block:
            wf = self._text_workflow("")
            values = {k: persona["blocks"].get(k, "") for k in models.PROFILE_INPUTS}
            values |= {
                "context": "",
                "memory": "",
                "facts": f"{offer['product']} wird jetzt zugestellt",
                "message": block,
            }
            values |= {k: v for k, v in persona["params"].items() if k in wf.params}
            run = {"influencer_id": figure["id"], "persona_version": persona["id"],
                   "customer_id": order.customer_id, "message": "(Begleittext der Zustellung)",
                   "context": {"order": order.order_no, "caption": True}}  # fmt: skip
            facts = dialog.facts_for(self.cfg, figure)
            error, run_id, _typed = await self._llm_run(
                "test" if order.test else "chat", wf.key, values, run, facts
            )
            row = self.store.ai_run(run_id) or {}
            bad = [g["reason"] for g in self._gates_of(row)
                   if g["name"] in ("amounts", "payment_ways") and not g["ok"]]  # fmt: skip
            if error or bad:
                self._card(order, f"BEGLEITTEXT VERWORFEN · {order.order_no} · {error or bad[0]}")
            else:
                answer = (row.get("answer") or "").strip()
        return "\n\n".join(p for p in (answer, notice) if p)

    def _window_closed(self, order) -> bool:
        """Antwortfenster der Plattform zu (Instagram 24 h)?"""
        offer = self.store.offer(order.id)
        if offer is None:
            return False
        ident, _figure = self._dialog_parts(offer["conversation_id"])
        adapter = self._adapter(ident["platform"], ident["account"])
        if adapter is None or not adapter.capabilities().reply_window:
            return False
        return not adapter.window_open(ident["platform_conversation_id"])

    async def _deliver(self, order, art) -> str:
        """Zustellung eines freigegebenen Artefakts: Kopie im Kanalformat, Anhangart aus dem
        Produkt, Begleittext, Gate (approval.py), Postausgang. Leer = eingereiht."""
        offer = self.store.offer(order.id)
        product, _figure = self._order_figure(offer or {})
        platform, account = self.store.conversation_account(offer["conversation_id"])
        adapter = self._adapter(platform, account)
        if adapter is None:
            return f"{platform} ist nicht verbunden."
        caps = adapter.capabilities()
        kind, destruct = self._delivery_kind(order, product, caps)
        attempt = len(self.store.deliveries(order.id))
        master = self.cfg.local / art.path
        try:
            disk_sha = await asyncio.to_thread(approval.file_sha, master)
            copy = await asyncio.to_thread(self._delivery_copy, order, master, attempt + 1)
            attachment = await asyncio.to_thread(
                _media_attachment, self.cfg.local, copy, kind, self_destruct_s=destruct,
                limit_mb=caps.max_attachment_mb.get(kind),
            )  # fmt: skip
        except (StoreError, OSError) as exc:
            self._card(order, f"ZUSTELLUNG GESPERRT · {order.order_no} · {exc}")
            self._message_changed(0)
            return str(exc)
        caption = await self._delivery_caption(order, offer)
        with self.store.tx():
            delivery = approval.prepare_delivery(
                self.store, order.order_no, art.id, order.customer_no, attempt=attempt,
                disk_sha=disk_sha,
            )  # fmt: skip
            message_id = self._queue_delivery(order, delivery, attachment, caption)
        self._wake(order)
        self._orders_changed()
        self._message_changed(message_id)
        return ""

    async def _resume_parked(self, conversation_id: int) -> None:
        """Kunde schreibt wieder (Instagram-Fenster offen): geparkte Zustellungen dieser
        Konversation gehen jetzt raus (awaiting_contact -> approved -> Postausgang)."""
        for order_no in self.store.parked_orders(conversation_id):
            order = self.store.transition(order_no, "approved", by="Kontakt")
            art = self.store.last_approved_artifact(order.id)
            if art is None:
                continue
            self._card(order, f"ZUSTELLUNG NACH KONTAKT · {order_no}")
            await self._deliver(order, art)

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
        reason = await self._approve(order, result, "Betreiber")
        if not reason:
            call.entity = f"order:{order.order_no}"
        return reason

    async def _approve(self, order, result: dict, approver: str, checks: dict | None = None) -> str:
        """Freigabe als Funktion mit Freigeber (SP5 Schritt 8): Master aus dem Ergebnis, Freigabe
        (System nur mit den vier Prüfwerten, Trigger), dann Zustellung bzw. Parken bei
        geschlossenem Antwortfenster. Leer = freigegeben."""
        if reason := self._send_ready(order):
            return reason
        src = self.cfg.local / result["path"]
        # Name nach Inhalt: ein neues Ergebnis nach „Neu“ überschreibt nie den alten Master
        name = f"{order.order_no}_ergebnis_{result['sha256'][:12]}{src.suffix.lower()}"
        master = self.store.order_dir(order) / "work" / name
        await asyncio.to_thread(_place_copy, src, master, result["sha256"])
        with self.store.tx():
            art = self.store.artifact_at(master) or self.store.add_artifact(
                order.order_no, "master", master, job_id=result["job_id"], sha256=result["sha256"]
            )  # Hash eben in _place_copy geprüft (FABLE-003); gleicher Inhalt: derselbe Master
            self.store.record_approval(order.order_no, art.id, "approved", approver, checks)
        order = self.store.order(order.order_no)
        if self._window_closed(order):  # Instagram-Fenster zu: Zustellung parkt (SP5 Schritt 9)
            self.store.transition(order.order_no, "awaiting_contact", by="Antwortfenster")
            text = f"ZUSTELLUNG WARTET AUF KONTAKT · {order.order_no} · Antwortfenster zu"
            self._card(order, text)
            self.store.notify_default(text)
            self._orders_changed()
            self._message_changed(0)
            return ""
        if reason := await self._deliver(order, art):
            return reason
        who = "durch das System" if approver == "System" else "durch den Betreiber"
        self._card(
            order, f"FREIGEGEBEN {who.upper()} · {order.order_no} · Zustellung im Postausgang"
        )
        self._message_changed(0)
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
        if reason := await self._deliver(order, self.store.artifact(last["artifact_id"])):
            return reason
        self._card(order, f"ERNEUT GESENDET · {order.order_no} · Zustellung im Postausgang")
        self._message_changed(0)
        return ""

    async def _delivery_gate(self, item: dict) -> str:
        """Letzte Prüfung im Versandmoment (Postausgang): Gate frisch gegen Datenbank und Datei,
        Zustellkopie unverändert und gekennzeichnet. Leer = senden. Datenbank im Hauptstrang,
        Dateien im Arbeiter-Thread (SP0 Schritt 5). KI-Antworten prüft ``_reply_gate``."""
        if item.get("ai_run_id") and not item.get("delivery_id"):
            return await self._reply_gate(item)
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
