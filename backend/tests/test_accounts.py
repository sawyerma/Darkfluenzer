"""SP2 Schritt 9a: Kanalkonten als Liste – Übernahme der Konfiguration, unveränderliche Konto-ID,
Konto → Influencerin, Sperre je Plattform-Identität, STATE 8 je Konto, Befehl 40 additiv."""

from __future__ import annotations

import uuid

import pytest
from test_channels import BOT, _inbound
from test_server import _csrf, _post, _run

from darkfluenzer.core import assessment
from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import channel_pb2, commands_pb2
from darkfluenzer.web import http as server


def test_import_bind_assign_and_lookup(tmp_path):
    store = Store(tmp_path / "local")
    seed = {"key": "telegram", "platform": "telegram", "test_mode": True, "test_chat_ids": (42,),
            "default_sender_id": "571"}  # fmt: skip
    assert store.import_channel_account(seed) is True
    assert store.import_channel_account(seed | {"test_mode": False}) is False  # nur einmal
    acc = store.channel_account("telegram")
    assert (
        acc["test_mode"] and acc["test_chat_ids"] == [42] and acc["customer_transport"] == "tdlib"
    )
    assert store.account_for("telegram", "999")["key"] == "telegram"  # einziges, noch ungebunden
    store.set_account_platform_id("telegram", "999")
    store.set_account_platform_id("telegram", "999")  # gleich: nichts
    with pytest.raises(StoreError, match="gehört zu 999"):
        store.set_account_platform_id("telegram", "123")  # anderes Konto
    assert store.account_for("telegram", "123") is None
    clara = store.save_influencer(0, 0, "Clara", None, "", "", [])
    store.assign_account_influencer("telegram", clara)
    assert store.channel_account("telegram")["influencer_name"] == "Clara"
    ident = {"platform": "telegram", "account": "999"}
    assert store.influencer_for_identity(ident) == clara
    with pytest.raises(StoreError, match="unbekannt"):
        store.assign_account_influencer("telegram", 77)


def _other(store, account: str, event: str):
    """Derselbe Telegram-Nutzer 42 schreibt an ein anderes Konto (andere Influencerin)."""
    return store.record_inbound(
        "telegram", account, event, sender_id="42", conversation_id="42",
        platform_message_id=f"m-{event}", text="Hi", sent_at="2026-11-18T08:00:00+00:00",
    )  # fmt: skip


def test_minor_lock_follows_the_platform_identity_across_influencers(tmp_path):
    store = Store(tmp_path / "local")
    a = _inbound(store, "1", "42", "Hallo", "10")  # Konto BOT
    b = _other(store, "zweites-konto", "e2")
    assert a.customer.id != b.customer.id  # zwei Influencerinnen-Konten: zwei Akten
    assert store.customers_with_identity_of(a.customer.id) == sorted([a.customer.id, b.customer.id])
    assert (
        assessment.apply_minor_lock(store, a.customer.id, a.conversation_id, "Ich bin 15") is True
    )
    marks = {r[0]: r[1] for r in store.db.execute("SELECT id, age_mark FROM customers")}
    assert marks[a.customer.id] == marks[b.customer.id] == "under_18"
    c = _other(store, "drittes-konto", "e3")
    mark = store.db.execute(
        "SELECT age_mark FROM customers WHERE id = ?", (c.customer.id,)
    ).fetchone()
    assert mark[0] == "under_18"  # neue Akte derselben Identität erbt die Sperre
    other = _inbound(store, "4", "43", "Hallo", "11")
    mark = store.db.execute("SELECT age_mark FROM customers WHERE id = ?", (other.customer.id,))
    assert mark.fetchone()[0] != "under_18"
    assert BOT  # Konto des Testkanals


def test_channels_state_per_account_and_assign_command(cfg):
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        store.import_channel_account({"key": "telegram", "platform": "telegram"})
        clara = store.save_influencer(0, 0, "Clara", None, "", "", [])
        csrf = await _csrf(client)
        update = commands_pb2.ChannelAccountUpdate(
            platform="telegram", key="telegram", action="assign_influencer", influencer_id=clara
        )
        req = commands_pb2.CommandRequest(
            request_id=str(uuid.uuid4()), channel_account_update=update
        )
        status, body = await _post(client, origin, csrf, req)
        assert status == 200 and commands_pb2.CommandResponse.FromString(body).detail == ""
        state = channel_pb2.Channels.FromString(cockpit._channels())
        tg = next(c for c in state.channels if c.platform == "telegram")
        assert tg.key == "telegram" and tg.influencer == "Clara" and tg.influencer_id == clara
        assert tg.operating_mode == "production" and tg.transport == "tdlib"
        assert tg.state == "OFF" and "telegram_account" in tg.missing  # Testprojekt ohne Zugang
        assert [c.platform for c in state.channels] == ["telegram", "instagram", "whatsapp"]

    _run(cfg, scenario)
