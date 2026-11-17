"""EINE SQLite-Datenbank: Kunden, Nachrichten, Aufträge, Zahlungen, Jobs, Artefakte, Freigaben,
Lieferungen, Ereignisse. Ordner unter ``local/customers`` sind nur Ablage, nie zweite Wahrheit.

Schutz in zwei Schichten: Python-Logik prüft und protokolliert, SQLite-Constraints/Trigger
verhindern zusätzlich Doppelanlagen, nachträgliche Änderungen an Artefakten/Freigaben/Ereignissen
und Lieferungen ohne bestätigte Zahlung + passende Betreiberfreigabe.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .migrations import MIGRATIONS, REBUILDS
from .schema import (
    DB_NAME,
    SCHEMA,
    SCHEMA_VERSION,
)

log = logging.getLogger("darkfluenzer.store")


class StoreError(Exception):
    """Fachlich unzulässige Operation (Meldung für Menschen)."""


@dataclass(frozen=True)
class Customer:
    id: int
    customer_no: str
    kind: str  # customer | internal (Default-Kontakt)
    display_name: str | None
    status: str


@dataclass(frozen=True)
class Inbound:
    """Ergebnis eines gespeicherten Eingangs."""

    customer: Customer
    identity_id: int
    conversation_id: int
    message_id: int | None  # None: Ereignis war bereits bekannt (Duplikat)
    new_customer: bool


@dataclass(frozen=True)
class Order:
    id: int
    order_no: str
    customer_id: int | None  # nur Kundenaufträge
    customer_no: str | None
    kind: str
    request: str
    offer: str | None
    price_amount: int | None
    currency: str | None
    status: str
    source: str = "customer"


@dataclass(frozen=True)
class Stage:
    id: int
    order_id: int
    seq: int
    kind: str
    status: str
    workflow: str
    params: dict
    count: int
    selected_media_id: int | None
    attempts: int
    error: str | None


@dataclass(frozen=True)
class Artifact:
    id: int
    order_id: int
    role: str
    path: str
    sha256: str
    size: int
    parent_id: int | None
    job_id: int | None


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


class StoreBase:
    """Verbindung, Transaktion, Migration, Ereignisjournal und Adapterzustand."""

    def __init__(self, local: Path) -> None:
        self.local = local
        self.path = local / DB_NAME
        local.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA busy_timeout = 30000")
        self._migrate()

    def close(self) -> None:
        self.db.close()

    def backup(self, label: str) -> Path:
        """Kopie der Datenbank über die SQLite-Sicherungsschnittstelle vor einer Migration oder
        einem Ordnerumzug (SP0 Schritt 1, BUG-105); erst vollständig geschrieben, dann umbenannt."""
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        target = self.path.with_name(f"{self.path.name}.bak-{stamp}-{label}")
        n = 1
        while target.exists():
            n += 1
            target = target.with_name(f"{self.path.name}.bak-{stamp}-{n}-{label}")
        part = target.with_name(target.name + ".part")
        dest = sqlite3.connect(part)
        try:
            self.db.backup(dest)
        finally:
            dest.close()
        part.replace(target)
        return target

    def _check_integrity(self) -> None:
        """Nach einer Migration, noch in deren Transaktion: Fehler rollen alles zurück."""
        result = [r[0] for r in self.db.execute("PRAGMA integrity_check").fetchall()]
        if result != ["ok"]:
            raise StoreError(f"Integritätsprüfung fehlgeschlagen: {result[:5]}")
        if bad := self.db.execute("PRAGMA foreign_key_check").fetchall():
            raise StoreError(f"Migration verletzt Fremdschlüssel: {[tuple(r) for r in bad]}")

    def _migrate(self) -> None:
        # Einzelne Statements statt executescript(): executescript würde die laufende
        # Transaktion implizit committen; so bleibt die Migration atomar und parallel sicher.
        pending = self.db.execute("PRAGMA user_version").fetchone()[0]
        if pending == SCHEMA_VERSION:  # aktuell: keine Schreibsperre nehmen (FABLE-016)
            return
        backup = None
        if 1 <= pending < SCHEMA_VERSION:  # bestehende Datenbank: vorher sichern
            backup = self.backup(f"vor-migration{pending + 1}")
            log.info("Sicherung vor Migration %d→%d: %s", pending, SCHEMA_VERSION, backup)
        rebuild = any(step in REBUILDS for step in range(max(pending, 1) + 1, SCHEMA_VERSION + 1))
        if rebuild:  # nur außerhalb einer Transaktion umschaltbar
            self.db.execute("PRAGMA foreign_keys = OFF")
            self.db.execute("PRAGMA legacy_alter_table = ON")  # Trigger-Verweise unverändert
        try:
            with self.tx():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise StoreError(f"Unbekannte Datenbankversion {version} in {self.path}")
                if version == 0:
                    for statement in _statements(SCHEMA):
                        self.db.execute(statement)
                    version = 1
                migrated = version < SCHEMA_VERSION
                for step in range(version + 1, SCHEMA_VERSION + 1):
                    for statement in _statements(MIGRATIONS[step]):
                        self.db.execute(statement)
                if migrated:
                    self._check_integrity()
                self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except Exception as exc:
            if backup is None:
                raise
            raise StoreError(
                f"Migration auf Version {SCHEMA_VERSION} abgebrochen, Datenbank unverändert; "
                f"Sicherung: {backup}: {exc}"
            ) from exc
        finally:
            if rebuild:
                self.db.execute("PRAGMA legacy_alter_table = OFF")
                self.db.execute("PRAGMA foreign_keys = ON")

    @contextlib.contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Schreibtransaktion; BEGIN IMMEDIATE serialisiert parallele Schreiber."""
        if self.db.in_transaction:  # verschachtelt: äußere Transaktion trägt
            yield self.db
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _event(self, entity: str, entity_id: int, event: str, **data: object) -> None:
        self.db.execute(
            "INSERT INTO events (entity, entity_id, event, data, created_at) VALUES (?,?,?,?,?)",
            (entity, entity_id, event, json.dumps(data, ensure_ascii=False, default=str), now()),
        )

    def domain_version(self, domain: str) -> int:
        row = self.db.execute("SELECT version FROM domain_versions WHERE domain = ?", (domain,))
        found = row.fetchone()
        return found[0] if found else 0

    def bump(self, domain: str, fingerprint: str | None = None) -> int:
        """Domain-Version nach einer Änderung erhöhen (im Commit der Änderung). Mit
        ``fingerprint`` nur, wenn er sich vom gespeicherten unterscheidet (z. B. Registry-Hash)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT version, fingerprint FROM domain_versions WHERE domain = ?", (domain,)
            ).fetchone()
            if row and fingerprint is not None and row["fingerprint"] == fingerprint:
                return row["version"]
            version = (row["version"] if row else 0) + 1
            db.execute(
                "INSERT INTO domain_versions (domain, version, fingerprint) VALUES (?,?,?)"
                " ON CONFLICT(domain) DO UPDATE SET version = excluded.version,"
                " fingerprint = coalesce(?, domain_versions.fingerprint)",
                (domain, version, fingerprint or "", fingerprint),
            )
            return version

    def events(self, entity: str, entity_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT event, data, created_at FROM events WHERE entity = ? AND entity_id = ? "
            "ORDER BY id",
            (entity, entity_id),
        )
        return [dict(r) | {"data": json.loads(r["data"])} for r in rows]

    def journal_head(self) -> int:
        """Höchster Journal-Cursor (0 = leeres Journal)."""
        return self.db.execute("SELECT coalesce(max(id), 0) FROM events").fetchone()[0]

    def adapter_get(self, platform: str, account: str, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM adapter_state WHERE platform = ? AND account = ? AND key = ?",
            (platform, account, key),
        ).fetchone()
        return row[0] if row else None

    def adapter_set(self, platform: str, account: str, key: str, value: str) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO adapter_state (platform, account, key, value) VALUES (?,?,?,?)"
                " ON CONFLICT (platform, account, key) DO UPDATE SET value = excluded.value",
                (platform, account, key, value),
            )

    def adapter_prefixed(self, platform: str, account: str, prefix: str) -> dict[str, str]:
        """Alle Adapterwerte eines Kontos mit Schlüsselpräfix (z. B. letzte Nachricht je Chat)."""
        rows = self.db.execute(
            "SELECT key, value FROM adapter_state WHERE platform = ? AND account = ?"
            " AND substr(key, 1, length(?)) = ?",
            (platform, account, prefix, prefix),
        )
        return {r[0][len(prefix) :]: r[1] for r in rows}


def _uncovered(inflow: dict, price_cents: int, offer: dict | None) -> str:
    """Leer, wenn der Eingang den Angebotspreis deckt (bugs_v1 BUG-005), sonst der Grund: gleicher
    Zahlungsweg wie im Angebot -> mindestens dessen exakter Betrag; sonst Euro-Wert beim Eingang
    (Gutschein: eingelöster Betrag)."""
    from decimal import Decimal, InvalidOperation

    wanted = (offer or {}).get("amounts", {}).get(inflow["method"])
    try:
        if wanted is not None:
            if Decimal(inflow["amount"]) >= Decimal(wanted):
                return ""
            return f"{inflow['amount']} {inflow['asset']} < {wanted} {inflow['asset']}"
        if inflow["method"] == "amazon":
            eur = Decimal(inflow["amount"])
        elif inflow["eur"] is None:
            return "Euro-Wert des Eingangs fehlt"
        else:
            eur = Decimal(str(inflow["eur"]))
    except InvalidOperation:
        return f"Betrag {inflow['amount']!r} nicht lesbar"
    if eur * 100 >= price_cents:
        return ""
    return f"{eur:.2f} € < {price_cents / 100:.2f} €"


def _statements(script: str) -> Iterator[str]:
    """Zerlegt SQL in vollständige Statements (Trigger-Körper mit ';' bleiben zusammen)."""
    buf = ""
    for part in script.split(";"):
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \n\t;"):
                yield buf.strip()
            buf = ""


def _customer(row: sqlite3.Row) -> Customer:
    return Customer(
        id=row["id"],
        customer_no=row["customer_no"],
        kind=row["kind"],
        display_name=row["display_name"],
        status=row["status"],
    )


def _order(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        order_no=row["order_no"],
        customer_id=row["customer_id"],
        customer_no=row["customer_no"],
        kind=row["kind"],
        request=row["request"],
        offer=row["offer"],
        price_amount=row["price_amount"],
        currency=row["currency"],
        status=row["status"],
        source=row["source"],
    )


def _stage(row: sqlite3.Row) -> Stage:
    return Stage(
        id=row["id"],
        order_id=row["order_id"],
        seq=row["seq"],
        kind=row["kind"],
        status=row["status"],
        workflow=row["workflow"],
        params=json.loads(row["params"]),
        count=row["count"],
        selected_media_id=row["selected_media_id"],
        attempts=row["attempts"],
        error=row["error"],
    )
