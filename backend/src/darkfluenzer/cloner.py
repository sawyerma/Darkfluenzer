"""Content-Cloner-Weiche (PHASENPLAN_V0 §8/§8.1, C3): Nachrichten des Default-Kontakts mit einem der
fünf Kurzbefehle werden interne Produktionsaufträge – vor jeder Kunden- und KI-Verarbeitung.

Freie Anweisungen ohne Befehl deutet später die KI-Instanz (B5); bis dahin antwortet Darkfluenzer
mit genau einer Rückfrage statt zu raten.
"""

from __future__ import annotations

COMMANDS = ("clone", "pose", "style", "remix", "animate")
ASK_COMMAND = (
    "Bitte beginne mit einem Befehl: clone, pose, style, remix oder animate "
    "(dahinter optional, was du dir wünschst)."
)
ASK_REFERENCE = "Bitte schick das Referenzbild mit dem Befehl oder antworte mit dem Befehl darauf."


def parse(text: str) -> tuple[str, str] | None:
    """Befehl und Freitext aus einer Nachricht („clone roter Bikini, 9:16“, „/remix“)."""
    words = text.strip().split(maxsplit=1)
    if not words:
        return None
    head = words[0].lower().lstrip("/").rstrip(".,:;!")
    if head not in COMMANDS:
        return None
    return head, words[1].strip() if len(words) > 1 else ""


def card(command: str, platform: str, detail: str) -> str:
    """Text der Systemkarte im Default-Verlauf (FRONT F4: INTERNER AUFTRAG · BEFEHL · KANAL)."""
    return f"INTERNER AUFTRAG · {command.upper()} · {platform.upper()}\n{detail}"
