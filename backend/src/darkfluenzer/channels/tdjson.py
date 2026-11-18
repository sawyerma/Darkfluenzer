"""Anbindung an TDLib über die offizielle JSON-Schnittstelle ``tdjson`` (PHASENPLAN_V0 §6.1).

TDLib läuft im Prozess (kein eigener Dienst). Genau ein Empfangsthread je Prozess (SP2 Schritt 4)
liest Antworten und Updates aller Instanzen mit ``td_receive`` und verteilt sie nach
``@client_id`` an die registrierten Konten; TDLib erlaubt ``td_receive`` nur aus einem Thread.
Anfragen tragen eine ``@extra``-Kennung, über die ihre Antwort genau einer wartenden Anfrage
zugeordnet wird. JSON ist hier nur das Schnittstellenformat von TDLib, nie internes Speicherformat.
"""

from __future__ import annotations

import asyncio
import ctypes
import itertools
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

CLOSED = "authorizationStateClosed"


class TdError(Exception):
    """TDLib-Antwort ``error`` (Code und Text wie von Telegram geliefert)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _load(library: Path):
    lib = ctypes.CDLL(str(library))
    lib.td_create_client_id.restype = ctypes.c_int
    lib.td_send.argtypes = [ctypes.c_int, ctypes.c_char_p]
    lib.td_receive.argtypes = [ctypes.c_double]
    lib.td_receive.restype = ctypes.c_char_p
    lib.td_execute.argtypes = [ctypes.c_char_p]
    lib.td_execute.restype = ctypes.c_char_p
    return lib


class Receiver:
    """Der eine Empfangsthread einer TDLib-Bibliothek: verteilt jedes Ereignis nach ``@client_id``.

    Der Thread läuft nach dem ersten Konto bis zum Prozessende (ein zweiter, gleichzeitiger
    ``td_receive`` wäre unzulässig); Ereignisse abgemeldeter Instanzen werden verworfen."""

    _all: dict[str, Receiver] = {}
    _guard = threading.Lock()

    @classmethod
    def of(cls, library: Path, lib=None) -> Receiver:
        with cls._guard:
            rec = cls._all.get(str(library))
            if rec is None:
                rec = cls._all[str(library)] = cls(lib if lib is not None else _load(library))
            return rec

    def __init__(self, lib) -> None:
        self.lib = lib
        self._clients: dict[int, Callable[[dict], None]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def register(self, client: int, deliver: Callable[[dict], None]) -> None:
        with self._lock:
            self._clients[client] = deliver
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="tdjson", daemon=True)
                self.thread.start()

    def unregister(self, client: int) -> None:
        with self._lock:
            self._clients.pop(client, None)

    def clients(self) -> list[int]:
        with self._lock:
            return list(self._clients)

    def stop(self) -> None:
        """Nur für Tests: Thread beenden (im Betrieb läuft er bis zum Prozessende)."""
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.lib.td_receive(1.0)
                if not raw:
                    continue
                event = json.loads(raw)
            except Exception:  # ein kaputtes Ereignis beendet den Empfang nie stumm
                log.exception("TDLib: Ereignis nicht lesbar")
                continue
            with self._lock:
                deliver = self._clients.get(event.get("@client_id"))
            if deliver is None:
                log.debug("TDLib: Ereignis %s ohne Empfänger", event.get("@type"))
                continue
            try:
                deliver(event)
            except Exception:
                log.exception("TDLib: Ereignis %s nicht zugestellt", event.get("@type"))


class TdJson:
    """Eine TDLib-Instanz (ein Telegram-Konto) mit asynchronen Anfragen."""

    def __init__(self, library: Path, loop: asyncio.AbstractEventLoop, *, lib=None) -> None:
        self._receiver = Receiver.of(library, lib)
        self._lib = self._receiver.lib
        self._loop = loop
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._closed = asyncio.Event()
        self.on_update: Callable[[dict], None] = lambda _u: None
        self.execute({"@type": "setLogVerbosityLevel", "new_verbosity_level": 1})
        self.client = self._lib.td_create_client_id()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def execute(self, request: dict) -> dict | None:
        """Synchrone TDLib-Methode (nur die dafür vorgesehenen, z. B. Protokollstufe)."""
        raw = self._lib.td_execute(json.dumps(request).encode())
        return json.loads(raw) if raw else None

    def start(self) -> None:
        self._receiver.register(self.client, self._deliver)
        # erste Anfrage weckt die Instanz; ihr Zustand kommt als updateAuthorizationState
        self.send({"@type": "getOption", "name": "version"})

    def close(self) -> None:
        """Instanz schließen (TDLib ``close``); abgemeldet wird sie beim Zustand ``closed``."""
        if not self.closed:
            self.send({"@type": "close"})

    async def wait_closed(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._closed.wait(), timeout)
        except TimeoutError:
            return False
        return True

    def send(self, request: dict) -> None:
        self._lib.td_send(self.client, json.dumps(request).encode())

    async def call(self, request: dict, timeout: float) -> dict:
        """Anfrage senden und auf genau ihre Antwort warten; ``error`` wird zu TdError."""
        if self.closed:
            raise TdError(500, "TDLib-Instanz geschlossen")
        extra = str(next(self._ids))
        future = self._loop.create_future()
        self._pending[extra] = future
        self.send({**request, "@extra": extra})
        try:
            result = await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(extra, None)
        if result.get("@type") == "error":
            raise TdError(int(result.get("code", 0)), str(result.get("message", "")))
        return result

    def _deliver(self, event: dict) -> None:
        """Im Empfangsthread: in die Schleife des Kontos reichen; nach ``closed`` abmelden."""
        state = event.get("authorization_state") or {}
        if event.get("@type") == "updateAuthorizationState" and state.get("@type") == CLOSED:
            self._receiver.unregister(self.client)
        try:
            self._loop.call_soon_threadsafe(self._dispatch, event)
        except RuntimeError:  # Schleife beendet (Herunterfahren): nichts mehr zuzustellen
            self._receiver.unregister(self.client)

    def _dispatch(self, event: dict) -> None:
        extra = event.get("@extra")
        if extra is not None:
            future = self._pending.get(str(extra))
            if future is not None and not future.done():
                future.set_result(event)
            return
        state = event.get("authorization_state") or {}
        if event.get("@type") == "updateAuthorizationState" and state.get("@type") == CLOSED:
            self._closed.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(TdError(500, "TDLib-Instanz geschlossen"))
        try:
            self.on_update(event)
        except Exception:
            log.exception("TDLib: Update %s nicht verarbeitet", event.get("@type"))
