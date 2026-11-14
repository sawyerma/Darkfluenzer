"""Lokaler Cockpit-Server: React-Build, Protobuf-WebSocket und Protobuf-Befehle auf EINEM Origin.

Schutz proportional zum Risiko (PHASENPLAN_FRONT_V1 F5): nur Loopback; Host-Prüfung gegen
DNS-Rebinding bei jeder Anfrage; Origin-Prüfung und Sitzungs-Cookie (HttpOnly, SameSite=Strict)
für WebSocket und geschützte Daten; zusätzlich CSRF-Token für zustandsändernde Befehle.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from aiohttp import web
from google.protobuf.message import DecodeError

from . import comfy, models, runtime
from .config import Config
from .store import Store
from .stream import Hub, schema_id
from .v1 import comfy_pb2, commands_pb2
from .v1 import stream_pb2 as spb

log = logging.getLogger("darkfluenzer.server")

SESSION_COOKIE = "df_session"
CSRF_HEADER = "X-CSRF-Token"
PROTOBUF = "application/x-protobuf"
MAX_SESSIONS = 32
MAX_REMEMBERED_COMMANDS = 256
MAX_COMMAND_BYTES = 64 * 1024


class Cockpit:
    """Projektionen und Befehle: ComfyUI-Zustand, Warteschlange und Workflows (STATE),
    abgeschlossene Jobs (EVENT)."""

    def __init__(self, cfg: Config, hub: Hub, store: Store) -> None:
        self.cfg = cfg
        self.hub = hub
        self.store = store
        self.manifest = models.load_manifest(cfg.root)  # Manifeständerung: Backend neu starten
        self._busy = ""  # "start" | "stop", solange ein ComfyUI-Befehl läuft
        self._error = ""
        self._status: dict = {}
        self._queue: list[tuple[int, bool]] = []  # (Job-ID oder 0, läuft?)
        self._tasks: set[asyncio.Task] = set()

    async def observe(self) -> None:
        """Beobachtet ComfyUI, Modelldateien und Job-Journal; gepusht wird nur bei Änderung."""
        while True:
            await self.refresh_comfy()
            workflows = await asyncio.to_thread(self._workflows)
            self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
            self.hub.push_events(spb.TOPIC_JOB_COMPLETED)
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
        self.hub.set_state(spb.TOPIC_COMFY_STATUS, self._comfy_status().SerializeToString())
        self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())

    def _read_queue(self) -> list[tuple[int, bool]]:
        client = comfy.ComfyClient(self.cfg.comfyui.url, timeout=self.cfg.server.observe_s)
        try:
            return client.queued_jobs()
        except comfy.ComfyError:
            return []

    def _jobs_active(self) -> bytes:
        ids = [job_id for job_id, _ in self._queue if job_id]
        names = self.store.job_workflows(ids) if ids else {}
        msg = comfy_pb2.JobsActive()
        for job_id, running in self._queue:
            msg.jobs.add(job_id=job_id, workflow=names.get(job_id, ""), running=running)
        return msg.SerializeToString()

    def _workflows(self) -> bytes:
        engines = models.status(self.manifest, models.models_dir(self.cfg.root))["engines"]
        msg = comfy_pb2.Workflows()
        for key, wf in self.manifest.workflows.items():
            eng, ready = self.manifest.engines[wf.engine], engines[wf.engine]
            msg.workflows.add(
                key=key,
                engine=wf.engine,
                engine_title=eng.title,
                kind=eng.kind,
                status=wf.status,
                models_ready=ready["ready"],
                missing_gb=ready["missing_gb"],
                usage=eng.usage,
            )
        return msg.SerializeToString()

    def _comfy_status(self) -> comfy_pb2.ComfyStatus:
        st = self._status
        health = st.get("health") or {}
        running = sum(1 for _, r in self._queue if r)
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

    def command(self, req: commands_pb2.CommandRequest) -> str:
        """Nimmt einen Befehl an (leerer Rückgabewert) oder nennt den Ablehnungsgrund."""
        which = req.WhichOneof("command")
        if which not in ("comfy_start", "comfy_stop"):
            return "Unbekannter Befehl"
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
        else comfy_pb2.JOB_RESULT_FAILED,
        error=data.get("error") or "",
        duration_s=float(data.get("duration_s") or 0),
        order_no=row["order_no"] or "",
    )
    for out in data.get("outputs") or []:
        msg.outputs.add(path=out["path"], sha256=out["sha256"], size=out["size"])
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
    body = await request.content.read(MAX_COMMAND_BYTES + 1)
    if len(body) > MAX_COMMAND_BYTES:
        return web.Response(status=413, text="Befehl zu groß")
    try:
        req = commands_pb2.CommandRequest.FromString(body)
        uuid.UUID(req.request_id)
    except (DecodeError, ValueError):
        return web.Response(status=400, text="Ungültiger CommandRequest")

    remembered: OrderedDict[str, tuple[bytes, bytes]] = request.app[COMMANDS_KEY]
    payload = req.SerializeToString(deterministic=True)
    if req.request_id in remembered:
        known_payload, known_response = remembered[req.request_id]
        if known_payload == payload:
            return web.Response(body=known_response, content_type=PROTOBUF)
        reason = "request_id wurde bereits für einen anderen Befehl verwendet"
        return _command_response(req.request_id, reason)

    reason = request.app[COCKPIT_KEY].command(req)
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

    app = web.Application(middlewares=[_host_check], client_max_size=MAX_COMMAND_BYTES)
    app[GUARD_KEY] = _Guard(cfg)
    app[HUB_KEY] = hub
    app[COCKPIT_KEY] = cockpit
    app[COMMANDS_KEY] = OrderedDict()
    index, asset = _static(cfg.root / "frontend" / "dist")
    app.router.add_get("/", index)
    app.router.add_get("/assets/{name}", asset)
    app.router.add_get("/api/v1/session", _session)
    app.router.add_post("/api/v1/command", _command)
    app.router.add_get("/ws/v1/stream", _stream)
    app.router.add_get("/api/v1/media/{path:.+}", _media(cfg.local))

    async def lifecycle(_: web.Application):
        observer = asyncio.create_task(cockpit.observe())
        yield
        observer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await observer
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
