"""Claras Telegram-Konto über TDLib (PHASENPLAN_V0 §6.1, C2d) – ein normales Nutzerkonto, kein Bot.

Anmeldung im Cockpit (Nummer -> Code -> Passwort, Befehl 39); Code und Passwort werden nur an
TDLib weitergereicht, nie gespeichert oder protokolliert. Die Sitzung liegt unter
``[telegram_account] data_dir`` (verschlüsselt mit einem Schlüssel aus dem Schlüsselbund), ein
Neustart braucht keinen neuen Code.

Eingang: jede neue Nachricht eines Einzelchats wird vor dem Gelesen-Setzen dauerhaft gespeichert
(genau einmal), Anhänge sofort gesichert; im Testbetrieb nur freigegebene Test-Chats, alles andere
wird verworfen und nie gespeichert. Ausgang: nur über den Postausgang, mit Antworttempo,
Schreibanzeige, Höchstzahl je Minute und eingehaltener Telegram-Bremse (Flood-Wait). Schreibt der
Betreiber am Handy selbst in Claras Konto, entsteht die Karte ``ÜBERGABE AN BETREIBER``.
"""

from __future__ import annotations

import asyncio
import base64
import bisect
import contextlib
import hashlib
import logging
import os
import random
import re
import shutil
import sqlite3
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__
from ..config import Config
from ..keychain import secret, store_secret
from ..store import Inbound, Store
from .base import Capabilities, Channel
from .tdjson import TdError, TdJson

log = logging.getLogger("darkfluenzer.telegram")

PLATFORM = "telegram"
HANDOFF_CARD = "ÜBERGABE AN BETREIBER"
LAST = "last:"  # adapter_state: letzte gespeicherte Nachrichten-ID je Chat (Abgleich nach Neustart)
OWN = "own:"  # adapter_state: Plattform-IDs eigener Teilnachrichten je Chat (SP2 Schritt 6)
OWN_KEPT = 200  # gemerkte eigene IDs je Chat
UNKNOWN_SLACK_S = 120  # Verlaufsprüfung beginnt so viel vor der Einreihung der Sendung
DOWNLOAD_ATTEMPTS = 3  # Anhang laden: Versuche, danach `failed` mit Grund (SP1 Schritt 3)
DOWNLOAD_RETRY_S = 2.0  # Pause vor dem zweiten Versuch (wächst je Versuch)
HISTORY_PAGES = 20  # Obergrenze Seiten je Chat beim Abgleich (je bis zu 100 Nachrichten)
REJECTED_SHOWN = 5  # Testbetrieb: zuletzt verworfene Einzelchat-IDs (nur im Speicher, ohne Inhalt)
# TDLib-Inhaltsart -> (Anhangart, Feld mit der Datei)
_FILE_CONTENT = {
    "messageVideo": ("video", "video", "video"),
    "messageDocument": ("document", "document", "document"),
    "messageVoiceNote": ("voice", "voice_note", "voice"),
    "messageAudio": ("audio", "audio", "audio"),
    "messageVideoNote": ("video", "video_note", "video"),
    "messageAnimation": ("video", "animation", "animation"),
    "messageSticker": ("sticker", "sticker", "sticker"),
}
_RETRY_AFTER = re.compile(r"retry after (\d+)", re.IGNORECASE)
# Anmeldezustände (FRONT F4 V1.12 Punkt 1)
_AUTH_STEP = {
    "authorizationStateWaitPhoneNumber": "phone",
    "authorizationStateWaitCode": "code",
    "authorizationStateWaitPassword": "password",
    "authorizationStateReady": "ready",
}


def message_text(content: dict) -> str:
    if content.get("@type") == "messageText":
        return str(content["text"]["text"])
    return str((content.get("caption") or {}).get("text", ""))


def file_names_of(content: dict) -> list[str]:
    """Dateinamen einer Nachricht (Dokument: Name der gesendeten Zustellkopie)."""
    kind = content.get("@type")
    if kind in _FILE_CONTENT:
        _, field, _ = _FILE_CONTENT[kind]
        name = (content.get(field) or {}).get("file_name")
        return [str(name)] if name else []
    return []


def files_of(content: dict) -> list[dict]:
    """Anhänge einer TDLib-Nachricht (Foto: größte Fassung) mit TDLib-Datei-ID."""
    kind = content.get("@type")
    if kind == "messagePhoto":
        best = max(content["photo"]["sizes"], key=lambda s: s["width"] * s["height"])
        f = best["photo"]
        return [{"kind": "photo", "file_id": f["id"], "size": _size(f), "mime": "image/jpeg"}]
    if kind in _FILE_CONTENT:
        att, field, inner = _FILE_CONTENT[kind]
        obj = content[field]
        f = obj[inner]
        return [
            {"kind": att, "file_id": f["id"], "size": _size(f), "mime": obj.get("mime_type", "")}
        ]
    return []


def _size(f: dict) -> int:
    return int(f.get("size") or f.get("expected_size") or 0)


class TelegramAccount(Channel):
    """Ein Telegram-Nutzerkonto (Claras Konto; im Testbetrieb das des Betreibers)."""

    platform = PLATFORM

    def capabilities(self) -> Capabilities:
        """Dateien gehen heute als Dokument; selbstlöschend, Gelesen, Tippen folgen (SP4/SP5)."""
        return Capabilities(
            document=True,
            self_destruct=False,
            reply_window=False,
            read_receipts=False,
            typing=False,
        )

    def __init__(
        self,
        cfg: Config,
        store: Store,
        on_inbound: Callable[[Inbound], Awaitable[None]],
        on_change: Callable[[], None],
        account: dict | None = None,
    ) -> None:
        assert cfg.telegram is not None
        self.cfg = cfg
        self.tg = cfg.telegram
        # Kanalkonto (SP2 Schritt 9a): Kürzel, Testbetrieb und Test-Chats aus channel_accounts
        self.key = account["key"] if account else PLATFORM
        self.test_mode = account["test_mode"] if account else self.tg.test_mode
        self.test_chat_ids = tuple(account["test_chat_ids"]) if account else self.tg.test_chat_ids
        # je Konto eigene TDLib-Daten und eigener Datenbankschlüssel (SP2 Schritt 4); das aus der
        # Konfiguration übernommene Konto behält Verzeichnis und Schlüssel von bisher
        own = self.key == PLATFORM
        self.data_dir = self.tg.data_dir if own else self.tg.data_dir / "accounts" / self.key
        self.db_key_service = self.tg.db_key_service + ("" if own else f".{self.key}")
        self.store = store
        self.on_inbound = on_inbound
        self.on_change = on_change
        self.account = ""  # unveränderliche Telegram-Nutzer-ID nach der Anmeldung
        self.username = ""
        self.state = "OFF"
        self.login = ""  # phone | code | password | ready
        self.login_hint = ""
        self.error = ""
        self.missing = ""
        self.last_event_ms = 0
        self.flood_until = 0.0
        self.wake = asyncio.Event()  # Postausgang hat Arbeit
        self._td: TdJson | None = None
        self._stopping = False  # Server beendet: TDLib-Updates nicht mehr verarbeiten
        self._chats: dict[int, str] = {}  # Chat-ID -> TDLib-Chatart
        self._titles: dict[int, str] = {}  # Chat-ID -> Titel (Einzelchat: Name des Kontakts)
        # Chats mit ungelesenen Nachrichten -> zuletzt gelesene eingehende ID (aus TDLib-Updates);
        # gelesen wird erst nach dem Speichern, ungelesen heißt also: noch nicht verarbeitet
        self._unread: dict[int, int] = {}
        self._sending: dict[int, int] = {}  # vorläufige TDLib-Nachrichten-ID -> Postausgang-ID
        self._open: dict[int, int] = {}  # Postausgang-ID -> noch unbestätigte Teilnachrichten
        self._tasks: set[asyncio.Task] = set()  # laufende Hintergrundaufgaben (FABLE-005)
        self._sent_at: deque[float] = deque()
        # Eingang der Reihe nach je Chat (SP1 Schritt 3): Warteschlange (nach Nachrichten-ID) und
        # höchstens ein Arbeiter je Chat – ein Befehl überholt nie das Foto davor
        self._chat_queues: dict[int, list[tuple[int, dict, asyncio.Future]]] = {}
        self._chat_workers: set[int] = set()
        # Testbetrieb: verworfene Einzelchats (ID, Zeit) nur im Speicher, damit der Betreiber die
        # ID seines Testpartners findet – nie in SQLite, nie in TDLib-Dateien, ohne Inhalt/Namen
        self.rejected: deque[tuple[int, int]] = deque(maxlen=REJECTED_SHOWN)
        self._api: tuple[str, str] = ("", "")  # api_id, api_hash (nur im Speicher)
        self._key = ""  # TDLib-Datenbankschlüssel (nur im Speicher)

    # ------------------------------------------------------------------ Zustand

    @property
    def automation(self) -> bool:
        return (
            bool(self.account)
            and self.store.adapter_get(PLATFORM, self.account, "automation") == "1"
        )

    def status(self) -> dict:
        label = f"@{self.username}" if self.username else self.account
        return {
            "platform": PLATFORM,
            "account": label,
            "state": self.state,
            "error": self.error or self.task_error,
            "last_event_ms": self.last_event_ms,
            "missing": self.missing,
            "login_state": self.login,
            "login_hint": self.login_hint,
            "test_mode": self.test_mode,
            "automation": self.automation,
            "flood_until_ms": int(self.flood_until * 1000) if self.flood_until > time.time() else 0,
            "rejected_chats": [
                {"chat_id": chat, "at_ms": at} for chat, at in self.rejected if self.test_mode
            ],
        }

    def _set(
        self, state: str, *, login: str | None = None, error: str = "", missing: str = ""
    ) -> None:
        new = (state, self.login if login is None else login, error, missing)
        if state == "READY" and self.task_error:  # wieder verbunden: Meldung der Aufsicht erledigt
            self.task_error = ""
            self.on_change()
        if new != (self.state, self.login, self.error, self.missing):
            self.state, self.login, self.error, self.missing = new
            self.on_change()

    # ------------------------------------------------------------------ Start und Anmeldung

    def _prerequisites(self) -> tuple[str, str] | str:
        if not self.tg.tdjson.is_file():
            return f"TDLib fehlt ({self.tg.tdjson.name}: launcher/setup_tdlib.sh)"
        api_id = secret(self.tg.api_id_service)
        api_hash = secret(self.tg.api_hash_service)
        if not api_id or not api_hash:
            return f"api_id/api_hash im Schlüsselbund ({self.tg.api_id_service}, …api_hash)"
        if not api_id.isdigit():
            return f"{self.tg.api_id_service} ist keine Zahl"
        return api_id, api_hash

    def _db_key(self) -> str | None:
        key = secret(self.db_key_service)
        if key:
            return key
        key = base64.b64encode(os.urandom(32)).decode()
        return key if store_secret(self.db_key_service, key) else None

    async def run(self) -> None:
        """Voraussetzungen prüfen (Schlüsselbund wird regelmäßig neu gelesen), dann TDLib starten;
        alles Weitere treiben TDLib-Updates."""
        while True:
            ready = await asyncio.to_thread(self._prerequisites)
            if isinstance(ready, str):
                self._set("OFF", login="", missing=ready)
                await asyncio.sleep(self.cfg.server.observe_s * 15)
                continue
            self._api = ready
            key = await asyncio.to_thread(self._db_key)
            if key is None:
                self._set("ERROR", error="Datenbankschlüssel nicht im Schlüsselbund ablegbar")
                await asyncio.sleep(self.cfg.server.observe_s * 15)
                continue
            self._key = key
            break
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.data_dir, 0o700)
        # Neustart unter Aufsicht: die vorige Instanz gibt ihre Datenbank erst nach ``closed`` frei
        if self._td is not None and not self._td.closed:
            self._td.close()
            await self._td.wait_closed(self._timeout)
        self._stopping = False
        self._set("CONNECTING", missing="")
        self._start_client()
        try:
            await asyncio.Event().wait()  # läuft bis zum Beenden des Servers
        finally:
            # erst nichts mehr verarbeiten (die Datenbank schließt gleich), dann TDLib sauber
            # schließen; ``closed`` startet dann keine neue Instanz
            self._stopping = True
            if self._td is not None:
                self._td.close()

    def _start_client(self) -> None:
        """Neue TDLib-Instanz am gemeinsamen Empfangsthread (kein eigener Thread je Instanz)."""
        self._td = TdJson(self.tg.tdjson, asyncio.get_running_loop())
        self._td.on_update = self._on_update
        self._td.start()

    def _parameters(self) -> dict:
        api_id, api_hash = self._api
        return {
            "@type": "setTdlibParameters",
            "use_test_dc": False,
            "database_directory": str(self.data_dir / "db"),
            "files_directory": str(self.data_dir / "files"),
            "database_encryption_key": self._key,
            # SQLite ist die einzige Autorität für Nachrichten und Anhänge (V0 §6.1 Punkt 1)
            "use_file_database": False,
            "use_chat_info_database": False,
            "use_message_database": False,
            "use_secret_chats": False,
            "api_id": int(api_id),
            "api_hash": api_hash,
            "system_language_code": "de",
            "device_model": "Mac",
            "application_version": __version__,
        }

    async def login_step(self, step: str, value: str) -> str:
        """Ein Anmeldeschritt (Befehl 39); leer bei Erfolg, sonst der Grund."""
        method = {
            "phone": ("setAuthenticationPhoneNumber", "phone_number"),
            "code": ("checkAuthenticationCode", "code"),
            "password": ("checkAuthenticationPassword", "password"),
        }.get(step)
        if method is None:
            return "Unbekannter Anmeldeschritt."
        if self._td is None:
            return self.missing or "Telegram ist nicht bereit."
        if step != self.login:
            return "Dieser Schritt ist gerade nicht dran."
        if step == "phone" and not value.strip().startswith("+"):
            return "Telefonnummer mit Ländervorwahl eingeben, z. B. +49 statt der führenden 0."
        try:
            await self._td.call({"@type": method[0], method[1]: value.strip()}, self._timeout)
        except TdError as exc:
            return f"Telegram: {exc.message}"
        except TimeoutError:
            return "Telegram antwortet nicht."
        return ""

    async def logout(self) -> str:
        if self._td is None or self.login != "ready":
            return "Nicht angemeldet."
        try:
            await self._td.call({"@type": "logOut"}, self._timeout)
        except (TdError, TimeoutError) as exc:
            return f"Abmelden fehlgeschlagen: {exc}"
        return ""

    def set_automation(self, enabled: bool) -> str:
        if not self.account:
            return "Nicht angemeldet."
        self.store.adapter_set(PLATFORM, self.account, "automation", "1" if enabled else "0")
        self.on_change()
        return ""

    @property
    def _timeout(self) -> float:
        return self.cfg.server.timeout_s

    # ------------------------------------------------------------------ Updates

    def _on_update(self, update: dict) -> None:
        if self._stopping:
            return
        kind = update.get("@type")
        if kind == "updateAuthorizationState":
            self._spawn(self._auth_step(update["authorization_state"]))
        elif kind == "updateNewChat":
            chat = update["chat"]
            self._chats[chat["id"]] = chat["type"]["@type"]
            self._titles[chat["id"]] = str(chat.get("title", ""))
            if chat.get("unread_count"):
                self._unread[chat["id"]] = int(chat.get("last_read_inbox_message_id", 0))
        elif kind == "updateChatReadInbox":
            if update.get("unread_count"):
                self._unread[update["chat_id"]] = int(update["last_read_inbox_message_id"])
            else:
                self._unread.pop(update["chat_id"], None)
        elif kind == "updateNewMessage":
            self._enqueue_message(update["message"])
        elif kind == "updateMessageContent":
            self._edited(update)
        elif kind == "updateDeleteMessages":
            self._deleted(update)
        elif kind == "updateMessageSendSucceeded":
            msg = update["message"]
            self._send_result(update["old_message_id"], str(msg["id"]), None, msg)
        elif kind == "updateMessageSendFailed":
            err = update.get("error") or {}
            self._flood(str(err.get("message", "")), int(err.get("code", 0)))
            self._send_result(
                update["old_message_id"], None, str(err.get("message", "Fehler")), update["message"]
            )
        elif kind == "updateConnectionState" and self.login == "ready":
            ready = update["state"]["@type"] == "connectionStateReady"
            self._set("READY" if ready else "CONNECTING")
            if ready:
                self.wake.set()

    def _edited(self, update: dict) -> None:
        """Bearbeitete Nachricht (SP2 Schritt 5): neuer Text im Verlauf, erster Text bleibt; nur
        für gespeicherte Nachrichten, nie für ignorierte Chats."""
        chat = int(update["chat_id"])
        if chat in self.tg.ignored_chat_ids or not self.account:
            return
        text = message_text(update.get("new_content") or {})
        changed = self.store.edit_platform_message(
            PLATFORM, self.account, str(chat), str(update["message_id"]), text
        )
        if changed is not None:
            self.on_change_message(changed)

    def _deleted(self, update: dict) -> None:
        """Gelöschte Nachrichten: Löschmarke im Verlauf; ``from_cache`` (nur aus dem TDLib-Speicher
        entfernt) und nicht endgültige Löschungen ändern nichts."""
        chat = int(update["chat_id"])
        if (
            chat in self.tg.ignored_chat_ids
            or not self.account
            or update.get("from_cache")
            or not update.get("is_permanent")
        ):
            return
        ids = [str(i) for i in update.get("message_ids") or ()]
        gone = self.store.delete_platform_messages(PLATFORM, self.account, str(chat), ids)
        for message_id in gone:
            self.on_change_message(message_id)

    def _enqueue_message(self, msg: dict) -> asyncio.Future:
        """Nachricht in die Warteschlange ihres Chats (nach Telegram-ID einsortiert); das Future
        ist erfüllt, sobald sie verarbeitet ist (Speichern, Anhänge, Weiterleitung)."""
        chat = int(msg["chat_id"])
        done = asyncio.get_running_loop().create_future()
        queue = self._chat_queues.setdefault(chat, [])
        ids = [entry[0] for entry in queue]
        queue.insert(bisect.bisect_right(ids, int(msg["id"])), (int(msg["id"]), msg, done))
        if chat not in self._chat_workers:
            self._chat_workers.add(chat)
            self._spawn(self._chat_worker(chat))
        return done

    async def _chat_worker(self, chat: int) -> None:
        queue = self._chat_queues[chat]
        try:
            while queue:
                _, msg, done = queue.pop(0)
                try:
                    await self._guard(self._message(msg))
                finally:
                    if not done.done():
                        done.set_result(None)
        finally:
            self._chat_workers.discard(chat)
            if not queue:
                self._chat_queues.pop(chat, None)

    def _spawn(self, job: Awaitable[None]) -> None:
        """Hintergrundaufgabe mit Referenz bis zum Ende; ohne sie kann der Event-Loop die Aufgabe
        mitten im Lauf einsammeln (FABLE-005)."""
        task = asyncio.ensure_future(job)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _auth_step(self, state: dict) -> None:
        """Anmeldeschritt; ein unerwarteter Fehler erscheint als ERROR am Kanal (FABLE-005)."""
        try:
            await self._auth(state)
        except Exception as exc:
            log.exception("Telegram: Anmeldeschritt %s fehlgeschlagen", state.get("@type"))
            self._set("ERROR", error=f"Anmeldung: interner Fehler ({type(exc).__name__})")

    async def _guard(self, job: Awaitable[None]) -> None:
        try:
            await job
        except Exception:  # eine fehlerhafte Nachricht stoppt den Eingang nicht
            log.exception("Telegram: Nachricht nicht verarbeitet")

    async def _auth(self, state: dict) -> None:
        kind = state["@type"]
        assert self._td is not None
        if kind == "authorizationStateWaitTdlibParameters":
            try:
                await self._td.call(self._parameters(), self._timeout)
            except (TdError, TimeoutError) as exc:
                self._set("ERROR", error=f"TDLib-Start: {exc}")
            return
        if kind in _AUTH_STEP:
            step = _AUTH_STEP[kind]
            self.login_hint = str(state.get("password_hint", "")) if step == "password" else ""
            if step != "ready":
                self._set("LOGIN", login=step)
                return
            try:
                me = await self._td.call({"@type": "getMe"}, self._timeout)
            except (TdError, TimeoutError) as exc:
                self._set("ERROR", error=f"getMe: {exc}")
                return
            self.account = str(me["id"])
            names = (me.get("usernames") or {}).get("active_usernames") or []
            self.username = names[0] if names else ""
            self._set("READY", login="ready")
            log.info("Telegram angemeldet als Konto %s", self.account)
            await self._guard(self._reconcile())
            await self._guard(self._resume_pending())
            await self._guard(self._settle_unknown())
            self.wake.set()
            return
        if kind == "authorizationStateClosed":  # nach Abmelden: neue Instanz, wieder Nummer
            self.account, self.username = "", ""
            self._set("CONNECTING", login="")
            self._start_client()
            return
        if kind in ("authorizationStateLoggingOut", "authorizationStateClosing"):
            self._set("CONNECTING", login="")
            return
        # E-Mail-Anmeldung, Registrierung, Bestätigung auf anderem Gerät: in der Telegram-App
        self._set(
            "ERROR", login="", error=f"Anmeldeschritt {kind} bitte in der Telegram-App erledigen"
        )

    async def _reconcile(self) -> None:
        """Nachrichten, die während einer Pause ankamen, über getChatHistory nachholen (V0 §6):
        bekannte Chats ab der zuletzt gespeicherten Nachrichten-ID; Chats ohne gespeicherte
        Position (Kunde schrieb erstmals, während Darkfluenzer aus war, oder Test-Chat schrieb
        vor seiner Freigabe) nur ab der zuletzt gelesenen eingehenden Nachricht – nie älterer
        Verlauf des Kontos."""
        assert self._td is not None
        with contextlib.suppress(TdError):  # 404: alle Chats geladen (Updates kommen vorher)
            await self._td.call(
                {"@type": "loadChats", "chat_list": {"@type": "chatListMain"}, "limit": 200},
                self._timeout,
            )
        stored = self.store.adapter_prefixed(PLATFORM, self.account, LAST)
        since = {int(chat): int(last) for chat, last in stored.items()}
        for chat_id, read in self._unread.items():
            since.setdefault(chat_id, read)
        for chat_id, last in since.items():
            if self.test_mode and chat_id not in self.test_chat_ids:
                continue
            missed = await self._missed(chat_id, last)
            # dieselbe Warteschlange wie der Live-Eingang: Reihenfolge je Chat bleibt erhalten
            await asyncio.gather(*(self._enqueue_message(msg) for msg in missed))
            if missed:
                log.info("Telegram: %d Nachricht(en) aus Chat %s nachgeholt", len(missed), chat_id)

    async def _missed(self, chat_id: int, last: int) -> list[dict]:
        """Nachrichten mit ID > ``last``, aufsteigend."""
        assert self._td is not None
        found: dict[int, dict] = {}
        start = 0
        for _ in range(HISTORY_PAGES):
            page = await self._td.call(
                {
                    "@type": "getChatHistory",
                    "chat_id": chat_id,
                    "from_message_id": start,
                    "offset": 0,
                    "limit": 100,
                    "only_local": False,
                },
                self._timeout,
            )
            batch = page.get("messages") or []
            found.update({m["id"]: m for m in batch if m["id"] > last})
            oldest = min((m["id"] for m in batch), default=0)
            if not batch or oldest <= last:
                break
            start = oldest
        return [found[i] for i in sorted(found)]

    async def _resume_pending(self) -> None:
        """Nach dem Start: Eingänge, deren Anhänge beim Beenden noch luden (``pending``), neu
        laden – TDLib-Datei-IDs gelten nur je Sitzung, daher die Nachricht frisch abrufen – und
        dann erst weiterleiten (ihre Verarbeitung war unterbrochen, SP1 Schritt 3)."""
        assert self._td is not None
        for row in self.store.pending_inbound(PLATFORM, self.account):
            chat, mid = int(row["platform_conversation_id"]), int(row["platform_message_id"])
            try:
                fresh = await self._td.call(
                    {"@type": "getMessage", "chat_id": chat, "message_id": mid},
                    self._timeout,
                )  # fmt: skip
                files = files_of(fresh["content"])
            except (TdError, TimeoutError, KeyError, ValueError) as exc:
                files, why = [], f"Nachricht nicht mehr abrufbar: {exc}"[:200]
            else:
                why = "Anhang nicht mehr in der Nachricht"
            saved = []
            for i, att in enumerate(row["attachments"]):
                if att.get("status") != "pending":
                    saved.append(att)
                elif i < len(files):
                    saved.append(await self._save(chat, mid, i, files[i]))
                else:
                    saved.append(att | {"status": "failed", "note": why})
            self.store.set_attachments(row["id"], saved)
            log.info("Telegram: Anhänge von Nachricht %s nach dem Start geladen", row["id"])
            await self.on_inbound(self.store.inbound_of(row["id"]))

    def _remember(self, chat_id: int, message_id: int) -> None:
        key = f"{LAST}{chat_id}"
        known = int(self.store.adapter_get(PLATFORM, self.account, key) or 0)
        if message_id > known:
            self.store.adapter_set(PLATFORM, self.account, key, str(message_id))

    async def _chat_type(self, chat_id: int) -> str:
        if chat_id not in self._chats and self._td is not None:
            chat = await self._td.call({"@type": "getChat", "chat_id": chat_id}, self._timeout)
            self._chats[chat_id] = chat["type"]["@type"]
            self._titles[chat_id] = str(chat.get("title", ""))
        return self._chats.get(chat_id, "")

    async def _message(self, msg: dict) -> None:
        chat_id = int(msg["chat_id"])
        if chat_id in self.tg.ignored_chat_ids:
            return  # Dienstkonto 777000 u. ä.: nie gespeichert, nie im Verlauf (SP2 Schritt 5)
        if self.test_mode and chat_id not in self.test_chat_ids:
            if chat_id > 0 and not msg.get("is_outgoing"):  # Einzelchat (TDLib: positive ID)
                self.rejected = deque(
                    [r for r in self.rejected if r[0] != chat_id], maxlen=REJECTED_SHOWN
                )
                self.rejected.append((chat_id, int(time.time() * 1000)))
                self.on_change()
            return  # Testbetrieb: fremde Chats werden nie gespeichert
        if await self._chat_type(chat_id) != "chatTypePrivate":
            return  # nur Einzelchats
        content = msg["content"]
        sent_at = datetime.fromtimestamp(msg["date"], UTC).isoformat(timespec="seconds")
        if msg.get("is_outgoing"):
            if msg.get("sending_state"):
                return  # eigener Versand aus dem Postausgang (Ergebnis über Send-Updates)
            await self._external_outgoing(chat_id, msg, content, sent_at)
            self._remember(chat_id, int(msg["id"]))
            return
        sender = msg.get("sender_id") or {}
        if sender.get("@type") != "messageSenderUser":
            return
        user_id = int(sender["user_id"])
        handle, name = await self._user(user_id)
        reply = msg.get("reply_to") or {}
        files = files_of(content)
        inbound = self.store.record_inbound(
            PLATFORM,
            self.account,
            f"{chat_id}:{msg['id']}",
            sender_id=str(user_id),
            conversation_id=str(chat_id),
            platform_message_id=str(msg["id"]),
            text=message_text(content),
            sent_at=sent_at,
            handle=handle,
            display_name=name,
            reply_to=str(reply["message_id"])
            if reply.get("@type") == "messageReplyToMessage"
            else None,
            attachments=[_pending(f) for f in files],
            album_id=str(msg.get("media_album_id") or "") if msg.get("media_album_id") else None,
        )
        self.last_event_ms = int(time.time() * 1000)
        self._remember(chat_id, int(msg["id"]))
        if inbound.message_id is None:
            return  # bereits gespeichert (erneut zugestellt)
        if files:
            saved = [await self._save(chat_id, msg["id"], i, f) for i, f in enumerate(files)]
            self.store.set_attachments(inbound.message_id, saved)
        await self.on_inbound(inbound)
        # ehrlich gelesen: erst nach Speichern und Verarbeitung
        assert self._td is not None
        self._td.send(
            {
                "@type": "viewMessages",
                "chat_id": chat_id,
                "message_ids": [msg["id"]],
                "force_read": True,
            }
        )

    async def _external_outgoing(
        self, chat_id: int, msg: dict, content: dict, sent_at: str
    ) -> None:
        mid, partner = str(msg["id"]), str(chat_id)
        if mid in self._own(chat_id):
            return  # eigene Teilnachricht aus dem Postausgang (Abgleich nach Neustart)
        text = message_text(content)
        names = file_names_of(content)
        item = self.store.match_unknown(PLATFORM, self.account, partner, text, names)
        if item is not None:  # Sendung mit unbekanntem Ergebnis kam doch an (SPEC-009)
            self._resolved(item, chat_id, mid, "angekommen (eigene Nachricht im Telegram-Verlauf)")
            return
        conv, message_id = self.store.record_external_outgoing(
            PLATFORM, self.account, partner, mid, text, sent_at
        )
        if message_id is None:
            return
        self.store.add_system_card(
            conv, f"{HANDOFF_CARD}\nNachricht direkt in der Telegram-App gesendet."
        )
        self.on_change_message(message_id)

    async def _user(self, user_id: int) -> tuple[str | None, str | None]:
        assert self._td is not None
        title = self._titles.get(user_id) or None  # Einzelchat-ID = Nutzer-ID
        try:
            user = await self._td.call({"@type": "getUser", "user_id": user_id}, self._timeout)
        except (TdError, TimeoutError) as exc:
            log.warning("Telegram: getUser %s: %s – Name aus dem Chat-Titel", user_id, exc)
            return None, title
        names = (user.get("usernames") or {}).get("active_usernames") or []
        full = " ".join(filter(None, (user.get("first_name"), user.get("last_name"))))
        return (names[0] if names else None), (full or title)

    async def _save(self, chat_id: int, message_id: int, index: int, f: dict) -> dict:
        """Anhang über TDLib laden, nach local/channels/telegram/<chat>/ kopieren, Hash
        festhalten; bis zu DOWNLOAD_ATTEMPTS Versuche, danach `failed` mit Grund."""
        att = _pending(f)
        limit = int(self.tg.max_download_mb * 1024 * 1024)
        if f["size"] > limit:
            return att | {"status": "too_large", "note": f"über {self.tg.max_download_mb:.0f} MB"}
        assert self._td is not None
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                done = await self._td.call(
                    {
                        "@type": "downloadFile",
                        "file_id": f["file_id"],
                        "priority": 1,
                        "offset": 0,
                        "limit": 0,
                        "synchronous": True,
                    },
                    max(self._timeout, 600.0),
                )
                break
            except (TdError, TimeoutError) as exc:
                if attempt == DOWNLOAD_ATTEMPTS:
                    note = f"nach {attempt} Versuchen: {str(exc)[:180]}"
                    return att | {"status": "failed", "note": note}
                await asyncio.sleep(DOWNLOAD_RETRY_S * attempt)
        src = Path(done["local"]["path"])
        suffix = src.suffix or ".bin"
        rel = Path("channels") / PLATFORM / str(chat_id) / f"{message_id}_{index}{suffix}"
        target = self.cfg.local / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            await asyncio.to_thread(_copy_whole, src, target)
        # TDLib-Kopie entfernen: Anhänge liegen nur unter local/channels (V0 §6.1 Punkt 1)
        self._td.send({"@type": "deleteFile", "file_id": f["file_id"]})
        digest = await asyncio.to_thread(_sha256, target)
        return att | {
            "status": "saved",
            "path": rel.as_posix(),
            "sha256": digest,
            "size": target.stat().st_size,
        }

    # ------------------------------------------------------------------ Ausgang

    async def outbox_worker(self) -> None:
        """Postausgang abarbeiten, wenn Arbeit da ist und das Konto verbunden ist."""
        while True:
            await self.wake.wait()
            self.wake.clear()
            for item in self.store.outbox(PLATFORM, self.account) if self.state == "READY" else []:
                await self._pace(item)
                if self.state != "READY":
                    break
                await self._send(item)
                if self.task_error:  # Postausgang läuft wieder: Meldung der Aufsicht erledigt
                    self.task_error = ""
                    self.on_change()

    async def _pace(self, item: dict) -> None:
        """Telegram-Bremse, Höchstzahl je Minute, Antwortverzögerung und Schreibanzeige."""
        while (wait := self.flood_until - time.time()) > 0:
            await asyncio.sleep(wait)
        while len(self._sent_at) >= self.tg.max_messages_per_minute:
            wait = self._sent_at[0] + 60 - time.time()
            if wait <= 0:
                self._sent_at.popleft()
                continue
            await asyncio.sleep(wait)
        await asyncio.sleep(random.uniform(self.tg.reply_delay_min_s, self.tg.reply_delay_max_s))
        assert self._td is not None
        chat = int(item["platform_conversation_id"])
        self._td.send(
            {"@type": "sendChatAction", "chat_id": chat, "action": {"@type": "chatActionTyping"}}
        )
        await asyncio.sleep(
            min(len(item["text"]) / self.tg.typing_chars_per_s, self.tg.reply_delay_max_s)
        )

    async def _send(self, item: dict) -> None:
        assert self._td is not None
        # Zustellung an Kunden: Gate im Versandmoment frisch prüfen (approval.py, V0 §8.4 Punkt 9)
        if item.get("delivery_id") and (reason := await self.gate(item)):
            self.store.set_message_status(item["id"], "failed", error=reason)
            self.on_change_message(item["id"])
            return
        self.store.set_message_status(item["id"], "sending")
        self.on_change_message(item["id"])
        chat = int(item["platform_conversation_id"])
        reply = (
            {"@type": "inputMessageReplyToMessage", "message_id": int(item["reply_to_platform_id"])}
            if item["reply_to_platform_id"]
            else None
        )
        text = {"@type": "formattedText", "text": item["text"]}
        files = [a for a in item["attachments"] if a.get("path")]
        contents = (
            [
                {  # verlustfrei als Dokument (Telegram komprimiert Fotos neu)
                    "@type": "inputMessageDocument",
                    "document": {
                        "@type": "inputFileLocal",
                        "path": str(self.cfg.local / a["path"]),
                    },
                    # Beschriftung nur am ersten Anhang (SP2 Schritt 5), nicht an jedem Teil
                    "caption": text if i == 0 else {"@type": "formattedText", "text": ""},
                }
                for i, a in enumerate(files)
            ]
            if files
            else [{"@type": "inputMessageText", "text": text}]
        )
        self._open[item["id"]] = len(contents)
        for content in contents:
            request = {"@type": "sendMessage", "chat_id": chat, "input_message_content": content}
            if reply:
                request["reply_to"] = reply
            try:
                sent = await self._td.call(request, self._timeout)
            except TdError as exc:  # sicher nicht angenommen
                self._flood(exc.message, exc.code)
                self._open.pop(item["id"], None)
                self.store.set_message_status(
                    item["id"], "failed", error=f"Telegram: {exc.message}"
                )
                self.on_change_message(item["id"])
                return
            except TimeoutError:  # womöglich angenommen: nie blind wiederholen
                self._open.pop(item["id"], None)
                self.store.set_message_status(
                    item["id"], "unknown", error="Keine Antwort von TDLib"
                )
                self.on_change_message(item["id"])
                return
            self._sending[int(sent["id"])] = item["id"]
            self._sent_at.append(time.time())

    def _send_result(
        self, old_id: int, new_id: str | None, error: str | None, msg: dict | None = None
    ) -> None:
        item = self._sending.pop(int(old_id), None)
        chat = int((msg or {}).get("chat_id") or 0)
        if item is None and msg is not None:  # Antwort auf sendMessage kam nie (unknown)
            self._late_result(chat, msg, new_id, error)
            return
        if item is None or item not in self._open:
            return
        if error is not None:
            self._open.pop(item)
            self.store.set_message_status(item, "failed", error=f"Telegram: {error}")
        else:
            if chat and new_id:
                self._remember_own(chat, new_id)  # jede Teilnachricht ist eigene (SP2 Schritt 6)
            self._open[item] -= 1
            if self._open[item] > 0:
                return
            self._open.pop(item)
            self.store.set_message_status(item, "sent", platform_message_id=new_id)
        self.on_change_message(item)

    def _late_result(self, chat: int, msg: dict, new_id: str | None, error: str | None) -> None:
        """Versandergebnis einer Sendung, deren sendMessage-Aufruf ohne Antwort blieb: TDLib
        meldet Erfolg oder Fehlschlag nachträglich – das ist der Beleg der Plattform."""
        content = msg.get("content") or {}
        item = self.store.match_unknown(
            PLATFORM, self.account, str(chat), message_text(content), file_names_of(content)
        )
        if item is None:
            return
        if error is None and new_id:
            self._resolved(item, chat, new_id, "angekommen (Telegram meldet den Versand)")
        elif error is not None:
            self.store.set_message_status(item, "failed", error=f"Telegram: {error}")
            self.on_change_message(item)

    def _resolved(self, item: int, chat: int, mid: str, how: str) -> None:
        self._remember_own(chat, mid)
        try:
            self.store.set_message_status(item, "sent", platform_message_id=mid)
        except sqlite3.IntegrityError:  # ID gehört schon einer Teilnachricht derselben Sendung
            self.store.set_message_status(item, "sent")
        conv = self.store.message(item)["conversation_id"]
        self.store.add_system_card(conv, f"VERSAND GEKLÄRT · Nachricht {item} · {how}")
        self.on_change_message(item)

    def _own(self, chat: int) -> list[str]:
        return (self.store.adapter_get(PLATFORM, self.account, f"{OWN}{chat}") or "").split()

    def _remember_own(self, chat: int, mid: str) -> None:
        kept = [*self._own(chat), mid][-OWN_KEPT:]
        self.store.adapter_set(PLATFORM, self.account, f"{OWN}{chat}", " ".join(kept))

    async def _settle_unknown(self) -> None:
        """Nach dem (Wieder-)Verbinden: jede Sendung mit unbekanntem Ergebnis gegen den Verlauf
        prüfen (SPEC-009). Passende eigene Nachricht → ``sent``; Verlauf ab der Einreihung ohne
        passende Nachricht und ohne laufenden Versand → ``failed`` mit Beleg; sonst bleibt sie
        ``unknown`` für die Entscheidung des Betreibers. Nie ein automatischer neuer Versuch."""
        assert self._td is not None
        for row in self.store.unknown_outgoing(PLATFORM, self.account):
            chat = int(row["platform_conversation_id"])
            since = datetime.fromisoformat(row["created_at"]).timestamp() - UNKNOWN_SLACK_S
            try:
                history = await self._history_since(chat, since)
            except (TdError, TimeoutError) as exc:
                log.warning("Telegram: Verlauf für Sendung %s nicht lesbar: %s", row["id"], exc)
                continue
            if history is None:
                continue  # Verlauf nicht vollständig bis zur Einreihung: kein Beleg
            taken = set(self._own(chat)) | self.store.known_platform_ids(
                PLATFORM, self.account, str(chat)
            )
            files = {Path(str(a.get("path", ""))).name for a in row["attachments"]}
            own = [m for m in history if m.get("is_outgoing") and str(m["id"]) not in taken]
            if any(m.get("sending_state") for m in own):
                continue  # TDLib sendet noch: Ergebnis folgt als Send-Update
            hit = next(
                (
                    m for m in own
                    if (row["text"].strip() and message_text(m["content"]) == row["text"])
                    or files & set(file_names_of(m["content"]))
                ),
                None,
            )  # fmt: skip
            if hit is not None:
                self._resolved(row["id"], chat, str(hit["id"]), "angekommen (Telegram-Verlauf)")
                continue
            when = datetime.fromtimestamp(since, UTC).astimezone().strftime("%d.%m. %H:%M")
            self.store.set_message_status(
                row["id"], "failed",
                error=f"Telegram-Verlauf ab {when} enthält diese Nachricht nicht",
            )  # fmt: skip
            self.on_change_message(row["id"])

    async def _history_since(self, chat_id: int, since: float) -> list[dict] | None:
        """Verlauf eines Chats bis zur Zeit ``since`` (Unix-Sekunden); None, wenn die Seiten nicht
        bis dorthin reichen (dann gibt es keinen Beleg)."""
        assert self._td is not None
        found: list[dict] = []
        start = 0
        for _ in range(HISTORY_PAGES):
            page = await self._td.call(
                {"@type": "getChatHistory", "chat_id": chat_id, "from_message_id": start,
                 "offset": 0, "limit": 100, "only_local": False},
                self._timeout,
            )  # fmt: skip
            batch = [m for m in page.get("messages") or [] if not start or m["id"] < start]
            if not batch:
                return found  # Anfang des Chats erreicht
            found += batch
            oldest = min(batch, key=lambda m: m["id"])
            if oldest["date"] < since:
                return found
            start = oldest["id"]
        return None

    def _flood(self, message: str, code: int) -> None:
        """Telegram-Bremse (429 „retry after N“) einhalten und anzeigen."""
        found = _RETRY_AFTER.search(message)
        if code == 429 and found:
            self.flood_until = time.time() + int(found.group(1))
            log.warning("Telegram bremst %s s", found.group(1))
            self.on_change()

    # Server setzt diesen Rückruf (Push des geänderten Nachrichtenstatus)
    on_change_message: Callable[[int], None] = staticmethod(lambda _id: None)  # type: ignore[assignment]
    # Server setzt die Versandprüfung für Zustellungen (leer = senden, sonst der Sperrgrund)
    gate: Callable[[dict], str] = staticmethod(lambda _item: "Keine Versandprüfung.")  # type: ignore[assignment]


def _pending(f: dict) -> dict:
    return {"kind": f["kind"], "size": f["size"], "mime": f["mime"], "status": "pending"}


def _copy_whole(src: Path, target: Path) -> None:
    """Vollständig oder gar nicht: über eine Zwischendatei und ``os.replace``; ein Abbruch
    hinterlässt nie eine halbe Datei am Ziel (FABLE-017)."""
    tmp = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()
