"""Kanalvertrag (SP0 Schritt 4): eine Schnittstelle für alle Kanäle.

Zustand, Eingang (``run``), Versand (``outbox_worker``), Versandprüfung (``send_check``),
Antwortfenster, Gelesen, Tippen und die Fähigkeiten des Kanals. Telegram und Instagram erfüllen ihn;
Dialog, Verhalten und Zustellung fragen nur diesen Vertrag, nie eine Plattform direkt. Ein Kanal
ohne Antwortfenster meldet es als offen.

Gelesen und Tippen setzen die Kanäle in SP4 um (BUG-096); bis dahin melden sie „nicht unterstützt“.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capabilities:
    """Was ein Kanal kann; Größen aus der Konfiguration, ``None`` = vom Kanal nicht begrenzt."""

    document: bool  # Datei als Dokument (Originaldatei)
    self_destruct: bool  # selbstlöschende Nachrichten
    reply_window: bool  # Plattform-Antwortfenster (Instagram 24 h)
    read_receipts: bool  # Gelesen-Markierung durch uns
    typing: bool  # Tippanzeige
    max_text_bytes: int | None = None
    max_attachment_mb: dict[str, float] = field(default_factory=dict)  # je Art (image, video, …)


class Channel(ABC):
    """Ein angemeldetes Kanalkonto (Adapter)."""

    platform: str
    state: str  # OFF · WAIT_* · READY · ERROR
    account: str  # unveränderliche Plattform-ID des Kontos nach der Anmeldung
    wake: asyncio.Event  # Postausgang hat Arbeit
    on_change_message: Callable[[int], None] | None
    gate: Callable[[dict], Awaitable[str]] | None  # Liefer-Gate vor dem Versand einer Zustellkopie
    # letzter Fehler einer Daueraufgabe des Kontos, von der Aufsicht gemeldet (SP2 Schritt 1)
    task_error: str = ""

    @property
    @abstractmethod
    def automation(self) -> bool:
        """Automatische Antworten für dieses Konto erlaubt."""

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Fähigkeiten des Kanals."""

    @abstractmethod
    def status(self) -> dict:
        """Zustand für den STATE ``channels``."""

    @abstractmethod
    async def run(self) -> None:
        """Eingang: Verbindung halten und eingehende Nachrichten melden."""

    @abstractmethod
    async def outbox_worker(self) -> None:
        """Versand: Postausgang abarbeiten, wenn Arbeit da ist und das Konto bereit ist."""

    @abstractmethod
    async def logout(self) -> str:
        """Abmelden."""

    @abstractmethod
    def set_automation(self, enabled: bool) -> str:
        """Automatik ein- oder ausschalten."""

    def send_check(self, conversation: str, *, human_agent: bool = False) -> str:
        """Leer, wenn an diese Konversation gesendet werden darf, sonst der Grund."""
        return "Human-Agent gibt es nur bei Instagram." if human_agent else ""

    def window_remaining_ms(self, conversation: str, *, human_agent: bool = False) -> int:
        """Restzeit des Antwortfensters; nur sinnvoll, wenn ``capabilities().reply_window``."""
        return 0

    def window_open(self, conversation: str) -> bool:
        """Ohne Antwortfenster ist immer offen."""
        return True

    def last_read_ms(self, conversation: str) -> int:
        """Letzte Lesebestätigung des Kunden (Unix-ms), 0 = keine bekannt."""
        return 0

    def mark_human_agent(self, message_id: int) -> None:
        """Manuelle Antwort als Human-Agent kennzeichnen; nur Kanäle mit Antwortfenster."""
        return None

    async def mark_read(self, conversation: str, message_ids: list[str]) -> bool:
        """Nachrichten als gelesen markieren; False = vom Kanal (noch) nicht unterstützt."""
        return False

    async def set_typing(self, conversation: str, typing: bool) -> bool:
        """Tippanzeige setzen; False = vom Kanal (noch) nicht unterstützt."""
        return False

    async def set_online(self, online: bool) -> bool:
        """Online-Status des Kontos (SP4 Schritt 7: ein beim Lesen und Tippen, sonst aus);
        False = vom Kanal nicht unterstützt."""
        return False
