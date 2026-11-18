"""Strukturierte Ergebnisse des neutralen Einstufungslaufs (SP4 Schritt 4, E26).

Melody liefert im registrierten Workflow ein JSON-Objekt nach der Schema-Anweisung im Profil.
Das Backend typisiert es streng und leitet daraus nur autorisierte Folgen ab – keine Textdeutung:

- ``minor_hint`` → Akte gesperrt (``age_mark = under_18``), kein Flirt, kein Angebot, Karte;
  aufheben kann nur der Betreiber (Befehl 44, protokolliert).
- ``explicit_wish`` → kein Auftrag; die Antwort (Fansly-Verweis) formuliert Melody.
- ``purchase_readiness`` ≥ ``OFFER_READINESS`` mit Wunsch → Angebot (SP5).

Schema-Vertrag (``SCHEMA_HINT``): Pflicht sind ``minor_hint``, ``explicit_wish`` und
``purchase_readiness`` (0–3); optional ``minor_evidence``, ``readiness_evidence``, ``intent`` und
``wish`` mit ``kind`` (image, video, leer), ``description``, ``source``, und ``memory`` (Liste
mit ``level`` customer, memo, event, self, ``text`` und optional ``replaces``, SP4 Schritt 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

OFFER_READINESS = 2  # ab dieser Kaufbereitschaft mit Wunsch folgt das Angebot (SP5)
WISH_KINDS = ("image", "video", "")
MEMORY_LEVELS = ("customer", "memo", "event", "self")
REQUIRED = ("minor_hint", "explicit_wish", "purchase_readiness")
SCHEMA_HINT = (
    '{"minor_hint": false, "minor_evidence": "", "explicit_wish": false, "purchase_readiness": 0, '
    '"readiness_evidence": "", "wish": {"kind": "", "description": "", "source": ""}, '
    '"intent": "", '
    '"memory": [{"level": "customer|memo|event|self", "text": "", "replaces": 0}]}'
)


@dataclass(frozen=True)
class Wish:
    kind: str = ""
    description: str = ""
    source: str = ""  # Quellnachricht (Zitat oder Verweis)


@dataclass(frozen=True)
class MemoryItem:
    """Vorschlag für das Gedächtnis (SP4 Schritt 5): Ebene, Text, optional ersetzte Erinnerung."""

    level: str
    text: str
    replaces: int = 0


@dataclass(frozen=True)
class Assessment:
    minor_hint: bool
    explicit_wish: bool
    purchase_readiness: int
    minor_evidence: str = ""
    readiness_evidence: str = ""
    wish: Wish = field(default_factory=Wish)
    intent: str = ""
    memory: tuple[MemoryItem, ...] = ()

    @property
    def consequences(self) -> list[str]:
        """Autorisierte Folgen; ausgeführt in der Kette (Sperre Schritt 6, Angebot SP5)."""
        out = []
        if self.minor_hint:
            out.append("lock_minor")
        if self.explicit_wish:
            out.append("no_order_explicit")
        elif (
            not self.minor_hint
            and self.purchase_readiness >= OFFER_READINESS
            and self.wish.description.strip()
        ):
            out.append("offer_ready")
        return out


def parse(value: object) -> tuple[Assessment | None, str]:
    """Einstufung streng typisieren; ``(None, Grund)`` bei Verstoß gegen den Schema-Vertrag."""
    if not isinstance(value, dict):
        return None, "Einstufung ist kein JSON-Objekt."
    missing = [k for k in REQUIRED if k not in value]
    if missing:
        return None, f"Einstufung unvollständig: {', '.join(missing)} fehlt."
    for key in ("minor_hint", "explicit_wish"):
        if not isinstance(value[key], bool):
            return None, f"Einstufung: {key} muss true oder false sein."
    readiness = value["purchase_readiness"]
    if isinstance(readiness, bool) or not isinstance(readiness, int) or not 0 <= readiness <= 3:
        return None, "Einstufung: purchase_readiness muss 0 bis 3 sein."
    texts = {k: value.get(k, "") for k in ("minor_evidence", "readiness_evidence", "intent")}
    bad = [k for k, v in texts.items() if not isinstance(v, str)]
    if bad:
        return None, f"Einstufung: {bad[0]} muss Text sein."
    raw_wish = value.get("wish") or {}
    if not isinstance(raw_wish, dict):
        return None, "Einstufung: wish muss ein Objekt sein."
    wish = Wish(**{k: raw_wish.get(k, "") for k in ("kind", "description", "source")})
    if any(not isinstance(v, str) for v in vars(wish).values()) or wish.kind not in WISH_KINDS:
        return None, "Einstufung: wish braucht kind (image, video oder leer), description, source."
    raw_memory = value.get("memory") or []
    if not isinstance(raw_memory, list):
        return None, "Einstufung: memory muss eine Liste sein."
    memory = []
    for item in raw_memory:
        if not isinstance(item, dict) or item.get("level") not in MEMORY_LEVELS:
            return None, f"Einstufung: memory braucht level ({', '.join(MEMORY_LEVELS)})."
        text, replaces = item.get("text"), item.get("replaces", 0) or 0
        if not isinstance(text, str) or isinstance(replaces, bool) or not isinstance(replaces, int):
            return None, "Einstufung: memory braucht text und optional replaces (Nummer)."
        if text.strip():
            memory.append(MemoryItem(item["level"], text.strip(), replaces))
    typed = Assessment(
        value["minor_hint"], value["explicit_wish"], readiness, wish=wish, memory=tuple(memory),
        **texts,
    )  # fmt: skip
    return typed, ""


def apply_minor_lock(store, customer_id: int, conversation_id: int, evidence: str) -> bool:
    """Folge eines Hinweises auf Minderjährigkeit an einer Kundenakte: Sperre setzen und Karte im
    Verlauf; True, wenn neu gesperrt. Aufheben nur durch den Betreiber (Befehl 44)."""
    row = store.db.execute("SELECT age_mark FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise ValueError(f"Akte {customer_id} unbekannt.")
    if row[0] == "under_18":
        return False
    # gilt für alle Akten mit genau dieser Plattform-Identität (SP2 Schritt 9a)
    for other in store.customers_with_identity_of(customer_id):
        store.set_age_mark(other, "under_18")
    note = f" · Beleg: {evidence.strip()}" if evidence.strip() else ""
    store.add_system_card(
        conversation_id,
        f"SPERRE · minderjährig vermutet (KI-Einstufung){note} – kein Flirt, kein Angebot; "
        "aufheben nur durch den Betreiber",
    )
    return True
