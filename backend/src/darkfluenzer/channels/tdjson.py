"""Anbindung an TDLib über die offizielle JSON-Schnittstelle ``tdjson`` (PHASENPLAN_V0 §6.1).

TDLib läuft im Prozess (kein eigener Dienst). Ein Empfangsthread liest Antworten und Updates mit
``td_receive`` und reicht sie in die asyncio-Schleife; Anfragen tragen eine ``@extra``-Kennung,
über die ihre Antwort genau einer wartenden Anfrage zugeordnet wird. JSON ist hier nur das
Schnittstellenformat von TDLib, nie internes Speicherformat.
"""

from __future__ import annotations

import asyncio
import ctypes
import itertools
import json
import threading
from collections.abc import Callable
from pathlib import Path


class TdError(Exception):
    """TDLib-Antwort ``error`` (Code und Text wie von Telegram geliefert)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class TdJson:
    """Eine TDLib-Instanz (ein Telegram-Konto) mit asynchronen Anfragen."""

    def __init__(self, library: Path, loop: asyncio.AbstractEventLoop) -> None:
        lib = ctypes.CDLL(str(library))
        lib.td_create_client_id.restype = ctypes.c_int
        lib.td_send.argtypes = [ctypes.c_int, ctypes.c_char_p]
        lib.td_receive.argtypes = [ctypes.c_double]
        lib.td_receive.restype = ctypes.c_char_p
        lib.td_execute.argtypes = [ctypes.c_char_p]
        lib.td_execute.restype = ctypes.c_char_p
        self._lib = lib
        self._loop = loop
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_update: Callable[[dict], None] = lambda _u: None
        self.execute({"@type": "setLogVerbosityLevel", "new_verbosity_level": 1})
        self.client = lib.td_create_client_id()

    def execute(self, request: dict) -> dict | None:
        """Synchrone TDLib-Methode (nur die dafür vorgesehenen, z. B. Protokollstufe)."""
        raw = self._lib.td_execute(json.dumps(request).encode())
        return json.loads(raw) if raw else None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._receive, name="tdjson", daemon=True)
        self._thread.start()
        # erste Anfrage weckt die Instanz; ihr Zustand kommt als updateAuthorizationState
        self.send({"@type": "getOption", "name": "version"})

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def send(self, request: dict) -> None:
        self._lib.td_send(self.client, json.dumps(request).encode())

    async def call(self, request: dict, timeout: float) -> dict:
        """Anfrage senden und auf genau ihre Antwort warten; ``error`` wird zu TdError."""
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

    def _receive(self) -> None:
        while not self._stop.is_set():
            raw = self._lib.td_receive(1.0)
            if not raw:
                continue
            event = json.loads(raw)
            if event.get("@client_id") not in (None, self.client):
                continue
            self._loop.call_soon_threadsafe(self._dispatch, event)

    def _dispatch(self, event: dict) -> None:
        extra = event.get("@extra")
        if extra is not None:
            future = self._pending.get(str(extra))
            if future is not None and not future.done():
                future.set_result(event)
            return
        self.on_update(event)
