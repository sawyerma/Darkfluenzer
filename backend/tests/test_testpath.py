"""Kundentest mit Bild (SP5 Schritt 12, SPEC-008): Testauftrag nur an der internen Default-Akte
(Trigger, unveränderlich), Testangebot im Kundentest ohne Zahlungswege, Testfreigabe per Wort
(„Cash“) oder automatisch, kein Eingang im Wallet; Liefer-Gate und beide Trigger lassen „ohne
Zahlung“ nur zu, wenn alle Bedingungen gelten; Verlassen des Testbetriebs bricht offene
Testaufträge ab; Testmedien dürfen gelöscht werden."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from test_channels import BOT, _cloner_setup, _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_chat import Melody, _settle
from test_kundentest import _prepare, _rows
from test_server import _run

from darkfluenzer import approval
from darkfluenzer.nodes import llm
from darkfluenzer.store import Store, StoreError
from darkfluenzer.web import http as server

READY = ('{"minor_hint": false, "explicit_wish": false, "purchase_readiness": 2, '
         '"wish": {"kind": "image", "description": "Strandfoto", "source": ""}}')  # fmt: skip
SOON = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="milliseconds")


def _default_chat(store):
    """Default-Kontakt mit Telegram-ID 99, Konto im Testbetrieb, eine Nachricht (verifiziert)."""
    store.import_channel_account({"key": "tg", "platform": "telegram"})
    store.set_account_platform_id("tg", BOT)
    default = store.default_contact()
    store.update_default_contact(default["revision"], {}, {("telegram", BOT): "99"})
    first = _inbound(store, "d1", "99", "hallo", "d1")
    store.set_account_mode("tg", "test")
    return first


def _approved_test_order(store, tmp_path, conv_customer, conv):
    order = store.create_offer(conv_customer, conv, "Foto", False, 2000, SOON, {}, test=True)
    store.release_test_order(order.order_no, "Test")
    for status in ("producing", "review"):
        store.transition(order.order_no, status)
    file = store.order_dir(store.order(order.order_no)) / "work" / "ergebnis.png"
    file.write_bytes(b"\x89PNG test")
    art = store.add_artifact(order.order_no, "master", file)
    store.db.execute(
        "UPDATE media SET content_tier = 'standard' WHERE artifact_id = ?", (art.id,)
    )  # Inhaltsstufe standard (Regel 13)
    store.record_approval(order.order_no, art.id, "approved", "Betreiber")
    return store.order(order.order_no), art


def test_test_orders_only_internal_and_immutable(tmp_path):
    store = Store(tmp_path / "local")
    first = _default_chat(store)
    customer = _inbound(store, "c1", "42", "hallo", "c1")
    with pytest.raises(sqlite3.IntegrityError, match="nur an der internen Default-Akte"):
        store.create_offer(customer.customer.id, customer.conversation_id, "Foto", False, 2000,
                           SOON, {}, test=True)  # fmt: skip
    order = store.create_offer(first.customer.id, first.conversation_id, "Foto", False, 2000,
                               SOON, {}, test=True)  # fmt: skip
    with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
        store.db.execute("UPDATE orders SET test = 0 WHERE id = ?", (order.id,))
    real = store.create_offer(customer.customer.id, customer.conversation_id, "Foto", False, 2000,
                              SOON, {})  # fmt: skip
    with pytest.raises(StoreError, match="kein Testauftrag"):
        store.release_test_order(real.order_no, "Test")
    assert [o["order_no"] for o in store.open_offers()] == [real.order_no]  # Wallet: kein Test
    store.release_test_order(order.order_no, "Wort „Cash“")
    assert store.order(order.order_no).status == "paid"
    assert store.db.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM payment_inflows").fetchone()[0] == 0
    store.close()


def test_gate_and_triggers_allow_test_only_under_all_conditions(tmp_path):
    store = Store(tmp_path / "local")
    first = _default_chat(store)
    order, art = _approved_test_order(store, tmp_path, first.customer.id, first.conversation_id)
    no = order.customer_no
    assert approval.check_gate(store, order.order_no, art.id, no).ok
    store.set_account_mode("tg", "production")  # Betriebsart nicht test: Zahlung fehlt
    gate = approval.check_gate(store, order.order_no, art.id, no)
    assert "PAYMENT_NOT_CONFIRMED" in gate.reasons
    with pytest.raises(StoreError, match="PAYMENT_NOT_CONFIRMED"):
        approval.prepare_delivery(store, order.order_no, art.id, no)
    with pytest.raises(sqlite3.IntegrityError, match="keine bestätigte"):  # Trigger allein
        store.db.execute(
            "INSERT INTO deliveries (order_id, customer_id, artifact_id, artifact_sha256,"
            " idempotency_key, status, created_at) VALUES (?,?,?,?,'x','pending',?)",
            (order.id, order.customer_id, art.id, art.sha256, SOON),
        )
    store.set_account_mode("tg", "test")
    delivery = approval.prepare_delivery(store, order.order_no, art.id, no)
    # Versand-Trigger: Zustellnachricht an eine fremde Konversation -> abgewiesen
    other = _inbound(store, "c1", "42", "hallo", "c1")
    wrong = store.queue_outbound(other.customer.id, other.conversation_id, "", revision=1,
                                 delivery_id=delivery)  # fmt: skip
    with pytest.raises(sqlite3.IntegrityError, match="Gate beim Versand"):
        store.db.execute("UPDATE deliveries SET status = 'sent' WHERE id = ?", (delivery,))
    store.db.execute("UPDATE channel_messages SET conversation_id = ? WHERE id = ?",
                     (first.conversation_id, wrong))  # fmt: skip
    store.db.execute("UPDATE deliveries SET status = 'sent' WHERE id = ?", (delivery,))
    store.close()


def test_test_media_may_be_deleted(tmp_path):
    store = Store(tmp_path / "local")
    first = _default_chat(store)
    order = store.create_offer(first.customer.id, first.conversation_id, "Foto", False, 2000,
                               SOON, {}, test=True)  # fmt: skip
    store.db.execute(
        "INSERT INTO media (path, kind, sha256, size, created_at, order_id) VALUES (?,?,?,?,?,?)",
        ("t.png", "image", "f" * 64, 9, SOON, order.id),
    )
    real = _inbound(store, "c1", "42", "hallo", "c1")
    paid = store.create_offer(real.customer.id, real.conversation_id, "Foto", False, 2000, SOON, {})
    store.db.execute(
        "INSERT INTO media (path, kind, sha256, size, created_at, order_id) VALUES (?,?,?,?,?,?)",
        ("k.png", "image", "e" * 64, 9, SOON, paid.id),
    )
    with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
        store.db.execute("DELETE FROM media WHERE order_id = ?", (paid.id,))
    store.db.execute("DELETE FROM media WHERE order_id = ?", (order.id,))  # kein Abbruch
    store.close()


def test_kundentest_offer_cash_word_and_mode_switch(cloner_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, clara = _prepare(cockpit, cloner_cfg)
        store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                              "Ich bin eine KI.", [{"product": "Foto", "price_cents": 2000,
                                                   "hd_surcharge_cents": 0}])  # fmt: skip
        monkeypatch.setattr(cockpit, "_product_problems", lambda *_a, **_k: [])
        monkeypatch.setattr(cockpit, "_delivery_estimate", lambda *_a: (300.0, ""))
        first = send("t1", "Hi Clara", "t1")
        await cockpit._on_inbound(first)
        await _settle(cockpit)
        conv = first.conversation_id
        melody.classes.append(READY)
        melody.answers.append("Gern, hier dein Testangebot:")
        await cockpit._on_inbound(send("t2", "Strandfoto bitte", "t2"))
        await _settle(cockpit)
        offer = store.open_offer_of(conv)
        order = store.order(offer["order_no"])
        assert order.test and offer["facts"].startswith(f"Testangebot {order.order_no}")
        assert "Testfreigabe: „Cash“ senden" in offer["facts"]
        reply = [r for r in _rows(store, first.customer.id) if r["test"]][-1]
        assert reply["text"].endswith(offer["facts"]) and reply["direction"] == "out"
        # „Cash“: festes Wort, nie an Melody; bezahlt ohne Zahlung, Antwort im Testverlauf
        calls = len(melody.calls)
        await cockpit._on_inbound(send("t3", "Cash", "t3"))
        assert len(melody.calls) == calls
        assert store.order(order.order_no).status == "paid"
        texts = [r["text"] for r in _rows(store, first.customer.id) if r["test"]]
        assert any(t.startswith(f"Testfreigabe für {order.order_no}") for t in texts)
        assert store.db.execute("SELECT count(*) FROM payment_inflows").fetchone()[0] == 0
        # Verlassen des Testbetriebs: offener Testauftrag abgebrochen
        await cockpit._on_inbound(send("w1", "Produktion", "w1"))
        assert store.order(order.order_no).status == "cancelled"
        assert store.order_reason(order.id) == "Testbetrieb beendet"
        # automatische Testfreigabe
        store.set_account_mode("tg", "test")
        default = store.default_contact()
        store.update_default_contact(default["revision"], {"test_auto_pay": 1}, {})
        melody.classes.append(READY)
        melody.answers.append("Gern!")
        await cockpit._on_inbound(send("t4", "Noch ein Strandfoto", "t4"))
        await _settle(cockpit)
        auto = store.db.execute(
            "SELECT order_no FROM orders WHERE test = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert store.order(auto).status == "paid"

    _run(cloner_cfg, scenario)
