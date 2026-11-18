"""Aufsicht für Daueraufgaben (SP2 Schritt 1, BUG-015): Kanalempfang, Postausgang, Wallet-Beobachter
und die eigenen Schleifen des Cockpits laufen nie mehr als nackte Aufgaben. Ein unerwarteter Fehler
(oder ein unerwartetes Ende) wird protokolliert, über ``report`` im STATE des Kanals bzw. der
Datenquelle angezeigt und die Aufgabe mit wachsender Pause neu gestartet."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("darkfluenzer.supervise")


async def supervise(
    name: str,
    start: Callable[[], Awaitable[None]],
    *,
    report: Callable[[str], None] | None = None,
    base_s: float,
    max_s: float,
) -> None:
    """``start`` immer wieder ausführen; Pause verdoppelt sich je Fehler bis ``max_s`` und beginnt
    nach einem Lauf, der länger als ``max_s`` hielt, wieder bei ``base_s``."""
    loop = asyncio.get_running_loop()
    failures = 0
    while True:
        started = loop.time()
        try:
            await start()
            reason = "unerwartet beendet"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 – genau dafür ist die Aufsicht da
            log.exception("Daueraufgabe %s fehlgeschlagen", name)
            reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        if loop.time() - started > max_s:
            failures = 0
        failures += 1
        wait = min(base_s * 2 ** (failures - 1), max_s)
        message = f"{name}: {reason} – Neustart in {wait:.0f} s"
        log.warning(message)
        if report is not None:
            try:
                report(message)
            except Exception:  # noqa: BLE001 – Meldeweg darf die Aufsicht nie beenden
                log.exception("Aufsicht %s: Meldung fehlgeschlagen", name)
        await asyncio.sleep(wait)
