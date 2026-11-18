"""Ungeklärter Versand (SP2 Schritt 6, SPEC-009) und KI-Hinweis erneut (Schritt 7): ``unknown``
wird nur über Echo, Verlauf oder Send-Update geklärt, ``failed`` nur mit Beleg der Plattform, sonst
entscheidet der Betreiber (Befehl 66); nie ein automatischer neuer Versuch."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from test_server import _csrf, _post, _run
from test_telegram import CLARA, TEST_CHAT, _account, _msg

from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import commands_pb2
from darkfluenzer.web import http as server


def _now_msg(chat, mid, *, text, outgoing=True, pending=False):
    msg = _msg(chat, mid, text=text, outgoing=outgoing, pending=pending)
    msg["date"] = int(time.time())
    return msg


def _cards(store, conv) -> list[str]:
    rows = store.db.execute(
        "SELECT text FROM channel_messages WHERE conversation_id = ? AND direction = 'system'",
        (conv,),
    )
    return [r[0] for r in rows]


def _unknown(store, acc, inbound, text):
    """Sendung, deren sendMessage-Aufruf ohne Antwort blieb."""
    conv = inbound[0].conversation_id
    out = store.queue_outbound(
        inbound[0].customer.id, conv, text, revision=store.conversation_revision(conv)
    )
    item = store.outbox("telegram", CLARA)[0]
    acc._td.fail = TimeoutError()
    asyncio.run(acc._send(item))
    acc._td.fail = None
    assert store.message(out)["status"] == "unknown"
    return conv, out


def test_timeout_is_unknown_with_card_and_late_send_update_clears_it(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound, changed = _account(cfg, tmp_path, store)
    asyncio.run(acc._message(_msg(TEST_CHAT, 10)))
    conv, out = _unknown(store, acc, inbound, "Bild kommt gleich")
    assert any(c.startswith("VERSAND UNGEKLÄRT") for c in _cards(store, conv))
    assert store.outbox("telegram", CLARA) == []  # nie blind wiederholt
    late = _now_msg(TEST_CHAT, 501, text="Bild kommt gleich")
    acc._on_update({"@type": "updateMessageSendSucceeded", "old_message_id": 7, "message": late})
    row = store.message(out)
    assert (row["status"], row["platform_message_id"]) == ("sent", "501")
    assert any(c.startswith("VERSAND GEKLÄRT") for c in _cards(store, conv))
    # dieselbe Nachricht kommt beim Abgleich als eigene: keine Übergabe an den Betreiber
    asyncio.run(acc._message(_now_msg(TEST_CHAT, 501, text="Bild kommt gleich")))
    assert not any("ÜBERGABE" in c for c in _cards(store, conv))
    store.close()


def test_late_send_failure_is_platform_evidence(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)
    asyncio.run(acc._message(_msg(TEST_CHAT, 10)))
    _, out = _unknown(store, acc, inbound, "geht nicht raus")
    acc._on_update(
        {"@type": "updateMessageSendFailed", "old_message_id": 8,
         "message": _now_msg(TEST_CHAT, 8, text="geht nicht raus"),
         "error": {"code": 400, "message": "CHAT_WRITE_FORBIDDEN"}}
    )  # fmt: skip
    row = store.message(out)
    assert row["status"] == "failed" and "CHAT_WRITE_FORBIDDEN" in row["error"]
    store.close()


def test_history_after_restart_decides_sent_failed_or_stays_unknown(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound, changed = _account(cfg, tmp_path, store)
    asyncio.run(acc._message(_msg(TEST_CHAT, 10)))
    conv, arrived = _unknown(store, acc, inbound, "angekommen")
    _, missing = _unknown(store, acc, inbound, "verloren")
    acc._td.history = [
        _now_msg(TEST_CHAT, 600, text="angekommen"),
        _now_msg(TEST_CHAT, 601, text="Antwort des Kunden", outgoing=False),
    ]
    asyncio.run(acc._settle_unknown())
    assert store.message(arrived)["status"] == "sent"
    assert store.message(arrived)["platform_message_id"] == "600"
    row = store.message(missing)
    assert row["status"] == "failed" and row["error"].startswith("Telegram-Verlauf ab")
    # TDLib sendet noch: kein Beleg, bleibt unknown
    _, pending = _unknown(store, acc, inbound, "unterwegs")
    acc._td.history = [_now_msg(TEST_CHAT, 602, text="unterwegs", pending=True)]
    asyncio.run(acc._settle_unknown())
    assert store.message(pending)["status"] == "unknown"
    # ID gehört schon einer anderen Nachricht: zählt nicht als Beleg für eine gleichlautende
    acc._td.history = [_now_msg(TEST_CHAT, 600, text="angekommen")]
    _, twin = _unknown(store, acc, inbound, "angekommen")
    asyncio.run(acc._settle_unknown())
    assert store.message(twin)["status"] == "failed"
    store.close()


def test_own_parts_are_never_recorded_as_foreign_after_restart(cfg, tmp_path):
    """Mehrteilige Sendung: jede Teil-ID ist eigene; der Abgleich legt sie nicht als Handy-Nachricht
    mit ÜBERGABE an (bisher war nur die letzte ID gespeichert)."""
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)
    asyncio.run(acc._message(_msg(TEST_CHAT, 10)))
    conv = inbound[0].conversation_id
    (cfg.local / "customers").mkdir(parents=True, exist_ok=True)
    for n in (1, 2):
        (cfg.local / f"customers/p{n}.png").write_bytes(b"png")
    files = [{"kind": "document", "path": f"customers/p{n}.png", "mime": "image/png", "size": 3}
             for n in (1, 2)]  # fmt: skip
    out = store.queue_outbound(
        inbound[0].customer.id, conv, "zwei Bilder", attachments=files,
        revision=store.conversation_revision(conv),
    )  # fmt: skip
    asyncio.run(acc._send(store.outbox("telegram", CLARA)[0]))
    for old, new in ((901, 701), (902, 702)):
        acc._on_update(
            {"@type": "updateMessageSendSucceeded", "old_message_id": old,
             "message": _now_msg(TEST_CHAT, new, text="")}
        )  # fmt: skip
    assert store.message(out)["status"] == "sent"
    for mid in (701, 702):  # Abgleich nach Neustart sieht beide Teile als eigene Nachrichten
        asyncio.run(acc._message(_now_msg(TEST_CHAT, mid, text="")))
    assert not any("ÜBERGABE" in c for c in _cards(store, conv))
    outs = store.db.execute(
        "SELECT count(*) FROM channel_messages WHERE conversation_id = ? AND direction = 'out'",
        (conv,),
    ).fetchone()[0]
    assert outs == 1
    store.close()


def test_ai_notice_again_only_after_failed(tmp_path):
    from test_channels import _inbound

    store = Store(tmp_path / "local")
    first = _inbound(store, "1", "42", "Hallo", "10")
    ident = store.identities(first.customer.id)[0]
    notice = store.queue_ai_notice(first.customer.id, ident["id"], "Ich bin eine KI.")
    for status in ("queued", "sending", "unknown", "sent"):
        store.set_message_status(notice, status)
        with pytest.raises(StoreError, match="bereits ausgelöst"):
            store.queue_ai_notice(first.customer.id, ident["id"], "Ich bin eine KI.")
    store.set_message_status(notice, "failed", error="Telegram: Fehler")
    again = store.queue_ai_notice(first.customer.id, ident["id"], "Ich bin eine KI.")
    assert again != notice
    assert store.identities(first.customer.id)[0]["ai_notice_message_id"] == again
    store.close()


def test_operator_marks_sent_or_resends(cfg):
    from test_channels import _inbound

    async def scenario(client, app, origin):
        import types

        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        first = _inbound(store, "1", "42", "Hallo", "10")
        conv, cust = first.conversation_id, first.customer.id
        ident = store.identities(cust)[0]
        channel = types.SimpleNamespace(
            state="READY", wake=asyncio.Event(), platform="telegram", account=ident["account"],
            key="telegram",
        )  # fmt: skip
        cockpit.adapters = {"telegram": channel}
        csrf = await _csrf(client)

        async def resolve(message_id, action):
            req = commands_pb2.CommandRequest(
                request_id=str(uuid.uuid4()),
                message_resolve=commands_pb2.MessageResolve(message_id=message_id, action=action),
            )
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        def queued(text):
            rev = store.conversation_revision(conv)
            return store.queue_outbound(cust, conv, text, revision=rev)

        sent = queued("schon da")
        assert "unbekanntem Ergebnis" in await resolve(sent, "mark_sent")  # nur unknown
        store.set_message_status(sent, "unknown")
        assert await resolve(sent, "mark_sent") == ""
        assert store.message(sent)["status"] == "sent"
        again = queued("nochmal")
        store.set_message_status(again, "unknown")
        assert await resolve(again, "resend") == ""
        assert store.message(again)["status"] == "failed"
        copy = store.outbox("telegram", ident["account"])
        assert [c["text"] for c in copy] == ["nochmal"] and copy[0]["id"] != again
        assert channel.wake.is_set()
        notice = store.queue_ai_notice(cust, ident["id"], "Ich bin eine KI.")
        store.set_message_status(notice, "unknown")
        assert await resolve(notice, "resend") == ""
        linked = store.identities(cust)[0]["ai_notice_message_id"]
        assert linked != notice and store.message(linked)["status"] == "queued"
        channel.state = "CONNECTING"
        other = queued("offline")
        store.set_message_status(other, "unknown")
        assert "Unbekannte Aktion" in await resolve(other, "x")
        assert "nicht verbunden" in await resolve(other, "resend")
        assert store.message(other)["status"] == "unknown"  # nichts geändert
        assert any(c.startswith("ERNEUT EINGEREIHT") for c in _cards(store, conv))

    _run(cfg, scenario)
