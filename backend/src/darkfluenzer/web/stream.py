"""Echtzeit-Hub des Cockpits: EIN binärer Protobuf-WebSocket je Browser (PHASENPLAN_FRONT_V1 F3).

STATE: vollständige kleine Projektion je Topic, Ordnung (generation, seq), Push nur bei Änderung.
EVENT: Ereignisse aus dem SQLite-Journal (Cursor = events.id); Catch-up nach Reconnect, dann live.
Der Hub kennt keine Fachlogik: Projektionen liefern Payload-Bytes, Journale liefern Zeilen.

Belastung (DF-PUSH): je Client wartet je STATE-Topic höchstens der neueste Frame (Latest-wins);
EVENT-Frames werden nie verworfen – übersteigt ihr Rückstand die Grenze, wird der Client mit 1013
getrennt und holt nach dem Reconnect ab seinem Cursor nach (Lücke ehrlich gemeldet).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import WSCloseCode, WSMsgType, web
from google.protobuf.message import DecodeError

from ..v1 import stream_pb2 as pb

PROTOCOL_MAJOR = 1
PROTOCOL_MINOR = 0
HELLO_TIMEOUT_S = 5.0
CLOSE_POLICY = 1008  # Protokollverletzung: der Client blockiert statt neu zu verbinden
CLOSE_SLOW = 1013  # Rückstand zu groß: der Client verbindet neu und holt nach

log = logging.getLogger("darkfluenzer.stream")

# Journalzeile: (Cursor, Commit-Zeit in Unix-ms, Payload)
EventRow = tuple[int, int, bytes]
# (nach Cursor, Höchstzahl) -> (neueste Zeilen aufsteigend, ältere ausgelassen?)
ReadEvents = Callable[[int, int], tuple[list[EventRow], bool]]


def schema_id(schemas: Path) -> str:
    """SHA-256 über alle .proto-Dateien (sortierter relativer Pfad + Inhalt, je mit Länge).
    Dasselbe Verfahren rechnet der Frontend-Build (frontend/vite.config.ts)."""
    digest = hashlib.sha256()
    files = {path.relative_to(schemas).as_posix(): path for path in schemas.rglob("*.proto")}
    for name in sorted(files):
        rel = name.encode()
        data = files[name].read_bytes()
        digest.update(len(rel).to_bytes(4, "big") + rel + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


@dataclass(eq=False)  # Identität als Schlüssel in der Client-Menge
class _Client:
    ws: web.WebSocketResponse
    limit: int
    states: set[int] = field(default_factory=set)
    # EVENT-Topic -> höchster Cursor, den dieser Client bereits hat (Grenze für Live-Push)
    events: dict[int, int] = field(default_factory=dict)
    # Wartende Frames: je STATE-Topic nur der neueste, Ereignisse/Nachzug in Reihenfolge
    pending_states: dict[int, bytes] = field(default_factory=dict)
    frames: deque[bytes] = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    overflow: bool = False

    def put_state(self, topic: int, data: bytes) -> None:
        self.pending_states[topic] = data  # Latest-wins: ein älterer, ungesendeter Stand entfällt
        self.wake.set()

    def put_frame(self, data: bytes) -> None:
        if len(self.frames) >= self.limit:
            self.overflow = True  # Ereignisse nie stillschweigend verwerfen: trennen, nachholen
        else:
            self.frames.append(data)
        self.wake.set()


@dataclass
class _EventTopic:
    read: ReadEvents
    published: int


class Hub:
    def __init__(
        self,
        schema: str,
        heartbeat_s: float,
        catchup_limit: int,
        head: Callable[[], int],
        client_queue_max: int,
    ) -> None:
        self.schema = schema
        self.heartbeat_s = heartbeat_s
        self.catchup_limit = catchup_limit
        self.client_queue_max = client_queue_max
        self._head = head
        self.generation = time.time_ns() // 1_000_000
        self._descriptors: dict[int, pb.TopicDescriptor] = {}
        self._states: dict[int, pb.StateFull] = {}
        self._events: dict[int, _EventTopic] = {}
        self._clients: set[_Client] = set()

    # ------------------------------------------------------------------ Topics

    def offer_state(self, topic: int, payload_type: str) -> None:
        self._descriptors[topic] = pb.TopicDescriptor(
            topic=topic, topic_class=pb.TOPIC_CLASS_STATE, payload_type=payload_type
        )

    def offer_events(self, topic: int, payload_type: str, read: ReadEvents) -> None:
        self._descriptors[topic] = pb.TopicDescriptor(
            topic=topic, topic_class=pb.TOPIC_CLASS_EVENT, payload_type=payload_type
        )
        self._events[topic] = _EventTopic(read=read, published=self._head())

    def set_state(self, topic: int, payload: bytes) -> None:
        """Neuen Zustand veröffentlichen; unveränderte Payloads erzeugen keinen Frame."""
        old = self._states.get(topic)
        if old is not None and old.payload == payload:
            return
        frame = pb.StateFull(
            topic=topic,
            generation=self.generation,
            seq=old.seq + 1 if old else 1,
            payload=payload,
        )
        self._states[topic] = frame
        data = pb.ServerMessage(state_full=frame).SerializeToString()
        for client in self._clients:
            if topic in client.states:
                client.put_state(topic, data)

    def push_events(self, topic: int) -> None:
        """Seit dem letzten Aufruf ins Journal geschriebene Ereignisse live verteilen."""
        et = self._events[topic]
        rows, gap = et.read(et.published, self.catchup_limit)
        if not rows:
            return
        et.published = rows[-1][0]
        for client in self._clients:
            if topic not in client.events:
                continue
            if gap:  # mehr neue Ereignisse als das Limit: Lücke ehrlich melden
                client.put_frame(self._catchup_complete(topic, gap=True))
            for row in rows:
                if row[0] > client.events[topic]:
                    client.put_frame(self._event(topic, row))
            client.events[topic] = max(client.events[topic], rows[-1][0])

    # ------------------------------------------------------------------ Verbindung

    async def serve(self, request: web.Request) -> web.WebSocketResponse:
        """Eine Browser-Verbindung: Hello/Welcome, Subscribe, geordnetes Senden, Heartbeat."""
        ws = web.WebSocketResponse(heartbeat=self.heartbeat_s, max_msg_size=4096)
        await ws.prepare(request)
        try:
            hello = await self._receive(ws, timeout=HELLO_TIMEOUT_S)
        except (TimeoutError, ValueError) as exc:
            await ws.close(code=CLOSE_POLICY, message=f"Hello erwartet: {exc}".encode()[:120])
            return ws
        if hello is None or hello.WhichOneof("msg") != "hello":
            await ws.close(code=CLOSE_POLICY, message=b"Hello erwartet")
            return ws
        welcome = self._welcome(hello.hello)
        await ws.send_bytes(pb.ServerMessage(welcome=welcome).SerializeToString())
        if welcome.status != pb.WELCOME_STATUS_ACCEPTED:
            log.info("Verbindung abgewiesen: %s", welcome.reject_reason)
            await ws.close()
            return ws

        client = _Client(ws, limit=self.client_queue_max)
        self._clients.add(client)
        writer = asyncio.create_task(self._write(ws, client))
        try:
            while True:
                try:
                    msg = await self._receive(ws, timeout=None)
                except ValueError as exc:
                    await ws.close(code=CLOSE_POLICY, message=str(exc).encode()[:120])
                    break
                if msg is None:
                    break
                if msg.WhichOneof("msg") != "subscribe" or not self._subscribe(
                    client, msg.subscribe
                ):
                    await ws.close(code=CLOSE_POLICY, message=b"Unerwartete Nachricht")
                    break
        finally:
            self._clients.discard(client)
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer
        return ws

    async def close_all(self) -> None:
        """Beim Beenden des Backends alle Browser sofort informieren (Code 1001), statt
        offene WebSockets bis zum Shutdown-Timeout hängen zu lassen."""
        for client in list(self._clients):
            await client.ws.close(code=WSCloseCode.GOING_AWAY, message=b"Backend wird beendet")

    def _welcome(self, hello: pb.Hello) -> pb.Welcome:
        w = pb.Welcome(
            protocol_major=PROTOCOL_MAJOR,
            protocol_minor=PROTOCOL_MINOR,
            schema_id=self.schema,
            heartbeat_interval_ms=int(self.heartbeat_s * 1000),
        )
        if hello.protocol_major != PROTOCOL_MAJOR:
            w.status = pb.WELCOME_STATUS_REJECTED_MAJOR
            w.reject_reason = f"Protokoll {hello.protocol_major}, Backend {PROTOCOL_MAJOR}"
        elif hello.schema_id != self.schema:
            w.status = pb.WELCOME_STATUS_REJECTED_SCHEMA
            w.reject_reason = "Frontend-Build passt nicht zum Backend-Schema"
        else:
            w.status = pb.WELCOME_STATUS_ACCEPTED
            w.topics.extend(self._descriptors.values())
        return w

    def _subscribe(self, client: _Client, sub: pb.Subscribe) -> bool:
        desc = self._descriptors.get(sub.topic)
        if desc is None:
            return False
        if desc.topic_class == pb.TOPIC_CLASS_STATE:
            client.states.add(sub.topic)
            frame = self._states.get(sub.topic)
            if frame is not None:
                client.put_state(sub.topic, pb.ServerMessage(state_full=frame).SerializeToString())
            return True
        # EVENT: Nachzug und Registrierung ohne await dazwischen -> keine Lücke, kein Überholen
        rows, gap = self._events[sub.topic].read(sub.after_cursor, self.catchup_limit)
        for row in rows:
            client.put_frame(self._event(sub.topic, row))
        through = max(self._head(), rows[-1][0] if rows else 0)
        client.put_frame(
            self._catchup_complete(sub.topic, gap=gap and sub.after_cursor > 0, through=through)
        )
        client.events[sub.topic] = through
        return True

    async def _write(self, ws: web.WebSocketResponse, client: _Client) -> None:
        """Einziger Sender je Client: neueste STATE-Frames, Ereignisse in Reihenfolge, Heartbeat
        bei Ruhe. Zu großer Ereignis-Rückstand -> Trennung mit 1013 (Nachholen nach Reconnect)."""
        beat = 0
        while not ws.closed:
            if client.overflow:
                log.warning("Client zu langsam (%d Frames offen) – getrennt", len(client.frames))
                await ws.close(code=CLOSE_SLOW, message=b"Rueckstand zu gross")
                return
            batch = list(client.pending_states.values()) + list(client.frames)
            client.pending_states.clear()
            client.frames.clear()
            client.wake.clear()
            if not batch:
                try:
                    await asyncio.wait_for(client.wake.wait(), timeout=self.heartbeat_s)
                    continue
                except TimeoutError:
                    beat += 1
                    batch = [
                        pb.ServerMessage(
                            heartbeat=pb.Heartbeat(
                                heartbeat_id=beat, server_unix_ms=time.time_ns() // 1_000_000
                            )
                        ).SerializeToString()
                    ]
            try:
                for data in batch:
                    await ws.send_bytes(data)
            except ConnectionError:
                return

    @staticmethod
    async def _receive(ws: web.WebSocketResponse, timeout: float | None) -> pb.ClientMessage | None:
        msg = await ws.receive(timeout=timeout)
        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
            return None
        if msg.type != WSMsgType.BINARY:
            raise ValueError("nur binäre Protobuf-Frames")
        try:
            return pb.ClientMessage.FromString(msg.data)
        except DecodeError as exc:
            raise ValueError("ClientMessage nicht lesbar") from exc

    def _event(self, topic: int, row: EventRow) -> bytes:
        cursor, committed_ms, payload = row
        return pb.ServerMessage(
            event=pb.Event(
                topic=topic, cursor=cursor, committed_unix_ms=committed_ms, payload=payload
            )
        ).SerializeToString()

    def _catchup_complete(self, topic: int, gap: bool, through: int | None = None) -> bytes:
        return pb.ServerMessage(
            catchup_complete=pb.CatchupComplete(
                topic=topic, through=self._head() if through is None else through, gap=gap
            )
        ).SerializeToString()
