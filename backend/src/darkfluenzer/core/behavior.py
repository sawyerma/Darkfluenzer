"""Verhalten (SP4 Schritt 7, E3, E4): reale Sendezeiten aus dem Verhaltensprofil der Influencerin.

Das Profil enthält nur Zahlen für die Ausführung (versioniert in SQLite); Stil, Länge und Ton der
Antworten stehen im Promptprofil (E19). Das Backend plant daraus Lesezeit, Bedenkzeit und Tippzeit:

- im Gesprächsfluss schnell (``read_*``, ``think_*``);
- bei Erstkontakt, nach einer Pause (``pause_after_s``) und zufällig (``slow_chance``) langsam
  (``slow_*``, E3: 30 s bis 30 min);
- nachts (``night_start_h``–``night_end_h``) langsam (``night_*``, E3: 30–60 min), außer die letzte
  Einstufung zeigt Kaufbereitschaft ab ``readiness_fast`` (E4);
- Tippzeit = Länge / ``typing_cps``; gebündelt wird nach der letzten Kundennachricht ``bundle_s``.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Behavior:
    bundle_s: float = 20.0
    read_min_s: float = 3.0
    read_max_s: float = 20.0
    think_min_s: float = 2.0
    think_max_s: float = 15.0
    typing_cps: float = 6.0
    slow_min_s: float = 30.0
    slow_max_s: float = 1800.0
    pause_after_s: float = 3600.0
    slow_chance: float = 0.15
    night_start_h: float = 0.0
    night_end_h: float = 7.0
    night_min_s: float = 1800.0
    night_max_s: float = 3600.0
    readiness_fast: float = 2.0
    max_wait_s: float = 180.0
    consolations_per_day: float = 2.0
    consolation_stock: float = 3.0

    def values(self) -> dict[str, float]:
        return asdict(self)


NAMES = tuple(f.name for f in fields(Behavior))
_PAIRS = (("read_min_s", "read_max_s"), ("think_min_s", "think_max_s"),
          ("slow_min_s", "slow_max_s"), ("night_min_s", "night_max_s"))  # fmt: skip


def build(base: Behavior, data: dict) -> Behavior | str:
    """Profilwerte prüfen und auf ``base`` setzen; Grund bei Verstoß."""
    unknown = sorted(set(data) - set(NAMES))
    if unknown:
        return f"Verhalten: unbekannte Werte {unknown}."
    try:
        b = replace(base, **{k: float(v) for k, v in data.items()})
    except (TypeError, ValueError):
        return "Verhalten: nur Zahlen."
    if any(v < 0 for v in b.values().values()):
        return "Verhalten: keine negativen Werte."
    for low, high in _PAIRS:
        if getattr(b, low) > getattr(b, high):
            return f"Verhalten: {low} > {high}."
    if not 0 <= b.slow_chance <= 1:
        return "Verhalten: slow_chance zwischen 0 und 1."
    if b.typing_cps <= 0:
        return "Verhalten: typing_cps > 0."
    if not (0 <= b.night_start_h < 24 and 0 <= b.night_end_h <= 24):
        return "Verhalten: Nachtstunden 0 bis 24."
    return b


@dataclass(frozen=True)
class Plan:
    kind: str  # fast | slow | night
    read_at: datetime
    think_until: datetime


def is_night(b: Behavior, when: datetime) -> bool:
    hour = when.hour + when.minute / 60
    if b.night_start_h <= b.night_end_h:
        return b.night_start_h <= hour < b.night_end_h
    return hour >= b.night_start_h or hour < b.night_end_h  # über Mitternacht


def plan(
    b: Behavior,
    last_in: datetime,
    *,
    previous_out: datetime | None,
    first_contact: bool,
    readiness: int,
    rng: random.Random | None = None,
) -> Plan:
    """Lese- und Bedenkzeit ab der letzten Kundennachricht (``last_in``, Ortszeit für die Nacht).
    ``previous_out``: letzte eigene Nachricht (Pause = lange keine)."""
    rng = rng or random.Random()
    pause = previous_out is None or (last_in - previous_out).total_seconds() >= b.pause_after_s
    if is_night(b, last_in) and readiness < b.readiness_fast:
        kind, wait = "night", rng.uniform(b.night_min_s, b.night_max_s)
    elif first_contact or pause or rng.random() < b.slow_chance:
        kind, wait = "slow", rng.uniform(b.slow_min_s, b.slow_max_s)
    else:
        kind, wait = "fast", rng.uniform(b.read_min_s, b.read_max_s)
    read_at = last_in + timedelta(seconds=wait)
    think = rng.uniform(b.think_min_s, b.think_max_s)
    return Plan(kind, read_at, read_at + timedelta(seconds=think))


def send_at(b: Behavior, p: Plan, text: str, now: datetime) -> datetime:
    """Sendezeit: nach Lesen, Bedenken und Tippen – nie vor jetzt."""
    typed = p.think_until + timedelta(seconds=len(text) / b.typing_cps)
    return max(typed, now)
