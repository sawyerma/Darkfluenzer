"""Freie Default-Anweisungen (SP4 Schritt 4, bisher B5.4a): der registrierte Workflow
``default_instruction_melody`` deutet eine Nachricht ohne Kurzbefehl und liefert nach dem Schema
in seiner Anweisung ein JSON-Objekt. Das Backend typisiert es streng und führt nur Erlaubtes aus:
Befehl aus der Liste, Workflow aus der Registry (gleiche Prüfung wie beim Befehl), Format/Dauer wie
im Wunsch, Bezug nur auf Medien dieses Chats. Keine Textdeutung in Python (E19)."""

from __future__ import annotations

from dataclasses import dataclass

from . import cloner_text


@dataclass(frozen=True)
class Instruction:
    command: str  # einer der Kurzbefehle oder "none"
    workflow: str = ""
    prompt: str = ""
    format: str = ""
    duration_s: float = 0.0
    reference: str = ""  # "letztes" | "media:<ID>" | "" (wie beim Befehl)
    question: str = ""


def parse(value: object) -> tuple[Instruction | None, str]:
    """Ergebnis streng typisieren; ``(None, Grund)`` bei Verstoß gegen das Schema."""
    if not isinstance(value, dict):
        return None, "Deutung ist kein JSON-Objekt."
    command = value.get("command")
    if command not in (*cloner_text.COMMANDS, "none"):
        return None, f"Deutung: Befehl {command!r} unbekannt."
    texts = {k: value.get(k, "") or "" for k in ("workflow", "prompt", "reference", "question")}
    if any(not isinstance(v, str) for v in texts.values()):
        return None, "Deutung: workflow, prompt, reference und question müssen Text sein."
    options = value.get("options") or {}
    if not isinstance(options, dict):
        return None, "Deutung: options muss ein Objekt sein."
    fmt = options.get("format", "") or ""
    duration = options.get("duration_s", 0) or 0
    if (
        not isinstance(fmt, str)
        or isinstance(duration, bool)
        or not isinstance(duration, int | float)
    ):
        return None, "Deutung: options braucht format (Text) und duration_s (Zahl)."
    reference = texts["reference"].strip().lower()
    if reference == "none":
        reference = ""
    if (
        reference
        and reference != "letztes"
        and not (reference.startswith("media:") and reference[6:].isdigit())
    ):
        return None, "Deutung: reference nur letztes, media:<ID> oder none."
    return Instruction(
        command, texts["workflow"].strip(), texts["prompt"].strip(), fmt.strip(),
        float(duration), reference, texts["question"].strip(),
    ), ""  # fmt: skip


def wish(ins: Instruction) -> str:
    """Wunschtext wie bei einem Kurzbefehl: Bildwunsch, Format, Dauer (Optionen, SP1 Schritt 6)."""
    parts = [ins.prompt, ins.format]
    if ins.duration_s:
        parts.append(f"{ins.duration_s:g}s")
    return " ".join(p for p in parts if p)
