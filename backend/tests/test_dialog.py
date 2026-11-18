"""SP4 Schritt 3 (SPEC-017): Gates vor dem Versand – Zahlen- und Zustandsabgleich, keine
Sprachdeutung. Fakten aus Preisliste und Konfiguration, Begriffskatalog aus [dialog]."""

from __future__ import annotations

import dataclasses

from darkfluenzer.config import DEFAULT_PAYMENT_TERMS
from darkfluenzer.core import dialog

PRICES = ({"product": "Foto", "price_cents": 2000, "hd_surcharge_cents": 500},)
FACTS = dialog.Facts(PRICES, ("amazon",), {"amazon": "Amazon-Gutschein", "bank": "Überweisung"})
TERMS = DEFAULT_PAYMENT_TERMS
OK_SCHEMA = {"minor_hint": False, "explicit_wish": False, "purchase_readiness": 1}


def failed(gates: list[dialog.Gate]) -> dict[str, str]:
    return {g.name: g.reason for g in gates if not g.ok}


def test_amounts_from_facts_only_in_any_written_form():
    assert dialog.mentioned_amounts("20,00 € oder € 25 bzw. 5 Euro, 30.50 EUR") == [
        2000,
        2500,
        500,
        3050,
    ]
    assert FACTS.amounts() == {2000, 2500, 500}
    ok = dialog.check("Ein Foto kostet 20,00 €, mit HD 25 €.", OK_SCHEMA, FACTS, TERMS)
    assert dialog.sendable(ok) and [g.name for g in ok] == [
        "schema",
        "minor",
        "amounts",
        "payment_ways",
    ]
    bad = failed(dialog.check("Für dich nur 15 € statt 30,00 €!", OK_SCHEMA, FACTS, TERMS))
    assert bad == {
        "amounts": "15,00 € steht nicht in den Fakten, 30,00 € steht nicht in den Fakten"
    }
    assert dialog.check("Ich bin 20 Jahre alt.", OK_SCHEMA, FACTS, TERMS)[2].ok  # keine Währung


def test_payment_ways_only_when_released_and_schema_minor():
    assert dialog.mentioned_ways("Zahl per Überweisung oder PayPal", TERMS) == ["paypal", "bank"]
    bad = failed(
        dialog.check(
            "Schick mir einen Amazon-Gutschein oder per Überweisung.", OK_SCHEMA, FACTS, TERMS
        )
    )
    assert bad == {"payment_ways": "Zahlungsweg Überweisung nicht freigegeben"}
    assert dialog.check("Ich mag Gutscheinhefte", OK_SCHEMA, FACTS, TERMS)[3].ok  # ganzes Wort
    assert failed(dialog.check("Hi", None, FACTS, TERMS)) == {
        "schema": "Einstufung ist kein JSON-Objekt."
    }
    minor = failed(dialog.check("Hi", OK_SCHEMA | {"minor_hint": True}, FACTS, TERMS))
    assert minor == {"minor": "Einstufung meldet Minderjährigkeit."}
    # unvollständig: Schema-Gate; ein roher Hinweis auf Minderjährigkeit sperrt trotzdem
    bad = failed(dialog.check("Hi", {"minor_hint": True}, FACTS, TERMS))
    assert bad == {
        "schema": "Einstufung unvollständig: explicit_wish, purchase_readiness fehlt.",
        "minor": "Einstufung meldet Minderjährigkeit.",
    }


def test_customer_context_gates():
    ctx = dialog.ReplyContext(ai_notice_sent=True, age_mark="", operator_active=False,
                              automation=True, window_open=True, max_text_bytes=10)  # fmt: skip
    gates = dialog.check("Hallo du", OK_SCHEMA, FACTS, TERMS, ctx)
    assert dialog.sendable(gates) and len(gates) == 10
    worst = dataclasses.replace(
        ctx, ai_notice_sent=False, age_mark="under_18", operator_active=True, automation=False,
        window_open=False,
    )  # fmt: skip
    bad = failed(dialog.check("Hallo du, wie geht's?", OK_SCHEMA, FACTS, TERMS, worst))
    assert set(bad) == {"ai_notice", "locked", "operator", "automation", "window", "text_limit"}
    assert bad["text_limit"] == "Text zu lang (21 > 10 Byte)."


def test_facts_payment_ways_follow_configuration(cfg):
    from test_customer_orders import _wallet

    facts = dialog.facts_for(cfg, {"prices": list(PRICES)})
    assert facts.payment_ways == ("amazon",)  # ohne Wallet, PayPal noch nicht angeschlossen
    assert facts.text() == "Foto: 20,00 €, HD-Aufschlag 5,00 €\nZahlungswege: Amazon-Gutschein"
    wallet_cfg = dataclasses.replace(cfg, wallet=_wallet(cfg))
    assert dialog.facts_for(wallet_cfg, {"prices": []}).payment_ways == ("amazon",)  # gewählte
    chosen = {"prices": [], "payment_ways": ["amazon", "btc", "usdt", "usdc", "paypal"]}
    facts = dialog.facts_for(wallet_cfg, chosen)  # nur eingerichtete (SP5 Schritt 1)
    assert facts.payment_ways == ("amazon", "btc", "usdt")
    assert facts.text() == "Zahlungswege: Amazon-Gutschein, Bitcoin, USDT"
