"""Claras Telegram-Konto über TDLib (V0 §6.1, C2d) mit einer Ersatz-TDLib: Testbetrieb, Eingang
genau einmal und erst danach gelesen, Übergabe an den Betreiber, Versandstatus, Telegram-Bremse,
Anmeldewert nie im Befehlsjournal."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import time
import uuid

from test_server import _csrf, _post, _run

from darkfluenzer import config, server
from darkfluenzer.channels import telegram
from darkfluenzer.channels.tdjson import TdError
from darkfluenzer.store import Store
from darkfluenzer.v1 import commands_pb2

CLARA = "555"
TEST_CHAT = 42


class FakeTd:
    """Antwortet wie TDLib auf die Anfragen des Adapters und merkt sich alles Gesendete."""

    def __init__(self, tmp):
        self.sent: list[dict] = []
        self.calls: list[dict] = []
        self.tmp = tmp
        self.fail: TdError | None = None
        self.next_id = 900
        self.history: list[dict] = []

    def send(self, request):
        self.sent.append(request)

    async def call(self, request, timeout):
        self.calls.append(request)
        kind = request["@type"]
        if kind == "getChat":
            return {"type": {"@type": "chatTypePrivate"}}
        if kind == "getUser":
            return {"first_name": "Leon", "usernames": {"active_usernames": ["leon"]}}
        if kind == "downloadFile":
            path = self.tmp / f"file{request['file_id']}.jpg"
            path.write_bytes(b"jpeg-bytes")
            return {"local": {"path": str(path)}}
        if kind == "loadChats":
            raise TdError(404, "Not Found")
        if kind == "getChatHistory":
            start = request["from_message_id"] or 10**12
            page = [m for m in self.history if m["id"] < start or request["from_message_id"] == 0]
            page = sorted(page, key=lambda m: -m["id"])[:2]  # kleine Seiten wie TDLib anfangs
            if request["from_message_id"]:
                page = [m for m in page if m["id"] < start]
            return {"messages": page}
        if kind == "sendMessage":
            if self.fail:
                raise self.fail
            self.next_id += 1
            return {"id": self.next_id}
        raise AssertionError(kind)


def _account(cfg, tmp_path, store):
    tg = config.TelegramConfig(
        tdjson=tmp_path / "libtdjson.dylib",
        data_dir=tmp_path / "telegram",
        api_id_service="x",
        api_hash_service="y",
        db_key_service="z",
        test_mode=True,
        test_chat_ids=(TEST_CHAT,),
        max_download_mb=10,
        reply_delay_min_s=0.01,
        reply_delay_max_s=0.01,
        typing_chars_per_s=1000,
        max_messages_per_minute=6,
    )
    changed: list[int] = []
    inbound: list = []

    async def on_inbound(i):
        inbound.append(i)

    acc = telegram.TelegramAccount(
        dataclasses.replace(cfg, telegram=tg), store, on_inbound, lambda: None
    )
    acc.on_change_message = changed.append
    acc._td = FakeTd(tmp_path)
    acc.account, acc.state, acc.login = CLARA, "READY", "ready"
    return acc, inbound, changed


def _msg(chat, mid, *, text="hallo", outgoing=False, pending=False, photo=False):
    content = {"@type": "messageText", "text": {"text": text}}
    if photo:
        sizes = [
            {"width": 90, "height": 90, "photo": {"id": 1, "size": 100}},
            {"width": 1280, "height": 960, "photo": {"id": 2, "size": 9000}},
        ]
        content = {"@type": "messagePhoto", "photo": {"sizes": sizes}, "caption": {"text": text}}
    msg = {
        "id": mid,
        "chat_id": chat,
        "date": 1763200000,
        "is_outgoing": outgoing,
        "sender_id": {"@type": "messageSenderUser", "user_id": chat},
        "content": content,
    }
    if pending:
        msg["sending_state"] = {"@type": "messageSendingStatePending"}
    return msg


def test_files_take_largest_photo():
    content = _msg(1, 1, photo=True)["content"]
    assert telegram.files_of(content) == [
        {"kind": "photo", "file_id": 2, "size": 9000, "mime": "image/jpeg"}
    ]
    assert telegram.message_text(content) == "hallo"


def test_inbound_test_mode_once_then_read_and_handoff(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)

    async def scenario():
        await acc._message(_msg(7, 1))  # fremder Chat im Testbetrieb: verworfen
        assert store.db.execute("SELECT count(*) FROM channel_messages").fetchone()[0] == 0
        # nur die ID (für test_chat_ids) flüchtig im Status, ohne Inhalt und Namen
        assert [r["chat_id"] for r in acc.status()["rejected_chats"]] == [7]
        assert acc._td.calls == []  # für fremde Chats nicht einmal getChat/getUser
        await acc._message(_msg(TEST_CHAT, 10, photo=True))
        await acc._message(_msg(TEST_CHAT, 10, photo=True))  # erneut zugestellt
        assert len(inbound) == 1
        (item,) = store.conversation_items(inbound[0].customer.id, 0, 10)[0]
        assert item["text"] == "hallo" and item["attachments"][0]["status"] == "saved"
        assert (cfg.local / item["attachments"][0]["path"]).read_bytes() == b"jpeg-bytes"
        deleted = [r["file_id"] for r in acc._td.sent if r["@type"] == "deleteFile"]
        assert deleted == [2]  # TDLib-Kopie des Anhangs entfernt (nur local/channels)
        views = [r for r in acc._td.sent if r["@type"] == "viewMessages"]
        assert views == [
            {"@type": "viewMessages", "chat_id": TEST_CHAT, "message_ids": [10], "force_read": True}
        ]  # gelesen erst nach Speichern und Verarbeitung, genau einmal
        await acc._message(_msg(TEST_CHAT, 11, outgoing=True, pending=True))  # eigener Versand
        await acc._message(_msg(TEST_CHAT, 12, text="bin gleich da", outgoing=True))  # Handy
        items, _ = store.conversation_items(inbound[0].customer.id, 0, 10)
        assert [(i["direction"], i["text"].split("\n")[0]) for i in items[1:]] == [
            ("out", "bin gleich da"),
            ("system", telegram.HANDOFF_CARD),
        ]

    asyncio.run(scenario())
    store.close()


def test_send_status_and_flood_wait(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound, changed = _account(cfg, tmp_path, store)

    async def scenario():
        await acc._message(_msg(TEST_CHAT, 10))
        conv = inbound[0].conversation_id
        rev = store.conversation_revision(conv)
        out = store.queue_outbound(inbound[0].customer.id, conv, "hi", revision=rev)
        (item,) = store.outbox("telegram", CLARA)
        await acc._send(item)
        assert store.message(out)["status"] == "sending"
        acc._on_update(
            {"@type": "updateMessageSendSucceeded", "old_message_id": 901, "message": {"id": 77}}
        )
        row = store.message(out)
        assert (row["status"], row["platform_message_id"]) == ("sent", "77")
        second = store.queue_outbound(
            inbound[0].customer.id, conv, "noch was", revision=store.conversation_revision(conv)
        )
        acc._td.fail = TdError(429, "Too Many Requests: retry after 30")
        await acc._send(store.outbox("telegram", CLARA)[0])
        assert store.message(second)["status"] == "failed"
        assert acc.flood_until > time.time() + 25 and acc.status()["flood_until_ms"] > 0

    asyncio.run(scenario())
    store.close()


def test_login_value_never_in_journal(cfg):
    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        rid = str(uuid.uuid4())
        req = commands_pb2.CommandRequest(
            request_id=rid,
            channel_account_login=commands_pb2.ChannelAccountLogin(
                platform="telegram", step="code", value="12345"
            ),
        )
        status, body = await _post(client, origin, csrf, req)
        assert status == 200
        assert "nicht eingerichtet" in commands_pb2.CommandResponse.FromString(body).detail
        stored = (
            app[server.COCKPIT_KEY]
            .store.db.execute("SELECT payload_sha FROM commands WHERE request_id = ?", (rid,))
            .fetchone()[0]
        )
        req.channel_account_login.value = ""
        blank = hashlib.sha256(req.SerializeToString(deterministic=True)).hexdigest()
        assert stored == blank  # Hash ohne den Code

    _run(cfg, scenario)


def test_reconcile_after_restart_fetches_missed_messages(cfg, tmp_path):
    """Nach dem Anmelden: je Chat ab der letzten gespeicherten Nachrichten-ID nachholen."""
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)

    async def scenario():
        await acc._message(_msg(TEST_CHAT, 10, text="eins"))
        assert store.adapter_get("telegram", CLARA, f"{telegram.LAST}{TEST_CHAT}") == "10"
        acc._td.history = [_msg(TEST_CHAT, i, text=f"m{i}") for i in (8, 9, 10, 11, 12, 13)]
        await acc._reconcile()
        items, _ = store.conversation_items(inbound[0].customer.id, 0, 20)
        assert [i["text"] for i in items] == ["eins", "m11", "m12", "m13"]
        assert store.adapter_get("telegram", CLARA, f"{telegram.LAST}{TEST_CHAT}") == "13"
        await acc._reconcile()  # nichts doppelt
        assert len(store.conversation_items(inbound[0].customer.id, 0, 20)[0]) == 4

    asyncio.run(scenario())
    store.close()
