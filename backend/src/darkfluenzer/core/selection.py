"""Automatische Auswahl (SP5 Schritt 7, E16/E17): Entscheidung aus den Messwerten der Prüfkette.

Keine Bildprüfung in Python: die Prüfknoten im Workflow liefern Werte (``media_checks``), hier
wird nur gegen die Schwellen aus der Konfiguration verglichen. Vier Prüfungen müssen bestehen
(Identität, Inhalt, Technik, Qualität); ein fehlender Wert oder ein Status außer ``ok`` gilt als
nicht bestanden, bei Video muss jedes geprüfte Frame bestehen. Eine Regel ohne Quelle der
Kalibrierung ist nicht qualifiziert – dann wählt der Betreiber (keine erfundenen Grenzwerte).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import SELECTION_RULES, SelectionConfig, SelectionRule

LABELS = {"identity": "Identität", "content": "Inhalt", "technical": "Technik",
          "quality": "Qualität"}  # fmt: skip


@dataclass(frozen=True)
class Verdict:
    media_id: int
    passed: bool
    score: float
    reasons: tuple[str, ...]
    values: dict  # Regel -> schlechtester Wert


def unqualified(cfg: SelectionConfig) -> list[str]:
    """Regeln, die fehlen oder keine Kalibrierungsquelle nennen."""
    return [n for n in SELECTION_RULES if n not in cfg.rules or not cfg.rules[n].source]


def _check(name: str, rule: SelectionRule, rows: list[dict]) -> tuple[bool, object, str]:
    label = LABELS[name]
    hits = [r for r in rows if r["check_name"] == rule.check]
    if not hits:
        return False, None, f"{label}: Wert fehlt"
    values = []
    for r in hits:
        if r["status"] != "ok":
            return False, None, f"{label}: {r['status']}"
        v = (r.get("data") or {}).get(rule.value)
        if v is None:
            return False, None, f"{label}: Wert {rule.value} fehlt"
        values.append(v)
    if rule.allowed:
        bad = [v for v in values if str(v) not in rule.allowed]
        if bad:
            return False, bad[0], f"{label}: {bad[0]} nicht erlaubt"
        return True, values[0], ""
    try:
        numbers = [float(v) for v in values]
    except (TypeError, ValueError):
        return False, values[0], f"{label}: {rule.value} ist keine Zahl"
    if rule.min is not None and min(numbers) < rule.min:
        return False, min(numbers), f"{label}: {min(numbers):g} < {rule.min:g}"
    if rule.max is not None and max(numbers) > rule.max:
        return False, max(numbers), f"{label}: {max(numbers):g} > {rule.max:g}"
    return True, (min(numbers) if rule.min is not None else max(numbers)), ""


def judge(cfg: SelectionConfig, media_id: int, rows: list[dict]) -> Verdict:
    """Ein Kandidat gegen alle vier Regeln; Gesamtwert aus Identität und Qualität."""
    reasons, values = [], {}
    for name in SELECTION_RULES:
        ok, value, why = _check(name, cfg.rules[name], rows)
        values[name] = value
        if not ok:
            reasons.append(why)
    score = 0.0
    if not reasons:
        score = cfg.weight_identity * float(values["identity"]) + cfg.weight_quality * float(
            values["quality"]
        )
    return Verdict(media_id, not reasons, score, tuple(reasons), values)


def choose(
    cfg: SelectionConfig, candidates: list[tuple[int, list[dict]]]
) -> tuple[Verdict | None, list[Verdict]]:
    """Bester bestandener Kandidat (höchster Gesamtwert) und alle Urteile."""
    verdicts = [judge(cfg, media_id, rows) for media_id, rows in candidates]
    passed = [v for v in verdicts if v.passed]
    return (max(passed, key=lambda v: v.score) if passed else None), verdicts
