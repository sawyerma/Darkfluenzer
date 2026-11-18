"""Produktion nach Zahlung (SP5 Schritt 6): mit Bildautomatik startet ein bezahlter Auftrag aus dem
Produkt (Workflow, Kandidaten, Prompt aus dem Wunsch, Vorrang Kunde; Video mit Animation als
Fertigstellen-Stufe mit eigenem Prompt und Höchstlänge); ohne Wunsch oder ohne Bildautomatik nicht;
Testaufträge laufen als Klasse Default; Dank mit angehängter Lieferzeit; genau eine
Verzugsnachricht."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from test_channels import _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_chat import Melody, _setup
from test_server import _run

from darkfluenzer.nodes import llm
from darkfluenzer.web import http as server

SOON = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="milliseconds")
PRODUCTS = [
    {"product": "Foto", "price_cents": 2000, "hd_surcharge_cents": 0, "kind": "image",
     "workflow": "krea2_turbo_t2i", "candidates": 3},
    {"product": "Clip", "price_cents": 6000, "hd_surcharge_cents": 0, "kind": "video",
     "workflow": "krea2_turbo_t2i", "finish_workflow": "ltx25_i2v", "candidates": 2,
     "max_duration_s": 4},
]  # fmt: skip


def _paid(store, first, product, wish: str, *, delivery_s: float = 600.0):
    order = store.create_offer(
        first.customer.id, first.conversation_id, product["product"], False,
        product["price_cents"], SOON, {}, product_id=product["id"], kind=product["kind"],
        delivery_s=delivery_s, wish=wish,
    )  # fmt: skip
    store.transition(order.order_no, "accepted")
    store.record_payment(order.order_no, "usdt", f"0x{order.id}:0", product["price_cents"], "EUR")
    return store.order(order.order_no)


def _cards(store, customer_id):
    return [i["text"] for i in store.conversation_items(customer_id, 0, 80)[0]
            if i["direction"] == "system"]  # fmt: skip


def test_paid_orders_start_from_the_product(cloner_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, _adapter = _setup(cockpit)
        store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                              "Ich bin eine KI.", PRODUCTS)  # fmt: skip
        foto, clip = store.influencers()[0]["prices"]
        monkeypatch.setattr(cockpit, "_product_problems", lambda *_a, **_k: [])
        queued: list[int] = []
        monkeypatch.setattr(cockpit, "_enqueue", lambda jobs: queued.extend(jobs))
        first = _inbound(store, "1", "42", "Hallo", "10")
        # Bildautomatik aus: nichts startet
        order = _paid(store, first, foto, "Strandfoto bei Sonnenuntergang")
        cockpit._start_paid_orders()
        assert store.order(order.order_no).status == "paid" and not queued
        store.set_influencer_switches(clara, True, True, True)
        # ohne Wunsch: Karte genau einmal, kein Start
        empty = _paid(store, first, foto, "")
        cockpit._start_paid_orders()
        cockpit._start_paid_orders()
        waits = [c for c in _cards(store, first.customer.id) if c.startswith("PRODUKTION WARTET")]
        assert len(waits) == 1 and empty.order_no in waits[0]
        # mit Wunsch: Kandidaten aus dem Produkt, Prompt aus dem Wunsch, Vorrang Kunde
        assert store.order(order.order_no).status == "producing"
        (stage,) = store.stages(order.id)
        jobs = store.stage_jobs(stage.id)
        assert len(jobs) == 3 and set(queued) >= {j["id"] for j in jobs}
        params = json.loads(store.db.execute(
            "SELECT params FROM jobs WHERE id = ?", (jobs[0]["id"],)).fetchone()[0])  # fmt: skip
        assert params["prompt"] == "Strandfoto bei Sonnenuntergang"
        assert store.job_priorities([jobs[0]["id"]])[jobs[0]["id"]] == "customer"
        assert store.offer(order.id)["production_started_at"]
        cards = _cards(store, first.customer.id)
        assert any(c.startswith(f"PRODUKTION GESTARTET · {order.order_no} · 3") for c in cards)
        # Video: Animation als Fertigstellen-Stufe mit eigenem Prompt und Höchstlänge
        video = _paid(store, first, clip, "Tanz am Strand")
        cockpit._start_paid_orders()
        (vstage,) = store.stages(video.id)
        assert vstage.params["finish"] == "ltx25_i2v"
        assert vstage.params["finish_values"] == {"prompt": "Tanz am Strand", "duration_s": 4.0}
        assert len(store.stage_jobs(vstage.id)) == 2
        # Dank: ohne Profilblock nur Karte
        for _ in range(100):
            if any(c.startswith("DANK") for c in _cards(store, first.customer.id)):
                break
            await __import__("asyncio").sleep(0.01)
        assert any("Profilblock „Lieferung“ fehlt" in c for c in _cards(store, first.customer.id))

    _run(cloner_cfg, scenario)


def test_delivery_note_and_one_delay_notice(cloner_cfg, monkeypatch):  # noqa: F811
    import asyncio

    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, _adapter = _setup(cockpit)
        store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                              "Ich bin eine KI.", PRODUCTS)  # fmt: skip
        store.save_persona_version(clara, {"persona": "Clara, 24", "delivery": "Bedanke dich."},
                                   {}, "mit Lieferung", activate=True)  # fmt: skip
        store.set_influencer_switches(clara, True, True, True)
        foto = store.influencers()[0]["prices"][0]
        monkeypatch.setattr(cockpit, "_product_problems", lambda *_a, **_k: [])
        monkeypatch.setattr(cockpit, "_enqueue", lambda jobs: None)
        first = _inbound(store, "1", "42", "Hallo", "10")
        melody.answers.append("Danke dir, ich lege gleich los!")
        order = _paid(store, first, foto, "Strandfoto", delivery_s=1500.0)
        cockpit._start_paid_orders()
        for _ in range(200):
            outs = [i for i in store.conversation_items(first.customer.id, 0, 80)[0]
                    if i["direction"] == "out" and i["ai_run_id"]]  # fmt: skip
            if outs:
                break
            await asyncio.sleep(0.01)
        assert outs[-1]["text"] == "Danke dir, ich lege gleich los!\n\nLieferzeit ca. 25 Minuten"
        assert outs[-1]["status"] == "queued" and melody.calls[-1]["message"] == "Bedanke dich."
        # Verzug: genau eine Zwischennachricht aus dem Vertröst-Vorrat
        persona = store.active_persona(clara)
        store.add_consolation(persona["id"], "Dauert noch einen Moment!", None)
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="milliseconds")
        store.db.execute("UPDATE offers SET production_started_at = ? WHERE order_id = ?",
                         (past, order.id))  # fmt: skip
        cockpit._delay_notices()
        cockpit._delay_notices()
        texts = [i["text"] for i in store.conversation_items(first.customer.id, 0, 80)[0]
                 if i["direction"] == "out"]  # fmt: skip
        assert texts.count("Dauert noch einen Moment!") == 1
        assert store.offer(order.id)["delay_notice_at"]

    _run(cloner_cfg, scenario)


def test_test_orders_run_as_default_class(cloner_cfg, monkeypatch):  # noqa: F811
    from test_kundentest import _prepare

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, clara = _prepare(cockpit, cloner_cfg)
        store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                              "Ich bin eine KI.", PRODUCTS[:1])  # fmt: skip
        store.set_influencer_switches(clara, True, True, True)
        foto = store.influencers()[0]["prices"][0]
        monkeypatch.setattr(cockpit, "_product_problems", lambda *_a, **_k: [])
        monkeypatch.setattr(cockpit, "_enqueue", lambda jobs: None)
        first = send("t1", "Hi", "t1")
        order = store.create_offer(
            first.customer.id, first.conversation_id, "Foto", False, 2000, SOON, {},
            product_id=foto["id"], test=True, wish="Strandfoto", delivery_s=300.0,
        )  # fmt: skip
        cockpit._test_release(order.order_no, "Test")
        assert store.order(order.order_no).status == "producing"
        (stage,) = store.stages(order.id)
        job = store.stage_jobs(stage.id)[0]["id"]
        assert store.job_priorities([job])[job] == "default"

    _run(cloner_cfg, scenario)
