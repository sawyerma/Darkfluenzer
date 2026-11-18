"""Kundentest im Default-Chat (SP4 Schritt 8): Betriebsart ``test`` führt in denselben Dialog und
denselben registrierten Workflow wie bei Kunden, im eigenen Testverlauf mit eigenem Gedächtnis je
Sitzung; feste Wörter (Abbrechen, Betriebsart) vor der Betriebsart, nie an das Sprachmodell;
Systemnachrichten nie im Testverlauf; „Zurücksetzen“ (Befehl 63); „Verzögerung wie Kunde“."""

from __future__ import annotations

import asyncio
import uuid

from test_channels import BOT, _cloner_setup, cloner_cfg  # noqa: F401  (Fixture)
from test_chat import FAST, OK, Melody, Presence, _settle
from test_server import _csrf, _post, _run

from darkfluenzer.nodes import llm
from darkfluenzer.v1 import commands_pb2
from darkfluenzer.web import http as server

MINOR = '{"minor_hint": true, "minor_evidence": "bin 15", "explicit_wish": false, ' \
        '"purchase_readiness": 0}'  # fmt: skip


def _prepare(cockpit, cfg):
    import dataclasses
    import types

    store = cockpit.store
    cockpit.cfg = dataclasses.replace(cockpit.cfg, behavior=dict(FAST))
    send, photo = _cloner_setup(cfg, store, auto=True)
    clara = store.save_influencer(0, 0, "Clara", None, "", "Ich bin eine KI.", [])
    store.save_persona_version(clara, {"persona": "Clara, 24"}, {}, "Start", activate=True)
    default = store.default_contact()
    store.update_default_contact(default["revision"], {"influencer": str(clara)}, {})
    store.import_channel_account({"key": "tg", "platform": "telegram"})
    store.set_account_platform_id("tg", BOT)
    store.set_account_mode("tg", "test")
    presence = Presence()
    cockpit.adapters = {"tg": types.SimpleNamespace(
        platform="telegram", account=BOT, key="tg", state="READY", wake=asyncio.Event(),
        automation=False, window_open=lambda _p: True, status=lambda: {},
        capabilities=lambda: types.SimpleNamespace(reply_window=False),
        mark_read=presence.mark_read, set_typing=presence.set_typing,
        set_online=presence.set_online,
    )}  # fmt: skip
    return send, clara


def _rows(store, customer_id):
    return store.conversation_items(customer_id, 0, 80)[0]


def test_customer_test_uses_the_same_dialog_in_its_own_history(cloner_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, clara = _prepare(cockpit, cfg)
        store.set_account_mode("tg", "production")
        await cockpit._on_inbound(send("p1", "Hallo Produktion", "p1"))  # Produktion: Rückfrage
        store.set_account_mode("tg", "test")
        first = send("t1", "Hi Clara", "t1")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        rows = _rows(store, first.customer.id)
        tests = [r for r in rows if r["test"]]
        assert [r["direction"] for r in tests] == ["in", "out", "out"]  # Eingang, Hinweis, Antwort
        notice, reply = tests[1], tests[2]
        assert notice["text"] == "Ich bin eine KI." and reply["ai_run_id"]
        assert reply["status"] == "queued" and reply["scheduled_at"] is None  # ohne Verzögerung
        run = store.ai_run(reply["ai_run_id"])
        assert run["kind"] == "test" and run["session"] == 1 and run["influencer_id"] == clara
        assert melody.calls[-1]["context"] == ""  # Produktionsverlauf gehört nicht dazu
        assert all(not r["test"] for r in rows if r["direction"] == "system")
        # Versand-Gate: erst der Testhinweis
        assert "KI-Hinweis des Kundentests" in await cockpit._reply_gate(store.message(reply["id"]))
        store.set_message_status(notice["id"], "sent")
        assert await cockpit._reply_gate(store.message(reply["id"])) == ""
        store.set_message_status(reply["id"], "sent")
        second = send("t2", "Wie geht's?", "t2")
        await cockpit._on_inbound(second)
        await _settle(cockpit)
        assert melody.calls[-1]["context"].startswith("Kunde: Hi Clara\nClara: ")
        # Hinweis auf Minderjährigkeit: nur Karte, die interne Akte bleibt offen
        melody.classes.append(MINOR)
        await cockpit._on_inbound(send("t3", "bin 15", "t3"))
        await _settle(cockpit)
        assert store.age_mark(first.customer.id) != "under_18"
        cards = [r["text"] for r in _rows(store, first.customer.id) if r["direction"] == "system"]
        assert any(c.startswith("TEST · SPERRE wäre gesetzt") for c in cards)

    _run(cfg, scenario)


def test_fixed_words_reset_and_delay(cloner_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, clara = _prepare(cockpit, cfg)
        first = send("t1", "Hi", "t1")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        calls = len(melody.calls)
        await cockpit._on_inbound(send("w1", "Produktion", "w1"))  # festes Wort vor Betriebsart
        assert store.channel_account("tg")["operating_mode"] == "production"
        assert len(melody.calls) == calls
        last = _rows(store, first.customer.id)[-1]
        assert last["text"] == "Betriebsart: Produktion." and not last["test"]
        await cockpit._on_inbound(send("w2", "kundentest", "w2"))
        assert store.channel_account("tg")["operating_mode"] == "test"
        # Zurücksetzen: neue Sitzung, Hinweis wieder fällig, Testgedächtnis gelöscht
        store.add_memory("test", clara, 1, "customer", "mag Katzen", source="t", origin="operator")
        csrf = await _csrf(client)
        req = commands_pb2.CommandRequest(
            request_id=str(uuid.uuid4()), test_reset=commands_pb2.TestReset()
        )
        status, body = await _post(client, origin, csrf, req)
        assert status == 200 and commands_pb2.CommandResponse.FromString(body).detail == ""
        default = store.default_contact()
        assert default["test_session"] == 2 and default["test_notice_message_id"] is None
        active = store.db.execute(
            "SELECT count(*) FROM memories WHERE scope = 'test' AND status = 'active'"
        ).fetchone()[0]
        assert active == 0
        assert any("KUNDENTEST ZURÜCKGESETZT" in r["text"] for r in _rows(store, first.customer.id))
        # Verzögerung wie Kunde: Sendezeit aus dem Verhaltensprofil
        store.update_default_contact(default["revision"], {"test_delay": 1}, {})
        await cockpit._on_inbound(send("t2", "Hallo nochmal", "t2"))
        await _settle(cockpit)
        reply = [r for r in _rows(store, first.customer.id) if r["test"] and r["ai_run_id"]][-1]
        assert reply["scheduled_at"] is not None
        assert store.ai_run(reply["ai_run_id"])["session"] == 2
        notices = [r for r in _rows(store, first.customer.id)
                   if r["test"] and r["text"] == "Ich bin eine KI."]  # fmt: skip
        assert len(notices) == 2  # je Sitzung genau einmal

    _run(cfg, scenario)


assert OK
