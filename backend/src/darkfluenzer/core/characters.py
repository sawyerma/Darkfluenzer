"""Charaktere, Influencerinnen, Trainingsordner (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import hashlib

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
        sig = (
            tuple(tuple(sorted(r.items())) for r in rows),
            await asyncio.to_thread(lambda: tuple(training.signature(f) for f in folders)),
            tuple(sorted(self.manifest.loras.items())),
        )
        if sig != self._character_sig:
            msg = await asyncio.to_thread(self._characters, rows)
            fingerprint = hashlib.sha256(msg.SerializeToString()).hexdigest()
            msg.version = self.store.bump("characters", fingerprint)  # SQLite im Loop-Thread
            self.hub.set_state(spb.TOPIC_CHARACTERS, msg.SerializeToString())
            self._character_sig = sig

    def _folders(self, row: dict) -> training.Folders:
        return training.profile_folders(self.cfg.root, row["data_dir"], row["photos_dir"])

    def _characters(self, rows: list[dict]) -> character_pb2.Characters:
        """Charakterprofile mit geprüftem Trainingsdatenordner, Datensätzen und LoRAs. Ohne
        Store-Zugriff (Zeilen kommen aus dem Loop-Thread), läuft im Worker-Thread (Scan hasht)."""
        out = character_pb2.Characters()
        for row in rows:
            folders = self._folders(row)
            photos = training.scan(folders.photos)
            char = out.characters.add(
                id=str(row["id"]),
                name=row["name"],
                photos_dir=row["photos_dir"],
                usable=sum(p.status == "ok" for p in photos),
                min_images=training.MIN_IMAGES,
                revision=row["revision"],
                photos_missing=not folders.photos.is_dir(),
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
        """Charakterprofil anlegen oder ändern; ein angegebener Trainingsdatenordner muss
        existieren (neue Profile ohne Angabe erhalten ihren eigenen Ordner)."""
        photos_dir = msg.photos_dir.strip()
        if photos_dir:
            target = training.profile_folders(self.cfg.root, "", photos_dir).photos
            if not target.is_dir():
                return f"Ordner {photos_dir} existiert nicht."
        row = self.store.save_character(msg.character_id, msg.revision, msg.name, photos_dir)
        call.entity = f"character:{row['id']}"
        await asyncio.to_thread(self._folders(row).photos.mkdir, parents=True, exist_ok=True)
        await self.refresh_characters()
        log.info("Charakter %s gespeichert (%s)", row["id"], row["name"])
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
