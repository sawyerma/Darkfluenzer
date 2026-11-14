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
import secrets
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from aiohttp import web
from google.protobuf.message import DecodeError

from . import comfy, models, pipeline, runtime
from .config import Config
from .store import Store, StoreError
from .stream import Hub, schema_id
from .v1 import comfy_pb2, commands_pb2
from .v1 import stream_pb2 as spb

log = logging.getLogger("darkfluenzer.server")

SESSION_COOKIE = "df_session"
CSRF_HEADER = "X-CSRF-Token"
PROTOBUF = "application/x-protobuf"
MAX_SESSIONS = 32
MAX_REMEMBERED_COMMANDS = 256
# Befehle, deren Fehler als Ablehnungsgrund an den Betreiber gehen (Eingabe-/Registry-Prüfung)
_COMMAND_ERRORS = (
    models.ManifestError,
    pipeline.PipelineError,
    comfy.ComfyError,
    StoreError,
    ValueError,
    OSError,
)


class Cockpit:
    """Projektionen und Befehle: ComfyUI-Zustand, Warteschlange und Workflows (STATE),
    abgeschlossene Jobs (EVENT)."""

    def __init__(self, cfg: Config, hub: Hub, store: Store) -> None:
        self.cfg = cfg
        self.hub = hub
        self.store = store
        # Einzige Registry; Änderungen aus dem Cockpit ersetzen dieses Objekt nach dem Speichern.
        self.manifest = models.load_manifest(cfg.root)
        self._busy = ""  # "start" | "stop", solange ein ComfyUI-Befehl läuft
        self._error = ""
        self._status: dict = {}
        # ComfyUI-Warteschlange: (Job-ID oder 0, läuft?, prompt_id)
        self._queue: list[tuple[int, bool, str]] = []
        # Eigene ComfyUI-Client-ID der Renderjobs: nur an sie meldet ComfyUI den Fortschritt
        self.client_id = uuid.uuid4().hex
        self._progress: dict[str, tuple[int, int]] = {}  # prompt_id -> (Wert, Maximum)
        self._resume = asyncio.Event()  # gesetzt = Warteschlange läuft, gelöscht = angehalten
        self._resume.set()
        self._cancelled: set[int] = set()  # laufende Jobs mit Abbruchwunsch des Betreibers
        self._renders: asyncio.Queue[int] = asyncio.Queue()  # FIFO der Backend-Renderjobs
        # Registry-Änderungen und das Lesen der Workflow-Projektion nie gleichzeitig
        self._registry = asyncio.Lock()
        self._manifest_mtime = self._manifest_path().stat().st_mtime_ns
        self._tasks: set[asyncio.Task] = set()
        for key in self.manifest.workflows:  # Editor-Kopien für "Öffnen" bereitstellen
            comfy.install_editor_copy(cfg, self.manifest, key)

    def _manifest_path(self) -> Path:
        return self.cfg.root / models.MANIFEST_RELATIVE

    def _reload_if_changed(self) -> None:
        """Externe Änderungen an manifest.toml (CLI, git) übernehmen; ungültige Fassung -> alte
        Registry bleibt aktiv, Fehler im Log."""
        mtime = self._manifest_path().stat().st_mtime_ns
        if mtime == self._manifest_mtime:
            return
        self._manifest_mtime = mtime
        try:
            self.manifest = models.load_manifest(self.cfg.root)
        except models.ManifestError as exc:
            log.error("Geänderte Registry ungültig, bisherige bleibt aktiv: %s", exc)
            return
        for key in self.manifest.workflows:
            comfy.install_editor_copy(self.cfg, self.manifest, key)
        log.info("Registry neu geladen (%d Workflows)", len(self.manifest.workflows))

    async def render_worker(self) -> None:
        """Führt Renderjobs nacheinander (FIFO) über den einen Renderpfad aus. Nach einem
        Neustart werden angelegte, noch nicht gestartete Jobs in Reihenfolge fortgesetzt."""
        for job_id, pid in self.store.running_jobs():
            if not pid or not runtime.pid_alive(pid):  # Ausführender Prozess beendet
                self.store.set_job_status(
                    job_id, "failed", error="Abgebrochen: ausführender Prozess wurde beendet."
                )
        for job_id, _ in self.store.queued_jobs():
            self._renders.put_nowait(job_id)
        while True:
            job_id = await self._renders.get()
            await self._resume.wait()  # angehalten: nächster Job wartet
            if self.store.job(job_id)["status"] != "queued":  # inzwischen entfernt
                continue
            try:
                await asyncio.to_thread(
                    pipeline.run_render,
                    self.cfg,
                    self.manifest,
                    job_id,
                    client_id=self.client_id,
                    is_cancelled=lambda job=job_id: job in self._cancelled,
                )
            except Exception as exc:  # im Journal als fehlgeschlagen festgehalten
                log.error("Renderjob %s fehlgeschlagen: %s", job_id, exc)
            self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
            self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    async def observe(self) -> None:
        """Beobachtet ComfyUI, Modelldateien und Job-Journal; gepusht wird nur bei Änderung."""
        while True:
            try:
                await self.refresh_comfy()
                async with self._registry:
                    await asyncio.to_thread(self._reload_if_changed)
                    workflows = await asyncio.to_thread(self._workflows)
                self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
                self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
            except Exception:  # eine fehlerhafte Runde beendet die Beobachtung nicht
                log.exception("Beobachtung fehlgeschlagen")
            await asyncio.sleep(self.cfg.server.observe_s)

    async def refresh_comfy(self) -> None:
        try:
            self._status = await asyncio.to_thread(runtime.status, self.cfg)
        except runtime.RuntimeFailure as exc:
            self._status = {"state": "error", "managed": False}
            self._error = str(exc)
        self._queue = (
            await asyncio.to_thread(self._read_queue) if self._status.get("health") else []
        )
        queued = {prompt_id for _, _, prompt_id in self._queue}
        self._progress = {p: v for p, v in self._progress.items() if p in queued}
        self.hub.set_state(spb.TOPIC_COMFY_STATUS, self._comfy_status().SerializeToString())
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    async def progress_listener(self) -> None:
        """Fortschritt (z. B. Sampler-Schritte) der eigenen Aufträge aus ComfyUIs WebSocket in die
        Warteschlange übernehmen; bei Verbindungsverlust nach der Beobachtungspause erneut."""
        while True:
            if self._status.get("health"):
                try:
                    async for prompt_id, value, maximum in comfy.progress_events(
                        self.cfg.comfyui.url, self.client_id
                    ):
                        if maximum:
                            self._progress[prompt_id] = (value, maximum)
                        else:
                            self._progress.pop(prompt_id, None)
                        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
                except Exception as exc:  # ComfyUI beendet/neu gestartet: später neu verbinden
                    log.debug("ComfyUI-Fortschritt getrennt: %s", exc)
            await asyncio.sleep(self.cfg.server.observe_s)

    def _read_queue(self) -> list[tuple[int, bool, str]]:
        client = comfy.ComfyClient(self.cfg.comfyui.url, timeout=self.cfg.server.observe_s)
        try:
            return client.queued_jobs()
        except comfy.ComfyError:
            return []

    def _jobs_active(self) -> bytes:
        """FIFO-Sicht: ComfyUI (läuft, wartet), danach angelegte, noch nicht übergebene Jobs."""
        queued = [job_id for job_id, _ in self.store.queued_jobs()]
        in_comfy = [job_id for job_id, _, _ in self._queue if job_id]
        ids = in_comfy + [j for j in queued if j not in in_comfy]
        brief = self.store.jobs_brief(ids) if ids else {}
        msg = comfy_pb2.JobsActive(paused=not self._resume.is_set())

        def add(job_id: int, running: bool, prompt_id: str = "") -> None:
            workflow, params = brief.get(job_id, ("", {}))
            value, maximum = self._progress.get(prompt_id, (0, 0)) if running else (0, 0)
            job = msg.jobs.add(
                job_id=job_id,
                workflow=workflow,
                running=running,
                progress_value=value,
                progress_max=maximum,
            )
            job.params.update({k: str(v) for k, v in params.items()})

        for job_id, running, prompt_id in self._queue:
            add(job_id, running, prompt_id)
        for job_id in queued:
            if job_id not in in_comfy:
                add(job_id, False)
        return msg.SerializeToString()

    def _workflows(self) -> bytes:
        engines = models.status(self.manifest, models.models_dir(self.cfg.root))["engines"]
        msg = comfy_pb2.Workflows()
        for key, wf in self.manifest.workflows.items():
            eng, ready = self.manifest.engines[wf.engine], engines[wf.engine]
            registry_ui = self.manifest.root / "workflows" / wf.ui
            editor = comfy.editor_file(self.cfg, key)
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
                editor_changed=editor.is_file() and editor.read_bytes() != registry_ui.read_bytes(),
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

    def _comfy_status(self) -> comfy_pb2.ComfyStatus:
        st = self._status
        health = st.get("health") or {}
        running = sum(1 for _, r, _ in self._queue if r)
        if self._busy == "start":
            state = comfy_pb2.COMFY_STATE_STARTING
        elif self._busy == "stop":
            state = comfy_pb2.COMFY_STATE_STOPPING
        elif health and st.get("state") in ("running", "foreign"):
            state = comfy_pb2.COMFY_STATE_BUSY if running else comfy_pb2.COMFY_STATE_READY
            self._error = ""
        elif st.get("state") == "starting":
            state = comfy_pb2.COMFY_STATE_STARTING
        elif st.get("state") == "stopped":
            state = comfy_pb2.COMFY_STATE_FAILED if self._error else comfy_pb2.COMFY_STATE_STOPPED
        else:  # unhealthy, fremder Prozess ohne ComfyUI-Antwort, Prüffehler
            state = comfy_pb2.COMFY_STATE_UNREACHABLE
        return comfy_pb2.ComfyStatus(
            state=state,
            managed=bool(st.get("managed")),
            url=self.cfg.comfyui.url,
            version=health.get("comfyui_version") or "",
            device=health.get("device_type") or "",
            error=self._error,
            queue_running=running,
            queue_pending=len(self._queue) - running,
        )

    async def command(self, req: commands_pb2.CommandRequest) -> str:
        """Nimmt einen Befehl an (leerer Rückgabewert) oder nennt den Ablehnungsgrund."""
        which = req.WhichOneof("command")
        handlers = {
            "render": self._render,
            "set_workflow_enabled": self._set_enabled,
            "open_workflow": self._open,
            "adopt_workflow": self._adopt,
            "delete_workflow": self._delete,
            "create_workflow": self._create,
            "cancel_job": self._cancel,
            "pause_queue": self._pause,
        }
        if which in ("comfy_start", "comfy_stop"):
            return self._comfy_command(which)
        if which not in handlers:
            return "Unbekannter Befehl"
        async with self._registry:
            try:
                reason = await handlers[which](getattr(req, which))
            except _COMMAND_ERRORS as exc:
                return str(exc)
            workflows = await asyncio.to_thread(self._workflows)
        self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
        return reason

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

    async def _render(self, msg: commands_pb2.Render) -> str:
        wf = self._workflow(msg.workflow)
        if reason := await asyncio.to_thread(self._not_startable, wf):
            return reason
        values = {
            v.name: getattr(v, v.WhichOneof("value")) for v in msg.values if v.WhichOneof("value")
        }
        inputs = {}
        for f in msg.files:
            if f.param not in wf.params or not wf.params[f.param].upload:
                return f"{f.param}: kein Upload-Parameter von {wf.key}."
            inputs[f.param] = await asyncio.to_thread(
                pipeline.store_input, self.cfg, f.data, f.filename
            )
        job_id = pipeline.create_render(self.store, self.manifest, wf.key, values, inputs)
        log.info("Renderjob %s (%s) eingereiht", job_id, wf.key)
        self._renders.put_nowait(job_id)
        return ""

    async def _set_enabled(self, msg: commands_pb2.SetWorkflowEnabled) -> str:
        self._workflow(msg.workflow)
        self.manifest = await asyncio.to_thread(
            models.set_workflow_enabled, self.cfg.root, msg.workflow, msg.enabled
        )
        log.info("Workflow %s %s", msg.workflow, "aktiviert" if msg.enabled else "deaktiviert")
        return ""

    async def _open(self, msg: commands_pb2.OpenWorkflow) -> str:
        self._workflow(msg.workflow)
        if not self._status.get("health"):
            return "ComfyUI läuft nicht."
        await asyncio.to_thread(comfy.install_editor_copy, self.cfg, self.manifest, msg.workflow)
        return ""

    async def _adopt(self, msg: commands_pb2.AdoptWorkflow) -> str:
        wf = self._workflow(msg.workflow)
        if not self._status.get("health"):
            return "ComfyUI läuft nicht (Node-Definitionen für die Prüfung fehlen)."

        def adopt() -> models.Manifest:
            info = comfy.ComfyClient(self.cfg.comfyui.url, timeout=120).object_info()
            edited = json.loads(comfy.editor_file(self.cfg, wf.key).read_text(encoding="utf-8"))
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

    async def _create(self, msg: commands_pb2.CreateWorkflow) -> str:
        self._workflow(msg.source)
        self.manifest, key = await asyncio.to_thread(
            models.create_workflow, self.cfg.root, msg.source, msg.title
        )
        await asyncio.to_thread(comfy.install_editor_copy, self.cfg, self.manifest, key)
        log.info("Workflow %s als Kopie von %s angelegt", key, msg.source)
        return ""

    async def _cancel(self, msg: commands_pb2.CancelJob) -> str:
        job = self.store.job(msg.job_id)
        if job["status"] == "queued":
            self.store.set_job_status(
                msg.job_id, "failed", error="Aus der Warteschlange entfernt.", cancelled=True
            )
            log.info("Job %s aus der Warteschlange entfernt", msg.job_id)
            return ""
        if job["status"] != "running":
            return "Auftrag ist bereits abgeschlossen."
        prompt = next((p for j, _, p in self._queue if j == msg.job_id), "")
        if not prompt:
            return "Auftrag startet gerade – gleich erneut versuchen."
        self._cancelled.add(msg.job_id)
        client = comfy.ComfyClient(self.cfg.comfyui.url, timeout=self.cfg.server.timeout_s)
        await asyncio.to_thread(client.cancel, prompt)
        log.info("Job %s (prompt %s) abgebrochen", msg.job_id, prompt)
        return ""

    async def _pause(self, msg: commands_pb2.PauseQueue) -> str:
        if msg.paused:
            self._resume.clear()
        else:
            self._resume.set()
        log.info("Warteschlange %s", "angehalten" if msg.paused else "fortgesetzt")
        return ""

    async def _delete(self, msg: commands_pb2.DeleteWorkflow) -> str:
        wf = self._workflow(msg.workflow)
        active = comfy_pb2.JobsActive.FromString(self._jobs_active())
        if any(job.workflow == wf.key for job in active.jobs):
            return "Workflow hat laufende oder wartende Aufträge."
        self.manifest = await asyncio.to_thread(models.delete_workflow, self.cfg.root, wf.key)
        await asyncio.to_thread(comfy.remove_editor_copy, self.cfg, wf.key)
        log.info("Workflow %s gelöscht (Registrierung, UI/API, Editor-Kopie)", wf.key)
        return ""

    def _comfy_command(self, which: str) -> str:
        if self._busy:
            return "Ein ComfyUI-Befehl läuft bereits"
        if self._status.get("state") == "foreign":
            return "Port belegt durch eine nicht von Darkfluenzer gestartete Instanz"
        action = "start" if which == "comfy_start" else "stop"
        self._busy, self._error = action, ""
        self.hub.set_state(spb.TOPIC_COMFY_STATUS, self._comfy_status().SerializeToString())
        task = asyncio.create_task(self._run(action))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return ""

    async def _run(self, action: str) -> None:
        fn = runtime.start if action == "start" else runtime.stop
        try:
            await asyncio.to_thread(fn, self.cfg)
        except runtime.RuntimeFailure as exc:
            log.error("ComfyUI %s fehlgeschlagen: %s", action, exc)
            self._error = str(exc)
        finally:
            self._busy = ""
        await self.refresh_comfy()

    def read_jobs(self, after: int, limit: int) -> tuple[list[tuple[int, int, bytes]], bool]:
        rows, gap = self.store.finished_jobs(after, limit)
        return [(r["id"], _unix_ms(r["created_at"]), _job_completed(r)) for r in rows], gap


def _unix_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _job_completed(row: dict) -> bytes:
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
        msg.outputs.add(path=out["path"], sha256=out["sha256"], size=out["size"])
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
COMMANDS_KEY = web.AppKey("commands", OrderedDict)


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

    remembered: OrderedDict[str, tuple[bytes, bytes]] = request.app[COMMANDS_KEY]
    payload = hashlib.sha256(req.SerializeToString(deterministic=True)).digest()
    if req.request_id in remembered:
        known_payload, known_response = remembered[req.request_id]
        if known_payload == payload:
            return web.Response(body=known_response, content_type=PROTOBUF)
        reason = "request_id wurde bereits für einen anderen Befehl verwendet"
        return _command_response(req.request_id, reason)

    reason = await request.app[COCKPIT_KEY].command(req)
    resp = _command_response(req.request_id, reason)
    remembered[req.request_id] = (payload, resp.body)
    while len(remembered) > MAX_REMEMBERED_COMMANDS:
        remembered.popitem(last=False)
    return resp


def _command_response(request_id: str, reason: str) -> web.Response:
    accepted, rejected = commands_pb2.COMMAND_STATUS_ACCEPTED, commands_pb2.COMMAND_STATUS_REJECTED
    status = rejected if reason else accepted
    msg = commands_pb2.CommandResponse(request_id=request_id, status=status, detail=reason)
    return web.Response(body=msg.SerializeToString(), content_type=PROTOBUF)


def _media(local: Path):
    """Ausgabedateien der Renderungen (nur unter local/evaluation), nur mit gültiger Sitzung.
    Pfade sind relativ zu local/, wie in JobCompleted.outputs; Dateien werden nie überschrieben."""
    allowed = (local / "evaluation").resolve()

    async def media(request: web.Request) -> web.StreamResponse:
        if request.app[GUARD_KEY].csrf_of(request) is None:
            return web.Response(status=401, text="Keine gültige Sitzung")
        path = (local / request.match_info["path"]).resolve()
        if not path.is_relative_to(allowed) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Cache-Control": "private, max-age=31536000, immutable"}
        )

    return media


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
    )
    cockpit = Cockpit(cfg, hub, store)
    hub.offer_state(spb.TOPIC_COMFY_STATUS, comfy_pb2.ComfyStatus.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_JOBS_ACTIVE, comfy_pb2.JobsActive.DESCRIPTOR.full_name)
    hub.offer_state(spb.TOPIC_COMFY_WORKFLOWS, comfy_pb2.Workflows.DESCRIPTOR.full_name)
    hub.offer_events(
        spb.TOPIC_JOB_COMPLETED, comfy_pb2.JobCompleted.DESCRIPTOR.full_name, cockpit.read_jobs
    )

    limit = int(cfg.server.max_upload_mb * 1024 * 1024)
    app = web.Application(middlewares=[_host_check], client_max_size=limit)
    app[GUARD_KEY] = _Guard(cfg)
    app[HUB_KEY] = hub
    app[COCKPIT_KEY] = cockpit
    app[COMMANDS_KEY] = OrderedDict()
    index, asset = _static(cfg.root / "frontend" / "dist")
    app.router.add_get("/", index)
    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/assets/{name}", asset)
    app.router.add_get("/api/v1/session", _session)
    app.router.add_post("/api/v1/command", _command)
    app.router.add_get("/ws/v1/stream", _stream)
    app.router.add_get("/api/v1/media/{path:.+}", _media(cfg.local))

    async def lifecycle(_: web.Application):
        tasks = [
            asyncio.create_task(cockpit.observe()),
            asyncio.create_task(cockpit.render_worker()),
            asyncio.create_task(cockpit.progress_listener()),
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
