"""EINE SQLite-Datenbank: Kunden, Nachrichten, Aufträge, Zahlungen, Jobs, Artefakte, Freigaben,
Lieferungen, Ereignisse. Ordner unter ``local/customers`` sind nur Ablage, nie zweite Wahrheit.

Schutz in zwei Schichten: Python-Logik prüft und protokolliert, SQLite-Constraints/Trigger
verhindern zusätzlich Doppelanlagen, nachträgliche Änderungen an Artefakten/Freigaben/Ereignissen
und Lieferungen ohne bestätigte Zahlung + passende Betreiberfreigabe.
"""

from __future__ import annotations

from .commands import CommandsMixin
from .customers import CustomersMixin
from .db import (
    Artifact,
    Customer,
    Inbound,
    Order,
    Stage,
    StoreBase,
    StoreError,
    _statements,
    now,
    sha256_file,
)
from .jobs import JobsMixin
from .media import MediaMixin
from .messages import MessagesMixin
from .migrations import MIGRATIONS, REBUILDS
from .orders import OrdersMixin
from .payments import PaymentsMixin
from .profiles import ProfilesMixin
from .schema import DB_NAME, GALLERY_ROLES, MEDIA_KINDS, SCHEMA, SCHEMA_VERSION


class Store(
    CustomersMixin,
    MessagesMixin,
    ProfilesMixin,
    OrdersMixin,
    PaymentsMixin,
    MediaMixin,
    JobsMixin,
    CommandsMixin,
    StoreBase,
):
    """Die eine fachliche Datenbank; Methoden nach Themen in den Modulen dieses Pakets."""


__all__ = [
    "DB_NAME",
    "GALLERY_ROLES",
    "MEDIA_KINDS",
    "MIGRATIONS",
    "REBUILDS",
    "SCHEMA",
    "SCHEMA_VERSION",
    "Artifact",
    "Customer",
    "Inbound",
    "Order",
    "Stage",
    "Store",
    "StoreError",
    "_statements",
    "now",
    "sha256_file",
]
