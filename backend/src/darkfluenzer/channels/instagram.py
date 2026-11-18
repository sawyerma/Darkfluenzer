"""Claras Instagram-Creator-Konto über die Instagram-API mit Instagram-Login (PHASENPLAN_V0 §6,
§6.1, C2/C4) – Darkfluenzer liest und beantwortet Direktnachrichten und veröffentlicht nie etwas.

Öffentlich über den Tunnel (§10 Punkt 1) sind nur drei Pfade, jeder mit eigener Prüfung: Webhook
(Verify-Token beim Abonnieren, Meta-Signatur ``X-Hub-Signature-256`` über die unveränderten
Bytes), OAuth-Rückruf (einmaliger, kurzlebiger ``state``) und Abruf ausgehender Medien
(kurzlebiges, je Pfad signiertes Token). App-ID, App-Geheimnis, Verify-Token, Zugangstoken und
Medienschlüssel liegen nur im Schlüsselbund und erscheinen nie in Logs, Fehlertexten oder SQLite.

Eingang: jedes Ereignis wird vor der Antwort 200 genau einmal gespeichert (``mid``), Medien
sofort gesichert (CDN-Adressen laufen ab). Echos eigener Sendungen werden über die gemerkten
``mid`` erkannt; schreibt der Betreiber in der Instagram-App, entsteht die Karte
``ÜBERGABE AN BETREIBER``. Ausgang nur über den Postausgang und nur im 24-h-Fenster; danach
ausschließlich manuell mit Human-Agent-Kennzeichnung (FRONT F4 V1.12 Punkt 10).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode, urlsplit

import aiohttp

from ..config import Config
from ..keychain import secret, store_secret
from ..store import Inbound, Store, StoreError, sha256_file
from .base import Capabilities, Channel
from .telegram import HANDOFF_CARD

log = logging.getLogger("darkfluenzer.instagram")

PLATFORM = "instagram"
MEDIA_TOKEN_PARAM = "t"  # Query-Parameter der signierten Medien-URL
# adapter_state je Konto
WINDOW = "window:"  # letzte Kundennachricht je Konversation (Unix-ms, Antwortfenster)
READ = "read:"  # letzte Lesebestätigung des Kunden je Konversation (Unix-ms)
OWN = "own:"  # zuletzt aus dem Postausgang gesendete mid je Konversation (Echo-Erkennung)
USER = "user:"  # Benutzername und Name je Absender (einmal abgefragt)
PENDING = "pending"  # Nachrichten mit noch zu sichernden Anhängen (Fortsetzung nach Neustart)
HUMAN = "human_agent"  # Postausgang-IDs mit Human-Agent-Kennzeichnung (nur Betreiberaktion)
OWN_KEPT = 50  # gemerkte eigene mid bzw. unbestätigte Sendungen je Konversation
MB = 1024 * 1024
CHUNK = 1024 * 1024
_KEYS = ("app_id", "app_secret", "verify_token", "token", "token_expiry", "media_key")
# Instagram-Anhangart -> Anhangart im Cockpit (MessageAttachment.kind)
_KIND = {
    "image": "photo",
    "video": "video",
    "audio": "audio",
    "file": "document",
    "share": "share",
    "ig_reel": "reel",
    "reel": "reel",
    "ig_post": "post",
    "story_mention": "other",
    "ig_story": "other",
    "story_reply": "other",
}
_STORY = {"story_mention", "ig_story", "story_reply"}  # Art erst nach dem Laden (Foto/Video)
_NOTE = {
    "story_mention": "Story-Erwähnung",
    "ig_story": "Story",
    "story_reply": "Antwort auf Story",
}
_MEDIA = ("image/", "video/", "audio/")
# Versand (Meta Send API): Bilder nur PNG/JPEG/GIF, Video und Audio je nach Inhaltstyp
_SEND_IMAGE = {"image/png", "image/jpeg", "image/gif"}


class InstagramError(Exception):
    """Einrichtung fehlt oder Eingabe ungültig (Meldung für Menschen)."""


class HttpError(Exception):
    """Aufruf bei Meta fehlgeschlagen; ``maybe_sent``: Meta kann ihn trotzdem angenommen haben
    (Zeitüberschreitung, Abbruch, 5xx) – dann nie blind wiederholen."""

    def __init__(self, message: str, *, maybe_sent: bool) -> None:
        super().__init__(message)
        self.maybe_sent = maybe_sent


class GraphError(HttpError):
    """Fehlerantwort der Graph-API mit Meta-Fehlercode (190 = Token ungültig)."""

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(f"{message} (HTTP {status}, Code {code})", maybe_sent=status >= 500)
        self.status = status
        self.code = code


class TooLarge(Exception):
    """Anhang über ``max_download_mb``."""


class Http:
    """Dünne aiohttp-Schicht für Graph-API und CDN-Downloads. Fehlertexte enthalten nie die
    Adresse (Token und Geheimnisse stehen dort teils als Parameter)."""

    def __init__(self, timeout_s: float) -> None:
        self.timeout_s = timeout_s
        self._session: aiohttp.ClientSession | None = None

    def _client(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_s)
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        body: dict | None = None,
        token: str | None = None,
        timeout_s: float | None = None,
    ) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        timeout = aiohttp.ClientTimeout(total=timeout_s or self.timeout_s)
        try:
            async with self._client().request(
                method, url, params=params, data=data, json=body, headers=headers, timeout=timeout
            ) as resp:
                status, text = resp.status, await resp.text()
        except TimeoutError:
            raise HttpError("Keine Antwort von Instagram", maybe_sent=True) from None
        except aiohttp.ClientConnectorError:
            raise HttpError("Instagram nicht erreichbar", maybe_sent=False) from None
        except aiohttp.ClientError as exc:
            raise HttpError(
                f"Verbindung abgebrochen ({type(exc).__name__})", maybe_sent=True
            ) from None
        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            payload = {}
        if status < 400:
            return payload if isinstance(payload, dict) else {}
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            code, message = _int(err.get("code")), str(err.get("message") or "")
        elif isinstance(payload, dict):  # OAuth-Endpunkt: error_type/code/error_message
            code, message = _int(payload.get("code")), str(payload.get("error_message") or "")
        else:
            code, message = 0, ""
        raise GraphError(status, code, (message or "Fehler")[:200])

    async def download(self, url: str, target: Path, limit: int, timeout_s: float) -> str:
        """Datei nach ``target`` (höchstens ``limit`` Bytes); liefert den Inhaltstyp."""
        try:
            async with self._client().get(
                url, timeout=aiohttp.ClientTimeout(total=timeout_s)
            ) as resp:
                if resp.status >= 400:
                    raise HttpError(f"HTTP {resp.status}", maybe_sent=False)
                if (resp.content_length or 0) > limit:
                    raise TooLarge
                size = 0
                with open(target, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(CHUNK):
                        size += len(chunk)
                        if size > limit:
                            raise TooLarge
                        fh.write(chunk)
                return resp.headers.get("Content-Type", "")
        except TimeoutError:
            raise HttpError("Zeitüberschreitung beim Laden", maybe_sent=False) from None
        except aiohttp.ClientError as exc:
            raise HttpError(
                f"Laden fehlgeschlagen ({type(exc).__name__})", maybe_sent=False
            ) from None


def signature_ok(app_secret: str, body: bytes, header: str) -> bool:
    """Meta-Signatur ``sha256=<HMAC-SHA256(App-Geheimnis, unveränderte Bytes)>``, zeitkonstant."""
    if not app_secret or not header:
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.strip().lower().encode())


def attachment_of(att: dict) -> dict:
    """Anhang eines Instagram-Ereignisses normalisiert; mit CDN-Adresse ``pending`` (``source``
    bleibt nur bis zum Sichern gespeichert), sonst ``not_importable``."""
    kind = str(att.get("type") or "")
    payload = att.get("payload") if isinstance(att.get("payload"), dict) else {}
    out: dict = {"kind": _KIND.get(kind, "other"), "size": 0, "mime": "", "ig_type": kind}
    notes = [n for n in (_NOTE.get(kind, ""), str(payload.get("title") or "")) if n]
    for field in ("reel_video_id", "ig_post_media_id", "id"):
        if payload.get(field):
            out["ref_id"] = str(payload[field])
            break
    url = str(payload.get("url") or "")
    if url.startswith("https://"):
        out |= {"status": "pending", "source": url}
    else:
        out["status"] = "not_importable"
        notes.append("ohne abrufbare Datei")
    if notes:
        out["note"] = " · ".join(notes)[:200]
    return out


class InstagramAccount(Channel):
    """Claras Instagram-Konto (Creator) – Kanalvertrag wie ``TelegramAccount``."""

    platform = PLATFORM

    def capabilities(self) -> Capabilities:
        """Keine Dateien als Dokument; Antwortfenster und Größen aus der Konfiguration."""
        return Capabilities(
            document=False,
            self_destruct=False,
            reply_window=True,
            read_receipts=False,
            typing=False,
            max_text_bytes=self.ig.max_text_bytes,
            max_attachment_mb={
                "image": self.ig.max_image_mb,
                "video": self.ig.max_video_mb,
                "audio": self.ig.max_audio_mb,
            },
        )

    def __init__(
        self,
        cfg: Config,
        store: Store,
        on_inbound: Callable[[Inbound], Awaitable[None]],
        on_change: Callable[[], None],
        account: dict | None = None,
    ) -> None:
        self.key = account["key"] if account else "instagram"  # Kanalkonto (SP2 Schritt 9a)
        assert cfg.instagram is not None
        self.cfg = cfg
        self.ig = cfg.instagram
        self.store = store
        self.on_inbound = on_inbound
        self.on_change = on_change
        self.account = ""  # Instagram-Konto-ID (``/me`` user_id) nach der Anmeldung
        self.username = ""
        self.state = "OFF"
        self.login_needed = False  # nur die Instagram-Anmeldung fehlt (OAuth-Link)
        self.error = ""
        self.missing = ""
        self.last_event_ms = 0
        self.wake = asyncio.Event()  # Postausgang hat Arbeit
        self.http = Http(cfg.server.timeout_s)
        self._keys: dict[str, str] = {}  # Schlüsselbundwerte, nur im Speicher
        self._states: dict[str, float] = {}  # OAuth-state -> Ablauf (monotonic)
        self._subscribed = False
        self._refresh_after = 0.0
        self._sent_at: deque[float] = deque()
        self._inflight: dict[str, asyncio.Event] = {}  # Konversation -> laufender Sendeaufruf
        self._chains: dict[str, asyncio.Task] = {}  # Reihenfolge je Konversation
        self._tasks: set[asyncio.Task] = set()
        self._scheduled: set[int] = set()

    # ------------------------------------------------------------------ Zustand

    @property
    def automation(self) -> bool:
        return (
            bool(self.account)
            and self.store.adapter_get(PLATFORM, self.account, "automation") == "1"
        )

    def status(self) -> dict:
        return {
            "platform": PLATFORM,
            "account": f"@{self.username}" if self.username else self.account,
            "state": self.state,
            "error": self.error or self.task_error,
            "last_event_ms": self.last_event_ms,
            "missing": self.missing,
            # oauth: nur die Anmeldung fehlt -> Cockpit zeigt „Mit Instagram anmelden“
            "login_state": "ready"
            if self.state == "READY"
            else "oauth"
            if self.login_needed
            else "",
            "automation": self.automation,
        }

    def _set(self, state: str, *, error: str = "", missing: str = "", login: bool = False) -> None:
        new = (state, error, missing, login)
        if state == "READY" and self.task_error:  # wieder bereit: Meldung der Aufsicht erledigt
            self.task_error = ""
            self.on_change()
        if new != (self.state, self.error, self.missing, self.login_needed):
            self.state, self.error, self.missing, self.login_needed = new
            self.on_change()

    def set_automation(self, enabled: bool) -> str:
        if not self.account:
            return "Nicht angemeldet."
        self.store.adapter_set(PLATFORM, self.account, "automation", "1" if enabled else "0")
        self.on_change()
        return ""

    @property
    def public_host(self) -> str:
        """Host der Tunnel-Adresse (für die Host-Prüfung der drei öffentlichen Pfade)."""
        return urlsplit(self.ig.public_base_url).netloc

    def is_public(self, path: str) -> bool:
        """Nur Webhook, OAuth-Rückruf und Medienabruf sind über den Tunnel erreichbar."""
        return path in (self.ig.webhook_path, self.ig.oauth_path) or path.startswith(
            self.ig.media_path + "/"
        )

    # ------------------------------------------------------------------ Schlüsselbund

    def _service(self, name: str) -> str:
        return str(getattr(self.ig, f"{name}_service"))

    def _load_keys(self) -> dict[str, str]:
        keys = {name: secret(self._service(name)) or "" for name in _KEYS}
        if not keys["media_key"]:  # Medienschlüssel je Installation, von Darkfluenzer angelegt
            key = base64.b64encode(os.urandom(32)).decode()
            if store_secret(self._service("media_key"), key):
                keys["media_key"] = key
        return keys

    def _key(self, name: str) -> str:
        if not self._keys.get(name):
            value = secret(self._service(name)) or ""
            if value:
                self._keys[name] = value
        return self._keys.get(name, "")

    def _save_token(self, token: str, expiry: int) -> bool:
        stamp = str(expiry) if expiry else ""
        ok = store_secret(self.ig.token_service, token) and store_secret(
            self.ig.token_expiry_service, stamp
        )
        if ok:
            self._keys["token"], self._keys["token_expiry"] = token, stamp
        return ok

    # ------------------------------------------------------------------ Start und Anmeldung

    async def run(self) -> None:
        """Schlüsselbund, Token (Erneuerung vor Ablauf) und Konto regelmäßig prüfen."""
        try:
            while True:
                try:
                    await self._check()
                except Exception:  # eine fehlerhafte Prüfung beendet den Kanal nie
                    log.exception("Instagram: Prüfung fehlgeschlagen")
                await asyncio.sleep(self.ig.check_s)
        finally:
            await self.http.close()

    async def _check(self) -> None:
        self._keys = await asyncio.to_thread(self._load_keys)
        missing = [] if self.ig.public_base_url else ["public_base_url"]
        missing += [n for n in ("app_id", "app_secret", "verify_token") if not self._keys[n]]
        if not self._keys["media_key"]:
            missing.append("media_key")
        if missing:
            self._set("OFF", missing=f"Meta-App und Tunnel einrichten ({', '.join(missing)})")
            return
        token = self._keys["token"]
        expiry = _int(self._keys["token_expiry"])
        if not token:
            self._set("OFF", missing="Instagram-Anmeldung fehlt", login=True)
            return
        if expiry and expiry <= time.time():
            self._set("OFF", missing="Instagram-Anmeldung abgelaufen – neu anmelden", login=True)
            return
        if expiry and expiry - time.time() < self.ig.token_refresh_margin_s:
            await self._refresh(token)
            token = self._keys["token"]
        if not (self.account and self._subscribed):
            if self.state != "READY":
                self._set("CONNECTING")
            try:
                await self._identify(token)
                await self._subscribe(token)
            except GraphError as exc:
                if exc.code == 190:
                    self._set(
                        "OFF", missing="Instagram-Anmeldung ungültig – neu anmelden", login=True
                    )
                else:
                    self._set("ERROR", error=f"Instagram: {exc}")
                return
            except HttpError as exc:
                self._set("ERROR", error=f"Instagram: {exc}")
                return
            log.info("Instagram angemeldet als Konto %s", self.account)
        if self.state != "READY":
            self._set("READY")
            self.wake.set()
            await self._resume_pending()

    async def _identify(self, token: str) -> None:
        me = await self.http.json(
            "GET", self._graph("me"), params={"fields": "user_id,username"}, token=token
        )
        account = str(me.get("user_id") or me.get("id") or "")
        if not account:
            raise HttpError("Konto-ID fehlt in /me", maybe_sent=False)
        self.account, self.username = account, str(me.get("username") or "")

    async def _subscribe(self, token: str) -> None:
        """Webhook-Felder für Claras Konto abonnieren (idempotent)."""
        answer = await self.http.json(
            "POST",
            self._graph("me/subscribed_apps"),
            params={"subscribed_fields": ",".join(self.ig.subscribed_fields)},
            token=token,
        )
        if not answer.get("success"):
            raise HttpError("Webhook-Abo abgelehnt", maybe_sent=False)
        self._subscribed = True

    async def _refresh(self, token: str) -> None:
        """Langzeit-Token vor Ablauf erneuern (nach Fehlschlag erst nach ``retry``)."""
        if time.time() < self._refresh_after:
            return
        try:
            answer = await self.http.json(
                "GET",
                f"{self.ig.graph_url}/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": token},
            )
            new, expires = str(answer["access_token"]), int(answer["expires_in"])
        except (HttpError, KeyError, ValueError, TypeError) as exc:
            self._refresh_after = time.time() + self.ig.token_refresh_retry_s
            log.warning("Instagram: Token-Erneuerung fehlgeschlagen (%s)", _reason(exc))
            return
        if not await asyncio.to_thread(self._save_token, new, int(time.time()) + expires):
            self._refresh_after = time.time() + self.ig.token_refresh_retry_s
            log.warning("Instagram: erneuertes Token nicht im Schlüsselbund ablegbar")
            return
        log.info("Instagram: Token erneuert (gültig %d Tage)", expires // 86400)

    def authorize_url(self) -> str:
        """Anmeldeadresse (Instagram-Login) mit neuem, einmaligem ``state``."""
        app_id = self._key("app_id")
        if not app_id or not self.ig.public_base_url:
            raise InstagramError("Meta-App und Tunnel einrichten (app_id, public_base_url).")
        self._prune_states()
        state = secrets.token_urlsafe(32)
        self._states[state] = time.monotonic() + self.ig.oauth_state_ttl_s
        query = urlencode(
            {
                "client_id": app_id,
                "redirect_uri": self.ig.redirect_uri,
                "response_type": "code",
                "scope": ",".join(self.ig.scopes),
                "state": state,
            }
        )
        return f"{self.ig.oauth_authorize_url}?{query}"

    def _prune_states(self) -> None:
        now = time.monotonic()
        self._states = {s: exp for s, exp in self._states.items() if exp > now}

    async def oauth_callback(self, params: Mapping[str, str]) -> tuple[int, str]:
        """OAuth-Rückruf: ``state`` prüfen (einmalig), Code -> Kurzzeit- -> Langzeit-Token,
        Token und Ablauf in den Schlüsselbund, Konto bestimmen. Liefert (HTTP-Status, Text)."""
        self._prune_states()
        state = str(params.get("state") or "")
        if not state or self._states.pop(state, None) is None:
            log.warning("Instagram-OAuth: unbekannter oder abgelaufener state abgewiesen")
            return 403, "Anmeldung abgewiesen: ungültiger oder abgelaufener Anmeldevorgang."
        if params.get("error"):
            reason = str(params.get("error_description") or params.get("error"))[:200]
            return 400, f"Instagram-Anmeldung abgebrochen: {reason}"
        code = str(params.get("code") or "").removesuffix("#_")
        if not code:
            return 400, "Instagram hat keinen Anmeldecode geliefert."
        app_id, app_secret = self._key("app_id"), self._key("app_secret")
        if not app_id or not app_secret:
            return 503, "Meta-App einrichten (app_id, app_secret im Schlüsselbund)."
        try:
            short = await self.http.json(
                "POST",
                self.ig.oauth_token_url,
                data={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.ig.redirect_uri,
                    "code": code,
                },
            )
            first = short["data"][0] if isinstance(short.get("data"), list) else short
            long = await self.http.json(
                "GET",
                f"{self.ig.graph_url}/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": app_secret,
                    "access_token": str(first["access_token"]),
                },
            )
            token, expires = str(long["access_token"]), int(long["expires_in"])
        except (HttpError, KeyError, IndexError, ValueError, TypeError) as exc:
            log.warning("Instagram-OAuth: Tokentausch fehlgeschlagen (%s)", _reason(exc))
            return 502, f"Instagram-Anmeldung fehlgeschlagen: {_reason(exc)}"
        if not await asyncio.to_thread(self._save_token, token, int(time.time()) + expires):
            return 500, "Token nicht im Schlüsselbund ablegbar."
        self.account, self.username, self._subscribed = "", "", False
        self._set("CONNECTING")
        await self._check()
        if self.state != "READY":
            return (
                502,
                f"Token gespeichert, Instagram aber nicht bereit: {self.error or self.missing}",
            )
        return 200, f"Instagram verbunden ({self.status()['account']}). Fenster schließen."

    async def logout(self) -> str:
        """Token vergessen (Schlüsselbund); erneut anmelden über ``authorize_url``."""
        if not self._key("token"):
            return "Nicht angemeldet."
        if not await asyncio.to_thread(self._save_token, "", 0):
            return "Abmelden fehlgeschlagen (Schlüsselbund)."
        self.account, self.username, self._subscribed = "", "", False
        self._set("OFF", missing="Instagram-Anmeldung fehlt", login=True)
        return ""

    def _graph(self, path: str) -> str:
        return f"{self.ig.graph_url}/{self.ig.graph_version}/{path}"

    # ------------------------------------------------------------------ Webhook

    async def verify(self, params: Mapping[str, str]) -> tuple[int, str]:
        """Webhook-Abonnement (GET): ``hub.mode`` = subscribe und Verify-Token aus dem
        Schlüsselbund (im Arbeiter-Thread, FABLE-007) -> ``hub.challenge``."""
        expected = self._keys.get("verify_token") or await asyncio.to_thread(
            self._key, "verify_token"
        )
        given = str(params.get("hub.verify_token") or "")
        challenge = str(params.get("hub.challenge") or "")
        if (
            params.get("hub.mode") == "subscribe"
            and expected
            and challenge
            and hmac.compare_digest(given.encode(), expected.encode())
        ):
            return 200, challenge
        log.warning("Instagram-Webhook: Abonnement mit falschem Verify-Token abgewiesen")
        return 403, "Verify-Token ungültig"

    async def handle_webhook(self, raw_body: bytes, signature_header: str) -> int:
        """Webhook-Zustellung (POST): Signatur über die unveränderten Bytes, dann jedes Ereignis
        speichern; erst danach 200. 403 Signatur, 400 kein JSON, 503 Konto noch unbekannt,
        500 Speichern fehlgeschlagen (Meta stellt erneut zu, Duplikate wirken nicht)."""
        app_secret = self._keys.get("app_secret") or await asyncio.to_thread(
            self._key, "app_secret"
        )
        if not signature_ok(app_secret, raw_body, signature_header):
            log.warning("Instagram-Webhook: Signatur fehlt oder ist ungültig – abgewiesen")
            return 403
        try:
            data = json.loads(raw_body)
        except ValueError:
            return 400
        if not isinstance(data, dict) or data.get("object") != "instagram":
            return 200  # anderes Objekt: quittieren, nichts speichern
        if not self.account:
            return 503
        try:
            for entry in data.get("entry") or []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("id", "")) != self.account:
                    log.warning("Instagram-Webhook für fremdes Konto %s ignoriert", entry.get("id"))
                    continue
                for event in entry.get("messaging") or []:
                    if isinstance(event, dict):
                        await self._event(event)
        except Exception:
            log.exception("Instagram-Webhook nicht vollständig gespeichert")
            return 500
        return 200

    async def _event(self, event: dict) -> None:
        sender = str((event.get("sender") or {}).get("id", ""))
        recipient = str((event.get("recipient") or {}).get("id", ""))
        at_ms = _int(event.get("timestamp")) or int(time.time() * 1000)
        self.last_event_ms = int(time.time() * 1000)
        msg, postback, read = event.get("message"), event.get("postback"), event.get("read")
        if isinstance(msg, dict):
            if msg.get("is_echo") or sender == self.account:
                if recipient and recipient != self.account:
                    await self._echo(recipient, msg, at_ms)
            elif sender and not msg.get("is_deleted"):
                await self._inbound(sender, msg, at_ms)
        elif isinstance(postback, dict) and sender and sender != self.account:
            mid = str(postback.get("mid") or f"{sender}:{at_ms}")
            text = str(postback.get("title") or postback.get("payload") or "")
            await self._inbound(sender, {"mid": mid, "text": text}, at_ms, event=f"postback:{mid}")
        elif isinstance(read, dict) and sender and sender != self.account:
            key = f"{READ}{sender}"
            if at_ms > _int(self.store.adapter_get(PLATFORM, self.account, key)):
                self.store.adapter_set(PLATFORM, self.account, key, str(at_ms))

    async def _inbound(self, sender: str, msg: dict, at_ms: int, *, event: str = "") -> None:
        mid = str(msg.get("mid") or "")
        if not mid:
            return
        reply = msg.get("reply_to") if isinstance(msg.get("reply_to"), dict) else {}
        attachments = [
            attachment_of(a) for a in msg.get("attachments") or [] if isinstance(a, dict)
        ]
        if isinstance(reply.get("story"), dict):  # Antwort auf eine Story: Story mitsichern
            attachments.append(attachment_of({"type": "story_reply", "payload": reply["story"]}))
        if msg.get("is_unsupported"):
            attachments.append(
                {
                    "kind": "other",
                    "size": 0,
                    "mime": "",
                    "status": "not_importable",
                    "note": "von Instagram nicht unterstützt",
                }
            )
        handle, name = await self._profile(sender)
        inbound = self.store.record_inbound(
            PLATFORM,
            self.account,
            event or mid,
            sender_id=sender,
            conversation_id=sender,
            platform_message_id=mid,
            text=str(msg.get("text") or ""),
            sent_at=_iso(at_ms),
            handle=handle,
            display_name=name,
            reply_to=str(reply["mid"]) if reply.get("mid") else None,
            attachments=attachments,
        )
        self._open_window(sender, at_ms)
        if inbound.message_id is not None:  # sonst bereits gespeichert (erneut zugestellt)
            self._schedule(sender, inbound.message_id, inbound)

    async def _echo(self, partner: str, msg: dict, at_ms: int) -> None:
        """Von Claras Konto gesendete Nachricht: eigene (Postausgang) über die gemerkte mid, sonst
        vom Handy -> Übergabe an den Betreiber."""
        mid = str(msg.get("mid") or "")
        if not mid or self._is_own(partner, mid):
            return
        flight = self._inflight.get(partner)
        if flight is not None:  # Echo kann vor der Antwort auf den eigenen Sendeaufruf kommen
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(flight.wait(), self.cfg.server.timeout_s * 2)
            if self._is_own(partner, mid):
                return
        text = str(msg.get("text") or "")
        if (item := self._confirm_unknown(partner, text)) is not None:
            self._remember_own(partner, mid)  # Sendung mit unbekanntem Ergebnis kam doch an
            self._finish(item, "sent", platform_message_id=mid)
            return
        attachments = [
            attachment_of(a) for a in msg.get("attachments") or [] if isinstance(a, dict)
        ]
        conv, message_id = self.store.record_external_outgoing(
            PLATFORM, self.account, partner, mid, text, _iso(at_ms), attachments=attachments
        )
        if message_id is None:
            return
        self.store.add_system_card(
            conv, f"{HANDOFF_CARD}\nNachricht direkt in der Instagram-App gesendet."
        )
        self.on_change_message(message_id)
        if any(a["status"] == "pending" for a in attachments):
            self._schedule(partner, message_id, None)

    async def _profile(self, partner: str) -> tuple[str | None, str | None]:
        """Benutzername und Name eines Absenders, einmal abgefragt (kurze Zeitgrenze)."""
        cached = self.store.adapter_get(PLATFORM, self.account, f"{USER}{partner}")
        if cached is None and self._keys.get("token"):
            try:
                user = await self.http.json(
                    "GET",
                    self._graph(partner),
                    params={"fields": "name,username"},
                    token=self._keys["token"],
                    timeout_s=self.ig.profile_timeout_s,
                )
            except HttpError as exc:
                log.info("Instagram: Profil nicht abrufbar (%s)", exc)
                return None, None
            cached = f"{user.get('username') or ''}\x1f{user.get('name') or ''}"
            self.store.adapter_set(PLATFORM, self.account, f"{USER}{partner}", cached)
        handle, _, name = (cached or "").partition("\x1f")
        return handle or None, name or None

    # ------------------------------------------------------------------ Anhänge sichern

    def _schedule(self, partner: str, message_id: int, inbound: Inbound | None) -> None:
        """Anhänge sichern und Eingang melden – je Konversation in Eingangsreihenfolge."""
        if message_id in self._scheduled:
            return
        self._scheduled.add(message_id)
        ids = self._ids(PENDING)
        if message_id not in ids:
            self._set_ids(PENDING, [*ids, message_id])
        previous = self._chains.get(partner)

        async def job() -> None:
            if previous is not None:
                with contextlib.suppress(Exception):
                    await previous
            await self._guard(self._complete(message_id, inbound))

        task = asyncio.create_task(job())
        self._chains[partner] = task
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._done(partner, t))

    def _done(self, partner: str, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if self._chains.get(partner) is task:
            del self._chains[partner]

    async def drain(self) -> None:
        """Warten, bis alle laufenden Sicherungen und Eingangsmeldungen fertig sind."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _guard(self, job: Awaitable[None]) -> None:
        try:
            await job
        except Exception:  # eine fehlerhafte Nachricht stoppt den Eingang nicht
            log.exception("Instagram: Nachricht nicht verarbeitet")

    async def _resume_pending(self) -> None:
        """Nach Neustart: unterbrochene Sicherungen fortsetzen (CDN-Adresse evtl. abgelaufen)."""
        for message_id in self._ids(PENDING):
            try:
                partner = str(self.store.message(message_id)["platform_conversation_id"])
            except StoreError:
                self._drop_id(PENDING, message_id)
                continue
            self._schedule(partner, message_id, None)

    async def _complete(self, message_id: int, inbound: Inbound | None) -> None:
        try:
            msg = self.store.message(message_id)
        except StoreError:
            self._drop_id(PENDING, message_id)
            return
        partner = str(msg["platform_conversation_id"])
        atts = msg["attachments"]
        if any(a.get("status") == "pending" for a in atts):
            mid = str(msg["platform_message_id"] or message_id)
            saved = [
                await self._save(partner, mid, i, a) if a.get("status") == "pending" else a
                for i, a in enumerate(atts)
            ]
            self.store.set_attachments(message_id, saved)
            if msg["direction"] != "in":
                self.on_change_message(message_id)
        self._drop_id(PENDING, message_id)
        self._scheduled.discard(message_id)
        if msg["direction"] != "in":
            return
        if inbound is None:  # fortgesetzt nach Neustart
            customer, identity, _ = self.store.customer_for_identity(
                PLATFORM, self.account, partner
            )
            inbound = Inbound(customer, identity, msg["conversation_id"], message_id, False)
        await self.on_inbound(inbound)

    async def _save(self, partner: str, mid: str, index: int, att: dict) -> dict:
        """CDN-Datei nach local/channels/instagram/<konversation>/ laden, Hash festhalten."""
        url = str(att.get("source") or "")
        base = {k: v for k, v in att.items() if k != "source"}
        note = str(base.get("note") or "")
        folder = self.cfg.local / "channels" / PLATFORM / _safe(partner)
        stem = f"{hashlib.sha256(mid.encode()).hexdigest()[:16]}_{index}"
        part = folder / f"{stem}.part"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            ctype = await self.http.download(
                url, part, int(self.ig.max_download_mb * MB), self.ig.download_timeout_s
            )
        except TooLarge:
            part.unlink(missing_ok=True)
            return base | {"status": "too_large", "note": f"über {self.ig.max_download_mb:g} MB"}
        except HttpError as exc:
            part.unlink(missing_ok=True)
            return base | {"status": "failed", "note": str(exc)[:200]}
        ctype = ctype.split(";")[0].strip().lower()
        kind = str(base.get("ig_type") or "")
        if not (ctype.startswith(_MEDIA) or (kind == "file" and ctype != "text/html")):
            part.unlink(missing_ok=True)
            return base | {
                "status": "not_importable",
                "note": _join(note, "kein abrufbares Medium"),
            }
        size = part.stat().st_size
        if size == 0:
            part.unlink(missing_ok=True)
            return base | {"status": "failed", "note": _join(note, "leere Datei")}
        target = folder / f"{stem}{_suffix(ctype, url)}"
        part.replace(target)
        if kind in _STORY:
            base["kind"] = {"image": "photo", "video": "video"}.get(ctype.split("/")[0], "other")
        return base | {
            "mime": ctype,
            "status": "saved",
            "path": target.relative_to(self.cfg.local).as_posix(),
            "sha256": await asyncio.to_thread(sha256_file, target),
            "size": size,
        }

    # ------------------------------------------------------------------ Antwortfenster

    def _open_window(self, partner: str, at_ms: int) -> None:
        key = f"{WINDOW}{partner}"
        if at_ms > _int(self.store.adapter_get(PLATFORM, self.account, key)):
            self.store.adapter_set(PLATFORM, self.account, key, str(at_ms))

    def window_remaining_ms(self, conversation: str, *, human_agent: bool = False) -> int:
        """Restzeit des Antwortfensters (0 = abgelaufen); ``human_agent``: verlängertes Fenster
        für manuelle Antworten mit Human-Agent-Kennzeichnung."""
        if not self.account:
            return 0
        last = _int(self.store.adapter_get(PLATFORM, self.account, f"{WINDOW}{conversation}"))
        if not last:
            return 0
        hours = self.ig.human_agent_window_h if human_agent else self.ig.reply_window_h
        return max(0, int(last + hours * 3_600_000 - time.time() * 1000))

    def window_open(self, conversation: str) -> bool:
        return self.window_remaining_ms(conversation) > 0

    def last_read_ms(self, conversation: str) -> int:
        """Letzte Lesebestätigung des Kunden (read-Ereignis), 0 = keine."""
        if not self.account:
            return 0
        return _int(self.store.adapter_get(PLATFORM, self.account, f"{READ}{conversation}"))

    def send_check(self, conversation: str, *, human_agent: bool = False) -> str:
        """Leer, wenn an diese Konversation gesendet werden darf, sonst der Grund."""
        if self.window_open(conversation):
            return ""
        if not human_agent:
            return (
                f"Instagram-Antwortfenster ({self.ig.reply_window_h:g} h) abgelaufen – nur "
                "manuelle Antwort mit Human-Agent-Kennzeichnung."
            )
        if self.window_remaining_ms(conversation, human_agent=True) > 0:
            return ""
        return (
            "Instagram-Antwortfenster abgelaufen – auch mit Human-Agent-Kennzeichnung nur "
            f"{self.ig.human_agent_window_h / 24:g} Tage nach der letzten Kundennachricht."
        )

    def mark_human_agent(self, message_id: int) -> None:
        """Manuelle Betreiberantwort im Postausgang als Human-Agent kennzeichnen (vor wake)."""
        if self.account and message_id not in (ids := self._ids(HUMAN)):
            self._set_ids(HUMAN, [*ids, message_id])

    # ------------------------------------------------------------------ Ausgang

    async def outbox_worker(self) -> None:
        """Postausgang abarbeiten, wenn Arbeit da ist und das Konto bereit ist."""
        while True:
            await self.wake.wait()
            self.wake.clear()
            for item in self.store.outbox(PLATFORM, self.account) if self.state == "READY" else []:
                if self.state != "READY":
                    break
                await self._send(item)
                if self.task_error:  # Postausgang läuft wieder: Meldung der Aufsicht erledigt
                    self.task_error = ""
                    self.on_change()

    async def _send(self, item: dict) -> None:
        message_id = int(item["id"])
        partner = str(item["platform_conversation_id"])
        # Zustellung an Kunden: Gate im Versandmoment frisch prüfen (approval.py, V0 §8.4 Punkt 9)
        if item.get("delivery_id") and (reason := await self.gate(item)):
            self._finish(message_id, "failed", error=reason)
            return
        human = message_id in self._ids(HUMAN)
        plan = self.send_check(partner, human_agent=human) or self._parts(item)
        if isinstance(plan, str):
            self._drop_id(HUMAN, message_id)
            self._finish(message_id, "failed", error=plan)
            return
        self.store.set_message_status(message_id, "sending")
        self.on_change_message(message_id)
        tag = (
            {"messaging_type": "MESSAGE_TAG", "tag": "HUMAN_AGENT"}
            if human and not self.window_open(partner)
            else {}
        )
        mid = ""
        for n, message in enumerate(plan):
            await self._pace()
            try:
                mid = await self._post(
                    partner, {"recipient": {"id": partner}, "message": message, **tag}
                )
            except HttpError as exc:
                after = f" (nach {n} von {len(plan)} Teilen)" if n else ""
                self._drop_id(HUMAN, message_id)
                self._finish(
                    message_id,
                    "unknown" if exc.maybe_sent else "failed",
                    error=f"Instagram: {exc}{after}",
                )
                return
        self._drop_id(HUMAN, message_id)
        self._finish(message_id, "sent", platform_message_id=mid or None)

    def _parts(self, item: dict) -> list[dict] | str:
        """Text und Anhänge als einzelne Instagram-Nachrichten (Anhänge über signierte URL);
        alle Grenzen werden vor dem ersten Aufruf geprüft."""
        parts: list[dict] = []
        text = str(item["text"] or "")
        if text.strip():
            size = len(text.encode())
            if size > self.ig.max_text_bytes:
                return (
                    f"Text zu lang für Instagram ({size} Bytes, Grenze {self.ig.max_text_bytes})."
                )
            parts.append({"text": text})
        limits = {
            "image": self.ig.max_image_mb,
            "video": self.ig.max_video_mb,
            "audio": self.ig.max_audio_mb,
        }
        for att in item["attachments"]:
            rel = str(att.get("path") or "")
            if not rel:
                continue
            mime = mimetypes.guess_type(rel)[0] or ""
            kind = (
                "image"
                if mime in _SEND_IMAGE
                else next((k for k in ("video", "audio") if mime.startswith(f"{k}/")), "")
            )
            if not kind:
                return f"Dateityp für Instagram nicht unterstützt ({PurePosixPath(rel).suffix})."
            path = self.cfg.local / rel
            if not path.is_file():
                return f"Datei fehlt: {rel}"
            size_mb = path.stat().st_size / MB
            if size_mb > limits[kind]:
                return f"Zu groß für Instagram ({size_mb:.1f} MB, Grenze {limits[kind]:g} MB)."
            try:
                url = self.sign_media_url(rel)
            except InstagramError as exc:
                return str(exc)
            parts.append({"attachment": {"type": kind, "payload": {"url": url}}})
        return parts or "Leere Nachricht."

    async def _post(self, partner: str, body: dict) -> str:
        flight = asyncio.Event()
        self._inflight[partner] = flight
        try:
            answer = await self.http.json(
                "POST", self._graph(f"{self.account}/messages"), body=body, token=self._key("token")
            )
            mid = str(answer.get("message_id") or "")
            if mid:
                self._remember_own(partner, mid)  # vor dem Freigeben wartender Echos
            self._sent_at.append(time.time())
            return mid
        finally:
            flight.set()
            if self._inflight.get(partner) is flight:
                del self._inflight[partner]

    async def _pace(self) -> None:
        """Höchstzahl Nachrichten je Minute (Meta-Ratenbegrenzung)."""
        while len(self._sent_at) >= self.ig.max_messages_per_minute:
            wait = self._sent_at[0] + 60 - time.time()
            if wait <= 0:
                self._sent_at.popleft()
                continue
            await asyncio.sleep(wait)

    def _finish(
        self,
        message_id: int,
        status: str,
        *,
        platform_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            self.store.set_message_status(
                message_id, status, platform_message_id=platform_message_id, error=error
            )
        except sqlite3.IntegrityError:  # mid schon als Handy-Echo gespeichert (Wettlauf)
            self.store.set_message_status(message_id, status, error=error)
        self.on_change_message(message_id)

    def _own(self, partner: str) -> list[str]:
        return (self.store.adapter_get(PLATFORM, self.account, f"{OWN}{partner}") or "").split()

    def _is_own(self, partner: str, mid: str) -> bool:
        return mid in self._own(partner)

    def _remember_own(self, partner: str, mid: str) -> None:
        kept = [*self._own(partner), mid][-OWN_KEPT:]
        self.store.adapter_set(PLATFORM, self.account, f"{OWN}{partner}", " ".join(kept))

    def _confirm_unknown(self, partner: str, text: str) -> int | None:
        """Echo mit gleichem Text bestätigt eine Sendung, deren Ergebnis unbekannt war; die offene
        Liste sind die Nachrichten im Status ``unknown`` in SQLite (übersteht den Neustart,
        SP2 Schritt 6)."""
        return self.store.match_unknown(PLATFORM, self.account, partner, text)

    def _ids(self, key: str) -> list[int]:
        raw = self.store.adapter_get(PLATFORM, self.account, key) or ""
        return [int(v) for v in raw.split() if v.isdigit()]

    def _set_ids(self, key: str, ids: list[int]) -> None:
        self.store.adapter_set(PLATFORM, self.account, key, " ".join(map(str, ids)))

    def _drop_id(self, key: str, message_id: int) -> None:
        ids = self._ids(key)
        if message_id in ids:
            self._set_ids(key, [i for i in ids if i != message_id])

    # ------------------------------------------------------------------ Ausgehende Medien

    def _media_key(self) -> str:
        key = self._key("media_key")
        if not key:
            key = base64.b64encode(os.urandom(32)).decode()
            if not store_secret(self.ig.media_key_service, key):
                raise InstagramError("Medienschlüssel nicht im Schlüsselbund ablegbar.")
            self._keys["media_key"] = key
        return key

    def sign_media_url(self, rel_path: str) -> str:
        """Kurzlebige öffentliche Adresse einer Datei unter local/ für den Abruf durch Meta."""
        rel = _clean_rel(rel_path)
        if rel is None:
            raise InstagramError("Ungültiger Medienpfad.")
        if not self.ig.public_base_url:
            raise InstagramError("Tunnel-Adresse fehlt (instagram.public_base_url).")
        exp = int(time.time() + self.ig.media_url_ttl_s)
        token = f"{exp}.{_mac(self._media_key(), rel, exp)}"
        return (
            f"{self.ig.public_base_url}{self.ig.media_path}/{quote(rel)}"
            f"?{MEDIA_TOKEN_PARAM}={token}"
        )

    def check_media_token(self, path: str, token: str) -> bool:
        """Medien-Token des öffentlichen Abrufs: Pfad passt, nicht abgelaufen, Signatur echt."""
        rel = _clean_rel(path)
        exp, _, mac = str(token or "").partition(".")
        key = self._key("media_key")
        if rel is None or not exp.isdigit() or not mac or not key or int(exp) < time.time():
            return False
        return hmac.compare_digest(mac.encode(), _mac(key, rel, int(exp)).encode())

    # Server setzt diesen Rückruf (Push des geänderten Nachrichtenstatus)
    on_change_message: Callable[[int], None] = staticmethod(lambda _id: None)  # type: ignore[assignment]
    # Server setzt die Versandprüfung für Zustellungen (leer = senden, sonst der Sperrgrund)
    gate: Callable[[dict], str] = staticmethod(lambda _item: "Keine Versandprüfung.")  # type: ignore[assignment]


def _mac(key: str, rel: str, exp: int) -> str:
    digest = hmac.new(key.encode(), f"{rel}\n{exp}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _clean_rel(path: str) -> str | None:
    """Relativer Pfad unter local/ ohne Ausbruch (kein absoluter Pfad, kein ``..``)."""
    if not path or "\\" in path or "\x00" in path:
        return None
    p = PurePosixPath(path)
    if p.is_absolute() or any(part in ("..", ".", "") for part in path.split("/")):
        return None
    return p.as_posix()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64] or "unbekannt"


def _suffix(ctype: str, url: str) -> str:
    ext = (mimetypes.guess_extension(ctype) if ctype else None) or PurePosixPath(
        urlsplit(url).path
    ).suffix.lower()
    return ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext or "") else ".bin"


def _join(*notes: str) -> str:
    return " · ".join(n for n in notes if n)[:200]


def _int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds")


def _reason(exc: Exception) -> str:
    """Fehlertext ohne Adressen oder Werte (nie Token/Geheimnisse)."""
    return str(exc)[:200] if isinstance(exc, HttpError) else type(exc).__name__
