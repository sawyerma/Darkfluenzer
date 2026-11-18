"""Content-Cloner-Weiche (PHASENPLAN_V0 §8/§8.1, C3): Nachrichten des Default-Kontakts mit einem der
fünf Kurzbefehle werden interne Produktionsaufträge – vor jeder Kunden- und KI-Verarbeitung.

Freie Anweisungen ohne Befehl deutet später die KI-Instanz (B5); bis dahin antwortet Darkfluenzer
mit genau einer Rückfrage statt zu raten.
"""

from __future__ import annotations

COMMANDS = ("clone", "pose", "style", "remix", "animate", "edit")
ASK_COMMAND = (
    "Bitte beginne mit einem Befehl: clone, pose, style, remix, animate oder edit "
    "(dahinter optional, was du dir wünschst)."
)
ASK_OWN = (
    "edit nur für eigene Bilder: antworte mit edit auf ein Ergebnis von Darkfluenzer "
    "(z. B. „edit dress: rotes Kleid“)."
)
# Bildanweisung je Befehl für Workflows mit Vorlagen-Parameter (FLUX 3 Klein: <ref_image_0>);
# der Wunsch des Betreibers folgt dahinter (V0 §8.1, FL-6)
TEMPLATES = {
    "clone": "Recreate <ref_image_0> as faithfully as possible: same pose, framing, camera angle, "
    "lighting, outfit and setting.",
    "pose": "A new photo with exactly the same body pose and framing as <ref_image_0>.",
    "style": "A new photo with the same lighting, color grading, mood and photographic style as "
    "<ref_image_0>.",
    "remix": "A new variation inspired by <ref_image_0>: similar setting and mood, different "
    "details.",
}
ASK_REFERENCE = "Bitte schick das Referenzbild mit dem Befehl oder antworte mit dem Befehl darauf."
COMMANDS_OFF = "Befehle sind aus (Cockpit → Nachrichten → Default → Befehle verarbeiten)."
# Ausgänge eines Kloner-Auftrags (SP1 Schritt 5): jeder schreibt Karte und Chat-Antwort
STATES = {
    "started": "GESTARTET",
    "waiting_start": "WARTET AUF START",
    "rejected": "ABGELEHNT",
    "returned": "ZURÜCKGESENDET",
    "return_blocked": "RÜCKVERSAND GESPERRT",
    "failed": "FEHLGESCHLAGEN",
    "cancelled": "ABGEBROCHEN",
}


def parse(text: str) -> tuple[str, str] | None:
    """Befehl und Freitext aus einer Nachricht („clone roter Bikini, 9:16“, „/remix“)."""
    words = text.strip().split(maxsplit=1)
    if not words:
        return None
    head = words[0].lower().lstrip("/").rstrip(".,:;!")
    if head not in COMMANDS:
        return None
    return head, words[1].strip() if len(words) > 1 else ""


def card(command: str, platform: str, detail: str, state: str = "") -> str:
    """Text der Systemkarte im Default-Verlauf (FRONT F4: INTERNER AUFTRAG · BEFEHL · KANAL ·
    ZUSTAND)."""
    head = f"INTERNER AUFTRAG · {command.upper()} · {platform.upper()}"
    return f"{head} · {STATES[state]}\n{detail}" if state else f"{head}\n{detail}"


def reply(state: str, detail: str, order_no: str = "") -> str:
    """Chat-Antwort an den Default zu einem Ausgang (kurz, mit Grund bzw. Auftragsnummer)."""
    prefix = f"{order_no}: " if order_no else ""
    texts = {
        "started": f"{prefix}gestartet · {detail}",
        "waiting_start": f"Erkannt · {detail} · wartet auf Start im Cockpit.",
        "rejected": detail,
        "return_blocked": f"{prefix}Rückversand gesperrt · {detail}",
        "failed": f"{prefix}fehlgeschlagen · {detail}",
        "cancelled": f"{prefix}abgebrochen{' · ' + detail if detail else ''}",
        "returned": f"{prefix}{detail}",
    }
    return texts[state]


def prompt(command: str, wish: str, templated: bool) -> str:
    """Prompt für den Auftrag: bei Vorlagen-Workflows die Befehlsanweisung plus Wunsch."""
    base = TEMPLATES.get(command, "") if templated else ""
    return " ".join(x for x in (base, wish) if x)


def edit_parts(wish: str) -> tuple[str, str]:
    """„edit dress: rotes Kleid“ -> (Bereich, Änderung); ohne Doppelpunkt nur die Änderung."""
    region, sep, change = wish.partition(":")
    return (region.strip(), change.strip()) if sep else ("", wish.strip())
