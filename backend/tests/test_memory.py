"""SP4 Schritt 5 (B5.3): Gedächtnis – SQLite mit FTS5, Bereiche strikt getrennt, Quelle, Zeit und
Verlauf, Auswahl je Ebene nach Konfiguration, Übernahme der Einträge aus der Einstufung,
Wiederholung."""

from __future__ import annotations

import dataclasses

import pytest

from darkfluenzer.core import assessment, memory
from darkfluenzer.store import Store, StoreError


def test_store_scopes_history_search_and_restart(tmp_path):
    store = Store(tmp_path / "local")
    a = store.add_memory(
        "studio", 1, 1, "customer", "Mag Pasta und Rotwein", source="Lauf #1", origin="ai"
    )
    store.add_memory("studio", 1, 1, "customer", "Wohnt in Hamburg", source="Lauf #2", origin="ai")
    store.add_memory(
        "studio", 1, 2, "customer", "Andere Sitzung: mag Sushi", source="x", origin="ai"
    )
    store.add_memory("customer", 1, 0, "customer", "Kunde 1: mag Pasta", source="x", origin="ai")
    hits = store.search_memories("studio", 1, 1, "customer", "Was isst du gern? Pasta?", 5)
    assert [h["id"] for h in hits][0] == a and hits[0]["score"] is not None  # FTS-Treffer zuerst
    assert {h["text"] for h in hits} == {
        "Mag Pasta und Rotwein",
        "Wohnt in Hamburg",
    }  # nur dieser Bereich
    b = store.replace_memory(
        a, "Mag Pasta, keinen Rotwein mehr", source="Betreiber", origin="operator"
    )
    old = store.memory(a)
    assert old["status"] == "replaced" and old["replaced_by"] == b
    with pytest.raises(StoreError, match="nicht mehr aktiv"):
        store.replace_memory(a, "x", source="x", origin="operator")
    store.delete_memory(b, origin="operator")
    assert [m["text"] for m in store.memories("studio", 1, 1)] == ["Wohnt in Hamburg"]
    assert len(store.memories("studio", 1, 1, active_only=False)) == 3  # Verlauf bleibt
    store.close()
    again = Store(tmp_path / "local")  # Neustart
    assert [m["text"] for m in again.memories("studio", 1, 1)] == ["Wohnt in Hamburg"]
    events = [e["event"] for e in again.memory_events(0, 50)[0]]
    assert events.count("added") == 5 and "replaced" in events and "deleted" in events


def test_selection_per_level_input_and_apply(cfg, tmp_path):
    store = Store(tmp_path / "local")
    cfg = dataclasses.replace(cfg, ai=dataclasses.replace(cfg.ai, memory_hits={
        "customer": 2, "memo": 1, "event": 0, "self": 1}))  # fmt: skip
    for i in range(4):
        store.add_memory("studio", 7, 1, "customer", f"Fakt {i}", source="x", origin="ai")
    store.add_memory("studio", 7, 1, "event", "Bestellt: Foto am Strand", source="x", origin="ai")
    store.add_memory("studio", 7, 1, "self", "Ich mag Katzen", source="x", origin="ai")
    chosen = memory.select(store, cfg, "studio", 7, 1, "Magst du Katzen?")
    assert [m["level"] for m in chosen] == ["customer", "customer", "self"]  # event: 0 Treffer
    assert chosen[-1]["reason"] == "Treffer" and chosen[0]["reason"] == "jüngste"
    text = memory.as_input(chosen)
    assert text.splitlines()[-1].endswith("[Eigene Aussage] Ich mag Katzen") and text.startswith(
        "#"
    )
    cat = chosen[-1]["id"]
    foreign = store.add_memory("studio", 8, 1, "self", "fremd", source="x", origin="ai")
    items = [assessment.MemoryItem("self", "Ich mag Katzen und Hunde", replaces=cat),
             assessment.MemoryItem("event", "Will Video", replaces=foreign),
             assessment.MemoryItem("memo", "Plaudern über Tiere")]  # fmt: skip
    done = memory.apply_items(store, "studio", 7, 1, items, "Lauf #9")
    assert [d[0] for d in done] == ["replaced", "added", "added"]  # fremde ID: neu, nie ersetzt
    assert store.memory(foreign)["status"] == "active" and store.memory(cat)["status"] == "replaced"
    assert store.memory(done[1][1])["source"] == "Lauf #9"


def test_repetition_and_schema_memory_field():
    assert memory.similarity("Hallo du, wie geht es dir?", "hallo du wie geht es dir") == 1.0
    assert memory.repeats("Ganz neu hier", ["Hallo du, wie geht es dir?"], 0.8) == 0.0
    assert (
        memory.repeats("Hallo du wie geht es dir heute", ["Hallo du, wie geht es dir?"], 0.8) > 0.8
    )
    base = {"minor_hint": False, "explicit_wish": False, "purchase_readiness": 0}
    items = [
        {"level": "customer", "text": "Mag Pasta"},
        {"level": "self", "text": " ", "replaces": 3},
    ]
    typed, _ = assessment.parse(base | {"memory": items})
    assert typed.memory == (assessment.MemoryItem("customer", "Mag Pasta"),)  # leere entfallen
    assert (
        "memory braucht level"
        in assessment.parse(base | {"memory": [{"level": "x", "text": "a"}]})[1]
    )
    assert "memory muss eine Liste" in assessment.parse(base | {"memory": "Pasta"})[1]
