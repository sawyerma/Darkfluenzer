"""Ausnahmeweg Handy (SP5 Schritt 11, bisher C5.10).

Wartet ein Kundenauftrag auf den Betreiber, geht eine Vorschau (Ergebnis plus Grund) in den
Default-Chat über Telegram. Die Wörter aus dem Default-Kontakt (Freigeben, Neu, Erstatten) wirken
nur als Telegram-Antwort auf genau diese Vorschau und nur von der verifizierten Default-Identität;
je Vorschau genau eine Entscheidung. Ohne Antwortbezug fragt das Backend zurück. Erstatten verlangt
eine zweite Antwort mit der Auftragsnummer. Freigeben wirkt nie gegen harte Gates (Inhaltsstufe,
Zahlung, gesperrte Akte – die prüft die gemeinsame Freigabe ``_approve`` bzw. das Liefer-Gate).
"""

from __future__ import annotations

import re

from ..media.pipeline import PipelineError
from ..store import StoreError
from .base import log
from .orders import regenerate_candidates

ORDER_NO = re.compile(r"DF-O-\d{6}")


class PhoneMixin:
    """Freigabe vom Handy; Teil von ``Cockpit``."""

    async def _phone_preview(self, order, reason: str) -> None:
        """Vorschau des wartenden Auftrags in den Default-Chat (Telegram), höchstens einmal je
        Ergebnis; nur mit eingeschalteter „Freigabe vom Handy“."""
        default = self.store.default_contact()
        if not default.get("phone_approval"):
            return
        conv = self.store.default_conversation("telegram")
        if conv is None:
            return
        result = self._order_result(order)
        media_id = result["id"] if result else None
        if self.store.open_phone_preview(order.id, media_id) is not None:
            return
        offer = self.store.offer(order.id) or {}
        words = " · ".join(default[k] for k in ("approve_word", "redo_word", "refund_word"))
        text = (
            f"FREIGABE? {order.order_no} · {offer.get('product', order.request)} · {reason}\n"
            f"Antwort auf diese Nachricht: {words}"
        )
        files = [result["path"]] if result else []
        message_id, _blocked = await self._reply_internal(conv, text, files, block_card=False)
        self.store.add_phone_preview(message_id, order.id, media_id, reason)
        self._card(order, f"VORSCHAU AUFS HANDY · {order.order_no} · {reason}")

    async def _phone_decision(self, conv: int, msg: dict) -> bool:
        """Antwort im Default-Chat auswerten; True = als Handy-Entscheidung behandelt."""
        default = self.store.default_contact()
        if not default.get("phone_approval"):
            return False
        said = (msg.get("text") or "").strip()
        words = {
            default["approve_word"].strip().lower(): "approve",
            default["redo_word"].strip().lower(): "redo",
            default["refund_word"].strip().lower(): "refund",
        }
        kind = words.get(said.lower())
        number = said.upper() if ORDER_NO.fullmatch(said.upper()) else ""
        reply = msg.get("reply_to_platform_id")
        preview = self.store.phone_preview_for_reply(conv, reply) if reply else None
        if preview is None:
            if (kind or number) and self.store.open_phone_previews():
                await self._reply_internal(
                    conv, "Bitte als Antwort auf die Vorschau des Auftrags senden."
                )
                return True
            return False
        if not self.store.identity_verified(conv):
            await self._reply_internal(conv, "Default-Identität ist nicht verifiziert.")
            return True
        order = self.store.order_by_id(preview["order_id"])
        if preview["decision"] in ("approved", "regenerate", "refunded"):
            await self._reply_internal(conv, f"{order.order_no}: schon entschieden.")
            return True
        if kind == "approve":
            text = await self._phone_approve(order, preview)
        elif kind == "redo":
            text = await self._phone_redo(order, preview)
        elif kind == "refund":
            self.store.decide_phone_preview(preview["message_id"], "refund_asked")
            text = (
                f"Zum Erstatten die Auftragsnummer {order.order_no} als Antwort auf die Vorschau "
                "senden."
            )
        elif number:
            if preview["decision"] != "refund_asked" or number != order.order_no:
                text = f"Erstatten: erst „{default['refund_word']}“, dann genau {order.order_no}."
            else:
                text = self._phone_refund(order, preview)
        else:
            text = "Antwort mit " + " · ".join(
                default[k] for k in ("approve_word", "redo_word", "refund_word")
            )
        await self._reply_internal(conv, text)
        self._orders_changed()
        self._message_changed(0)
        return True

    async def _phone_approve(self, order, preview: dict) -> str:
        if order.status != "review":
            return f"{order.order_no} wartet nicht auf die Freigabe ({order.status})."
        result = self._order_result(order)
        if result is None or result["id"] != preview["media_id"]:
            return f"{order.order_no}: Vorschau ist veraltet – neue Vorschau abwarten."
        if result["content_tier"] != "standard":  # hartes Gate, nie per Freigabe
            return f"{order.order_no}: Inhaltsstufe nicht standard – nicht zustellbar (Regel 13)."
        if reason := await self._approve(order, result, "Betreiber (Handy)"):
            return f"{order.order_no}: Freigabe gesperrt – {reason}"
        self.store.decide_phone_preview(preview["message_id"], "approved")
        log.info("Auftrag %s vom Handy freigegeben", order.order_no)
        return f"{order.order_no} freigegeben – Zustellung im Postausgang."

    async def _phone_redo(self, order, preview: dict) -> str:
        if order.status != "review":
            return f"{order.order_no} wartet nicht auf die Freigabe ({order.status})."
        try:
            with self.store.tx():
                self.store.transition(order.order_no, "producing", reason="Neu vom Handy")
                jobs = regenerate_candidates(
                    self.store, self.manifest, order.order_no,
                    video_max_s=self.cfg.production.video_max_s,
                )  # fmt: skip
        except (PipelineError, StoreError, IndexError) as exc:
            return f"{order.order_no}: Neu nicht möglich – {exc}"
        self.store.decide_phone_preview(preview["message_id"], "regenerate")
        self._enqueue(jobs)
        self._card(order, f"NEU VOM HANDY · {order.order_no} · {len(jobs)} Kandidat(en)")
        return f"{order.order_no}: neue Kandidaten werden erzeugt."

    def _phone_refund(self, order, preview: dict) -> str:
        try:
            self.store.transition(
                order.order_no, "refunded", reason="Erstattung vom Handy – Zahlung erstatten"
            )
        except StoreError as exc:
            return f"{order.order_no}: Erstatten nicht möglich – {exc}"
        self.store.decide_phone_preview(preview["message_id"], "refunded")
        self._card(order, f"ERSTATTET VOM HANDY · {order.order_no} · Zahlung manuell erstatten")
        self._wallet_changed()
        return f"{order.order_no} erstattet (Zahlung manuell zurücküberweisen)."
