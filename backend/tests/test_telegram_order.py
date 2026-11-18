"""Telegram-Eingang der Reihe nach (SP1 Schritt 3): je Chat eine Warteschlange – ein Befehl überholt
nie das Foto, dessen Download noch läuft; Alben tragen ihre album_id; Anhänge, die beim Beenden
noch luden, werden nach dem Start frisch geladen und dann erst weitergeleitet; ein Download wird
dreimal versucht, danach `failed` mit Grund."""

from __future__ import annotations

import asyncio

from test_telegram import TEST_CHAT, FakeTd, _account, _msg

from darkfluenzer.channels import telegram
from darkfluenzer.channels.tdjson import TdError
from darkfluenzer.store import Store


class SlowTd(FakeTd):
    def __init__(self, tmp):
        super().__init__(tmp)
        self.release = asyncio.Event()
        self.failures = 0
        self.message: dict | None = None

    async def call(self, request, timeout):
        if request["@type"] == "downloadFile":
            await self.release.wait()
            if self.failures:
                self.failures -= 1
                self.calls.append(request)
                raise TdError(400, "FILE_DOWNLOAD_FAILED")
        if request["@type"] == "getMessage":
            self.calls.append(request)
            if self.message is None:
                raise TdError(404, "Not Found")
            return self.message
        return await super().call(request, timeout)


def _setup(cfg, tmp_path, store):
    acc, inbound, _ = _account(cfg, tmp_path, store)
    acc._td = SlowTd(tmp_path)
    return acc, inbound


def test_command_waits_for_the_photo_download(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound = _setup(cfg, tmp_path, store)

    async def scenario():
        acc._on_update({"@type": "updateNewMessage", "message": _msg(TEST_CHAT, 10, photo=True)})
        acc._on_update({"@type": "updateNewMessage", "message": _msg(TEST_CHAT, 11, text="clone")})
        await asyncio.sleep(0.05)
        assert inbound == []  # Foto lädt noch; der Befehl wartet dahinter
        acc._td.release.set()
        for _ in range(100):
            if len(inbound) == 2:
                break
            await asyncio.sleep(0.01)

    asyncio.run(scenario())
    photo, command = (store.message(i.message_id) for i in inbound)
    assert photo["attachments"][0]["status"] == "saved" and command["text"] == "clone"
    assert photo["id"] < command["id"]
    assert acc._chat_queues == {} and acc._chat_workers == set()  # Arbeiter beendet
    store.close()


def test_album_id_is_stored(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound = _setup(cfg, tmp_path, store)
    acc._td.release.set()

    async def scenario():
        for mid in (20, 21):
            msg = _msg(TEST_CHAT, mid, photo=True) | {"media_album_id": "777"}
            await acc._enqueue_message(msg)

    asyncio.run(scenario())
    album = store.album_messages(inbound[0].conversation_id, "777")
    assert [m["platform_message_id"] for m in album] == ["20", "21"]
    store.close()


def test_pending_attachment_is_loaded_after_restart(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(telegram, "DOWNLOAD_RETRY_S", 0)
    store = Store(cfg.local)
    acc, inbound = _setup(cfg, tmp_path, store)
    files = telegram.files_of(_msg(TEST_CHAT, 30, photo=True)["content"])
    stored = store.record_inbound(  # beim Beenden noch nicht geladen
        "telegram", acc.account, f"{TEST_CHAT}:30", sender_id=str(TEST_CHAT),
        conversation_id=str(TEST_CHAT), platform_message_id="30", text="clone",
        sent_at="2026-11-18T08:00:00+00:00", attachments=[telegram._pending(f) for f in files],
    )  # fmt: skip
    other = store.record_inbound(
        "telegram", acc.account, f"{TEST_CHAT}:31", sender_id=str(TEST_CHAT),
        conversation_id=str(TEST_CHAT), platform_message_id="31", text="weg",
        sent_at="2026-11-18T08:00:01+00:00", attachments=[telegram._pending(f) for f in files],
    )  # fmt: skip
    acc._td.release.set()
    acc._td.message = _msg(TEST_CHAT, 30, photo=True)

    async def scenario():
        acc._td.message = _msg(TEST_CHAT, 30, photo=True)
        real = acc._td.call

        async def call(request, timeout):  # Nachricht 31 gibt es nicht mehr
            if request["@type"] == "getMessage" and request["message_id"] == 31:
                raise TdError(404, "Not Found")
            return await real(request, timeout)

        acc._td.call = call
        await acc._resume_pending()

    asyncio.run(scenario())
    assert store.message(stored.message_id)["attachments"][0]["status"] == "saved"
    gone = store.message(other.message_id)["attachments"][0]
    assert gone["status"] == "failed" and "nicht mehr abrufbar" in gone["note"]
    assert [i.message_id for i in inbound] == [stored.message_id, other.message_id]
    assert store.pending_inbound("telegram", acc.account) == []
    store.close()


def test_download_is_tried_three_times(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(telegram, "DOWNLOAD_RETRY_S", 0)
    store = Store(cfg.local)
    acc, _ = _setup(cfg, tmp_path, store)
    acc._td.release.set()
    f = telegram.files_of(_msg(TEST_CHAT, 40, photo=True)["content"])[0]
    acc._td.failures = 2
    ok = asyncio.run(acc._save(TEST_CHAT, 40, 0, f))
    assert ok["status"] == "saved"
    acc._td.failures = 3
    bad = asyncio.run(acc._save(TEST_CHAT, 41, 0, f))
    assert bad["status"] == "failed" and bad["note"].startswith("nach 3 Versuchen")
    store.close()
