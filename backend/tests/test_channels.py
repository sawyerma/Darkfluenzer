"""Kanal-Basis (V0 §6, C2): Eingang genau einmal, Kundenliste/Verlauf, Antwortziel-Prüfung,
Default-Kontakt, Postausgang nach Neustart."""

from __future__ import annotations

import uuid

import pytest
from test_server import _csrf, _post, _run

from darkfluenzer import server
from darkfluenzer.channels.telegram import _files
from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import channel_pb2, commands_pb2

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


def test_telegram_files_take_largest_photo_and_documents():
    msg = {
        "photo": [
            {"file_id": "s", "file_size": 1000, "width": 90, "height": 90},
            {"file_id": "l", "file_size": 90000, "width": 1280, "height": 960},
        ],
        "document": {"file_id": "d", "file_size": 30_000_000, "mime_type": "video/mp4"},
    }
    files = _files(msg)
    assert [(f["kind"], f["file_id"], f["size"]) for f in files] == [
        ("photo", "l", 90000),
        ("document", "d", 30_000_000),
    ]


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
