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
import re
import secrets
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

from aiohttp import web
from google.protobuf.message import DecodeError

from ..channels.instagram import InstagramAccount, InstagramError
from ..config import Config
from ..core.base import CockpitBase, log
from ..core.characters import CharactersMixin
from ..core.cloner import ClonerMixin
from ..core.delivery import DeliveryMixin
from ..core.messages import MessagesMixin
from ..core.orders import OrdersMixin
from ..core.registry import RegistryMixin
from ..core.render import RenderMixin
from ..core.sales import SalesMixin
from ..store import Store, StoreError
from ..v1 import (
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
from ..v1 import stream_pb2 as spb
from .commands import CommandsMixin
from .mappers import (
    MappersMixin,
    _conversation_item,
    _customer_summary,
    _media_item,
    _payment,
    _provenance,
    _reference_item,
    _window,
)
from .stream import Hub, schema_id

SESSION_COOKIE = "df_session"


CSRF_HEADER = "X-CSRF-Token"


PROTOBUF = "application/x-protobuf"


MAX_SESSIONS = 32


MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Cockpit(
    MappersMixin,
    CommandsMixin,
    RenderMixin,
    RegistryMixin,
    OrdersMixin,
    ClonerMixin,
    MessagesMixin,
    SalesMixin,
    DeliveryMixin,
    CharactersMixin,
    CockpitBase,
):
    """Projektionen und Befehle: ComfyUI-Instanzen, Warteschlangen, Ressourcen und Workflows
    (STATE), abgeschlossene Jobs, Medien und Befehls-Receipts (EVENT)."""


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
                command_workflows=[
                    channel_pb2.CommandWorkflow(command=c, workflow=w)
                    for c, w in sorted(d["command_workflows"].items())
                ],
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
