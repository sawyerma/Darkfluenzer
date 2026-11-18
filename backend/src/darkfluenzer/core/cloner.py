"""Kloner der Default-Kette: Plan, Auftrag, Rückversand (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..core import cloner_text as cloner
from ..core import instruction, orders
from ..media import aimeta, models, pipeline
from ..nodes import comfy, llm
from ..store import sha256_file
from ..v1 import commands_pb2
from ..v1 import stream_pb2 as spb
from .base import _Call, _document_attachment, log


def _upload_param(wf: models.Workflow) -> str:
    """Eingangsbild eines Workflows für den Kloner: ``image`` bzw. die Vorlage (``reference``)."""
    slots = _slots(wf)
    return slots[0] if slots else ""


def _slots(wf: models.Workflow) -> list[str]:
    """Bild-Eingänge für Referenzen (ohne Masken), ``image``/``reference`` zuerst."""
    names = [n for n, p in wf.params.items() if p.upload and not p.tier_exempt]
    return sorted(names, key=lambda n: (n not in ("image", "reference"), list(wf.params).index(n)))


def _masks(wf: models.Workflow) -> list[str]:
    return [n for n, p in wf.params.items() if p.upload and p.tier_exempt and p.required]


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

    async def _reply_internal(
        self, conversation_id: int, text: str, files: list[str] = (), *, block_card: bool = True
    ) -> tuple[int, list[str]]:
        """Rückfrage bzw. Ergebnis an den Default-Nutzer in denselben Chat (Postausgang); liefert
        Nachricht und gesperrte Dateien."""
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
        if blocked and block_card:
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
        return message_id, blocked

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
        conv = inbound.conversation_id
        # feste Wörter vor der Betriebsart (SP4 Schritt 8): nie Sprachmodell oder Gedächtnis
        said = msg["text"].strip().lower()
        word = (default.get("cancel_word") or "").strip().lower()
        if word and said == word:  # Chat-Wort (SP1 Schritt 11)
            await self._cloner_cancel_chat(conv, msg)
            return
        if said in self.cfg.cloner.mode_words:  # Betriebsart per Chat
            await self._cloner_mode_word(conv, msg, self.cfg.cloner.mode_words[said])
            return
        mode = self.store.account_mode(msg["platform"], msg["account"])
        if mode == "off":
            return  # Betriebsart aus: nur anzeigen (SP1 Schritt 12)
        if mode == "test":
            await self._dialog_test(inbound)  # Kundentest (SP4 Schritt 8)
            return
        parsed = cloner.parse(msg["text"])
        if not default["process_commands"]:
            if parsed is not None and self._notice_due(conv, "off"):
                await self._reply_internal(conv, cloner.COMMANDS_OFF)
            return  # nur anzeigen
        if parsed is None:
            if msg["text"].strip():  # freie Anweisung: Deutung im Hintergrund (SP4 Schritt 4)
                task = asyncio.create_task(self._cloner_instruction(inbound))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            return
        command, wish = parsed
        plan = self._cloner_plan(msg, default, command)
        opts = (
            self._cloner_options(plan[0], command, wish, default)
            if isinstance(plan, tuple)
            else plan
        )
        if isinstance(plan, str) or isinstance(opts, str):
            reason = plan if isinstance(plan, str) else opts
            await self._cloner_state(
                conv, "rejected", command, msg["platform"], reason,
                reply=reason if reason in (cloner.ASK_REFERENCE, cloner.ASK_OWN) else None,
            )  # fmt: skip
            return
        if not default["auto_orders"]:
            title = self.manifest.workflows[plan[0]].title
            await self._cloner_state(
                conv, "waiting_start", command, msg["platform"],
                f"{title} · {opts['wish'] or '–'}", origin_message_id=inbound.message_id,
            )  # fmt: skip
            return
        numbers = await self._cloner_orders(msg, command, plan[0], plan[1], opts)
        await self._cloner_started(conv, command, msg["platform"], plan[0], numbers, opts)

    async def _cloner_started(
        self,
        conv: int,
        command: str,
        platform: str,
        key: str,
        numbers: list[str],
        opts: dict,
        *,
        card_id: int | None = None,
    ) -> None:
        """Karte je Auftrag (zeigt seine Stufe), eine Chat-Antwort für den ganzen Stapel."""
        for n, order_no in enumerate(numbers):
            order = self.store.order(order_no)
            summary = self._cloner_summary(key, opts, order)
            if n == 0 and card_id is not None:  # wartende Karte wird zur ersten Auftragskarte
                self.store.start_card(
                    card_id, order.id, cloner.card(command, platform, f"{order_no} · {summary}",
                                                   "started"),
                )  # fmt: skip
                self._message_changed(card_id)
                continue
            self.store.add_system_card(
                conv, cloner.card(command, platform, f"{order_no} · {summary}", "started"),
                order_id=order.id,
            )  # fmt: skip
        self._message_changed(0)
        first = self.store.order(numbers[0])
        label = numbers[0] if len(numbers) == 1 else f"{numbers[0]} … {numbers[-1]}"
        stack = f" · {len(numbers)} Aufträge" if len(numbers) > 1 else ""
        await self._reply_internal(
            conv, cloner.reply("started", self._cloner_summary(key, opts, first) + stack, label)
        )

    def _notice_due(self, conversation_id: int, kind: str) -> bool:
        """Hinweis („Befehle sind aus“, Kundentest) höchstens einmal je
        ``cloner.notice_interval_s`` und Chat."""
        key = (conversation_id, kind)
        last = self._commands_off_at.get(key)
        if last is not None and time.monotonic() - last < self.cfg.cloner.notice_interval_s:
            return False
        self._commands_off_at[key] = time.monotonic()
        return True

    def _cloner_summary(self, key: str, opts: dict, order) -> str:
        jobs = sum(len(self.store.stage_jobs(st.id)) for st in self.store.stages(order.id))
        parts = [self.manifest.workflows[key].title, f"{jobs} Kandidat(en)"]
        parts += [x for x in (opts.get("format"), opts.get("duration")) if x]
        if self.manifest.workflows[key].lora is not None:
            stages = self.store.stages(order.id)
            lora = str(stages[0].params.get(pipeline.LORA_KEY) or "") if stages else ""
            parts.append(f"LoRA {lora}" if lora else "ohne Charakter-LoRA")
        return " · ".join(parts + [opts.get("wish") or "–"])

    def _cloner_options(self, key: str, command: str, wish: str, default: dict) -> dict | str:
        """Optionen aus dem Wunsch (SP1 Schritt 6): Formatname der Engine setzt Breite und Höhe,
        eine Dauer ``duration_s`` (nur Video); sonst gilt das Ausgabeprofil des Befehls im
        Default-Kontakt. Fertigstellen bekommt eigene Werte (Instagram-Höhe zum Format)."""
        wf = self.manifest.workflows[key]
        eng = self.manifest.engines[wf.engine]
        fmt, duration, rest = cloner.options(wish)
        profile = default.get("command_profiles", {}).get(command, {})
        values: dict = {}
        sized = "width" in wf.params and "height" in wf.params
        if fmt:
            if fmt not in eng.formats:
                names = ", ".join(eng.formats) or "keine"
                return f"Format {fmt} gibt es bei {wf.title} nicht ({names})."
            if not sized:
                return f"{wf.title} übernimmt die Größe der Vorlage – kein Format möglich."
        else:
            fmt = profile.get("format", "") if profile.get("format") in eng.formats else ""
        if fmt and sized:
            values["width"], values["height"] = eng.formats[fmt]
        if duration is not None and eng.kind != "video":
            return "Eine Dauer gibt es nur bei Video (animate)."
        duration = duration or (profile.get("duration_s") or None if eng.kind == "video" else None)
        if duration:
            if not 0 < duration <= self.cfg.production.video_max_s:
                return f"Dauer 0 bis {self.cfg.production.video_max_s:.0f} s."
            values["duration_s"] = float(duration)
        finish = profile.get("finish", "") if eng.kind == "image" else ""
        finish_values: dict = {}
        if finish and fmt and (fw := self.manifest.workflows.get(finish)) is not None:
            height = fw.params.get("height")
            size = eng.formats[fmt]
            if height is not None and (h := cloner.finish_height(height.choices, size)):
                finish_values["height"] = h
        return {
            "values": values, "finish": finish, "finish_values": finish_values, "wish": rest,
            "format": fmt, "duration": f"{duration:g} s" if duration else "",
        }  # fmt: skip

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

    def _cloner_plan(
        self,
        msg: dict,
        default: dict,
        command: str,
        *,
        key: str = "",
        refs: list[dict] | None = None,
    ) -> tuple[str, list[dict]] | str:
        """Workflow des Default-Kontakts für den Befehl (``animate``: Video-Workflow, sonst
        Medien-Workflow), Referenzen und Vorprüfung (Instanz eingerichtet, Workflow startbar);
        bei fehlenden Voraussetzungen der Grund. ``key``/``refs``: aus einer freien Anweisung
        (SP4 Schritt 4), sonst wie beim Kurzbefehl."""
        found, replied = self._cloner_refs(msg)
        refs = found if refs is None else refs
        video = command == "animate"
        key = key or (
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
        if masks := _masks(wf):
            return f"{wf.title} braucht eine Maske ({', '.join(masks)}) – nicht über den Chat."
        slots = _slots(wf)
        if slots and not refs:
            return cloner.ASK_REFERENCE
        if any(str(r.get("kind")) in ("video", "animation") for r in refs):
            return "Video als Referenz ist noch nicht möglich (Zeitachse B4)."
        if len(slots) > 1 and len(refs) != len(slots):
            return f"{wf.title} braucht genau {len(slots)} Bilder ({', '.join(slots)})."
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

    def _cloner_candidates(self, wf: models.Workflow) -> int:
        """Kandidaten (SP1 Schritt 7): ohne Seed 1, Video ``production.video_candidates_default``,
        sonst der Wert des Default-Kontakts bzw. ``production.cloner_candidates``."""
        if "seed" not in wf.params:
            return 1
        if self.manifest.engines[wf.engine].kind == "video":
            return self.cfg.production.video_candidates_default
        own = self.store.default_contact().get("candidates")
        return int(own or self.cfg.production.cloner_candidates)

    async def _cloner_orders(
        self, msg: dict, command: str, key: str, refs: list[dict], opts: dict
    ) -> list[str]:
        """Kloner-Aufträge anlegen und einreihen (SP1 Schritt 7): bei einem Bild-Eingang je
        Referenz ein Auftrag (Stapel), bei mehreren Eingängen alle Bilder gemeinsam; eigenes
        Medium als Ausgangsmedium; Influencerin und Charakter des Default-Kontakts am Auftrag."""
        wf = self.manifest.workflows[key]
        slots = _slots(wf)
        groups = [[r] for r in refs] if len(slots) == 1 else [refs]
        if not slots:
            groups = [[]]
        default = self.store.default_contact()
        figure = next(
            (f for f in self.store.influencers() if str(f["id"]) == default["influencer"]), None
        )
        extra = {
            "influencer": figure["id"] if figure else None,
            "character": figure["character_id"] if figure else None,
            "command": command,
        }
        wish = opts["wish"]
        values: dict = dict(opts["values"])
        if command == "edit" and "region" in wf.params:
            region, wish = cloner.edit_parts(wish)
            if region:
                values["region"] = region
        templated = any(wf.params[n].reference for n in slots)
        text = cloner.prompt(command, wish, templated=templated)
        if text and "prompt" in wf.params:
            values["prompt"] = text
        graph = comfy.load_graph(self.manifest, wf)
        for name, p in wf.params.items():  # Pflichtwerte ohne Angabe: geprüfter Graph-Standard
            if p.required and not p.upload and name not in values:
                values[name] = graph[p.node]["inputs"][p.input]
        # Charakter-LoRA der Figur des Default-Kontakts (SP3 Schritt 8/9), wenn der Workflow sie
        # laden darf; sonst „ohne Charakter-LoRA“ (Karte)
        character = figure["character_id"] if figure else None
        lora = pipeline.active_lora(self.store, self.manifest, character, wf) if character else ""
        numbers: list[str] = []
        for group in groups:
            inputs = {}
            for slot, ref in zip(slots, group, strict=False):
                src = self.cfg.local / ref["path"]
                inputs[slot] = await asyncio.to_thread(
                    pipeline.store_input, self.cfg, src.read_bytes(), src.name
                )
                # Vorlagen kommen auch aus dem Kloner-Eingang (FRONT, C1)
                await self._register_reference(inputs[slot], f"{msg['platform']}:{msg['id']}")
            parent = None
            if group and (own := self.store.media_by_sha(group[0].get("sha256", ""))):
                parent = own["id"]  # eigenes Medium als Ausgangsmedium
            order_no, jobs = orders.create_order(
                self.store, self.manifest, key, values, inputs,
                count=self._cloner_candidates(wf),
                finish_workflow=opts["finish"], finish_values=opts["finish_values"],
                parent_media_id=parent, source="cloner", origin=msg["id"],
                video_max_s=self.cfg.production.video_max_s, extra=extra,
                lora=lora, character_id=character if lora else None,
            )  # fmt: skip
            order_id = self.store.order(order_no).id
            self.store.link_order(msg["id"], order_id)
            for source in {r["message_id"] for r in group if r.get("message_id")} - {msg["id"]}:
                self.store.link_order(source, order_id)  # Referenz gehört jetzt diesem Auftrag
            log.info(
                "Kloner: %s %s → %s (%d Kandidaten)", command, msg["platform"], order_no, len(jobs)
            )
            self._enqueue(jobs)
            numbers.append(order_no)
        self._orders_changed()
        return numbers

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
        default = self.store.default_contact()
        plan = self._cloner_plan(origin, default, command)
        if isinstance(plan, str):
            return plan
        opts = self._cloner_options(plan[0], command, wish, default)
        if isinstance(opts, str):
            return opts
        numbers = await self._cloner_orders(origin, command, plan[0], plan[1], opts)
        await self._cloner_started(
            card["conversation_id"], command, origin["platform"], plan[0], numbers, opts,
            card_id=card["id"],
        )  # fmt: skip
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
        """Abschluss und Rückversand eines Kloner-Auftrags (SP1 Schritt 8): genau ein Ergebnis
        wird automatisch gewählt (danach ggf. Fertigstellen); Modus Direkt mit mehreren sendet
        alle und schließt die Stufe ohne Auswahl; sonst das gewählte bzw. fertiggestellte
        Ergebnis. Rückversand je Medium genau einmal; Fehlschlag/Abbruch mit Grund."""
        order = self.store.order_by_id(order_id)
        stages = self.store.stages(order_id)
        origin = stages[0].params.get("origin") if stages else None
        if order.source != "cloner" or not origin:
            return
        source = self.store.message(int(origin))
        conv, platform = source["conversation_id"], source["platform"]
        command = str(stages[0].params.get("command") or "")
        command = command or (cloner.parse(source["text"]) or ("auftrag", ""))[0]
        last = stages[-1]
        if order.status == "cancelled" or last.status == "failed":
            state = "cancelled" if order.status == "cancelled" else "failed"
            if self.store.mark_cloner_outcome(order_id, state):
                why = "" if state == "cancelled" else (last.error or "kein Ergebnis")
                await self._cloner_state(
                    conv, state, command, platform, why or "vom Betreiber", order_no=order.order_no
                )
            return
        mode = self.store.default_contact()["approval_mode"]
        if last.kind == "candidates" and last.status == "waiting":
            done = [
                j for j in self.store.stage_jobs(last.id) if j["status"] == "done" and j["path"]
            ]
            if len(done) == 1:  # genau ein Ergebnis: automatisch gewählt
                jobs = orders.select_candidate(
                    self.cfg, self.store, self.manifest, order.order_no, done[0]["media_id"], None
                )
                self._enqueue(jobs)
                self._orders_changed()
                if jobs:
                    return  # Fertigstellen läuft; Rückversand danach
                selected = done[0]["media_id"]
            elif mode == "direct":  # alle senden, Stufe ohne Auswahl schließen, Auftrag zur Prüfung
                with self.store.tx():
                    self.store.set_stage(last.id, "done")
                    self.store.transition(order.order_no, "review")
                self._orders_changed()
                files = [(j["media_id"], j["path"]) for j in done]
                await self._cloner_return(order, conv, command, platform, files)
                return
            else:
                return  # wartet auf die Auswahl im Cockpit
            last = self.store.stages(order_id)[-1]
        if mode == "cockpit_only":
            return
        files: list[tuple[int, str]] = []
        if last.kind == "finish" and last.status == "done":
            done = self.store.stage_jobs(last.id)
            files = [
                (j["media_id"], j["path"]) for j in done if j["status"] == "done" and j["path"]
            ]
        elif selected is not None and (media := self.store.media_by_id(selected)):
            files = [(selected, media["path"])]
        await self._cloner_return(order, conv, command, platform, files)

    async def _cloner_return(
        self, order, conv: int, command: str, platform: str, files: list[tuple[int, str]]
    ) -> None:
        """Dateien an den Default, je Auftrag und Medium genau einmal (``cloner_returns``)."""
        fresh = [(m, p) for m, p in files if self.store.claim_cloner_return(order.id, m)]
        if not fresh:
            return
        blocked_all: list[str] = []
        for n, (media_id, path) in enumerate(fresh, 1):
            label = f"{order.order_no} · Nr. {n}" if len(fresh) > 1 else order.order_no
            message_id, blocked = await self._reply_internal(conv, label, [path], block_card=False)
            self.store.set_cloner_return_message(order.id, media_id, message_id)
            blocked_all += blocked
        sent = len(fresh) - len(blocked_all)
        if blocked_all:
            await self._cloner_state(
                conv, "return_blocked", command, platform,
                f"{', '.join(blocked_all)} · Inhaltsstufe explizit – über "
                f"{platform} nie (Regel 13)", order_no=order.order_no,
            )  # fmt: skip
        if sent:
            await self._cloner_state(
                conv, "returned", command, platform, f"{sent} Datei(en) im Chat",
                order_no=order.order_no, reply="",
            )  # fmt: skip

    def _instruction_workflow(self) -> models.Workflow | None:
        wf = next((w for w in self.manifest.workflows.values() if w.instruction), None)
        if wf is None or not wf.enabled or wf.status == "GESPERRT" or self.cfg.comfyui_ai is None:
            return None
        return wf

    def _instruction_facts(self, conv: int, default: dict) -> tuple[str, list[dict]]:
        """Fakten für die Deutung (Daten, keine Formulierung): Befehle mit Workflow und Formaten,
        weitere Medien-Workflows, frühere Ergebnisse dieses Chats (neueste zuerst)."""
        lines = ["Befehle:"]
        for command in cloner.COMMANDS:
            video = command == "animate"
            key = (
                default["command_workflows"].get(command)
                or default["video_workflow" if video else "media_workflow"]
            )
            wf = self.manifest.workflows.get(key or "")
            if wf is not None:
                formats = ", ".join(self.manifest.engines[wf.engine].formats) or "Größe der Vorlage"
                lines.append(f"- {command}: {wf.title} ({wf.key}); Formate: {formats}")
            else:
                lines.append(f"- {command}: kein Workflow")
        media_kinds = ("image", "video")
        usable = [
            w
            for w in self.manifest.workflows.values()
            if not w.training and w.enabled and self.manifest.engines[w.engine].kind in media_kinds
        ]
        lines.append("Workflows: " + "; ".join(f"{w.key} ({w.title})" for w in usable))
        recent = self.store.recent_returns(conv, 5)
        lines.append("Frühere Medien (neueste zuerst):")
        lines += [f"- media:{r['media_id']} · {r['order_no']} · {r['name']}" for r in recent]
        return "\n".join(lines), recent

    async def _cloner_instruction(self, inbound) -> None:
        """Freie Anweisung deuten (registrierter Workflow ``default_instruction_melody``) und nur
        Erlaubtes ausführen; ohne Workflow die bisherige Rückfrage."""
        conv = inbound.conversation_id
        msg = self.store.message(inbound.message_id)
        wf = self._instruction_workflow()
        if wf is None:
            await self._reply_internal(conv, cloner.ASK_COMMAND)
            return
        default = self.store.default_contact()
        facts, recent = self._instruction_facts(conv, default)
        values = {"facts": facts, "message": msg["text"]}
        started = time.monotonic()
        fields: dict = {}
        error = ""
        try:
            result = await asyncio.to_thread(
                llm.instruct, self.cfg, self.manifest, wf.key, values,
                timeout_s=self.cfg.ai.run_timeout_s,
            )  # fmt: skip
            fields = {
                "workflow_sha": result.workflow_sha, "model_sha": result.model_sha,
                "system_prompt": result.system, "user_text": result.user,
                "answer": result.answer, "prompt_id": result.prompt_id,
                "wait_ms": round(result.wait_s * 1000),
                "duration_ms": round(result.duration_s * 1000),
            }  # fmt: skip
            ins, why = instruction.parse(llm.parse_classification(result.answer))
        except (llm.LlmError, comfy.ComfyError, ValueError, OSError) as exc:
            ins, why, error = None, "", str(exc) or type(exc).__name__
        run_id = self.store.add_ai_run(
            "instruction", wf.key, customer_id=default["customer_id"], message=msg["text"],
            context={"conversation": conv, "media": len(recent)}, error=error or why,
            total_ms=round((time.monotonic() - started) * 1000), **fields,
        )  # fmt: skip
        self.hub.push_events(spb.TOPIC_AI_RESULT)
        platform = msg["platform"]
        if ins is None:
            await self._cloner_state(
                conv, "failed", "anweisung", platform, error or why or "keine Deutung",
                reply=f"Anweisung nicht verstanden ({error or why}). {cloner.ASK_COMMAND}",
            )  # fmt: skip
            return
        if ins.command == "none":
            await self._reply_internal(conv, ins.question or cloner.ASK_COMMAND)
            return
        refs = None
        if ins.reference:
            chosen = recent[0] if ins.reference == "letztes" and recent else next(
                (r for r in recent if f"media:{r['media_id']}" == ins.reference), None
            )  # fmt: skip
            if chosen is None:
                reason = f"Bezug {ins.reference} gehört zu keinem Medium dieses Chats."
                await self._cloner_state(conv, "rejected", ins.command, platform, reason)
                return
            refs = [{"path": chosen["path"], "sha256": chosen["sha256"], "status": "saved",
                     "kind": "photo"}]  # fmt: skip
        if ins.workflow and ins.workflow not in self.manifest.workflows:
            reason = f"Workflow {ins.workflow} ist nicht registriert."
            await self._cloner_state(conv, "rejected", ins.command, platform, reason)
            return
        kind = "video" if ins.command == "animate" else "image"
        if ins.workflow and (reason := self._cloner_workflow_reason(ins.workflow, kind)):
            await self._cloner_state(conv, "rejected", ins.command, platform, reason)
            return
        plan = self._cloner_plan(msg, default, ins.command, key=ins.workflow, refs=refs)
        wished = instruction.wish(ins)
        opts = (
            self._cloner_options(plan[0], ins.command, wished, default)
            if isinstance(plan, tuple)
            else plan
        )
        if isinstance(plan, str) or isinstance(opts, str):
            reason = plan if isinstance(plan, str) else opts
            await self._cloner_state(conv, "rejected", ins.command, platform, reason)
            return
        if not default["auto_orders"]:
            await self._cloner_state(
                conv, "rejected", ins.command, platform,
                f"gedeutet als {ins.command} ({wished or '–'}) – automatische Aufträge sind aus",
            )  # fmt: skip
            return
        log.info("Freie Anweisung (Lauf #%s) gedeutet als %s", run_id, ins.command)
        numbers = await self._cloner_orders(msg, ins.command, plan[0], plan[1], opts)
        await self._cloner_started(conv, ins.command, platform, plan[0], numbers, opts)

    async def _cloner_mode_word(self, conv: int, msg: dict, mode: str) -> None:
        """Betriebsart des Kontos per festem Wort im Default-Chat."""
        acc = self.store.account_for(msg["platform"], msg["account"])
        if acc is None:
            await self._reply_internal(conv, "Betriebsart: Kanalkonto unbekannt.")
            return
        self.store.set_account_mode(acc["key"], mode)
        self._channels_changed()
        labels = {"production": "Produktion", "test": "Kundentest", "off": "Aus"}
        await self._reply_internal(conv, f"Betriebsart: {labels[mode]}.")

    async def _cloner_cancel_chat(self, conv: int, msg: dict) -> None:
        """Chat-Wort (SP1 Schritt 11): laufende Kloner-Aufträge dieses Chats abbrechen."""
        running = self.store.cloner_orders_running(conv)
        if not running:
            await self._reply_internal(conv, "Nichts zum Abbrechen.")
            return
        for order_no in running:
            call = _Call(f"chat-{msg['id']}-{order_no}", "", "order_cancel")
            await self._order_cancel(commands_pb2.OrderCancel(order_no=order_no), call)
