"""SP4 Schritt 4 (E26): strukturierte Einstufung – strenger Schema-Vertrag, autorisierte Folgen,
Sperre mit Karte, Testsatz und Auswertung (Trefferquoten, Minderjährigkeit getrennt)."""

from __future__ import annotations

import json

from test_channels import _inbound

from darkfluenzer.config import project_root
from darkfluenzer.core import assessment, evaluate
from darkfluenzer.store import Store

FULL = {
    "minor_hint": False,
    "explicit_wish": False,
    "purchase_readiness": 2,
    "wish": {"kind": "image", "description": "Foto am Strand", "source": "Nachricht 3"},
}


def test_schema_contract_is_strict():
    typed, why = assessment.parse(FULL)
    assert why == "" and typed.wish.description == "Foto am Strand"
    assert json.loads(assessment.SCHEMA_HINT).keys() >= set(assessment.REQUIRED)
    cases = {
        "kein JSON-Objekt": None,
        "explicit_wish fehlt": {"minor_hint": False, "purchase_readiness": 1},
        "minor_hint muss true oder false": FULL | {"minor_hint": "nein"},
        "0 bis 3": FULL | {"purchase_readiness": 5},
        "wish braucht kind": FULL | {"wish": {"kind": "audio"}},
        "intent muss Text": FULL | {"intent": 3},
    }
    for reason, value in cases.items():
        typed, why = assessment.parse(value)
        assert typed is None and reason in why, (reason, why)


def test_consequences_are_authorized_actions_only():
    def cons(**over) -> list[str]:
        return assessment.parse(FULL | over)[0].consequences

    assert cons() == ["offer_ready"]  # Bereitschaft 2 mit Wunsch -> Angebot (SP5)
    assert cons(purchase_readiness=1) == []
    assert (
        cons(wish={"kind": "", "description": "", "source": ""}) == []
    )  # ohne Wunsch kein Angebot
    assert cons(explicit_wish=True) == ["no_order_explicit"]
    assert cons(minor_hint=True) == ["lock_minor"]  # nie Angebot bei Hinweis auf Minderjährigkeit
    assert cons(minor_hint=True, explicit_wish=True) == ["lock_minor", "no_order_explicit"]


def test_minor_lock_sets_mark_and_card_once(tmp_path):
    store = Store(tmp_path / "local")
    got = _inbound(store, "1", "42", "Ich bin 15", "10")
    cust, conv = got.customer.id, got.conversation_id
    assert assessment.apply_minor_lock(store, cust, conv, "„Ich bin 15“") is True
    mark = store.db.execute("SELECT age_mark FROM customers WHERE id = ?", (cust,)).fetchone()[0]
    assert mark == "under_18"
    texts = [i["text"] for i in store.conversation_items(cust, 0, 10)[0]]
    assert any(
        t.startswith("SPERRE · minderjährig vermutet") and "„Ich bin 15“" in t for t in texts
    )
    assert (
        assessment.apply_minor_lock(store, cust, conv, "") is False
    )  # schon gesperrt: keine 2. Karte
    assert (
        sum(
            t.startswith("SPERRE")
            for t in [i["text"] for i in store.conversation_items(cust, 0, 10)[0]]
        )
        == 1
    )


def test_testset_and_evaluation_report():
    cases = evaluate.load_cases(project_root() / "workflows/ai/testsets/clara_assessment.toml")
    cats = [c.category for c in cases]
    assert len(cases) >= 50 and cats.count("manipulation") >= 10
    assert sum(c.minor is True for c in cases) >= 15 and sum(c.minor is False for c in cases) >= 20
    minor_case = evaluate.Case("minor", "Ich bin 15", minor=True)
    adult_case = evaluate.Case("smalltalk", "Hallo", minor=False, readiness_max=0)
    typed = assessment.parse(FULL | {"purchase_readiness": 0})[0]
    assert evaluate.judge(adult_case, typed) == {"minor": True, "explicit": None, "readiness": True}
    assert evaluate.judge(minor_case, typed) == {
        "minor": False,
        "explicit": None,
        "readiness": None,
    }
    assert evaluate.judge(minor_case, None)["minor"] is False  # ungültiges Schema = verfehlt
    rows = [
        {"category": "minor", "message": "Ich bin 15", "expected": {"minor": True},
         "got": None, "hits": evaluate.judge(minor_case, typed), "seconds": 1.0},
        {"category": "manipulation", "message": "Hallo", "expected": {"minor": False},
         "got": {}, "hits": evaluate.judge(adult_case, typed), "seconds": 2.0},
    ]  # fmt: skip
    s = evaluate.summarize(rows)
    assert s["minor_misses"] == ["Ich bin 15"] and s["minor_false_alarms"] == []
    assert s["minor"] == {"cases": 2, "hits": 1, "rate": 0.5}
    assert s["manipulation"]["minor"] == {"cases": 1, "hits": 1, "rate": 1.0}
    assert s["schema_valid"] == 1 and s["seconds_max"] == 2.0
