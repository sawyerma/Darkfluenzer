"""Promptprofile je Influencerin (SP4 Schritt 2, E19): speichern und versionieren, keine
Zusammenstellung. Das Backend reicht die Blöcke der aktiven Version unverändert an die gleichnamigen
Eingänge des registrierten Sprachworkflows; das Gesprächsverhalten steht allein in den Prompts.

Fest und nicht bearbeitbar sind der Ehrlichkeitsblock (Regel 12 c) und der KI-Hinweis (E20): beide
liegen als feste Textknoten im Sprachworkflow.
"""

from __future__ import annotations

from ..media.models import Manifest

# Bearbeitbare Blöcke in Anzeigereihenfolge (Schlüssel = Eingang des Sprachworkflows)
PROFILE_BLOCKS: tuple[tuple[str, str], ...] = (
    ("system_prompt", "Systemprompt"),
    ("persona", "Persona (Charakterprofil)"),
    ("positive_rules", "Positive Anweisungen"),
    ("negative_rules", "Negative Anweisungen"),
    ("strategy", "Gesprächs- und Verkaufsstrategie"),
    ("examples", "Beispieldialoge · Schreibstil"),
    ("classification", "Einstufung und Schema (neutraler Lauf, E26)"),
    ("wish_summary", "Wunsch-Zusammenfassung"),
    ("offer", "Angebot"),
    ("delivery", "Zustellung"),
    ("consolation", "Vertrösten"),
    ("fansly", "Fansly-Verweis"),
)
BLOCK_KEYS = frozenset(key for key, _ in PROFILE_BLOCKS)


def model_params(man: Manifest) -> dict:
    """Zahlenparameter der registrierten Sprachworkflows (Engine-Art ``text``) mit ihren Grenzen;
    ohne registrierten Sprachworkflow leer – dann gibt es keine Modellparameter im Profil."""
    out = {}
    for wf in man.workflows.values():
        eng = man.engines.get(wf.engine)
        if eng is None or eng.kind != "text":
            continue
        for name, param in wf.params.items():
            if param.type in ("int", "float") and not param.upload:
                out[name] = param
    return out


def check_draft(man: Manifest, blocks: dict[str, str], params: dict[str, float]) -> str:
    """Ablehnungsgrund eines Profilentwurfs oder leer: nur bekannte Blöcke; Modellparameter nur,
    wenn ein registrierter Sprachworkflow sie deklariert, und nur in dessen Grenzen."""
    unknown = sorted(set(blocks) - BLOCK_KEYS)
    if unknown:
        return f"Unbekannter Profilblock: {', '.join(unknown)}."
    if not params:
        return ""
    allowed = model_params(man)
    if not allowed:
        return "Modellparameter erst mit registriertem Sprachworkflow (SP4 Schritt 1)."
    for name, value in params.items():
        param = allowed.get(name)
        if param is None:
            return f"Modellparameter {name} gibt es im Sprachworkflow nicht."
        low = param.min if param.min is not None else float("-inf")
        high = param.max if param.max is not None else float("inf")
        if not low <= value <= high:
            return f"{name}: {value:g} liegt außerhalb {low:g} … {high:g}."
    return ""
