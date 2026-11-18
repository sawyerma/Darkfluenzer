"""Default-Kette (SP1 Schritte 4, 5): Referenzen aus eigenen Anhängen samt Album, beantworteter
Nachricht oder zuletzt gesendeten Medien desselben Absenders; Album erst nach Ruhe; Vorprüfung mit
Instanz und Startbarkeit; jeder Ausgang mit Karte und Chat-Antwort; „Befehle sind aus“ einmal je
Zeitraum; Ausnahmen enden sichtbar als FEHLGESCHLAGEN."""

from __future__ import annotations

import asyncio
import dataclasses

from test_channels import BOT, _cloner_setup, _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_server import _run

from darkfluenzer.config import ClonerConfig
from darkfluenzer.web import http as server


def _items(store, customer_id):
    return store.conversation_items(customer_id, 0, 50)[0]


def _photo_msg(store, send, photo, update, message, *, album=None, text=""):
    inbound = send(update, text, message, [photo])
    if album:
        store.db.execute(
            "UPDATE channel_messages SET album_id = ? WHERE id = ?", (album, inbound.message_id)
        )
    return inbound


def test_photo_then_command_uses_the_recent_photo_once(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        pic = _photo_msg(store, send, photo, "1", "1")
        await cockpit._on_inbound(pic)  # Foto ohne Befehl: nur anzeigen
        cmd = send("2", "clone", "2")
        await cockpit._on_inbound(cmd)
        order = store.db.execute("SELECT id FROM orders").fetchall()
        assert len(order) == 1
        assert store.message(pic.message_id)["order_id"] == order[0][0]  # Referenz gehört ihm
        again = send("3", "clone", "3")  # Foto ist vergeben: Rückfrage
        await cockpit._on_inbound(again)
        last = _items(store, cmd.customer.id)[-1]
        assert last["direction"] == "out" and "Referenzbild" in last["text"]
        cards = [i["text"] for i in _items(store, cmd.customer.id) if i["direction"] == "system"]
        assert any("· ABGELEHNT" in c for c in cards)

    _run(cfg, scenario)


def test_reply_and_album_references_never_other_senders(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        stranger = _inbound(store, "9", "42", "", "9")  # anderer Absender mit Bild
        store.set_attachments(stranger.message_id, [photo])
        albums = [_photo_msg(store, send, photo | {"path": photo["path"]}, str(n), str(n),
                             album="A1") for n in (1, 2, 3)]  # fmt: skip
        caption = store.message(albums[0].message_id)
        refs, _ = cockpit._cloner_refs(caption)
        assert [r["message_id"] for r in refs] == [a.message_id for a in albums]
        reply = send("4", "clone", "4")
        store.db.execute(
            "UPDATE channel_messages SET reply_to_platform_id = '2', order_id = NULL WHERE id = ?",
            (reply.message_id,),
        )
        refs, replied = cockpit._cloner_refs(store.message(reply.message_id))
        assert replied["platform_message_id"] == "2" and len(refs) == 3  # Album der Antwort
        store.db.execute(  # Album außerhalb des Zeitfensters: das fremde Bild wird nie genommen
            "UPDATE channel_messages SET created_at = '2020-01-01T00:00:00.000+00:00'"
            " WHERE album_id = 'A1'"
        )
        lone = send("5", "clone", "5")
        refs, _ = cockpit._cloner_refs(store.message(lone.message_id))
        assert refs == []

    _run(cfg, scenario)


def test_album_with_caption_waits_until_quiet(cloner_cfg):  # noqa: F811
    cfg = dataclasses.replace(cloner_cfg, cloner=ClonerConfig(album_settle_s=0.2))

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        first = _photo_msg(store, send, photo, "1", "1", album="B7", text="remix")
        await cockpit._on_inbound(first)  # kehrt sofort zurück: der Chat-Eingang läuft weiter
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        for n in (2, 3):
            await cockpit._on_inbound(_photo_msg(store, send, photo, str(n), str(n), album="B7"))
        for _ in range(100):
            if store.db.execute("SELECT count(*) FROM orders").fetchone()[0]:
                break
            await asyncio.sleep(0.02)
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] >= 1
        linked = store.db.execute(
            "SELECT count(*) FROM channel_messages WHERE album_id = 'B7' AND order_id IS NOT NULL"
        ).fetchone()[0]
        assert linked == 3  # das ganze Album gehört dem Auftrag

    _run(cfg, scenario)


def test_every_exit_has_card_and_answer(cloner_cfg, monkeypatch):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        cust = send("0", "", "0").customer.id
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"media_workflow": ""}, {})
        await cockpit._on_inbound(send("1", "clone", "1", [photo]))
        items = _items(store, cust)
        assert "· ABGELEHNT\nKein Workflow für clone" in items[-2]["text"]
        assert items[-1]["direction"] == "out" and "Kein Workflow" in items[-1]["text"]
        default = store.default_contact()
        store.update_default_contact(
            default["revision"], {"media_workflow": "lustify_sdxl_refine"}, {}
        )
        monkeypatch.setattr(cockpit, "_not_startable", lambda wf: "Modelle fehlen (6.5 GB).")
        await cockpit._on_inbound(send("2", "clone", "2", [photo]))
        assert "Modelle fehlen" in _items(store, cust)[-1]["text"]
        monkeypatch.undo()

        def boom(*_a, **_k):
            raise RuntimeError("Graph kaputt")

        monkeypatch.setattr(cockpit, "_cloner_order", boom)
        await cockpit._on_inbound(send("3", "clone", "3", [photo]))
        items = _items(store, cust)
        assert "· FEHLGESCHLAGEN\nGraph kaputt" in items[-2]["text"]
        assert "fehlgeschlagen · Graph kaputt" in items[-1]["text"]
        monkeypatch.undo()
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"process_commands": False}, {})
        before = len(_items(store, cust))
        await cockpit._on_inbound(send("4", "clone", "4", [photo]))
        await cockpit._on_inbound(send("5", "clone", "5", [photo]))  # Hinweis nur einmal
        new = _items(store, cust)[before:]
        notes = [i for i in new if i["direction"] == "out"]
        assert len(notes) == 1 and notes[0]["text"].startswith("Befehle sind aus")

    _run(cfg, scenario)


del BOT
