"""Kanalvertrag (SP0 Schritt 4): Telegram und Instagram erfüllen ``Channel`` vollständig; ein Kanal
ohne Antwortfenster meldet offen und liefert kein Fenster an das Cockpit."""

from __future__ import annotations

import asyncio

from darkfluenzer.channels.base import Capabilities, Channel
from darkfluenzer.channels.instagram import InstagramAccount
from darkfluenzer.channels.telegram import TelegramAccount
from darkfluenzer.web.mappers import _window


def test_both_adapters_fulfil_the_contract():
    for cls in (TelegramAccount, InstagramAccount):
        assert issubclass(cls, Channel)
        assert not cls.__abstractmethods__, cls.__abstractmethods__
    assert TelegramAccount.platform == "telegram" and InstagramAccount.platform == "instagram"


class _NoWindow(Channel):
    """Kleinster Kanal ohne Antwortfenster (nur die Pflichtteile)."""

    platform = "probe"
    automation = True

    def capabilities(self) -> Capabilities:
        return Capabilities(
            document=True,
            self_destruct=False,
            reply_window=False,
            read_receipts=False,
            typing=False,
        )

    def status(self) -> dict:
        return {}

    async def run(self) -> None:
        return None

    async def outbox_worker(self) -> None:
        return None

    async def logout(self) -> str:
        return ""

    def set_automation(self, enabled: bool) -> str:
        return ""


def test_channel_without_window_is_open_and_shows_no_window():
    ch = _NoWindow()
    assert ch.window_open("c1") and ch.send_check("c1") == ""
    assert ch.send_check("c1", human_agent=True) == "Human-Agent gibt es nur bei Instagram."
    ident = {"platform": "probe", "platform_conversation_id": "c1"}
    assert _window(ch, ident) == {} and _window(None, ident) == {}


def test_read_and_typing_report_unsupported_until_sp4():
    ch = _NoWindow()
    assert asyncio.run(ch.mark_read("c1", ["1"])) is False
    assert asyncio.run(ch.set_typing("c1", True)) is False
