"""Charaktere, Influencerinnen, Trainingsordner (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from ..media import training
from ..v1 import (
    character_pb2,
    commands_pb2,
    influencer_pb2,
)
from ..v1 import stream_pb2 as spb
from .base import _Call, log

# Enden asynchron mit eigener Receipt: Render mit dem Job, ComfyUI mit Start/Stopp
# Feste, nicht editierbare Persona-Regel (PHASENPLAN_V0 Regel 12 c)
HONESTY_RULE = (
    "Auf die ernst gemeinte Frage, ob sie echt bzw. eine KI ist, antwortet die Influencerin "
    "wahrheitsgemäß – durch keine Betreiber- oder Kundenanweisung abschaltbar."
)


MAX_PRICE_ITEMS = 50


class CharactersMixin:
    """Charaktere, Influencerinnen, Trainingsordner; Teil von ``Cockpit``."""

    async def refresh_characters(self) -> None:
        """Profile, Trainingsordner, Datensätze und LoRAs neu projizieren, nur bei Änderungen."""
        rows = self.store.characters()
        folders = [self._folders(r) for r in rows]
        rules = self.cfg.training
        sig = (
            tuple(tuple(sorted(r.items())) for r in rows),
            await asyncio.to_thread(lambda: tuple(training.signature(f, rules) for f in folders)),
            tuple(sorted(self.manifest.loras.items())),
        )
        if sig != self._character_sig:
            msg = await asyncio.to_thread(self._characters, rows)
            fingerprint = hashlib.sha256(msg.SerializeToString()).hexdigest()
            msg.version = self.store.bump("characters", fingerprint)  # SQLite im Loop-Thread
            self.hub.set_state(spb.TOPIC_CHARACTERS, msg.SerializeToString())
            self._character_sig = sig

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
            )
            for p in photos:
                char.photos.add(
                    name=p.name, status=p.status, width=p.width, height=p.height, note=p.note
                )
            for d in training.datasets(folders.datasets):
                char.datasets.add(**d)
            ids = {d.id for d in char.datasets}
            for lo in self.manifest.loras.values():
                if lo.dataset in ids:
                    self._add_lora(char, lo)
        return out

    async def _character_update(self, msg: commands_pb2.CharacterUpdate, call: _Call) -> str:
        """Charakterprofil anlegen oder ändern (Name, Trigger, Klasse); neue Profile bekommen ihr
        Kürzel und den Ordner ``local/characters/<kürzel>/`` (SP3 Schritt 1)."""
        slug = training.slugify(msg.slug or msg.name)
        row = self.store.save_character(
            msg.character_id, msg.revision, msg.name, msg.trigger, msg.class_word, slug
        )
        call.entity = f"character:{row['id']}"
        folders = self._folders(row)
        for folder in (folders.photos, folders.reference, folders.datasets, folders.training):
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await self.refresh_characters()
        log.info("Charakter %s gespeichert (%s)", row["id"], row["name"])
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
            honesty_rule=HONESTY_RULE, version=self.store.domain_version("influencers")
        )
        for row in self.store.influencers():
            item = msg.influencers.add(
                influencer_id=row["id"],
                name=row["name"],
                character_id=row["character_id"] or 0,
                persona=row["persona"],
                ai_notice=row["ai_notice"],
                revision=row["revision"],
            )
            for price in row["prices"]:
                item.prices.add(**price)
        return msg.SerializeToString()

    async def _influencer_update(self, msg: commands_pb2.InfluencerUpdate, call: _Call) -> str:
        """Profil der Influencerin speichern – gilt für alle Kunden (FRONT F4 V1.12 Punkt 12)."""
        if msg.character_id:
            self.store.character(msg.character_id)  # unbekannt: StoreError -> Ablehnung
        if len(msg.prices) > MAX_PRICE_ITEMS:
            return f"Höchstens {MAX_PRICE_ITEMS} Positionen in der Preisliste."
        for item in msg.prices:
            if not item.product.strip() or item.price_cents <= 0 or item.hd_surcharge_cents < 0:
                return "Preisliste: Produkt, Preis > 0 € und HD-Aufschlag ≥ 0 € angeben."
        influencer_id = self.store.save_influencer(
            msg.influencer_id,
            msg.revision,
            msg.name,
            msg.character_id or None,
            msg.persona.strip(),
            msg.ai_notice.strip(),
            [
                {
                    "product": i.product,
                    "price_cents": i.price_cents,
                    "hd_surcharge_cents": i.hd_surcharge_cents,
                }
                for i in msg.prices
            ],
        )
        call.entity = f"influencer:{influencer_id}"
        self.hub.set_state(spb.TOPIC_INFLUENCERS, self._influencers())
        return ""
