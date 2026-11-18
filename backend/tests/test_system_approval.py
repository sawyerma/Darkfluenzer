"""Systemfreigabe (SP5 Schritt 8, SPEC-013): Freigabeart je Influencerin; das System gibt nur mit
qualifizierten Schwellen und vier bestandenen Prüfwerten genau dieses Inhalts frei (Trigger auf
approvals), nie für Videos (E23); harte Gates (gesperrte Akte, Inhaltsstufe) gelten auch dann."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import types

import pytest
from test_channels import _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_chat import _setup
from test_selection import CFG, _checks, _waiting_order
from test_server import _run

from darkfluenzer import approval
from darkfluenzer.channels.base import Capabilities
from darkfluenzer.web import http as server

CAPS = Capabilities(document=True, self_destruct=False, reply_window=False, read_receipts=False,
                    typing=False)  # fmt: skip


def _system_setup(cockpit, monkeypatch):
    store = cockpit.store
    clara, adapter = _setup(cockpit)
    adapter.capabilities = lambda: CAPS
    store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                          "Ich bin eine KI.", [{"product": "Foto", "price_cents": 2000,
                          "hd_surcharge_cents": 0, "workflow": "krea2_turbo_t2i"}])  # fmt: skip
    monkeypatch.setattr(cockpit, "_enqueue", lambda jobs: None)
    cockpit.cfg = dataclasses.replace(
        cockpit.cfg, selection=CFG, telegram=types.SimpleNamespace(self_destruct_s=20)
    )
    return clara, store.influencers()[0]["prices"][0]


def _bind_product(store, order, product):
    store.db.execute("UPDATE offers SET product_id = ? WHERE order_id = ?",
                     (product["id"], order.id))  # fmt: skip


def test_system_approval_only_with_four_passed_checks(cloner_cfg, monkeypatch):  # noqa: F811
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, product = _system_setup(cockpit, monkeypatch)
        # Freigabeart Betreiber: das System gibt nicht frei
        order, jobs, media = _waiting_order(cockpit, cloner_cfg, count=1)
        _bind_product(store, order, product)
        _checks(store, jobs[0], media[0], identity=0.9)
        cockpit._auto_select(order.id)
        await cockpit._system_approve(order.id)
        assert store.order(order.order_no).status == "review"
        # Freigabeart System: freigegeben und zugestellt, Freigeber System mit Prüfwerten
        store.set_influencer_approval_mode(clara, "system")
        await cockpit._system_approve(order.id)
        assert store.order(order.order_no).status == "approved"
        assert store.approved_by(order.id) == "System"
        row = store.db.execute("SELECT checks FROM approvals WHERE order_id = ?", (order.id,))
        checks = json.loads(row.fetchone()[0])
        assert set(checks) >= {"identity", "content", "technical", "quality"}
        assert len(store.deliveries(order.id)) == 1
        # Trigger: System ohne bestandene Prüfung dieses Inhalts -> abgewiesen
        other, ojobs, omedia = _waiting_order(cockpit, cloner_cfg, count=1)
        _bind_product(store, other, product)
        _checks(store, ojobs[0], omedia[0], sharp=5.0)  # Technik fällt durch
        cockpit._auto_select(other.id)  # keiner besteht -> neue Stufe (Obergrenze 1)
        art_file = cloner_cfg.local / store.media_by_id(omedia[0])["path"]
        store.db.execute("UPDATE order_stages SET status = 'done', selected_media_id = ?"
                         " WHERE order_id = ? AND seq = 1", (omedia[0], other.id))  # fmt: skip
        store.db.execute("UPDATE orders SET status = 'review' WHERE id = ?", (other.id,))
        master = store.order_dir(store.order(other.order_no)) / "work" / "master.png"
        master.write_bytes(art_file.read_bytes())  # gleicher Inhalt wie der geprüfte Kandidat
        art = store.add_artifact(other.order_no, "master", master)
        with pytest.raises(sqlite3.IntegrityError, match="Systemfreigabe ohne vier"):
            store.record_approval(other.order_no, art.id, "approved", "System",
                                  {"identity": 1, "content": "neutral", "technical": 1,
                                   "quality": 1})  # fmt: skip
        store.record_approval(other.order_no, art.id, "approved", "Betreiber")  # Betreiber darf
        # hartes Gate: gesperrte Akte wird nie beliefert
        store.set_age_mark(other.customer_id, "under_18")
        gate = approval.check_gate(store, other.order_no, art.id, store.order(other.order_no)
                                   .customer_no)  # fmt: skip
        assert any(r.startswith("CUSTOMER_LOCKED") for r in gate.reasons)

    _run(cloner_cfg, scenario)


def test_video_and_unqualified_go_to_the_operator(cloner_cfg, monkeypatch):  # noqa: F811
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, product = _system_setup(cockpit, monkeypatch)
        store.set_influencer_approval_mode(clara, "system")
        order, jobs, media = _waiting_order(cockpit, cloner_cfg, count=1)
        _bind_product(store, order, product)
        _checks(store, jobs[0], media[0], identity=0.9)
        cockpit._auto_select(order.id)
        cockpit.cfg = dataclasses.replace(cockpit.cfg, selection=dataclasses.replace(
            CFG, rules={k: v for k, v in CFG.rules.items() if k != "quality"}))  # fmt: skip
        await cockpit._system_approve(order.id)
        assert store.order(order.order_no).status == "review"
        store.db.execute("UPDATE orders SET kind = 'video' WHERE id = ?", (order.id,))
        cockpit.cfg = dataclasses.replace(cockpit.cfg, selection=CFG)
        await cockpit._system_approve(order.id)
        assert store.order(order.order_no).status == "review"
        offer = store.offer(order.id)
        cards = [
            i["text"]
            for i in store.conversation_items(order.customer_id, 0, 80)[0]
            if i["direction"] == "system" and i["conversation_id"] == offer["conversation_id"]
        ]
        assert any("Prüfung nicht qualifiziert (Qualität)" in c for c in cards)
        assert any(c.endswith("Video (E23)") for c in cards)

    _run(cloner_cfg, scenario)
