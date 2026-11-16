"""Lokaler Cockpit-Server: React-Build, Protobuf-WebSocket und Protobuf-Befehle auf EINEM Origin.

Schutz proportional zum Risiko (PHASENPLAN_FRONT_V1 F5): nur Loopback; Host-Prüfung gegen
DNS-Rebinding bei jeder Anfrage; Origin-Prüfung und Sitzungs-Cookie (HttpOnly, SameSite=Strict)
für WebSocket und geschützte Daten; zusätzlich CSRF-Token für zustandsändernde Befehle.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from aiohttp import web
from google.protobuf.message import DecodeError

from . import aimeta, approval, cloner, comfy, models, pipeline, runtime, training
from .channels.instagram import InstagramAccount, InstagramError
from .channels.telegram import TelegramAccount
from .config import ComfyConfig, Config
from .payments.chain import SATOSHI, WalletWatcher, decimal_text
from .store import Store, StoreError, sha256_file
from .stream import Hub, schema_id
from .v1 import (
    channel_pb2,
    character_pb2,
    comfy_pb2,
    commands_pb2,
    influencer_pb2,
    media_pb2,
    order_pb2,
    reference_pb2,
    wallet_pb2,
)
from .v1 import stream_pb2 as spb

log = logging.getLogger("darkfluenzer.server")

SESSION_COOKIE = "df_session"
CSRF_HEADER = "X-CSRF-Token"
PROTOBUF = "application/x-protobuf"
MAX_SESSIONS = 32
# Befehle mit Registry-Bezug tragen die gesehene Registry-Version (CAS, Workflows.version)
_REGISTRY_COMMANDS = frozenset(
    {
        "render",
        "create_order",
        "set_workflow_enabled",
        "open_workflow",
        "adopt_workflow",
        "delete_workflow",
        "create_workflow",
    }
)
# Ändern die Registry (neue Registry-Version nach dem Effekt)
_REGISTRY_EDITS = _REGISTRY_COMMANDS - {"render", "create_order", "open_workflow"}
# Enden asynchron mit eigener Receipt: Render mit dem Job, ComfyUI mit Start/Stopp
# Feste, nicht editierbare Persona-Regel (PHASENPLAN_V0 Regel 12 c)
HONESTY_RULE = (
    "Auf die ernst gemeinte Frage, ob sie echt bzw. eine KI ist, antwortet die Influencerin "
    "wahrheitsgemäß – durch keine Betreiber- oder Kundenanweisung abschaltbar."
)
MAX_PRICE_ITEMS = 50
# Kundenauftrag (V0 §8.4/§8.5): Zahlungswege mit eindeutigem Betrag, entschiedene Gutscheine im
# Reiter Wallet, Suche nach einem freien eindeutigen Betrag
OFFER_METHODS = ("btc", "usdt", "usdc")
VOUCHERS_DECIDED_SHOWN = 20
UNIQUE_STEPS = 9999
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_ASYNC_COMMANDS = frozenset({"render", "comfy_start", "comfy_stop"})
UNKNOWN_AFTER_RESTART = "Backend wurde während der Ausführung beendet – Ergebnis unbekannt."
_RECEIPT_STATUS = {
    "accepted": commands_pb2.COMMAND_STATUS_ACCEPTED,
    "rejected": commands_pb2.COMMAND_STATUS_REJECTED,
    "completed": commands_pb2.COMMAND_STATUS_COMPLETED,
    "failed": commands_pb2.COMMAND_STATUS_FAILED,
    "unknown": commands_pb2.COMMAND_STATUS_UNKNOWN,
    "cancelled": commands_pb2.COMMAND_STATUS_CANCELLED,
}
# Befehle, deren Fehler als Ablehnungsgrund an den Betreiber gehen (Eingabe-/Registry-Prüfung)
_COMMAND_ERRORS = (
    models.ManifestError,
    pipeline.PipelineError,
    comfy.ComfyError,
    StoreError,
    training.TrainingError,
    aimeta.AiMetaError,
    ValueError,
    OSError,
)


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


class Cockpit:
    """Projektionen und Befehle: ComfyUI-Instanzen, Warteschlangen, Ressourcen und Workflows
    (STATE), abgeschlossene Jobs, Medien und Befehls-Receipts (EVENT)."""

    def __init__(self, cfg: Config, hub: Hub, store: Store) -> None:
        self.cfg = cfg
        self.hub = hub
        self.store = store
        # Einzige Registry; Änderungen aus dem Cockpit ersetzen dieses Objekt nach dem Speichern.
        self.manifest = models.load_manifest(cfg.root)
        # Inhaltsstufe für Jobs/Medien vor Migration 14 (Regel 13, fail-closed)
        store.backfill_content_tiers({k: w.content for k, w in self.manifest.workflows.items()})
        self.lanes = {inst.name: _Lane(inst) for inst in cfg.instances}
        self._memory: dict = {}  # letzte Messung: ram_total, ram_free (Bytes), swap (MB)
        self._cancelled: set[int] = set()  # laufende Jobs mit Abbruchwunsch des Betreibers
        self._seen_media = store.media_paths()  # bereits geprüfte Dateien des Galerie-Index
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

    def _install_editor_copies(self) -> None:
        """Editor-Kopien für "Öffnen" in der jeweils ausführenden, eingerichteten Instanz."""
        for key, wf in self.manifest.workflows.items():
            if self._lane_of(wf) is not None:
                comfy.install_editor_copy(self.cfg, self.manifest, key)

    def _lane_of(self, wf: models.Workflow) -> _Lane | None:
        """Bahn der Instanz, die diesen Workflow ausführt (None: Instanz nicht eingerichtet)."""
        return self.lanes.get(self.manifest.engines[wf.engine].instance)

    def _lane_of_job(self, job_id: int) -> _Lane:
        wf = self.manifest.workflows.get(self.store.job(job_id)["workflow"])
        return (self._lane_of(wf) if wf else None) or self.lanes["media"]

    def _fingerprint(self) -> str:
        """Hash über Manifest und alle registrierten UI-/API-Graphen (Registry-Version)."""
        digest = hashlib.sha256(self._manifest_path().read_bytes())
        for key in sorted(self.manifest.workflows):
            wf = self.manifest.workflows[key]
            for rel in (wf.ui, wf.api):
                digest.update((self.manifest.root / "workflows" / rel).read_bytes())
        return digest.hexdigest()

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

    def _manifest_path(self) -> Path:
        return self.cfg.root / models.MANIFEST_RELATIVE

    def _reload_if_changed(self) -> str | None:
        """Externe Änderungen an manifest.toml (CLI, git) übernehmen; ungültige Fassung -> alte
        Registry bleibt aktiv, Fehler im Log. Liefert den neuen Registry-Hash oder None."""
        mtime = self._manifest_path().stat().st_mtime_ns
        if mtime == self._manifest_mtime:
            return None
        self._manifest_mtime = mtime
        try:
            self.manifest = models.load_manifest(self.cfg.root)
        except models.ManifestError as exc:
            log.error("Geänderte Registry ungültig, bisherige bleibt aktiv: %s", exc)
            return None
        self._install_editor_copies()
        log.info("Registry neu geladen (%d Workflows)", len(self.manifest.workflows))
        return self._fingerprint()

    def enqueue_existing(self) -> None:
        """Nach einem Neustart: bei ComfyUI eingereichte Jobs abholen statt neu rendern
        (prompt_id), nie eingereichte erneut einreihen, angelegte in Reihenfolge fortsetzen."""
        for job_id, pid in self.store.running_jobs():
            if pid and pid != os.getpid() and runtime.pid_alive(pid):
                continue  # ein anderer Prozess (z. B. CLI-Evaluation) führt ihn aus
            if self.store.job(job_id)["prompt_id"]:
                self._resuming.add(job_id)
                self._lane_of_job(job_id).renders.put_nowait(job_id)
            else:
                self.store.requeue_job(job_id)
        for job_id, _ in self.store.queued_jobs():
            self._lane_of_job(job_id).renders.put_nowait(job_id)

    async def render_worker(self, lane: _Lane) -> None:
        """Führt die Renderjobs einer Instanz nacheinander (FIFO) aus; vor jedem Start prüft die
        gemeinsame Zulassung den freien Speicher (§4.2)."""
        while True:
            job_id = await lane.renders.get()
            await lane.resume.wait()  # angehalten: nächster Job wartet
            job = self.store.job(job_id)
            status = job["status"]
            if status != "queued" and not (status == "running" and job_id in self._resuming):
                continue  # inzwischen entfernt
            self._resuming.discard(job_id)
            engine = job["engine"]
            eng = self.manifest.engines.get(engine)
            modelfree = eng is not None and eng.modelfree  # lässt geladene Modelle in Ruhe
            if not modelfree and not await self._admit(lane, job_id, engine):
                continue  # während des Wartens auf Speicher entfernt
            lane.running_job = job_id
            try:
                await asyncio.to_thread(
                    pipeline.run_render,
                    self.cfg,
                    self.manifest,
                    job_id,
                    client_id=lane.client_id,
                    is_cancelled=lambda job=job_id: job in self._cancelled,
                    unload_first=bool(lane.engine) and lane.engine != engine and not modelfree,
                )
            except Exception as exc:  # im Journal als fehlgeschlagen festgehalten
                log.error("Renderjob %s fehlgeschlagen: %s", job_id, exc)
            lane.engine, lane.running_job = lane.engine if modelfree else engine, 0
            pipeline.advance_order(self.store, job_id)  # Stufe vollständig? (SQLite im Loop)
            if (stage_id := self.store.job(job_id).get("stage_id")) is not None:
                self._cloner_delivery(self.store.stage(stage_id).order_id)
            self._orders_changed()
            self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
            self.hub.push_events(spb.TOPIC_MEDIA_ADDED)
            self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
            self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
            self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())

    def _need_gb(self, engine: str) -> float:
        """Speicherbedarf einer Engine: gemessene Spitze des letzten Laufs, bis zur ersten
        Messung die Summe ihrer Modelldateien."""
        if (peak := self.store.engine_peak_gb(engine)) is not None:
            return peak
        return sum(mf.size for mf in self.manifest.engine_files(engine)) / 1e9

    async def _admit(self, lane: _Lane, job_id: int, engine: str) -> bool:
        """Zulassung (§4.2): startet erst, wenn nach dem Bedarf die Reserve frei bleibt. Ist sie zu
        knapp, entlädt eine ruhende andere Instanz ihre Modelle; sonst wartet der Auftrag.
        False: der Auftrag wurde während des Wartens entfernt."""
        need = self._need_gb(engine)
        if lane.engine == engine:
            return True  # gleiche Engine: Modelle sind bereits geladen
        while True:
            if self.store.job(job_id)["status"] not in ("queued", "running"):
                lane.waiting_job, lane.need_gb = 0, 0.0
                self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
                return False
            free = (await asyncio.to_thread(self._measure)).get("ram_free", 0) / 2**30
            if not free or free - need >= self.cfg.server.memory_reserve_gb:
                break
            idle = [
                other
                for other in self.lanes.values()
                if other is not lane and other.engine and not other.running_job
            ]
            if idle:
                for other in idle:
                    await asyncio.to_thread(comfy.ComfyClient(other.inst.url).free)
                    log.info(
                        "Zulassung: %s entlädt %s für Auftrag %s",
                        other.inst.name,
                        other.engine,
                        job_id,
                    )
                    other.engine = ""
                continue
            if not any(o.running_job for o in self.lanes.values() if o is not lane):
                # nichts mehr freizugeben und keine andere Instanz arbeitet: Warten hilft nicht
                log.warning(
                    "Zulassung: Auftrag %s braucht %.1f GB, frei %.1f GB (Reserve %.0f GB) – "
                    "nichts mehr freizugeben, Start",
                    job_id,
                    need,
                    free,
                    self.cfg.server.memory_reserve_gb,
                )
                break
            lane.waiting_job, lane.need_gb = job_id, round(need, 1)
            self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
            await asyncio.sleep(self.cfg.server.observe_s)
        if lane.waiting_job:
            lane.waiting_job, lane.need_gb = 0, 0.0
            self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
        return True

    def _measure(self) -> dict:
        """Freier Unified Memory (über eine erreichbare Instanz) und macOS-Swap."""
        for lane in self.lanes.values():
            if lane.status.get("health"):
                try:
                    stats = comfy.ComfyClient(lane.inst.url, timeout=self.cfg.server.observe_s)
                    system = stats._json("GET", "/system_stats").get("system") or {}
                except comfy.ComfyError:
                    continue
                self._memory = {
                    "ram_total": int(system.get("ram_total") or 0),
                    "ram_free": int(system.get("ram_free") or 0),
                    "swap": comfy.swap_used_mb(),
                }
                return self._memory
        self._memory = {"swap": comfy.swap_used_mb()}
        return self._memory

    async def observe(self) -> None:
        """Beobachtet ComfyUI, Modelldateien und Job-Journal; gepusht wird nur bei Änderung."""
        while True:
            try:
                await self.refresh_comfy()
                await asyncio.to_thread(self._measure)
                self.hub.set_state(spb.TOPIC_RESOURCES, self._resources())
                async with self._registry:
                    if fingerprint := await asyncio.to_thread(self._reload_if_changed):
                        self._registry_version = self.store.bump("workflows", fingerprint)
                    workflows = await asyncio.to_thread(self._workflows)
                self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
                await self.refresh_characters()
                self.hub.set_state(spb.TOPIC_ORDERS_ACTIVE, self._orders_active())
                self.hub.set_state(spb.TOPIC_CHANNELS, self._channels())
                self.hub.set_state(spb.TOPIC_WALLET, self._wallet_state())
                self.hub.set_state(spb.TOPIC_INFLUENCERS, self._influencers())
                self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
                self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
                await asyncio.to_thread(
                    pipeline.scan_media, self.cfg, self._seen_media, self.cfg.server.media_settle_s
                )
                self.hub.push_events(spb.TOPIC_MEDIA_ADDED)
            except Exception:  # eine fehlerhafte Runde beendet die Beobachtung nicht
                log.exception("Beobachtung fehlgeschlagen")
            await asyncio.sleep(self.cfg.server.observe_s)

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

    @staticmethod
    def _add_lora(char: character_pb2.Character, lo) -> None:
        char.loras.add(
            key=lo.key,
            base_engine=lo.base_engine,
            dataset=lo.dataset,
            trigger=lo.trigger,
            steps=lo.steps,
            rank=lo.rank,
            status=lo.status,
            created_at=lo.created_at,
        )

    async def refresh_comfy(self) -> None:
        for lane in self.lanes.values():
            try:
                lane.status = await asyncio.to_thread(runtime.status, self.cfg, lane.inst.name)
            except runtime.RuntimeFailure as exc:
                lane.status = {"state": "error", "managed": False}
                lane.error = str(exc)
            lane.queue = (
                await asyncio.to_thread(self._read_queue, lane) if lane.status.get("health") else []
            )
            queued = {prompt_id for _, _, prompt_id in lane.queue}
            lane.progress = {p: v for p, v in lane.progress.items() if p in queued}
        self.hub.set_state(spb.TOPIC_COMFY_INSTANCES, self._instances())
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    async def progress_listener(self, lane: _Lane) -> None:
        """Fortschritt (z. B. Sampler-Schritte) der eigenen Aufträge aus ComfyUIs WebSocket in die
        Warteschlange übernehmen; bei Verbindungsverlust nach der Beobachtungspause erneut."""
        while True:
            if lane.status.get("health"):
                try:
                    async for prompt_id, value, maximum in comfy.progress_events(
                        lane.inst.url, lane.client_id
                    ):
                        if maximum:
                            lane.progress[prompt_id] = (value, maximum)
                        else:
                            lane.progress.pop(prompt_id, None)
                        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
                except Exception as exc:  # ComfyUI beendet/neu gestartet: später neu verbinden
                    log.debug("ComfyUI-Fortschritt %s getrennt: %s", lane.inst.name, exc)
            await asyncio.sleep(self.cfg.server.observe_s)

    def _read_queue(self, lane: _Lane) -> list[tuple[int, bool, str]]:
        client = comfy.ComfyClient(lane.inst.url, timeout=self.cfg.server.observe_s)
        try:
            return client.queued_jobs()
        except comfy.ComfyError:
            return []

    def _jobs_active(self) -> bytes:
        """FIFO-Sicht je Instanz: ComfyUI (läuft, wartet), danach angelegte, noch nicht
        übergebene Jobs."""
        queued = [job_id for job_id, _ in self.store.queued_jobs()]
        in_comfy = [job_id for lane in self.lanes.values() for job_id, _, _ in lane.queue if job_id]
        ids = in_comfy + [j for j in queued if j not in in_comfy]
        brief = self.store.jobs_brief(ids) if ids else {}
        msg = comfy_pb2.JobsActive(
            paused=[n for n, lane in self.lanes.items() if not lane.resume.is_set()],
            version=self.store.domain_version("jobs"),
        )

        def add(lane: _Lane, job_id: int, running: bool, prompt_id: str = "") -> None:
            workflow, params = brief.get(job_id, ("", {}))
            value, maximum = lane.progress.get(prompt_id, (0, 0)) if running else (0, 0)
            job = msg.jobs.add(
                job_id=job_id,
                workflow=workflow,
                running=running,
                progress_value=value,
                progress_max=maximum,
                instance=lane.inst.name,
            )
            job.params.update({k: _param_text(k, v) for k, v in params.items()})

        for lane in self.lanes.values():
            for job_id, running, prompt_id in lane.queue:
                add(lane, job_id, running, prompt_id)
        for job_id in queued:
            if job_id not in in_comfy:
                add(self._lane_of_job(job_id), job_id, False)
        return msg.SerializeToString()

    def _workflows(self) -> bytes:
        engines = models.status(self.manifest, models.models_dir(self.cfg.root))["engines"]
        msg = comfy_pb2.Workflows(version=self._registry_version)
        for key, wf in self.manifest.workflows.items():
            eng, ready = self.manifest.engines[wf.engine], engines[wf.engine]
            lane = self._lane_of(wf)
            registry_ui = self.manifest.root / "workflows" / wf.ui
            editor = comfy.editor_file(lane.inst, key) if lane else None
            info = msg.workflows.add(
                key=key,
                engine=wf.engine,
                engine_title=eng.title,
                kind=eng.kind,
                status=wf.status,
                models_ready=ready["ready"],
                missing_gb=ready["missing_gb"],
                usage=eng.usage,
                title=wf.title,
                enabled=wf.enabled,
                editor_changed=editor is not None
                and editor.is_file()
                and editor.read_bytes() != registry_ui.read_bytes(),
                instance=eng.instance,
                training=wf.training,
                role=eng.role,
                content=wf.content,
            )
            if {"width", "height"} <= set(wf.params):
                for name, (width, height) in eng.formats.items():
                    info.formats.add(name=name, width=width, height=height)
            graph = comfy.load_graph(self.manifest, wf)
            if wf.video:  # Länge in Sekunden: Gesamtlänge (Grund) und Abschnittslänge (Experte)
                v = wf.video
                fps_p = wf.params[v.fps]
                fps = float(graph[fps_p.node]["inputs"][fps_p.input])
                frames = int(graph[v.length_node]["inputs"][v.length_input])
                segment = (v.segment_frames_max - 1) / fps
                for name, label, high, value, expert in (
                    ("duration_s", "Gesamtlänge (s)", self.cfg.production.video_max_s,
                     (frames - 1) / fps, False),
                    ("segment_s", f"Abschnittslänge (s, höchstens {v.segment_frames_max} Frames)",
                     segment, segment, True),
                ):  # fmt: skip
                    info.params.add(
                        name=name, type="float", min=0.25, max=high, label=label, expert=expert,
                        number=round(value, 2),
                    )  # fmt: skip
            for name, p in wf.params.items():
                param = info.params.add(
                    name=name,
                    type=p.type,
                    required=p.required,
                    upload=p.upload,
                    multiple_of=p.multiple_of or 0,
                    choices=[str(c) for c in p.choices],
                    label=p.label,
                    expert=p.is_expert,
                    reference=p.reference,
                )
                if p.min is not None:
                    param.min = p.min
                if p.max is not None:
                    param.max = p.max
                default = graph[p.node]["inputs"].get(p.input)
                if p.upload or default is None:
                    continue
                if p.type == "int":
                    param.integer = int(default)
                elif p.type == "float":
                    param.number = float(default)
                else:
                    param.text = str(default)
        return msg.SerializeToString()

    def _instances(self) -> bytes:
        msg = comfy_pb2.ComfyInstances()
        for lane in self.lanes.values():
            msg.instances.append(self._comfy_status(lane))
        return msg.SerializeToString()

    def _resources(self) -> bytes:
        mem = self._memory
        msg = comfy_pb2.Resources(
            ram_total_gb=round(mem.get("ram_total", 0) / 2**30, 1),
            ram_free_gb=round(mem.get("ram_free", 0) / 2**30, 1),
            swap_used_mb=round(mem.get("swap", 0.0), 1),
            reserve_gb=self.cfg.server.memory_reserve_gb,
        )
        for lane in self.lanes.values():
            msg.instances.add(
                name=lane.inst.name,
                engine=lane.engine,
                waiting_job=lane.waiting_job,
                need_gb=lane.need_gb,
            )
        return msg.SerializeToString()

    def _comfy_status(self, lane: _Lane) -> comfy_pb2.ComfyStatus:
        st = lane.status
        health = st.get("health") or {}
        running = sum(1 for _, r, _ in lane.queue if r)
        if lane.busy == "start":
            state = comfy_pb2.COMFY_STATE_STARTING
        elif lane.busy == "stop":
            state = comfy_pb2.COMFY_STATE_STOPPING
        elif health and st.get("state") in ("running", "foreign"):
            state = comfy_pb2.COMFY_STATE_BUSY if running else comfy_pb2.COMFY_STATE_READY
            lane.error = ""
        elif st.get("state") == "starting":
            state = comfy_pb2.COMFY_STATE_STARTING
        elif st.get("state") == "stopped":
            state = comfy_pb2.COMFY_STATE_FAILED if lane.error else comfy_pb2.COMFY_STATE_STOPPED
        else:  # unhealthy, fremder Prozess ohne ComfyUI-Antwort, Prüffehler
            state = comfy_pb2.COMFY_STATE_UNREACHABLE
        return comfy_pb2.ComfyStatus(
            state=state,
            managed=bool(st.get("managed")),
            url=lane.inst.url,
            version=health.get("comfyui_version") or "",
            device=health.get("device_type") or "",
            error=lane.error,
            queue_running=running,
            queue_pending=len(lane.queue) - running,
            name=lane.inst.name,
        )

    async def command(
        self, req: commands_pb2.CommandRequest, payload_sha: str
    ) -> commands_pb2.CommandResponse:
        """Führt einen Befehl höchstens einmal je request_id aus (Befehlsjournal in SQLite, auch
        über Neustarts). Dieselbe ID mit demselben Befehl liefert dieselbe Antwort ohne zweite
        Ausführung, mit anderem Befehl eine Ablehnung."""
        rid = req.request_id
        while rid in self._inflight:  # dieselbe ID parallel: auf die erste Ausführung warten
            await asyncio.shield(self._inflight[rid])
        known = self.store.command(rid)
        if known is not None:
            if known["payload_sha"] != payload_sha:
                return _response(rid, "request_id wurde bereits für einen anderen Befehl verwendet")
            rejected = known["status"] == "rejected"
            return _response(rid, known["detail"] if rejected else "", known["entity"])
        done = asyncio.get_running_loop().create_future()
        self._inflight[rid] = done
        try:
            return await self._execute(req, payload_sha)
        finally:
            del self._inflight[rid]
            done.set_result(None)

    async def _execute(
        self, req: commands_pb2.CommandRequest, payload_sha: str
    ) -> commands_pb2.CommandResponse:
        which = req.WhichOneof("command") or ""
        call = _Call(req.request_id, payload_sha, which)
        handlers = {
            "render": self._render,
            "create_order": self._create_order,
            "select_candidate": self._select_candidate,
            "retry_stage": self._retry_stage,
            "mark_read": self._mark_read,
            "send_reply": self._send_reply,
            "default_contact_update": self._default_contact_update,
            "start_cloner_order": self._start_cloner_order,
            "character_update": self._character_update,
            "influencer_update": self._influencer_update,
            "media_content_tier": self._media_content_tier,
            "customer_age_mark": self._customer_age_mark,
            "send_ai_notice": self._send_ai_notice,
            "create_offer": self._create_offer,
            "approve_artifact": self._approve_artifact,
            "retry_delivery": self._retry_delivery,
            "payment_assign": self._payment_assign,
            "gift_card_confirm": self._gift_card_confirm,
            "channel_account_login": self._channel_login,
            "channel_account_update": self._channel_update,
            "set_workflow_enabled": self._set_enabled,
            "open_workflow": self._open,
            "adopt_workflow": self._adopt,
            "delete_workflow": self._delete,
            "create_workflow": self._create,
            "cancel_job": self._cancel,
            "pause_queue": self._pause,
            "delete_media": self._delete_media,
        }
        version = 0
        if which in ("comfy_start", "comfy_stop"):
            reason = self._comfy_command(which, getattr(req, which).instance or "media", call)
        elif which not in handlers:
            reason = "Unbekannter Befehl"
        else:
            async with self._registry:
                if which in _REGISTRY_COMMANDS and req.expected_version != self._registry_version:
                    reason = "Workflows wurden inzwischen geändert – Ansicht ist aktualisiert."
                else:
                    try:
                        reason = await handlers[which](getattr(req, which), call)
                    except _COMMAND_ERRORS as exc:
                        reason = str(exc)
                    if not reason and which in _REGISTRY_EDITS:
                        fingerprint = await asyncio.to_thread(self._fingerprint)
                        self._registry_version = self.store.bump("workflows", fingerprint)
                        version = self._registry_version
                workflows = await asyncio.to_thread(self._workflows)
            self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
            self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
        if not call.recorded:
            status = "rejected" if reason else "accepted"
            self.store.record_command(
                call.request_id,
                payload_sha,
                which or "unbekannt",
                status,
                entity=call.entity,
                detail=reason,
            )
            if not reason and which not in _ASYNC_COMMANDS:
                self.store.finish_command(call.request_id, "completed", version=version)
        self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
        return _response(call.request_id, reason, call.entity)

    def _workflow(self, key: str) -> models.Workflow:
        wf = self.manifest.workflows.get(key)
        if wf is None:
            raise models.ManifestError(f"Workflow '{key}' ist nicht registriert.")
        return wf

    def _not_startable(self, wf: models.Workflow) -> str:
        """Gates vor einem neuen Job: Betreiberschalter, Abnahme-Sperre, Modellbereitschaft."""
        if not wf.enabled:
            return "Workflow ist deaktiviert."
        if wf.status == "GESPERRT":
            return "Workflow ist gesperrt."
        eng = models.status(self.manifest, models.models_dir(self.cfg.root))["engines"][wf.engine]
        return "" if eng["ready"] else f"Modelle fehlen ({eng['missing_gb']:.1f} GB)."

    async def _render(self, msg: commands_pb2.Render, call: _Call) -> str:
        wf = self._workflow(msg.workflow)
        call.entity = f"workflow:{wf.key}"
        lane = self._lane_of(wf)
        if lane is None:
            return "Die ausführende ComfyUI-Instanz ist nicht eingerichtet."
        if reason := await asyncio.to_thread(self._not_startable, wf):
            return reason
        values = {
            v.name: getattr(v, v.WhichOneof("value")) for v in msg.values if v.WhichOneof("value")
        }
        inputs = {}
        if msg.repeat_job_id:  # Wiederholen/Variieren: Parameter und Eingaben des Ursprungsjobs
            origin = self.store.job(msg.repeat_job_id)
            if origin["workflow"] != wf.key:
                return (
                    f"Auftrag {msg.repeat_job_id} gehört zu {origin['workflow']}, nicht {wf.key}."
                )
            for name, value in origin["params"].items():
                if name in wf.params and wf.params[name].upload:
                    inputs[name] = value
                elif name in wf.params or name in pipeline.VIDEO_KEYS:
                    values.setdefault(name, value)
        inputs.update(await self._inputs(wf, msg.files))
        dataset = None
        if wf.training:  # Datensatzversion der geeigneten Bilder des gewählten Charakters
            if not msg.character_id:
                return "Für ein Training einen Charakter wählen."
            folders = self._folders(self.store.character(msg.character_id))
            path = await asyncio.to_thread(training.build_dataset, folders)
            dataset = path.relative_to(self.cfg.local).as_posix()
        job_id = pipeline.create_render(
            self.store,
            self.manifest,
            wf.key,
            values,
            inputs,
            video_max_s=self.cfg.production.video_max_s,
            dataset=dataset,
            parent_media_id=msg.parent_media_id or None,
            command={
                "request_id": call.request_id,
                "payload_sha": call.payload_sha,
                "command": call.name,
                "status": "accepted",
            },
        )
        call.entity, call.recorded = f"job:{job_id}", True
        log.info("Renderjob %s (%s, %s) eingereiht", job_id, wf.key, lane.inst.name)
        lane.renders.put_nowait(job_id)
        return ""

    async def _inputs(self, wf: models.Workflow, files) -> dict[str, str]:
        """Eingabedateien eines Befehls: Galerie-Medium per ID (SHA-256 geprüft), Vorlage aus der
        Bibliothek oder Upload; Vorlagen-Parameter landen zusätzlich in der Bibliothek (C1)."""
        inputs: dict[str, str] = {}
        for f in files:
            p = wf.params.get(f.param)
            if p is None or not p.upload:
                raise pipeline.PipelineError(f"{f.param}: kein Upload-Parameter von {wf.key}.")
            if f.reference_id:
                if not p.reference:
                    raise pipeline.PipelineError(f"{f.param}: hier wird keine Vorlage erwartet.")
                ref = self.store.reference(f.reference_id)
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.input_from_file, self.cfg, ref["path"], ref["sha256"]
                )
                source = f"reference:{f.reference_id}"
            elif f.media_id:  # exakte Galerie-Datei über ihre unveränderliche ID
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.input_from_media, self.cfg, f.media_id
                )
                source = f"media:{f.media_id}"
            else:
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.store_input, self.cfg, f.data, f.filename
                )
                source = "upload"
            if p.reference:
                await self._register_reference(inputs[f.param], source)
        return inputs

    async def _register_reference(self, rel: str, source: str) -> None:
        """Datei unter local/ als Vorlage führen (gleicher Inhalt = dieselbe Vorlage)."""
        digest = await asyncio.to_thread(pipeline.sha256_file, self.cfg.local / rel)
        _, new = self.store.add_reference(rel, digest, "image", source)
        if new:
            self.hub.push_events(spb.TOPIC_REFERENCE_ADDED)

    def _journal_entry(self, call: _Call) -> dict:
        return {
            "request_id": call.request_id,
            "payload_sha": call.payload_sha,
            "command": call.name,
            "status": "accepted",
        }

    def _enqueue(self, jobs: list[int]) -> None:
        for job_id in jobs:
            lane = self._lane_of_job(job_id)
            lane.renders.put_nowait(job_id)

    def _orders_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_ORDERS_ACTIVE, self._orders_active())
        self.hub.push_events(spb.TOPIC_ORDER_UPDATED)
        self.hub.push_events(spb.TOPIC_CONVERSATION_EVENT)  # Systemkarten der Aufträge
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    async def _create_order(self, msg: commands_pb2.CreateOrder, call: _Call) -> str:
        """Auftrag mit Kandidaten (V0 §4.3); Auftrag, Stufe, Jobs und Befehl in einem Commit."""
        wf = self._workflow(msg.workflow)
        call.entity = f"workflow:{wf.key}"
        prod = self.cfg.production
        count = msg.candidates or prod.candidates_default
        if count > prod.candidates_max:
            return f"Höchstens {prod.candidates_max} Kandidaten je Auftrag."
        for key in filter(None, (wf.key, msg.finish_workflow)):
            target = self._workflow(key)
            if self._lane_of(target) is None:
                return "Die ausführende ComfyUI-Instanz ist nicht eingerichtet."
            if reason := await asyncio.to_thread(self._not_startable, target):
                return f"{target.title}: {reason}"
        values = {
            v.name: getattr(v, v.WhichOneof("value")) for v in msg.values if v.WhichOneof("value")
        }
        inputs = await self._inputs(wf, msg.files)
        order_no, jobs = pipeline.create_order(
            self.store,
            self.manifest,
            wf.key,
            values,
            inputs,
            count=count,
            finish_workflow=msg.finish_workflow,
            parent_media_id=msg.parent_media_id or None,
            command=self._journal_entry(call),
            customer_order_no=msg.customer_order_no,
            video_max_s=self.cfg.production.video_max_s,
        )
        call.entity, call.recorded = f"order:{order_no}", True
        log.info("Auftrag %s: %d Kandidaten von %s eingereiht", order_no, len(jobs), wf.key)
        self._enqueue(jobs)
        self._orders_changed()
        if msg.customer_order_no:
            self._message_changed(0)  # Auftragskarte im Kundenverlauf
        return ""

    async def _select_candidate(self, msg: commands_pb2.SelectCandidate, call: _Call) -> str:
        call.entity = f"order:{msg.order_no}"
        jobs = pipeline.select_candidate(
            self.cfg,
            self.store,
            self.manifest,
            msg.order_no,
            msg.media_id,
            self._journal_entry(call),
        )
        call.recorded = True
        log.info("Auftrag %s: Medium %s ausgewählt", msg.order_no, msg.media_id)
        if not jobs:  # ohne Fertigstellen: das Gewählte geht ggf. an den Default-Nutzer
            self._cloner_delivery(self.store.order(msg.order_no).id, selected=msg.media_id)
        self._enqueue(jobs)
        self._orders_changed()
        return ""

    async def _retry_stage(self, msg: commands_pb2.RetryStage, call: _Call) -> str:
        call.entity = f"order:{msg.order_no}"
        jobs = pipeline.retry_stage(
            self.store,
            self.manifest,
            msg.order_no,
            msg.seq,
            self.cfg.production.stage_attempts_max,
            self._journal_entry(call),
            video_max_s=self.cfg.production.video_max_s,
        )
        call.recorded = True
        log.info("Auftrag %s: Stufe %s wiederholt (%d Jobs)", msg.order_no, msg.seq, len(jobs))
        self._enqueue(jobs)
        self._orders_changed()
        return ""

    # ------------------------------------------------------------ Nachrichten (C2/C5)

    def _channels(self) -> bytes:
        """STATE channels: Zustand je Kanal; nicht eingerichtete Kanäle mit dem, was fehlt."""
        msg = channel_pb2.Channels(version=self.store.domain_version("channels"))
        if self.telegram:
            msg.channels.add(**self.telegram.status())
        else:
            msg.channels.add(
                platform="telegram", state="OFF", missing="Abschnitt [telegram_account]"
            )
        if self.instagram:
            msg.channels.add(**self.instagram.status())
        else:
            msg.channels.add(platform="instagram", state="OFF", missing="Abschnitt [instagram]")
        msg.channels.add(platform="whatsapp", state="OFF", missing="WhatsApp folgt später (C7)")
        return msg.SerializeToString()

    # ------------------------------------------------------------ Wallet (C5a)

    def _wallet_state(self) -> bytes:
        """STATE wallet: Konten mit Guthaben, Euro-Wert, Kurszeit, letzter Prüfung, Quellen."""
        msg = wallet_pb2.Wallet(version=self.store.domain_version("payments"))
        for v in self.store.vouchers(VOUCHERS_DECIDED_SHOWN):
            msg.vouchers.add(
                voucher_id=v["id"],
                customer_id=v["customer_id"],
                customer_no=v["customer_no"],
                display_name=v["display_name"] or "",
                code=v["code"],
                status=v["status"],
                amount_cents=v["amount_cents"] or 0,
                at_ms=_unix_ms(v["created_at"]),
                decided_ms=_unix_ms(v["decided_at"]) if v["decided_at"] else 0,
            )
        for o in self.store.open_offers():
            msg.open_offers.add(
                order_no=o["order_no"],
                customer_id=o["customer_id"],
                customer_no=o["customer_no"],
                display_name=o["display_name"] or "",
                product=o["product"] + (" + HD" if o["hd"] else ""),
                price_cents=o["price_cents"],
                expires_ms=_unix_ms(o["expires_at"]),
                amounts=[f"{m.upper()} {a}" for m, a in o["amounts"].items()],
            )
        if self.wallet is None:
            for key, title, network in (("btc", "Bitcoin", "bitcoin"), ("bsc", "BSC", "bsc")):
                msg.accounts.add(
                    key=key, title=title, network=network, state="MISSING",
                    missing="Abschnitt [wallet] in config.toml",
                )  # fmt: skip
            return msg.SerializeToString()
        for acc in self.wallet.accounts():
            balances = acc.pop("balances")
            item = msg.accounts.add(**acc)
            for b in balances:
                item.balances.add(**b)
        for src in self.wallet.sources():
            msg.sources.add(**src)
        return msg.SerializeToString()

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

    async def _media_content_tier(self, msg: commands_pb2.MediaContentTier, call: _Call) -> str:
        """Inhaltsstufe anheben (Befehl 43, Regel 13: nur anhebbar)."""
        call.entity = f"media:{msg.media_id}"
        self.store.raise_content_tier(msg.media_id)
        self.hub.push_events(spb.TOPIC_MEDIA_ADDED)  # geänderter Eintrag per Push
        return ""

    async def _customer_age_mark(self, msg: commands_pb2.CustomerAgeMark, call: _Call) -> str:
        """Altersangabe der Akte (Befehl 44; nur Betreiber, nie das LLM)."""
        call.entity = f"customer:{msg.customer_id}"
        self.store.set_age_mark(msg.customer_id, msg.mark)
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""

    async def _send_ai_notice(self, msg: commands_pb2.SendAiNotice, call: _Call) -> str:
        """KI-Hinweis der Influencerin einmal je Kanalidentität (Befehl 45, Regel 12 b)."""
        call.entity = f"customer:{msg.customer_id}"
        figure = next(iter(self.store.influencers()), None)
        if figure is None or not figure["ai_notice"].strip():
            return "KI-Hinweistext im Influencerin-Profil fehlt."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None:
            return "Kanalidentität gehört nicht zu dieser Kundenakte."
        adapter = self._adapter(ident["platform"])
        if adapter is None or adapter.state != "READY":
            return f"{ident['platform']} ist nicht verbunden."
        if reason := self._send_check(ident["platform"], ident["platform_conversation_id"]):
            return reason
        message_id = self.store.queue_ai_notice(
            msg.customer_id, msg.identity_id, figure["ai_notice"].strip()
        )
        call.entity = f"message:{message_id}"
        adapter.wake.set()
        self._message_changed(message_id)
        return ""

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

    def _wallet_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_WALLET, self._wallet_state())

    def _payments_changed(self) -> None:
        """Eingang neu/geändert; eine automatische Zuordnung ändert auch Auftrag und Verlauf."""
        self.hub.push_events(spb.TOPIC_PAYMENT_UPDATED)
        self._wallet_changed()
        self._orders_changed()
        self._message_changed(0)

    # ------------------------------------------------------------ Kundenauftrag (C5/C5a)

    def _adapter(self, platform: str):
        return {"telegram": self.telegram, "instagram": self.instagram}.get(platform)

    def _send_check(self, platform: str, partner: str, *, human_agent: bool = False) -> str:
        """Kanalgrenzen vor dem Einreihen (Instagram: 24-h-Fenster); leer = erlaubt."""
        if platform == "instagram" and self.instagram:
            return self.instagram.send_check(partner, human_agent=human_agent)
        return "Human-Agent gibt es nur bei Instagram." if human_agent else ""

    def _offer_amounts(self, price_cents: int) -> dict[str, tuple[str, str, float, int]]:
        """Je eingerichtetem Zahlungsweg ein noch nie vergebener, exakter Betrag zum aktuellen Kurs
        (V0 §8.5 Punkte 2–3): BTC in Satoshi aufgerundet plus eindeutige Endung, Stablecoins auf
        Cent aufgerundet plus eindeutige vierte Nachkommastelle."""
        w = self.wallet
        if w is None:
            raise StoreError("Keine Zahlungswege eingerichtet (Abschnitt [wallet] in config.toml).")
        fresh_ms = int(w.w.poll_s * 3 * 1000)
        if not w.rate_ms or int(time.time() * 1000) - w.rate_ms > fresh_ms:
            raise StoreError("Kein aktueller Kurs – Angebot gerade nicht möglich.")
        eur = Decimal(price_cents) / 100
        ways: list[
            tuple[str, str, float, Decimal, Decimal]
        ] = []  # Weg, Adresse, Kurs, Basis, Schritt
        if w.w.btc_address and (rate := w.rates.get(w.w.btc_price_id)):
            sats = (eur / Decimal(str(rate)) * SATOSHI).to_integral_value(ROUND_CEILING)
            ways.append(("btc", w.w.btc_address, rate, sats / SATOSHI, 1 / SATOSHI))
        for token in w.w.tokens if w.w.bsc_address else []:
            method = token.symbol.lower()
            if method in OFFER_METHODS and (rate := w.rates.get(token.price_id)):
                cents = (eur / Decimal(str(rate)) * 100).to_integral_value(ROUND_CEILING)
                ways.append((method, w.w.bsc_address, rate, cents / 100, Decimal("0.0001")))
        if not ways:
            raise StoreError("Kein Zahlungsweg mit Adresse und Kurs eingerichtet.")
        out = {}
        for method, address, rate, base, step in ways:
            for k in range(1, UNIQUE_STEPS + 1):
                amount = decimal_text(base + k * step)
                if not self.store.amount_taken(method, amount):
                    out[method] = (amount, address, rate, w.rate_ms)
                    break
            else:
                raise StoreError(f"{method.upper()}: kein freier eindeutiger Betrag.")
        return out

    def _offer_text(self, order, product: str, hd: bool, price_cents: int, amounts, expires,
                    note: str) -> str:  # fmt: skip
        """Nachricht an den Kunden: Betrag und Zahlungswege (Tatsachen, kein Persona-Text)."""
        until = expires.astimezone().strftime("%d.%m.%Y, %H:%M Uhr")
        lines = [note.strip(), ""] if note.strip() else []
        lines.append(
            f"Angebot {order.order_no}: {product}{' + HD' if hd else ''} · {_eur(price_cents)}"
        )
        lines.append(f"Bitte genau diesen Betrag senden, gültig bis {until}:")
        for method, (amount, address, _rate, _ms) in amounts.items():
            if method == "btc":
                lines.append(f"• Bitcoin: {amount} BTC an {address}")
            else:
                lines.append(f"• {method.upper()} (BNB Smart Chain, BEP-20): {amount} an {address}")
        return "\n".join(lines)

    async def _create_offer(self, msg: commands_pb2.CreateOffer, call: _Call) -> str:
        """Angebot aus der Preisliste (Befehl 46, V0 §8.4 Punkt 3)."""
        call.entity = f"customer:{msg.customer_id}"
        summary = self.store.customers_overview(msg.customer_id)
        if not summary or summary[0]["kind"] == "internal":
            return "Angebote nur an Kundenakten."
        if summary[0]["age_mark"] != "self_declared_adult":
            return "Angebot nur bei Altersangabe ≥ 18 (Selbstauskunft) in der Akte."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None or ident["conversation_id"] != msg.conversation_id:
            return "Kanal passt nicht zu dieser Kundenakte."
        if ident["ai_notice_status"] != "sent":
            return "Erst den KI-Hinweis über diesen Kanal senden (Regel 12 b)."
        adapter = self._adapter(ident["platform"])
        if adapter is None or adapter.state != "READY":
            return f"{ident['platform']} ist nicht verbunden."
        figure = next((f for f in self.store.influencers() if f["id"] == msg.influencer_id), None)
        if figure is None:
            return "Influencerin-Profil unbekannt."
        if msg.position >= len(figure["prices"]):
            return "Position der Preisliste unbekannt."
        item = figure["prices"][msg.position]
        price = item["price_cents"] + (item["hd_surcharge_cents"] if msg.hd else 0)
        assert self.cfg.wallet is not None  # sonst lehnt _offer_amounts ab
        amounts = self._offer_amounts(price)
        expires = datetime.now(UTC) + timedelta(minutes=self.cfg.wallet.offer_valid_min)
        with self.store.tx():
            order = self.store.create_offer(
                msg.customer_id,
                msg.conversation_id,
                item["product"],
                msg.hd,
                price,
                expires.isoformat(timespec="milliseconds"),
                amounts,
            )
            text = self._offer_text(
                order, item["product"], msg.hd, price, amounts, expires, msg.note
            )
            self.store.queue_outbound(
                msg.customer_id,
                msg.conversation_id,
                text,
                revision=msg.revision,
                request_id=call.request_id,
            )
            ways = " · ".join(f"{m.upper()} {a[0]}" for m, a in amounts.items())
            self.store.add_system_card(
                msg.conversation_id,
                f"ANGEBOT · {item['product']}{' + HD' if msg.hd else ''} · {_eur(price)} · {ways}",
                order_id=order.id,
            )
        call.entity = f"order:{order.order_no}"
        adapter.wake.set()
        self._message_changed(0)
        self._wallet_changed()
        return ""

    def _order_result(self, order) -> dict | None:
        """Ergebnis eines Auftrags in Prüfung: Medium der letzten fertigen Stufe."""
        stages = self.store.stages(order.id)
        last = stages[-1] if stages else None
        if last is None or last.status != "done" or not last.selected_media_id:
            return None
        media = self.store.media_by_id(last.selected_media_id)
        return media

    def _delivery_copy(self, order, master: Path) -> Path:
        """Gekennzeichnete Zustellkopie (Regel 12 d) im Ordner sent des Auftrags."""
        copy = self.store.order_dir(order) / "sent" / f"{order.order_no}{master.suffix.lower()}"
        aimeta.mark(master, copy)
        return copy

    def _queue_delivery(self, order, delivery_id: int, copy: Path) -> int:
        offer = self.store.offer(order.id)
        assert offer is not None
        conv = offer["conversation_id"]
        rel = copy.relative_to(self.cfg.local).as_posix()
        attachment = {
            "kind": "document",
            "path": rel,
            "status": "saved",
            "sha256": sha256_file(copy),
            "size": copy.stat().st_size,
            "mime": mimetypes.guess_type(copy.name)[0] or "",
        }
        return self.store.queue_outbound(
            order.customer_id,
            conv,
            "",
            revision=self.store.conversation_revision(conv),
            attachments=[attachment],
            delivery_id=delivery_id,
        )

    def _send_ready(self, order) -> str:
        offer = self.store.offer(order.id)
        if offer is None:
            return "Auftrag ohne Angebot – kein Zustellkanal."
        conv = self.store.conversation_platform(offer["conversation_id"])
        adapter = self._adapter(conv)
        if adapter is None or adapter.state != "READY":
            return f"{conv} ist nicht verbunden."
        return ""

    async def _approve_artifact(self, msg: commands_pb2.ApproveArtifact, call: _Call) -> str:
        """„Freigeben & senden“ (Befehl 34, V0 §8.4 Punkte 8–9): Freigabe und Zustellung hinter
        approval.py in einer Transaktion; Versand über den Postausgang."""
        call.entity = f"order:{msg.order_no}"
        order = self.store.order(msg.order_no)
        if order.source != "customer" or order.status != "review":
            return f"{msg.order_no} wartet nicht auf die Freigabe ({order.status})."
        if not msg.not_explicit:
            return "Bitte bestätigen: das Ergebnis ist nicht explizit."
        result = self._order_result(order)
        if result is None or result["id"] != msg.media_id:
            return "Freigeben lässt sich nur das fertige Ergebnis dieses Auftrags."
        if result["content_tier"] != "standard":
            return "Inhaltsstufe nicht standard – an Kunden nicht zustellbar (Regel 13)."
        if reason := self._send_ready(order):
            return reason
        src = self.cfg.local / result["path"]
        master = (
            self.store.order_dir(order) / "work" / f"{order.order_no}_ergebnis{src.suffix.lower()}"
        )
        await asyncio.to_thread(_place_copy, src, master, result["sha256"])
        copy = await asyncio.to_thread(self._delivery_copy, order, master)
        with self.store.tx():
            art = self.store.add_artifact(order.order_no, "master", master, job_id=result["job_id"])
            self.store.record_approval(order.order_no, art.id, "approved", "Betreiber")
            delivery = approval.prepare_delivery(
                self.store, order.order_no, art.id, order.customer_no
            )
            message_id = self._queue_delivery(order, delivery, copy)
            self._card(order, f"FREIGEGEBEN · {order.order_no} · Zustellung im Postausgang")
        call.entity = f"message:{message_id}"
        self._wake(order)
        self._orders_changed()
        self._message_changed(message_id)
        return ""

    async def _retry_delivery(self, msg: commands_pb2.RetryDelivery, call: _Call) -> str:
        """Erneut senden (Befehl 47) – nur nach endgültig fehlgeschlagener Zustellung."""
        call.entity = f"order:{msg.order_no}"
        order = self.store.order(msg.order_no)
        deliveries = self.store.deliveries(order.id)
        if order.status != "approved" or not deliveries or deliveries[-1]["status"] != "failed":
            return "Erneut senden nur nach endgültig fehlgeschlagener Zustellung."
        if reason := self._send_ready(order):
            return reason
        last = deliveries[-1]
        master = self.cfg.local / self.store.artifact(last["artifact_id"]).path
        copy = await asyncio.to_thread(self._delivery_copy, order, master)
        with self.store.tx():
            delivery = approval.prepare_delivery(
                self.store, order.order_no, last["artifact_id"], order.customer_no,
                attempt=len(deliveries),
            )  # fmt: skip
            message_id = self._queue_delivery(order, delivery, copy)
            self._card(order, f"ERNEUT GESENDET · {order.order_no} · Zustellung im Postausgang")
        call.entity = f"message:{message_id}"
        self._wake(order)
        self._orders_changed()
        self._message_changed(message_id)
        return ""

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

    def _delivery_gate(self, item: dict) -> str:
        """Letzte Prüfung im Versandmoment (Postausgang): Gate frisch gegen Datenbank und Datei,
        Zustellkopie unverändert und gekennzeichnet. Leer = senden."""
        delivery = self.store.delivery(item["delivery_id"])
        if delivery is None or delivery["status"] != "pending":
            return "Zustellung ist nicht mehr offen."
        gate = approval.check_gate(
            self.store, delivery["order_no"], delivery["artifact_id"], delivery["customer_no"]
        )
        if not gate.ok:
            return "Zustellung gesperrt: " + "; ".join(gate.reasons)
        for att in item["attachments"]:
            path = self.cfg.local / att["path"]
            if not path.is_file() or sha256_file(path) != att.get("sha256"):
                return "Zustellkopie fehlt oder wurde verändert."
            if not aimeta.is_marked(path):
                return "Zustellkopie ohne KI-Kennzeichnung."
        return ""

    def _delivery_update(self, message_id: int) -> None:
        """Versandausgang einer Zustellnachricht festschreiben (Karte VERSENDET bzw. Fehler)."""
        delivery = self.store.delivery_by_message(message_id)
        if delivery is None or delivery["status"] != "pending":
            return
        msg = self.store.message(message_id)
        order = self.store.order_by_id(delivery["order_id"])
        if msg["status"] == "sent":
            approval.confirm_sent(self.store, delivery["id"], msg["platform_message_id"] or "")
            self._card(order, f"VERSENDET · {order.order_no}")
        elif msg["status"] == "failed":
            if self.store.fail_delivery(delivery["id"], msg["error"] or ""):
                self._card(
                    order, f"ZUSTELLUNG FEHLGESCHLAGEN · {order.order_no} · {msg['error'] or ''}"
                )
        else:
            return
        self._orders_changed()

    def _settle_deliveries(self) -> None:
        """Nach einem Neustart: gesendete Zustellnachricht, deren Bestätigung fehlt."""
        for delivery_id, external in self.store.pending_sent_deliveries():
            try:
                approval.confirm_sent(self.store, delivery_id, external)
            except StoreError as exc:
                log.error("Zustellung %s: %s", delivery_id, exc)

    async def _payment_assign(self, msg: commands_pb2.PaymentAssign, call: _Call) -> str:
        """Nicht zugeordneten Eingang einem offenen Angebot zuordnen (Befehl 41)."""
        call.entity = f"payment:{msg.payment_id}"
        self.store.assign_inflow(msg.payment_id, msg.order_no, "Betreiber")
        self._payments_changed()
        return ""

    async def _gift_card_confirm(self, msg: commands_pb2.GiftCardConfirm, call: _Call) -> str:
        """Amazon-Gutschein entscheiden (Befehl 42): eingelöster Betrag oder abgelehnt."""
        call.entity = f"voucher:{msg.voucher_id}"
        if msg.reject:
            self.store.reject_voucher(msg.voucher_id)
        elif msg.amount_cents <= 0:
            return "Eingelösten Betrag angeben."
        else:
            self.store.redeem_voucher(msg.voucher_id, msg.amount_cents)
        self._payments_changed()
        return ""

    def read_payments(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.payment_events(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                wallet_pb2.PaymentUpdated(
                    payment=_payment(self.store.payment(r["payment_id"]))
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def _channels_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_CHANNELS, self._channels())

    def _message_changed(self, message_id: int) -> None:
        if message_id:
            try:
                self._delivery_update(message_id)
            except StoreError as exc:  # Gate beim Festschreiben gesperrt: bleibt offen, sichtbar
                log.error("Zustellung zu Nachricht %s: %s", message_id, exc)
        self.hub.push_events(spb.TOPIC_CONVERSATION_EVENT)
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)

    async def _on_inbound(self, inbound) -> None:
        """Neue Nachricht gespeichert: Cockpit per Push aktualisieren; Nachrichten des Default-
        Kontakts gehen vor jeder Kundenverarbeitung durch die Kloner-Weiche (V0 §8)."""
        self._message_changed(inbound.message_id or 0)
        self._wallet_changed()  # erkannter Gutscheincode erscheint im Reiter Wallet
        if inbound.customer.kind == "internal" and inbound.message_id:
            try:
                await self._cloner(inbound)
            except (pipeline.PipelineError, comfy.ComfyError, StoreError) as exc:
                self.store.add_system_card(inbound.conversation_id, f"Auftrag nicht möglich: {exc}")
                self._message_changed(0)

    def _reply_internal(self, conversation_id: int, text: str, files: list[str] = ()) -> None:
        """Rückfrage bzw. Ergebnis an den Default-Nutzer in denselben Chat (Postausgang)."""
        default = self.store.default_contact()
        attachments = []
        for rel in files:
            src = self.cfg.local / rel
            copy = self.cfg.local / "channels" / "sent" / f"{src.stem}_ki{src.suffix.lower()}"
            try:
                if not copy.exists():
                    aimeta.mark(src, copy)
            except (aimeta.AiMetaError, OSError) as exc:
                text += f"\n{src.name}: nicht gesendet ({exc})"
                continue
            attachments.append(
                {"kind": "document", "path": copy.relative_to(self.cfg.local).as_posix(),
                 "status": "saved", "sha256": sha256_file(copy), "size": copy.stat().st_size,
                 "mime": mimetypes.guess_type(copy.name)[0] or ""}
            )  # fmt: skip
        message_id = self.store.queue_outbound(
            default["customer_id"],
            conversation_id,
            text,
            revision=self.store.conversation_revision(conversation_id),
            attachments=attachments,
        )
        adapter = self._adapter(self.store.conversation_platform(conversation_id))
        if adapter is not None:
            adapter.wake.set()
        self._message_changed(message_id)

    async def _cloner(self, inbound) -> None:
        default = self.store.default_contact()
        if not default["process_commands"]:
            return  # nur anzeigen
        msg = self.store.message(inbound.message_id)
        parsed = cloner.parse(msg["text"])
        if parsed is None:
            if msg["text"].strip():  # freie Anweisung: KI-Deutung folgt mit B5
                self._reply_internal(inbound.conversation_id, cloner.ASK_COMMAND)
            return
        command, wish = parsed
        plan = self._cloner_plan(msg, default, command)
        if isinstance(plan, str):
            if plan == cloner.ASK_REFERENCE:
                self._reply_internal(inbound.conversation_id, plan)
            else:
                self.store.add_system_card(
                    inbound.conversation_id, cloner.card(command, msg["platform"], plan)
                )
                self._message_changed(0)
            return
        if not default["auto_orders"]:
            self.store.add_system_card(
                inbound.conversation_id,
                cloner.card(command, msg["platform"], f"{wish or '–'} · wartet auf Start"),
                origin_message_id=inbound.message_id,
            )
            self._message_changed(0)
            return
        order_no = await self._cloner_order(msg, command, wish, *plan)
        self.store.add_system_card(
            inbound.conversation_id,
            cloner.card(command, msg["platform"], self._cloner_detail(order_no, plan[0], wish)),
            order_id=self.store.order(order_no).id,
        )
        self._message_changed(0)

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

    def _cloner_plan(self, msg: dict, default: dict, command: str) -> tuple[str, list[dict]] | str:
        """Workflow des Default-Kontakts für den Befehl (``animate``: Video-Workflow, sonst
        Medien-Workflow) und Referenzen (angehängt oder beantwortete Nachricht); bei fehlenden
        Voraussetzungen der Grund."""
        refs = [a for a in msg["attachments"] if a.get("status") == "saved"]
        if not refs and msg["reply_to_platform_id"]:
            replied = self.store.message_by_platform_id(
                msg["conversation_id"], msg["reply_to_platform_id"]
            )
            refs = [a for a in (replied or {}).get("attachments", []) if a.get("status") == "saved"]
        video = command == "animate"
        key = default["video_workflow" if video else "media_workflow"]
        if not key or key not in self.manifest.workflows:
            if video:
                return "Kein Video-Workflow (animate) im Default-Kontakt gewählt."
            return "Kein Medien-Workflow im Default-Kontakt gewählt."
        wf = self.manifest.workflows[key]
        if "image" in wf.params and wf.params["image"].upload and not refs:
            return cloner.ASK_REFERENCE
        return key, refs

    def _cloner_detail(self, order_no: str, key: str, wish: str) -> str:
        return f"{order_no} · {self.manifest.workflows[key].title} · {wish or '–'}"

    async def _cloner_order(
        self, msg: dict, command: str, wish: str, key: str, refs: list[dict]
    ) -> str:
        """Kloner-Auftrag (Quelle ``cloner``) mit Kandidaten anlegen und einreihen."""
        wf = self.manifest.workflows[key]
        takes_image = "image" in wf.params and wf.params["image"].upload
        inputs = {}
        if takes_image:
            ref = self.cfg.local / refs[0]["path"]
            inputs["image"] = await asyncio.to_thread(
                pipeline.store_input, self.cfg, ref.read_bytes(), ref.name
            )
            # Vorlagen kommen auch aus dem Kloner-Eingang (FRONT, C1)
            await self._register_reference(inputs["image"], f"{msg['platform']}:{msg['id']}")
        values = {"prompt": wish} if wish and "prompt" in wf.params else {}
        order_no, jobs = pipeline.create_order(
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
        self.store.link_order(msg["id"], self.store.order(order_no).id)
        log.info(
            "Kloner: %s %s → %s (%d Kandidaten)", command, msg["platform"], order_no, len(jobs)
        )
        self._enqueue(jobs)
        self._orders_changed()
        return order_no

    async def _channel_login(self, msg: commands_pb2.ChannelAccountLogin, call: _Call) -> str:
        """Anmeldeschritt (Befehl 39); der Wert geht nur an TDLib (V0 §6.1 Punkt 2)."""
        call.entity = f"channel:{msg.platform}"
        if msg.platform == "instagram":
            return "Instagram meldet sich über den Link „Mit Instagram anmelden“ an."
        if msg.platform != "telegram" or self.telegram is None:
            return f"{msg.platform or 'Kanal'}: Kontoanmeldung nicht eingerichtet."
        return await self.telegram.login_step(msg.step, msg.value)

    async def _channel_update(self, msg: commands_pb2.ChannelAccountUpdate, call: _Call) -> str:
        """Automatik freigeben/sperren oder abmelden (Befehl 40)."""
        call.entity = f"channel:{msg.platform}"
        adapter = self._adapter(msg.platform)
        if adapter is None:
            return f"{msg.platform or 'Kanal'}: Konto nicht eingerichtet."
        if msg.action == "logout":
            return await adapter.logout()
        if msg.action in ("enable_automation", "disable_automation"):
            return adapter.set_automation(msg.action == "enable_automation")
        return "Unbekannte Aktion."

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
        self.store.start_card(
            card["id"],
            self.store.order(order_no).id,
            cloner.card(command, origin["platform"], self._cloner_detail(order_no, plan[0], wish)),
        )
        self._message_changed(card["id"])
        return ""

    def _cloner_delivery(self, order_id: int, selected: int | None = None) -> None:
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
            self._reply_internal(conv, label, [path])

    def _default_identity_account(self, platform: str) -> str:
        if platform == "telegram":
            if not self.telegram or not self.telegram.account:
                raise pipeline.PipelineError("Claras Telegram-Konto ist noch nicht angemeldet.")
            return self.telegram.account
        if platform == "instagram":
            if not self.instagram or not self.instagram.account:
                raise pipeline.PipelineError("Claras Instagram-Konto ist noch nicht angemeldet.")
            return self.instagram.account
        raise pipeline.PipelineError(f"{platform} ist noch nicht eingerichtet.")

    async def _mark_read(self, msg: commands_pb2.MarkRead, call: _Call) -> str:
        call.entity = f"customer:{msg.customer_id}"
        self.store.customer_by_id(msg.customer_id)
        if self.store.mark_read(msg.customer_id, msg.up_to_item):
            self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""

    async def _send_reply(self, msg: commands_pb2.SendReply, call: _Call) -> str:
        """Manuelle Textantwort nur an die gewählte, verifizierte Konversation dieses Kunden
        (F4): Plattform, Identität und Konversation müssen zusammenpassen; Revision = CAS."""
        call.entity = f"customer:{msg.customer_id}"
        if not msg.text.strip():
            return "Leere Antwort."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None or ident["platform"] != msg.platform or not msg.platform:
            return "Kanal passt nicht zu dieser Kundenakte."
        if ident["conversation_id"] != msg.conversation_id:
            return "Konversation passt nicht zu diesem Kanal."
        adapter = self._adapter(msg.platform)
        if adapter is None or adapter.state != "READY":
            return f"{msg.platform} ist nicht verbunden."
        partner = ident["platform_conversation_id"]
        if reason := self._send_check(msg.platform, partner, human_agent=msg.human_agent):
            return reason
        message_id = self.store.queue_outbound(
            msg.customer_id,
            msg.conversation_id,
            msg.text.strip(),
            revision=msg.revision,
            request_id=call.request_id,
        )
        call.entity = f"message:{message_id}"
        if msg.human_agent and self.instagram and not self.instagram.window_open(partner):
            self.instagram.mark_human_agent(message_id)
        adapter.wake.set()
        self._message_changed(message_id)
        return ""

    async def _default_contact_update(
        self, msg: commands_pb2.DefaultContactUpdate, call: _Call
    ) -> str:
        current = self.store.default_contact()
        call.entity = f"customer:{current['customer_id']}"
        if msg.approval_mode not in ("direct", "cockpit", "cockpit_only"):
            return "Freigabemodus unbekannt."
        if msg.influencer and msg.influencer not in {
            str(i["id"]) for i in self.store.influencers()
        }:
            return "Influencerin: unbekanntes Profil."
        for key, kind in ((msg.media_workflow, "image"), (msg.video_workflow, "video")):
            if reason := self._cloner_workflow_reason(key, kind):
                return reason
        senders = {}
        if msg.telegram_sender_id.strip() != current["sender_ids"].get("telegram", ""):
            senders[("telegram", self._default_identity_account("telegram"))] = (
                msg.telegram_sender_id.strip()
            )
        if msg.instagram_sender_id.strip() != current["sender_ids"].get("instagram", ""):
            senders[("instagram", self._default_identity_account("instagram"))] = (
                msg.instagram_sender_id.strip()
            )
        self.store.update_default_contact(
            msg.revision,
            {
                "process_commands": int(msg.process_commands),
                "auto_orders": int(msg.auto_orders),
                "approval_mode": msg.approval_mode,
                "influencer": msg.influencer.strip(),
                "media_workflow": msg.media_workflow,
                "video_workflow": msg.video_workflow,
            },
            senders,
        )
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""

    def read_customers(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.customer_events(after, limit)
        out = []
        for r in rows:
            summary = self.store.customers_overview(r["customer_id"])
            customer = (
                _customer_summary(summary[0])
                if summary
                else channel_pb2.CustomerSummary(customer_id=r["customer_id"])
            )  # entfernte Akte: nur die ID
            out.append(
                (
                    r["cursor"],
                    _unix_ms(r["committed_at"]),
                    channel_pb2.CustomerUpdated(customer=customer).SerializeToString(),
                )
            )
        return out, gap

    def read_conversation(
        self, after: int, limit: int
    ) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.message_events(after, limit)
        out = []
        for r in rows:
            item = self.store.conversation_item(r["message_id"])
            if item is None:
                continue
            out.append(
                (
                    r["cursor"],
                    _unix_ms(r["committed_at"]),
                    channel_pb2.ConversationEvent(
                        item=_conversation_item(item, self.store)
                    ).SerializeToString(),
                )
            )
        return out, gap

    def _orders_active(self) -> bytes:
        """STATE orders.active: Aufträge in Produktion mit Stufen und deren Jobs/Kandidaten."""
        prod = self.cfg.production
        msg = order_pb2.OrdersActive(
            version=self.store.domain_version("orders"),
            candidates_default=prod.candidates_default,
            candidates_max=prod.candidates_max,
        )
        for order in self.store.active_orders():
            _fill_order(msg.orders.add(), self.store, order)
        for order in self.store.active_orders("paid"):
            _fill_order(msg.awaiting_production.add(), self.store, order)
        return msg.SerializeToString()

    def read_orders(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.order_events(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                order_pb2.OrderUpdated(
                    order_no=r["order_no"],
                    event=r["event"],
                    status=str(r["data"].get("status") or r["data"].get("new") or r["status"]),
                    seq=int(r["data"].get("seq") or 0),
                    kind=str(r["data"].get("kind") or ""),
                    detail=str(r["data"].get("detail") or ""),
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    async def _set_enabled(self, msg: commands_pb2.SetWorkflowEnabled, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        self._workflow(msg.workflow)
        self.manifest = await asyncio.to_thread(
            models.set_workflow_enabled, self.cfg.root, msg.workflow, msg.enabled
        )
        log.info("Workflow %s %s", msg.workflow, "aktiviert" if msg.enabled else "deaktiviert")
        return ""

    async def _open(self, msg: commands_pb2.OpenWorkflow, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        lane = self._lane_of(self._workflow(msg.workflow))
        if lane is None or not lane.status.get("health"):
            return "Die ausführende ComfyUI-Instanz läuft nicht."
        await asyncio.to_thread(comfy.install_editor_copy, self.cfg, self.manifest, msg.workflow)
        return ""

    async def _adopt(self, msg: commands_pb2.AdoptWorkflow, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        wf = self._workflow(msg.workflow)
        lane = self._lane_of(wf)
        if lane is None or not lane.status.get("health"):
            return "Die ausführende ComfyUI-Instanz läuft nicht (Node-Definitionen fehlen)."

        def adopt() -> models.Manifest:
            info = comfy.ComfyClient(lane.inst.url, timeout=120).object_info()
            edited = json.loads(comfy.editor_file(lane.inst, wf.key).read_text(encoding="utf-8"))
            registry_ui = json.loads((self.manifest.root / "workflows" / wf.ui).read_text())
            api = comfy.ui_to_api(edited, info)
            uploads = {(p.node, p.input) for p in wf.params.values() if p.upload}
            if problems := comfy.check_graph(api, info, uploads):
                raise comfy.ComfyError("; ".join(problems))
            changed = api != comfy.ui_to_api(registry_ui, info)
            man = models.replace_workflow_graph(
                self.cfg.root, wf.key, edited, api, reset_status=changed
            )
            comfy.install_editor_copy(self.cfg, man, wf.key, replace=True)
            return man

        self.manifest = await asyncio.to_thread(adopt)
        log.info("Workflow %s aus dem Editor übernommen", wf.key)
        return ""

    async def _create(self, msg: commands_pb2.CreateWorkflow, call: _Call) -> str:
        self._workflow(msg.source)
        self.manifest, key = await asyncio.to_thread(
            models.create_workflow, self.cfg.root, msg.source, msg.title
        )
        call.entity = f"workflow:{key}"
        if self._lane_of(self.manifest.workflows[key]) is not None:
            await asyncio.to_thread(comfy.install_editor_copy, self.cfg, self.manifest, key)
        log.info("Workflow %s als Kopie von %s angelegt", key, msg.source)
        return ""

    async def _cancel(self, msg: commands_pb2.CancelJob, call: _Call) -> str:
        call.entity = f"job:{msg.job_id}"
        job = self.store.job(msg.job_id)
        if job["status"] == "queued":
            self.store.set_job_status(
                msg.job_id, "failed", error="Aus der Warteschlange entfernt.", cancelled=True
            )
            log.info("Job %s aus der Warteschlange entfernt", msg.job_id)
            pipeline.advance_order(self.store, msg.job_id)
            self._orders_changed()
            return ""
        if job["status"] != "running":
            return "Auftrag ist bereits abgeschlossen."
        lane = self._lane_of_job(msg.job_id)
        prompt = next((p for j, _, p in lane.queue if j == msg.job_id), "")
        if not prompt:
            return "Auftrag startet gerade – gleich erneut versuchen."
        self._cancelled.add(msg.job_id)
        client = comfy.ComfyClient(lane.inst.url, timeout=self.cfg.server.timeout_s)
        await asyncio.to_thread(client.cancel, prompt)
        log.info("Job %s (prompt %s) abgebrochen", msg.job_id, prompt)
        return ""

    async def _pause(self, msg: commands_pb2.PauseQueue, call: _Call) -> str:
        name = msg.instance or "media"
        call.entity = f"comfyui:{name}"
        lane = self.lanes.get(name)
        if lane is None:
            return f"ComfyUI-Instanz '{name}' ist nicht eingerichtet."
        if msg.paused:
            lane.resume.clear()
        else:
            lane.resume.set()
        log.info("Warteschlange %s %s", name, "angehalten" if msg.paused else "fortgesetzt")
        return ""

    async def _delete(self, msg: commands_pb2.DeleteWorkflow, call: _Call) -> str:
        call.entity = f"workflow:{msg.workflow}"
        wf = self._workflow(msg.workflow)
        active = comfy_pb2.JobsActive.FromString(self._jobs_active())
        if any(job.workflow == wf.key for job in active.jobs):
            return "Workflow hat laufende oder wartende Aufträge."
        lane = self._lane_of(wf)
        self.manifest = await asyncio.to_thread(models.delete_workflow, self.cfg.root, wf.key)
        if lane is not None:
            await asyncio.to_thread(comfy.remove_editor_copy, lane.inst, wf.key)
        log.info("Workflow %s gelöscht (Registrierung, UI/API, Editor-Kopie)", wf.key)
        return ""

    async def _delete_media(self, msg: commands_pb2.DeleteMedia, call: _Call) -> str:
        if not msg.media_ids:
            return "Keine Datei gewählt."
        call.entity = "media:" + ",".join(str(i) for i in msg.media_ids[:20])
        removed = await asyncio.to_thread(pipeline.delete_media, self.cfg, list(msg.media_ids))
        # Freigewordene Pfade neu prüfen: ComfyUI vergibt gelöschte Dateinamen erneut.
        self._seen_media.difference_update(removed)
        self.hub.push_events(spb.TOPIC_MEDIA_REMOVED)
        log.info("Galerie: %d Datei(en) gelöscht", len(removed))
        return ""

    def _comfy_command(self, which: str, name: str, call: _Call) -> str:
        call.entity = f"comfyui:{name}"
        lane = self.lanes.get(name)
        if lane is None:
            return f"ComfyUI-Instanz '{name}' ist nicht eingerichtet."
        if lane.busy:
            return "Ein Befehl für diese ComfyUI-Instanz läuft bereits"
        if lane.status.get("state") == "foreign":
            return "Port belegt durch eine nicht von Darkfluenzer gestartete Instanz"
        if which == "comfy_stop" and (lane.running_job or lane.queue):
            return "Instanz arbeitet – erst nach dem laufenden Auftrag stoppen."
        action = "start" if which == "comfy_start" else "stop"
        lane.busy, lane.error = action, ""
        self.hub.set_state(spb.TOPIC_COMFY_INSTANCES, self._instances())
        task = asyncio.create_task(self._run(lane, action, call.request_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ""

    async def _run(self, lane: _Lane, action: str, request_id: str) -> None:
        fn = runtime.start if action == "start" else runtime.stop
        try:
            await asyncio.to_thread(fn, self.cfg, lane.inst.name)
        except runtime.RuntimeFailure as exc:
            log.error("ComfyUI %s %s fehlgeschlagen: %s", lane.inst.name, action, exc)
            lane.error = str(exc)
        finally:
            lane.busy = ""
        if action == "stop":
            lane.engine = ""  # gestoppt: keine Modelle mehr geladen
        self.store.finish_command(
            request_id, "failed" if lane.error else "completed", detail=lane.error
        )
        self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
        await self.refresh_comfy()

    def read_media(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.media_events(after, limit)
        return [
            (r["cursor"], _unix_ms(r["committed_at"]), _media_item(r).SerializeToString())
            for r in rows
        ], gap

    def read_references(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.reference_events(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                reference_pb2.ReferenceAdded(
                    reference=_reference_item(self.store.reference(r["reference_id"]))
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_removed(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.media_removed(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                media_pb2.MediaRemoved(media_id=r["media_id"], path=r["path"]).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_receipts(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.receipts(after, limit)
        return [
            (
                r["cursor"],
                _unix_ms(r["committed_at"]),
                commands_pb2.CommandReceipt(
                    request_id=r["request_id"],
                    status=_RECEIPT_STATUS[r["status"]],
                    command=r["command"],
                    entity=r["entity"],
                    detail=r["detail"],
                    version=r["version"],
                ).SerializeToString(),
            )
            for r in rows
        ], gap

    def read_jobs(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.finished_jobs(after, limit)
        indexed = self.store.media_path_by_sha() if rows else {}
        return [(r["id"], _unix_ms(r["created_at"]), _job_completed(r, indexed)) for r in rows], gap


def _unix_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _media_item(row: dict) -> media_pb2.MediaItem:
    """Galerie-Eintrag; Unterschrift: Kundenname (sonst Kundennummer) oder laufende Nummer."""
    if row["artifact_id"]:
        origin = media_pb2.MEDIA_ORIGIN_ORDER
    elif row["job_id"]:
        origin = media_pb2.MEDIA_ORIGIN_RENDER
    elif row["path"].startswith("ComfyUI/"):
        origin = media_pb2.MEDIA_ORIGIN_COMFYUI
    else:
        origin = media_pb2.MEDIA_ORIGIN_EVALUATION
    caption = (
        (row["display_name"] or row["customer_no"] or "")
        if row["order_id"]
        else f"{row['number']:04d}"
    )
    item = media_pb2.MediaItem(
        media_id=row["id"],
        kind=media_pb2.MEDIA_KIND_VIDEO if row["kind"] == "video" else media_pb2.MEDIA_KIND_IMAGE,
        caption=caption,
        path=row["path"],
        size=row["size"],
        sha256=row["sha256"],
        created_unix_ms=_unix_ms(row["created_at"]),
        origin=origin,
        workflow=row["workflow"] or "",
        job_id=row["job_id"] or 0,
        order_no=row["order_no"] or "",
        customer_no=row["customer_no"] or "",
        content_tier=row["content_tier"] or "",
    )
    item.params.update({k: str(v) for k, v in row["params"].items()})
    return item


def _provenance(cockpit: Cockpit, media_id: int) -> media_pb2.MediaProvenance | None:
    """Herkunft eines Mediums aus Job-Journal, Graph-Snapshot und Herkunftsdatei des Laufs."""
    store, man = cockpit.store, cockpit.manifest
    row = store.media_by_id(media_id)
    if row is None:
        return None
    msg = media_pb2.MediaProvenance(
        media_id=media_id, child_media_ids=store.media_children(media_id)
    )
    if not row["job_id"]:
        return msg
    job = store.job(row["job_id"])
    wf = man.workflows.get(job["workflow"])
    msg.job_id = job["id"]
    msg.workflow = job["workflow"]
    msg.workflow_title = wf.title if wf else ""
    msg.engine = job["engine"]
    msg.workflow_sha256 = job["workflow_sha256"] or ""
    msg.prompt_id = job["prompt_id"] or ""
    msg.parent_media_id = job["parent_media_id"] or 0
    msg.params.update({k: str(v) for k, v in job["params"].items()})
    done = next(
        (
            e["data"]
            for e in reversed(store.events("job", job["id"]))
            if e["event"] == "status" and e["data"].get("status") == "done"
        ),
        {},
    )
    msg.duration_s = float(done.get("duration_s") or 0)
    if memory := done.get("memory"):
        msg.memory.CopyFrom(media_pb2.MemoryTrace(**memory_fields(memory)))
    sidecar = pipeline.sidecar_for(cockpit.cfg, row["path"]) or {}
    for param, inp in (sidecar.get("inputs") or {}).items():
        path = Path(inp["file"])
        rel = path.relative_to(cockpit.cfg.local).as_posix() if path.is_absolute() else str(path)
        msg.inputs.add(param=param, path=rel, sha256=inp["sha256"])
    for model in (sidecar.get("provenance") or {}).get("models") or []:
        msg.models.add(
            file=model["file"],
            repo=model["repo"],
            revision=model["revision"],
            sha256=model["sha256"],
        )
    for nid, node in (job["graph"] or {}).items():
        gnode = msg.graph.add(id=nid, class_type=node["class_type"])
        for name, value in node["inputs"].items():
            if not (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)):
                gnode.inputs.add(name=name, value=str(value))
    return msg


def memory_fields(memory: dict) -> dict:
    """Felder des Speicherverlaufs, die MemoryTrace kennt."""
    names = set(media_pb2.MemoryTrace.DESCRIPTOR.fields_by_name)
    return {k: float(v) for k, v in memory.items() if k in names}


def _job_completed(row: dict, indexed: dict[str, str]) -> bytes:
    """Abgeschlossener Job; Ausgaben verweisen auf die indizierte Datei gleichen Inhalts (eine
    bitgleiche Wiederholung zeigt auf das vorhandene Medium), gelöschte entfallen."""
    data = row["data"]
    msg = comfy_pb2.JobCompleted(
        job_id=row["job_id"],
        workflow=row["workflow"],
        engine=row["engine"],
        result=comfy_pb2.JOB_RESULT_DONE
        if data.get("status") == "done"
        else comfy_pb2.JOB_RESULT_CANCELLED
        if data.get("cancelled")
        else comfy_pb2.JOB_RESULT_FAILED,
        error=data.get("error") or "",
        duration_s=float(data.get("duration_s") or 0),
        order_no=row["order_no"] or "",
    )
    for out in data.get("outputs") or []:
        path = indexed.get(out["sha256"])
        if path is None:  # vom Betreiber gelöscht (oder nicht in der Galerie)
            continue
        msg.outputs.add(path=path, sha256=out["sha256"], size=out["size"])
    msg.params.update({k: str(v) for k, v in (row.get("params") or {}).items()})
    return msg.SerializeToString()


# --------------------------------------------------------------------------- Schutz


class _Guard:
    """Host-/Origin-Prüfung und Sitzungen (Cookie + CSRF-Token) des einzigen Betreibers."""

    def __init__(self, cfg: Config) -> None:
        port = cfg.server.port
        self.hosts = {f"{cfg.server.host}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.sessions: OrderedDict[str, str] = OrderedDict()

    def same_origin(self, request: web.Request) -> bool:
        return request.headers.get("Origin") in self.origins

    def csrf_of(self, request: web.Request) -> str | None:
        return self.sessions.get(request.cookies.get(SESSION_COOKIE, ""))

    def open_session(self, request: web.Request) -> tuple[str, str]:
        sid = request.cookies.get(SESSION_COOKIE, "")
        if sid in self.sessions:
            return sid, self.sessions[sid]
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[sid] = csrf
        while len(self.sessions) > MAX_SESSIONS:
            self.sessions.popitem(last=False)
        return sid, csrf


HUB_KEY = web.AppKey("hub", Hub)
COCKPIT_KEY = web.AppKey("cockpit", Cockpit)
GUARD_KEY = web.AppKey("guard", _Guard)


# Tunnel und Reverse-Proxys setzen diese Header; das Cockpit ist nie über einen Tunnel erreichbar,
# auch wenn ein Tunnel den Host auf 127.0.0.1 umschreibt (bugs_v1 BUG-002). Öffentliche Pfade
# gibt es nur in der eigenen App auf server.public_port.
FORWARD_HEADERS = (
    "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-IP",
    "CF-Connecting-IP", "CF-Ray", "Tailscale-Funnel-Request", "Tailscale-User-Login",
    "True-Client-IP", "Via",
)  # fmt: skip


@web.middleware
async def _host_check(request: web.Request, handler):
    if any(h in request.headers for h in FORWARD_HEADERS):
        return web.Response(status=403, text="Das Cockpit ist über einen Tunnel nicht erreichbar")
    if request.host not in request.app[GUARD_KEY].hosts:
        return web.Response(status=403, text="Unbekannter Host")
    return await handler(request)


def _instagram(request: web.Request) -> InstagramAccount:
    ig = request.app[COCKPIT_KEY].instagram
    if ig is None:
        raise web.HTTPNotFound()
    return ig


async def _ig_verify(request: web.Request) -> web.Response:
    status, body = _instagram(request).verify(request.query)
    return web.Response(status=status, text=body)


async def _ig_webhook(request: web.Request) -> web.Response:
    raw = await request.read()  # Signatur über die unveränderten Bytes
    status = await _instagram(request).handle_webhook(
        raw, request.headers.get("X-Hub-Signature-256", "")
    )
    return web.Response(status=status)


async def _ig_oauth(request: web.Request) -> web.Response:
    status, text = await _instagram(request).oauth_callback(request.query)
    return web.Response(status=status, text=text, headers={"Cache-Control": "no-store"})


async def _ig_media(request: web.Request) -> web.StreamResponse:
    """Medienabruf durch Meta: nur mit kurzlebigem signiertem Token, nur Dateien unter local/."""
    ig = _instagram(request)
    rel = request.match_info["path"]
    if not ig.check_media_token(rel, request.query.get("t", "")):
        return web.Response(status=403)
    local = request.app[COCKPIT_KEY].cfg.local.resolve()
    path = (local / rel).resolve()
    if not path.is_relative_to(local) or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-store"})


async def _ig_login(request: web.Request) -> web.Response:
    """Anmeldung im Cockpit: Weiterleitung zur Instagram-Anmeldung (OAuth mit state)."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        url = _instagram(request).authorize_url()
    except InstagramError as exc:
        return web.Response(status=409, text=str(exc))
    raise web.HTTPFound(url)


# --------------------------------------------------------------------------- Routen


async def _healthz(_: web.Request) -> web.Response:
    return web.Response(status=204)


async def _session(request: web.Request) -> web.Response:
    guard = request.app[GUARD_KEY]
    site = request.headers.get("Sec-Fetch-Site", "same-origin")
    if site not in ("same-origin", "none") or (
        "Origin" in request.headers and not guard.same_origin(request)
    ):
        return web.Response(status=403, text="Fremde Herkunft")
    sid, csrf = guard.open_session(request)
    resp = web.Response(status=204, headers={CSRF_HEADER: csrf, "Cache-Control": "no-store"})
    resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Strict", path="/")
    return resp


async def _stream(request: web.Request) -> web.StreamResponse:
    guard = request.app[GUARD_KEY]
    if not guard.same_origin(request):
        return web.Response(status=403, text="Fremde Herkunft")
    if guard.csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    return await request.app[HUB_KEY].serve(request)


async def _command(request: web.Request) -> web.Response:
    guard = request.app[GUARD_KEY]
    if not guard.same_origin(request):
        return web.Response(status=403, text="Fremde Herkunft")
    csrf = guard.csrf_of(request)
    if csrf is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    if not secrets.compare_digest(request.headers.get(CSRF_HEADER, ""), csrf):
        return web.Response(status=403, text="CSRF-Token fehlt oder ist falsch")
    if request.content_type != PROTOBUF:
        return web.Response(status=415, text=f"Nur {PROTOBUF}")
    try:  # ganzer Körper; die Grenze (max_upload_mb) setzt client_max_size durch
        body = await request.read()
    except web.HTTPRequestEntityTooLarge:
        return web.Response(status=413, text="Befehl zu groß")
    try:
        req = commands_pb2.CommandRequest.FromString(body)
        uuid.UUID(req.request_id)
    except (DecodeError, ValueError):
        return web.Response(status=400, text="Ungültiger CommandRequest")

    hashed = commands_pb2.CommandRequest()
    hashed.CopyFrom(req)
    if hashed.WhichOneof("command") == "channel_account_login":
        hashed.channel_account_login.value = ""  # Code/Passwort nie im Befehlsjournal
    payload_sha = hashlib.sha256(hashed.SerializeToString(deterministic=True)).hexdigest()
    answer = await request.app[COCKPIT_KEY].command(req, payload_sha)
    return web.Response(body=answer.SerializeToString(), content_type=PROTOBUF)


def _response(request_id: str, reason: str, entity: str = "") -> commands_pb2.CommandResponse:
    """Sofortige Antwort: ACCEPTED oder REJECTED (mit Grund); nie ein terminales Ergebnis."""
    accepted, rejected = commands_pb2.COMMAND_STATUS_ACCEPTED, commands_pb2.COMMAND_STATUS_REJECTED
    return commands_pb2.CommandResponse(
        request_id=request_id,
        status=rejected if reason else accepted,
        detail=reason,
        entity=entity,
    )


# Nur passive Medien werden im Cockpit angezeigt; HTML, SVG, PDF und alles Unbekannte (z. B.
# Kundenanhänge) gehen als Download mit neutralem Typ hinaus (bugs_v1 BUG-001)
INLINE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".m4v": "video/mp4", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
}  # fmt: skip
MEDIA_CSP = "default-src 'none'; img-src 'self'; media-src 'self'; sandbox"


def _media(local: Path):
    """Erzeugte Bilder/Videos – nur Dateien des Galerie-Index, nur mit gültiger Sitzung.
    Pfade relativ zu local/; Dateien werden nie überschrieben. ``?download=1`` lädt herunter."""

    async def media(request: web.Request) -> web.StreamResponse:
        if request.app[GUARD_KEY].csrf_of(request) is None:
            return web.Response(status=401, text="Keine gültige Sitzung")
        rel = request.match_info["path"]
        store = request.app[COCKPIT_KEY].store
        if store.media_by_path(rel) is None and not store.message_file_known(rel):
            raise web.HTTPNotFound()  # nur Galerie-Index und gesicherte Nachrichtenanhänge
        path = (local / rel).resolve()
        if not path.is_relative_to(local.resolve()) or not path.is_file():
            raise web.HTTPNotFound()
        headers = {
            "Cache-Control": "private, max-age=31536000, immutable",
            # bugs_v1 BUG-001: nie als aktives Dokument unter der Cockpit-Origin
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": MEDIA_CSP,
        }
        inline = INLINE_TYPES.get(path.suffix.lower())
        if inline is None or request.query.get("download") == "1":
            headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        headers["Content-Type"] = inline or "application/octet-stream"
        return web.FileResponse(path, headers=headers)

    return media


async def _media_page(request: web.Request) -> web.Response:
    """Ältere Galerie-Einträge seitenweise (neueste zuerst), Protobuf."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        before = int(request.query.get("before", "0"))
        limit = min(max(int(request.query.get("limit", "48")), 1), 100)
    except ValueError:
        return web.Response(status=400, text="before/limit müssen Zahlen sein")
    rows, more = request.app[COCKPIT_KEY].store.media_page(before, limit)
    page = media_pb2.MediaPage(items=[_media_item(r) for r in rows], more=more)
    return web.Response(body=page.SerializeToString(), content_type=PROTOBUF)


def _payment(row: dict) -> wallet_pb2.Payment:
    return wallet_pb2.Payment(
        payment_id=row["id"],
        method=row["method"],
        asset=row["asset"],
        amount=row["amount"],
        eur=row["eur"] or 0.0,
        rate=row["rate"] or 0.0,
        rate_ms=row["rate_ms"] or 0,
        txid=row["txid"],
        confirmations=row["confirmations"],
        required_confirmations=row["required"],
        status=row["status"],
        order_no=row["order_no"] or "",
        customer_id=row["customer_id"] or 0,
        customer_no=row["customer_no"] or "",
        at_ms=_unix_ms(row["detected_at"]),
        network=row["network"],
    )


async def _payment_page(request: web.Request) -> web.Response:
    """Zahlungseingänge seitenweise (neueste zuerst) mit Filter, Protobuf (FRONT F7.8)."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        before = int(request.query.get("before", "0"))
        limit = min(max(int(request.query.get("limit", "50")), 1), 200)
    except ValueError:
        return web.Response(status=400, text="before/limit müssen Zahlen sein")
    store = request.app[COCKPIT_KEY].store
    try:
        rows, more = store.payment_page(before, limit, request.query.get("filter", "all"))
    except StoreError as exc:
        return web.Response(status=400, text=str(exc))
    page = wallet_pb2.PaymentPage(
        items=[_payment(r) for r in rows], more=more, version=store.domain_version("payments")
    )
    return web.Response(body=page.SerializeToString(), content_type=PROTOBUF)


async def _payment_export(request: web.Request) -> web.Response:
    """Steuer-Monatsliste (V0 §8.5 Punkt 7) als CSV-Datei: Euro-Wert und Kurs je Eingang."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    month = request.match_info["month"]
    if not MONTH.match(month):
        return web.Response(status=400, text="Monat als JJJJ-MM angeben")
    rows = request.app[COCKPIT_KEY].store.payments_of_month(month)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        ["Zeit (UTC)", "Weg", "Netz", "Asset", "Betrag", "Euro-Wert", "Kurs EUR", "Kurszeit (UTC)",
         "Transaktion", "Position", "Bestätigungen", "Status", "Auftrag", "Kunde"]
    )  # fmt: skip
    for r in rows:
        rate_at = (
            datetime.fromtimestamp(r["rate_ms"] / 1000, UTC).isoformat(timespec="seconds")
            if r["rate_ms"]
            else ""
        )
        writer.writerow(
            [r["detected_at"], r["method"], r["network"], r["asset"], r["amount"],
             f"{r['eur']:.2f}" if r["eur"] is not None else "", r["rate"] or "", rate_at,
             r["txid"], r["position"], r["confirmations"], r["status"], r["order_no"] or "",
             r["customer_no"] or ""]
        )  # fmt: skip
    return web.Response(
        body=out.getvalue().encode("utf-8-sig"),
        content_type="text/csv",
        charset="utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="darkfluenzer-zahlungen-{month}.csv"',
            "Cache-Control": "no-store",
        },
    )


async def _wallet_qr(request: web.Request) -> web.Response:
    """QR-Code der öffentlichen Adresse eines Kontos als SVG (Schublade, FRONT F7.8)."""
    import segno

    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    wallet = request.app[COCKPIT_KEY].cfg.wallet
    address = (
        {"btc": wallet.btc_address, "bsc": wallet.bsc_address}.get(request.match_info["key"], "")
        if wallet
        else ""
    )
    if not address:
        raise web.HTTPNotFound()
    svg = segno.make(address, error="m").svg_inline(scale=4, dark="#000", light="#fff")
    return web.Response(text=svg, content_type="image/svg+xml")


def _reference_item(row: dict) -> reference_pb2.ReferenceItem:
    return reference_pb2.ReferenceItem(
        reference_id=row["id"],
        path=row["path"],
        sha256=row["sha256"],
        kind=row["kind"],
        source=row["source"],
        created_ms=_unix_ms(row["created_at"]),
        analysis=row["analysis"],
    )


async def _reference_page(request: web.Request) -> web.Response:
    """Vorlagenbibliothek seitenweise (neueste zuerst), Protobuf."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        before = int(request.query.get("before", "0"))
        limit = min(max(int(request.query.get("limit", "48")), 1), 100)
    except ValueError:
        return web.Response(status=400, text="before/limit müssen Zahlen sein")
    store = request.app[COCKPIT_KEY].store
    rows, more = store.reference_page(before, limit)
    page = reference_pb2.ReferencePage(
        items=[_reference_item(r) for r in rows],
        more=more,
        version=store.domain_version("references"),
    )
    return web.Response(body=page.SerializeToString(), content_type=PROTOBUF)


async def _provenance_route(request: web.Request) -> web.Response:
    """Herkunft eines Mediums (Protobuf, bei Aufruf; abgeleitete Versionen kommen hinzu)."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        media_id = int(request.match_info["media_id"])
    except ValueError:
        return web.Response(status=400, text="media_id muss eine Zahl sein")
    msg = _provenance(request.app[COCKPIT_KEY], media_id)
    if msg is None:
        raise web.HTTPNotFound()
    headers = {"Cache-Control": "no-cache"}  # Kinder-Versionen ändern sich
    return web.Response(body=msg.SerializeToString(), content_type=PROTOBUF, headers=headers)


def _customer_summary(row: dict) -> channel_pb2.CustomerSummary:
    return channel_pb2.CustomerSummary(
        customer_id=row["id"],
        customer_no=row["customer_no"],
        display_name=row["display_name"] or "",
        kind=row["kind"],
        platforms=sorted(filter(None, (row["platforms"] or "").split(","))),
        last_text=row["last_text"] or "",
        last_platform=row["last_platform"] or "",
        last_ms=_unix_ms(row["last_at"]) if row["last_at"] else 0,
        unread=row["unread"] or 0,
        age_mark=row["age_mark"],
        handles=sorted(
            {v for pair in (row["handles"] or "").split("\x1e") for v in pair.split("\x1f") if v}
        ),
    )


def _window(ig: InstagramAccount | None, ident: dict) -> dict:
    """Instagram-Antwortfenster einer Identität (Unix-ms bis wann offen)."""
    if ig is None or ident["platform"] != "instagram" or not ident["platform_conversation_id"]:
        return {}
    now_ms = int(time.time() * 1000)
    partner = ident["platform_conversation_id"]
    left = ig.window_remaining_ms(partner)
    human = ig.window_remaining_ms(partner, human_agent=True)
    return {
        "window_until_ms": now_ms + left if left else 0,
        "human_until_ms": now_ms + human if human else 0,
    }


def _param_text(name: str, value: object) -> str:
    """Job-Parameter für die Anzeige; der Abschnittsplan eines Langvideos als eine Zeile."""
    if name == "video" and isinstance(value, dict):
        frames = value.get("frames") or []
        joined = " + ".join(map(str, frames))
        return f"{len(frames)} Abschnitt(e) · Frames {joined} · {value.get('fps', 0):g} fps"
    return str(value)


def _eur(cents: int) -> str:
    return f"{cents / 100:.2f} €".replace(".", ",")


def _place_copy(src: Path, dst: Path, sha256: str) -> None:
    """Bytegleiche Kopie (Hash geprüft); eine vorhandene gleiche Kopie bleibt."""
    if dst.is_file() and sha256_file(dst) == sha256:
        return
    if sha256_file(src) != sha256:
        raise StoreError(f"{src.name}: Datei weicht vom Galerie-Eintrag ab.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _fill_order(item: order_pb2.ActiveOrder, store: Store, order) -> None:
    """Auftrag mit Stufen, Jobs und Kandidaten (STATE orders.active, Systemkarte)."""
    item.order_no, item.source, item.kind = order.order_no, order.source, order.kind
    item.request, item.status = order.request, order.status
    for st in store.stages(order.id):
        stage = item.stages.add(
            seq=st.seq,
            kind=st.kind,
            status=st.status,
            workflow=st.workflow,
            count=st.count,
            selected_media_id=st.selected_media_id or 0,
            error=st.error or "",
            finish_workflow=str(st.params.get("finish") or ""),
            attempts=st.attempts,
        )
        for j in store.stage_jobs(st.id):
            stage.jobs.add(
                job_id=j["id"],
                seed=int(j["seeds"][0]) if j["seeds"] else 0,
                status=j["status"],
                media_id=j["media_id"] or 0,
                path=j["path"] or "",
                error=j["error"] or "",
                content_tier=j["content_tier"] or "",
            )
        if st.status == "done" and st.selected_media_id:
            media = store.media_by_id(st.selected_media_id)
            item.result_media_id = st.selected_media_id
            item.result_path = media["path"] if media else ""
            item.result_tier = (media["content_tier"] if media else "") or ""
    if order.source != "customer":
        return
    item.customer_id, item.customer_no = order.customer_id or 0, order.customer_no or ""
    offer = store.offer(order.id)
    if offer is not None:
        item.offer.product, item.offer.hd = offer["product"], bool(offer["hd"])
        item.offer.price_cents, item.offer.expires_ms = (
            offer["price_cents"],
            _unix_ms(offer["expires_at"]),
        )
        item.offer.conversation_id = offer["conversation_id"]
        for row in store.offer_amount_rows(order.id):
            network = "bitcoin" if row["method"] == "btc" else "bsc"
            item.offer.amounts.add(
                method=row["method"],
                asset=row["method"].upper(),
                amount=row["amount"],
                address=row["address"],
                network=network,
                rate=row["rate"],
                rate_ms=row["rate_ms"],
            )
    for d in store.deliveries(order.id):
        status = d["status"]
        if status == "pending" and d["message_status"] == "unknown":
            status = "unknown"
        atts = json.loads(d["attachments"] or "[]")
        item.deliveries.add(
            delivery_id=d["id"],
            status=status,
            message_id=d["message_id"] or 0,
            error=d["message_error"] or "",
            at_ms=_unix_ms(d["sent_at"] or d["created_at"]),
            path=atts[0]["path"] if atts else "",
        )


def _conversation_item(row: dict, store: Store) -> channel_pb2.ConversationItem:
    item = channel_pb2.ConversationItem(
        item_id=row["id"],
        customer_id=row["customer_id"],
        platform=row["platform"],
        direction=row["direction"],
        text=row["text"],
        status=row["status"],
        at_ms=_unix_ms(row["sent_at"]),
        sender=(row["handle"] or "") if row["direction"] == "in" else "Darkfluenzer",
        error=row["error"] or "",
        read=bool(row["read_at"]) or row["direction"] == "out",
        conversation_id=row["conversation_id"],
        awaiting_start=row["direction"] == "system"
        and bool(row["origin_message_id"])
        and not row["order_id"],
    )
    if row["order_id"]:
        _fill_order(item.order, store, store.order_by_id(row["order_id"]))
    for att in row["attachments"]:
        item.attachments.add(
            kind=str(att.get("kind", "")),
            path=str(att.get("path", "")),
            mime=str(att.get("mime", "")),
            size=int(att.get("size") or 0),
            sha256=str(att.get("sha256", "")),
            status=str(att.get("status", "")),
            note=str(att.get("note", "")),
        )
    return item


async def _customer_page(request: web.Request) -> web.Response:
    """Alle Kundenakten (bei Aufruf, nach Lücken/Reconnect), Protobuf."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    store = request.app[COCKPIT_KEY].store
    page = channel_pb2.CustomerPage(
        customers=[_customer_summary(r) for r in store.customers_overview()],
        version=store.domain_version("customers"),
    )
    return web.Response(body=page.SerializeToString(), content_type=PROTOBUF)


async def _conversation_page(request: web.Request) -> web.Response:
    """Verlauf einer Kundenakte über alle Kanäle mit Identitäten (Antwortziele), Protobuf."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        customer_id = int(request.query["customer"])
        before = int(request.query.get("before", "0"))
        limit = min(max(int(request.query.get("limit", "60")), 1), 200)
    except (KeyError, ValueError):
        return web.Response(status=400, text="customer/before/limit müssen Zahlen sein")
    store = request.app[COCKPIT_KEY].store
    summary = store.customers_overview(customer_id)
    if not summary:
        raise web.HTTPNotFound()
    items, more = store.conversation_items(customer_id, before, limit)
    page = channel_pb2.ConversationPage(
        customer=_customer_summary(summary[0]),
        items=[_conversation_item(i, store) for i in items],
        more=more,
        version=store.domain_version("conversations"),
    )
    for ident in store.identities(customer_id):
        page.identities.add(
            identity_id=ident["id"],
            platform=ident["platform"],
            account=ident["account"],
            platform_user_id=ident["platform_user_id"],
            handle=ident["handle"] or "",
            verified=bool(ident["verified"]),
            conversation_id=ident["conversation_id"] or 0,
            revision=ident["revision"] or 0,
            ai_notice=ident["ai_notice_status"] or "",
            **_window(request.app[COCKPIT_KEY].instagram, ident),
        )
    if summary[0]["kind"] == "internal":
        d = store.default_contact()
        page.default_contact.CopyFrom(
            channel_pb2.DefaultContact(
                customer_id=d["customer_id"],
                telegram_sender_id=d["sender_ids"].get("telegram", ""),
                instagram_sender_id=d["sender_ids"].get("instagram", ""),
                process_commands=bool(d["process_commands"]),
                auto_orders=bool(d["auto_orders"]),
                approval_mode=d["approval_mode"],
                influencer=d["influencer"],
                media_workflow=d["media_workflow"],
                revision=d["revision"],
                video_workflow=d["video_workflow"],
            )
        )
    return web.Response(body=page.SerializeToString(), content_type=PROTOBUF)


def _static(dist: Path):
    """index.html stets revalidieren, gehashte Vite-Assets unveränderlich cachen."""
    assets = dist / "assets"

    async def index(_: web.Request) -> web.StreamResponse:
        page = dist / "index.html"
        if not page.is_file():
            return web.Response(status=503, text="Frontend fehlt: cd frontend && npm run build")
        return web.FileResponse(page, headers={"Cache-Control": "no-cache"})

    async def asset(request: web.Request) -> web.StreamResponse:
        path = (assets / request.match_info["name"]).resolve()
        if path.parent != assets.resolve() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    return index, asset


def create_app(cfg: Config) -> web.Application:
    store = Store(cfg.local)
    hub = Hub(
        schema=schema_id(cfg.root / "protocol" / "schemas"),
        heartbeat_s=cfg.server.heartbeat_s,
        catchup_limit=cfg.server.catchup_limit,
        head=store.journal_head,
        client_queue_max=cfg.server.client_queue_max,
    )
    cockpit = Cockpit(cfg, hub, store)
    hub.offer_state(spb.TOPIC_COMFY_INSTANCES, comfy_pb2.ComfyInstances.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_RESOURCES, comfy_pb2.Resources.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_JOBS_ACTIVE, comfy_pb2.JobsActive.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_COMFY_WORKFLOWS, comfy_pb2.Workflows.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_CHARACTERS, character_pb2.Characters.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_ORDERS_ACTIVE, order_pb2.OrdersActive.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_CHANNELS, channel_pb2.Channels.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_WALLET, wallet_pb2.Wallet.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_INFLUENCERS, influencer_pb2.Influencers.DESCRIPTOR.full_name)
    hub.offer_events(
        spb.TOPIC_CUSTOMER_UPDATED,
        channel_pb2.CustomerUpdated.DESCRIPTOR.full_name,
        cockpit.read_customers,
    )
    hub.offer_events(
        spb.TOPIC_CONVERSATION_EVENT,
        channel_pb2.ConversationEvent.DESCRIPTOR.full_name,
        cockpit.read_conversation,
    )
    hub.offer_events(
        spb.TOPIC_JOB_COMPLETED, comfy_pb2.JobCompleted.DESCRIPTOR.full_name, cockpit.read_jobs
    )
    hub.offer_events(
        spb.TOPIC_MEDIA_ADDED, media_pb2.MediaItem.DESCRIPTOR.full_name, cockpit.read_media
    )
    hub.offer_events(
        spb.TOPIC_MEDIA_REMOVED, media_pb2.MediaRemoved.DESCRIPTOR.full_name, cockpit.read_removed
    )
    hub.offer_events(
        spb.TOPIC_ORDER_UPDATED, order_pb2.OrderUpdated.DESCRIPTOR.full_name, cockpit.read_orders
    )
    hub.offer_events(
        spb.TOPIC_PAYMENT_UPDATED,
        wallet_pb2.PaymentUpdated.DESCRIPTOR.full_name,
        cockpit.read_payments,
    )
    hub.offer_events(
        spb.TOPIC_REFERENCE_ADDED,
        reference_pb2.ReferenceAdded.DESCRIPTOR.full_name,
        cockpit.read_references,
    )
    hub.offer_events(
        spb.TOPIC_COMMAND_RECEIPT,
        commands_pb2.CommandReceipt.DESCRIPTOR.full_name,
        cockpit.read_receipts,
    )

    limit = int(cfg.server.max_upload_mb * 1024 * 1024)
    app = web.Application(middlewares=[_host_check], client_max_size=limit)
    app[GUARD_KEY] = _Guard(cfg)
    app[HUB_KEY] = hub
    app[COCKPIT_KEY] = cockpit
    index, asset = _static(cfg.root / "frontend" / "dist")
    app.router.add_get("/", index)
    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/assets/{name}", asset)
    app.router.add_get("/api/v1/session", _session)
    app.router.add_post("/api/v1/command", _command)
    app.router.add_get("/ws/v1/stream", _stream)
    app.router.add_get("/api/v1/media/{path:.+}", _media(cfg.local))
    app.router.add_get("/api/v1/media-page", _media_page)
    app.router.add_get("/api/v1/provenance/{media_id}", _provenance_route)
    app.router.add_get("/api/v1/reference-page", _reference_page)
    app.router.add_get("/api/v1/payment-page", _payment_page)
    app.router.add_get("/api/v1/wallet-qr/{key}", _wallet_qr)
    app.router.add_get("/api/v1/payment-export/{month}", _payment_export)
    app.router.add_get("/api/v1/instagram/login", _ig_login)
    app.router.add_get("/api/v1/customer-page", _customer_page)
    app.router.add_get("/api/v1/conversation-page", _conversation_page)

    async def lifecycle(_: web.Application):
        cockpit.enqueue_existing()
        tasks = [
            asyncio.create_task(cockpit.observe()),
            *(asyncio.create_task(cockpit.render_worker(lane)) for lane in cockpit.lanes.values()),
            *(
                asyncio.create_task(cockpit.progress_listener(lane))
                for lane in cockpit.lanes.values()
            ),
        ]
        if cockpit.wallet:
            tasks.append(asyncio.create_task(cockpit.wallet.run()))
        for adapter in filter(None, (cockpit.telegram, cockpit.instagram)):
            tasks += [
                asyncio.create_task(adapter.run()),
                asyncio.create_task(adapter.outbox_worker()),
            ]
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        store.close()

    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(lambda _: hub.close_all())
    return app


def create_public_app(cockpit: Cockpit) -> web.Application:
    """Öffentlicher Eingang (einziges Tunnel-Ziel, bugs_v1 BUG-002): ausschließlich Webhook,
    OAuth-Rückruf und signierte Medien – jeweils mit eigener Prüfung; sonst existiert nichts."""
    cfg = cockpit.cfg
    app = web.Application(client_max_size=int(cfg.server.max_upload_mb * 1024 * 1024))
    app[COCKPIT_KEY] = cockpit
    if cfg.instagram:
        ig = cfg.instagram
        app.router.add_get(ig.webhook_path, _ig_verify)
        app.router.add_post(ig.webhook_path, _ig_webhook)
        app.router.add_get(ig.oauth_path, _ig_oauth)
        app.router.add_get(ig.media_path + "/{path:.+}", _ig_media)
    return app


def serve(cfg: Config) -> None:
    """Blockierend bis zum Beenden (Strg+C / SIGTERM). Mit Tunnel-Adresse zusätzlich der
    öffentliche Eingang auf 127.0.0.1:server.public_port (nur dieser Port ist Tunnel-Ziel)."""
    log.info("Cockpit auf %s", cfg.server.url)
    app = create_app(cfg)
    if cfg.instagram and cfg.instagram.public_base_url:
        runner = web.AppRunner(create_public_app(app[COCKPIT_KEY]), access_log=None)

        async def start_public(_: web.Application) -> None:
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", cfg.server.public_port).start()
            log.info(
                "Öffentlicher Eingang (nur Tunnel-Pfade) auf 127.0.0.1:%d", cfg.server.public_port
            )

        async def stop_public(_: web.Application) -> None:
            await runner.cleanup()

        app.on_startup.append(start_public)
        app.on_cleanup.append(stop_public)
    web.run_app(app, host=cfg.server.host, port=cfg.server.port, print=None, access_log=None)
