"""Ausnahmeweg Handy (SP5 Schritt 11): Vorschau eines wartenden Auftrags in den Default-Chat; die
Wörter wirken nur als Telegram-Antwort auf genau diese Vorschau, je Vorschau einmal; ohne
Antwortbezug Rückfrage; Erstatten mit zweiter Bestätigung durch die Auftragsnummer; Freigeben nie
gegen harte Gates (Inhaltsstufe)."""

from __future__ import annotations

import dataclasses
import types

from test_channels import BOT, _cloner_setup, _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_chat import _setup
from test_delivery import _review_order
from test_server import _run

from darkfluenzer.channels.base import Capabilities
from darkfluenzer.web import http as server

CAPS = Capabilities(document=True, self_destruct=False, reply_window=False, read_receipts=False,
                    typing=False)  # fmt: skip


def _texts(store, conv):
    rows = store.db.execute(
        "SELECT text FROM channel_messages WHERE conversation_id = ? AND direction = 'out'"
        " ORDER BY id",
        (conv,),
    )
    return [r[0] for r in rows]


def test_phone_preview_and_decisions(cloner_cfg, monkeypatch):  # noqa: F811
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, adapter = _setup(cockpit)
        adapter.capabilities = lambda: CAPS
        cockpit.cfg = dataclasses.replace(
            cockpit.cfg, telegram=types.SimpleNamespace(self_destruct_s=20)
        )
        monkeypatch.setattr(cockpit, "_enqueue", lambda jobs: None)
        store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                              "Ich bin eine KI.", [{"product": "Foto", "price_cents": 2000,
                              "hd_surcharge_cents": 0, "workflow": "krea2_turbo_t2i"}])  # fmt: skip
        product = store.influencers()[0]["prices"][0]
        send, _photo = _cloner_setup(cloner_cfg, store, auto=False)
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"phone_approval": 1}, {})
        await cockpit._on_inbound(send("d0", "hallo", "d0"))  # Default-Chat, Identität belegt
        conv = store.default_conversation("telegram")
        first = _inbound(store, "1", "42", "Hallo", "10")

        def reply(update, text, to):
            return store.record_inbound(
                "telegram", BOT, update, sender_id="99", conversation_id="99",
                platform_message_id=update, text=text, sent_at="2026-11-18T12:00:00+00:00",
                reply_to=to,
            )  # fmt: skip

        async def preview(order):
            await cockpit._system_approve(order.id)  # Freigabeart Betreiber -> Vorschau
            row = store.db.execute(
                "SELECT message_id FROM phone_previews WHERE order_id = ?", (order.id,)
            ).fetchone()
            store.set_message_status(row[0], "sent", platform_message_id=f"p{order.id}")
            return f"p{order.id}"

        order, _media = _review_order(cockpit, cloner_cfg, first, product)
        to = await preview(order)
        assert _texts(store, conv)[-1].startswith(f"FREIGABE? {order.order_no} · Foto")
        await cockpit._system_approve(order.id)  # nicht doppelt
        assert store.db.execute("SELECT count(*) FROM phone_previews").fetchone()[0] == 1
        # ohne Antwortbezug: Rückfrage, nichts entschieden
        await cockpit._on_inbound(send("d1", "Freigeben", "d1"))
        assert _texts(store, conv)[-1] == "Bitte als Antwort auf die Vorschau des Auftrags senden."
        assert store.order(order.order_no).status == "review"
        # Antwort auf die Vorschau: freigegeben, Zustellung; zweite Antwort wirkt nicht
        await cockpit._on_inbound(reply("d2", "Freigeben", to))
        assert store.order(order.order_no).status == "approved"
        assert store.approved_by(order.id) == "Betreiber (Handy)"
        assert len(store.deliveries(order.id)) == 1
        await cockpit._on_inbound(reply("d3", "Freigeben", to))
        assert _texts(store, conv)[-1] == f"{order.order_no}: schon entschieden."
        # Erstatten: erst das Wort, dann genau die Auftragsnummer
        refund, _m = _review_order(cockpit, cloner_cfg, first, product)
        rto = await preview(refund)
        await cockpit._on_inbound(reply("d4", "Erstatten", rto))
        assert "Auftragsnummer" in _texts(store, conv)[-1]
        await cockpit._on_inbound(reply("d5", "DF-O-999999", rto))
        assert store.order(refund.order_no).status == "review"
        await cockpit._on_inbound(reply("d6", refund.order_no, rto))
        assert store.order(refund.order_no).status == "refunded"
        # Neu: neue Kandidatenstufe
        redo, _m = _review_order(cockpit, cloner_cfg, first, product)
        nto = await preview(redo)
        await cockpit._on_inbound(reply("d7", "Neu", nto))
        assert store.order(redo.order_no).status == "producing"
        assert [s.status for s in store.stages(redo.id)][-1] == "running"
        # hartes Gate: Inhaltsstufe nicht standard -> keine Freigabe vom Handy
        hard, hmedia = _review_order(cockpit, cloner_cfg, first, product)
        hto = await preview(hard)
        real = cockpit._order_result

        def explicit(o):
            found = real(o)
            return found | {"content_tier": "explizit"} if found else found

        monkeypatch.setattr(cockpit, "_order_result", explicit)
        await cockpit._on_inbound(reply("d8", "Freigeben", hto))
        assert store.order(hard.order_no).status == "review"
        assert "Inhaltsstufe nicht standard" in _texts(store, conv)[-1]

    _run(cloner_cfg, scenario)
