"""KI-Studio (SP4 Schritt 1, E19, E26): Testnachricht an den registrierten Sprachworkflow mit einer
Profilversion der Influencerin; Lauf auf ComfyUI 2 über ``nodes/llm`` (isolierte Sitzung, SPEC-018),
Nachweis und Messwerte in ``ai_runs``, Ergebnis als EVENT ai.result.

Das Backend reicht die Blöcke der Profilversion unverändert an die gleichnamigen Eingänge, dazu
Verlauf der Studio-Sitzung und Geschäftsfakten aus SQLite (Daten, keine Sprachlogik)."""

from __future__ import annotations

import asyncio
import json
import time

from ..media import models
from ..nodes import llm
from ..nodes.comfy import ComfyError
from ..v1 import ai_pb2, commands_pb2, memory_pb2
from ..v1 import stream_pb2 as spb
from . import assessment, dialog, memory
from .base import _Call, _unix_ms, log


def memory_entry(r: dict) -> memory_pb2.MemoryEntry:
    return memory_pb2.MemoryEntry(
        memory_id=r["id"],
        scope=r["scope"],
        owner_id=r["owner_id"],
        session=r["session"],
        level=r["level"],
        text=r["text"],
        source=r["source"],
        origin=r["origin"],
        status=r["status"],
        replaced_by=r["replaced_by"] or 0,
        created_ms=_unix_ms(r["created_at"]),
        updated_ms=_unix_ms(r["updated_at"]),
    )


def _assessment_msg(a: assessment.Assessment) -> ai_pb2.Assessment:
    return ai_pb2.Assessment(
        minor_hint=a.minor_hint,
        minor_evidence=a.minor_evidence,
        explicit_wish=a.explicit_wish,
        purchase_readiness=a.purchase_readiness,
        readiness_evidence=a.readiness_evidence,
        wish_kind=a.wish.kind,
        wish_description=a.wish.description,
        wish_source=a.wish.source,
        intent=a.intent,
    )


# technische Eingabe des Aufwärmlaufs (kein Kundentext); die Antwort wird nur gemessen
WARMUP_MESSAGE = "Hallo"


class AiStudioMixin:
    """Befehle 49 ``studio_chat`` und 50 ``studio_session_reset``; EVENT ai.result."""

    def _text_workflow(self, key: str) -> models.Workflow:
        wf = self.manifest.workflows.get(key) if key else None
        if wf is None:
            wf = next((w for w in self.manifest.workflows.values() if w.text), None)
        if wf is None or wf.text is None:
            raise models.ManifestError("Kein registrierter Sprachworkflow (SP4 Schritt 1).")
        return wf

    def _persona_of(self, influencer_id: int, version: int) -> dict | None:
        if version == 0:
            return self.store.active_persona(influencer_id)
        return next(
            (v for v in self.store.persona_versions(influencer_id) if v["version"] == version), None
        )

    async def _studio_chat(self, msg: commands_pb2.StudioChat, call: _Call) -> str:
        text = msg.text.strip()
        if not text:
            return "Nachricht fehlt."
        influencer = next(
            (i for i in self.store.influencers() if i["id"] == msg.influencer_id), None
        )
        if influencer is None:
            return "Influencerin unbekannt."
        wf = self._text_workflow(msg.workflow)
        if not wf.enabled or wf.status == "GESPERRT":
            return f"{wf.title} ist deaktiviert oder gesperrt."
        if self.cfg.comfyui_ai is None:
            return "KI-Instanz (ComfyUI 2) ist nicht eingerichtet."
        persona = self._persona_of(influencer["id"], msg.version)
        if persona is None:
            return "Diese Profilversion gibt es nicht." if msg.version else "Kein aktives Profil."
        session = self.store.studio_session(influencer["id"])
        turns = self.store.studio_turns(influencer["id"], session, self.cfg.ai.studio_turns)
        name = influencer["name"]
        context = "\n".join(f"Kunde: {t['message']}\n{name}: {t['answer']}" for t in turns)
        params = {k: v for k, v in persona["params"].items() if k in wf.params}
        values = {k: persona["blocks"].get(k, "") for k in models.PROFILE_INPUTS}
        facts = dialog.facts_for(self.cfg, influencer)  # Preise und freigegebene Zahlungswege
        # Gedächtnis der Studio-Sitzung (SP4 Schritt 5): Auswahl nach Zahlen aus [ai.memory]
        chosen = memory.select(self.store, self.cfg, "studio", influencer["id"], session, text)
        values |= {"context": context, "memory": memory.as_input(chosen), "facts": facts.text()}
        values |= {"message": text, **params}
        call.entity = f"influencer:{influencer['id']}"
        run = {
            "influencer_id": influencer["id"],
            "persona_version": persona["id"],
            "session": session,
            "request_id": call.request_id,
            "message": text,
            "context": {
                "turns": len(turns),
                "memory": [
                    {"id": m["id"], "level": m["level"], "reason": m["reason"]} for m in chosen
                ],
                "facts": len(influencer["prices"]),
            },
        }
        area = ("studio", influencer["id"], session)
        previous = [t["answer"] for t in turns]
        task = asyncio.create_task(self._studio_run(wf.key, values, run, facts, area, previous))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ""

    async def _llm_run(
        self,
        kind: str,
        workflow: str,
        values: dict,
        run: dict,
        facts: dialog.Facts | None = None,
        context: dialog.ReplyContext | None = None,
        previous: list[str] | None = None,
    ) -> tuple[str, int, assessment.Assessment | None]:
        """Ein Sprachlauf auf ComfyUI 2 mit Nachweis in ``ai_runs``; liefert den Fehler (leer =
        ok), die Lauf-ID und die typisierte Einstufung. Während des Laufs ist er in Warteschlange
        und KI-Status zugeordnet; danach gilt die Engine der KI-Instanz als geladen. Mit ``facts``
        (Antwort an einen Menschen): bei ungültiger Einstufung oder Wiederholung einer früheren
        Antwort (``previous``) neue Läufe (``[dialog] schema_retries``), danach die Gates."""
        wf = self.manifest.workflows[workflow]
        started = time.monotonic()
        fields: dict = {}
        error = ""
        prompt = ""
        attempts = 0
        typed: assessment.Assessment | None = None
        similar = 0.0

        def submitted(prompt_id: str) -> None:  # im Worker-Thread
            nonlocal prompt
            prompt = prompt_id
            self._llm_runs[prompt_id] = wf.title

        try:
            while True:
                attempts += 1
                result = await asyncio.to_thread(
                    llm.generate,
                    self.cfg,
                    self.manifest,
                    workflow,
                    values,
                    timeout_s=self.cfg.ai.run_timeout_s,
                    on_submit=submitted,
                )
                self._llm_runs.pop(prompt, None)
                schema = llm.parse_classification(result.classification)
                typed = assessment.parse(schema)[0]
                threshold = self.cfg.dialog.repeat_similarity
                similar = memory.repeats(result.answer, previous or [], threshold)
                if facts is None or (typed is not None and not similar):
                    break
                if attempts > self.cfg.dialog.schema_retries:
                    break
                log.info("Einstufung ungültig oder Wiederholung – neuer Lauf (%d)", attempts + 1)
            fields = {
                "workflow_sha": result.workflow_sha,
                "model_sha": result.model_sha,
                "system_prompt": result.system,
                "user_text": result.user,
                "answer": result.answer,
                "classification": result.classification,
                "prompt_id": result.prompt_id,
                "wait_ms": round(result.wait_s * 1000),
                "duration_ms": round(result.duration_s * 1000),
            }
            if (lane := self.lanes.get("ai")) is not None:
                lane.engine = wf.engine  # Modell geladen (Zulassung, STATE resources/ai.status)
            if not result.answer.strip():
                error = "Leere Antwort aus dem Sprachworkflow."
            elif facts is not None:
                gates = dialog.check(
                    result.answer, schema, facts, self.cfg.dialog.payment_terms, context
                )
                why = f"Antwort wiederholt eine frühere ({similar:.2f})." if similar else ""
                gates.append(dialog.Gate("repetition", not similar, why))
                fields["gates"] = [vars(g) for g in gates]
                fields["sendable"] = int(dialog.sendable(gates))
        except (llm.LlmError, ComfyError, models.ManifestError, ValueError, OSError) as exc:
            error = str(exc) or type(exc).__name__
        except Exception as exc:  # Ergebnis muss immer festgehalten werden
            log.exception("Sprachlauf (%s) fehlgeschlagen", kind)
            error = f"Interner Fehler ({type(exc).__name__})"
        finally:
            self._llm_runs.pop(prompt, None)
        total_ms = round((time.monotonic() - started) * 1000)
        run_id = self.store.add_ai_run(
            kind,
            workflow,
            **run,
            **fields,
            total_ms=total_ms,
            error=error,
            attempts=max(attempts, 1),
        )
        self.hub.push_events(spb.TOPIC_AI_RESULT)
        self._ai_changed()
        return error, run_id, None if error else typed

    def _ai_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_AI_STATUS, self._ai_status())
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
        self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())

    async def _studio_run(
        self,
        workflow: str,
        values: dict,
        run: dict,
        facts: dialog.Facts,
        area: tuple[str, int, int],
        previous: list[str],
    ) -> None:
        """Lauf im Hintergrund; danach ``ai_runs`` mit Gates, Gedächtnis-Einträge der Einstufung,
        EVENT und Receipt (auch bei Fehler). Im Studio gibt es keine Kanalidentität: geprüft werden
        Schema, Minderjährigkeit, Beträge, Zahlungswege und Wiederholung."""
        error, run_id, typed = await self._llm_run(
            "studio", workflow, values, run, facts, previous=previous
        )
        if typed is not None and typed.memory:
            memory.apply_items(self.store, *area, list(typed.memory), source=f"Lauf #{run_id}")
            self.hub.push_events(spb.TOPIC_MEMORY_CHANGED)
        self.store.finish_command(
            run["request_id"], "failed" if error else "completed", detail=error
        )
        self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)

    async def maybe_warmup(self) -> None:
        """Aufwärmlauf (BUG-061): einmal je Start der KI-Instanz, sobald sie antwortet und ein
        Sprachworkflow registriert ist; lädt Melody vor der ersten echten Nachricht."""
        lane = self.lanes.get("ai")
        if lane is None or not self.cfg.ai.warmup:
            return
        st = lane.status
        if not (st.get("health") and st.get("state") in ("running", "foreign")):
            self._warm_key = None  # nach dem nächsten Start erneut aufwärmen
            return
        key = f"{st.get('instance_id') or st.get('pid') or ''}:{st.get('started_at') or ''}"
        if key == self._warm_key:
            return
        usable = (w for w in self.manifest.workflows.values() if w.text and w.enabled)
        wf = next((w for w in usable if w.status != "GESPERRT"), None)
        if wf is None:
            return
        self._warm_key = key
        task = asyncio.create_task(self._warmup_run(wf.key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _warmup_run(self, workflow: str) -> None:
        values = {"message": WARMUP_MESSAGE, "max_tokens": self.cfg.ai.warmup_tokens}
        started = time.monotonic()
        error, _, _ = await self._llm_run("warmup", workflow, values, {"message": WARMUP_MESSAGE})
        self._warmup = {
            "ms": int(time.time() * 1000),
            "s": time.monotonic() - started,
            "error": error,
        }
        if error:
            log.warning("Aufwärmlauf der KI-Instanz fehlgeschlagen: %s", error)
        else:
            log.info("KI-Instanz aufgewärmt in %.1f s", self._warmup["s"])
        self._ai_changed()

    def _ai_status(self) -> bytes:
        """STATE ai.status: geladene Engine, bleibt geladen, laufende Sprachläufe, Aufwärmen,
        letzte Messwerte (ohne Inhalte)."""
        lane = self.lanes.get("ai")
        msg = ai_pb2.AiStatus(configured=lane is not None)
        if lane is not None:
            eng = self.manifest.engines.get(lane.engine)
            msg.engine = eng.title if eng else lane.engine
            msg.keep_loaded = lane.inst.keep_loaded
            msg.running = len(self._llm_runs)
        if self._warmup:
            msg.warmup_ms = self._warmup["ms"]
            msg.warmup_s = round(self._warmup["s"], 2)
            msg.warmup_error = self._warmup["error"]
        for r in self.store.recent_ai_runs(self.cfg.ai.status_runs):
            msg.recent.add(
                run_id=r["id"],
                kind=r["kind"],
                duration_s=(r["duration_ms"] or 0) / 1000,
                total_s=(r["total_ms"] or 0) / 1000,
                failed=bool(r["error"]),
                at_ms=_unix_ms(r["created_at"]),
            )
        return msg.SerializeToString()

    async def _studio_session_reset(self, msg: commands_pb2.StudioSessionReset, call: _Call) -> str:
        if not any(i["id"] == msg.influencer_id for i in self.store.influencers()):
            return "Influencerin unbekannt."
        session = self.store.reset_studio_session(msg.influencer_id)
        call.entity = f"influencer:{msg.influencer_id}:session:{session}"
        self.hub.set_state(spb.TOPIC_INFLUENCERS, self._influencers())  # neue Sitzung sichtbar
        return ""

    async def _memory_edit(self, msg: commands_pb2.MemoryEdit, call: _Call) -> str:
        """Gedächtnis von Hand (Befehl 52): Notiz anlegen, korrigieren (Verlauf bleibt) oder
        löschen; nur im angegebenen Bereich."""
        if msg.scope == "studio":
            if not any(i["id"] == msg.owner_id for i in self.store.influencers()):
                return "Influencerin unbekannt."
        elif msg.scope in ("customer", "test"):
            self.store.customer_by_id(msg.owner_id)
        else:
            return f"Bereich {msg.scope or '–'} unbekannt."
        area = (msg.scope, msg.owner_id, msg.session)
        if msg.memory_id:
            old = self.store.memory(msg.memory_id)
            if (old["scope"], old["owner_id"], old["session"]) != area:
                return "Erinnerung gehört zu einem anderen Bereich."
            if msg.delete:
                self.store.delete_memory(msg.memory_id, origin="operator")
                call.entity = f"memory:{msg.memory_id}"
            else:
                if not msg.text.strip():
                    return "Text fehlt."
                new = self.store.replace_memory(
                    msg.memory_id, msg.text, source="Betreiber", origin="operator"
                )
                call.entity = f"memory:{new}"
        else:
            if msg.delete or not msg.text.strip():
                return "Text fehlt."
            new = self.store.add_memory(
                *area, msg.level, msg.text, source="Betreiber", origin="operator"
            )
            call.entity = f"memory:{new}"
        self.hub.push_events(spb.TOPIC_MEMORY_CHANGED)
        return ""

    def read_memory_events(
        self, after: int, limit: int
    ) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.memory_events(after, limit)
        out = []
        for r in rows:
            changed = memory_pb2.MemoryChanged(entry=memory_entry(r), change=r["event"])
            out.append((r["cursor"], _unix_ms(r["committed_at"]), changed.SerializeToString()))
        return out, gap

    def read_ai_results(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.ai_results(after, limit)
        out = []
        for r in rows:
            run = ai_pb2.AiRun(
                run_id=r["id"],
                kind=r["kind"],
                request_id=r["request_id"],
                influencer_id=r["influencer_id"] or 0,
                persona_version=r["persona_number"] or 0,
                session=r["session"],
                message=r["message"],
                answer=r["answer"],
                classification=r["classification"],
                classification_valid=llm.parse_classification(r["classification"]) is not None,
                system_prompt=r["system_prompt"],
                user_text=r["user_text"],
                wait_s=(r["wait_ms"] or 0) / 1000,
                duration_s=(r["duration_ms"] or 0) / 1000,
                total_s=(r["total_ms"] or 0) / 1000,
                error=r["error"],
                workflow=r["workflow"],
                workflow_sha=r["workflow_sha"],
                model_sha=r["model_sha"],
                at_ms=_unix_ms(r["created_at"]),
                gates=[ai_pb2.GateCheck(**g) for g in json.loads(r["gates"] or "[]")],
                sendable=bool(r["sendable"]),
                attempts=r["attempts"],
            )
            typed, _ = assessment.parse(llm.parse_classification(r["classification"]))
            if typed is not None:
                run.assessment.CopyFrom(_assessment_msg(typed))
                run.consequences.extend(typed.consequences)
            out.append(
                (
                    r["cursor"],
                    _unix_ms(r["created_at"]),
                    ai_pb2.AiResult(run=run).SerializeToString(),
                )
            )
        return out, gap
