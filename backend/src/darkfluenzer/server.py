"""Lokaler Cockpit-Server: React-Build, Protobuf-WebSocket und Protobuf-Befehle auf EINEM Origin.

Schutz proportional zum Risiko (PHASENPLAN_FRONT_V1 F5): nur Loopback; Host-Prüfung gegen
DNS-Rebinding bei jeder Anfrage; Origin-Prüfung und Sitzungs-Cookie (HttpOnly, SameSite=Strict)
für WebSocket und geschützte Daten; zusätzlich CSRF-Token für zustandsändernde Befehle.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aiohttp import web
from google.protobuf.message import DecodeError

from . import comfy, models, pipeline, runtime, training
from .config import ComfyConfig, Config
from .store import Store, StoreError
from .stream import Hub, schema_id
from .v1 import character_pb2, comfy_pb2, commands_pb2, media_pb2
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
        "set_workflow_enabled",
        "open_workflow",
        "adopt_workflow",
        "delete_workflow",
        "create_workflow",
    }
)
# Ändern die Registry (neue Registry-Version nach dem Effekt)
_REGISTRY_EDITS = _REGISTRY_COMMANDS - {"render", "open_workflow"}
# Enden asynchron mit eigener Receipt: Render mit dem Job, ComfyUI mit Start/Stopp
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
            if not await self._admit(lane, job_id, engine):
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
                    unload_first=bool(lane.engine) and lane.engine != engine,
                )
            except Exception as exc:  # im Journal als fehlgeschlagen festgehalten
                log.error("Renderjob %s fehlgeschlagen: %s", job_id, exc)
            lane.engine, lane.running_job = engine, 0
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
        """Trainingsordner, Datensätze und LoRAs neu projizieren, nur wenn sich etwas änderte."""
        sig = (
            await asyncio.to_thread(training.signature, self.cfg.local),
            tuple(sorted(self.manifest.loras.items())),
        )
        if sig != self._character_sig:
            msg = await asyncio.to_thread(self._characters)
            fingerprint = hashlib.sha256(msg.SerializeToString()).hexdigest()
            msg.version = self.store.bump("characters", fingerprint)  # SQLite im Loop-Thread
            self.hub.set_state(spb.TOPIC_CHARACTERS, msg.SerializeToString())
            self._character_sig = sig

    def _characters(self) -> character_pb2.Characters:
        """B1: ein Charakter mit dem Trainingsdatenordner (Profile folgen in B2). Ohne Store-
        Zugriff, läuft im Worker-Thread (Scan hasht die Bilder)."""
        photos = training.scan(self.cfg.local)
        folder = training.character_dir(self.cfg.local)
        char = character_pb2.Character(
            id=folder.name,
            photos_dir=(folder / "photos").relative_to(self.cfg.root).as_posix(),
            usable=sum(p.status == "ok" for p in photos),
            min_images=training.MIN_IMAGES,
        )
        for p in photos:
            char.photos.add(
                name=p.name, status=p.status, width=p.width, height=p.height, note=p.note
            )
        for d in training.datasets(self.cfg.local):
            char.datasets.add(**d)
        for lo in self.manifest.loras.values():
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
        return character_pb2.Characters(characters=[char])

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
            job.params.update({k: str(v) for k, v in params.items()})

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
            )
            graph = comfy.load_graph(self.manifest, wf)
            for name, p in wf.params.items():
                param = info.params.add(
                    name=name,
                    type=p.type,
                    required=p.required,
                    upload=p.upload,
                    multiple_of=p.multiple_of or 0,
                    choices=list(p.choices),
                    label=p.label,
                    expert=p.is_expert,
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
                elif name in wf.params:
                    values.setdefault(name, value)
        for f in msg.files:
            if f.param not in wf.params or not wf.params[f.param].upload:
                return f"{f.param}: kein Upload-Parameter von {wf.key}."
            if f.media_id:  # exakte Galerie-Datei über ihre unveränderliche ID
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.input_from_media, self.cfg, f.media_id
                )
            else:
                inputs[f.param] = await asyncio.to_thread(
                    pipeline.store_input, self.cfg, f.data, f.filename
                )
        dataset = None
        if wf.training:  # Datensatzversion der aktuell geeigneten Bilder (mindestens MIN_IMAGES)
            dataset = (await asyncio.to_thread(training.build_dataset, self.cfg.local)).name
        job_id = pipeline.create_render(
            self.store,
            self.manifest,
            wf.key,
            values,
            inputs,
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
    )
    item.params.update({k: str(v) for k, v in row["params"].items()})
    return item


def _provenance(cockpit: Cockpit, media_id: int) -> media_pb2.MediaProvenance | None:
    """Herkunft eines Mediums aus Job-Journal, Graph-Snapshot und Herkunftsdatei des Laufs."""
    store, man = cockpit.store, cockpit.manifest
    row = store.media_by_id(media_id)
    if row is None:
        return None
    msg = media_pb2.MediaProvenance(media_id=media_id)
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


@web.middleware
async def _host_check(request: web.Request, handler):
    if request.host not in request.app[GUARD_KEY].hosts:
        return web.Response(status=403, text="Unbekannter Host")
    return await handler(request)


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

    payload_sha = hashlib.sha256(req.SerializeToString(deterministic=True)).hexdigest()
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


def _media(local: Path):
    """Erzeugte Bilder/Videos – nur Dateien des Galerie-Index, nur mit gültiger Sitzung.
    Pfade relativ zu local/; Dateien werden nie überschrieben. ``?download=1`` lädt herunter."""

    async def media(request: web.Request) -> web.StreamResponse:
        if request.app[GUARD_KEY].csrf_of(request) is None:
            return web.Response(status=401, text="Keine gültige Sitzung")
        rel = request.match_info["path"]
        if request.app[COCKPIT_KEY].store.media_by_path(rel) is None:
            raise web.HTTPNotFound()
        path = (local / rel).resolve()
        if not path.is_relative_to(local.resolve()) or not path.is_file():
            raise web.HTTPNotFound()
        headers = {"Cache-Control": "private, max-age=31536000, immutable"}
        if request.query.get("download") == "1":
            headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
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


async def _provenance_route(request: web.Request) -> web.Response:
    """Herkunft eines Mediums (Protobuf, bei Aufruf; Medien sind unveränderlich)."""
    if request.app[GUARD_KEY].csrf_of(request) is None:
        return web.Response(status=401, text="Keine gültige Sitzung")
    try:
        media_id = int(request.match_info["media_id"])
    except ValueError:
        return web.Response(status=400, text="media_id muss eine Zahl sein")
    msg = _provenance(request.app[COCKPIT_KEY], media_id)
    if msg is None:
        raise web.HTTPNotFound()
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}
    return web.Response(body=msg.SerializeToString(), content_type=PROTOBUF, headers=headers)


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


def serve(cfg: Config) -> None:
    """Blockierend bis zum Beenden (Strg+C / SIGTERM)."""
    log.info("Cockpit auf %s", cfg.server.url)
    web.run_app(
        create_app(cfg), host=cfg.server.host, port=cfg.server.port, print=None, access_log=None
    )
