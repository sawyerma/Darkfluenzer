"""Kanäle, Eingang, Antworten, Default-Kontakt (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

from ..core import cloner_text as cloner
from ..media import pipeline
from ..nodes import comfy
from ..store import StoreError
from ..v1 import (
    channel_pb2,
    commands_pb2,
)
from ..v1 import stream_pb2 as spb
from .base import _Call, log


class MessagesMixin:
    """Kanäle, Eingang, Antworten, Default-Kontakt; Teil von ``Cockpit``."""

    def _channels(self) -> bytes:
        """STATE channels: Zustand je Kanal; nicht eingerichtete Kanäle mit dem, was fehlt."""
        msg = channel_pb2.Channels(version=self.store.domain_version("channels"))
        if self.telegram:
            msg.channels.add(**self.telegram.status())
        else:
            msg.channels.add(
                platform="telegram", state="OFF", missing="Abschnitt [telegram_account]"
            )
        if self.instagram:
            msg.channels.add(**self.instagram.status())
        else:
            msg.channels.add(platform="instagram", state="OFF", missing="Abschnitt [instagram]")
        msg.channels.add(platform="whatsapp", state="OFF", missing="WhatsApp folgt später (C7)")
        return msg.SerializeToString()

    def _channels_changed(self) -> None:
        self.hub.set_state(spb.TOPIC_CHANNELS, self._channels())

    def _message_changed(self, message_id: int) -> None:
        if message_id:
            try:
                self._delivery_update(message_id)
            except StoreError as exc:  # Gate beim Festschreiben gesperrt: bleibt offen, sichtbar
                log.error("Zustellung zu Nachricht %s: %s", message_id, exc)
        self.hub.push_events(spb.TOPIC_CONVERSATION_EVENT)
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)

    async def _on_inbound(self, inbound) -> None:
        """Neue Nachricht gespeichert: Cockpit per Push aktualisieren; Nachrichten des Default-
        Kontakts gehen vor jeder Kundenverarbeitung durch die Kloner-Weiche (V0 §8)."""
        self._message_changed(inbound.message_id or 0)
        self._wallet_changed()  # erkannter Gutscheincode erscheint im Reiter Wallet
        if inbound.customer.kind == "internal" and inbound.message_id:
            try:
                await self._cloner(inbound)
            except (pipeline.PipelineError, comfy.ComfyError, StoreError) as exc:
                self.store.add_system_card(inbound.conversation_id, f"Auftrag nicht möglich: {exc}")
                self._message_changed(0)

    async def _send_ai_notice(self, msg: commands_pb2.SendAiNotice, call: _Call) -> str:
        """KI-Hinweis der Influencerin einmal je Kanalidentität (Befehl 45, Regel 12 b)."""
        call.entity = f"customer:{msg.customer_id}"
        figure = next(iter(self.store.influencers()), None)
        if figure is None or not figure["ai_notice"].strip():
            return "KI-Hinweistext im Influencerin-Profil fehlt."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None:
            return "Kanalidentität gehört nicht zu dieser Kundenakte."
        adapter = self._adapter(ident["platform"])
        if adapter is None or adapter.state != "READY":
            return f"{ident['platform']} ist nicht verbunden."
        if reason := self._send_check(ident["platform"], ident["platform_conversation_id"]):
            return reason
        message_id = self.store.queue_ai_notice(
            msg.customer_id, msg.identity_id, figure["ai_notice"].strip()
        )
        call.entity = f"message:{message_id}"
        adapter.wake.set()
        self._message_changed(message_id)
        return ""

    def _send_check(self, platform: str, partner: str, *, human_agent: bool = False) -> str:
        """Kanalgrenzen vor dem Einreihen (Instagram: 24-h-Fenster); leer = erlaubt."""
        adapter = self._adapter(platform)
        if adapter is None:
            return "Human-Agent gibt es nur bei Instagram." if human_agent else ""
        return adapter.send_check(partner, human_agent=human_agent)

    async def _send_reply(self, msg: commands_pb2.SendReply, call: _Call) -> str:
        """Manuelle Textantwort nur an die gewählte, verifizierte Konversation dieses Kunden
        (F4): Plattform, Identität und Konversation müssen zusammenpassen; Revision = CAS."""
        call.entity = f"customer:{msg.customer_id}"
        if not msg.text.strip():
            return "Leere Antwort."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None or ident["platform"] != msg.platform or not msg.platform:
            return "Kanal passt nicht zu dieser Kundenakte."
        if ident["conversation_id"] != msg.conversation_id:
            return "Konversation passt nicht zu diesem Kanal."
        adapter = self._adapter(msg.platform)
        if adapter is None or adapter.state != "READY":
            return f"{msg.platform} ist nicht verbunden."
        partner = ident["platform_conversation_id"]
        if reason := self._send_check(msg.platform, partner, human_agent=msg.human_agent):
            return reason
        message_id = self.store.queue_outbound(
            msg.customer_id,
            msg.conversation_id,
            msg.text.strip(),
            revision=msg.revision,
            request_id=call.request_id,
        )
        call.entity = f"message:{message_id}"
        if msg.human_agent and not adapter.window_open(partner):
            adapter.mark_human_agent(message_id)
        adapter.wake.set()
        self._message_changed(message_id)
        return ""

    async def _mark_read(self, msg: commands_pb2.MarkRead, call: _Call) -> str:
        call.entity = f"customer:{msg.customer_id}"
        self.store.customer_by_id(msg.customer_id)
        if self.store.mark_read(msg.customer_id, msg.up_to_item):
            self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""

    def _default_identity_account(self, platform: str) -> str:
        if platform == "telegram":
            if not self.telegram or not self.telegram.account:
                raise pipeline.PipelineError("Claras Telegram-Konto ist noch nicht angemeldet.")
            return self.telegram.account
        if platform == "instagram":
            if not self.instagram or not self.instagram.account:
                raise pipeline.PipelineError("Claras Instagram-Konto ist noch nicht angemeldet.")
            return self.instagram.account
        raise pipeline.PipelineError(f"{platform} ist noch nicht eingerichtet.")

    async def _default_contact_update(
        self, msg: commands_pb2.DefaultContactUpdate, call: _Call
    ) -> str:
        current = self.store.default_contact()
        call.entity = f"customer:{current['customer_id']}"
        if msg.approval_mode not in ("direct", "cockpit", "cockpit_only"):
            return "Freigabemodus unbekannt."
        if msg.influencer and msg.influencer not in {
            str(i["id"]) for i in self.store.influencers()
        }:
            return "Influencerin: unbekanntes Profil."
        for key, kind in ((msg.media_workflow, "image"), (msg.video_workflow, "video")):
            if reason := self._cloner_workflow_reason(key, kind):
                return reason
        commands: dict[str, str] = {}
        for cw in msg.command_workflows:  # FL-6: Workflow je Befehl
            if cw.command not in cloner.COMMANDS or cw.command in commands:
                return f"Befehl '{cw.command}' unbekannt oder doppelt."
            kind = "video" if cw.command == "animate" else "image"
            if reason := self._cloner_workflow_reason(cw.workflow, kind):
                return f"{cw.command}: {reason}"
            commands[cw.command] = cw.workflow
        senders = {}
        if msg.telegram_sender_id.strip() != current["sender_ids"].get("telegram", ""):
            senders[("telegram", self._default_identity_account("telegram"))] = (
                msg.telegram_sender_id.strip()
            )
        if msg.instagram_sender_id.strip() != current["sender_ids"].get("instagram", ""):
            senders[("instagram", self._default_identity_account("instagram"))] = (
                msg.instagram_sender_id.strip()
            )
        self.store.update_default_contact(
            msg.revision,
            {
                "process_commands": int(msg.process_commands),
                "auto_orders": int(msg.auto_orders),
                "approval_mode": msg.approval_mode,
                "influencer": msg.influencer.strip(),
                "media_workflow": msg.media_workflow,
                "video_workflow": msg.video_workflow,
            },
            senders,
            commands,
        )
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""

    async def _default_sender_assign(
        self, msg: commands_pb2.DefaultSenderAssign, call: _Call
    ) -> str:
        """Befehl 48: Absender aus einer Kundenakte zum Default machen – derselbe Weg wie die
        Absender-ID im Default-Kontakt (Umzug samt Verlauf), nur per Klick an der Identität."""
        call.entity = f"customer:{msg.customer_id}"
        current = self.store.default_contact()
        if msg.customer_id == current["customer_id"]:
            return "Gehört bereits zum Default."
        ident = next(
            (i for i in self.store.identities(msg.customer_id) if i["id"] == msg.identity_id),
            None,
        )
        if ident is None:
            return "Kanalidentität gehört nicht zu dieser Kundenakte."
        if ident["platform"] not in ("telegram", "instagram"):
            return "Default-Absender nur für Telegram oder Instagram."
        self.store.update_default_contact(
            current["revision"],
            {},
            {(ident["platform"], ident["account"]): ident["platform_user_id"]},
        )
        log.info("Default-Absender %s aus Kundenakte %s", ident["platform"], msg.customer_id)
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""

    async def _channel_login(self, msg: commands_pb2.ChannelAccountLogin, call: _Call) -> str:
        """Anmeldeschritt (Befehl 39); der Wert geht nur an TDLib (V0 §6.1 Punkt 2)."""
        call.entity = f"channel:{msg.platform}"
        if msg.platform == "instagram":
            return "Instagram meldet sich über den Link „Mit Instagram anmelden“ an."
        if msg.platform != "telegram" or self.telegram is None:
            return f"{msg.platform or 'Kanal'}: Kontoanmeldung nicht eingerichtet."
        return await self.telegram.login_step(msg.step, msg.value)

    async def _channel_update(self, msg: commands_pb2.ChannelAccountUpdate, call: _Call) -> str:
        """Automatik freigeben/sperren oder abmelden (Befehl 40)."""
        call.entity = f"channel:{msg.platform}"
        adapter = self._adapter(msg.platform)
        if adapter is None:
            return f"{msg.platform or 'Kanal'}: Konto nicht eingerichtet."
        if msg.action == "logout":
            return await adapter.logout()
        if msg.action in ("enable_automation", "disable_automation"):
            return adapter.set_automation(msg.action == "enable_automation")
        return "Unbekannte Aktion."

    async def _customer_age_mark(self, msg: commands_pb2.CustomerAgeMark, call: _Call) -> str:
        """Altersangabe der Akte (Befehl 44; nur Betreiber, nie das LLM)."""
        call.entity = f"customer:{msg.customer_id}"
        self.store.set_age_mark(msg.customer_id, msg.mark)
        self.hub.push_events(spb.TOPIC_CUSTOMER_UPDATED)
        return ""
