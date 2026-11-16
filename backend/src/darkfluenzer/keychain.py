"""Geheimnisse ausschließlich im macOS-Schlüsselbund – nie in Git, Konfiguration oder Logs.

Zugangsdaten trägt der Betreiber mit ``darkfluenzer secret set telegram.api_id`` bzw.
``telegram.api_hash`` ein (verdeckte Eingabe, Formatprüfung, Ersetzen nur nach Rückfrage – wie
``p0ctl provider credential set`` in Project_0); ``darkfluenzer secret status`` zeigt nur, ob ein
Eintrag vorhanden ist.
"""

from __future__ import annotations

import subprocess

ACCOUNT = "darkfluenzer"


def store_secret(service: str, value: str) -> bool:
    """Eintrag anlegen oder ersetzen (von Darkfluenzer erzeugte Werte wie der TDLib-
    Datenbankschlüssel und vom Betreiber über ``darkfluenzer secret set`` eingegebene Zugangsdaten).
    Der Wert geht über stdin an ``security -i`` und erscheint so nie in der Prozessliste."""
    if any(c in value + service for c in '"\n\\'):
        return False  # nur einfache Werte (z. B. Base64) und Dienstnamen
    line = f'add-generic-password -U -a "{ACCOUNT}" -s "{service}" -w "{value}"\n'
    try:
        result = subprocess.run(
            ["security", "-i"], input=line.encode(), capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def secret(service: str) -> str | None:
    """Wert eines Schlüsselbund-Eintrags oder None, wenn er fehlt."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None
