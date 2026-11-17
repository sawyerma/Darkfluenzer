"""Cockpit-Server: Schutzprüfungen, idempotente Befehle, STATE und EVENT mit Catch-up."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import os
import shutil
import uuid

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from darkfluenzer.config import project_root
from darkfluenzer.media import models
from darkfluenzer.nodes import local as runtime
from darkfluenzer.nodes.base import node_for
from darkfluenzer.store import Store
from darkfluenzer.v1 import (
    character_pb2,
    comfy_pb2,
    commands_pb2,
    influencer_pb2,
    media_pb2,
    order_pb2,
)
from darkfluenzer.v1 import stream_pb2 as pb
from darkfluenzer.web import http as server
from darkfluenzer.web.stream import PROTOCOL_MAJOR


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
    comfy_copy = cfg.comfyui.path / "output" / "darkfluenzer" / "out_00001_.png"
    comfy_copy.parent.mkdir(parents=True)
    comfy_copy.write_bytes(b"png")  # ComfyUIs eigene Kopie derselben Ausgabe
    store = Store(cfg.local)
    store.add_media("evaluation/lustify_sdxl/out.png", hashlib.sha256(b"png").hexdigest(), 3)
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
        # Löschen: Datei samt byte-gleicher ComfyUI-Kopie weg, Index leer, andere Dateien bleiben
        delete = commands_pb2.DeleteMedia(media_ids=[page.items[0].media_id])
        req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), delete_media=delete)
        answer = commands_pb2.CommandResponse.FromString(
            (await _post(client, origin, await _csrf(client), req))[1]
        )
        assert answer.status == commands_pb2.COMMAND_STATUS_ACCEPTED, answer.detail
        assert not (evaluation / "out.png").exists() and not comfy_copy.exists()
        assert (evaluation / "other.png").exists()
        assert (await client.get(url)).status == 404
        page = media_pb2.MediaPage.FromString(await (await client.get("/api/v1/media-page")).read())
        assert not page.items

    _run(cfg, scenario)


async def _next_event(ws) -> pb.Event:
    frame = await _frame(ws)
    while frame.WhichOneof("msg") != "event":
        frame = await _frame(ws)
    return frame.event


def test_command_journal_cas_receipts_and_restart(cfg):
    """Befehlsjournal in SQLite: CAS gegen die Registry-Version, Receipts ACCEPTED -> COMPLETED
    mit neuer Version, Idempotenz auch über einen Neustart (keine zweite Ausführung)."""
    t2i = "lustify_sdxl_t2i"
    rid = str(uuid.uuid4())
    seen: dict = {}

    async def first(client, app, origin):
        csrf = await _csrf(client)
        version = app[server.COCKPIT_KEY]._registry_version
        off = commands_pb2.SetWorkflowEnabled(workflow=t2i, enabled=False)
        stale = commands_pb2.CommandRequest(
            request_id=str(uuid.uuid4()), expected_version=version + 1, set_workflow_enabled=off
        )
        refused = commands_pb2.CommandResponse.FromString(
            (await _post(client, origin, csrf, stale))[1]
        )
        assert (
            refused.status == commands_pb2.COMMAND_STATUS_REJECTED and "geändert" in refused.detail
        )
        assert models.load_manifest(cfg.root).workflows[t2i].enabled is True

        ws = await _stream_after_catchup(client, app, origin, pb.TOPIC_COMMAND_RECEIPT)
        req = commands_pb2.CommandRequest(
            request_id=rid, expected_version=version, set_workflow_enabled=off
        )
        status, body = await _post(client, origin, csrf, req)
        answer = commands_pb2.CommandResponse.FromString(body)
        assert status == 200 and answer.status == commands_pb2.COMMAND_STATUS_ACCEPTED
        assert answer.entity == f"workflow:{t2i}"
        receipts = [
            commands_pb2.CommandReceipt.FromString((await _next_event(ws)).payload)
            for _ in range(2)
        ]
        assert [r.status for r in receipts] == [
            commands_pb2.COMMAND_STATUS_ACCEPTED,
            commands_pb2.COMMAND_STATUS_COMPLETED,
        ]
        assert receipts[1].request_id == rid and receipts[1].version == version + 1
        assert models.load_manifest(cfg.root).workflows[t2i].enabled is False
        await ws.close()
        start = commands_pb2.CommandRequest(request_id=rid, comfy_start=commands_pb2.ComfyStart())
        reused = commands_pb2.CommandResponse.FromString(
            (await _post(client, origin, csrf, start))[1]
        )
        assert (
            reused.status == commands_pb2.COMMAND_STATUS_REJECTED and "request_id" in reused.detail
        )
        seen.update(req=req, body=body)

    _run(cfg, first)  # danach setzt _run die Registry zurück (Workflow wieder aktiviert)
    store = Store(cfg.local)  # ein beim Beenden offener ComfyUI-Start: Ergebnis unbekannt
    interrupted = str(uuid.uuid4())
    store.record_command(interrupted, "0" * 64, "comfy_start", "accepted")
    store.close()

    async def again(client, app, origin):  # neuer Server, dieselbe Datenbank
        csrf = await _csrf(client)
        assert (await _post(client, origin, csrf, seen["req"]))[1] == seen["body"]
        assert models.load_manifest(cfg.root).workflows[t2i].enabled is True  # nicht erneut
        assert app[server.COCKPIT_KEY].store.command(interrupted)["status"] == "unknown"

    _run(cfg, again)


def test_stream_state_snapshot_event_catchup_gap_and_live(cfg):
    cfg = dataclasses.replace(
        cfg, server=dataclasses.replace(cfg.server, catchup_limit=2, observe_s=0.1)
    )
    store = Store(cfg.local)

    def finish_job(i: int) -> None:
        job = store.create_job(None, "lustify_sdxl", "lustify_sdxl_t2i", "p", {"seed": i}, [i])
        out = {"path": f"evaluation/x_{i}.png", "sha256": f"{i:064d}", "size": 1}
        store.add_media(out["path"], out["sha256"], 1, job_id=job)  # Ausgabe in der Galerie
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
            (pb.TOPIC_COMFY_INSTANCES, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_RESOURCES, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_JOBS_ACTIVE, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_COMFY_WORKFLOWS, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_CHARACTERS, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_ORDERS_ACTIVE, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_CHANNELS, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_JOB_COMPLETED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_ORDER_UPDATED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_REFERENCE_ADDED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_PAYMENT_UPDATED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_WALLET, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_INFLUENCERS, pb.TOPIC_CLASS_STATE),
            (pb.TOPIC_CUSTOMER_UPDATED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_CONVERSATION_EVENT, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_MEDIA_ADDED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_MEDIA_REMOVED, pb.TOPIC_CLASS_EVENT),
            (pb.TOPIC_COMMAND_RECEIPT, pb.TOPIC_CLASS_EVENT),
        }

        sub = pb.Subscribe(topic=pb.TOPIC_COMFY_INSTANCES)
        await ws.send_bytes(pb.ClientMessage(subscribe=sub).SerializeToString())
        state = (await _frame(ws)).state_full
        assert state.generation > 0 and state.seq >= 1
        (comfy,) = comfy_pb2.ComfyInstances.FromString(state.payload).instances
        assert comfy.name == "media" and comfy.state == comfy_pb2.COMFY_STATE_STOPPED

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

    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        cockpit = app[server.COCKPIT_KEY]

        def cmd(**kw):  # Registry-Befehle tragen die gesehene Registry-Version (CAS)
            return commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()), expected_version=cockpit._registry_version, **kw
            )

        def render():
            prompt = commands_pb2.ParamValue(name="prompt", text="studio portrait, adult woman")
            return cmd(render=commands_pb2.Render(workflow=t2i, values=[prompt]))

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
        assert held.adapter_get("comfyui", "media", "paused") == "1"  # übersteht Neustart
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
        assert node_for(cfg, cfg.comfyui).editor_file("portraet_neu").is_file()
        assert "vergeben" in (await answer(cmd(create_workflow=new))).detail
        edit = commands_pb2.CreateWorkflow(source="lustify_sam31_edit", title="Ausziehen Neu")
        assert (await answer(cmd(create_workflow=edit))).detail == ""
        assert models.load_manifest(cfg.root).workflows["ausziehen_neu"].mask_output == "19"

        gone = "lustify_sdxl_refine"
        files = [cfg.root / "workflows" / f for f in ("image/lustify_sdxl_refine.api.json",)]
        assert (
            await answer(cmd(delete_workflow=commands_pb2.DeleteWorkflow(workflow=gone)))
        ).detail == ""
        assert gone not in models.load_manifest(cfg.root).workflows
        assert not any(f.exists() for f in files)
        assert not node_for(cfg, cfg.comfyui).editor_file(gone).exists()
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


def test_client_queue_keeps_latest_state_and_never_drops_events():
    from darkfluenzer.web.stream import _Client

    client = _Client(ws=None, limit=2)
    client.put_state(1, b"alt")
    client.put_state(1, b"neu")
    assert client.pending_states == {1: b"neu"}  # Latest-wins je STATE-Topic
    client.put_frame(b"e1")
    client.put_frame(b"e2")
    assert not client.overflow
    client.put_frame(b"e3")  # über der Grenze: nicht verwerfen, sondern trennen und nachholen
    assert client.overflow and list(client.frames) == [b"e1", b"e2"]


def test_provenance_of_a_rendered_medium(cfg):
    store = Store(cfg.local)
    job = store.create_job(
        None, "lustify_sdxl", "lustify_sdxl_t2i", "p", {"seed": 7, "prompt": "p"}, [7]
    )
    graph = {"5": {"class_type": "KSampler", "inputs": {"seed": 7, "model": ["1", 0]}}}
    store.set_job_submitted(job, "prompt-x", graph, "b" * 64)
    out = cfg.local / "evaluation" / "lustify_sdxl" / "x_20261115T000000Z_01.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"png")
    rel = out.relative_to(cfg.local).as_posix()
    memory = {"ram_total_gb": 128.0, "ram_free_min_gb": 50.0, "swap_max_mb": 10.0}
    store.set_job_status(job, "done", duration_s=2.5, outputs=[], memory=memory)
    media_id = store.add_media(rel, hashlib.sha256(b"png").hexdigest(), 3, job_id=job)
    # abgeleitete Version: Verfeinern mit diesem Medium als Ausgang (F7.6)
    child_job = store.create_job(
        None, "lustify_sdxl", "lustify_sdxl_refine", "", {}, [], parent_media_id=media_id
    )
    child = store.add_media(
        rel.replace("_01", "_02"), hashlib.sha256(b"png2").hexdigest(), 4, job_id=child_job
    )
    store.close()

    async def scenario(client, app, origin):
        await _csrf(client)
        resp = await client.get(f"/api/v1/provenance/{media_id}")
        assert resp.status == 200
        prov = media_pb2.MediaProvenance.FromString(await resp.read())
        assert prov.job_id == job and prov.workflow == "lustify_sdxl_t2i"
        assert prov.workflow_title and prov.prompt_id == "prompt-x"
        assert prov.params["seed"] == "7" and prov.duration_s == 2.5
        assert [
            (n.id, n.class_type, [(i.name, i.value) for i in n.inputs]) for n in prov.graph
        ] == [
            ("5", "KSampler", [("seed", "7")])  # Verbindungen ausgelassen
        ]
        assert prov.memory.ram_free_min_gb == 50.0
        assert list(prov.child_media_ids) == [child]
        resp = await client.get(f"/api/v1/provenance/{child}")
        assert media_pb2.MediaProvenance.FromString(await resp.read()).parent_media_id == media_id
        assert (await client.get("/api/v1/provenance/999999")).status == 404

    _run(cfg, scenario)


def test_characters_state_pushes_training_folder_changes(cfg):
    """Trainingsdatenordner per Push: neue, fertig kopierte Bilder erscheinen geprüft im STATE."""
    from PIL import Image

    cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, observe_s=0.1))
    photos = cfg.local / "character" / "photos"
    photos.mkdir(parents=True)

    async def scenario(client, app, origin):
        await _csrf(client)
        ws = await client.ws_connect("/ws/v1/stream", headers={"Origin": origin})
        hello = pb.Hello(protocol_major=PROTOCOL_MAJOR, schema_id=app[server.HUB_KEY].schema)
        await ws.send_bytes(pb.ClientMessage(hello=hello).SerializeToString())
        assert (await _frame(ws)).welcome.status == pb.WELCOME_STATUS_ACCEPTED
        sub = pb.Subscribe(topic=pb.TOPIC_CHARACTERS)
        await ws.send_bytes(pb.ClientMessage(subscribe=sub).SerializeToString())
        first = character_pb2.Characters.FromString((await _frame(ws)).state_full.payload)
        (char,) = first.characters
        assert char.photos_dir == "local/character/photos" and not char.photos
        assert char.usable == 0 and char.min_images > 0

        for name, side in (("gross.png", 1024), ("klein.png", 512)):
            Image.new("RGB", (side, side), (side % 255, 40, 90)).save(photos / name)
            os.utime(photos / name, (1, 1))  # fertig kopiert (älter als die Ruhezeit)
        later = character_pb2.Characters.FromString((await _frame(ws)).state_full.payload)
        (char,) = later.characters
        assert {(p.name, p.status) for p in char.photos} == {
            ("gross.png", "ok"),
            ("klein.png", "too_small"),
        }
        assert char.usable == 1 and later.version > first.version
        await ws.close()

    _run(cfg, scenario)


def test_character_profiles_command(cfg):
    """Befehl 25: Profil 1 = local/character; neues Profil mit eigenem Ordner; CAS; nur
    existierende Trainingsdatenordner; Influencerin des Default-Kontakts = Profil."""

    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        store = app[server.COCKPIT_KEY].store

        async def send(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        (first,) = store.characters()
        assert (first["name"], first["photos_dir"]) == ("Charakter 01", "local/character/photos")
        new = commands_pb2.CharacterUpdate(name="Charakter 02")
        assert await send(character_update=new) == ""
        second = store.characters()[1]
        assert second["data_dir"] == "local/characters/2"
        assert (cfg.root / "local/characters/2/photos").is_dir()  # eigener Ordner angelegt
        upd = commands_pb2.CharacterUpdate(character_id=2, revision=5, name="X")
        assert "geändert" in await send(character_update=upd)  # CAS
        upd = commands_pb2.CharacterUpdate(character_id=2, name="Mia", photos_dir="gibt/es/nicht")
        assert "existiert nicht" in await send(character_update=upd)
        upd = commands_pb2.CharacterUpdate(character_id=2, name="Mia", photos_dir=str(cfg.root))
        assert await send(character_update=upd) == ""
        assert store.character(2)["photos_dir"] == str(cfg.root)
        await app[server.COCKPIT_KEY].refresh_characters()

    _run(cfg, scenario)


def test_influencer_profile_for_all_customers(cfg):
    """Befehl 35 (FRONT F4 V1.12 Punkt 12): Profil mit Charakterbezug und Preisliste, CAS,
    Prüfung der Preise; der Default-Kontakt wählt ein Profil; STATE 9 mit fester Regel."""

    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store

        async def send(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        def update(**kw):
            base = {"name": "Clara", "character_id": 1, "persona": "warm, direkt"}
            return commands_pb2.InfluencerUpdate(**(base | kw))

        price = influencer_pb2.PriceItem
        prices = [price(product="Foto", price_cents=2499, hd_surcharge_cents=500)]
        assert await send(influencer_update=update(prices=prices)) == ""
        (clara,) = store.influencers()
        assert clara["prices"] == [
            {"product": "Foto", "price_cents": 2499, "hd_surcharge_cents": 500}
        ]
        bad = [price(product="Foto", price_cents=0)]
        assert "Preisliste" in await send(influencer_update=update(influencer_id=1, prices=bad))
        stale = update(influencer_id=1, revision=7, ai_notice="Hi, ich bin KI-Creatorin")
        assert "geändert" in await send(influencer_update=stale)  # CAS
        ok = update(influencer_id=1, revision=0, ai_notice="Hi, ich bin KI-Creatorin")
        assert await send(influencer_update=ok) == ""
        (clara,) = store.influencers()
        assert clara["revision"] == 1 and clara["prices"] == []  # Liste vollständig ersetzt
        assert "unbekannt" in await send(influencer_update=update(character_id=99))
        state = influencer_pb2.Influencers.FromString(cockpit._influencers())
        assert state.honesty_rule and state.influencers[0].ai_notice.startswith("Hi")
        d = store.default_contact()
        unknown = commands_pb2.DefaultContactUpdate(
            revision=d["revision"], approval_mode="cockpit", influencer="9"
        )
        assert "unbekanntes Profil" in await send(default_contact_update=unknown)
        chosen = commands_pb2.DefaultContactUpdate(
            revision=d["revision"], approval_mode="cockpit", influencer="1"
        )
        assert await send(default_contact_update=chosen) == ""

    _run(cfg, scenario)


def test_order_commands_push_stages_and_retry(cfg):
    """Auftrag per Befehl: Receipt, STATE 4 per Push, fehlgeschlagene Stufe, Wiederholen."""
    cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, observe_s=0.1))
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows")
    man = models.load_manifest(cfg.root)
    for mf in man.engine_files("lustify_sdxl"):  # Modell "vorhanden" (sparse)
        target = models.models_dir(cfg.root) / mf.target
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:
            fh.truncate(mf.size)

    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        cockpit = app[server.COCKPIT_KEY]

        async def answer(**kw):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()), expected_version=cockpit._registry_version, **kw
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body)

        ws = await client.ws_connect("/ws/v1/stream", headers={"Origin": origin})
        hello = pb.Hello(protocol_major=PROTOCOL_MAJOR, schema_id=app[server.HUB_KEY].schema)
        await ws.send_bytes(pb.ClientMessage(hello=hello).SerializeToString())
        assert (await _frame(ws)).welcome.status == pb.WELCOME_STATUS_ACCEPTED
        sub = pb.Subscribe(topic=pb.TOPIC_ORDERS_ACTIVE)
        await ws.send_bytes(pb.ClientMessage(subscribe=sub).SerializeToString())
        first = order_pb2.OrdersActive.FromString((await _frame(ws)).state_full.payload)
        assert not first.orders and first.candidates_default == 3 and first.candidates_max == 6

        async def stage_until(status: str, attempts: int) -> order_pb2.OrderStage:
            while True:
                state = order_pb2.OrdersActive.FromString((await _frame(ws)).state_full.payload)
                stages = [s for o in state.orders for s in o.stages]
                if stages and stages[0].status == status and stages[0].attempts == attempts:
                    return stages[0]

        prompt = commands_pb2.ParamValue(name="prompt", text="studio portrait")
        create = commands_pb2.CreateOrder(workflow="lustify_sdxl_t2i", values=[prompt])
        too_many = commands_pb2.CreateOrder(
            workflow="lustify_sdxl_t2i", values=[prompt], candidates=7
        )
        assert "Höchstens 6" in (await answer(create_order=too_many)).detail
        done = await answer(create_order=create)
        assert done.status == commands_pb2.COMMAND_STATUS_ACCEPTED and done.entity.startswith(
            "order:"
        )
        order_no = done.entity.removeprefix("order:")
        assert Store(cfg.local).command(done.request_id)["status"] == "completed"
        # Test-ComfyUI kennt kein /prompt: alle drei Kandidaten scheitern -> Stufe fehlgeschlagen
        failed = await stage_until("failed", 1)
        assert failed.kind == "candidates" and len(failed.jobs) == 3 and failed.error

        pick = commands_pb2.SelectCandidate(order_no=order_no, media_id=1)
        assert "wartet nicht" in (await answer(select_candidate=pick)).detail
        retry = commands_pb2.RetryStage(order_no=order_no, seq=1)
        assert (await answer(retry_stage=retry)).detail == ""
        again = await stage_until("failed", 2)
        assert len(again.jobs) == 6
        await ws.close()

    _run(cfg, scenario)


def test_render_worker_survives_a_failing_after_job(cfg, monkeypatch):
    """SP1 Schritt 2: wirft die Nachbearbeitung (hier der Kloner-Rückversand), protokolliert die
    Bahn den Fehler, schickt die Pushes trotzdem und führt den nächsten Job aus."""
    import asyncio
    import types

    from darkfluenzer.core import orders as core_orders
    from darkfluenzer.core import render as core_render

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        lane = cockpit.lanes["media"]
        jobs = {
            1: {"status": "queued", "engine": "x", "stage_id": 7},
            2: {"status": "queued", "engine": "x", "stage_id": None},
        }
        ran, pushed = [], []

        async def admit(_lane, _job, _engine):
            return True

        async def delivery(order_id, selected=None):
            raise RuntimeError("Rückversand kaputt")

        monkeypatch.setattr(cockpit.store, "job", lambda job_id: dict(jobs[job_id]))
        monkeypatch.setattr(cockpit.store, "stage", lambda sid: types.SimpleNamespace(order_id=3))
        monkeypatch.setattr(cockpit, "_admit", admit)
        monkeypatch.setattr(cockpit, "_cloner_delivery", delivery)
        monkeypatch.setattr(cockpit, "_orders_changed", lambda: pushed.append("orders"))
        monkeypatch.setattr(core_orders, "advance_order", lambda store, job_id: None)
        monkeypatch.setattr(
            core_render.pipeline, "run_render", lambda cfg, man, job_id, **kw: ran.append(job_id)
        )
        lane.renders.put_nowait(1)
        lane.renders.put_nowait(2)
        for _ in range(100):
            if ran == [1, 2] and len(pushed) == 2:
                break
            await asyncio.sleep(0.05)
        assert ran == [1, 2] and pushed == ["orders", "orders"]
        assert lane.running_job == 0

    _run(cfg, scenario)


def test_queue_shows_unknown_stall_and_estimate_and_notifies_once(cfg, monkeypatch):
    """SP1 Schritt 2: läuft ein Job, während ComfyUI nicht antwortet, bleibt er sichtbar mit
    Zustand unbekannt; Stillstand ist ein Hinweis (genau einmal), die Dauer eine Schätzung."""
    import asyncio
    import time

    cfg = dataclasses.replace(
        cfg, production=dataclasses.replace(cfg.production, stall_notice_s=300)
    )

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        lane = cockpit.lanes["media"]
        notices = []

        async def notice(job_id, quiet):
            notices.append(job_id)

        monkeypatch.setattr(cockpit, "_stall_notice", notice)
        earlier = store.create_job(None, "e", "wf_lang", "p", {}, [])
        store.set_job_status(earlier, "done", duration_s=120.0, outputs=[])
        job = store.create_job(None, "e", "wf_lang", "p", {}, [])
        store.set_job_status(job, "running")
        lane.running_job = job
        lane.started_at = lane.progress_at = time.time() - 1000
        await cockpit._watch_runs()
        await cockpit._watch_runs()
        await asyncio.sleep(0.2)
        assert notices == [job]  # genau ein Hinweis, kein Abbruch
        lane.status = {}  # ComfyUI antwortet nicht
        lane.queue = []
        shown = [
            j
            for j in comfy_pb2.JobsActive.FromString(cockpit._jobs_active()).jobs
            if j.job_id == job
        ]
        assert len(shown) == 1 and shown[0].running and shown[0].unknown
        assert shown[0].stalled_s >= 1000 and shown[0].elapsed_s >= 1000
        assert shown[0].estimate_s == 120 and shown[0].remaining_s == 0
        assert store.job(job)["status"] == "running"  # nichts automatisch beendet

    _run(cfg, scenario)


def test_order_cancel_stops_all_jobs_of_the_order(cfg):
    """SP1 Schritt 11 (Befehl 59): alle wartenden Jobs eines Auftrags werden entfernt, der
    Betreiber-Auftrag geht auf abgebrochen; ein Auftrag ohne offene Jobs wird abgewiesen."""

    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        await cockpit.lanes["media"].resume.wait()
        for lane in cockpit.lanes.values():  # nichts soll die Jobs vorher starten
            lane.resume.clear()
        order = store.create_production_order("operator", "image", "Test")
        stage = store.add_stage(order.id, "candidates", "wf", {}, 2)
        jobs = [
            store.create_job(order.order_no, "e", "wf", "p", {}, [], stage_id=stage.id)
            for _ in range(2)
        ]
        other = store.create_job(None, "e", "wf", "p", {}, [])

        async def answer(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body)

        cancel = commands_pb2.OrderCancel(order_no=order.order_no)
        assert (await answer(order_cancel=cancel)).detail == ""
        assert [store.job(j)["status"] for j in jobs] == ["failed", "failed"]
        assert store.job(other)["status"] == "queued"  # fremde Jobs bleiben
        assert store.order(order.order_no).status == "cancelled"
        again = await answer(order_cancel=cancel)
        assert again.status == commands_pb2.COMMAND_STATUS_REJECTED
        assert "keine wartenden oder laufenden" in again.detail

    _run(cfg, scenario)


def test_command_status_endpoint(cfg):
    """SP2 Schritt 11 (SPEC-011): Quittung aus dem Journal, ACCEPTED während der Ausführung,
    404 nur ohne beides; ohne Sitzung 401."""
    import asyncio

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        anon = await client.get("/api/v1/command/egal")
        assert anon.status == 401
        csrf = await _csrf(client)
        rid = str(uuid.uuid4())
        req = commands_pb2.CommandRequest(
            request_id=rid, pause_queue=commands_pb2.PauseQueue(paused=False)
        )
        status, _ = await _post(client, origin, csrf, req)
        assert status == 200
        resp = await client.get(f"/api/v1/command/{rid}")
        assert resp.status == 200 and resp.headers["Content-Type"].startswith(server.PROTOBUF)
        receipt = commands_pb2.CommandReceipt.FromString(await resp.read())
        assert receipt.request_id == rid and receipt.command == "pause_queue"
        assert receipt.status == commands_pb2.COMMAND_STATUS_COMPLETED
        running = str(uuid.uuid4())
        cockpit._inflight[running] = asyncio.get_running_loop().create_future()
        resp = await client.get(f"/api/v1/command/{running}")
        assert commands_pb2.CommandReceipt.FromString(await resp.read()).status == (
            commands_pb2.COMMAND_STATUS_ACCEPTED
        )
        del cockpit._inflight[running]
        assert (await client.get(f"/api/v1/command/{uuid.uuid4()}")).status == 404

    _run(cfg, scenario)
