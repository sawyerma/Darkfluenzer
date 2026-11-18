"""Gedächtnis im Lauf (SP4 Schritt 5, B5.3): Auswahl, Übergabe an den Sprachworkflow, Übernahme der
von Melody formulierten Einträge und Wiederholungsprüfung.

- Ebene 1 (Kurzzeit) ist der Verlauf der Sitzung bzw. Konversation (eigener Eingang ``context``).
- Ebenen 2–4 und eigene Aussagen kommen aus ``memories`` (SQLite, FTS5): je Ebene die besten
  Treffer zur neuen Nachricht, aufgefüllt mit den jüngsten; Zahlen aus ``[ai.memory]``.
- Was gemerkt wird, formuliert Melody im neutralen Lauf (Schemafeld ``memory``); ein Eintrag kann
  eine ältere Erinnerung desselben Bereichs ersetzen (``replaces``, Verlauf bleibt).
- Bereiche sind strikt getrennt; eine Ersetzung über die Bereichsgrenze wird abgewiesen."""

from __future__ import annotations

import re

from ..config import Config
from . import assessment

LEVEL_LABEL = {
    "customer": "Kundengedächtnis",
    "memo": "Gesprächsmemo",
    "event": "Ereignis",
    "self": "Eigene Aussage",
}
_WORD = re.compile(r"[\wÄÖÜäöüß]+")


def select(store, cfg: Config, scope: str, owner_id: int, session: int, query: str) -> list[dict]:
    """Erinnerungen für den nächsten Lauf: je Ebene FTS5-Treffer zur Nachricht, dann jüngste."""
    chosen = []
    for level, limit in cfg.ai.memory_hits.items():
        for row in store.search_memories(scope, owner_id, session, level, query, limit):
            chosen.append(
                row | {"reason": "Treffer" if row.get("score") is not None else "jüngste"}
            )
    return chosen


def as_input(chosen: list[dict]) -> str:
    """Eingang ``memory`` des Sprachworkflows: je Zeile Nummer, Ebene und Text (Daten)."""
    return "\n".join(f"#{m['id']} [{LEVEL_LABEL[m['level']]}] {m['text']}" for m in chosen)


def apply_items(
    store, scope: str, owner_id: int, session: int, items: list[assessment.MemoryItem], source: str
) -> list[tuple[str, int]]:
    """Von Melody vorgeschlagene Einträge übernehmen; liefert (Aktion, ID) je Eintrag. Ersetzt wird
    nur eine aktive Erinnerung desselben Bereichs, sonst wird neu angelegt."""
    done = []
    for item in items:
        target = None
        if item.replaces:
            try:
                old = store.memory(item.replaces)
            except Exception:  # noqa: BLE001 – unbekannte ID: neu anlegen
                old = None
            same = old and (old["scope"], old["owner_id"], old["session"]) == (
                scope,
                owner_id,
                session,
            )
            target = item.replaces if same and old["status"] == "active" else None
        if target:
            done.append(
                ("replaced", store.replace_memory(target, item.text, source=source, origin="ai"))
            )
        else:
            mid = store.add_memory(scope, owner_id, session, item.level, item.text, source=source,
                                   origin="ai")  # fmt: skip
            done.append(("added", mid))
    return done


def similarity(a: str, b: str) -> float:
    """Wortmengen-Überdeckung (Jaccard) zweier Antworten – technische Wiederholungsprüfung."""
    wa, wb = ({w.lower() for w in _WORD.findall(t)} for t in (a, b))
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def repeats(answer: str, previous: list[str], threshold: float) -> float:
    """Höchste Ähnlichkeit zu einer früheren Antwort, wenn sie die Schwelle erreicht, sonst 0."""
    best = max((similarity(answer, p) for p in previous), default=0.0)
    return best if best >= threshold else 0.0
