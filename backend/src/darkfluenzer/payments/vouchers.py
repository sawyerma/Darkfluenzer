"""Amazon-Gutscheincodes im Chat erkennen (PHASENPLAN_V0 §8.5 Punkt 5).

Ein Code wird vor dem Speichern aus dem Nachrichtentext entfernt (damit steht er nie im Verlauf
und nie im KI-Kontext) und nur im Reiter Wallet unter „Gutscheine zu prüfen“ gezeigt. Erkannt werden
Codes im Aufbau der Amazon-Geschenkkarten (4-6-4 bzw. 4-6-5 Zeichen, mit oder ohne Trennzeichen),
die Buchstaben und Ziffern enthalten; ein Fehltreffer wird im Wallet abgelehnt.
"""

from __future__ import annotations

import re

CODE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9]{4})[- ]?([A-Za-z0-9]{6})[- ]?([A-Za-z0-9]{4,5})(?![A-Za-z0-9])"
)
MASK = "[Gutscheincode – im Reiter Wallet]"


def extract(text: str) -> tuple[str, list[str]]:
    """Text ohne Codes und die gefundenen Codes (normiert: Großbuchstaben, mit Bindestrichen)."""
    codes: list[str] = []

    def replace(match: re.Match) -> str:
        parts = [p.upper() for p in match.groups()]
        joined = "".join(parts)
        if not (any(c.isdigit() for c in joined) and any(c.isalpha() for c in joined)):
            return match.group(0)
        codes.append("-".join(parts))
        return MASK

    return CODE.sub(replace, text), codes
