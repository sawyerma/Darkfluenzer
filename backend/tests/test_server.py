"""Cockpit-Server: Schutzprüfungen, idempotente Befehle, STATE und EVENT mit Catch-up."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from darkfluenzer import server
from darkfluenzer.store import Store
from darkfluenzer.stream import PROTOCOL_MAJOR
from darkfluenzer.v1 import comfy_pb2, commands_pb2
from darkfluenzer.v1 import stream_pb2 as pb


def _run(cfg, scenario) -> None:
    async def main() -> None:
        app = server.create_app(cfg)
        async with TestClient(TestServer(app, host="127.0.0.1", port=cfg.server.port)) as client:
            await scenario(client, app, f"http://127.0.0.1:{cfg.server.port}")

    asyncio.run(main())


async def _csrf(client) -> str:
    resp = await client.get("/api/v1/session")
    assert resp.status == 204
    return resp.headers["X-CSRF-Token"]


async def _post(client, origin, csrf, req) -> tuple[int, bytes]:
    headers = {"Origin": origin, "Content-Type": "application/x-protobuf"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    resp = await client.post("/api/v1/command", data=req.SerializeToString(), headers=headers)
    return resp.status, await resp.read()


async def _handshake_status(client, origin) -> int:
    try:
        ws = await client.ws_connect("/ws/v1/stream", headers={"Origin": origin})
    except WSServerHandshakeError as exc:
        return exc.status
    await ws.close()
    return 101


async def _frame(ws) -> pb.ServerMessage:
    msg = await asyncio.wait_for(ws.receive(), timeout=5)
    return pb.ServerMessage.FromString(msg.data)


def test_guards_reject_foreign_host_origin_and_missing_tokens(cfg):
    async def scenario(client, app, origin):
        resp = await client.get("/", headers={"Host": f"evil.example:{cfg.server.port}"})
        assert resp.status == 403
        assert await _handshake_status(client, origin) == 401  # noch keine Sitzung
        csrf = await _csrf(client)
        assert await _handshake_status(client, "http://evil.example") == 403
        assert await _handshake_status(client, origin) == 101
        req = commands_pb2.CommandRequest(
            request_id=str(uuid.uuid4()), comfy_stop=commands_pb2.ComfyStop()
        )
        assert (await _post(client, origin, None, req))[0] == 403
        assert (await _post(client, "http://evil.example", csrf, req))[0] == 403

    _run(cfg, scenario)


def test_command_is_idempotent_per_request_id(cfg):
    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        rid = str(uuid.uuid4())
        stop = commands_pb2.CommandRequest(request_id=rid, comfy_stop=commands_pb2.ComfyStop())
        status, first = await _post(client, origin, csrf, stop)
        assert status == 200
        resp = commands_pb2.CommandResponse.FromString(first)
        assert resp.status == commands_pb2.COMMAND_STATUS_ACCEPTED
        assert (await _post(client, origin, csrf, stop))[1] == first  # keine zweite Ausführung
        start = commands_pb2.CommandRequest(request_id=rid, comfy_start=commands_pb2.ComfyStart())
        reused = commands_pb2.CommandResponse.FromString(
            (await _post(client, origin, csrf, start))[1]
        )
        assert reused.status == commands_pb2.COMMAND_STATUS_REJECTED
        assert "request_id" in reused.detail

    _run(cfg, scenario)


def test_stream_state_snapshot_event_catchup_gap_and_live(cfg):
    cfg = dataclasses.replace(
        cfg, server=dataclasses.replace(cfg.server, catchup_limit=2, observe_s=0.1)
    )
    store = Store(cfg.local)

    def finish_job(i: int) -> None:
        job = store.create_job(None, "lustify_sdxl", "lustify_sdxl_t2i", "p", {"seed": i}, [i])
        out = {"path": f"evaluation/x_{i}.png", "sha256": "0" * 64, "size": 1}
        store.set_job_status(job, "done", duration_s=1.5, outputs=[out])

    for i in range(4):
        finish_job(i)
    cursors = [row["id"] for row in store.finished_jobs(0, 10)[0]]

    async def scenario(client, app, origin):
        await _csrf(client)
        schema = app[server.HUB_KEY].schema

        ws = await client.ws_connect("/ws/v1/stream", headers={"Origin": origin})
        hello = pb.Hello(protocol_major=PROTOCOL_MAJOR, schema_id="anderes-schema")
        await ws.send_bytes(pb.ClientMessage(hello=hello).SerializeToString())
        assert (await _frame(ws)).welcome.status == pb.WELCOME_STATUS_REJECTED_SCHEMA
        await ws.close()

        ws = await client.ws_connect("/ws/v1/stream", headers={"Origin": origin})
        hello = pb.Hello(protocol_major=PROTOCOL_MAJOR, schema_id=schema)
        await ws.send_bytes(pb.ClientMessage(hello=hello).SerializeToString())
        welcome = (await _frame(ws)).welcome
        assert welcome.status == pb.WELCOME_STATUS_ACCEPTED
        assert {(d.topic, d.topic_class) for d in welcome.topics} == {
            (pb.TOPIC_COMFY_STATUS, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_JOB_COMPLETED, pb.TOPIC_CLASS_EVENT),
        }

        sub = pb.Subscribe(topic=pb.TOPIC_COMFY_STATUS)
        await ws.send_bytes(pb.ClientMessage(subscribe=sub).SerializeToString())
        state = (await _frame(ws)).state_full
        assert state.generation > 0 and state.seq >= 1
        comfy = comfy_pb2.ComfyStatus.FromString(state.payload)
        assert comfy.state == comfy_pb2.COMFY_STATE_STOPPED

        # Nachzug ab dem ersten Job: drei neuere, Limit 2 -> die neuesten zwei plus Lücke
        sub = pb.Subscribe(topic=pb.TOPIC_JOB_COMPLETED, after_cursor=cursors[0])
        await ws.send_bytes(pb.ClientMessage(subscribe=sub).SerializeToString())
        events = [(await _frame(ws)).event for _ in range(2)]
        assert [e.cursor for e in events] == cursors[2:]
        done = (await _frame(ws)).catchup_complete
        assert done.gap and done.through >= cursors[-1]

        finish_job(4)  # live: der Beobachter verteilt das neue Journal-Ereignis
        live = (await _frame(ws)).event
        assert live.cursor > done.through
        job = comfy_pb2.JobCompleted.FromString(live.payload)
        assert job.result == comfy_pb2.JOB_RESULT_DONE
        assert job.outputs[0].path == "evaluation/x_4.png" and job.order_no == ""
        await ws.close()

    try:
        _run(cfg, scenario)
    finally:
        store.close()
