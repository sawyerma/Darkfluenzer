"""Grundgerüst des Cockpits: Zustand, Lebenszyklus, Typen (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..channels.instagram import InstagramAccount
from ..channels.telegram import TelegramAccount
from ..config import ComfyConfig, Config
from ..media import models
from ..nodes.base import Node, node_for
from ..payments.chain import WalletWatcher
from ..store import Store, sha256_file

if TYPE_CHECKING:
    from ..web.stream import Hub


log = logging.getLogger("darkfluenzer.server")


UNKNOWN_AFTER_RESTART = "Backend wurde während der Ausführung beendet – Ergebnis unbekannt."


@dataclass
class _Call:
    """Ein Befehl in Ausführung: Journal-Schlüssel und das, was der Handler festhält."""

    request_id: str
    payload_sha: str
    name: str
    entity: str = ""
    recorded: bool = False  # Handler hat Befehl und Effekt in einem Commit festgehalten (Render)


@dataclass(eq=False)
class _Lane:
    """Eine ComfyUI-Instanz mit eigener Warteschlange (PHASENPLAN_V0 §4.2): Zustand, ComfyUI-Queue,
    Fortschritt, FIFO der Backend-Renderjobs, Anhalten und zuletzt geladene Engine."""

    inst: ComfyConfig
    node: Node  # Prozess- und Ordnerzugriffe der Instanz (SP0 Schritt 3)
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex)  # Fortschritt nur an uns
    status: dict = field(default_factory=dict)
    queue: list[tuple[int, bool, str]] = field(default_factory=list)  # (Job, läuft?, prompt_id)
    progress: dict[str, tuple[int, int]] = field(default_factory=dict)
    renders: asyncio.Queue[int] = field(default_factory=asyncio.Queue)
    resume: asyncio.Event = field(default_factory=asyncio.Event)  # gesetzt = läuft
    busy: str = ""  # "start" | "stop", solange ein ComfyUI-Befehl läuft
    error: str = ""
    engine: str = ""  # Engine des letzten Laufs (Entladen beim Wechsel, Zulassung)
    waiting_job: int = 0  # Auftrag, der auf freien Speicher wartet
    need_gb: float = 0.0
    running_job: int = 0

    def __post_init__(self) -> None:
        self.resume.set()


def _document_attachment(local: Path, path: Path) -> dict:
    """Anhang einer fertigen Datei für den Postausgang; liest die ganze Datei (Hash), daher nur in
    einem Arbeiter-Thread aufrufen (SP0 Schritt 5, BUG-106)."""
    return {
        "kind": "document",
        "path": path.relative_to(local).as_posix(),
        "status": "saved",
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "mime": mimetypes.guess_type(path.name)[0] or "",
    }


def _unix_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


class CockpitBase:
    """Grundgerüst des Cockpits: Zustand, Lebenszyklus, gemeinsame Typen; Teil von ``Cockpit``."""

    def __init__(self, cfg: Config, hub: Hub, store: Store) -> None:
        self.cfg = cfg
        self.hub = hub
        self.store = store
        # Einzige Registry; Änderungen aus dem Cockpit ersetzen dieses Objekt nach dem Speichern.
        self.manifest = models.load_manifest(cfg.root)
        # Inhaltsstufe für Jobs/Medien vor Migration 14 (Regel 13, fail-closed)
        store.backfill_content_tiers({k: w.content for k, w in self.manifest.workflows.items()})
        self.lanes = {inst.name: _Lane(inst, node_for(cfg, inst)) for inst in cfg.instances}
        for name, lane in self.lanes.items():  # Pause übersteht den Neustart (BUG-046)
            if self.store.adapter_get("comfyui", name, "paused") == "1":
                lane.resume.clear()
        # Verzögerung des Hauptstrangs (Zeitpunkt, Sekunden), SP0 Schritt 5
        self._lags: deque[tuple[float, float]] = deque()
        self._memory: dict = {}  # letzte Messung: ram_total, ram_free (Bytes), swap (MB)
        self._cancelled: set[int] = set()  # laufende Jobs mit Abbruchwunsch des Betreibers
        self._seen_media = store.media_paths()  # bereits geprüfte Dateien des Galerie-Index
        self._folder_scan_at = float("-inf")  # letzter Ordner-Scan der Galerie (SP0 Schritt 6)
        self._character_sig: tuple = ()  # letzter Stand von Trainingsordner, Datensätzen, LoRAs
        # Registry-Änderungen und das Lesen der Workflow-Projektion nie gleichzeitig
        self._registry = asyncio.Lock()
        self._manifest_mtime = self._manifest_path().stat().st_mtime_ns
        self._tasks: set[asyncio.Task] = set()
        self._inflight: dict[str, asyncio.Future] = {}  # request_id -> laufende Ausführung
        self._resuming: set[int] = set()  # vor dem Neustart eingereichte Jobs (nur abholen)
        self._install_editor_copies()
        self._registry_version = store.bump("workflows", self._fingerprint())
        self._settle_open_commands()
        store.settle_sending()  # vor dem Neustart begonnener Versand: Ergebnis unbekannt
        store.default_contact()  # interner Kontakt Default existiert genau einmal
        self.wallet = (
            WalletWatcher(cfg, store, self._wallet_changed, self._payments_changed)
            if cfg.wallet
            else None
        )
        self.telegram = (
            TelegramAccount(cfg, store, self._on_inbound, self._channels_changed)
            if cfg.telegram
            else None
        )
        self.instagram = (
            InstagramAccount(cfg, store, self._on_inbound, self._channels_changed)
            if cfg.instagram
            else None
        )
        for adapter in filter(None, (self.telegram, self.instagram)):
            adapter.on_change_message = self._message_changed
            adapter.gate = self._delivery_gate
        self._settle_deliveries()

    def _adapter(self, platform: str):
        return {"telegram": self.telegram, "instagram": self.instagram}.get(platform)

    def _card(self, order, text: str) -> None:
        """Ereigniskarte im Verlauf des Angebots (die Auftragskarte selbst ist ANGEBOT)."""
        offer = self.store.offer(order.id)
        if offer is not None:
            self.store.add_system_card(offer["conversation_id"], text)

    def _wake(self, order) -> None:
        offer = self.store.offer(order.id)
        adapter = self._adapter(self.store.conversation_platform(offer["conversation_id"]))
        if adapter is not None:
            adapter.wake.set()

    def _journal_entry(self, call: _Call) -> dict:
        return {
            "request_id": call.request_id,
            "payload_sha": call.payload_sha,
            "command": call.name,
            "status": "accepted",
        }

    def _settle_open_commands(self) -> None:
        """Nach einem Neustart: angenommene Befehle ohne Ergebnis klären. Ein Render endet mit
        seinem Job (er läuft weiter oder wird abgeholt); alles andere ist UNKNOWN – kein
        automatischer Neuversuch."""
        for cmd in self.store.open_commands():
            entity = cmd["entity"]
            pending_job = (
                cmd["command"] == "render"
                and entity.startswith("job:")
                and self.store.job(int(entity[4:]))["status"] in ("queued", "running")
            )
            if not pending_job:
                self.store.finish_command(
                    cmd["request_id"], "unknown", detail=UNKNOWN_AFTER_RESTART
                )
