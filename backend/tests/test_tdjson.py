"""Ein TDLib-Empfänger je Prozess (SP2 Schritt 4) mit einer Ersatz-Bibliothek: zwei Instanzen
erhalten je ihre Ereignisse über denselben Thread; Abmelden und neues Anmelden ohne Verlust und
ohne zweiten Thread; ``close`` meldet ab; offene Anfragen scheitern beim Schließen sichtbar."""

from __future__ import annotations

import asyncio
import itertools
import json
import queue
import threading

import pytest

from darkfluenzer.channels.tdjson import Receiver, TdError, TdJson


class FakeLib:
    """``td_*`` wie libtdjson: Instanz-IDs, Sendeliste, eine Ereignis-Warteschlange."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.events: queue.Queue[bytes] = queue.Queue()
        self.sent: list[tuple[int, dict]] = []
        self.receivers: set[int] = set()  # Threads, die td_receive aufgerufen haben

    def td_create_client_id(self) -> int:
        return next(self._ids)

    def td_send(self, client: int, raw: bytes) -> None:
        request = json.loads(raw)
        self.sent.append((client, request))
        if "@extra" in request:  # jede Anfrage bekommt ihre Antwort
            self.push(client, {"@type": "ok", "@extra": request["@extra"]})
        if request["@type"] in ("close", "logOut"):
            self.push(client, _auth("authorizationStateClosed"))

    def td_receive(self, timeout: float) -> bytes | None:
        self.receivers.add(threading.get_ident())
        try:
            return self.events.get(timeout=min(timeout, 0.05))
        except queue.Empty:
            return None

    def td_execute(self, raw: bytes) -> bytes | None:
        return None

    def push(self, client: int, event: dict) -> None:
        self.events.put(json.dumps({**event, "@client_id": client}).encode())


def _auth(state: str) -> dict:
    return {"@type": "updateAuthorizationState", "authorization_state": {"@type": state}}


@pytest.fixture
def lib(tmp_path):
    fake = FakeLib()
    yield fake, tmp_path / "libtdjson.dylib"
    Receiver._all.pop(str(tmp_path / "libtdjson.dylib")).stop()


async def _until(check, seconds: float = 2.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Bedingung nicht erreicht")


def _tdjson_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "tdjson")


def test_two_clients_each_get_their_events_over_one_thread(lib):
    fake, path = lib

    async def scenario():
        loop = asyncio.get_running_loop()
        before = _tdjson_threads()
        a, b = TdJson(path, loop, lib=fake), TdJson(path, loop, lib=fake)
        got_a, got_b = [], []
        a.on_update, b.on_update = got_a.append, got_b.append
        a.start()
        b.start()
        assert _tdjson_threads() == before + 1  # genau ein Empfangsthread
        fake.push(a.client, {"@type": "updateNewMessage", "n": 1})
        fake.push(b.client, {"@type": "updateNewMessage", "n": 2})
        fake.push(99, {"@type": "updateNewMessage", "n": 3})  # unbekannte Instanz: verworfen
        assert (await a.call({"@type": "getMe"}, 2))["@type"] == "ok"
        assert (await b.call({"@type": "getMe"}, 2))["@type"] == "ok"
        await _until(lambda: got_a and got_b)
        assert [e["n"] for e in got_a] == [1] and [e["n"] for e in got_b] == [2]
        assert len(fake.receivers) == 1  # td_receive nur aus einem Thread

    asyncio.run(scenario())


def test_logout_and_new_login_lose_nothing_and_add_no_thread(lib):
    """Wie der Adapter nach ``authorizationStateClosed``: neue Instanz am selben Empfänger."""
    fake, path = lib

    async def scenario():
        loop = asyncio.get_running_loop()
        other = TdJson(path, loop, lib=fake)  # zweites Konto läuft durch
        got_other: list[dict] = []
        other.on_update = got_other.append
        other.start()
        threads = _tdjson_threads()
        first = TdJson(path, loop, lib=fake)
        states: list[str] = []
        first.on_update = lambda e: states.append(e.get("authorization_state", {}).get("@type"))
        first.start()
        receiver = Receiver.of(path)
        thread = receiver.thread
        await first.call({"@type": "logOut"}, 2)
        await _until(lambda: first.closed)
        assert "authorizationStateClosed" in states
        assert first.client not in receiver.clients()  # abgemeldet
        second = TdJson(path, loop, lib=fake)  # neu anmelden
        got: list[dict] = []
        second.on_update = got.append
        second.start()
        for n in range(20):
            fake.push(second.client, {"@type": "updateNewMessage", "n": n})
            fake.push(other.client, {"@type": "updateNewMessage", "n": n})
        await _until(lambda: len(got) == 20 and len(got_other) == 20)
        assert [e["n"] for e in got] == list(range(20))  # nichts verloren, Reihenfolge erhalten
        assert receiver.thread is thread and _tdjson_threads() == threads
        assert len(fake.receivers) == 1

    asyncio.run(scenario())


def test_close_unregisters_and_fails_open_requests(lib):
    fake, path = lib

    async def scenario():
        loop = asyncio.get_running_loop()
        td = TdJson(path, loop, lib=fake)
        td.start()
        fake.td_send = lambda client, raw: fake.sent.append((client, json.loads(raw)))
        waiting = asyncio.ensure_future(td.call({"@type": "getMe"}, 5))  # Antwort kommt nie
        await asyncio.sleep(0.05)
        td.close()
        assert fake.sent[-1] == (td.client, {"@type": "close"})
        fake.push(td.client, _auth("authorizationStateClosed"))
        assert await td.wait_closed(2)
        with pytest.raises(TdError):
            await waiting
        with pytest.raises(TdError):
            await td.call({"@type": "getMe"}, 1)  # geschlossen: keine Anfrage mehr
        assert td.client not in Receiver.of(path).clients()
        td.close()  # zweites Schließen sendet nichts mehr
        assert sum(1 for _, r in fake.sent if r["@type"] == "close") == 1

    asyncio.run(scenario())
