"""Telegram-Adapter (PHASENPLAN_V0 §6, C2): Bot der Influencerin über die Bot-API.

Eingang per Long-Polling (``getUpdates``): jedes Update wird vor dem Weiterschalten des Offsets
dauerhaft gespeichert (Ereignis genau einmal, Kundenakte, Konversation, Nachricht); Anhänge bis zur
konfigurierten Grenze sofort gesichert, größere sichtbar als „zu groß“. Ausgang über den
Postausgang: Status „sendet“ vor dem API-Aufruf, danach „gesendet“ mit Plattform-ID oder
„fehlgeschlagen“; eine Zeitüberschreitung nach möglicher Annahme bleibt „unbekannt“ (kein blindes
Wiederholen). Der Bot-Token stammt ausschließlich aus dem Schlüsselbund.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

from ..config import Config
from ..keychain import secret
from ..store import Inbound, Store

log = logging.getLogger("darkfluenzer.telegram")

PLATFORM = "telegram"
# Telegram-Nachrichtenfelder mit Datei -> Anhangart
_FILE_KINDS = {
    "video": "video",
    "document": "document",
    "voice": "voice",
    "audio": "audio",
    "video_note": "video",
    "animation": "video",
    "sticker": "sticker",
}


class TelegramError(Exception):
    """Antwort der Bot-API mit ok=false (endgültig) oder Transportfehler."""

    def __init__(self, message: str, *, definite: bool) -> None:
        super().__init__(message)
        self.definite = definite  # True: Telegram hat sicher nicht angenommen


class TelegramAdapter:
    """Ein Bot (Konto der Influencerin). ``account`` ist die unveränderliche Bot-ID."""

    def __init__(
        self,
        cfg: Config,
        store: Store,
        on_inbound: Callable[[Inbound], Awaitable[None]],
        on_change: Callable[[], None],
    ) -> None:
        assert cfg.telegram is not None
        self.cfg = cfg
        self.tg = cfg.telegram
        self.store = store
        self.on_inbound = on_inbound
        self.on_change = on_change
        self.account = ""  # Bot-ID nach getMe
        self.username = ""
        self.state = "OFF"
        self.error = ""
        self.missing = ""
        self.last_event_ms = 0
        self.wake = asyncio.Event()  # Postausgang hat Arbeit
        self._token = ""
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------ Zustand

    def status(self) -> dict:
        return {
            "platform": PLATFORM,
            "account": f"@{self.username}" if self.username else "",
            "state": self.state,
            "error": self.error,
            "last_event_ms": self.last_event_ms,
            "missing": self.missing,
        }

    def _set(self, state: str, error: str = "", missing: str = "") -> None:
        if (state, error, missing) != (self.state, self.error, self.missing):
            self.state, self.error, self.missing = state, error, missing
            self.on_change()

    # ------------------------------------------------------------------ Bot-API

    async def _call(self, method: str, timeout: float, **params: object) -> object:
        assert self._session is not None
        url = f"{self.tg.api_base}/bot{self._token}/{method}"
        try:
            async with self._session.post(
                url, json=params, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                body = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise TelegramError(f"{method}: {type(exc).__name__}", definite=False) from exc
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'Fehler')}", definite=True)
        return body["result"]

    async def _upload(self, method: str, field: str, path: Path, **params: object) -> dict:
        """Datei per Multipart senden (keine öffentliche URL nötig)."""
        assert self._session is not None
        form = aiohttp.FormData()
        for key, value in params.items():
            if value is not None:
                form.add_field(key, str(value))
        form.add_field(field, path.read_bytes(), filename=path.name)
        url = f"{self.tg.api_base}/bot{self._token}/{method}"
        try:
            async with self._session.post(
                url, data=form, timeout=aiohttp.ClientTimeout(total=self.tg.send_timeout_s)
            ) as resp:
                body = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise TelegramError(f"{method}: {type(exc).__name__}", definite=False) from exc
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'Fehler')}", definite=True)
        return body["result"]

    # ------------------------------------------------------------------ Eingang

    async def run(self) -> None:
        """Verbinden, dann Long-Polling; fehlender Token wird sichtbar gemeldet und regelmäßig
        neu geprüft (Ablage im Schlüsselbund ohne Neustart)."""
        async with aiohttp.ClientSession() as session:
            self._session = session
            while True:
                token = await asyncio.to_thread(secret, self.tg.keychain_service)
                if not token:
                    self._set(
                        "OFF", missing=f"Bot-Token im Schlüsselbund ({self.tg.keychain_service})"
                    )
                    await asyncio.sleep(self.cfg.server.observe_s * 15)
                    continue
                self._token = token
                try:
                    self._set("CONNECTING")
                    me = await self._call("getMe", self.cfg.server.timeout_s)
                    self.account, self.username = str(me["id"]), str(me.get("username", ""))
                    self._set("READY")
                    self.wake.set()  # liegengebliebenen Postausgang anstoßen
                    await self._poll()
                except TelegramError as exc:
                    self._set("ERROR", error=str(exc))
                    log.warning("Telegram: %s", exc)
                    await asyncio.sleep(self.cfg.server.observe_s * 5)

    async def _poll(self) -> None:
        while True:
            offset = int(self.store.adapter_get(PLATFORM, self.account, "offset") or 0)
            updates = await self._call(
                "getUpdates",
                self.tg.poll_timeout_s + self.cfg.server.timeout_s,
                offset=offset + 1 if offset else 0,
                timeout=int(self.tg.poll_timeout_s),
                allowed_updates=["message"],
            )
            for update in updates:  # type: ignore[union-attr]
                await self._handle(update)
                # erst nach dem dauerhaften Speichern weiterschalten (Wiederanlauf ohne Verlust)
                self.store.adapter_set(PLATFORM, self.account, "offset", str(update["update_id"]))
            if self.state != "READY":
                self._set("READY")

    async def _handle(self, update: dict) -> None:
        msg = update.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            return  # nur Einzelchats mit dem Bot
        sender = msg.get("from") or {}
        name = " ".join(filter(None, (sender.get("first_name"), sender.get("last_name"))))
        reply = msg.get("reply_to_message") or {}
        files = _files(msg)
        inbound = self.store.record_inbound(
            PLATFORM,
            self.account,
            str(update["update_id"]),
            sender_id=str(sender.get("id")),
            conversation_id=str(msg["chat"]["id"]),
            platform_message_id=str(msg["message_id"]),
            text=msg.get("text") or msg.get("caption") or "",
            sent_at=datetime.fromtimestamp(msg["date"], UTC).isoformat(timespec="seconds"),
            handle=sender.get("username"),
            display_name=name or None,
            reply_to=str(reply["message_id"]) if reply.get("message_id") else None,
            attachments=[{k: v for k, v in f.items() if k != "file_id"} for f in files],
        )
        self.last_event_ms = int(time.time() * 1000)
        if inbound.message_id is None:
            return  # bereits gespeichert (erneut zugestellt)
        if files:
            saved = [await self._save(inbound, msg, i, f) for i, f in enumerate(files)]
            self.store.set_attachments(inbound.message_id, saved)
        await self.on_inbound(inbound)

    async def _save(self, inbound: Inbound, msg: dict, index: int, f: dict) -> dict:
        """Anhang sichern: Telegram-Datei bis zur Grenze laden, Inhalts-Hash festhalten."""
        att = {k: v for k, v in f.items() if k != "file_id"}
        limit = int(self.tg.max_download_mb * 1024 * 1024)
        if f.get("size", 0) > limit:
            return att | {
                "status": "too_large",
                "note": f"über {self.tg.max_download_mb:.0f} MB (Bot-API-Grenze)",
            }
        try:
            info = await self._call("getFile", self.cfg.server.timeout_s, file_id=f["file_id"])
            url = f"{self.tg.api_base}/file/bot{self._token}/{info['file_path']}"  # type: ignore[index]
            assert self._session is not None
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=self.tg.send_timeout_s)
            ) as resp:
                resp.raise_for_status()
                data = await resp.read()
        except (TelegramError, TimeoutError, aiohttp.ClientError) as exc:
            return att | {"status": "failed", "note": str(exc)[:200]}
        suffix = (
            Path(str(info.get("file_path", ""))).suffix
            or mimetypes.guess_extension(  # type: ignore[union-attr]
                f.get("mime", "")
            )
            or ".bin"
        )
        rel = (
            Path("channels")
            / PLATFORM
            / str(msg["chat"]["id"])
            / (f"{msg['message_id']}_{index}{suffix}")
        )
        target = self.cfg.local / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        return att | {
            "status": "saved",
            "path": rel.as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "mime": f.get("mime") or mimetypes.guess_type(target.name)[0] or "",
        }

    # ------------------------------------------------------------------ Ausgang

    async def outbox_worker(self) -> None:
        """Postausgang abarbeiten, wenn Arbeit da ist und der Bot verbunden ist."""
        while True:
            await self.wake.wait()
            self.wake.clear()
            if self.state != "READY":
                continue
            for item in self.store.outbox(PLATFORM, self.account):
                await self._send(item)

    async def _send(self, item: dict) -> None:
        self.store.set_message_status(item["id"], "sending")
        self.on_change_message(item["id"])
        chat = item["platform_conversation_id"]
        try:
            files = [a for a in item["attachments"] if a.get("path")]
            if files:
                result = None
                for att in files:  # verlustfrei als Dokument (Telegram komprimiert Fotos neu)
                    result = await self._upload(
                        "sendDocument",
                        "document",
                        self.cfg.local / att["path"],
                        chat_id=chat,
                        caption=item["text"] or None,
                        reply_to_message_id=item["reply_to_platform_id"],
                    )
            else:
                result = await self._call(
                    "sendMessage",
                    self.tg.send_timeout_s,
                    chat_id=chat,
                    text=item["text"],
                    reply_to_message_id=item["reply_to_platform_id"],
                )
            self.store.set_message_status(
                item["id"],
                "sent",
                platform_message_id=str(result["message_id"]),  # type: ignore[index]
            )
        except TelegramError as exc:
            self.store.set_message_status(
                item["id"], "failed" if exc.definite else "unknown", error=str(exc)
            )
        self.on_change_message(item["id"])

    # Server setzt diesen Rückruf (Push des geänderten Nachrichtenstatus)
    on_change_message: Callable[[int], None] = staticmethod(lambda _id: None)  # type: ignore[assignment]


def _files(msg: dict) -> list[dict]:
    """Anhänge einer Telegram-Nachricht (Foto: größte Fassung)."""
    files = []
    if msg.get("photo"):
        best = max(msg["photo"], key=lambda p: p.get("file_size", 0) or p["width"] * p["height"])
        files.append(
            {
                "kind": "photo",
                "file_id": best["file_id"],
                "size": best.get("file_size", 0),
                "mime": "image/jpeg",
                "status": "pending",
            }
        )
    for field, kind in _FILE_KINDS.items():
        if msg.get(field):
            item = msg[field]
            files.append(
                {
                    "kind": kind,
                    "file_id": item["file_id"],
                    "size": item.get("file_size", 0),
                    "mime": item.get("mime_type", ""),
                    "status": "pending",
                }
            )
    return files
