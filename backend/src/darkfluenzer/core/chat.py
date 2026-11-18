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
from datetime import UTC, datetime

from ..media import models
from ..store import StoreError
from ..v1 import commands_pb2
from ..v1 import stream_pb2 as spb
from . import assessment, behavior, dialog, memory
from .base import _Call, log

LOCK_REASON = "Akte gesperrt (minderjährig vermutet)."


class ChatMixin:
    """Kundenzweig von ``_on_inbound`` und Befehl 54 ``outbox_control``; Teil von ``Cockpit``."""

    # ------------------------------------------------------------------ Eingang

    async def _dialog_entry(self, inbound) -> bool:
        """Neue Kundennachricht: nie still scheitern (Karte mit Grund). True = der Dialog liest
        zur geplanten Lesezeit (der Kanal markiert dann nicht sofort gelesen)."""
        try:
            return await self._dialog(inbound)
        except Exception as exc:
            log.exception("Dialog: Nachricht %s nicht verarbeitet", inbound.message_id)
            self.store.add_system_card(
                inbound.conversation_id, f"KI-ANTWORT FEHLGESCHLAGEN · {exc or type(exc).__name__}"
            )
            self._message_changed(0)
            return False

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

    async def _dialog(self, inbound) -> bool:
        conv = inbound.conversation_id
        ident, figure = self._dialog_parts(conv)
        if figure is None or not figure["text_ai"]:
            return False  # Text-KI der Influencerin aus: nur anzeigen
        if self.store.conversation_mode(conv) == "manual":
            return False  # Betreiber hat übernommen
        if self.store.age_mark(inbound.customer.id) == "under_18":
            return False  # gesperrt: keine KI-Antwort
        for message_id in self.store.open_ai_replies(conv):  # neue Nachricht vor dem Senden
            if self.store.cancel_message(message_id, "neue Kundennachricht – neu erzeugt"):
                self._message_changed(message_id)
        await self._dialog_notice(conv, ident, figure)
        b = self._behavior(figure)
        last = self.store.last_sent_at(conv)
        state = self._dialog_state.setdefault(conv, {"task": None, "dirty": False})
        state["plan"] = behavior.plan(
            b, datetime.now().astimezone(),
            previous_out=datetime.fromisoformat(last) if last else None,
            first_contact=last is None,
            readiness=self.store.last_readiness(inbound.customer.id),
        )  # fmt: skip
        self._presence_start(conv, state["plan"])
        self._dialog_start(conv, delay=b.bundle_s)  # bündeln: eine Antwort für alle
        return True

    def _test_figure(self, ident: dict) -> dict | None:
        """Influencerin des Kundentests: die des Default-Kontakts, sonst die des Kontos."""
        chosen = self.store.default_contact()["influencer"]
        figures = self.store.influencers()
        found = next((f for f in figures if str(f["id"]) == chosen), None)
        if found is None:
            figure_id = self.store.influencer_for_identity(ident)
            found = next((f for f in figures if f["id"] == figure_id), None)
        return found

    async def _dialog_test(self, inbound) -> None:
        """Kundentest (SP4 Schritt 8): derselbe Dialog und derselbe registrierte Workflow wie bei
        Kunden, im eigenen Testverlauf des Default-Chats mit eigenem Gedächtnis je Sitzung."""
        conv = inbound.conversation_id
        self.store.mark_test(inbound.message_id)
        ident, _figure = self._dialog_parts(conv)
        figure = self._test_figure(ident)
        if figure is None:
            await self._reply_internal(conv, "Kundentest: keine Influencerin im Default-Kontakt.")
            return
        for message_id in self.store.open_ai_replies(conv):
            if self.store.cancel_message(message_id, "neue Testnachricht – neu erzeugt"):
                self._message_changed(message_id)
        default = self.store.default_contact()
        notice = default["test_notice_message_id"]
        if notice is None or self.store.message(notice)["status"] == "failed":
            text = self._notice_text(figure)
            if text:
                message_id = self.store.queue_test_notice(conv, text)
                adapter = self._adapter(ident["platform"], ident["account"])
                if adapter is not None:
                    adapter.wake.set()
                self._message_changed(message_id)
            else:
                self.store.add_system_card(conv, "KUNDENTEST · KI-Hinweistext fehlt (E20/E21)")
                self._message_changed(0)
        state = self._dialog_state.setdefault(conv, {"task": None, "dirty": False})
        state["test"] = True
        b = self._behavior(figure)
        if default["test_delay"]:  # „Verzögerung wie Kunde“
            last = self.store.last_sent_at(conv)
            state["plan"] = behavior.plan(
                b, datetime.now().astimezone(),
                previous_out=datetime.fromisoformat(last) if last else None,
                first_contact=last is None, readiness=0,
            )  # fmt: skip
            self._dialog_start(conv, delay=b.bundle_s)
        else:
            state["plan"] = None
            self._dialog_start(conv)

    async def _test_reset(self, msg: commands_pb2.TestReset, call: _Call) -> str:
        """Kundentest zurücksetzen (Befehl 63): Testgedächtnis und Hinweisstatus leer."""
        default = self.store.default_contact()
        call.entity = f"customer:{default['customer_id']}"
        figure = next(
            (f for f in self.store.influencers() if str(f["id"]) == default["influencer"]), None
        )
        session = self.store.test_reset(figure["id"] if figure else None)
        conv = self.store.default_conversation()
        if conv is not None:
            self.store.add_system_card(conv, f"KUNDENTEST ZURÜCKGESETZT · Sitzung {session}")
        self._message_changed(0)
        self.hub.push_events(spb.TOPIC_MEMORY_CHANGED)
        return ""

    def _behavior(self, figure: dict) -> behavior.Behavior:
        """Verhaltensprofil: Startwerte aus ``[behavior]``, darüber das aktive Profil."""
        base = behavior.build(behavior.Behavior(), self.cfg.behavior)
        if isinstance(base, str):
            log.error("Konfiguration [behavior]: %s – Vorgaben gelten", base)
            base = behavior.Behavior()
        own = behavior.build(base, self.store.behavior_of(figure["id"])[1])
        return own if isinstance(own, behavior.Behavior) else base

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
        watch = asyncio.create_task(self._consolation_watch(conv, state))
        try:
            await self._dialog_loop(conv, state)
        finally:
            watch.cancel()

    async def _dialog_loop(self, conv: int, state: dict) -> None:
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

    def _dialog_frame(self, conv: int, state: dict) -> dict | None:
        """Rahmen eines Laufs: Kunde (Akte, Kundengedächtnis) oder Kundentest im Default-Chat
        (eigener Verlauf, Testgedächtnis je Sitzung, nie Sperre der internen Akte; SP4 Schritt 8).
        None = keine Antwort."""
        ident, figure = self._dialog_parts(conv)
        if state.get("test"):
            default = self.store.default_contact()
            figure = self._test_figure(ident)
            if figure is None:
                return None
            notice = default["test_notice_message_id"]
            status = self.store.message(notice)["status"] if notice else None
            return {
                "ident": ident, "figure": figure, "customer_id": default["customer_id"],
                "age_mark": "", "notice": notice, "notice_status": status, "test": True,
                "memory": ("test", figure["id"], default["test_session"]),
                "kind": "test", "session": default["test_session"],
            }  # fmt: skip
        if (
            figure is None
            or not figure["text_ai"]
            or self.store.conversation_mode(conv) == "manual"
        ):
            return None
        age_mark = self.store.age_mark(ident["customer_id"])
        if age_mark == "under_18":
            return None
        return {
            "ident": ident, "figure": figure, "customer_id": ident["customer_id"],
            "age_mark": age_mark, "notice": ident["ai_notice_message_id"],
            "notice_status": ident["ai_notice_status"], "test": False,
            "memory": ("customer", ident["customer_id"], 0), "kind": "chat", "session": 0,
        }  # fmt: skip

    async def _dialog_reply(self, conv: int, state: dict) -> None:
        frame = self._dialog_frame(conv, state)
        if frame is None:
            return
        ident, figure, test = frame["ident"], frame["figure"], frame["test"]
        persona = self.store.active_persona(figure["id"])
        if persona is None:
            self.store.add_system_card(conv, "KI-ANTWORT · kein aktives Profil der Influencerin")
            self._message_changed(0)
            return
        wf = self._text_workflow("")
        limit_turns = self.cfg.dialog.chat_turns
        turns = [
            t for t in self.store.dialog_turns(conv, limit_turns + 1, test=test)
            if t["id"] != frame["notice"]  # fester Hinweis gehört nicht zum Gespräch
        ][-limit_turns:]  # fmt: skip
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
        chosen = memory.select(self.store, self.cfg, *frame["memory"], message)
        values = {k: persona["blocks"].get(k, "") for k in models.PROFILE_INPUTS}
        values |= {"context": context, "memory": memory.as_input(chosen), "facts": facts.text()}
        values |= {"message": message}
        values |= {k: v for k, v in persona["params"].items() if k in wf.params}
        adapter = self._adapter(ident["platform"], ident["account"])
        partner = ident["platform_conversation_id"]
        window = adapter.window_open(partner) if adapter is not None else True
        limit = getattr(getattr(adapter, "ig", None), "max_text_bytes", None)
        mode = "auto" if test else self.store.conversation_mode(conv)
        context_gates = dialog.ReplyContext(
            # der Hinweis geht vor der Antwort raus (gleiche Konversation, ältere Nachricht)
            ai_notice_sent=frame["notice_status"] in ("sent", "queued", "sending"),
            age_mark=frame["age_mark"],
            operator_active=mode == "manual",
            automation=True,  # Automatik/Modus entscheiden Entwurf oder Versand (unten)
            window_open=window,
            max_text_bytes=limit,
        )
        run = {
            "influencer_id": figure["id"],
            "persona_version": persona["id"],
            "customer_id": frame["customer_id"],
            "session": frame["session"],
            "message": message,
            "context": {
                "turns": len(turns) - tail,
                "conversation": conv,
                "test": test,
                "memory": [
                    {"id": m["id"], "level": m["level"], "reason": m["reason"]} for m in chosen
                ],
                "facts": len(figure["prices"]),
            },
        }
        previous = [t["text"] for t in turns if t["direction"] == "out"]
        error, run_id, typed = await self._llm_run(
            frame["kind"], wf.key, values, run, facts, context_gates, previous
        )
        if typed is not None and typed.memory:
            source = f"Lauf #{run_id}"
            memory.apply_items(self.store, *frame["memory"], list(typed.memory), source=source)
        if error:
            self.store.add_system_card(conv, f"KI-ANTWORT FEHLGESCHLAGEN · {error}")
            self._message_changed(0)
            return
        if typed is not None and self._consequences(conv, frame, typed):
            return  # gesperrt bzw. im Test: Hinweis auf Minderjährigkeit, keine Antwort
        row = self.store.ai_run(run_id)
        customer_id = frame["customer_id"]
        if state.get("dirty"):  # neue Nachricht während der Erzeugung: verworfen, neu erzeugt
            message_id = self.store.queue_reply(
                customer_id, conv, row["answer"], status="draft", ai_run_id=run_id, test=test
            )
            self.store.cancel_message(message_id, "neue Kundennachricht während der Erzeugung")
            self._message_changed(message_id)
            return
        failed = [g["reason"] for g in self._gates_of(row) if not g["ok"]]
        allowed = "" if test else self._auto_allowed(conv, ident, figure)
        why = failed + ([allowed] if allowed else [])
        if not why:
            when = self._reply_time(conv, figure, row["answer"])
            if test and not self.store.default_contact()["test_delay"]:
                when = None  # Kundentest ohne „Verzögerung wie Kunde“: sofort
            message_id = self.store.queue_reply(
                customer_id, conv, row["answer"], status="queued", ai_run_id=run_id,
                scheduled_at=when, test=test,
            )  # fmt: skip
            if adapter is not None:
                adapter.wake.set()
        else:
            message_id = self.store.queue_reply(
                customer_id, conv, row["answer"], status="draft", ai_run_id=run_id,
                reason="; ".join(why), test=test,
            )  # fmt: skip
        self._message_changed(message_id)
        if self._fill is None or self._fill.done():  # Vertröst-Texte nachlegen (Leerlauf)
            self._fill = asyncio.create_task(self._fill_consolations(figure))
            self._tasks.add(self._fill)
            self._fill.add_done_callback(self._tasks.discard)

    def _reply_time(self, conv: int, figure: dict, text: str) -> str | None:
        """Sendezeit (SP4 Schritt 7): nach Lesen, Bedenken und Tippen laut Verhaltensprofil."""
        plan = self._dialog_state.get(conv, {}).get("plan")
        if plan is None:
            return None
        when = behavior.send_at(self._behavior(figure), plan, text, datetime.now().astimezone())
        return when.astimezone(UTC).isoformat(timespec="milliseconds")

    # ------------------------------------------------------------------ Lesen, Tippen, Online

    def _presence_start(self, conv: int, plan: behavior.Plan) -> None:
        state = self._dialog_state[conv]
        old = state.get("presence")
        if old is not None and not old.done():
            old.cancel()
        state["presence"] = asyncio.create_task(self._presence(conv, plan))
        self._tasks.add(state["presence"])
        state["presence"].add_done_callback(self._tasks.discard)

    async def _presence(self, conv: int, plan: behavior.Plan) -> None:
        """Gelesen zur geplanten Lesezeit, danach online und Tippanzeige bis zum Senden (BUG-096);
        ohne KI-Antwort in Arbeit wieder offline."""
        ident, _figure = self._dialog_parts(conv)
        adapter = self._adapter(ident["platform"], ident["account"])
        partner = ident["platform_conversation_id"]
        if adapter is None:
            return
        online = False
        try:
            await asyncio.sleep(
                max(0.0, (plan.read_at - datetime.now().astimezone()).total_seconds())
            )
            await adapter.mark_read(partner, self.store.last_inbound_ids(conv))
            online = await adapter.set_online(True)
            if online:
                self._online[adapter.key] = self._online.get(adapter.key, 0) + 1
            pause = (plan.think_until - datetime.now().astimezone()).total_seconds()
            await asyncio.sleep(max(0.0, pause))
            while self._reply_pending(conv):
                await adapter.set_typing(partner, True)
                await asyncio.sleep(4.0)
        finally:
            if online:
                self._online[adapter.key] -= 1
                if self._online[adapter.key] <= 0:
                    await adapter.set_online(False)

    def _reply_pending(self, conv: int) -> bool:
        """Antwort in Arbeit: Erzeugung läuft oder eine geplante KI-Antwort wartet."""
        state = self._dialog_state.get(conv, {})
        task = state.get("task")
        if task is not None and not task.done():
            return True
        return any(
            self.store.message(m)["status"] == "queued" for m in self.store.open_ai_replies(conv)
        )

    # ------------------------------------------------------------------ Vertröstung

    async def _consolation_watch(self, conv: int, state: dict) -> None:
        """Ist die Antwort zur geplanten Zeit plus ``max_wait_s`` nicht fertig, geht ein vorab
        erzeugter Vertröst-Text raus (höchstens ``consolations_per_day`` je Gespräch)."""
        ident, figure = self._dialog_parts(conv)
        plan = state.get("plan")
        if figure is None or plan is None:
            return
        b = self._behavior(figure)
        due = (plan.think_until - datetime.now().astimezone()).total_seconds() + b.max_wait_s
        await asyncio.sleep(max(0.0, due))
        if not state.get("generating") or self._auto_allowed(conv, ident, figure):
            return
        if self.store.consolations_today(conv) >= b.consolations_per_day:
            return
        persona = self.store.active_persona(figure["id"])
        found = self.store.take_consolation(persona["id"]) if persona else None
        if found is None:
            return
        cid, text, run_id = found
        message_id = self.store.queue_reply(
            ident["customer_id"], conv, text, status="queued", ai_run_id=run_id
        )
        self.store.mark_consolation_used(cid, message_id)
        adapter = self._adapter(ident["platform"], ident["account"])
        if adapter is not None:
            adapter.wake.set()
        self._message_changed(message_id)

    async def _fill_consolations(self, figure: dict) -> None:
        """Vertröst-Texte im Leerlauf vorab erzeugen: derselbe registrierte Workflow mit der
        Profilanweisung ``consolation`` als Nachricht (keine Sprachregel in Python, E19)."""
        persona = self.store.active_persona(figure["id"])
        if persona is None or not persona["blocks"].get("consolation", "").strip():
            return
        b = self._behavior(figure)
        wf = self._text_workflow("")
        while self.store.consolation_stock(persona["id"]) < b.consolation_stock:
            values = {k: persona["blocks"].get(k, "") for k in models.PROFILE_INPUTS}
            facts = dialog.facts_for(self.cfg, figure).text()
            values |= {"context": "", "memory": "", "facts": facts}
            values["message"] = persona["blocks"]["consolation"]
            values |= {k: v for k, v in persona["params"].items() if k in wf.params}
            run = {
                "influencer_id": figure["id"],
                "persona_version": persona["id"],
                "message": "(Vertröstung vorab)",
                "context": {"consolation": True},
            }
            error, run_id, _typed = await self._llm_run("chat", wf.key, values, run)
            answer = self.store.ai_run(run_id).get("answer", "")
            if error or not answer.strip():
                return
            self.store.add_consolation(persona["id"], answer, run_id)

    @staticmethod
    def _gates_of(row: dict) -> list[dict]:
        return json.loads(row.get("gates") or "[]")

    def _consequences(self, conv: int, frame: dict, typed: assessment.Assessment) -> bool:
        """Autorisierte Folgen der Einstufung (SP4 Schritt 4); True = keine Antwort. Im Kundentest
        nur Karten (die interne Akte wird nie gesperrt)."""
        prefix = "TEST · " if frame["test"] else ""
        if typed.minor_hint:
            if frame["test"]:
                evidence = f" · Beleg: {typed.minor_evidence}" if typed.minor_evidence else ""
                self.store.add_system_card(
                    conv, f"{prefix}SPERRE wäre gesetzt (minderjährig vermutet){evidence}"
                )
            elif assessment.apply_minor_lock(
                self.store, frame["customer_id"], conv, typed.minor_evidence
            ):
                pass
            self._message_changed(0)
            return True
        if typed.explicit_wish:
            self.store.add_system_card(
                conv, f"{prefix}EXPLIZITER WUNSCH · kein Auftrag – Antwort nach der Strategie"
            )
        elif "offer_ready" in typed.consequences:
            wish = typed.wish.description or "–"
            self.store.add_system_card(conv, f"{prefix}KAUFBEREIT · {wish} · Angebot folgt (SP5)")
        self._message_changed(0)
        return False

    # ------------------------------------------------------------------ Versand-Gate

    async def _reply_gate(self, item: dict) -> str:
        """Frische Prüfung einer KI-Antwort im Versandmoment; leer = senden. Vom Betreiber
        freigegebene Antworten prüfen nur die harten Gates (Hinweis, Sperre, Fenster)."""
        conv = item["conversation_id"]
        ident, figure = self._dialog_parts(conv)
        if item.get("test"):  # Kundentest: nur der Testhinweis muss vorher raus
            notice = self.store.default_contact()["test_notice_message_id"]
            if notice and notice != item["id"] and self.store.message(notice)["status"] != "sent":
                return "KI-Hinweis des Kundentests noch nicht gesendet."
            return ""
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
