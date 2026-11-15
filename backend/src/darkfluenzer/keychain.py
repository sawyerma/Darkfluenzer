"""Geheimnisse ausschließlich im macOS-Schlüsselbund – nie in Git, Konfiguration oder Logs.

Ablegen (der Wert wird nicht angezeigt):
``security add-generic-password -U -a darkfluenzer -s <dienst> -w``
"""

from __future__ import annotations

import subprocess

ACCOUNT = "darkfluenzer"


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
