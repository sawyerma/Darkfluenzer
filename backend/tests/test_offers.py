"""Angebot (SP5 Schritt 2): Lieferzeit aus Messwerten, Faktenblock wörtlich vom Backend, Angebot aus
dem Dialog (Wunsch bestätigt, Kaufbereitschaft ab 2), Angebotstext ohne Ziffern, Ablehnung mit
Sperrzeit, Ablauf als Zeitaufgabe, Zahlung in Prüfung (Frist ruht) und Eingang nach Ablauf (E24)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from test_channels import BOT, _inbound
from test_chat import FAST, Melody, _settle, _setup, chat_cfg  # noqa: F401  (Fixture)
from test_customer_orders import EVM
from test_server import _run

from darkfluenzer.core import assessment, eta
from darkfluenzer.nodes import llm
from darkfluenzer.store import Store
from darkfluenzer.web import http as server

FOTO = {"workflow": "wf_bild", "finish_workflow": "", "kind": "image", "candidates": 2}
VIDEO = {"workflow": "wf_bild", "finish_workflow": "wf_anim", "kind": "video", "candidates": 1}
READY = ('{"minor_hint": false, "explicit_wish": false, "purchase_readiness": 2, '
         '"wish": {"kind": "image", "description": "Strandfoto", "source": ""}}')  # fmt: skip
REJECT = ('{"minor_hint": false, "explicit_wish": false, "purchase_readiness": 0, '
          '"offer_response": "reject"}')  # fmt: skip


def test_delivery_time_from_measurements():
    runs = {"wf_bild": 100.0, "wf_anim": 300.0, "wf_other": 50.0}.get
    steps = {"train": 2.0}.get
    assert eta.delivery_s(FOTO, [], lambda k: runs(k) or 0, lambda k: 0) == (200.0, "")
    assert eta.delivery_s(VIDEO, [], lambda k: runs(k) or 0, lambda k: 0) == (400.0, "")
    pending = [
        eta.Pending("wf_other", "running", "cockpit", elapsed_s=20),  # Rest 30 s
        eta.Pending("wf_other", "queued", "customer"),  # bezahlter Kundenauftrag: davor
        eta.Pending("wf_other", "queued", "cockpit"),  # andere Klassen: danach
        eta.Pending("train", "running", "training", elapsed_s=100, steps=100, training=True),
    ]
    got, why = eta.delivery_s(FOTO, pending, lambda k: runs(k) or 0, lambda k: steps(k) or 0)
    assert why == "" and got == 200 + 30 + 50 + 100  # Training: 100 Schritte × 2 s − 100 s
    none, why = eta.delivery_s({**FOTO, "workflow": "neu"}, [], lambda k: 0, lambda k: 0)
    assert none is None and "keine Laufzeitmessung für neu" in why
    train = [eta.Pending("train", "running", "training", training=True)]
    assert eta.delivery_s(FOTO, train, lambda k: runs(k) or 0, lambda k: 0)[0] is None
    assert (eta.minutes(1), eta.minutes(301), eta.minutes(900)) == (5, 10, 15)


def test_run_seconds_median(tmp_path):
    store = Store(tmp_path / "local")
    for seconds in (30.0, 10.0, 20.0):
        job = store.create_job(None, "e", "wf_bild", "p", {}, [])
        store.set_job_status(job, "done", duration_s=seconds, outputs=[])
    queued = store.create_job(None, "e", "wf_bild", "p", {"steps": 9}, [], priority="customer")
    assert store.run_seconds("wf_bild", 5) == 20.0 and store.run_seconds("x", 5) == 0.0
    assert store.run_seconds("wf_bild", 1) == 20.0  # nur der letzte Lauf
    (row,) = store.pending_jobs()
    assert row["id"] == queued and row["priority"] == "customer" and row["steps"] == 9
    store.close()


def _offer(store, first, expires: str, amounts=None, payments=None):
    return store.create_offer(
        first.customer.id, first.conversation_id, "Foto", False, 2000, expires, amounts or {},
        payments=payments or [{"way": "amazon", "amount": "20.00", "currency": "EUR"}],
    )  # fmt: skip


def _cards(store, customer_id):
    return [i["text"] for i in store.conversation_items(customer_id, 0, 80)[0]
            if i["direction"] == "system"]  # fmt: skip


def test_expiry_review_and_late_inflow(tmp_path):
    store = Store(tmp_path / "local")
    default = store.default_contact()
    store.update_default_contact(default["revision"], {}, {("telegram", BOT): "99"})
    phone = _inbound(store, "0", "99", "hallo", "1")  # Default-Chat besteht
    first = _inbound(store, "1", "42", "hallo", "10")
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="milliseconds")
    future = (datetime.now(UTC) + timedelta(minutes=30)).isoformat(timespec="milliseconds")
    amounts = {"usdt": ("21.0001", EVM, 0.95, 1)}
    late = _offer(store, first, past, amounts)
    review = _offer(store, first, past)
    store.db.execute("UPDATE offers SET expires_at = ? WHERE order_id = ?", (future, review.id))
    assert store.offer(late.id)["payments"][0]["way"] == "amazon"
    # Gutscheincode im Chat: jüngstes offenes Angebot nach payment_review, die Frist ruht
    _inbound(store, "2", "42", "hier: ab12-cd34ef-gh56", "11")
    assert store.order(review.order_no).status == "payment_review"
    assert store.offer(review.id)["review_started_at"]
    now = datetime.now(UTC).isoformat(timespec="milliseconds")
    much_later = (datetime.now(UTC) + timedelta(hours=2)).isoformat(timespec="milliseconds")
    assert store.expire_offers(now) == [late.order_no]  # nur offered mit abgelaufener Frist
    assert store.order(late.order_no).status == "cancelled"
    assert store.order_reason(late.id) == "abgelaufen"
    assert store.expire_offers(much_later) == []  # in Prüfung: Frist ruht
    assert any(
        c.startswith(f"ANGEBOT ABGELAUFEN · {late.order_no}")
        for c in _cards(store, first.customer.id)
    )
    # Gutschein abgelehnt: zurück nach offered mit Restfrist (Frist um die Prüfdauer verlängert)
    store.db.execute(
        "UPDATE offers SET review_started_at = ? WHERE order_id = ?",
        ((datetime.now(UTC) - timedelta(minutes=10)).isoformat(timespec="milliseconds"),
         review.id),
    )  # fmt: skip
    (voucher,) = [v for v in store.vouchers(5) if v["status"] == "pending"]
    store.reject_voucher(voucher["id"])
    assert store.order(review.order_no).status == "offered"
    moved = datetime.fromisoformat(store.offer(review.id)["expires_at"])
    assert moved - datetime.fromisoformat(future) >= timedelta(minutes=9, seconds=59)
    # Eingang nach Ablauf (E24): bleibt nicht zugeordnet, Karte und Meldung ans Handy
    pay = dict(network="bsc", asset="USDT", position=0, block=1, required=15, eur=20.0,
               rate=0.95, rate_ms=1)  # fmt: skip
    store.upsert_payment(method="usdt", amount="21.0001", txid="0xl", confirmations=20, **pay)
    assert store.payment_page(0, 10, "unassigned")[0][0]["txid"] == "0xl"
    assert store.order(late.order_no).status == "cancelled"
    assert any(c.startswith("EINGANG NACH ABLAUF") for c in _cards(store, first.customer.id))
    notes = [i for i in store.conversation_items(phone.customer.id, 0, 20)[0]
             if i["direction"] == "out"]  # fmt: skip
    assert notes and notes[-1]["text"].startswith("EINGANG NACH ABLAUF")
    with pytest.raises(Exception, match="kein offenes Angebot"):
        store.assign_inflow(store.payment_page(0, 10, "unassigned")[0][0]["id"],
                            late.order_no, "Betreiber")  # fmt: skip
    store.close()


def test_assessment_offer_response():
    typed, why = assessment.parse({**_base(), "offer_response": "reject"})
    assert why == "" and "offer_rejected" in typed.consequences
    assert "offer_ready" not in typed.consequences
    assert assessment.parse({**_base(), "offer_response": "vielleicht"})[0] is None


def _base():
    return {"minor_hint": False, "explicit_wish": False, "purchase_readiness": 3,
            "wish": {"kind": "image", "description": "Strandfoto", "source": ""}}  # fmt: skip


def test_dialog_offer_fact_block_rejection_cooldown(chat_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, _adapter = _setup(cockpit)
        monkeypatch.setattr(cockpit, "_product_problems", lambda *_a, **_k: [])
        monkeypatch.setattr(cockpit, "_delivery_estimate", lambda *_a: (840.0, ""))
        first = _inbound(store, "1", "42", "Hallo", "10")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        assert "Lieferzeit ca. 15 Minuten" in melody.calls[-1]["facts"]  # Lieferstand im Lauf
        conv = first.conversation_id
        melody.classes.append(READY)
        melody.answers.append("Gern, so machen wir es:")
        await cockpit._on_inbound(_inbound(store, "2", "42", "Ja, das Strandfoto bitte", "11"))
        await _settle(cockpit)
        offer = store.open_offer_of(conv)
        assert offer is not None and offer["status"] == "offered" and offer["delivery_s"] == 840
        reply = [i for i in store.conversation_items(first.customer.id, 0, 80)[0]
                 if i["direction"] == "out"][-1]  # fmt: skip
        assert reply["status"] == "queued" and reply["text"].startswith("Gern, so machen wir es:")
        assert (
            reply["text"].endswith(offer["facts"])
            and "Amazon-Gutschein über 20,00 €" in offer["facts"]
        )
        assert "Lieferzeit ca. 15 Minuten nach Zahlungseingang" in offer["facts"]
        assert any(
            c.startswith("ANGEBOT · Foto · 20,00 €") for c in _cards(store, first.customer.id)
        )
        # ein offenes Angebot genügt
        melody.classes.append(READY)
        await cockpit._on_inbound(_inbound(store, "3", "42", "Also ja", "12"))
        await _settle(cockpit)
        assert store.db.execute("SELECT count(*) FROM offers").fetchone()[0] == 1
        # Ablehnung: Auftrag cancelled „abgelehnt“, danach Sperrzeit
        store.set_influencer_sales(clara, ["amazon"], 0, 30)
        melody.classes.append(REJECT)
        await cockpit._on_inbound(_inbound(store, "4", "42", "Nein, doch nicht", "13"))
        await _settle(cockpit)
        assert store.order(offer["order_no"]).status == "cancelled"
        assert store.last_rejection(conv)
        melody.classes.append(READY)
        await cockpit._on_inbound(_inbound(store, "5", "42", "Doch, mach!", "14"))
        await _settle(cockpit)
        assert store.open_offer_of(conv) is None
        assert any("Sperrzeit nach Ablehnung bis" in c for c in _cards(store, first.customer.id))
        # ohne Sperrzeit: Angebot, aber Text mit Ziffern -> Entwurf mit Grund
        store.set_influencer_sales(clara, ["amazon"], 0, 0)
        melody.classes.append(READY)
        melody.answers.append("Für 20 € schicke ich es dir.")
        await cockpit._on_inbound(_inbound(store, "6", "42", "Jetzt aber", "15"))
        await _settle(cockpit)
        assert store.open_offer_of(conv) is not None
        draft = [i for i in store.conversation_items(first.customer.id, 0, 80)[0]
                 if i["direction"] == "out"][-1]  # fmt: skip
        assert draft["status"] == "draft" and "Ziffern" in draft["error"]
        # kein lieferbares Produkt: Karte mit Grund, kein Angebot
        store.reject_offer(store.open_offer_of(conv)["order_no"], "Test")
        monkeypatch.setattr(cockpit, "_delivery_estimate", lambda *_a: (None, "keine Messung"))
        melody.classes.append(READY)
        await cockpit._on_inbound(_inbound(store, "7", "42", "Und nun?", "16"))
        await _settle(cockpit)
        assert store.open_offer_of(conv) is None
        assert any("Lieferzeit für Foto unbekannt" in c for c in _cards(store, first.customer.id))

    _run(chat_cfg, scenario)
