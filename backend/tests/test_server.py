"""Cockpit-Server: Schutzprüfungen, idempotente Befehle, STATE und EVENT mit Catch-up."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import shutil
import uuid

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from darkfluenzer import comfy, models, runtime, server
from darkfluenzer.config import project_root
from darkfluenzer.store import Store
from darkfluenzer.stream import PROTOCOL_MAJOR
from darkfluenzer.v1 import comfy_pb2, commands_pb2, media_pb2
from darkfluenzer.v1 import stream_pb2 as pb


def _run(cfg, scenario) -> None:
    # Echte Registry; Modelldateien fehlen im Testprojekt (Workflows dann "nicht bereit").
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)

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


def test_media_only_indexed_files_with_session_page_and_download(cfg):
    evaluation = cfg.local / "evaluation" / "lustify_sdxl"
    evaluation.mkdir(parents=True)
    (evaluation / "out.png").write_bytes(b"png")
    (evaluation / "other.png").write_bytes(b"other")
    (evaluation / "escape.png").symlink_to(cfg.local / "config.toml")
    store = Store(cfg.local)
    store.add_media("evaluation/lustify_sdxl/out.png", "c" * 64, 3)
    store.close()

    async def scenario(client, app, origin):
        url = "/api/v1/media/evaluation/lustify_sdxl/out.png"
        assert (await client.get(url)).status == 401
        assert (await client.get("/api/v1/media-page")).status == 401
        await _csrf(client)
        resp = await client.get(url)
        assert resp.status == 200 and await resp.read() == b"png"
        download = await client.get(url + "?download=1")
        assert "attachment" in download.headers["Content-Disposition"]
        for unindexed in ("other.png", "escape.png"):
            assert (
                await client.get(f"/api/v1/media/evaluation/lustify_sdxl/{unindexed}")
            ).status == 404
        assert (await client.get("/api/v1/media/config.toml")).status == 404
        page = media_pb2.MediaPage.FromString(await (await client.get("/api/v1/media-page")).read())
        assert [(i.caption, i.path) for i in page.items] == [
            ("0001", "evaluation/lustify_sdxl/out.png")
        ]

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
            (pb.TOPIC_JOBS_ACTIVE, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_COMFY_WORKFLOWS, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_JOB_COMPLETED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_MEDIA_ADDED, pb.TOPIC_CLASS_EVENT),
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


async def _stream_after_catchup(client, app, origin, topic):
    """Angemeldeter WebSocket mit abgeschlossenem Nachzug für ``topic``."""
    ws = await client.ws_connect("/ws/v1/stream", headers={"Origin": origin})
    hello = pb.Hello(protocol_major=PROTOCOL_MAJOR, schema_id=app[server.HUB_KEY].schema)
    await ws.send_bytes(pb.ClientMessage(hello=hello).SerializeToString())
    assert (await _frame(ws)).welcome.status == pb.WELCOME_STATUS_ACCEPTED
    await ws.send_bytes(pb.ClientMessage(subscribe=pb.Subscribe(topic=topic)).SerializeToString())
    while (await _frame(ws)).WhichOneof("msg") != "catchup_complete":
        pass
    return ws


def test_workflow_commands_enable_render_fifo_and_delete(cfg):
    cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, observe_s=0.1))
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows")
    man = models.load_manifest(cfg.root)
    for mf in man.engine_files("lustify_sdxl"):  # Modell "vorhanden" (Größe laut Registry, sparse)
        target = models.models_dir(cfg.root) / mf.target
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:
            fh.truncate(mf.size)
    t2i = "lustify_sdxl_t2i"

    def cmd(**kw):
        return commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)

    def render():
        prompt = commands_pb2.ParamValue(name="prompt", text="studio portrait, adult woman")
        return cmd(render=commands_pb2.Render(workflow=t2i, values=[prompt]))

    async def scenario(client, app, origin):
        csrf = await _csrf(client)

        async def answer(req):
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body)

        off = commands_pb2.SetWorkflowEnabled(workflow=t2i, enabled=False)
        assert (await answer(cmd(set_workflow_enabled=off))).detail == ""
        assert models.load_manifest(cfg.root).workflows[t2i].enabled is False
        refused = await answer(render())
        assert refused.status == commands_pb2.COMMAND_STATUS_REJECTED
        assert "deaktiviert" in refused.detail

        on = commands_pb2.SetWorkflowEnabled(workflow=t2i, enabled=True)
        assert (await answer(cmd(set_workflow_enabled=on))).detail == ""
        # großer Befehl (1 MB Datei) wird vollständig gelesen und fachlich beurteilt, nicht 400
        big = commands_pb2.InputFile(param="prompt", filename="x.png", data=os.urandom(1 << 20))
        too_much = cmd(render=commands_pb2.Render(workflow=t2i, files=[big]))
        assert "kein Upload-Parameter" in (await answer(too_much)).detail
        ws = await _stream_after_catchup(client, app, origin, pb.TOPIC_JOB_COMPLETED)

        async def next_job() -> comfy_pb2.JobCompleted:
            frame = await _frame(ws)
            while frame.WhichOneof("msg") != "event":
                frame = await _frame(ws)
            return comfy_pb2.JobCompleted.FromString(frame.event.payload)

        # Angehalten: Auftrag bleibt eingereiht; Entfernen -> ENTFERNT mit seinen Parametern
        pause = commands_pb2.PauseQueue(paused=True)
        assert (await answer(cmd(pause_queue=pause))).detail == ""
        assert (await answer(render())).status == commands_pb2.COMMAND_STATUS_ACCEPTED
        held = Store(cfg.local)
        (queued_id, _), *rest = held.queued_jobs()
        held.close()
        assert rest == []
        cancel = commands_pb2.CancelJob(job_id=queued_id)
        assert (await answer(cmd(cancel_job=cancel))).detail == ""
        removed = await next_job()
        assert removed.result == comfy_pb2.JOB_RESULT_CANCELLED
        assert removed.params["prompt"] == "studio portrait, adult woman"
        resume = commands_pb2.PauseQueue(paused=False)
        assert (await answer(cmd(pause_queue=resume))).detail == ""

        assert (await answer(render())).status == commands_pb2.COMMAND_STATUS_ACCEPTED
        job = await next_job()
        # Test-ComfyUI kennt kein /prompt: der echte Renderpfad lief und meldet den Fehler
        assert job.workflow == t2i and job.result == comfy_pb2.JOB_RESULT_FAILED and job.error
        await ws.close()

        new = commands_pb2.CreateWorkflow(source=t2i, title="Porträt Neu")
        assert (await answer(cmd(create_workflow=new))).detail == ""
        created = models.load_manifest(cfg.root).workflows["portraet_neu"]
        assert created.engine == "lustify_sdxl" and created.status == "OFFEN"
        assert set(created.params) == set(man.workflows[t2i].params)
        assert comfy.editor_file(cfg, "portraet_neu").is_file()
        assert "vergeben" in (await answer(cmd(create_workflow=new))).detail

        gone = "lustify_sdxl_refine"
        files = [cfg.root / "workflows" / f for f in ("image/lustify_sdxl_refine.api.json",)]
        assert (
            await answer(cmd(delete_workflow=commands_pb2.DeleteWorkflow(workflow=gone)))
        ).detail == ""
        assert gone not in models.load_manifest(cfg.root).workflows
        assert not any(f.exists() for f in files) and not comfy.editor_file(cfg, gone).exists()
        assert all(
            (models.models_dir(cfg.root) / mf.target).exists()
            for mf in man.engine_files("lustify_sdxl")
        )
        store = Store(cfg.local)
        assert store.job(job.job_id)["workflow"] == t2i  # Historie bleibt
        store.close()

    try:
        _run(cfg, scenario)
    finally:
        runtime.stop(cfg)
