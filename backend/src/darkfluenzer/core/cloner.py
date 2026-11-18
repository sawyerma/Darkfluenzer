"""Kloner der Default-Kette: Plan, Auftrag, Rückversand (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..core import cloner_text as cloner
from ..core import orders
from ..media import aimeta, models, pipeline
from ..nodes import comfy
from ..store import sha256_file
from ..v1 import (
    commands_pb2,
)
from .base import _Call, _document_attachment, log


def _upload_param(wf: models.Workflow) -> str:
    """Eingangsbild eines Workflows für den Kloner: ``image`` bzw. die Vorlage (``reference``)."""
    for name in ("image", "reference"):
        if name in wf.params and wf.params[name].upload:
            return name
    return next((n for n, p in wf.params.items() if p.upload), "")


def _marked_copy(local: Path, src: Path) -> dict:
    """Inhaltsadressierte, gekennzeichnete Kopie in ``channels/sent`` (bugs_v1 BUG-004: gleicher
    Name, anderer Inhalt -> andere Kopie); liest und schreibt ganze Dateien, daher im Thread."""
    digest = sha256_file(src)
    copy = local / "channels" / "sent" / f"{digest[:16]}_{src.stem}_ki{src.suffix.lower()}"
    if not (copy.is_file() and aimeta.is_marked(copy)):
        aimeta.mark(src, copy)
    return _document_attachment(local, copy)


class ClonerMixin:
    """Kloner der Default-Kette: Plan, Auftrag, Rückversand; Teil von ``Cockpit``."""

    async def _reply_internal(self, conversation_id: int, text: str, files: list[str] = ()) -> None:
        """Rückfrage bzw. Ergebnis an den Default-Nutzer in denselben Chat (Postausgang)."""
        default = self.store.default_contact()
        platform, account = self.store.conversation_account(conversation_id)
        attachments, blocked = [], []
        for rel in files:
            src = self.cfg.local / rel
            # Regel 13 (bugs_v1 BUG-003): `explizit` (auch unbekannt) nur an Default über Telegram
            media = self.store.media_by_path(rel)
            if platform != "telegram" and (media or {}).get("content_tier") != "standard":
                blocked.append(src.name)
                text += f"\n{src.name}: nicht gesendet (Inhaltsstufe explizit)"
                continue
            try:  # Hash, Kennzeichnung und Kopie im Arbeiter-Thread (SP0 Schritt 5, BUG-106)
                attachments.append(await asyncio.to_thread(_marked_copy, self.cfg.local, src))
            except (aimeta.AiMetaError, OSError) as exc:
                text += f"\n{src.name}: nicht gesendet ({exc})"
                continue
        if blocked:
            label = {"instagram": "Instagram", "whatsapp": "WhatsApp"}.get(platform, platform)
            self.store.add_system_card(
                conversation_id,
                f"RÜCKVERSAND GESPERRT · {', '.join(blocked)} · Inhaltsstufe explizit – über "
                f"{label} nie (Regel 13); explizite Ergebnisse nur an Default über Telegram",
            )
        message_id = self.store.queue_outbound(
            default["customer_id"],
            conversation_id,
            text,
            revision=self.store.conversation_revision(conversation_id),
            attachments=attachments,
        )
        adapter = self._adapter(platform, account)
        if adapter is not None:
            adapter.wake.set()
        self._message_changed(message_id)

    async def _cloner_entry(self, inbound) -> None:
        """Nachricht des Default-Kontakts in die Kloner-Weiche (SP1 Schritt 5): jede Ausnahme
        endet sichtbar als ``failed``. Ein Album mit Befehl wartet im Hintergrund, bis es ruhig
        ist – der Eingang seines Chats läuft derweil weiter (SP1 Schritte 3, 4)."""
        msg = self.store.message(inbound.message_id)
        if msg.get("album_id") and cloner.parse(msg["text"]) is not None:
            task = asyncio.create_task(self._cloner_guarded(inbound, album=True))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return
        await self._cloner_guarded(inbound)

    async def _cloner_guarded(self, inbound, *, album: bool = False) -> None:
        msg = self.store.message(inbound.message_id)
        parsed = cloner.parse(msg["text"])
        try:
            if album:
                await self._album_quiet(msg)
            await self._cloner(inbound)
        except Exception as exc:  # nie still: Karte und Antwort mit Grund
            log.exception("Kloner: Nachricht %s nicht verarbeitet", inbound.message_id)
            await self._cloner_state(
                inbound.conversation_id, "failed", parsed[0] if parsed else "auftrag",
                msg["platform"], str(exc) or type(exc).__name__,
            )  # fmt: skip

    async def _album_quiet(self, msg: dict) -> None:
        """Warten, bis seit dem letzten Bild des Albums ``album_settle_s`` vergangen sind und
        kein Anhang mehr lädt."""
        settle = self.cfg.cloner.album_settle_s
        for _ in range(int(600 / max(settle / 2, 0.05))):  # höchstens 10 min
            album = self.store.album_messages(msg["conversation_id"], msg["album_id"])
            last = max(datetime.fromisoformat(m["created_at"]) for m in album)
            loading = any(a.get("status") == "pending" for m in album for a in m["attachments"])
            quiet = (datetime.now(UTC) - last).total_seconds()
            if quiet >= settle and not loading:
                return
            await asyncio.sleep(max(settle - quiet, settle / 2, 0.05))

    async def _cloner_state(
        self,
        conversation_id: int,
        state: str,
        command: str,
        platform: str,
        detail: str,
        *,
        order_no: str = "",
        order_id: int | None = None,
        origin_message_id: int | None = None,
        reply: str | None = None,
    ) -> None:
        """Jeder Ausgang der Default-Kette schreibt Karte **und** Chat-Antwort (SP1 Schritt 5)."""
        shown = f"{order_no} · {detail}" if order_no else detail
        self.store.add_system_card(
            conversation_id, cloner.card(command, platform, shown, state),
            order_id=order_id, origin_message_id=origin_message_id,
        )  # fmt: skip
        self._message_changed(0)
        text = reply if reply is not None else cloner.reply(state, detail, order_no)
        if text:
            await self._reply_internal(conversation_id, text)

    async def _cloner(self, inbound) -> None:
        default = self.store.default_contact()
        msg = self.store.message(inbound.message_id)
        parsed = cloner.parse(msg["text"])
        conv = inbound.conversation_id
        if not default["process_commands"]:
            if parsed is not None and self._commands_off_due(conv):
                await self._reply_internal(conv, cloner.COMMANDS_OFF)
            return  # nur anzeigen
        if parsed is None:
            if msg["text"].strip():  # freie Anweisung: KI-Deutung folgt mit B5
                await self._reply_internal(conv, cloner.ASK_COMMAND)
            return
        command, wish = parsed
        plan = self._cloner_plan(msg, default, command)
        if isinstance(plan, str):
            await self._cloner_state(
                conv, "rejected", command, msg["platform"], plan,
                reply=plan if plan in (cloner.ASK_REFERENCE, cloner.ASK_OWN) else None,
            )  # fmt: skip
            return
        if not default["auto_orders"]:
            title = self.manifest.workflows[plan[0]].title
            await self._cloner_state(
                conv, "waiting_start", command, msg["platform"],
                f"{title} · {wish or '–'}", origin_message_id=inbound.message_id,
            )  # fmt: skip
            return
        order_no = await self._cloner_order(msg, command, wish, *plan)
        order = self.store.order(order_no)
        await self._cloner_state(
            conv, "started", command, msg["platform"], self._cloner_summary(plan[0], wish, order),
            order_no=order_no, order_id=order.id,
        )  # fmt: skip

    def _commands_off_due(self, conversation_id: int) -> bool:
        """„Befehle sind aus“ höchstens einmal je ``cloner.notice_interval_s`` und Chat."""
        last = self._commands_off_at.get(conversation_id)
        if last is not None and time.monotonic() - last < self.cfg.cloner.notice_interval_s:
            return False
        self._commands_off_at[conversation_id] = time.monotonic()
        return True

    def _cloner_summary(self, key: str, wish: str, order) -> str:
        jobs = sum(len(self.store.stage_jobs(st.id)) for st in self.store.stages(order.id))
        return f"{self.manifest.workflows[key].title} · {jobs} Kandidat(en) · {wish or '–'}"

    def _cloner_workflow_reason(self, key: str, kind: str) -> str:
        """Leer, wenn ``key`` leer ist oder ein registrierter Workflow der Art ``kind`` ist, der
        keine Trainingsaufgabe ist (Default-Kontakt: Medien- bzw. Video-Workflow)."""
        if not key:
            return ""
        wf = self.manifest.workflows.get(key)
        if wf is None:
            return f"Workflow '{key}' ist nicht registriert."
        if wf.training or self.manifest.engines[wf.engine].kind != kind:
            label = "Video-Workflow" if kind == "video" else "Medien-Workflow"
            return f"{wf.title} ist kein {label} für den Kloner."
        return ""

    def _with_album(self, msg: dict) -> list[dict]:
        """Gesicherte Anhänge einer Nachricht samt ihres Albums, je mit Quellnachricht."""
        album = msg.get("album_id")
        msgs = self.store.album_messages(msg["conversation_id"], album) if album else [msg]
        return [
            a | {"message_id": m["id"]}
            for m in msgs
            for a in m["attachments"]
            if a.get("status") == "saved"
        ]

    def _cloner_refs(self, msg: dict) -> tuple[list[dict], dict | None]:
        """Referenzen (SP1 Schritt 4): eigene Anhänge samt Album; sonst die beantwortete
        Nachricht samt Album; sonst Medien desselben Absenders in dieser Konversation aus den
        letzten ``cloner.reference_window_s``, die noch keinem Auftrag gehören. Nie Medien anderer
        Absender (eine Konversation gehört genau einer Identität)."""
        own = self._with_album(msg)
        replied = None
        if msg["reply_to_platform_id"]:
            replied = self.store.message_by_platform_id(
                msg["conversation_id"], msg["reply_to_platform_id"]
            )
        if own:
            return own, replied
        if replied is not None and (quoted := self._with_album(replied)):
            return quoted, replied
        since = datetime.now(UTC) - timedelta(seconds=self.cfg.cloner.reference_window_s)
        recent = self.store.recent_unassigned_media(
            msg["conversation_id"], msg["id"], since.isoformat(timespec="milliseconds")
        )
        refs: list[dict] = []
        seen: set[str] = set()
        for m in recent:
            for a in self._with_album(m):
                if a.get("path") not in seen:
                    seen.add(a.get("path"))
                    refs.append(a)
        return refs, replied

    def _cloner_plan(self, msg: dict, default: dict, command: str) -> tuple[str, list[dict]] | str:
        """Workflow des Default-Kontakts für den Befehl (``animate``: Video-Workflow, sonst
        Medien-Workflow), Referenzen und Vorprüfung (Instanz eingerichtet, Workflow startbar);
        bei fehlenden Voraussetzungen der Grund."""
        refs, replied = self._cloner_refs(msg)
        video = command == "animate"
        key = (
            default["command_workflows"].get(command)
            or default["video_workflow" if video else "media_workflow"]
        )
        if not key or key not in self.manifest.workflows:
            if video:
                return "Kein Video-Workflow (animate) im Default-Kontakt gewählt."
            return f"Kein Workflow für {command} im Default-Kontakt gewählt."
        wf = self.manifest.workflows[key]
        if self._lane_of(wf) is None:
            return f"{wf.title}: ComfyUI-Instanz nicht eingerichtet."
        if reason := self._not_startable(wf):
            return f"{wf.title}: {reason}"
        if _upload_param(wf) and not refs:
            return cloner.ASK_REFERENCE
        if command == "edit" and not self._own_reference(refs, replied):
            return cloner.ASK_OWN
        return key, refs

    def _own_reference(self, refs: list[dict], replied: dict | None) -> bool:
        """edit nur auf eigene Bilder (V0 §8): Antwort auf eine eigene gesendete Nachricht oder
        eine Datei, deren Inhalt Darkfluenzer erzeugt hat (gleicher SHA-256 wie ein Medium)."""
        if replied is not None and replied.get("direction") == "out":
            return True
        return bool(refs) and all(
            self.store.media_by_sha(r.get("sha256", "")) is not None for r in refs
        )

    async def _cloner_order(
        self, msg: dict, command: str, wish: str, key: str, refs: list[dict]
    ) -> str:
        """Kloner-Auftrag (Quelle ``cloner``) mit Kandidaten anlegen und einreihen."""
        wf = self.manifest.workflows[key]
        upload = _upload_param(wf)
        inputs = {}
        if upload:
            ref = self.cfg.local / refs[0]["path"]
            inputs[upload] = await asyncio.to_thread(
                pipeline.store_input, self.cfg, ref.read_bytes(), ref.name
            )
            # Vorlagen kommen auch aus dem Kloner-Eingang (FRONT, C1)
            await self._register_reference(inputs[upload], f"{msg['platform']}:{msg['id']}")
        values: dict = {}
        if command == "edit" and "region" in wf.params:
            region, wish = cloner.edit_parts(wish)
            if region:
                values["region"] = region
        text = cloner.prompt(command, wish, templated=bool(upload and wf.params[upload].reference))
        if text and "prompt" in wf.params:
            values["prompt"] = text
        graph = comfy.load_graph(self.manifest, wf)
        for name, p in wf.params.items():  # Pflichtwerte ohne Angabe: geprüfter Graph-Standard
            if p.required and not p.upload and name not in values:
                values[name] = graph[p.node]["inputs"][p.input]
        order_no, jobs = orders.create_order(
            self.store,
            self.manifest,
            key,
            values,
            inputs,
            count=self.cfg.production.candidates_default,
            source="cloner",
            origin=msg["id"],
            video_max_s=self.cfg.production.video_max_s,
        )
        order_id = self.store.order(order_no).id
        self.store.link_order(msg["id"], order_id)
        for source in {r["message_id"] for r in refs if r.get("message_id")} - {msg["id"]}:
            self.store.link_order(source, order_id)  # Referenz gehört jetzt diesem Auftrag
        log.info(
            "Kloner: %s %s → %s (%d Kandidaten)", command, msg["platform"], order_no, len(jobs)
        )
        self._enqueue(jobs)
        self._orders_changed()
        return order_no

    async def _start_cloner_order(self, msg: commands_pb2.StartClonerOrder, call: _Call) -> str:
        """Wartenden Kloner-Auftrag starten (Automatische Produktionsaufträge aus)."""
        call.entity = f"message:{msg.item_id}"
        card = self.store.message(msg.item_id)  # unbekannt: StoreError -> Ablehnung
        if card["direction"] != "system" or not card["origin_message_id"]:
            return "Kein wartender Kloner-Auftrag."
        if card["order_id"]:
            return "Auftrag wurde bereits gestartet."
        origin = self.store.message(card["origin_message_id"])
        parsed = cloner.parse(origin["text"])
        if parsed is None:
            return "Ursprungsnachricht enthält keinen Befehl."
        command, wish = parsed
        plan = self._cloner_plan(origin, self.store.default_contact(), command)
        if isinstance(plan, str):
            return plan
        order_no = await self._cloner_order(origin, command, wish, *plan)
        order = self.store.order(order_no)
        summary = self._cloner_summary(plan[0], wish, order)
        self.store.start_card(
            card["id"],
            order.id,
            cloner.card(command, origin["platform"], f"{order_no} · {summary}", "started"),
        )
        self._message_changed(card["id"])
        await self._reply_internal(
            card["conversation_id"], cloner.reply("started", summary, order_no)
        )
        return ""

    async def _stall_notice(self, job_id: int, quiet_s: float) -> None:
        """Hinweis an den Default bei Stillstand eines Kloner-Auftrags (SP1 Schritt 2): der Lauf
        geht weiter, abbrechen kann der Betreiber."""
        stage_id = self.store.job(job_id).get("stage_id")
        if stage_id is None:
            return
        order = self.store.order_by_id(self.store.stage(stage_id).order_id)
        stages = self.store.stages(order.id)
        origin = stages[0].params.get("origin") if stages else None
        if order.source != "cloner" or not origin:
            return
        conv = self.store.message(int(origin))["conversation_id"]
        await self._reply_internal(
            conv,
            f"Hinweis: {order.order_no} läuft seit {quiet_s / 60:.0f} min ohne Fortschritt. "
            "Der Lauf geht weiter; abbrechen kannst du im Cockpit.",
        )

    async def _cloner_delivery(self, order_id: int, selected: int | None = None) -> None:
        """Rückversand eines Kloner-Auftrags je Freigabemodus (V0 §8.1): direkt die Kandidaten,
        nach Auswahl das gewählte bzw. fertiggestellte Ergebnis, „nur Cockpit“ nichts."""
        order = self.store.order_by_id(order_id)
        if order.source != "cloner":
            return
        stages = self.store.stages(order_id)
        origin = stages[0].params.get("origin") if stages else None
        mode = self.store.default_contact()["approval_mode"]
        if not origin or mode == "cockpit_only":
            return
        conv = self.store.message(int(origin))["conversation_id"]
        last = stages[-1]
        files: list[str] = []
        if (
            mode == "direct"
            and last.kind == "candidates"
            and last.status == "waiting"
            or (
                mode == "cockpit"
                and selected is None
                and last.kind == "finish"
                and last.status == "done"
            )
        ):
            files = [j["path"] for j in self.store.stage_jobs(last.id) if j["path"]]
        elif mode == "cockpit" and selected is not None and len(stages) == 1:
            media = self.store.media_by_id(selected)
            files = [media["path"]] if media else []
        for n, path in enumerate(files, 1):
            label = f"{order.order_no} · Nr. {n}" if len(files) > 1 else order.order_no
            await self._reply_internal(conv, label, [path])
