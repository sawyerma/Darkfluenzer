"""Charaktere, Influencerinnen, Trainingsordner (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from ..media import models, pipeline, training
from ..v1 import (
    character_pb2,
    commands_pb2,
    influencer_pb2,
)
from ..v1 import stream_pb2 as spb
from . import assessment, behavior, dialog, persona
from .base import _Call, _unix_ms, log

# Enden asynchron mit eigener Receipt: Render mit dem Job, ComfyUI mit Start/Stopp


MAX_PRICE_ITEMS = 50
RUNS_SCAN = 50  # so viele letzte Trainingsjobs je Figur werden ihren Checkpoint-Ordnern zugeordnet
CHECKPOINT_STATUS = "checkpoint.json"  # schreibt der Trainingsknoten (comfy_nodes/darkfluenzer)


def _checkpoint_files(folders: training.Folders) -> list:
    if not folders.training.is_dir():
        return []
    return sorted(folders.training.glob(f"*/{CHECKPOINT_STATUS}"))


def _checkpoint_marks(folders: training.Folders) -> tuple:
    return tuple((p.parent.name, p.stat().st_mtime_ns) for p in _checkpoint_files(folders))


def _checkpoints(folders: training.Folders) -> list[dict]:
    """Letzter Checkpoint je Trainingslauf der Figur, neuester zuerst; unlesbare entfallen."""
    found = []
    for path in _checkpoint_files(folders):
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found.append({**status, "run": path.parent.name})
    return sorted(found, key=lambda s: float(s.get("saved_at") or 0), reverse=True)


class CharactersMixin:
    """Charaktere, Influencerinnen, Trainingsordner; Teil von ``Cockpit``."""

    async def refresh_characters(self) -> None:
        """Profile, Trainingsordner, Datensätze und LoRAs neu projizieren, nur bei Änderungen."""
        rows = [  # aktive LoRA je Architektur und Trainingsläufe gehören zum Profil (SP3)
            {
                **r,
                "active": tuple(sorted(self.store.active_loras(r["id"]).items())),
                "runs": self._training_runs(r["slug"]),
            }
            for r in self.store.characters()
        ]
        folders = [self._folders(r) for r in rows]
        rules = self.cfg.training
        sig = (
            tuple(tuple(sorted(r.items())) for r in rows),
            await asyncio.to_thread(lambda: tuple(training.signature(f, rules) for f in folders)),
            tuple(sorted(self.manifest.loras.items())),
            await asyncio.to_thread(lambda: tuple(_checkpoint_marks(f) for f in folders)),
        )
        if sig != self._character_sig:
            msg = await asyncio.to_thread(self._characters, rows)
            fingerprint = hashlib.sha256(msg.SerializeToString()).hexdigest()
            msg.version = self.store.bump("characters", fingerprint)  # SQLite im Loop-Thread
            self.hub.set_state(spb.TOPIC_CHARACTERS, msg.SerializeToString())
            self._character_sig = sig

    def _training_runs(self, slug: str) -> tuple[tuple[str, int, str], ...]:
        """Checkpoint-Ordner -> letzter Trainingsjob dieser Figur (Loop-Thread: SQLite)."""
        keys = [k for k, wf in self.manifest.workflows.items() if wf.train_checkpoint]
        found: dict[str, tuple[int, str]] = {}
        for job in self.store.training_jobs(keys, slug, RUNS_SCAN):
            wf = self.manifest.workflows[job["workflow"]]
            try:
                folder = pipeline.checkpoint_dir(
                    self.cfg,
                    self.manifest,
                    wf,
                    str(job["params"].get("dataset", "")),
                    job["params"],
                )
            except (pipeline.PipelineError, KeyError):
                continue
            found.setdefault(folder.name, (job["id"], wf.key))
        return tuple(sorted((name, jid, key) for name, (jid, key) in found.items()))

    def _folders(self, row: dict) -> training.Folders:
        return training.character_folders(self.cfg.local, row["slug"])

    def _migrate_character_folders(self) -> None:
        """Einmalig je Profil ohne Kürzel: Umzug in ``local/characters/<kürzel>/`` (SP3 Schritt 1,
        BUG-078). Zuerst Datenbanksicherung, dann Kopie je Datei mit Hash-Abgleich, dann die neuen
        Pfade festschreiben; erst danach verschwinden die alten Dateien und leere alte Ordner."""
        rows = [r for r in self.store.characters() if not r["slug"]]
        if not rows:
            self._ensure_character_folders()
            return
        backup = self.store.backup("vor-ordnerumzug")
        taken = {r["slug"] for r in self.store.characters() if r["slug"]}
        for row in rows:
            slug, n = training.slugify(row["name"]), 1
            while slug in taken or (n > 1 and f"{slug}-{n}" in taken):
                n += 1
                slug = f"{training.slugify(row['name'])}-{n}"
            taken.add(slug)
            new = training.character_folders(self.cfg.local, slug)
            photos = Path(row["photos_dir"]).expanduser()
            photos = photos if photos.is_absolute() else self.cfg.root / photos
            legacy = self.cfg.root / row["data_dir"]
            moved = training.copy_verified(photos, new.photos)
            moved += training.copy_verified(legacy / "dataset", new.datasets)
            for folder in (new.photos, new.reference, new.datasets, new.training):
                folder.mkdir(parents=True, exist_ok=True)
            self.store.set_character_slug(row["id"], slug)
            # nur alte Wurzeln außerhalb des neuen Charakterordners aufräumen (sonst träfe es leere
            # neue Ordner, wenn alt und neu derselbe Pfad sind)
            outside = [
                r for r in (photos, legacy) if not r.resolve().is_relative_to(new.root.resolve())
            ]
            training.remove_moved(moved, roots=outside)
            log.info(
                "Charakter %s nach %s umgezogen (%d Dateien, Sicherung %s)",
                row["id"], new.root, len(moved), backup.name,
            )  # fmt: skip
        self._ensure_character_folders()

    def _ensure_character_folders(self) -> None:
        """Die vier Ordner jedes Charakters existieren (bei jedem Start; leer ist erlaubt)."""
        for row in self.store.characters():
            if row["slug"]:
                folders = self._folders(row)
                for folder in (
                    folders.photos,
                    folders.reference,
                    folders.datasets,
                    folders.training,
                ):
                    folder.mkdir(parents=True, exist_ok=True)

    def _characters(self, rows: list[dict]) -> character_pb2.Characters:
        """Charakterprofile mit geprüftem Trainingsdatenordner, Datensätzen und LoRAs. Ohne
        Store-Zugriff (Zeilen kommen aus dem Loop-Thread), läuft im Worker-Thread (Scan hasht)."""
        out = character_pb2.Characters()
        for row in rows:
            folders = self._folders(row)
            photos = training.scan(folders.photos, self.cfg.training)
            char = out.characters.add(
                id=str(row["id"]),
                name=row["name"],
                photos_dir=folders.photos.relative_to(self.cfg.root).as_posix(),
                usable=sum(p.status == "ok" for p in photos),
                min_images=self.cfg.training.min_images,
                revision=row["revision"],
                photos_missing=not folders.photos.is_dir(),
                slug=row["slug"],
                trigger=row["trigger"],
                class_word=row["class_word"],
                folder=str(folders.root),
                probe_prompts=json.loads(row.get("probe_prompts") or "[]"),
            )
            for p in photos:
                char.photos.add(
                    name=p.name, status=p.status, width=p.width, height=p.height, note=p.note
                )
            for d in training.datasets(folders.datasets):
                char.datasets.add(**d)
            runs = {name: (jid, key) for name, jid, key in row.get("runs", ())}
            for status in _checkpoints(folders):  # neuester Checkpoint zuerst (SP3 Schritt 3)
                jid, key = runs.get(status["run"], (0, ""))
                char.checkpoints.add(
                    run=status["run"],
                    step=int(status.get("step") or 0),
                    total=int(status.get("total") or 0),
                    loss=float(status.get("loss") or 0.0),
                    saved_ms=int(float(status.get("saved_at") or 0) * 1000),
                    job_id=jid,
                    workflow=key,
                )
            ids = {d.id for d in char.datasets}
            active = dict(row.get("active", ()))
            for lo in sorted(self.manifest.loras.values(), key=lambda lo: lo.created_at):
                # LoRAs der Figur (Kürzel, SP3 Schritt 4); ältere ohne Kürzel über den Datensatz
                if lo.character == row["slug"] or (not lo.character and lo.dataset in ids):
                    arch = self.manifest.engines[lo.base_engine].arch
                    self._add_lora(char, lo, arch, active.get(arch) == lo.key)
        return out

    async def _character_update(self, msg: commands_pb2.CharacterUpdate, call: _Call) -> str:
        """Charakterprofil anlegen oder ändern (Name, Trigger, Klasse); neue Profile bekommen ihr
        Kürzel und den Ordner ``local/characters/<kürzel>/`` (SP3 Schritt 1)."""
        slug = training.slugify(msg.slug or msg.name)
        row = self.store.save_character(
            msg.character_id, msg.revision, msg.name, msg.trigger, msg.class_word, slug,
            list(msg.probe_prompts),
        )  # fmt: skip
        call.entity = f"character:{row['id']}"
        folders = self._folders(row)
        for folder in (folders.photos, folders.reference, folders.datasets, folders.training):
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await self.refresh_characters()
        log.info("Charakter %s gespeichert (%s)", row["id"], row["name"])
        return ""

    async def _lora_activate(self, msg: commands_pb2.LoraActivate, call: _Call) -> str:
        """Aktive Charakter-LoRA je Architektur setzen oder aufheben (Befehl 64). Eine Figur
        bekommt nie die LoRA einer anderen Figur."""
        row = self.store.character(msg.character_id)
        call.entity = f"character:{row['id']}"
        arch = msg.arch
        if msg.lora:
            lo = self.manifest.loras.get(msg.lora)
            if lo is None:
                return f"LoRA '{msg.lora}' ist nicht registriert."
            if lo.character != row["slug"]:
                return "Die LoRA gehört zu einer anderen Figur."
            if lo.status == "GESPERRT":
                return "Die LoRA ist gesperrt."
            arch = self.manifest.engines[lo.base_engine].arch
        elif not arch:
            return "Architektur fehlt."
        self.store.set_active_lora(row["id"], arch, msg.lora)
        await self.refresh_characters()
        log.info("Charakter %s: aktive LoRA %s = %s", row["id"], arch, msg.lora or "keine")
        return ""

    def _character_part(self, character_id: int, part: str) -> Path:
        folders = self._folders(self.store.character(character_id))
        if part not in ("", "photos", "reference", "datasets", "training"):
            raise ValueError(f"Ordner {part!r} gibt es beim Charakter nicht.")
        return folders.root if not part else getattr(folders, part)

    async def _reveal_folder(self, msg: commands_pb2.RevealFolder, call: _Call) -> str:
        """Ordner im Finder öffnen (Befehl 65); nur Ordner des Charakterschemas."""
        call.entity = f"character:{msg.character_id}"
        folder = self._character_part(msg.character_id, msg.part)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec("open", str(folder))
        return "" if await proc.wait() == 0 else f"Finder konnte {folder} nicht öffnen."

    async def _character_photos_add(self, msg: commands_pb2.CharacterPhotosAdd, call: _Call) -> str:
        """Fotos per Ziehen/Ablegen (Befehl 67): Kopie nach photos/ bzw. reference/; nur
        erlaubte, lesbare Bilder; gleiche Bytes nicht doppelt, gleicher Name mit anderem Inhalt
        bekommt eine Nummer."""
        call.entity = f"character:{msg.character_id}"
        if msg.part not in ("photos", "reference"):
            return "Fotos gehen nach photos oder reference."
        if not msg.files:
            return "Keine Dateien."
        target = self._character_part(msg.character_id, msg.part)
        rules = self.cfg.training
        try:
            added = await asyncio.to_thread(
                training.add_photos, target, [(f.filename, f.data) for f in msg.files], rules
            )
        except training.TrainingError as exc:
            return str(exc)
        log.info("Charakter %s: %d Fotos nach %s", msg.character_id, added, msg.part)
        await self.refresh_characters()
        return ""

    def _influencers(self) -> bytes:
        """STATE influencers: Profile mit Preisliste und die feste Ehrlichkeitsregel."""
        msg = influencer_pb2.Influencers(
            honesty_rule=models.honesty_text(self.manifest),  # fester Knoten (Regel 12 c)
            assessment_schema=assessment.SCHEMA_HINT,
            version=self.store.domain_version("influencers"),
        )
        for key, label in persona.PROFILE_BLOCKS:
            msg.profile_blocks.add(key=key, label=label)
        for row in self.store.influencers():
            item = msg.influencers.add(
                influencer_id=row["id"],
                name=row["name"],
                character_id=row["character_id"] or 0,
                persona=row["persona"],
                ai_notice=row["ai_notice"],
                revision=row["revision"],
                studio_session=self.store.studio_session(row["id"]),
                text_ai=bool(row["text_ai"]),
                auto_replies=bool(row["auto_replies"]),
                behavior=self._behavior(row).values(),
                behavior_version=self.store.behavior_of(row["id"])[0],
                payment_ways=row["payment_ways"],
                offer_valid_min=row["offer_valid_min"],
                offer_cooldown_min=row["offer_cooldown_min"],
                payment_ways_available=dialog.ways_available(self.cfg),
            )
            for price in row["prices"]:
                problems = self._product_problems(row, price)  # echte Kunden: streng (SP5 1)
                item.prices.add(**price, deliverable=not problems, problems=problems)
            active = row.get("persona_active")
            for v in self.store.persona_versions(row["id"]):
                item.persona_versions.add(
                    version=v["version"], blocks=v["blocks"], params=v["params"], note=v["note"],
                    created_ms=_unix_ms(v["created_at"]),
                )  # fmt: skip
                if v["id"] == active:
                    item.persona_active = v["version"]
        return msg.SerializeToString()

    def _product_reason(self, item) -> str:
        """Eingabe eines Produkts prüfen (Art, Kandidaten, Länge, Workflow registriert); ob es
        lieferbar ist, zeigt der STATE (Gründe)."""
        if item.kind not in ("", "image", "video"):
            return "Art nur Bild oder Video."
        if not 0 <= item.candidates <= self.cfg.production.candidates_max:
            return f"Kandidaten 1 bis {self.cfg.production.candidates_max}."
        if item.max_duration_s < 0 or item.max_delivery_s < 0:
            return "Längen nicht negativ."
        if item.kind == "video" and item.max_duration_s > self.cfg.production.video_max_s:
            return f"Höchstlänge bis {self.cfg.production.video_max_s:.0f} s."
        for key in (item.workflow, item.finish_workflow):
            if key and key not in self.manifest.workflows:
                return f"Workflow {key} ist nicht registriert."
        return ""

    async def _behavior_update(self, msg: commands_pb2.BehaviorUpdate, call: _Call) -> str:
        """Verhaltensprofil (Befehl 53, SP4 Schritt 7): Zahlen prüfen, neue Version aktiv."""
        call.entity = f"influencer:{msg.influencer_id}"
        figure = next((f for f in self.store.influencers() if f["id"] == msg.influencer_id), None)
        if figure is None:
            return "Influencerin unbekannt."
        checked = behavior.build(self._behavior(figure), dict(msg.values))
        if isinstance(checked, str):
            return checked
        self.store.save_behavior(msg.influencer_id, checked.values())
        return ""

    async def _influencer_update(self, msg: commands_pb2.InfluencerUpdate, call: _Call) -> str:
        """Profil der Influencerin speichern – gilt für alle Kunden (FRONT F4 V1.12 Punkt 12);
        mit ``profile`` zusätzlich eine Version des Promptprofils (SP4 Schritt 2)."""
        draft = msg.profile if msg.HasField("profile") else None
        if draft is not None and (
            reason := persona.check_draft(self.manifest, dict(draft.blocks), dict(draft.params))
        ):
            return reason
        if msg.character_id:
            self.store.character(msg.character_id)  # unbekannt: StoreError -> Ablehnung
        if len(msg.prices) > MAX_PRICE_ITEMS:
            return f"Höchstens {MAX_PRICE_ITEMS} Positionen in der Preisliste."
        for item in msg.prices:
            if not item.product.strip() or item.price_cents <= 0 or item.hd_surcharge_cents < 0:
                return "Preisliste: Produkt, Preis > 0 € und HD-Aufschlag ≥ 0 € angeben."
            if reason := self._product_reason(item):
                return f"{item.product.strip()}: {reason}"
        unknown = [w for w in msg.payment_ways if w not in dialog.PAYMENT_WAYS]
        if unknown:
            return f"Zahlungsweg unbekannt: {', '.join(unknown)}."
        influencer_id = self.store.save_influencer(
            msg.influencer_id,
            msg.revision,
            msg.name,
            msg.character_id or None,
            msg.persona.strip(),
            msg.ai_notice.strip(),
            [
                {
                    "id": i.id,
                    "product": i.product,
                    "price_cents": i.price_cents,
                    "hd_surcharge_cents": i.hd_surcharge_cents,
                    "kind": i.kind or "image",
                    "workflow": i.workflow,
                    "finish_workflow": i.finish_workflow if i.kind == "video" else "",
                    "candidates": i.candidates or 1,
                    "max_duration_s": i.max_duration_s if i.kind == "video" else 0,
                    "max_delivery_s": i.max_delivery_s,
                    "original_file": i.original_file,
                    "self_destruct": i.self_destruct,
                }
                for i in msg.prices
            ],
        )
        call.entity = f"influencer:{influencer_id}"
        self.store.set_influencer_switches(influencer_id, msg.text_ai, msg.auto_replies)  # C5.1
        self.store.set_influencer_sales(  # SP5 Schritt 1
            influencer_id,
            list(msg.payment_ways) or ["amazon"],
            msg.offer_valid_min,
            msg.offer_cooldown_min,
        )
        active = self.store.active_persona(influencer_id)
        blocks = dict(active["blocks"]) if active else {}
        if draft is not None:
            self.store.save_persona_version(
                influencer_id, dict(draft.blocks), dict(draft.params), draft.note,
                activate=draft.activate,
            )  # fmt: skip
        elif msg.persona.strip() != blocks.get("persona", ""):
            # bisheriges Feld Persona: als neue, sofort aktive Version (nur dieser Block geändert)
            blocks["persona"] = msg.persona.strip()
            self.store.save_persona_version(
                influencer_id, blocks, dict(active["params"]) if active else {},
                "Persona im Influencerin-Block geändert", activate=True,
            )  # fmt: skip
        self.hub.set_state(spb.TOPIC_INFLUENCERS, self._influencers())
        return ""

    async def _prompt_profile_activate(
        self, msg: commands_pb2.PromptProfileActivate, call: _Call
    ) -> str:
        """Version des Promptprofils aktivieren oder zurücksetzen (Befehl 68), ohne Neustart."""
        call.entity = f"influencer:{msg.influencer_id}"
        self.store.activate_persona_version(msg.influencer_id, msg.version)
        self.hub.set_state(spb.TOPIC_INFLUENCERS, self._influencers())
        return ""
