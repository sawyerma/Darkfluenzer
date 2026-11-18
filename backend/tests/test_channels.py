"""Kanal-Basis (V0 §6, C2): Eingang genau einmal, Kundenliste/Verlauf, Antwortziel-Prüfung,
Default-Kontakt, Postausgang nach Neustart."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from test_server import _csrf, _post, _run

from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import channel_pb2, commands_pb2
from darkfluenzer.web import http as server

BOT = "7000001"


def _inbound(store: Store, update: str, sender: str, text: str, message: str):
    return store.record_inbound(
        "telegram",
        BOT,
        update,
        sender_id=sender,
        conversation_id=sender,
        platform_message_id=message,
        text=text,
        sent_at="2026-11-15T20:00:00+00:00",
        handle=f"user{sender}",
    )


def test_inbound_once_outbox_cas_and_restart(tmp_path):
    store = Store(tmp_path / "local")
    first = _inbound(store, "1", "42", "hallo", "10")
    assert first.new_customer and first.message_id
    assert _inbound(store, "1", "42", "hallo", "10").message_id is None  # erneut zugestellt
    (ident,) = store.identities(first.customer.id)
    with pytest.raises(StoreError, match="fortgesetzt"):  # veraltete Revision
        store.queue_outbound(first.customer.id, first.conversation_id, "hi", revision=0)
    out = store.queue_outbound(
        first.customer.id, first.conversation_id, "hi", revision=ident["revision"]
    )
    other = _inbound(store, "2", "43", "x", "11")
    with pytest.raises(StoreError, match="gehört nicht"):  # fremde Konversation
        store.queue_outbound(other.customer.id, first.conversation_id, "x", revision=2)
    assert [m["id"] for m in store.outbox("telegram", BOT)] == [out]
    store.set_message_status(out, "sending")
    store.close()
    store = Store(tmp_path / "local")  # Neustart mitten im Versand: kein blindes Wiederholen
    assert store.settle_sending() == [out]
    assert store.message(out)["status"] == "unknown" and store.outbox("telegram", BOT) == []
    store.close()


def test_default_contact_takes_over_own_id(tmp_path):
    store = Store(tmp_path / "local")
    default = store.default_contact()
    mine = _inbound(store, "1", "99", "hallo", "1")  # Betreiber schreibt dem Bot zuerst
    assert mine.customer.kind == "customer"
    updated = store.update_default_contact(
        default["revision"], {"approval_mode": "direct"}, {("telegram", BOT): "99"}
    )
    assert updated["sender_ids"] == {"telegram": "99"} and updated["approval_mode"] == "direct"
    with pytest.raises(StoreError, match="unbekannt"):  # leere Fehl-Akte ist entfernt
        store.customer_by_id(mine.customer.id)
    again = _inbound(store, "2", "99", "clone", "2")
    assert again.customer.kind == "internal" and again.customer.id == default["customer_id"]
    assert [i["text"] for i in store.conversation_items(again.customer.id, 0, 10)[0]] == [
        "hallo",
        "clone",
    ]
    with pytest.raises(StoreError, match="geändert"):  # CAS
        store.update_default_contact(default["revision"], {}, {})
    store.close()


def test_pages_reply_guard_and_mark_read(cfg):
    store = Store(cfg.local)
    a = _inbound(store, "1", "42", "hallo", "10")
    _inbound(store, "2", "43", "guten tag", "11")
    store.close()

    async def scenario(client, app, origin):
        csrf = await _csrf(client)

        async def answer(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body)

        page = channel_pb2.CustomerPage.FromString(
            await (await client.get("/api/v1/customer-page")).read()
        )
        assert [c.kind for c in page.customers][0] == "internal"  # Default zuerst
        assert {c.unread for c in page.customers if c.kind == "customer"} == {1}
        mine = next(c for c in page.customers if c.customer_id == a.customer.id)
        assert list(mine.handles) == ["42", "user42"]  # Suche nach Plattformkennung (F7.2)
        conv = channel_pb2.ConversationPage.FromString(
            await (await client.get(f"/api/v1/conversation-page?customer={a.customer.id}")).read()
        )
        assert [i.text for i in conv.items] == ["hallo"] and not conv.more
        (ident,) = conv.identities
        assert ident.platform == "telegram" and ident.conversation_id == a.conversation_id

        def reply(**kw):
            base = {
                "customer_id": a.customer.id,
                "identity_id": ident.identity_id,
                "conversation_id": ident.conversation_id,
                "platform": "telegram",
                "revision": ident.revision,
                "text": "hi",
            }
            return commands_pb2.SendReply(**(base | kw))

        assert "passt nicht" in (await answer(send_reply=reply(platform=""))).detail  # „Gesamt“
        assert "passt nicht" in (await answer(send_reply=reply(platform="instagram"))).detail
        assert "passt nicht" in (await answer(send_reply=reply(conversation_id=999))).detail
        assert "nicht verbunden" in (await answer(send_reply=reply())).detail  # kein Bot-Token
        read = commands_pb2.MarkRead(customer_id=a.customer.id, up_to_item=conv.items[-1].item_id)
        assert (await answer(mark_read=read)).detail == ""
        page = channel_pb2.CustomerPage.FromString(
            await (await client.get("/api/v1/customer-page")).read()
        )
        unread = {c.customer_id: c.unread for c in page.customers}
        assert unread[a.customer.id] == 0
        assert app[server.COCKPIT_KEY].telegram is None  # Testprojekt ohne [telegram]

    _run(cfg, scenario)


def _cloner_setup(cfg, store: Store, *, auto: bool):
    """Default-Kontakt mit Telegram-ID 99, Medien-Workflow „Verfeinern“ und einem Referenzfoto;
    liefert ``send(update, text, message, files)`` und den Fotoanhang."""
    from PIL import Image

    default = store.default_contact()
    store.update_default_contact(
        default["revision"],
        {"media_workflow": "lustify_sdxl_refine", "approval_mode": "direct", "auto_orders": auto},
        {("telegram", BOT): "99"},
    )
    ref = cfg.local / "channels" / "telegram" / "99" / "1_0.png"
    ref.parent.mkdir(parents=True)
    Image.new("RGB", (64, 64), (200, 30, 30)).save(ref)
    photo = {
        "kind": "photo",
        "status": "saved",
        "path": "channels/telegram/99/1_0.png",
        "sha256": "a" * 64,
        "size": ref.stat().st_size,
        "mime": "image/png",
    }

    def send(update: str, text: str, message: str, files=()):
        inbound = _inbound(store, update, "99", text, message)
        if inbound.message_id and files:
            store.set_attachments(inbound.message_id, list(files))
        return inbound

    return send, photo


@pytest.fixture
def cloner_cfg(cfg):
    """Projekt mit den echten Workflows und (leeren) LUSTIFY-Modelldateien."""
    import shutil

    from darkfluenzer.config import project_root
    from darkfluenzer.media import models

    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    for mf in models.load_manifest(cfg.root).engine_files("lustify_sdxl"):  # Modell vorhanden
        target = models.models_dir(cfg.root) / mf.target
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:
            fh.truncate(mf.size)
    return cfg


def test_cloner_switch_creates_one_internal_order(cloner_cfg):
    """Default-Absender + Befehl + Referenzbild -> genau ein Kloner-Auftrag mit Systemkarte;
    freie Anweisung -> genau eine Rückfrage; erneut zugestelltes Ereignis -> nichts."""
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)

        first = send("1", "remix roter Bikini", "1", [photo])
        assert first.customer.kind == "internal"
        await cockpit._on_inbound(first)
        await cockpit._on_inbound(send("1", "remix roter Bikini", "1"))  # Duplikat: message_id None
        orders = store.db.execute("SELECT order_no, source FROM orders").fetchall()
        assert [tuple(o) for o in orders] == [("DF-O-000001", "cloner")]
        items, _ = store.conversation_items(first.customer.id, 0, 20)
        assert [i["direction"] for i in items] == ["in", "system"]
        assert items[1]["text"].startswith("INTERNER AUFTRAG · REMIX · TELEGRAM")
        await _csrf(client)  # Sitzung für die Verlaufsseite
        conv = channel_pb2.ConversationPage.FromString(
            await (
                await client.get(f"/api/v1/conversation-page?customer={first.customer.id}")
            ).read()
        )
        card = conv.items[1]  # Karte trägt den Auftrag mit Stufe und Kandidaten (F4)
        assert card.order.order_no == "DF-O-000001" and not card.awaiting_start
        assert [st.kind for st in card.order.stages] == ["candidates"]
        assert len(card.order.stages[0].jobs) == cfg.production.candidates_default
        # jedes Auftragsereignis liefert die Karte erneut (Push statt Abfrage)
        events, _ = store.message_events(0, 100)
        before = [e["message_id"] for e in events].count(card.item_id)
        store.transition("DF-O-000001", "cancelled")
        events, _ = store.message_events(0, 100)
        assert [e["message_id"] for e in events].count(card.item_id) == before + 1
        free = send("2", "mach mir schöne Fotos", "2")
        await cockpit._on_inbound(free)
        items, _ = store.conversation_items(first.customer.id, 0, 20)
        assert items[-1]["direction"] == "out" and items[-1]["status"] == "queued"
        assert "Befehl" in items[-1]["text"]

    _run(cfg, scenario)


def test_cloner_waits_for_operator_start(cloner_cfg):
    """Automatische Produktionsaufträge aus: der erkannte Auftrag wartet sichtbar und startet
    genau einmal per Befehl aus dem Cockpit (V0 §8)."""
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=False)
        first = send("1", "clone 9:16", "1", [photo])
        await cockpit._on_inbound(first)
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        csrf = await _csrf(client)
        conv = channel_pb2.ConversationPage.FromString(
            await (
                await client.get(f"/api/v1/conversation-page?customer={first.customer.id}")
            ).read()
        )
        card = conv.items[-1]
        assert card.direction == "system" and card.awaiting_start and not card.order.order_no

        async def start(item_id):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                start_cloner_order=commands_pb2.StartClonerOrder(item_id=item_id),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert await start(conv.items[0].item_id) == "Kein wartender Kloner-Auftrag."
        assert await start(card.item_id) == ""
        assert "bereits gestartet" in await start(card.item_id)  # genau einmal
        orders = store.db.execute("SELECT order_no, source FROM orders").fetchall()
        assert [tuple(o) for o in orders] == [("DF-O-000001", "cloner")]
        row = store.message(card.item_id)
        assert row["order_id"] and "DF-O-000001" in row["text"]

    _run(cfg, scenario)


def test_animate_uses_the_video_workflow(cloner_cfg):
    """`animate` braucht den Video-Workflow des Default-Kontakts; das Backend nimmt nur passende
    Workflow-Arten an (Medien = Bild, animate = Video)."""
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        first = send("1", "animate langsam zur Kamera drehen", "1", [photo])
        await cockpit._on_inbound(first)
        items, _ = store.conversation_items(first.customer.id, 0, 20)
        assert "Kein Video-Workflow (animate)" in items[-1]["text"]
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        csrf = await _csrf(client)

        async def update(**kw):
            d = store.default_contact()
            base = {
                "revision": d["revision"],
                "telegram_sender_id": "99",
                "approval_mode": "direct",
                "process_commands": True,
                "auto_orders": True,
                "media_workflow": "lustify_sdxl_refine",
            }
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                default_contact_update=commands_pb2.DefaultContactUpdate(**(base | kw)),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert "kein Medien-Workflow" in await update(media_workflow="wan22_remix_v30_i2v")
        assert "kein Video-Workflow" in await update(video_workflow="lustify_sdxl_refine")
        assert await update(video_workflow="wan22_remix_v30_i2v") == ""
        assert store.default_contact()["video_workflow"] == "wan22_remix_v30_i2v"
        page = channel_pb2.ConversationPage.FromString(
            await (
                await client.get(f"/api/v1/conversation-page?customer={first.customer.id}")
            ).read()
        )
        assert page.default_contact.video_workflow == "wan22_remix_v30_i2v"

    _run(cfg, scenario)


def test_reference_library_from_files_and_cloner(cloner_cfg):
    """Vorlagen (C1): ein Vorlagen-Parameter legt die Datei genau einmal in der Bibliothek an
    (EVENT 25, reference-page); Vorlage per ID nur für Vorlagen-Parameter; der Kloner-Eingang
    landet ebenfalls in der Bibliothek."""
    import hashlib

    from PIL import Image

    from darkfluenzer.v1 import reference_pb2

    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        # „image“ von Verfeinern als Vorlagen-Parameter (wie ein künftiger Vorlagen-Workflow)
        params = cockpit.manifest.workflows["lustify_sdxl_refine"].params
        params["image"] = dataclasses.replace(params["image"], reference=True)
        img = cfg.local / "evaluation" / "x" / "bild.png"
        img.parent.mkdir(parents=True)
        Image.new("RGB", (64, 80), (10, 120, 200)).save(img)
        data = img.read_bytes()
        media = store.add_media(
            img.relative_to(cfg.local).as_posix(), hashlib.sha256(data).hexdigest(), len(data)
        )
        csrf = await _csrf(client)
        version = cockpit._registry_version

        async def render(**file):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                expected_version=version,
                render=commands_pb2.Render(
                    workflow="lustify_sdxl_refine",
                    files=[commands_pb2.InputFile(param="image", filename="bild.png", **file)],
                ),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert await render(media_id=media) == ""
        assert await render(media_id=media) == ""  # gleicher Inhalt: keine zweite Vorlage
        page = reference_pb2.ReferencePage.FromString(
            await (await client.get("/api/v1/reference-page")).read()
        )
        (ref,) = page.items
        assert ref.source == f"media:{media}" and ref.analysis == "none"
        assert ref.sha256 == hashlib.sha256(data).hexdigest()
        events, _ = store.reference_events(0, 10)
        assert [e["reference_id"] for e in events] == [ref.reference_id]
        assert await render(reference_id=ref.reference_id) == ""  # Vorlage aus der Bibliothek
        (cfg.local / ref.path).write_bytes(b"anders")
        assert "verändert" in await render(reference_id=ref.reference_id)  # SHA-Prüfung

        send, photo = _cloner_setup(cfg, store, auto=True)
        first = send("1", "clone", "1", [photo])
        await cockpit._on_inbound(first)
        sources = [r["source"] for r in store.reference_page(0, 10)[0]]
        assert sources[0] == f"telegram:{first.message_id}" and len(sources) == 2

    _run(cfg, scenario)


def test_content_tier_age_mark_and_ai_notice(cloner_cfg):
    """Regel 13: Stufe aus Workflow und Ausgangsmedium (fail-closed), Anheben per Befehl 43;
    Befehl 44 Altersangabe; Regel 12 b: KI-Hinweis genau einmal, Karte erst beim Versand."""
    import hashlib

    from darkfluenzer.media import pipeline

    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        man = cockpit.manifest
        csrf = await _csrf(client)

        async def send(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert man.workflows["lustify_sdxl_t2i"].content == "explizit"  # ohne Eintrag
        assert man.workflows["output_instagram"].content == "standard"
        out = cfg.local / "evaluation" / "x.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"png-lustify")
        job = pipeline.create_render(store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {})
        media = store.add_media(
            "evaluation/x.png", hashlib.sha256(b"png-lustify").hexdigest(), 11, job_id=job
        )
        assert store.media_tier(media) == "explizit"
        # abgeleitet über einen „standard“-Workflow: höhere Stufe des Ausgangsmediums bleibt
        inp = pipeline.store_input(cfg, _png(), "a.png")
        child = pipeline.create_render(
            store, man, "output_instagram", {}, {"image": inp}, parent_media_id=media
        )
        row = store.db.execute("SELECT content_tier FROM jobs WHERE id = ?", (child,)).fetchone()
        assert row[0] == "explizit"
        assert "bereits explizit" in await send(
            media_content_tier=commands_pb2.MediaContentTier(media_id=media)
        )

        first = _inbound(store, "1", "42", "hallo", "10")
        assert first.customer.kind == "customer"
        assert store.customers_overview(first.customer.id)[0]["age_mark"] == "unclear"
        mark = commands_pb2.CustomerAgeMark(customer_id=first.customer.id, mark="volljährig")
        assert "unbekannt" in await send(customer_age_mark=mark)
        mark = commands_pb2.CustomerAgeMark(
            customer_id=first.customer.id, mark="self_declared_adult"
        )
        assert await send(customer_age_mark=mark) == ""
        (summary,) = store.customers_overview(first.customer.id)
        assert summary["age_mark"] == "self_declared_adult"

        (ident,) = store.identities(first.customer.id)
        notice = commands_pb2.SendAiNotice(customer_id=first.customer.id, identity_id=ident["id"])
        # SP2 Schritt 9a: Influencerin über das Kanalkonto, nie die erste Influencerin
        assert "keine Influencerin zugeordnet" in await send(send_ai_notice=notice)
        clara = store.save_influencer(0, 0, "Clara", None, "", "", [])
        store.import_channel_account({"key": "telegram", "platform": "telegram"})
        store.assign_account_influencer("telegram", clara)
        assert "Hinweistext" in await send(send_ai_notice=notice)  # Profil ohne KI-Hinweis
        rev = store.influencers()[0]["revision"]
        store.save_influencer(clara, rev, "Clara", None, "", "Ich bin eine KI-Creatorin.", [])
        assert "nicht verbunden" in await send(send_ai_notice=notice)  # Testprojekt ohne Konto
        msg_id = store.queue_ai_notice(first.customer.id, ident["id"], "Ich bin eine KI.")
        with pytest.raises(StoreError, match="bereits"):
            store.queue_ai_notice(first.customer.id, ident["id"], "nochmal")
        texts = [i["text"] for i in store.conversation_items(first.customer.id, 0, 20)[0]]
        assert "KI-HINWEIS GESENDET" not in texts  # erst beim tatsächlichen Versand
        store.set_message_status(msg_id, "sent", platform_message_id="99")
        texts = [i["text"] for i in store.conversation_items(first.customer.id, 0, 20)[0]]
        assert texts[-1] == "KI-HINWEIS GESENDET"
        assert store.identities(first.customer.id)[0]["ai_notice_status"] == "sent"

    _run(cfg, scenario)


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


def test_default_sender_by_click_moves_identity_and_history(cfg):
    """Befehl 48 (live 17.11.: privates Zweitkonto landete als Kunde): Identität einer Kundenakte
    per Klick zum Default – samt Verlauf, die leere Akte entfällt; fremde Identität abgewiesen."""

    async def scenario(client, app, origin):
        store = app[server.COCKPIT_KEY].store
        inbound = store.record_inbound(
            "telegram", "555", "7:1", sender_id="7", conversation_id="7",
            platform_message_id="1", text="Hallo", sent_at="2026-11-17T00:00:00+00:00",
        )  # fmt: skip
        cust, default = inbound.customer.id, store.default_contact()["customer_id"]
        ident = store.identities(cust)[0]["id"]
        csrf = await _csrf(client)

        async def assign(customer, identity):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                default_sender_assign=commands_pb2.DefaultSenderAssign(
                    customer_id=customer, identity_id=identity
                ),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert "gehört nicht" in await assign(cust, ident + 99)
        assert await assign(cust, ident) == ""
        assert store.default_contact()["sender_ids"]["telegram"] == "7"
        assert [i["text"] for i in store.conversation_items(default, 0, 20)[0]] == ["Hallo"]
        assert store.customers_overview(cust) == []
        assert "bereits" in await assign(default, ident)

    _run(cfg, scenario)


def test_cloner_command_workflows_reference_and_edit(cloner_cfg):
    """FL-6: Workflow je Befehl (Befehl 37); ein Vorlagen-Workflow erhält das Referenzbild als
    `reference` samt Befehlsanweisung; edit nur auf eigene Bilder, Bereich aus „edit dress: …“."""
    from darkfluenzer.media import models

    cfg = cloner_cfg
    man = models.load_manifest(cfg.root)
    for engine in ("flux3_klein_base", "lustify_sam31_edit"):
        for mf in man.engine_files(engine):
            target = models.models_dir(cfg.root) / mf.target
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fh:
                fh.truncate(mf.size)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        csrf = await _csrf(client)

        async def update(commands):
            d = store.default_contact()
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                default_contact_update=commands_pb2.DefaultContactUpdate(
                    revision=d["revision"], telegram_sender_id="99", approval_mode="direct",
                    process_commands=True, auto_orders=True, media_workflow="lustify_sdxl_refine",
                    command_workflows=[
                        channel_pb2.CommandWorkflow(command=c, workflow=w) for c, w in commands
                    ],
                ),
            )  # fmt: skip
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert "kein Video-Workflow" in await update([("animate", "lustify_sdxl_refine")])
        assert "unbekannt" in await update([("dance", "lustify_sdxl_refine")])
        ok = [("clone", "flux3_klein_reference"), ("edit", "lustify_sam31_edit")]
        assert await update(ok) == ""
        assert store.default_contact()["command_workflows"] == dict(ok)

        first = send("1", "clone in rotem Kleid", "1", [photo])
        await cockpit._on_inbound(first)
        (jid,) = [r[0] for r in store.db.execute("SELECT id FROM jobs ORDER BY id LIMIT 1")]
        params = store.job(jid)["params"]
        assert "reference" in params and store.job(jid)["workflow"] == "flux3_klein_reference"
        assert params["prompt"].startswith("Recreate <ref_image_0>")
        assert params["prompt"].endswith("in rotem Kleid")

        orders = store.db.execute("SELECT count(*) FROM orders").fetchone()[0]
        await cockpit._on_inbound(send("2", "edit dress: rotes Kleid", "2", [photo]))  # fremd
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == orders
        items, _ = store.conversation_items(first.customer.id, 0, 50)
        assert "nur für eigene Bilder" in items[-1]["text"]

        store.add_media("evaluation/x/own.png", photo["sha256"], 10)  # eigener Inhalt
        await cockpit._on_inbound(send("3", "edit dress: rotes Kleid", "3", [photo]))
        last = store.db.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT 1").fetchone()[0]
        params = store.job(last)["params"]
        assert params["region"] == "dress" and params["prompt"] == "rotes Kleid"
        assert params["keep"]  # Pflichtwert aus dem geprüften Graph

    _run(cfg, scenario)
