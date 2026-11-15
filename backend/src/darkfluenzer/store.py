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
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 4
DB_NAME = "darkfluenzer.sqlite3"

ORDER_KINDS = ("image", "video")
ARTIFACT_ROLES = ("input", "master", "mask", "candidate", "preview", "edit", "refined", "sent")
# Erlaubte Auftragsübergänge (alles andere wird abgewiesen)
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"offered", "cancelled"},
    "offered": {"accepted", "cancelled"},
    "accepted": {"paid", "cancelled"},
    "paid": {"producing", "refunded"},
    "producing": {"review", "refunded"},
    "review": {"producing", "approved", "refunded"},
    "approved": {"delivered", "producing", "refunded"},
    "delivered": set(),
    "cancelled": set(),
    "refunded": set(),
}

_IMMUTABLE = ("artifacts", "approvals", "events")

SCHEMA = f"""
CREATE TABLE customers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_no      TEXT GENERATED ALWAYS AS ('DF-C-' || printf('%06d', id)) STORED,
    bot_id           TEXT    NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'blocked')),
    created_at       TEXT    NOT NULL,
    UNIQUE (bot_id, telegram_user_id)
);
CREATE UNIQUE INDEX customers_no ON customers(customer_no);

CREATE TABLE messages (
    id                  INTEGER PRIMARY KEY,
    customer_id         INTEGER NOT NULL REFERENCES customers(id),
    direction           TEXT    NOT NULL CHECK (direction IN ('in', 'out')),
    chat_id             INTEGER NOT NULL,
    telegram_message_id INTEGER,
    text                TEXT    NOT NULL,
    sent_at             TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    UNIQUE (chat_id, direction, telegram_message_id)
);
CREATE INDEX messages_customer ON messages(customer_id, id);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no     TEXT GENERATED ALWAYS AS ('DF-O-' || printf('%06d', id)) STORED,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    kind         TEXT    NOT NULL CHECK (kind IN {ORDER_KINDS}),
    request      TEXT    NOT NULL,
    offer        TEXT,
    price_amount INTEGER CHECK (price_amount IS NULL OR price_amount > 0),
    currency     TEXT,
    status       TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN {tuple(TRANSITIONS)}),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
CREATE UNIQUE INDEX orders_no ON orders(order_no);
CREATE INDEX orders_customer ON orders(customer_id);

CREATE TABLE payments (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    provider       TEXT    NOT NULL,
    provider_tx_id TEXT    NOT NULL,
    amount         INTEGER NOT NULL CHECK (amount > 0),
    currency       TEXT    NOT NULL,
    status         TEXT    NOT NULL CHECK (status IN ('confirmed', 'refunded')),
    confirmed_at   TEXT    NOT NULL,
    refunded_at    TEXT,
    UNIQUE (provider, provider_tx_id)
);
CREATE INDEX payments_order ON payments(order_id);

-- order_id NULL: Renderung ohne Kundenbezug (Evaluation durch den Betreiber)
CREATE TABLE jobs (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER REFERENCES orders(id),
    engine     TEXT    NOT NULL,
    workflow   TEXT    NOT NULL,
    prompt     TEXT    NOT NULL,
    params     TEXT    NOT NULL DEFAULT '{{}}',
    seeds      TEXT    NOT NULL DEFAULT '[]',
    status     TEXT    NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued', 'running', 'done', 'failed')),
    error      TEXT,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

CREATE TABLE artifacts (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    job_id     INTEGER REFERENCES jobs(id),
    parent_id  INTEGER REFERENCES artifacts(id),
    role       TEXT    NOT NULL CHECK (role IN {ARTIFACT_ROLES}),
    path       TEXT    NOT NULL UNIQUE,
    sha256     TEXT    NOT NULL CHECK (length(sha256) = 64),
    size       INTEGER NOT NULL CHECK (size > 0),
    provenance TEXT    NOT NULL DEFAULT '{{}}',
    created_at TEXT    NOT NULL
);

CREATE TABLE approvals (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    artifact_id     INTEGER NOT NULL REFERENCES artifacts(id),
    artifact_sha256 TEXT    NOT NULL,
    decision        TEXT    NOT NULL CHECK (decision IN ('approved', 'rejected', 'regenerate')),
    operator        TEXT    NOT NULL,
    decided_at      TEXT    NOT NULL
);
CREATE INDEX approvals_order ON approvals(order_id, id);

CREATE TABLE deliveries (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    artifact_id     INTEGER NOT NULL REFERENCES artifacts(id),
    artifact_sha256 TEXT    NOT NULL,
    idempotency_key TEXT    NOT NULL UNIQUE,
    status          TEXT    NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    external_id     TEXT,
    created_at      TEXT    NOT NULL,
    sent_at         TEXT
);
CREATE UNIQUE INDEX deliveries_one_per_order ON deliveries(order_id) WHERE status != 'failed';

CREATE TABLE events (
    id         INTEGER PRIMARY KEY,
    entity     TEXT    NOT NULL,
    entity_id  INTEGER NOT NULL,
    event      TEXT    NOT NULL,
    data       TEXT    NOT NULL DEFAULT '{{}}',
    created_at TEXT    NOT NULL
);
CREATE INDEX events_entity ON events(entity, entity_id);

-- Freigabe nur für ein Artefakt dieses Auftrags mit exakt dessen Hash
CREATE TRIGGER approvals_consistent BEFORE INSERT ON approvals
WHEN NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.id = NEW.artifact_id
                 AND a.order_id = NEW.order_id AND a.sha256 = NEW.artifact_sha256)
BEGIN SELECT RAISE(ABORT, 'approval: Artefakt/Hash passt nicht zum Auftrag'); END;

-- Liefer-Gate auf Datenbankebene (zweite Schicht hinter approval.py)
CREATE TRIGGER deliveries_gate BEFORE INSERT ON deliveries
BEGIN
    SELECT RAISE(ABORT, 'delivery: Kunde/Auftrag ungültig oder storniert')
    WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = NEW.order_id
                      AND o.customer_id = NEW.customer_id AND o.status = 'approved');
    SELECT RAISE(ABORT, 'delivery: keine bestätigte, passende Zahlung')
    WHERE NOT EXISTS (SELECT 1 FROM payments p JOIN orders o ON o.id = p.order_id
                      WHERE p.order_id = NEW.order_id AND p.status = 'confirmed'
                      AND p.amount = o.price_amount AND p.currency = o.currency);
    SELECT RAISE(ABORT, 'delivery: keine gültige Betreiberfreigabe für dieses Artefakt')
    WHERE NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.id =
                        (SELECT max(id) FROM approvals WHERE order_id = NEW.order_id)
                      AND ap.decision = 'approved' AND ap.artifact_id = NEW.artifact_id
                      AND ap.artifact_sha256 = NEW.artifact_sha256);
END;

-- Im Versandmoment erneut: Refund/Storno/neue Ablehnung sperren den Versand
CREATE TRIGGER deliveries_send_gate BEFORE UPDATE OF status ON deliveries
WHEN NEW.status = 'sent' AND (
    OLD.status != 'pending'
    OR NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = NEW.order_id
                   AND p.status = 'confirmed')
    OR NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.id =
                     (SELECT max(id) FROM approvals WHERE order_id = NEW.order_id)
                   AND ap.decision = 'approved' AND ap.artifact_id = NEW.artifact_id)
    OR NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = NEW.order_id AND o.status = 'approved'))
BEGIN SELECT RAISE(ABORT, 'delivery: Gate beim Versand nicht erfüllt'); END;

CREATE TRIGGER deliveries_frozen BEFORE UPDATE OF order_id, customer_id, artifact_id,
    artifact_sha256, idempotency_key ON deliveries
BEGIN SELECT RAISE(ABORT, 'delivery: Zuordnung unveränderlich'); END;
""" + "\n".join(
    f"""
CREATE TRIGGER {t}_no_update BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, '{t}: unveränderlich'); END;
CREATE TRIGGER {t}_no_delete BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, '{t}: unveränderlich'); END;"""
    for t in _IMMUTABLE
)

# Geordnete Schritte: neue Datenbank = SCHEMA + alle Schritte; vorhandene Datenbank = nur die
# noch fehlenden. Bestehende Daten werden nie umgeschrieben.
MIGRATIONS: dict[int, str] = {
    2: """
-- Hinterlegter Kundenname (Bild-/Videounterschrift); füllt z. B. der Telegram-Adapter
ALTER TABLE customers ADD COLUMN display_name TEXT;

-- Medienindex der Galerie: jede erzeugte Datei genau einmal (Dateiidentität = SHA-256)
CREATE TABLE media (
    id          INTEGER PRIMARY KEY,
    sha256      TEXT    NOT NULL UNIQUE CHECK (length(sha256) = 64),
    path        TEXT    NOT NULL UNIQUE,
    kind        TEXT    NOT NULL CHECK (kind IN ('image', 'video')),
    size        INTEGER NOT NULL CHECK (size > 0),
    job_id      INTEGER REFERENCES jobs(id),
    artifact_id INTEGER REFERENCES artifacts(id),
    order_id    INTEGER REFERENCES orders(id),
    number      INTEGER UNIQUE,
    created_at  TEXT    NOT NULL,
    CHECK ((order_id IS NULL) = (number IS NOT NULL))
);
CREATE TRIGGER media_no_update BEFORE UPDATE ON media
BEGIN SELECT RAISE(ABORT, 'media: unveränderlich'); END;
CREATE TRIGGER media_no_delete BEFORE DELETE ON media
BEGIN SELECT RAISE(ABORT, 'media: unveränderlich'); END;
""",
    3: """
-- Betreiber darf eigene Medien löschen (Journal 'removed'); Kundenmedien bleiben unveränderlich
DROP TRIGGER media_no_delete;
CREATE TRIGGER media_order_no_delete BEFORE DELETE ON media WHEN OLD.order_id IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'media: Kundenmedien unveränderlich'); END;
""",
    4: """
-- Befehlsjournal (DF-PUSH): Idempotenz je request_id über Neustarts, Lebenszyklus als Receipt
CREATE TABLE commands (
    request_id  TEXT    PRIMARY KEY,
    payload_sha TEXT    NOT NULL CHECK (length(payload_sha) = 64),
    command     TEXT    NOT NULL,
    entity      TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL CHECK (status IN
                ('accepted', 'rejected', 'completed', 'failed', 'unknown', 'cancelled')),
    detail      TEXT    NOT NULL DEFAULT '',
    version     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
-- Terminale Ergebnisse sind endgültig
CREATE TRIGGER commands_final BEFORE UPDATE OF status ON commands
WHEN OLD.status != 'accepted'
BEGIN SELECT RAISE(ABORT, 'command: Ergebnis bereits endgültig'); END;

-- Fachliche Domain-Versionen; steigen nach jedem Commit der Domäne (fingerprint: Registry-Hash)
CREATE TABLE domain_versions (
    domain      TEXT    PRIMARY KEY,
    version     INTEGER NOT NULL,
    fingerprint TEXT    NOT NULL DEFAULT ''
);

-- Herkunft je Job: auslösender Befehl, Eltern-Medium (IDs werden nie neu vergeben, daher ohne
-- Fremdschlüssel), Workflow-Datei-Hash, exakt eingereichter API-Graph und ComfyUI-prompt_id
ALTER TABLE jobs ADD COLUMN request_id TEXT;
ALTER TABLE jobs ADD COLUMN parent_media_id INTEGER;
ALTER TABLE jobs ADD COLUMN workflow_sha256 TEXT;
ALTER TABLE jobs ADD COLUMN graph TEXT;
ALTER TABLE jobs ADD COLUMN prompt_id TEXT;
CREATE UNIQUE INDEX jobs_request ON jobs(request_id) WHERE request_id IS NOT NULL;
""",
}
# Artefaktrollen, die in die Galerie gehören (Eingaben, Masken, Vorschauen nicht)
GALLERY_ROLES = {"master", "candidate", "edit", "refined", "sent"}
MEDIA_KINDS = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
}


class StoreError(Exception):
    """Fachlich unzulässige Operation (Meldung für Menschen)."""


@dataclass(frozen=True)
class Customer:
    id: int
    customer_no: str
    bot_id: str
    telegram_user_id: int
    status: str


@dataclass(frozen=True)
class Order:
    id: int
    order_no: str
    customer_id: int
    customer_no: str
    kind: str
    request: str
    offer: str | None
    price_amount: int | None
    currency: str | None
    status: str


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


class Store:
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

    def _migrate(self) -> None:
        # Einzelne Statements statt executescript(): executescript würde die laufende
        # Transaktion implizit committen; so bleibt die Migration atomar und parallel sicher.
        with self.tx():
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise StoreError(f"Unbekannte Datenbankversion {version} in {self.path}")
            if version == 0:
                for statement in _statements(SCHEMA):
                    self.db.execute(statement)
                version = 1
            for step in range(version + 1, SCHEMA_VERSION + 1):
                for statement in _statements(MIGRATIONS[step]):
                    self.db.execute(statement)
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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

    # ------------------------------------------------------------------ Kunden & Nachrichten

    def customer_for_telegram(self, bot_id: str, telegram_user_id: int) -> tuple[Customer, bool]:
        """Stabile Kundennummer: existierend zurückgeben oder genau einmal anlegen.

        Erst suchen, dann einfügen – innerhalb von BEGIN IMMEDIATE serialisiert. (Ein
        INSERT … ON CONFLICT würde bei AUTOINCREMENT trotzdem eine Nummer verbrauchen und die
        fortlaufende Kundennummerierung lückenhaft machen.) UNIQUE bleibt Sicherheitsnetz.
        """
        with self.tx() as db:
            query = "SELECT * FROM customers WHERE bot_id = ? AND telegram_user_id = ?"
            row = db.execute(query, (bot_id, telegram_user_id)).fetchone()
            if row is not None:
                return _customer(row), False
            db.execute(
                "INSERT INTO customers (bot_id, telegram_user_id, created_at) VALUES (?,?,?)",
                (bot_id, telegram_user_id, now()),
            )
            created = True
            row = db.execute(
                "SELECT * FROM customers WHERE bot_id = ? AND telegram_user_id = ?",
                (bot_id, telegram_user_id),
            ).fetchone()
            if created:
                self._event("customer", row["id"], "created", customer_no=row["customer_no"])
        return _customer(row), created

    def customer(self, customer_no: str) -> Customer:
        row = self.db.execute("SELECT * FROM customers WHERE customer_no = ?", (customer_no,))
        found = row.fetchone()
        if found is None:
            raise StoreError(f"Kunde {customer_no} unbekannt.")
        return _customer(found)

    def add_message(
        self,
        customer_id: int,
        direction: str,
        chat_id: int,
        text: str,
        sent_at: str,
        telegram_message_id: int | None = None,
    ) -> tuple[int, bool]:
        """Speichert eine Nachricht; doppelt zugestellte Telegram-Updates werden erkannt."""
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO messages (customer_id, direction, chat_id, telegram_message_id, text,"
                " sent_at, created_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT (chat_id, direction, telegram_message_id) DO NOTHING",
                (customer_id, direction, chat_id, telegram_message_id, text, sent_at, now()),
            )
            if cur.rowcount == 1:
                return cur.lastrowid, True
            row = db.execute(
                "SELECT id, customer_id FROM messages WHERE chat_id = ? AND direction = ? "
                "AND telegram_message_id = ?",
                (chat_id, direction, telegram_message_id),
            ).fetchone()
            if row["customer_id"] != customer_id:
                raise StoreError("Nachricht ist bereits einem anderen Kunden zugeordnet.")
            return row["id"], False

    # ------------------------------------------------------------------ Aufträge

    def order(self, order_no: str) -> Order:
        row = self.db.execute(
            "SELECT o.*, c.customer_no FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE o.order_no = ?",
            (order_no,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Auftrag {order_no} unbekannt.")
        return _order(row)

    def order_dir(self, order: Order) -> Path:
        return self.local / "customers" / order.customer_no / "orders" / order.order_no

    def create_order(self, customer_id: int, kind: str, request: str) -> Order:
        if kind not in ORDER_KINDS:
            raise StoreError(f"Auftragstyp {kind!r} unbekannt (erlaubt: {ORDER_KINDS}).")
        with self.tx() as db:
            ts = now()
            cur = db.execute(
                "INSERT INTO orders (customer_id, kind, request, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (customer_id, kind, request, ts, ts),
            )
            no = db.execute("SELECT order_no FROM orders WHERE id = ?", (cur.lastrowid,))
            order = self.order(no.fetchone()[0])
            self._event("order", order.id, "created", order_no=order.order_no, kind=kind)
        for sub in ("input", "work", "sent"):
            (self.order_dir(order) / sub).mkdir(parents=True, exist_ok=True)
        return order

    def transition(self, order_no: str, new_status: str, **data: object) -> Order:
        with self.tx() as db:
            order = self.order(order_no)
            if new_status not in TRANSITIONS.get(order.status, set()):
                raise StoreError(
                    f"{order_no}: Übergang {order.status} -> {new_status} nicht erlaubt."
                )
            db.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now(), order.id),
            )
            self._event("order", order.id, "status", old=order.status, new=new_status, **data)
            return self.order(order_no)

    def set_offer(self, order_no: str, offer: str, price_amount: int, currency: str) -> Order:
        if price_amount <= 0 or not currency:
            raise StoreError("Angebot braucht positiven Preis und Währung.")
        with self.tx() as db:
            order = self.order(order_no)
            if order.status != "draft":
                raise StoreError(f"{order_no}: Angebot nur im Status draft möglich.")
            db.execute(
                "UPDATE orders SET offer = ?, price_amount = ?, currency = ?, updated_at = ? "
                "WHERE id = ?",
                (offer, price_amount, currency, now(), order.id),
            )
            return self.transition(order_no, "offered", price=price_amount, currency=currency)

    # ------------------------------------------------------------------ Zahlungen

    def record_payment(
        self, order_no: str, provider: str, provider_tx_id: str, amount: int, currency: str
    ) -> int:
        """Bestätigte Zahlung erfassen. Aufrufer ist ausschließlich der verifizierende
        Provider-Adapter (S5) – nie LLM, Kundentext oder Screenshot. Idempotent je Transaktion."""
        with self.tx() as db:
            order = self.order(order_no)
            existing = db.execute(
                "SELECT id, order_id FROM payments WHERE provider = ? AND provider_tx_id = ?",
                (provider, provider_tx_id),
            ).fetchone()
            if existing is not None:
                if existing["order_id"] != order.id:
                    raise StoreError("Transaktion gehört zu einem anderen Auftrag.")
                return existing["id"]
            if order.status != "accepted":
                raise StoreError(f"{order_no}: Zahlung nur im Status accepted ({order.status}).")
            if amount != order.price_amount or currency != order.currency:
                raise StoreError(
                    f"{order_no}: Betrag/Währung {amount} {currency} passt nicht zum Angebot "
                    f"{order.price_amount} {order.currency}."
                )
            cur = db.execute(
                "INSERT INTO payments (order_id, provider, provider_tx_id, amount, currency, "
                "status, confirmed_at) VALUES (?,?,?,?,?,'confirmed',?)",
                (order.id, provider, provider_tx_id, amount, currency, now()),
            )
            self._event("payment", cur.lastrowid, "confirmed", order_no=order_no, amount=amount)
            self.transition(order_no, "paid", payment_id=cur.lastrowid)
            return cur.lastrowid

    def record_refund(self, provider: str, provider_tx_id: str) -> None:
        with self.tx() as db:
            row = db.execute(
                "SELECT p.id, o.order_no FROM payments p JOIN orders o ON o.id = p.order_id "
                "WHERE p.provider = ? AND p.provider_tx_id = ? AND p.status = 'confirmed'",
                (provider, provider_tx_id),
            ).fetchone()
            if row is None:
                raise StoreError("Keine bestätigte Zahlung zu dieser Transaktion.")
            db.execute(
                "UPDATE payments SET status = 'refunded', refunded_at = ? WHERE id = ?",
                (now(), row["id"]),
            )
            self._event("payment", row["id"], "refunded")
            self.transition(row["order_no"], "refunded", payment_id=row["id"])

    # ------------------------------------------------------------------ Jobs & Artefakte

    def create_job(
        self,
        order_no: str | None,
        engine: str,
        workflow: str,
        prompt: str,
        params: dict,
        seeds: list,
        *,
        parent_media_id: int | None = None,
        command: dict | None = None,
    ) -> int:
        """Job anlegen; ``order_no=None`` für Renderungen ohne Kundenbezug (Evaluation).
        ``command``: auslösender Befehl (``record_command``-Argumente) – Job und Befehlsjournal
        entstehen in EINEM Commit, damit eine Wiederholung nie einen zweiten Job erzeugt."""
        with self.tx() as db:
            order_id = self.order(order_no).id if order_no else None
            ts = now()
            cur = db.execute(
                "INSERT INTO jobs (order_id, engine, workflow, prompt, params, seeds, created_at,"
                " updated_at, parent_media_id, request_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    order_id,
                    engine,
                    workflow,
                    prompt,
                    json.dumps(params),
                    json.dumps(seeds),
                    ts,
                    ts,
                    parent_media_id,
                    command["request_id"] if command else None,
                ),
            )
            job_id = cur.lastrowid
            self._event("job", job_id, "created", order_no=order_no, workflow=workflow)
            self.bump("jobs")
            if command:
                self.record_command(**command, entity=f"job:{job_id}")
            return job_id

    def set_job_status(
        self, job_id: int, status: str, error: str | None = None, **result: object
    ) -> None:
        """Statuswechsel mit Journal-Ereignis; der Abschluss (done/failed) trägt das Ergebnis und
        beendet im selben Commit den auslösenden Befehl (Receipt)."""
        with self.tx() as db:
            db.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, now(), job_id),
            )
            self._event("job", job_id, "status", status=status, error=error, **result)
            self.bump("jobs")
            if status in ("done", "failed"):
                rid = db.execute("SELECT request_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if rid and rid[0]:
                    final = (
                        "completed"
                        if status == "done"
                        else "cancelled"
                        if result.get("cancelled")
                        else "failed"
                    )
                    self.finish_command(rid[0], final, detail=error or "")

    def set_job_submitted(
        self, job_id: int, prompt_id: str, graph: dict, workflow_sha: str
    ) -> None:
        """Bei ComfyUI eingereicht: exakter API-Graph, Workflow-Hash und prompt_id (Wiederanlauf
        und Reproduzierbarkeit)."""
        with self.tx() as db:
            db.execute(
                "UPDATE jobs SET prompt_id = ?, graph = ?, workflow_sha256 = ?, updated_at = ?"
                " WHERE id = ?",
                (prompt_id, json.dumps(graph, ensure_ascii=False), workflow_sha, now(), job_id),
            )
            self._event("job", job_id, "submitted", prompt_id=prompt_id)

    def requeue_job(self, job_id: int) -> None:
        """Nie bei ComfyUI eingereichter, unterbrochener Job läuft nach dem Neustart erneut."""
        with self.tx() as db:
            cur = db.execute(
                "UPDATE jobs SET status = 'queued', updated_at = ? WHERE id = ?"
                " AND status = 'running' AND prompt_id IS NULL",
                (now(), job_id),
            )
            if cur.rowcount:
                self._event("job", job_id, "status", status="queued", error=None, requeued=True)
                self.bump("jobs")

    def job(self, job_id: int) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise StoreError(f"Job {job_id} ist unbekannt.")
        return dict(row) | {
            "params": json.loads(row["params"]),
            "seeds": json.loads(row["seeds"]),
            "graph": json.loads(row["graph"]) if row["graph"] else None,
        }

    def running_job_ids(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT id FROM jobs WHERE status = 'running'")]

    def queued_jobs(self) -> list[tuple[int, str]]:
        """Angelegte, noch nicht gestartete Jobs in Eingangsreihenfolge (FIFO): (ID, Workflow)."""
        rows = self.db.execute("SELECT id, workflow FROM jobs WHERE status = 'queued' ORDER BY id")
        return [(r["id"], r["workflow"]) for r in rows]

    def running_jobs(self) -> list[tuple[int, int | None]]:
        """Jobs im Status running mit der Prozess-ID, die sie ausführt (aus dem Journal)."""
        rows = self.db.execute(
            "SELECT j.id, json_extract(e.data, '$.pid') AS pid FROM jobs j"
            " JOIN events e ON e.entity = 'job' AND e.entity_id = j.id AND e.event = 'status'"
            " AND json_extract(e.data, '$.status') = 'running' WHERE j.status = 'running'"
        )
        return [(r["id"], r["pid"]) for r in rows]

    def jobs_brief(self, job_ids: list[int]) -> dict[int, tuple[str, dict]]:
        """(Workflow, Parameter) je Job-ID (unbekannte IDs fehlen im Ergebnis)."""
        marks = ",".join("?" * len(job_ids))
        rows = self.db.execute(
            f"SELECT id, workflow, params FROM jobs WHERE id IN ({marks})", job_ids
        )
        return {r["id"]: (r["workflow"], json.loads(r["params"])) for r in rows}

    def finished_jobs(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Abgeschlossene Jobs aus dem Journal mit Cursor (events.id) > ``after``: höchstens die
        neuesten ``limit``, aufsteigend. Zweiter Wert: dazwischen wurden ältere ausgelassen."""
        rows = self.db.execute(
            "SELECT e.id, e.entity_id AS job_id, e.created_at, e.data, j.workflow, j.engine,"
            " j.params,"
            " o.order_no FROM events e"
            " JOIN jobs j ON j.id = e.entity_id LEFT JOIN orders o ON o.id = j.order_id"
            " WHERE e.entity = 'job' AND e.event = 'status' AND e.id > ?"
            " AND json_extract(e.data, '$.status') IN ('done', 'failed')"
            " ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [
            dict(r) | {"data": json.loads(r["data"]), "params": json.loads(r["params"])}
            for r in rows[:limit]
        ]
        return recent[::-1], len(rows) > limit

    # ------------------------------------------------------------------ Befehle (DF-PUSH)

    def command(self, request_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM commands WHERE request_id = ?", (request_id,))
        found = row.fetchone()
        return dict(found) if found else None

    def record_command(
        self,
        request_id: str,
        payload_sha: str,
        command: str,
        status: str,
        *,
        entity: str = "",
        detail: str = "",
        version: int = 0,
    ) -> None:
        """Befehl genau einmal festhalten (PRIMARY KEY request_id) samt erster Receipt; die
        Antwort auf eine Wiederholung derselben request_id ergibt sich aus diesem Eintrag."""
        with self.tx() as db:
            ts = now()
            cur = db.execute(
                "INSERT INTO commands (request_id, payload_sha, command, entity, status, detail,"
                " version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (request_id, payload_sha, command, entity, status, detail, version, ts, ts),
            )
            self._receipt(cur.lastrowid, request_id, command, status, entity, detail, version)

    def finish_command(
        self, request_id: str, status: str, *, detail: str = "", version: int | None = None
    ) -> bool:
        """Terminales Ergebnis eines angenommenen Befehls; bereits beendete bleiben unverändert."""
        with self.tx() as db:
            row = db.execute(
                "SELECT rowid, * FROM commands WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None or row["status"] != "accepted":
                return False
            final_version = row["version"] if version is None else version
            db.execute(
                "UPDATE commands SET status = ?, detail = ?, version = ?, updated_at = ?"
                " WHERE request_id = ?",
                (status, detail, final_version, now(), request_id),
            )
            self._receipt(
                row["rowid"],
                request_id,
                row["command"],
                status,
                row["entity"],
                detail,
                final_version,
            )
            return True

    def _receipt(
        self,
        rowid: int,
        request_id: str,
        command: str,
        status: str,
        entity: str,
        detail: str,
        version: int,
    ) -> None:
        self._event(
            "command",
            rowid,
            "receipt",
            request_id=request_id,
            command=command,
            status=status,
            target=entity,
            detail=detail,
            version=version,
        )

    def open_commands(self) -> list[dict]:
        """Angenommene, noch nicht beendete Befehle (nach einem Neustart zu klären)."""
        return [
            dict(r) for r in self.db.execute("SELECT * FROM commands WHERE status = 'accepted'")
        ]

    def receipts(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Receipts aus dem Journal mit Cursor > ``after`` (neueste ``limit``, aufsteigend)."""
        rows = self.db.execute(
            "SELECT id AS cursor, created_at AS committed_at, data FROM events"
            " WHERE entity = 'command' AND event = 'receipt' AND id > ? ORDER BY id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = []
        for r in rows[:limit]:
            data = json.loads(r["data"])
            data["entity"] = data.pop("target")
            recent.append({"cursor": r["cursor"], "committed_at": r["committed_at"]} | data)
        return recent[::-1], len(rows) > limit

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

    # ------------------------------------------------------------------ Medienindex

    def add_media(
        self,
        rel: str,
        sha: str,
        size: int,
        *,
        job_id: int | None = None,
        artifact_id: int | None = None,
        created_at: str | None = None,
    ) -> int | None:
        """Nimmt eine erzeugte Datei (Pfad relativ zu ``local/``) genau einmal in die Galerie auf.
        Gleiche Bytes oder gleicher Pfad -> keine zweite Aufnahme (None). Kundenbezug nur über
        Auftrag (Job/Artefakt), sonst eine stabile fortlaufende Nummer."""
        kind = MEDIA_KINDS.get(Path(rel).suffix.lower())
        if kind is None:
            raise StoreError(f"{rel}: kein Bild-/Videoformat")
        with self.tx() as db:
            if db.execute(
                "SELECT 1 FROM media WHERE sha256 = ? OR path = ?", (sha, rel)
            ).fetchone():
                return None
            order_id = None
            if artifact_id is not None:
                order_id = self.artifact(artifact_id).order_id
            elif job_id is not None:
                order_id = db.execute(
                    "SELECT order_id FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()[0]
            # IDs und Nummern gelöschter Einträge werden nie wieder vergeben: das Journal kennt
            # jede jemals vergebene ID ('added') und jede gelöschte Nummer ('removed').
            media_id = db.execute(
                "SELECT coalesce(max(entity_id), 0) + 1 FROM events WHERE entity = 'media'"
            ).fetchone()[0]
            number = None
            if order_id is None:
                number = db.execute(
                    "SELECT max(coalesce((SELECT max(number) FROM media), 0), coalesce((SELECT"
                    " max(json_extract(data, '$.number')) FROM events WHERE entity = 'media'"
                    " AND event = 'removed'), 0)) + 1"
                ).fetchone()[0]
            db.execute(
                "INSERT INTO media (id, sha256, path, kind, size, job_id, artifact_id, order_id,"
                " number, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    media_id,
                    sha,
                    rel,
                    kind,
                    size,
                    job_id,
                    artifact_id,
                    order_id,
                    number,
                    created_at or now(),
                ),
            )
            self._event("media", media_id, "added", path=rel)
            self.bump("media")
            return media_id

    def remove_media(self, ids: list[int]) -> list[dict]:
        """Entfernt Galerie-Einträge (nur ohne Kundenbezug) und hält jeden im Journal als
        'removed' fest; bereits gelöschte IDs werden übergangen. Liefert die entfernten Zeilen."""
        with self.tx() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    f"SELECT * FROM media WHERE id IN ({','.join('?' * len(ids))})", ids
                )
            ]
            if any(r["order_id"] is not None for r in rows):
                raise StoreError("Medien eines Kundenauftrags können nicht gelöscht werden.")
            for r in rows:
                db.execute("DELETE FROM media WHERE id = ?", (r["id"],))
                self._event("media", r["id"], "removed", path=r["path"], number=r["number"])
            if rows:
                self.bump("media")
        return rows

    _MEDIA_SELECT = (
        "SELECT m.*, j.workflow, j.params, o.order_no, c.customer_no, c.display_name FROM media m"
        " LEFT JOIN jobs j ON j.id = m.job_id LEFT JOIN orders o ON o.id = m.order_id"
        " LEFT JOIN customers c ON c.id = o.customer_id"
    )

    def _media_rows(self, rows: list[sqlite3.Row]) -> list[dict]:
        return [dict(r) | {"params": json.loads(r["params"] or "{}")} for r in rows]

    def media_page(self, before: int, limit: int) -> tuple[list[dict], bool]:
        """Galerieseite, neueste zuerst; ``before`` = 0 beginnt bei der neuesten Datei."""
        rows = self.db.execute(
            self._MEDIA_SELECT + " WHERE (? = 0 OR m.id < ?) ORDER BY m.id DESC LIMIT ?",
            (before, before, limit + 1),
        ).fetchall()
        return self._media_rows(rows[:limit]), len(rows) > limit

    def media_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Aufgenommene Medien aus dem Journal mit Cursor > ``after`` (neueste ``limit``,
        aufsteigend); zweiter Wert: ältere wurden ausgelassen."""
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, x.* FROM events e JOIN ("
            + self._MEDIA_SELECT
            + ") x ON x.id = e.entity_id WHERE e.entity = 'media' AND e.event = 'added'"
            " AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return self._media_rows(rows[:limit])[::-1], len(rows) > limit

    def media_removed(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Gelöschte Medien aus dem Journal mit Cursor > ``after`` (neueste ``limit``,
        aufsteigend); zweiter Wert: ältere wurden ausgelassen."""
        rows = self.db.execute(
            "SELECT id AS cursor, created_at AS committed_at, entity_id AS media_id,"
            " json_extract(data, '$.path') AS path FROM events WHERE entity = 'media'"
            " AND event = 'removed' AND id > ? ORDER BY id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]][::-1], len(rows) > limit

    def removed_media_paths(self) -> set[str]:
        return {
            r[0]
            for r in self.db.execute(
                "SELECT json_extract(data, '$.path') FROM events"
                " WHERE entity = 'media' AND event = 'removed'"
            )
        }

    def media_by_path(self, rel: str) -> dict | None:
        row = self.db.execute("SELECT * FROM media WHERE path = ?", (rel,)).fetchone()
        return dict(row) if row else None

    def media_by_id(self, media_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return dict(row) if row else None

    def media_paths(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT path FROM media")}

    def journal_head(self) -> int:
        """Höchster Journal-Cursor (0 = leeres Journal)."""
        return self.db.execute("SELECT coalesce(max(id), 0) FROM events").fetchone()[0]

    def add_artifact(
        self,
        order_no: str,
        role: str,
        file: Path,
        *,
        job_id: int | None = None,
        parent_id: int | None = None,
        provenance: dict | None = None,
    ) -> Artifact:
        """Registriert eine Datei im Auftragsordner als unveränderliches Artefakt (Hash + 0444)."""
        if role not in ARTIFACT_ROLES:
            raise StoreError(f"Artefaktrolle {role!r} unbekannt.")
        order = self.order(order_no)
        file = file.resolve()
        if not file.is_relative_to(self.order_dir(order).resolve()) or not file.is_file():
            raise StoreError(f"{file} liegt nicht im Ordner von {order_no}.")
        sha, size = sha256_file(file), file.stat().st_size
        rel = file.relative_to(self.local.resolve()).as_posix()
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO artifacts (order_id, job_id, parent_id, role, path, sha256, size,"
                " provenance, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    order.id,
                    job_id,
                    parent_id,
                    role,
                    rel,
                    sha,
                    size,
                    json.dumps(provenance or {}, ensure_ascii=False),
                    now(),
                ),
            )
            self._event(
                "artifact", cur.lastrowid, "created", order_no=order_no, role=role, sha256=sha
            )
            if role in GALLERY_ROLES and file.suffix.lower() in MEDIA_KINDS:
                self.add_media(rel, sha, size, artifact_id=cur.lastrowid)
        os.chmod(file, 0o444)
        return self.artifact(cur.lastrowid)

    def artifact(self, artifact_id: int) -> Artifact:
        row = self.db.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise StoreError(f"Artefakt {artifact_id} unbekannt.")
        return Artifact(
            id=row["id"],
            order_id=row["order_id"],
            role=row["role"],
            path=row["path"],
            sha256=row["sha256"],
            size=row["size"],
            parent_id=row["parent_id"],
            job_id=row["job_id"],
        )

    # ------------------------------------------------------------------ Freigaben

    def record_approval(self, order_no: str, artifact_id: int, decision: str, operator: str) -> int:
        """Betreiberentscheidung (nie vom LLM). Freigabe setzt Auftrag auf approved."""
        with self.tx() as db:
            order = self.order(order_no)
            art = self.artifact(artifact_id)
            if art.order_id != order.id:
                raise StoreError("Artefakt gehört nicht zu diesem Auftrag.")
            if order.status != "review":
                raise StoreError(f"{order_no}: Entscheidung nur im Status review ({order.status}).")
            cur = db.execute(
                "INSERT INTO approvals (order_id, artifact_id, artifact_sha256, decision, operator,"
                " decided_at) VALUES (?,?,?,?,?,?)",
                (order.id, art.id, art.sha256, decision, operator, now()),
            )
            self._event("approval", cur.lastrowid, decision, order_no=order_no, artifact=art.id)
            if decision == "approved":
                self.transition(order_no, "approved", approval_id=cur.lastrowid)
            elif decision == "regenerate":
                self.transition(order_no, "producing", approval_id=cur.lastrowid)
            return cur.lastrowid

    def events(self, entity: str, entity_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT event, data, created_at FROM events WHERE entity = ? AND entity_id = ? "
            "ORDER BY id",
            (entity, entity_id),
        )
        return [dict(r) | {"data": json.loads(r["data"])} for r in rows]


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
        bot_id=row["bot_id"],
        telegram_user_id=row["telegram_user_id"],
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
    )
