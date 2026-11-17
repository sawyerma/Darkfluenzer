"""Schema und feste Wertemengen der Datenbank (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

SCHEMA_VERSION = 25
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
# Aufträge ohne Kunden (Betreiber, Kloner): Produktion -> Prüfung -> Freigabe, ohne Angebot/Zahlung
OPERATOR_TRANSITIONS: dict[str, set[str]] = {
    "producing": {"review", "cancelled"},
    "review": {"producing", "approved", "cancelled"},
    "approved": {"producing"},
    "cancelled": set(),
}
ORDER_SOURCES = ("operator", "cloner", "customer")
# Stufen eines Auftrags (V0 §4.3); weitere Arten kommen additiv (Bearbeiten, Video, Freigabe …)
STAGE_KINDS = ("candidates", "finish")
STAGE_ACTIVE = ("running", "waiting")
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
