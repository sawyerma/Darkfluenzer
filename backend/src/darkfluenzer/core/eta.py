"""Lieferzeit (SP5 Schritt 2): wie lange ein jetzt bezahlter Auftrag bis zur Lieferung braucht.

Grundlage sind nur Messwerte aus SQLite: Laufdauer je Workflow (Median der letzten Läufe) und
Sekunden je Schritt der Trainings. Vor dem neuen Auftrag liegen der laufende Job (Rest), wartende
bezahlte Kundenaufträge (Vorrang „customer“) und ein laufendes Training mit seiner Restdauer (bis
E25 das Pausieren am Checkpoint übernimmt). Fehlt eine Messung, ist die Lieferzeit unbekannt und es
entsteht kein Angebot – keine geschätzten Annahmen.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Pending:
    workflow: str
    status: str  # queued | running
    priority: str
    elapsed_s: float = 0.0
    steps: int = 0
    training: bool = False


def delivery_s(
    product: dict,
    pending: list[Pending],
    run_s: Callable[[str], float],
    step_s: Callable[[str], float],
) -> tuple[float | None, str]:
    """Sekunden bis zur Lieferung; ``(None, Grund)`` ohne Messung."""
    own = [(product["workflow"], max(1, int(product.get("candidates") or 1)))]
    if product["kind"] == "video":
        own.append((product["finish_workflow"], 1))  # Animation des gewählten Kandidaten
    total = 0.0
    for key, count in own:
        seconds = run_s(key)
        if not seconds:
            return None, f"keine Laufzeitmessung für {key}"
        total += count * seconds
    for job in pending:
        if job.status == "queued" and job.priority != "customer":
            continue  # bezahlte Kundenaufträge laufen vor allen anderen Klassen
        if job.training:
            per_step = step_s(job.workflow)
            if not per_step or not job.steps:
                return None, f"Restdauer des Trainings {job.workflow} unbekannt"
            estimate = per_step * job.steps
        else:
            estimate = run_s(job.workflow)
            if not estimate:
                return None, f"keine Laufzeitmessung für {job.workflow} (Warteschlange)"
        total += max(0.0, estimate - job.elapsed_s) if job.status == "running" else estimate
    return total, ""


def minutes(seconds: float) -> int:
    """Lieferzeit für Kunden: auf volle 5 Minuten aufgerundet, mindestens 5."""
    return max(5, math.ceil(seconds / 300) * 5)
