"""Default-Kette (SP1 Schritte 6–9, 11, 12): Optionen aus dem Wunsch und Ausgabeprofil je Befehl,
Stapel und Kandidaten, Abschluss mit Rückversand genau einmal, Fehlschlag und Abbruch mit Grund,
Default-Sendungen zuerst und ohne Verzögerung, Chat-Wort zum Abbrechen, Betriebsart je Konto,
Befehl 37 additiv."""

from __future__ import annotations

import asyncio
import time
import uuid

from test_channels import BOT, _cloner_setup, _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_orders import _finish
from test_server import _csrf, _post, _run

from darkfluenzer.core import cloner_text
from darkfluenzer.v1 import channel_pb2, commands_pb2
from darkfluenzer.web import http as server


def test_options_from_the_wish():
    assert cloner_text.options("roter Bikini, 9:16") == ("9:16", None, "roter Bikini")
    assert cloner_text.options("9:16, 8 sek, Strand") == ("9:16", 8.0, "Strand")
    assert cloner_text.options("animate 2,5s") == ("", 2.5, "animate")
    assert cloner_text.options("Strand") == ("", None, "Strand")
    heights = (1440, 1350, 1080, 1920)
    assert cloner_text.finish_height(heights, (768, 1344)) == 1920  # 9:16 → Story
    assert cloner_text.finish_height(heights, (896, 1216)) == 1440  # 3:4


def _items(store, customer_id):
    return store.conversation_items(customer_id, 0, 80)[0]


def _cards(store, customer_id):
    return [i["text"] for i in _items(store, customer_id) if i["direction"] == "system"]


def _profiles(store, commands, **fields):
    default = store.default_contact()
    store.update_default_contact(default["revision"], fields, {}, commands)


def test_output_profile_and_wish_options(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        _cloner_setup(cfg, store, auto=True)
        _profiles(store, {"clone": {"workflow": "lustify_sdxl_t2i", "format": "3:4",
                                    "finish": "output_instagram"}})  # fmt: skip
        default = store.default_contact()
        opts = cockpit._cloner_options("lustify_sdxl_t2i", "clone", "Strand", default)
        assert opts["values"] == {"width": 896, "height": 1216} and opts["wish"] == "Strand"
        assert opts["finish"] == "output_instagram" and opts["finish_values"] == {"height": 1440}
        story = cockpit._cloner_options("lustify_sdxl_t2i", "clone", "9:16 Strand", default)
        assert story["values"] == {"width": 768, "height": 1344}
        assert story["finish_values"] == {"height": 1920}  # BUG-090
        assert "gibt es bei" in cockpit._cloner_options("lustify_sdxl_t2i", "clone", "2:3", default)
        assert "nur bei Video" in cockpit._cloner_options(
            "lustify_sdxl_t2i", "clone", "5s", default
        )
        refine = cockpit._cloner_options("lustify_sdxl_refine", "clone", "9:16", default)
        assert "kein Format" in refine
        video = cockpit._cloner_options("wan22_remix_v30_i2v", "animate", "8s langsam", default)
        assert video["values"] == {"duration_s": 8.0} and video["wish"] == "langsam"
        _profiles(store, {"animate": {"workflow": "", "duration_s": 6}})
        video = cockpit._cloner_options(
            "wan22_remix_v30_i2v", "animate", "", store.default_contact()
        )
        assert video["values"] == {"duration_s": 6.0}

    _run(cfg, scenario)


def test_batch_candidates_parent_and_figure(cloner_cfg, monkeypatch):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        clara = store.save_influencer(0, 0, "Clara", None, "", "", [])
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"influencer": str(clara)}, {})
        wf = cockpit.manifest.workflows
        assert cockpit._cloner_candidates(wf["lustify_sdxl_refine"]) == 1  # Vorgabe
        _profiles(store, {}, candidates=2)
        assert cockpit._cloner_candidates(wf["lustify_sdxl_refine"]) == 2
        assert cockpit._cloner_candidates(wf["output_instagram"]) == 1  # ohne Seed
        assert cockpit._cloner_candidates(wf["wan22_remix_v30_i2v"]) == 1  # Video
        _profiles(store, {}, candidates=None)
        pics = []
        for n in (1, 2, 3):
            src = cfg.local / photo["path"]
            dst = src.with_name(f"1_{n}.png")
            dst.write_bytes(src.read_bytes())
            pics.append(photo | {"path": str(dst.relative_to(cfg.local)), "sha256": f"{n}" * 64})
        media = store.add_media(pics[0]["path"], "1" * 64, 10)  # eigenes Medium
        msg = send("1", "remix Strand", "1", pics)
        await cockpit._on_inbound(msg)
        rows = store.db.execute("SELECT id FROM orders ORDER BY id").fetchall()
        assert len(rows) == 3  # ein Bild-Eingang: je Bild ein Auftrag
        stage = store.stages(rows[0][0])[0]
        assert stage.params["influencer"] == clara and stage.params["command"] == "remix"
        job = store.stage_jobs(stage.id)[0]
        assert store.job(job["id"])["parent_media_id"] == media
        answer = _items(store, msg.customer.id)[-1]["text"]
        assert "DF-O-000001 … DF-O-000003" in answer and "3 Aufträge" in answer
        monkeypatch.setattr(cockpit, "_not_startable", lambda wf: "")
        _profiles(store, {"animate": {"workflow": "ltx25_flf2v"}})
        plan = cockpit._cloner_plan(
            store.message(send("2", "animate", "2", [pics[0]]).message_id),
            store.default_contact(), "animate",
        )  # fmt: skip
        assert "braucht genau 2 Bilder" in plan
        clip = photo | {"kind": "video", "path": pics[1]["path"]}
        plan = cockpit._cloner_plan(
            store.message(send("3", "remix", "3", [clip]).message_id),
            store.default_contact(), "remix",
        )  # fmt: skip
        assert "Video als Referenz" in plan

    _run(cfg, scenario)


async def _order_of(store, send, cockpit, photo, update, text="remix"):
    msg = send(update, text, update, [photo])
    await cockpit._on_inbound(msg)
    order_id = store.db.execute("SELECT max(id) FROM orders").fetchone()[0]
    return msg, store.order_by_id(order_id)


def test_completion_returns_each_result_once(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)  # Freigabe „direkt“
        msg, order = await _order_of(store, send, cockpit, photo, "1")
        (job,) = store.stage_jobs(store.stages(order.id)[0].id)
        _finish(cfg, store, job["id"])
        await cockpit._cloner_delivery(order.id)
        await cockpit._cloner_delivery(order.id)  # wiederholt: nichts doppelt
        assert store.order(order.order_no).status == "review"  # genau eins: automatisch gewählt
        assert len(store.cloner_returns(order.id)) == 1
        outs = [i for i in _items(store, msg.customer.id) if i["direction"] == "out"]
        assert outs[-1]["text"] == order.order_no and outs[-1]["attachments"]
        assert any("· ZURÜCKGESENDET" in c for c in _cards(store, msg.customer.id))
        # direkt mit zwei Kandidaten: beide zurück, Stufe ohne Auswahl geschlossen
        _profiles(store, {}, candidates=2)
        _, two = await _order_of(store, send, cockpit, photo, "2")
        for j in store.stage_jobs(store.stages(two.id)[0].id):
            _finish(cfg, store, j["id"])
        await cockpit._cloner_delivery(two.id)
        assert len(store.cloner_returns(two.id)) == 2
        assert (
            store.stages(two.id)[0].status == "done"
            and store.order(two.order_no).status == "review"
        )
        # Freigabe im Cockpit: wartet auf die Auswahl, dann genau das Gewählte
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"approval_mode": "cockpit"}, {})
        _, pick = await _order_of(store, send, cockpit, photo, "3")
        jobs = store.stage_jobs(store.stages(pick.id)[0].id)
        medias = [_finish(cfg, store, j["id"], color=200 + n) for n, j in enumerate(jobs)]
        await cockpit._cloner_delivery(pick.id)
        assert store.cloner_returns(pick.id) == []
        req = commands_pb2.CommandRequest(
            request_id=str(uuid.uuid4()),
            select_candidate=commands_pb2.SelectCandidate(
                order_no=pick.order_no, media_id=medias[1]
            ),
        )
        csrf = await _csrf(client)
        status, body = await _post(client, origin, csrf, req)
        assert status == 200 and commands_pb2.CommandResponse.FromString(body).detail == ""
        assert [r["media_id"] for r in store.cloner_returns(pick.id)] == [medias[1]]

    _run(cfg, scenario)


def test_finish_stage_failure_and_cancel_are_reported(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        _profiles(store, {"remix": {"workflow": "", "finish": "output_instagram"}})
        msg, order = await _order_of(store, send, cockpit, photo, "1")
        (job,) = store.stage_jobs(store.stages(order.id)[0].id)
        _finish(cfg, store, job["id"])
        await cockpit._cloner_delivery(order.id)  # automatisch gewählt -> Fertigstellen läuft
        stages = store.stages(order.id)
        assert [s.kind for s in stages] == ["candidates", "finish"]
        assert store.cloner_returns(order.id) == []
        (fin,) = store.stage_jobs(stages[1].id)
        finished = _finish(cfg, store, fin["id"], color=99)
        await cockpit._cloner_delivery(order.id)
        assert [r["media_id"] for r in store.cloner_returns(order.id)] == [finished]
        _profiles(store, {})
        _, bad = await _order_of(store, send, cockpit, photo, "2")
        (job,) = store.stage_jobs(store.stages(bad.id)[0].id)
        _finish(cfg, store, job["id"], ok=False)
        await cockpit._cloner_delivery(bad.id)
        await cockpit._cloner_delivery(bad.id)
        cards = [c for c in _cards(store, msg.customer.id) if "· FEHLGESCHLAGEN" in c]
        assert len(cards) == 1 and "ComfyUI-Fehler" in cards[0]
        # Chat-Wort bricht den laufenden Auftrag dieses Chats ab (SP1 Schritt 11)
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"cancel_word": "stopp"}, {})
        _, running = await _order_of(store, send, cockpit, photo, "3")
        await cockpit._on_inbound(send("4", "Stopp", "4"))
        assert store.order(running.order_no).status == "cancelled"
        assert any(f"{running.order_no} · vom Betreiber" in c and "· ABGEBROCHEN" in c
                   for c in _cards(store, msg.customer.id))  # fmt: skip
        await cockpit._on_inbound(send("5", "stopp", "5"))
        assert _items(store, msg.customer.id)[-1]["text"] == "Nichts zum Abbrechen."

    _run(cfg, scenario)


def test_operating_mode_per_account(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        store.import_channel_account({"key": "tg", "platform": "telegram"})
        store.set_account_platform_id("tg", BOT)
        store.set_account_mode("tg", "off")
        first = send("1", "remix", "1", [photo])
        await cockpit._on_inbound(first)
        assert [i["direction"] for i in _items(store, first.customer.id)] == ["in"]  # nur anzeigen
        store.set_account_mode("tg", "test")
        await cockpit._on_inbound(send("2", "remix", "2", [photo]))
        await cockpit._on_inbound(send("3", "remix", "3", [photo]))  # Hinweis nur einmal
        outs = [i for i in _items(store, first.customer.id) if i["direction"] == "out"]
        assert [o["text"] for o in outs] == [cloner_text.TEST_MODE]
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        store.set_account_mode("tg", "production")
        await cockpit._on_inbound(send("4", "remix", "4", [photo]))
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == 1

    _run(cfg, scenario)


def test_default_messages_first_and_without_delay(cfg, tmp_path):
    from test_telegram import TEST_CHAT, _account, _msg

    from darkfluenzer.store import Store

    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)
    asyncio.run(acc._message(_msg(TEST_CHAT, 10)))
    customer = inbound[0]
    conv = customer.conversation_id
    store.queue_outbound(
        customer.customer.id, conv, "an Kunden", revision=store.conversation_revision(conv)
    )
    default = store.default_contact()
    store.update_default_contact(default["revision"], {}, {("telegram", acc.account): "99"})
    internal = store.record_inbound(
        "telegram", acc.account, "d1", sender_id="99", conversation_id="99",
        platform_message_id="d1", text="clone", sent_at="2026-11-18T09:00:00+00:00",
    )  # fmt: skip
    assert internal.customer.kind == "internal"
    own = internal.conversation_id
    store.queue_outbound(
        internal.customer.id, own, "an Default", revision=store.conversation_revision(own)
    )
    items = store.outbox("telegram", acc.account)
    assert [i["text"] for i in items] == ["an Default", "an Kunden"]
    started = time.monotonic()
    asyncio.run(acc._pace(items[0]))
    assert time.monotonic() - started < 1.0  # ohne Antwortverzögerung und Tippanzeige
    assert not any(c["@type"] == "sendChatAction" for c in acc._td.sent)
    store.close()


def test_command_37_validates_and_round_trips(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        _cloner_setup(cfg, store, auto=True)
        store.import_channel_account({"key": "tg", "platform": "telegram"})
        csrf = await _csrf(client)

        async def update(**kw):
            d = store.default_contact()
            base = dict(revision=d["revision"], approval_mode="direct", process_commands=True,
                        telegram_sender_id="99",
                        auto_orders=True, media_workflow="lustify_sdxl_refine")  # fmt: skip
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                default_contact_update=commands_pb2.DefaultContactUpdate(**(base | kw)),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        cw = channel_pb2.CommandWorkflow
        assert "gibt es bei" in await update(command_workflows=[cw(command="clone", format="2:3")])
        assert "nur bei Video" in await update(
            command_workflows=[cw(command="clone", duration_s=5)]
        )
        assert "nicht möglich" in await update(
            command_workflows=[cw(command="animate", finish="output_instagram")]
        )
        assert "kein Befehl" in await update(cancel_word="clone")
        assert "höchstens" in await update(cloner_candidates=99)
        assert "unbekannt" in await update(
            account_modes=[channel_pb2.AccountMode(key="x", mode="off")]
        )
        ok = await update(
            command_workflows=[
                cw(
                    command="clone",
                    workflow="lustify_sdxl_t2i",
                    format="9:16",
                    finish="output_instagram",
                )
            ],  # fmt: skip
            cloner_candidates=2,
            cancel_word="stopp",
            account_modes=[channel_pb2.AccountMode(key="tg", mode="test")],
        )
        assert ok == ""
        cust = store.default_contact()["customer_id"]
        page = channel_pb2.ConversationPage.FromString(
            await (await client.get(f"/api/v1/conversation-page?customer={cust}")).read()
        )
        d = page.default_contact
        clone = next(c for c in d.command_workflows if c.command == "clone")
        assert (clone.workflow, clone.format, clone.finish) == ("lustify_sdxl_t2i", "9:16",
                                                                "output_instagram")  # fmt: skip
        assert d.cloner_candidates == 2 and d.cloner_candidates_default == 1
        assert d.cancel_word == "stopp"
        assert [(m.key, m.mode) for m in d.account_modes] == [("tg", "test")]

    _run(cfg, scenario)


def test_cloner_binds_the_active_lora_of_the_figure(cloner_cfg):  # noqa: F811
    """SP3 Schritte 8/9: der Kloner lädt die aktive LoRA der Figur des Default-Kontakts (nur
    wenn der Workflow sie laden darf); ohne aktive LoRA „ohne Charakter-LoRA“."""
    from darkfluenzer.media import models, pipeline

    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        slug = store.character(1)["slug"]
        clara = store.save_influencer(0, 0, "Clara", 1, "", "", [])
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"influencer": str(clara)}, {})
        await cockpit._on_inbound(send("1", "remix", "1", [photo]))
        first = store.order_by_id(store.db.execute("SELECT max(id) FROM orders").fetchone()[0])
        assert not store.stages(first.id)[0].params.get(pipeline.LORA_KEY)
        assert any(
            "ohne Charakter-LoRA" in c
            for c in _cards(store, store.default_contact()["customer_id"])
        )
        lora = models.Lora(
            key="figur_sdxl", target=f"loras/characters/{slug}/figur_sdxl.safetensors", size=1,
            sha256="c" * 64, base_engine="lustify_sdxl",
            base_file=cockpit.manifest.engines["lustify_sdxl"].files[0], dataset="ds",
            trigger="dfchar", steps=10, rank=16, learning_rate=1e-4, strength=0.8,
            status="OFFEN", created_at="t", trainer="t", character=slug,
        )  # fmt: skip
        cockpit.manifest = models.register_lora(cfg.root, lora)
        store.set_active_lora(1, "sdxl", "figur_sdxl")
        await cockpit._on_inbound(send("2", "remix", "2", [photo]))
        second = store.order_by_id(store.db.execute("SELECT max(id) FROM orders").fetchone()[0])
        assert store.stages(second.id)[0].params[pipeline.LORA_KEY] == "figur_sdxl"
        assert any(
            "LoRA figur_sdxl" in c for c in _cards(store, store.default_contact()["customer_id"])
        )

    _run(cfg, scenario)
