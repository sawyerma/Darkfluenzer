"""Befehlsannahme und Ausführung (Protobuf-Befehle) (SP0 Schritt 2, bisher ``server.py``)."""

from __future__ import annotations

import asyncio

from ..core.base import _Call
from ..media import aimeta, models, pipeline, training
from ..nodes import comfy
from ..store import StoreError
from ..v1 import (
    commands_pb2,
)
from ..v1 import stream_pb2 as spb

# Befehle mit Registry-Bezug tragen die gesehene Registry-Version (CAS, Workflows.version)
_REGISTRY_COMMANDS = frozenset(
    {
        "render",
        "create_order",
        "set_workflow_enabled",
        "open_workflow",
        "adopt_workflow",
        "delete_workflow",
        "create_workflow",
    }
)


# Ändern die Registry (neue Registry-Version nach dem Effekt)
_REGISTRY_EDITS = _REGISTRY_COMMANDS - {"render", "create_order", "open_workflow"}


_ASYNC_COMMANDS = frozenset({"render", "comfy_start", "comfy_stop"})


# Befehle, deren Fehler als Ablehnungsgrund an den Betreiber gehen (Eingabe-/Registry-Prüfung)
_COMMAND_ERRORS = (
    models.ManifestError,
    pipeline.PipelineError,
    comfy.ComfyError,
    StoreError,
    training.TrainingError,
    aimeta.AiMetaError,
    ValueError,
    OSError,
)


def _response(request_id: str, reason: str, entity: str = "") -> commands_pb2.CommandResponse:
    """Sofortige Antwort: ACCEPTED oder REJECTED (mit Grund); nie ein terminales Ergebnis."""
    accepted, rejected = commands_pb2.COMMAND_STATUS_ACCEPTED, commands_pb2.COMMAND_STATUS_REJECTED
    return commands_pb2.CommandResponse(
        request_id=request_id,
        status=rejected if reason else accepted,
        detail=reason,
        entity=entity,
    )


class CommandsMixin:
    """Befehlsannahme und Ausführung (Protobuf-Befehle); Teil von ``Cockpit``."""

    async def command(
        self, req: commands_pb2.CommandRequest, payload_sha: str
    ) -> commands_pb2.CommandResponse:
        """Führt einen Befehl höchstens einmal je request_id aus (Befehlsjournal in SQLite, auch
        über Neustarts). Dieselbe ID mit demselben Befehl liefert dieselbe Antwort ohne zweite
        Ausführung, mit anderem Befehl eine Ablehnung."""
        rid = req.request_id
        while rid in self._inflight:  # dieselbe ID parallel: auf die erste Ausführung warten
            await asyncio.shield(self._inflight[rid])
        known = self.store.command(rid)
        if known is not None:
            if known["payload_sha"] != payload_sha:
                return _response(rid, "request_id wurde bereits für einen anderen Befehl verwendet")
            rejected = known["status"] == "rejected"
            return _response(rid, known["detail"] if rejected else "", known["entity"])
        done = asyncio.get_running_loop().create_future()
        self._inflight[rid] = done
        try:
            return await self._execute(req, payload_sha)
        finally:
            del self._inflight[rid]
            done.set_result(None)

    async def _execute(
        self, req: commands_pb2.CommandRequest, payload_sha: str
    ) -> commands_pb2.CommandResponse:
        which = req.WhichOneof("command") or ""
        call = _Call(req.request_id, payload_sha, which)
        handlers = {
            "render": self._render,
            "create_order": self._create_order,
            "select_candidate": self._select_candidate,
            "retry_stage": self._retry_stage,
            "mark_read": self._mark_read,
            "send_reply": self._send_reply,
            "default_contact_update": self._default_contact_update,
            "default_sender_assign": self._default_sender_assign,
            "start_cloner_order": self._start_cloner_order,
            "character_update": self._character_update,
            "influencer_update": self._influencer_update,
            "media_content_tier": self._media_content_tier,
            "customer_age_mark": self._customer_age_mark,
            "send_ai_notice": self._send_ai_notice,
            "create_offer": self._create_offer,
            "approve_artifact": self._approve_artifact,
            "retry_delivery": self._retry_delivery,
            "payment_assign": self._payment_assign,
            "gift_card_confirm": self._gift_card_confirm,
            "channel_account_login": self._channel_login,
            "channel_account_update": self._channel_update,
            "set_workflow_enabled": self._set_enabled,
            "open_workflow": self._open,
            "adopt_workflow": self._adopt,
            "delete_workflow": self._delete,
            "create_workflow": self._create,
            "cancel_job": self._cancel,
            "order_cancel": self._order_cancel,
            "lora_activate": self._lora_activate,
            "reveal_folder": self._reveal_folder,
            "character_photos_add": self._character_photos_add,
            "pause_queue": self._pause,
            "delete_media": self._delete_media,
        }
        version = 0
        if which in ("comfy_start", "comfy_stop"):
            reason = self._comfy_command(which, getattr(req, which).instance or "media", call)
        elif which not in handlers:
            reason = "Unbekannter Befehl"
        else:
            async with self._registry:
                if which in _REGISTRY_COMMANDS and req.expected_version != self._registry_version:
                    reason = "Workflows wurden inzwischen geändert – Ansicht ist aktualisiert."
                else:
                    try:
                        reason = await handlers[which](getattr(req, which), call)
                    except _COMMAND_ERRORS as exc:
                        reason = str(exc)
                    if not reason and which in _REGISTRY_EDITS:
                        fingerprint = await asyncio.to_thread(self._fingerprint)
                        self._registry_version = self.store.bump("workflows", fingerprint)
                        version = self._registry_version
                workflows = await asyncio.to_thread(self._workflows)
            self.hub.set_state(spb.TOPIC_COMFY_WORKFLOWS, workflows)
            self.hub.set_state(spb.TOPIC_JOBS_ACTIVE, self._jobs_active())
        if not call.recorded:
            status = "rejected" if reason else "accepted"
            self.store.record_command(
                call.request_id,
                payload_sha,
                which or "unbekannt",
                status,
                entity=call.entity,
                detail=reason,
            )
            if not reason and which not in _ASYNC_COMMANDS:
                self.store.finish_command(call.request_id, "completed", version=version)
        self.hub.push_events(spb.TOPIC_COMMAND_RECEIPT)
        return _response(call.request_id, reason, call.entity)
