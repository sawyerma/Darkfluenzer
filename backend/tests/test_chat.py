"""Dialogbetrieb (SP4 Schritt 6): Kundennachricht → registrierter Sprachworkflow (ersetzt durch
eine Ersatz-Generierung; der echte Lauf mit Gates, ``ai_runs`` und Gedächtnis bleibt) → geplante
Antwort oder Entwurf mit Grund; KI-Hinweis zuerst und genau einmal; Sperre bei Hinweis auf
Minderjährigkeit; Nachricht vom Handy → manual; neue Nachricht storniert; Versand-Gate frisch;
Befehl 54; Rechtsfreigabe E21."""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import types
import uuid

import pytest
from test_channels import BOT, _inbound
from test_server import _csrf, _post, _run

from darkfluenzer.config import DialogConfig, project_root
from darkfluenzer.nodes import llm
from darkfluenzer.v1 import channel_pb2, commands_pb2
from darkfluenzer.web import http as server

OK = '{"minor_hint": false, "explicit_wish": false, "purchase_readiness": 1}'
MINOR = '{"minor_hint": true, "minor_evidence": "ich bin 16", "explicit_wish": false, ' \
        '"purchase_readiness": 0}'  # fmt: skip


@pytest.fixture
def chat_cfg(cfg):
    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    return cfg


class Melody:
    """Ersatz für ``llm.generate``: Antworten und Einstufungen der Reihe nach, Aufrufe gezählt."""

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.classes: list[str] = []
        self.calls: list[dict] = []
        self.gate: asyncio.Event | None = None

    def __call__(self, cfg, man, workflow, values, *, timeout_s, on_submit=None):
        self.calls.append(values)
        answer = self.answers.pop(0) if self.answers else f"Hi! ({values['message']})"
        cls = self.classes.pop(0) if self.classes else OK
        return llm.TextResult(
            answer=answer, classification=cls, system="S", user=values["message"],
            prompt_id=f"p{len(self.calls)}", wait_s=0.0, duration_s=0.01,
            workflow_sha="w", model_sha="m",
        )  # fmt: skip


FAST = {"bundle_s": 0, "read_min_s": 0, "read_max_s": 0, "think_min_s": 0, "think_max_s": 0,
        "slow_min_s": 0, "slow_max_s": 0, "night_min_s": 0, "night_max_s": 0,
        "typing_cps": 1000, "slow_chance": 0}  # fmt: skip


class Presence:
    """Lesen, Tippen, Online des Ersatz-Kanals (merkt sich die Aufrufe)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def mark_read(self, conversation, ids):
        self.calls.append(("read", conversation, tuple(ids)))
        return True

    async def set_typing(self, conversation, typing):
        self.calls.append(("typing", conversation, typing))
        return True

    async def set_online(self, online):
        self.calls.append(("online", online))
        return True


def _setup(cockpit, *, test_mode=True, auto=True, behavior=None):
    store = cockpit.store
    cockpit.cfg = dataclasses.replace(cockpit.cfg, behavior=dict(behavior or FAST))
    clara = store.save_influencer(0, 0, "Clara", None, "", "Ich bin eine KI.", [
        {"product": "Foto", "price_cents": 2000, "hd_surcharge_cents": 500}])  # fmt: skip
    store.save_persona_version(clara, {"persona": "Clara, 24"}, {}, "Start", activate=True)
    store.set_influencer_switches(clara, True, auto)
    store.import_channel_account({"key": "tg", "platform": "telegram", "influencer_id": clara,
                                  "test_mode": test_mode})  # fmt: skip
    store.set_account_platform_id("tg", BOT)
    presence = Presence()
    adapter = types.SimpleNamespace(
        platform="telegram", account=BOT, key="tg", state="READY", wake=asyncio.Event(),
        automation=True, window_open=lambda _p: True, status=lambda: {},
        capabilities=lambda: types.SimpleNamespace(reply_window=False),
        mark_read=presence.mark_read, set_typing=presence.set_typing,
        set_online=presence.set_online, presence=presence,
    )  # fmt: skip
    cockpit.adapters = {"tg": adapter}
    return clara, adapter


async def _settle(cockpit):
    for _ in range(200):
        busy = [s for s in cockpit._dialog_state.values() if s["task"] and not s["task"].done()]
        if not busy:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Dialog läuft noch")


def _out(store, customer_id):
    return [i for i in store.conversation_items(customer_id, 0, 80)[0] if i["direction"] == "out"]


def test_reply_after_notice_and_gates(chat_cfg, monkeypatch):
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        _clara, adapter = _setup(cockpit)
        first = _inbound(store, "1", "42", "Hallo Clara", "10")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        notice, reply = _out(store, first.customer.id)
        assert notice["text"] == "Ich bin eine KI." and notice["status"] == "queued"
        assert reply["status"] == "queued" and reply["ai_run_id"] and adapter.wake.is_set()
        assert melody.calls[0]["message"] == "Hallo Clara" and melody.calls[0]["persona"]
        run = store.ai_run(reply["ai_run_id"])
        assert run["kind"] == "chat" and run["customer_id"] == first.customer.id
        # Versand-Gate: Hinweis noch nicht gesendet -> die Antwort wartet
        assert "KI-Hinweis" in await cockpit._reply_gate(store.message(reply["id"]))
        store.set_message_status(notice["id"], "sent", platform_message_id="n1")
        assert await cockpit._reply_gate(store.message(reply["id"])) == ""
        store.set_message_status(reply["id"], "sent", platform_message_id="r1")
        # falscher Betrag: Entwurf mit Grund
        melody.answers.append("Das Foto kostet 50 €.")
        second = _inbound(store, "2", "42", "Was kostet ein Foto?", "11")
        await cockpit._on_inbound(second)
        await _settle(cockpit)
        draft = _out(store, first.customer.id)[-1]
        assert draft["status"] == "draft" and "50,00 € steht nicht in den Fakten" in draft["error"]
        assert melody.calls[-1]["context"].startswith("Kunde: Hallo Clara")
        # neue Nachricht vor dem Senden: offene KI-Antwort storniert, neu erzeugt
        third = _inbound(store, "3", "42", "Und als Video?", "12")
        await cockpit._on_inbound(third)
        await _settle(cockpit)
        assert store.message(draft["id"])["status"] == "cancelled"
        assert _out(store, first.customer.id)[-1]["status"] == "queued"
        # Modus draft: Entwurf mit Grund
        store.set_conversation_mode(first.conversation_id, "draft")
        await cockpit._on_inbound(_inbound(store, "4", "42", "Hallo?", "13"))
        await _settle(cockpit)
        last = _out(store, first.customer.id)[-1]
        assert last["status"] == "draft" and "Modus der Konversation: draft" in last["error"]

    _run(chat_cfg, scenario)


def test_minor_lock_phone_takeover_and_switches(chat_cfg, monkeypatch):
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, _adapter = _setup(cockpit)
        melody.classes.append(MINOR)
        first = _inbound(store, "1", "42", "ich bin 16", "10")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        assert store.age_mark(first.customer.id) == "under_18"
        cards = [i["text"] for i in store.conversation_items(first.customer.id, 0, 50)[0]
                 if i["direction"] == "system"]  # fmt: skip
        assert any(c.startswith("SPERRE") for c in cards)
        assert [o["text"] for o in _out(store, first.customer.id)] == ["Ich bin eine KI."]
        calls = len(melody.calls)
        await cockpit._on_inbound(_inbound(store, "2", "42", "hallo?", "11"))
        await _settle(cockpit)
        assert len(melody.calls) == calls  # gesperrt: kein weiterer Lauf
        # anderer Kunde; Nachricht vom Handy schaltet auf manual
        other = _inbound(store, "3", "77", "Hey", "20")
        store.record_external_outgoing(
            "telegram", BOT, "77", "900", "bin gleich da", "2026-11-18T10:00:00+00:00"
        )
        assert store.conversation_mode(other.conversation_id) == "manual"
        await cockpit._on_inbound(other)
        await _settle(cockpit)
        assert len(melody.calls) == calls
        # Text-KI aus: nichts
        store.set_influencer_switches(clara, False, True)
        third = _inbound(store, "4", "88", "Hey", "30")
        await cockpit._on_inbound(third)
        await _settle(cockpit)
        assert len(melody.calls) == calls and _out(store, third.customer.id) == []

    _run(chat_cfg, scenario)


def test_public_contact_gate_e21_and_dirty_generation(chat_cfg, monkeypatch):
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        _setup(cockpit, test_mode=False)
        first = _inbound(store, "1", "42", "Hallo", "10")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        outs = _out(store, first.customer.id)
        assert len(outs) == 1 and outs[0]["status"] == "draft" and "E21" in outs[0]["error"]
        assert store.identities(first.customer.id)[0]["ai_notice_status"] is None  # nicht auto
        cockpit.cfg = dataclasses.replace(
            cockpit.cfg, dialog=DialogConfig(public_contact_cleared=True)
        )
        # neue Nachricht während der Erzeugung: Ergebnis verworfen, neu erzeugt
        slow = asyncio.Event()
        real = cockpit._llm_run

        async def held(*a, **k):
            await slow.wait()
            return await real(*a, **k)

        monkeypatch.setattr(cockpit, "_llm_run", held)
        await cockpit._on_inbound(_inbound(store, "2", "42", "Bist du da?", "11"))
        await asyncio.sleep(0.02)
        await cockpit._on_inbound(_inbound(store, "3", "42", "Hallo??", "12"))
        slow.set()
        await _settle(cockpit)
        statuses = [o["status"] for o in _out(store, first.customer.id)]
        assert statuses.count("cancelled") >= 2 and statuses[-1] == "queued"
        assert melody.calls[-1]["message"].endswith("Hallo??")  # mit dem neuen Stand

    _run(chat_cfg, scenario)


def test_outbox_control_command_54(chat_cfg, monkeypatch):
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        _setup(cockpit, auto=False)  # automatische Antworten aus: Entwurf
        first = _inbound(store, "1", "42", "Hallo", "10")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        (draft,) = _out(store, first.customer.id)
        assert draft["status"] == "draft"
        csrf = await _csrf(client)

        async def control(**kw):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()), outbox_control=commands_pb2.OutboxControl(**kw)
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        assert await control(message_id=draft["id"], action="send_now") == "Keine geplante Antwort."
        assert await control(message_id=draft["id"], action="send_draft", text="Hallo du!") == ""
        row = store.message(draft["id"])
        assert (row["status"], row["text"], row["released"]) == ("queued", "Hallo du!", 1)
        # freigegeben: Gate prüft nur Hinweis/Sperre/Fenster, nicht die Automatik
        ident = store.identities(first.customer.id)[0]
        store.queue_ai_notice(first.customer.id, ident["id"], "Ich bin eine KI.")
        notice = store.identities(first.customer.id)[0]["ai_notice_message_id"]
        store.set_message_status(notice, "sent")
        assert await cockpit._reply_gate(store.message(draft["id"])) == ""
        assert await control(message_id=draft["id"], action="hold") == ""
        assert store.message(draft["id"])["status"] == "draft"
        assert await control(message_id=draft["id"], action="discard") == ""
        assert store.message(draft["id"])["status"] == "cancelled"
        assert "Nur KI-Antworten" in await control(message_id=notice, action="discard")
        assert await control(conversation_id=first.conversation_id, action="set_mode",
                             mode="manual") == ""  # fmt: skip
        assert store.conversation_mode(first.conversation_id) == "manual"
        page = channel_pb2.ConversationPage.FromString(
            await (
                await client.get(f"/api/v1/conversation-page?customer={first.customer.id}")
            ).read()
        )
        assert page.identities[0].mode == "manual"
        item = next(i for i in page.items if i.item_id == draft["id"])
        assert item.status == "cancelled" and item.ai_run_id

    _run(chat_cfg, scenario)
