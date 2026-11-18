"""Dialogbetrieb (SP4 Schritt 6): Kundennachricht → registrierter Sprachworkflow (dieselbe aktive
Profilversion wie im KI-Studio) → Gates → geplante Antwort oder Entwurf mit Grund.

Automatisch geantwortet wird nur, wenn alles gilt: Text-KI und automatische Antworten der
Influencerin an, Automatik des Kontos an, Modus der Konversation ``auto``, KI-Hinweis gesendet
(fehlt er, geht zuerst der feste Text genau einmal raus), Akte nicht gesperrt, Antwortfenster
offen, Rechtsfreigabe für echte Kunden (E21) oder Konto im Testbetrieb. Beim Versand prüft
``_reply_gate`` frisch (wie bei Zustellungen). Keine sprachliche Regelprüfung in Python (E19)."""

from __future__ import annotations

import asyncio
import json

from ..media import models
from ..store import StoreError
from ..v1 import commands_pb2
from . import assessment, dialog, memory
from .base import _Call, log

LOCK_REASON = "Akte gesperrt (minderjährig vermutet)."


class ChatMixin:
    """Kundenzweig von ``_on_inbound`` und Befehl 54 ``outbox_control``; Teil von ``Cockpit``."""

    # ------------------------------------------------------------------ Eingang

    async def _dialog_entry(self, inbound) -> None:
        """Neue Kundennachricht: nie still scheitern (Karte mit Grund)."""
        try:
            await self._dialog(inbound)
        except Exception as exc:
            log.exception("Dialog: Nachricht %s nicht verarbeitet", inbound.message_id)
            self.store.add_system_card(
                inbound.conversation_id, f"KI-ANTWORT FEHLGESCHLAGEN · {exc or type(exc).__name__}"
            )
            self._message_changed(0)

    def _dialog_parts(self, conversation_id: int) -> tuple[dict, dict | None]:
        """Identität der Konversation und Influencerin ihres Kontos (nie die erste)."""
        platform, _account = self.store.conversation_account(conversation_id)
        cust = self.store.db.execute(
            "SELECT i.customer_id FROM channel_conversations c JOIN channel_identities i"
            " ON i.id = c.identity_id WHERE c.id = ?",
            (conversation_id,),
        ).fetchone()[0]
        ident = next(
            i for i in self.store.identities(cust) if i["conversation_id"] == conversation_id
        )
        figure_id = self.store.influencer_for_identity(ident)
        figure = next((f for f in self.store.influencers() if f["id"] == figure_id), None)
        return ident | {"platform": platform}, figure

    async def _dialog(self, inbound) -> None:
        conv = inbound.conversation_id
        ident, figure = self._dialog_parts(conv)
        if figure is None or not figure["text_ai"]:
            return  # Text-KI der Influencerin aus: nur anzeigen
        if self.store.conversation_mode(conv) == "manual":
            return  # Betreiber hat übernommen
        if self.store.age_mark(inbound.customer.id) == "under_18":
            return  # gesperrt: keine KI-Antwort
        for message_id in self.store.open_ai_replies(conv):  # neue Nachricht vor dem Senden
            if self.store.cancel_message(message_id, "neue Kundennachricht – neu erzeugt"):
                self._message_changed(message_id)
        await self._dialog_notice(conv, ident, figure)
        self._dialog_start(conv)

    def _dialog_start(self, conv: int, delay: float = 0.0) -> None:
        """Antwort im Hintergrund erzeugen; läuft schon eine Erzeugung, wird sie danach mit dem
        neuen Stand wiederholt (nie zwei Läufe je Konversation)."""
        state = self._dialog_state.setdefault(conv, {"task": None, "dirty": False})
        task = state["task"]
        if task is not None and not task.done():
            if state.get("generating"):
                state["dirty"] = True
                return
            task.cancel()  # noch im Wartefenster: neu beginnen
        state["task"] = asyncio.create_task(self._dialog_after(conv, delay))
        self._tasks.add(state["task"])
        state["task"].add_done_callback(self._tasks.discard)

    async def _dialog_after(self, conv: int, delay: float) -> None:
        state = self._dialog_state[conv]
        if delay > 0:
            await asyncio.sleep(delay)
        while True:
            state["generating"], state["dirty"] = True, False
            try:
                await self._dialog_reply(conv, state)
            except Exception as exc:
                log.exception("Dialog: Antwort für Konversation %s fehlgeschlagen", conv)
                self.store.add_system_card(conv, f"KI-ANTWORT FEHLGESCHLAGEN · {exc}")
                self._message_changed(0)
            finally:
                state["generating"] = False
            if not state["dirty"]:
                return

    # ------------------------------------------------------------------ KI-Hinweis

    def _notice_text(self, figure: dict) -> str:
        """Fester KI-Hinweis (E20): Text aus dem registrierten Sprachworkflow, solange der fehlt
        (Rechtsfreigabe E21) der feste Text im Influencerin-Profil; nie formuliert."""
        try:
            wf = self._text_workflow("")
        except models.ManifestError:
            return figure["ai_notice"].strip()
        return models.ai_notice_text(wf) or figure["ai_notice"].strip()

    def _auto_allowed(self, conv: int, ident: dict, figure: dict) -> str:
        """Leer, wenn automatisch gesendet werden darf; sonst der Grund."""
        if self.store.conversation_mode(conv) != "auto":
            return f"Modus der Konversation: {self.store.conversation_mode(conv)}."
        if not figure["auto_replies"]:
            return "Automatische Antworten der Influencerin sind aus."
        adapter = self._adapter(ident["platform"], ident["account"])
        if adapter is None or not adapter.automation:
            return "Automatik des Kanalkontos ist aus."
        acc = self.store.account_for(ident["platform"], ident["account"])
        if not self.cfg.dialog.public_contact_cleared and not (acc and acc["test_mode"]):
            return "Rechtsfreigabe für echte Kunden fehlt (E21) – Konto nicht im Testbetrieb."
        return ""

    async def _dialog_notice(self, conv: int, ident: dict, figure: dict) -> None:
        """Fehlt der KI-Hinweis, geht zuerst der feste Text genau einmal raus (Regel 12 b)."""
        if ident["ai_notice_status"] in ("sent", "queued", "sending", "unknown"):
            return
        text = self._notice_text(figure)
        if not text:
            if conv not in self._notice_missing:
                self._notice_missing.add(conv)
                self.store.add_system_card(
                    conv, "KI-HINWEIS FEHLT · fester Text (Workflow E20 bzw. Profil) – keine "
                    "automatische Antwort",
                )  # fmt: skip
                self._message_changed(0)
            return
        if self._auto_allowed(conv, ident, figure):
            return  # Betreiber sendet den Hinweis selbst (Knopf in der Akte)
        message_id = self.store.queue_ai_notice(ident["customer_id"], ident["id"], text)
        adapter = self._adapter(ident["platform"], ident["account"])
        if adapter is not None:
            adapter.wake.set()
        self._message_changed(message_id)

    # ------------------------------------------------------------------ Antwort

    async def _dialog_reply(self, conv: int, state: dict) -> None:
        ident, figure = self._dialog_parts(conv)
        if (
            figure is None
            or not figure["text_ai"]
            or self.store.conversation_mode(conv) == "manual"
        ):
            return
        customer = self.store.customer_by_id(ident["customer_id"])
        age_mark = self.store.age_mark(customer.id)
        if age_mark == "under_18":
            return
        persona = self.store.active_persona(figure["id"])
        if persona is None:
            self.store.add_system_card(conv, "KI-ANTWORT · kein aktives Profil der Influencerin")
            self._message_changed(0)
            return
        wf = self._text_workflow("")
        notice = ident["ai_notice_message_id"]  # fester Hinweis gehört nicht zum Gespräch
        turns = [
            t for t in self.store.dialog_turns(conv, self.cfg.dialog.chat_turns + 1)
            if t["id"] != notice
        ][-self.cfg.dialog.chat_turns :]  # fmt: skip
        tail = 0
        while tail < len(turns) and turns[len(turns) - 1 - tail]["direction"] == "in":
            tail += 1
        if not tail:
            return  # nichts Neues vom Kunden
        newest = [t["text"] for t in turns[len(turns) - tail :]]
        name = figure["name"]
        context = "\n".join(
            (f"Kunde: {t['text']}" if t["direction"] == "in" else f"{name}: {t['text']}")
            for t in turns[: len(turns) - tail]
        )
        message = "\n".join(newest)
        facts = dialog.facts_for(self.cfg, figure)
        chosen = memory.select(self.store, self.cfg, "customer", customer.id, 0, message)
        values = {k: persona["blocks"].get(k, "") for k in models.PROFILE_INPUTS}
        values |= {"context": context, "memory": memory.as_input(chosen), "facts": facts.text()}
        values |= {"message": message}
        values |= {k: v for k, v in persona["params"].items() if k in wf.params}
        adapter = self._adapter(ident["platform"], ident["account"])
        partner = ident["platform_conversation_id"]
        window = adapter.window_open(partner) if adapter is not None else True
        limit = getattr(getattr(adapter, "ig", None), "max_text_bytes", None)
        mode = self.store.conversation_mode(conv)
        context_gates = dialog.ReplyContext(
            # der Hinweis geht vor der Antwort raus (gleiche Konversation, ältere Nachricht)
            ai_notice_sent=ident["ai_notice_status"] in ("sent", "queued", "sending"),
            age_mark=age_mark,
            operator_active=mode == "manual",
            automation=True,  # Automatik/Modus entscheiden Entwurf oder Versand (unten)
            window_open=window,
            max_text_bytes=limit,
        )
        run = {
            "influencer_id": figure["id"],
            "persona_version": persona["id"],
            "customer_id": customer.id,
            "message": message,
            "context": {
                "turns": len(turns) - tail,
                "conversation": conv,
                "memory": [
                    {"id": m["id"], "level": m["level"], "reason": m["reason"]} for m in chosen
                ],
                "facts": len(figure["prices"]),
            },
        }
        previous = [t["text"] for t in turns if t["direction"] == "out"]
        error, run_id, typed = await self._llm_run(
            "chat", wf.key, values, run, facts, context_gates, previous
        )
        if typed is not None and typed.memory:
            area = ("customer", customer.id, 0)
            memory.apply_items(self.store, *area, list(typed.memory), source=f"Lauf #{run_id}")
        if error:
            self.store.add_system_card(conv, f"KI-ANTWORT FEHLGESCHLAGEN · {error}")
            self._message_changed(0)
            return
        if typed is not None and self._consequences(conv, customer.id, typed):
            return  # gesperrt: keine Antwort
        row = self.store.ai_run(run_id)
        if state.get("dirty"):  # neue Nachricht während der Erzeugung: verworfen, neu erzeugt
            message_id = self.store.queue_reply(
                customer.id, conv, row["answer"], status="draft", ai_run_id=run_id
            )
            self.store.cancel_message(message_id, "neue Kundennachricht während der Erzeugung")
            self._message_changed(message_id)
            return
        failed = [g["reason"] for g in self._gates_of(row) if not g["ok"]]
        why = failed + ([w] if (w := self._auto_allowed(conv, ident, figure)) else [])
        if not why:
            message_id = self.store.queue_reply(
                customer.id, conv, row["answer"], status="queued", ai_run_id=run_id,
                scheduled_at=self._reply_time(conv, figure, row["answer"]),
            )  # fmt: skip
            if adapter is not None:
                adapter.wake.set()
        else:
            message_id = self.store.queue_reply(
                customer.id, conv, row["answer"], status="draft", ai_run_id=run_id,
                reason="; ".join(why),
            )  # fmt: skip
        self._message_changed(message_id)

    def _reply_time(self, conv: int, figure: dict, text: str) -> str | None:
        """Sendezeit der Antwort (SP4 Schritt 7: Verhaltensprofil); ohne Profil sofort."""
        return None

    @staticmethod
    def _gates_of(row: dict) -> list[dict]:
        return json.loads(row.get("gates") or "[]")

    def _consequences(self, conv: int, customer_id: int, typed: assessment.Assessment) -> bool:
        """Autorisierte Folgen der Einstufung (SP4 Schritt 4); True = keine Antwort."""
        if typed.minor_hint:
            if assessment.apply_minor_lock(self.store, customer_id, conv, typed.minor_evidence):
                self._message_changed(0)
            return True
        if typed.explicit_wish:
            self.store.add_system_card(
                conv, "EXPLIZITER WUNSCH · kein Auftrag – Antwort nach der Strategie im Profil"
            )
        elif "offer_ready" in typed.consequences:
            wish = typed.wish.description or "–"
            self.store.add_system_card(conv, f"KAUFBEREIT · {wish} · Angebot folgt (SP5)")
        self._message_changed(0)
        return False

    # ------------------------------------------------------------------ Versand-Gate

    async def _reply_gate(self, item: dict) -> str:
        """Frische Prüfung einer KI-Antwort im Versandmoment; leer = senden. Vom Betreiber
        freigegebene Antworten prüfen nur die harten Gates (Hinweis, Sperre, Fenster)."""
        conv = item["conversation_id"]
        ident, figure = self._dialog_parts(conv)
        if self.store.age_mark(ident["customer_id"]) == "under_18":
            return LOCK_REASON
        notice = ident["ai_notice_message_id"]
        if notice and notice != item["id"] and ident["ai_notice_status"] != "sent":
            return "KI-Hinweis noch nicht gesendet."
        adapter = self._adapter(ident["platform"], ident["account"])
        if adapter is not None and not adapter.window_open(ident["platform_conversation_id"]):
            return "Antwortfenster ist geschlossen."
        if item.get("released") or figure is None:
            return ""
        return self._auto_allowed(conv, ident, figure)

    # ------------------------------------------------------------------ Befehl 54

    async def _outbox_control(self, msg: commands_pb2.OutboxControl, call: _Call) -> str:
        """Entwurf senden/verwerfen, geplante Antwort jetzt senden/zurückhalten, Modus setzen."""
        if msg.action == "set_mode":
            call.entity = f"conversation:{msg.conversation_id}"
            if not self.store.set_conversation_mode(msg.conversation_id, msg.mode, "Betreiber"):
                return ""
            if msg.mode == "manual":  # übernommen: geplante KI-Antworten zurückhalten
                for message_id in self.store.open_ai_replies(msg.conversation_id):
                    if self.store.message(message_id)["status"] == "queued":
                        self.store.hold_message(message_id, "Betreiber hat übernommen.")
                        self._message_changed(message_id)
            self._message_changed(0)
            return ""
        call.entity = f"message:{msg.message_id}"
        try:
            row = self.store.message(msg.message_id)
        except StoreError:
            return "Nachricht unbekannt."
        if row["direction"] != "out" or not row["ai_run_id"]:
            return "Nur KI-Antworten lassen sich so steuern."
        if msg.action == "discard":
            if not self.store.cancel_message(row["id"], "Betreiber: verworfen"):
                return "Nur Entwürfe und geplante Antworten lassen sich verwerfen."
        elif msg.action in ("send_draft", "send_now"):
            if msg.action == "send_draft" and row["status"] != "draft":
                return "Kein Entwurf."
            if msg.action == "send_now" and row["status"] != "queued":
                return "Keine geplante Antwort."
            text = msg.text.strip() or None
            self.store.release_message(row["id"], text, None)
            adapter = self._adapter(row["platform"], row["account"])
            if adapter is not None:
                adapter.wake.set()
        elif msg.action == "hold":
            self.store.hold_message(row["id"], "Betreiber: zurückgehalten")
        else:
            return "Unbekannte Aktion."
        self._message_changed(row["id"])
        return ""
