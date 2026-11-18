"""Verhalten (SP4 Schritt 7, E3, E4): Plan aus dem Verhaltensprofil (schnell im Fluss, langsam bei
Erstkontakt/Pause/zufällig, nachts langsam außer bei Kaufbereitschaft), Bündeln, Sendezeit nach
Lesen/Bedenken/Tippen, Gelesen zur geplanten Zeit, Online und Tippanzeige bis zum Senden,
Vertröst-Text nach der Wartegrenze (vorab erzeugt, Tageslimit), Postausgang nach Sendezeit."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta

from test_channels import _inbound
from test_chat import FAST, Melody, _settle, _setup, chat_cfg  # noqa: F401  (Fixture)
from test_server import _run

from darkfluenzer.core import behavior
from darkfluenzer.nodes import llm
from darkfluenzer.web import http as server

B = behavior.Behavior()


def test_plan_kinds_and_send_time():
    rng = random.Random(1)
    day = datetime(2026, 11, 18, 14, 0).astimezone()
    flow = behavior.plan(B, day, previous_out=day - timedelta(seconds=60), first_contact=False,
                         readiness=0, rng=random.Random(5))  # fmt: skip
    assert flow.kind in ("fast", "slow")
    fast = behavior.plan(
        behavior.build(B, {"slow_chance": 0}), day, previous_out=day - timedelta(seconds=60),
        first_contact=False, readiness=0, rng=rng,
    )  # fmt: skip
    assert fast.kind == "fast" and 3 <= (fast.read_at - day).total_seconds() <= 20
    first = behavior.plan(B, day, previous_out=None, first_contact=True, readiness=0, rng=rng)
    assert first.kind == "slow" and 30 <= (first.read_at - day).total_seconds() <= 1800
    pause = behavior.plan(B, day, previous_out=day - timedelta(hours=2), first_contact=False,
                          readiness=0, rng=rng)  # fmt: skip
    assert pause.kind == "slow"
    night = datetime(2026, 11, 18, 3, 0).astimezone()
    sleepy = behavior.plan(B, night, previous_out=night - timedelta(seconds=30),
                           first_contact=False, readiness=1, rng=rng)  # fmt: skip
    assert sleepy.kind == "night" and (sleepy.read_at - night).total_seconds() >= 1800
    eager = behavior.plan(B, night, previous_out=night - timedelta(seconds=30),
                          first_contact=False, readiness=2, rng=rng)  # fmt: skip
    assert eager.kind != "night"  # E4: Kaufbereitschaft nachts zügig
    sent = behavior.send_at(B, fast, "x" * 60, day)
    assert sent == fast.think_until + timedelta(seconds=10)
    assert behavior.send_at(B, fast, "", fast.think_until + timedelta(hours=1)) > fast.think_until
    late = behavior.build(B, {"night_start_h": 22, "night_end_h": 6})
    assert behavior.is_night(late, datetime(2026, 11, 18, 23, 30))
    assert not behavior.is_night(late, datetime(2026, 11, 18, 12, 0))


def test_build_validates():
    assert "unbekannte" in behavior.build(B, {"tempo": 1})
    assert "read_min_s > read_max_s" in behavior.build(B, {"read_min_s": 30})
    assert "slow_chance" in behavior.build(B, {"slow_chance": 2})
    assert "negativen" in behavior.build(B, {"bundle_s": -1})
    assert behavior.build(B, {"bundle_s": 5}).bundle_s == 5


def test_bundle_schedule_presence(chat_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        _clara, adapter = _setup(cockpit, behavior=FAST | {"bundle_s": 0.3, "typing_cps": 1})
        for n, text in enumerate(("Hi", "bist du da?", "hallo?")):
            await cockpit._on_inbound(_inbound(store, str(n), "42", text, str(10 + n)))
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.4)
        await _settle(cockpit)
        assert len(melody.calls) == 1  # drei schnelle Nachrichten, eine Antwort
        assert melody.calls[0]["message"] == "Hi\nbist du da?\nhallo?"
        conv = _inbound(store, "0", "42", "Hi", "10").conversation_id
        reply = store.message(store.open_ai_replies(conv)[-1])
        due = datetime.fromisoformat(reply["scheduled_at"])
        assert due > datetime.now(UTC) + timedelta(seconds=5)  # Tippzeit: 1 Zeichen je Sekunde
        due_now = [o["id"] for o in store.outbox("telegram", "7000001")]
        assert reply["id"] not in due_now  # noch nicht fällig
        assert store.next_scheduled("telegram", "7000001") == reply["scheduled_at"]
        calls = adapter.presence.calls
        assert ("read", "42", ("12",)) in calls and ("online", True) in calls
        await asyncio.sleep(0.1)
        assert any(c[0] == "typing" for c in adapter.presence.calls)  # bis zum Senden
        store.cancel_message(reply["id"], "Test")
        await asyncio.sleep(4.2)
        assert adapter.presence.calls[-1] == ("online", False)

    _run(chat_cfg, scenario)


def test_consolation_after_wait_and_fill(chat_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, _adapter = _setup(cockpit, behavior=FAST | {"max_wait_s": 0.1,
                                                           "consolations_per_day": 1,
                                                           "consolation_stock": 2})  # fmt: skip
        blocks = {"persona": "Clara, 24", "consolation": "Kurz vertrösten."}
        store.save_persona_version(clara, blocks, {}, "mit Vertröstung", activate=True)
        persona = store.active_persona(clara)
        store.add_consolation(persona["id"], "Moment, gleich!", None)
        slow = asyncio.Event()
        real = cockpit._llm_run

        async def held(*a, **k):
            await slow.wait()
            return await real(*a, **k)

        monkeypatch.setattr(cockpit, "_llm_run", held)
        first = _inbound(store, "1", "42", "Hallo", "10")
        await cockpit._on_inbound(first)
        await asyncio.sleep(0.3)
        texts = [m["text"] for m in store.conversation_items(first.customer.id, 0, 50)[0]
                 if m["direction"] == "out"]  # fmt: skip
        assert "Moment, gleich!" in texts and store.consolations_today(first.conversation_id) == 1
        monkeypatch.setattr(cockpit, "_llm_run", real)
        slow.set()
        await _settle(cockpit)
        for _ in range(100):  # Vertröst-Texte im Leerlauf nachgelegt
            if store.consolation_stock(persona["id"]) >= 2:
                break
            await asyncio.sleep(0.02)
        assert store.consolation_stock(persona["id"]) == 2
        assert any(c["message"] == "Kurz vertrösten." for c in melody.calls)

    _run(chat_cfg, scenario)


def test_telegram_reads_later_when_the_dialog_takes_over(cfg, tmp_path):
    from test_telegram import TEST_CHAT, _account, _msg

    from darkfluenzer.store import Store

    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)

    async def takes_over(i):
        inbound.append(i)
        return True

    acc.on_inbound = takes_over
    asyncio.run(acc._message(_msg(TEST_CHAT, 10)))
    assert not any(r["@type"] == "viewMessages" for r in acc._td.sent)  # Dialog liest später

    async def no_dialog(i):
        inbound.append(i)
        return False

    acc.on_inbound = no_dialog
    asyncio.run(acc._message(_msg(TEST_CHAT, 11)))
    assert any(r["@type"] == "viewMessages" for r in acc._td.sent)
    asyncio.run(acc.mark_read(str(TEST_CHAT), ["12"]))
    asyncio.run(acc.set_typing(str(TEST_CHAT), True))
    asyncio.run(acc.set_online(True))
    kinds = [r["@type"] for r in acc._td.sent]
    assert kinds[-3:] == ["viewMessages", "sendChatAction", "setOption"]
    store.close()


def test_split_text_at_sentences():
    from darkfluenzer.channels.instagram import split_text

    assert split_text("kurz", 100) == ["kurz"]
    text = "Erster Satz hier. Zweiter Satz da! Dritter? Vierter."
    parts = split_text(text, 20)
    assert parts == ["Erster Satz hier.", "Zweiter Satz da!", "Dritter? Vierter."]
    assert all(len(p.encode()) <= 20 for p in parts)
    assert split_text("Ein sehr langer Satz ohne Ende " * 3, 20) is None


def test_behavior_command_53_and_state(chat_cfg):  # noqa: F811
    import uuid

    from test_server import _csrf, _post

    from darkfluenzer.v1 import commands_pb2, influencer_pb2

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, _ = _setup(cockpit, behavior={"bundle_s": 30})
        csrf = await _csrf(client)

        async def update(values):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                behavior_update=commands_pb2.BehaviorUpdate(influencer_id=clara, values=values),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        def state():
            payload = cockpit._influencers()
            return next(i for i in influencer_pb2.Influencers.FromString(payload).influencers
                        if i.influencer_id == clara)  # fmt: skip

        first = state()
        assert first.behavior["bundle_s"] == 30 and first.behavior_version == 0  # Startwerte
        assert "read_min_s > read_max_s" in await update({"read_min_s": 99})
        assert "unbekannte" in await update({"tempo": 1})
        assert await update({"bundle_s": 8, "night_start_h": 23}) == ""
        now = state()
        assert now.behavior["bundle_s"] == 8 and now.behavior["night_start_h"] == 23
        assert now.behavior_version == 1 and now.behavior["read_max_s"] == 20  # Vorgabe bleibt
        figure = next(f for f in store.influencers() if f["id"] == clara)
        assert cockpit._behavior(figure).bundle_s == 8

    _run(chat_cfg, scenario)
