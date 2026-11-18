"""Content-Cloner-Weiche (PHASENPLAN_V0 §8/§8.1, C3): Nachrichten des Default-Kontakts mit einem der
fünf Kurzbefehle werden interne Produktionsaufträge – vor jeder Kunden- und KI-Verarbeitung.

Freie Anweisungen ohne Befehl deutet später die KI-Instanz (B5); bis dahin antwortet Darkfluenzer
mit genau einer Rückfrage statt zu raten.
"""

from __future__ import annotations

import re

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
TEST_MODE = "Kundentest noch nicht verfügbar (Betriebsart Test)."
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


# Optionen im Wunsch (SP1 Schritt 6): Formatname der Engine und Dauer („8s“, „5 sek“)
_FORMAT = re.compile(r"(?<![\w:])(\d{1,2}:\d{1,2})(?![\w:])")
_DURATION = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,]\d)?)\s*(?:s|sek|sekunden|sec|seconds)(?!\w)", re.IGNORECASE
)


def options(wish: str) -> tuple[str, float | None, str]:
    """Format (z. B. ``9:16``) und Dauer (Sekunden) aus dem Wunsch lösen; der Rest bleibt Wunsch.
    Ob das Format zur Engine passt, prüft der Aufrufer."""
    fmt, duration, rest = "", None, wish
    if m := _FORMAT.search(rest):
        fmt, rest = m.group(1), rest[: m.start()] + " " + rest[m.end() :]
    if m := _DURATION.search(rest):
        duration = float(m.group(1).replace(",", "."))
        rest = rest[: m.start()] + " " + rest[m.end() :]
    rest = re.sub(r"\s+([,;.])", r"\1", " ".join(rest.split()))
    rest = re.sub(r"([,;])\s*(?=[,;]|$)", "", rest).strip(" ,;")
    return fmt, duration, rest


def finish_height(choices: tuple[str, ...], size: tuple[int, int]) -> int | None:
    """Höhe der Instagram-Ausgabe (1080 breit) zum Format: die nächste erlaubte Wahl (BUG-090)."""
    if not choices:
        return None
    want = 1080 * size[1] / size[0]
    return int(min(choices, key=lambda c: abs(int(c) - want)))
