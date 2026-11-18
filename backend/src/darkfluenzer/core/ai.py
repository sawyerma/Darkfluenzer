"""KI-Studio (SP4 Schritt 1, E19, E26): Testnachricht an den registrierten Sprachworkflow mit einer
Profilversion der Influencerin; Lauf auf ComfyUI 2 über ``nodes/llm`` (isolierte Sitzung, SPEC-018),
Nachweis und Messwerte in ``ai_runs``, Ergebnis als EVENT ai.result.

Das Backend reicht die Blöcke der Profilversion unverändert an die gleichnamigen Eingänge, dazu
Verlauf der Studio-Sitzung und Geschäftsfakten aus SQLite (Daten, keine Sprachlogik)."""

from __future__ import annotations

import asyncio
import time

from ..media import models
from ..nodes import llm
from ..nodes.comfy import ComfyError
from ..v1 import ai_pb2, commands_pb2
from ..v1 import stream_pb2 as spb
from .base import _Call, _unix_ms, log

# technische Eingabe des Aufwärmlaufs (kein Kundentext); die Antwort wird nur gemessen
WARMUP_MESSAGE = "Hallo"


def _euro(cents: int) -> str:
    return f"{cents / 100:.2f}".replace(".", ",") + " €"


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

    def _facts(self, influencer: dict) -> str:
        """Geschäftsfakten aus SQLite: Preisliste der Influencerin (Zahlen, keine Formulierung)."""
        lines = []
        for p in influencer["prices"]:
            hd = (
                f", HD-Aufschlag {_euro(p['hd_surcharge_cents'])}"
                if p["hd_surcharge_cents"]
                else ""
            )
            lines.append(f"{p['product']}: {_euro(p['price_cents'])}{hd}")
        return "\n".join(lines)

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
        values |= {"context": context, "memory": "", "facts": self._facts(influencer)}
        values |= {"message": text, **params}
        call.entity = f"influencer:{influencer['id']}"
        run = {
            "influencer_id": influencer["id"],
            "persona_version": persona["id"],
            "session": session,
            "request_id": call.request_id,
            "message": text,
            "context": {"turns": len(turns), "memory": 0, "facts": len(influencer["prices"])},
        }
        task = asyncio.create_task(self._studio_run(wf.key, values, run))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ""

    async def _llm_run(self, kind: str, workflow: str, values: dict, run: dict) -> str:
        """Ein Sprachlauf auf ComfyUI 2 mit Nachweis in ``ai_runs``; liefert den Fehler (leer =
        ok). Während des Laufs ist er in Warteschlange und KI-Status zugeordnet; danach gilt die
        Engine der KI-Instanz als geladen."""
        wf = self.manifest.workflows[workflow]
        started = time.monotonic()
        fields: dict = {}
        error = ""
        prompt = ""

        def submitted(prompt_id: str) -> None:  # im Worker-Thread
            nonlocal prompt
            prompt = prompt_id
            self._llm_runs[prompt_id] = wf.title

        try:
            result = await asyncio.to_thread(
                llm.generate,
                self.cfg,
                self.manifest,
                workflow,
                values,
                timeout_s=self.cfg.ai.run_timeout_s,
                on_submit=submitted,
            )
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
        except (llm.LlmError, ComfyError, models.ManifestError, ValueError, OSError) as exc:
            error = str(exc) or type(exc).__name__
        except Exception as exc:  # Ergebnis muss immer festgehalten werden
            log.exception("Sprachlauf (%s) fehlgeschlagen", kind)
            error = f"Interner Fehler ({type(exc).__name__})"
        finally:
            self._llm_runs.pop(prompt, None)
        total_ms = round((time.monotonic() - started) * 1000)
        self.store.add_ai_run(kind, workflow, **run, **fields, total_ms=total_ms, error=error)
        self.hub.push_events(spb.TOPIC_AI_RESULT)
        self._ai_changed()
        return error

    def _ai_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_AI_STATUS, self._ai_status())
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
        self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())

    async def _studio_run(self, workflow: str, values: dict, run: dict) -> None:
        """Lauf im Hintergrund; danach ``ai_runs``, EVENT und Receipt (auch bei Fehler)."""
        error = await self._llm_run("studio", workflow, values, run)
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
        error = await self._llm_run("warmup", workflow, values, {"message": WARMUP_MESSAGE})
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
            )
            out.append(
                (
                    r["cursor"],
                    _unix_ms(r["created_at"]),
                    ai_pb2.AiResult(run=run).SerializeToString(),
                )
            )
        return out, gap
