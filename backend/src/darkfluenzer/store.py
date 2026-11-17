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
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .payments.vouchers import extract as extract_vouchers

SCHEMA_VERSION = 17
DB_NAME = "darkfluenzer.sqlite3"
log = logging.getLogger("darkfluenzer.store")

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
    5: """
-- Auftrag mit Stufen (V0 §4.3): ein Auftragstyp für Betreiber, Kloner und Kunden; nur
-- Kundenaufträge haben einen Kunden. Neubau der Tabelle (SQLite kann NOT NULL nicht ändern),
-- alle Zeilen bleiben mit ihrer ID erhalten.
CREATE TABLE orders_v5 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no     TEXT GENERATED ALWAYS AS ('DF-O-' || printf('%06d', id)) STORED,
    source       TEXT    NOT NULL DEFAULT 'customer'
                 CHECK (source IN ('operator', 'cloner', 'customer')),
    customer_id  INTEGER REFERENCES customers(id),
    kind         TEXT    NOT NULL CHECK (kind IN ('image', 'video')),
    request      TEXT    NOT NULL,
    offer        TEXT,
    price_amount INTEGER CHECK (price_amount IS NULL OR price_amount > 0),
    currency     TEXT,
    status       TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'offered', 'accepted',
                 'paid', 'producing', 'review', 'approved', 'delivered', 'cancelled', 'refunded')),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    CHECK ((source = 'customer') = (customer_id IS NOT NULL))
);
INSERT INTO orders_v5 (id, source, customer_id, kind, request, offer, price_amount, currency,
                       status, created_at, updated_at)
SELECT id, 'customer', customer_id, kind, request, offer, price_amount, currency, status,
       created_at, updated_at FROM orders;
DROP TABLE orders;
ALTER TABLE orders_v5 RENAME TO orders;
CREATE UNIQUE INDEX orders_no ON orders(order_no);
CREATE INDEX orders_customer ON orders(customer_id);

-- Stufen: Kandidaten (n Jobs, dann Auswahl durch den Betreiber), Fertigstellen …
CREATE TABLE order_stages (
    id                INTEGER PRIMARY KEY,
    order_id          INTEGER NOT NULL REFERENCES orders(id),
    seq               INTEGER NOT NULL CHECK (seq > 0),
    kind              TEXT    NOT NULL,
    status            TEXT    NOT NULL
                      CHECK (status IN ('running', 'waiting', 'done', 'failed', 'cancelled')),
    workflow          TEXT    NOT NULL,
    params            TEXT    NOT NULL DEFAULT '{}',
    count             INTEGER NOT NULL DEFAULT 1 CHECK (count > 0),
    selected_media_id INTEGER,
    attempts          INTEGER NOT NULL DEFAULT 1,
    error             TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    UNIQUE (order_id, seq)
);
ALTER TABLE jobs ADD COLUMN stage_id INTEGER REFERENCES order_stages(id);
CREATE INDEX jobs_stage ON jobs(stage_id) WHERE stage_id IS NOT NULL;
""",
    6: """
-- Kanal-Basis (V0 §6, C2): kanalunabhängige Kundenakte; Plattformkonten als Identitäten;
-- Konversationen je Plattform-Chat; Nachrichten mit Ein-/Ausgang und Status (ersetzt die
-- Telegram-Tabelle messages); Eingangsereignisse zur Deduplizierung; Adapterzustand.
CREATE TABLE customers_v6 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_no  TEXT GENERATED ALWAYS AS ('DF-C-' || printf('%06d', id)) STORED,
    kind         TEXT    NOT NULL DEFAULT 'customer' CHECK (kind IN ('customer', 'internal')),
    display_name TEXT,
    status       TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'blocked')),
    created_at   TEXT    NOT NULL
);
INSERT INTO customers_v6 (id, display_name, status, created_at)
SELECT id, display_name, status, created_at FROM customers;

CREATE TABLE channel_identities (
    id               INTEGER PRIMARY KEY,
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    platform         TEXT    NOT NULL CHECK (platform IN ('telegram', 'instagram', 'whatsapp')),
    account          TEXT    NOT NULL,
    platform_user_id TEXT    NOT NULL,
    handle           TEXT,
    verified         INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    created_at       TEXT    NOT NULL,
    UNIQUE (platform, account, platform_user_id)
);
INSERT INTO channel_identities (customer_id, platform, account, platform_user_id, verified,
                                created_at)
SELECT id, 'telegram', bot_id, CAST(telegram_user_id AS TEXT), 1, created_at FROM customers;

CREATE TABLE channel_conversations (
    id                       INTEGER PRIMARY KEY,
    identity_id              INTEGER NOT NULL REFERENCES channel_identities(id),
    platform_conversation_id TEXT    NOT NULL,
    revision                 INTEGER NOT NULL DEFAULT 0,
    created_at               TEXT    NOT NULL,
    UNIQUE (identity_id, platform_conversation_id)
);
INSERT INTO channel_conversations (identity_id, platform_conversation_id, created_at)
SELECT DISTINCT i.id, CAST(m.chat_id AS TEXT), min(m.created_at) FROM messages m
JOIN channel_identities i ON i.customer_id = m.customer_id AND i.platform = 'telegram'
GROUP BY i.id, m.chat_id;

CREATE TABLE channel_messages (
    id                   INTEGER PRIMARY KEY,
    customer_id          INTEGER NOT NULL REFERENCES customers(id),
    conversation_id      INTEGER NOT NULL REFERENCES channel_conversations(id),
    direction            TEXT    NOT NULL CHECK (direction IN ('in', 'out')),
    platform_message_id  TEXT,
    reply_to_platform_id TEXT,
    text                 TEXT    NOT NULL DEFAULT '',
    attachments          TEXT    NOT NULL DEFAULT '[]',
    status               TEXT    NOT NULL CHECK (status IN
                         ('received', 'queued', 'sending', 'sent', 'failed', 'unknown')),
    error                TEXT,
    request_id           TEXT,
    sent_at              TEXT    NOT NULL,
    read_at              TEXT,
    created_at           TEXT    NOT NULL,
    UNIQUE (conversation_id, direction, platform_message_id)
);
CREATE INDEX channel_messages_customer ON channel_messages(customer_id, id);
CREATE UNIQUE INDEX channel_messages_request ON channel_messages(request_id)
    WHERE request_id IS NOT NULL;
INSERT INTO channel_messages (customer_id, conversation_id, direction, platform_message_id,
                              text, status, sent_at, created_at)
SELECT m.customer_id, c.id, m.direction, CAST(m.telegram_message_id AS TEXT), m.text,
       CASE m.direction WHEN 'in' THEN 'received' ELSE 'sent' END, m.sent_at, m.created_at
FROM messages m JOIN channel_identities i ON i.customer_id = m.customer_id
JOIN channel_conversations c ON c.identity_id = i.id
     AND c.platform_conversation_id = CAST(m.chat_id AS TEXT);
DROP TABLE messages;
DROP TABLE customers;
ALTER TABLE customers_v6 RENAME TO customers;
CREATE UNIQUE INDEX customers_no ON customers(customer_no);

-- Eingangsereignisse je Plattform genau einmal (Telegram update_id, Instagram mid)
CREATE TABLE inbound_events (
    id          INTEGER PRIMARY KEY,
    platform    TEXT NOT NULL,
    account     TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE (platform, account, event_id)
);
-- Gesicherte Anhänge eingehender Nachrichten (Medien-Endpunkt liefert nur diese und die Galerie)
CREATE TABLE message_files (
    path       TEXT    PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES channel_messages(id),
    sha256     TEXT    NOT NULL CHECK (length(sha256) = 64),
    size       INTEGER NOT NULL CHECK (size > 0),
    mime       TEXT    NOT NULL DEFAULT ''
);
-- Dauerhafter Adapterzustand (z. B. Telegram-Update-Offset)
CREATE TABLE adapter_state (
    platform TEXT NOT NULL,
    account  TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (platform, account, key)
);
-- Interner Kontakt Default (V0 §8, FRONT F7.4): Operator-Felder, Revision für CAS
CREATE TABLE default_contact (
    customer_id      INTEGER PRIMARY KEY REFERENCES customers(id),
    process_commands INTEGER NOT NULL DEFAULT 1 CHECK (process_commands IN (0, 1)),
    auto_orders      INTEGER NOT NULL DEFAULT 1 CHECK (auto_orders IN (0, 1)),
    approval_mode    TEXT    NOT NULL DEFAULT 'cockpit'
                     CHECK (approval_mode IN ('direct', 'cockpit', 'cockpit_only')),
    influencer       TEXT    NOT NULL DEFAULT '',
    media_workflow   TEXT    NOT NULL DEFAULT '',
    revision         INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT    NOT NULL
);
""",
    7: """
-- Systemkarten im Verlauf (INTERNER AUFTRAG, Rückfragen) und Auftragsbezug je Nachricht
CREATE TABLE channel_messages_v7 (
    id                   INTEGER PRIMARY KEY,
    customer_id          INTEGER NOT NULL REFERENCES customers(id),
    conversation_id      INTEGER NOT NULL REFERENCES channel_conversations(id),
    direction            TEXT    NOT NULL CHECK (direction IN ('in', 'out', 'system')),
    platform_message_id  TEXT,
    reply_to_platform_id TEXT,
    text                 TEXT    NOT NULL DEFAULT '',
    attachments          TEXT    NOT NULL DEFAULT '[]',
    status               TEXT    NOT NULL CHECK (status IN
                         ('received', 'queued', 'sending', 'sent', 'failed', 'unknown')),
    error                TEXT,
    request_id           TEXT,
    order_id             INTEGER REFERENCES orders(id),
    sent_at              TEXT    NOT NULL,
    read_at              TEXT,
    created_at           TEXT    NOT NULL,
    UNIQUE (conversation_id, direction, platform_message_id)
);
INSERT INTO channel_messages_v7 (id, customer_id, conversation_id, direction,
    platform_message_id, reply_to_platform_id, text, attachments, status, error, request_id,
    sent_at, read_at, created_at)
SELECT id, customer_id, conversation_id, direction, platform_message_id, reply_to_platform_id,
       text, attachments, status, error, request_id, sent_at, read_at, created_at
FROM channel_messages;
DROP TABLE channel_messages;
ALTER TABLE channel_messages_v7 RENAME TO channel_messages;
CREATE INDEX channel_messages_customer ON channel_messages(customer_id, id);
CREATE UNIQUE INDEX channel_messages_request ON channel_messages(request_id)
    WHERE request_id IS NOT NULL;
CREATE INDEX channel_messages_order ON channel_messages(order_id) WHERE order_id IS NOT NULL;
""",
    8: """
-- Karte eines wartenden Kloner-Auftrags verweist auf die auslösende Nachricht (Start im Cockpit)
ALTER TABLE channel_messages ADD COLUMN origin_message_id INTEGER REFERENCES channel_messages(id);
""",
    9: """
-- Default-Kontakt: eigener Video-Workflow für den Befehl animate (Foto -> Video)
ALTER TABLE default_contact ADD COLUMN video_workflow TEXT NOT NULL DEFAULT '';
""",
    10: """
-- Charakterprofile (V0 §9.2, B2): Name, Projektordner für Datensätze, Trainingsdatenordner.
-- Profil 1 übernimmt den bisherigen Ordner local/character (B1).
CREATE TABLE characters (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    data_dir    TEXT    NOT NULL UNIQUE,
    photos_dir  TEXT    NOT NULL,
    revision    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
INSERT INTO characters (name, data_dir, photos_dir, created_at, updated_at)
VALUES ('Charakter 01', 'local/character', 'local/character/photos',
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
""",
    11: """
-- Vorlagenbibliothek (C1): inhaltsadressiert, Herkunft Dateien oder Kloner-Eingang
CREATE TABLE reference_files (
    id          INTEGER PRIMARY KEY,
    sha256      TEXT    NOT NULL UNIQUE CHECK (length(sha256) = 64),
    path        TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('image', 'video')),
    source      TEXT    NOT NULL,
    analysis    TEXT    NOT NULL DEFAULT 'none'
                CHECK (analysis IN ('none', 'pending', 'done', 'failed')),
    created_at  TEXT    NOT NULL
);
""",
    12: """
-- Zahlungseingänge (V0 §8.5, C5a): beobachtete Eingänge genau einmal je Ausgang/Log, Euro-Wert und
-- Kurs beim Eingang; erst die Zuordnung zu einem Auftrag erzeugt eine Zeile in payments (Gate)
CREATE TABLE payment_inflows (
    id            INTEGER PRIMARY KEY,
    method        TEXT    NOT NULL CHECK (method IN ('btc', 'usdt', 'usdc', 'paypal', 'amazon')),
    network       TEXT    NOT NULL,
    asset         TEXT    NOT NULL,
    amount        TEXT    NOT NULL,
    txid          TEXT    NOT NULL,
    position      INTEGER NOT NULL DEFAULT 0,
    block         INTEGER,
    confirmations INTEGER NOT NULL DEFAULT 0,
    required      INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL CHECK (status IN
                  ('detected', 'confirmed', 'assigned', 'unassigned', 'expired')),
    eur           REAL,
    rate          REAL,
    rate_ms       INTEGER,
    order_id      INTEGER REFERENCES orders(id),
    customer_id   INTEGER REFERENCES customers(id),
    detected_at   TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    UNIQUE (method, txid, position)
);
CREATE INDEX payment_inflows_open ON payment_inflows(network, status) WHERE status = 'detected';
""",
    13: """
-- Influencerin-Profile (C5, FRONT F4 V1.12 Punkt 12): Persona, KI-Hinweistext, Preisliste
CREATE TABLE influencers (
    id            INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    character_id  INTEGER REFERENCES characters(id),
    persona       TEXT    NOT NULL DEFAULT '',
    ai_notice     TEXT    NOT NULL DEFAULT '',
    revision      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
CREATE TABLE influencer_prices (
    influencer_id      INTEGER NOT NULL REFERENCES influencers(id),
    position           INTEGER NOT NULL,
    product            TEXT    NOT NULL CHECK (length(trim(product)) > 0),
    price_cents        INTEGER NOT NULL CHECK (price_cents > 0),
    hd_surcharge_cents INTEGER NOT NULL DEFAULT 0 CHECK (hd_surcharge_cents >= 0),
    PRIMARY KEY (influencer_id, position)
);
""",
    14: """
-- Inhaltsstufe je Job und Medium (Regel 13; NULL = unbekannt = explizit), Altersangabe je Akte
-- (Regel 13; Standard unklar, setzt nur der Betreiber), KI-Hinweis je Kanalidentität (Regel 12 b)
ALTER TABLE jobs ADD COLUMN content_tier TEXT CHECK (content_tier IN ('standard', 'explizit'));
ALTER TABLE media ADD COLUMN content_tier TEXT CHECK (content_tier IN ('standard', 'explizit'));
ALTER TABLE customers ADD COLUMN age_mark TEXT NOT NULL DEFAULT 'unclear'
    CHECK (age_mark IN ('unclear', 'under_18', 'self_declared_adult'));
ALTER TABLE channel_identities ADD COLUMN ai_notice_message_id INTEGER
    REFERENCES channel_messages(id);
-- Medien bleiben unveränderlich bis auf die Inhaltsstufe, und die nur anhebbar
DROP TRIGGER media_no_update;
CREATE TRIGGER media_no_update BEFORE UPDATE OF id, sha256, path, kind, size, job_id, artifact_id,
    order_id, number, created_at ON media
BEGIN SELECT RAISE(ABORT, 'media: unveränderlich'); END;
CREATE TRIGGER media_tier_raise_only BEFORE UPDATE OF content_tier ON media
    WHEN OLD.content_tier = 'explizit' AND NEW.content_tier IS NOT 'explizit'
BEGIN SELECT RAISE(ABORT, 'media: Inhaltsstufe nur anhebbar'); END;
""",
    15: """
-- Kundenauftrag (V0 §8.4/§8.5, C5/C5a): Angebot aus der Preisliste mit eindeutigem Betrag je
-- Zahlungsweg, Gutscheine (Code nur im Reiter Wallet), Zustellnachricht je Lieferung
CREATE TABLE offers (
    order_id        INTEGER PRIMARY KEY REFERENCES orders(id),
    conversation_id INTEGER NOT NULL REFERENCES channel_conversations(id),
    product         TEXT    NOT NULL,
    hd              INTEGER NOT NULL DEFAULT 0 CHECK (hd IN (0, 1)),
    price_cents     INTEGER NOT NULL CHECK (price_cents > 0),
    expires_at      TEXT    NOT NULL,
    created_at      TEXT    NOT NULL
);
CREATE TABLE offer_amounts (
    order_id  INTEGER NOT NULL REFERENCES offers(order_id),
    method    TEXT    NOT NULL CHECK (method IN ('btc', 'usdt', 'usdc')),
    amount    TEXT    NOT NULL,
    address   TEXT    NOT NULL,
    rate      REAL    NOT NULL,
    rate_ms   INTEGER NOT NULL,
    PRIMARY KEY (order_id, method),
    UNIQUE (method, amount)
);
CREATE TABLE vouchers (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    message_id   INTEGER REFERENCES channel_messages(id),
    code         TEXT    NOT NULL UNIQUE,
    status       TEXT    NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'redeemed', 'rejected')),
    amount_cents INTEGER CHECK (amount_cents IS NULL OR amount_cents > 0),
    decided_at   TEXT,
    created_at   TEXT    NOT NULL
);
ALTER TABLE channel_messages ADD COLUMN delivery_id INTEGER REFERENCES deliveries(id);
""",
    16: """
-- Abschnitte eines langen Videos (V0 §10): je Job und Abschnitt der eingereichte Auftrag, das
-- Video, das letzte Bild (Startbild des nächsten Abschnitts) und die Dauer; Index = Anzahl
-- Abschnitte ist das Zusammensetzen. Nach einem Neustart wird nur der unfertige fortgesetzt.
CREATE TABLE job_segments (
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    idx        INTEGER NOT NULL CHECK (idx >= 0),
    prompt_id  TEXT,
    video      TEXT,
    last_frame TEXT,
    duration_s REAL,
    done_at    TEXT,
    PRIMARY KEY (job_id, idx)
);
""",
    17: """
-- Befehl -> Workflow des Default-Kontakts (V0 §8.1, FL-6); ohne Eintrag gilt der Medien- bzw.
-- (animate) Video-Workflow
CREATE TABLE default_commands (
    command  TEXT PRIMARY KEY
             CHECK (command IN ('clone', 'pose', 'style', 'remix', 'animate', 'edit')),
    workflow TEXT NOT NULL
);
""",
}
# Schritte mit Tabellenneubau: Fremdschlüssel währenddessen aus, danach vollständig geprüft
REBUILDS = {5, 6, 7}
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

    def _backup(self, first_step: int) -> Path:
        """Kopie der Datenbank über die SQLite-Sicherungsschnittstelle vor einer Migration
        (SP0 Schritt 1, BUG-105); erst vollständig geschrieben, dann umbenannt."""
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        target = self.path.with_name(f"{self.path.name}.bak-{stamp}-vor-migration{first_step}")
        n = 1
        while target.exists():
            n += 1
            target = target.with_name(f"{self.path.name}.bak-{stamp}-{n}-vor-migration{first_step}")
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
        backup = None
        if 1 <= pending < SCHEMA_VERSION:  # bestehende Datenbank: vorher sichern
            backup = self._backup(pending + 1)
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

    # ------------------------------------------------------------------ Kunden & Nachrichten

    def customer_for_identity(
        self,
        platform: str,
        account: str,
        platform_user_id: str,
        *,
        handle: str | None = None,
        display_name: str | None = None,
    ) -> tuple[Customer, int, bool]:
        """Kundenakte zu einer Plattform-Absender-ID: vorhanden zurückgeben oder genau einmal mit
        Identität anlegen (Zuordnung nur über die unveränderliche Plattform-ID, nie über Namen).
        Liefert (Kunde, Identitäts-ID, neu angelegt)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT i.id AS identity_id, c.* FROM channel_identities i"
                " JOIN customers c ON c.id = i.customer_id"
                " WHERE i.platform = ? AND i.account = ? AND i.platform_user_id = ?",
                (platform, account, platform_user_id),
            ).fetchone()
            if row is not None:
                if handle:
                    db.execute(
                        "UPDATE channel_identities SET handle = ? WHERE id = ?",
                        (handle, row["identity_id"]),
                    )
                if display_name and not row["display_name"]:  # nie einen gesetzten Namen ersetzen
                    db.execute(
                        "UPDATE customers SET display_name = ? WHERE id = ?",
                        (display_name, row["id"]),
                    )
                    self._event("customer", row["id"], "named")
                    self.bump("customers")
                    return self.customer_by_id(row["id"]), row["identity_id"], False
                return _customer(row), row["identity_id"], False
            ts = now()
            cur = db.execute(
                "INSERT INTO customers (kind, display_name, created_at) VALUES ('customer',?,?)",
                (display_name, ts),
            )
            customer_id = cur.lastrowid
            identity = db.execute(
                "INSERT INTO channel_identities (customer_id, platform, account, platform_user_id,"
                " handle, verified, created_at) VALUES (?,?,?,?,?,1,?)",
                (customer_id, platform, account, platform_user_id, handle, ts),
            ).lastrowid
            customer = self.customer_by_id(customer_id)
            self._event("customer", customer_id, "created", customer_no=customer.customer_no)
            self.bump("customers")
            return customer, identity, True

    def customer_by_id(self, customer_id: int) -> Customer:
        row = self.db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if row is None:
            raise StoreError(f"Kunde {customer_id} unbekannt.")
        return _customer(row)

    def customer(self, customer_no: str) -> Customer:
        row = self.db.execute("SELECT * FROM customers WHERE customer_no = ?", (customer_no,))
        found = row.fetchone()
        if found is None:
            raise StoreError(f"Kunde {customer_no} unbekannt.")
        return _customer(found)

    def conversation(self, identity_id: int, platform_conversation_id: str) -> int:
        """Konversation einer Identität (Telegram-Chat, Instagram-Thread), genau einmal angelegt."""
        with self.tx() as db:
            row = db.execute(
                "SELECT id FROM channel_conversations WHERE identity_id = ?"
                " AND platform_conversation_id = ?",
                (identity_id, platform_conversation_id),
            ).fetchone()
            if row is not None:
                return row[0]
            return db.execute(
                "INSERT INTO channel_conversations (identity_id, platform_conversation_id,"
                " created_at) VALUES (?,?,?)",
                (identity_id, platform_conversation_id, now()),
            ).lastrowid

    def record_inbound(
        self,
        platform: str,
        account: str,
        event_id: str,
        *,
        sender_id: str,
        conversation_id: str,
        platform_message_id: str,
        text: str,
        sent_at: str,
        handle: str | None = None,
        display_name: str | None = None,
        reply_to: str | None = None,
        attachments: list[dict] | None = None,
    ) -> Inbound:
        """Eingang vor der Bestätigung an die Plattform dauerhaft speichern: Ereignis genau
        einmal, Kundenakte/Identität/Konversation, Nachricht – alles in einer Transaktion. Ein
        erneut zugestelltes Ereignis ändert nichts (message_id None)."""
        with self.tx() as db:
            customer, identity, created = self.customer_for_identity(
                platform, account, sender_id, handle=handle, display_name=display_name
            )
            conv = self.conversation(identity, conversation_id)
            fresh = db.execute(
                "INSERT INTO inbound_events (platform, account, event_id, received_at)"
                " VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                (platform, account, event_id, now()),
            ).rowcount
            if not fresh:
                return Inbound(customer, identity, conv, None, created)
            codes: list[str] = []
            if customer.kind != "internal":  # Code nie im Verlauf und nie im KI-Kontext
                text, codes = extract_vouchers(text)
            cur = db.execute(
                "INSERT INTO channel_messages (customer_id, conversation_id, direction,"
                " platform_message_id, reply_to_platform_id, text, attachments, status, sent_at,"
                " created_at) VALUES (?,?,'in',?,?,?,?,'received',?,?)"
                " ON CONFLICT (conversation_id, direction, platform_message_id) DO NOTHING",
                (
                    customer.id,
                    conv,
                    platform_message_id,
                    reply_to,
                    text,
                    json.dumps(attachments or [], ensure_ascii=False),
                    sent_at,
                    now(),
                ),
            )
            if not cur.rowcount:  # gleiche Nachricht über ein anderes Ereignis
                return Inbound(customer, identity, conv, None, created)
            db.execute(
                "UPDATE channel_conversations SET revision = revision + 1 WHERE id = ?", (conv,)
            )
            self._event("message", cur.lastrowid, "added", customer_id=customer.id)
            self.bump("conversations")
            message_id = cur.lastrowid
            if any([self.add_voucher(customer.id, message_id, code) for code in codes]):
                self.add_system_card(conv, "GUTSCHEIN ERHALTEN · im Reiter Wallet prüfen")
            return Inbound(customer, identity, conv, message_id, created)

    def record_external_outgoing(
        self,
        platform: str,
        account: str,
        partner_id: str,
        platform_message_id: str,
        text: str,
        sent_at: str,
        attachments: list[dict] | None = None,
    ) -> tuple[int, int | None]:
        """Ausgehende Nachricht, die nicht aus dem Postausgang stammt (der Betreiber schreibt am
        Handy in Claras Konto, V0 §6.1 Punkt 5): genau einmal gespeichert; liefert
        (Konversation, Nachricht oder None, wenn schon bekannt)."""
        with self.tx() as db:
            customer, identity, _ = self.customer_for_identity(platform, account, partner_id)
            conv = self.conversation(identity, partner_id)
            cur = db.execute(
                "INSERT INTO channel_messages (customer_id, conversation_id, direction,"
                " platform_message_id, text, attachments, status, sent_at, read_at, created_at)"
                " VALUES (?,?,'out',?,?,?,'sent',?,?,?)"
                " ON CONFLICT (conversation_id, direction, platform_message_id) DO NOTHING",
                (
                    customer.id,
                    conv,
                    platform_message_id,
                    text,
                    json.dumps(attachments or [], ensure_ascii=False),
                    sent_at,
                    now(),
                    now(),
                ),
            )
            if not cur.rowcount:
                return conv, None
            db.execute(
                "UPDATE channel_conversations SET revision = revision + 1 WHERE id = ?", (conv,)
            )
            self._event("message", cur.lastrowid, "added", customer_id=customer.id)
            self.bump("conversations")
            return conv, cur.lastrowid

    def add_system_card(
        self,
        conversation_id: int,
        text: str,
        *,
        order_id: int | None = None,
        origin_message_id: int | None = None,
    ) -> int:
        """Systemkarte im Verlauf (z. B. INTERNER AUFTRAG, Rückfrage-Hinweis) – nie gesendet."""
        with self.tx() as db:
            customer = db.execute(
                "SELECT i.customer_id FROM channel_conversations c"
                " JOIN channel_identities i ON i.id = c.identity_id WHERE c.id = ?",
                (conversation_id,),
            ).fetchone()[0]
            ts = now()
            cur = db.execute(
                "INSERT INTO channel_messages (customer_id, conversation_id, direction, text,"
                " status, order_id, origin_message_id, sent_at, read_at, created_at)"
                " VALUES (?,?,'system',?,'sent',?,?,?,?,?)",
                (customer, conversation_id, text, order_id, origin_message_id, ts, ts, ts),
            )
            self._event("message", cur.lastrowid, "added", customer_id=customer)
            self.bump("conversations")
            return cur.lastrowid

    def link_order(self, message_id: int, order_id: int) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE channel_messages SET order_id = ? WHERE id = ?", (order_id, message_id)
            )

    def start_card(self, card_id: int, order_id: int, text: str) -> None:
        """Wartende Kloner-Karte mit dem gestarteten Auftrag verbinden – genau einmal."""
        with self.tx() as db:
            n = db.execute(
                "UPDATE channel_messages SET order_id = ?, text = ? WHERE id = ?"
                " AND direction = 'system' AND origin_message_id IS NOT NULL AND order_id IS NULL",
                (order_id, text, card_id),
            ).rowcount
            if n != 1:
                raise StoreError("Auftrag wurde bereits gestartet.")
            self._event("message", card_id, "started", order_id=order_id)
            self.bump("conversations")

    def conversation_revision(self, conversation_id: int) -> int:
        row = self.db.execute(
            "SELECT revision FROM channel_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row[0] if row else 0

    def message_by_platform_id(self, conversation_id: int, platform_message_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT id FROM channel_messages WHERE conversation_id = ? AND platform_message_id = ?",
            (conversation_id, platform_message_id),
        ).fetchone()
        return self.message(row[0]) if row else None

    def set_attachments(self, message_id: int, attachments: list[dict]) -> None:
        """Anhänge nach dem Sichern (Datei, SHA-256, Status) festhalten."""
        with self.tx() as db:
            db.execute(
                "UPDATE channel_messages SET attachments = ? WHERE id = ?",
                (json.dumps(attachments, ensure_ascii=False), message_id),
            )
            for att in attachments:
                if att.get("status") == "saved" and att.get("path"):
                    db.execute(
                        "INSERT INTO message_files (path, message_id, sha256, size, mime)"
                        " VALUES (?,?,?,?,?) ON CONFLICT (path) DO NOTHING",
                        (att["path"], message_id, att["sha256"], att["size"], att.get("mime", "")),
                    )
            self._event("message", message_id, "updated")
            self.bump("conversations")

    def queue_outbound(
        self,
        customer_id: int,
        conversation_id: int,
        text: str,
        *,
        revision: int,
        request_id: str | None = None,
        attachments: list[dict] | None = None,
        reply_to: str | None = None,
        delivery_id: int | None = None,
    ) -> int:
        """Ausgehende Nachricht in den Postausgang (Status queued). Nur an eine Konversation
        dieses Kunden und nur auf der gesehenen Gesprächsrevision (CAS gegen überholte
        Antworten)."""
        with self.tx() as db:
            conv = db.execute(
                "SELECT c.revision, i.customer_id FROM channel_conversations c"
                " JOIN channel_identities i ON i.id = c.identity_id WHERE c.id = ?",
                (conversation_id,),
            ).fetchone()
            if conv is None or conv["customer_id"] != customer_id:
                raise StoreError("Konversation gehört nicht zu diesem Kunden.")
            if conv["revision"] != revision:
                raise StoreError(
                    "Gespräch wurde inzwischen fortgesetzt – Ansicht ist aktualisiert."
                )
            cur = db.execute(
                "INSERT INTO channel_messages (customer_id, conversation_id, direction, text,"
                " attachments, status, reply_to_platform_id, request_id, delivery_id, sent_at,"
                " created_at) VALUES (?,?,'out',?,?,'queued',?,?,?,?,?)",
                (
                    customer_id,
                    conversation_id,
                    text,
                    json.dumps(attachments or [], ensure_ascii=False),
                    reply_to,
                    request_id,
                    delivery_id,
                    now(),
                    now(),
                ),
            )
            for att in attachments or []:  # gesendete Dateien: im Cockpit wie Eingänge abrufbar
                if att.get("status") == "saved" and att.get("sha256") and att.get("size"):
                    db.execute(
                        "INSERT INTO message_files (path, message_id, sha256, size, mime)"
                        " VALUES (?,?,?,?,?) ON CONFLICT (path) DO NOTHING",
                        (
                            att["path"],
                            cur.lastrowid,
                            att["sha256"],
                            att["size"],
                            att.get("mime", ""),
                        ),
                    )
            db.execute(
                "UPDATE channel_conversations SET revision = revision + 1 WHERE id = ?",
                (conversation_id,),
            )
            self._event("message", cur.lastrowid, "added", customer_id=customer_id)
            self.bump("conversations")
            return cur.lastrowid

    def set_message_status(
        self,
        message_id: int,
        status: str,
        *,
        platform_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE channel_messages SET status = ?, platform_message_id ="
                " coalesce(?, platform_message_id), error = ?, sent_at = CASE WHEN ? = 'sent'"
                " THEN ? ELSE sent_at END WHERE id = ?",
                (status, platform_message_id, error, status, now(), message_id),
            )
            self._event("message", message_id, "status", status=status, error=error)
            self.bump("conversations")
            if status == "sent":  # KI-Hinweis wirklich gesendet: Ereigniskarte (Regel 12 b)
                notice = db.execute(
                    "SELECT c.id FROM channel_identities i JOIN channel_conversations c"
                    " ON c.identity_id = i.id WHERE i.ai_notice_message_id = ?",
                    (message_id,),
                ).fetchone()
                if notice:
                    self.add_system_card(notice[0], "KI-HINWEIS GESENDET")

    def outbox(self, platform: str, account: str) -> list[dict]:
        """Wartende ausgehende Nachrichten eines Kanals in Eingangsreihenfolge."""
        rows = self.db.execute(
            "SELECT m.*, c.platform_conversation_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE m.direction = 'out' AND m.status = 'queued' AND i.platform = ?"
            " AND i.account = ? ORDER BY m.id",
            (platform, account),
        )
        return [dict(r) | {"attachments": json.loads(r["attachments"])} for r in rows]

    def settle_sending(self) -> list[int]:
        """Nach einem Neustart: Nachrichten, deren Versand begonnen hatte, sind „unbekannt“
        (kein blindes Wiederholen – die Plattform kann sie angenommen haben)."""
        rows = [
            r[0]
            for r in self.db.execute("SELECT id FROM channel_messages WHERE status = 'sending'")
        ]
        for message_id in rows:
            self.set_message_status(
                message_id, "unknown", error="Backend während des Versands beendet."
            )
        return rows

    def message(self, message_id: int) -> dict:
        row = self.db.execute(
            "SELECT m.*, c.platform_conversation_id, i.platform, i.account FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Nachricht {message_id} unbekannt.")
        return dict(row) | {"attachments": json.loads(row["attachments"])}

    def message_file_known(self, rel: str) -> bool:
        row = self.db.execute("SELECT 1 FROM message_files WHERE path = ?", (rel,)).fetchone()
        return row is not None

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

    def customers_overview(self, customer_id: int | None = None) -> list[dict]:
        """Kundenliste (F7.2): letzte Nachricht, Kanal, Zeit, ungelesen; Kanäle je Akte."""
        rows = self.db.execute(
            "SELECT c.*, (SELECT group_concat(DISTINCT platform) FROM channel_identities"
            " WHERE customer_id = c.id) AS platforms,"
            " (SELECT group_concat(coalesce(handle, '') || char(31) || platform_user_id, char(30))"
            "  FROM channel_identities WHERE customer_id = c.id) AS handles,"
            " (SELECT count(*) FROM channel_messages WHERE customer_id = c.id"
            "  AND direction = 'in' AND read_at IS NULL) AS unread,"
            " lm.text AS last_text, lm.sent_at AS last_at, li.platform AS last_platform"
            " FROM customers c"
            " LEFT JOIN channel_messages lm ON lm.id = (SELECT max(id) FROM channel_messages"
            "  WHERE customer_id = c.id)"
            " LEFT JOIN channel_conversations lc ON lc.id = lm.conversation_id"
            " LEFT JOIN channel_identities li ON li.id = lc.identity_id"
            " WHERE ? IS NULL OR c.id = ?"
            " ORDER BY c.kind = 'internal' DESC, coalesce(lm.id, 0) DESC, c.id DESC",
            (customer_id, customer_id),
        )
        return [dict(r) for r in rows]

    def conversation_item(self, message_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT m.*, i.platform, i.handle, c.platform_conversation_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        return dict(row) | {"attachments": json.loads(row["attachments"])} if row else None

    def identities(self, customer_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT i.*, c.id AS conversation_id, c.platform_conversation_id, c.revision,"
            " n.status AS ai_notice_status FROM channel_identities i"
            " LEFT JOIN channel_conversations c ON c.identity_id = i.id"
            " LEFT JOIN channel_messages n ON n.id = i.ai_notice_message_id"
            " WHERE i.customer_id = ? ORDER BY i.id",
            (customer_id,),
        )
        return [dict(r) for r in rows]

    def conversation_items(
        self, customer_id: int, before: int, limit: int
    ) -> tuple[list[dict], bool]:
        """Verlauf einer Kundenakte über alle Kanäle (neueste ``limit`` vor ``before``,
        aufsteigend); zweiter Wert: ältere vorhanden."""
        rows = self.db.execute(
            "SELECT m.*, i.platform, i.handle, c.platform_conversation_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE m.customer_id = ? AND (? = 0 OR m.id < ?) ORDER BY m.id DESC LIMIT ?",
            (customer_id, before, before, limit + 1),
        ).fetchall()
        items = [dict(r) | {"attachments": json.loads(r["attachments"])} for r in rows[:limit]]
        return items[::-1], len(rows) > limit

    def mark_read(self, customer_id: int, up_to: int) -> int:
        with self.tx() as db:
            n = db.execute(
                "UPDATE channel_messages SET read_at = ? WHERE customer_id = ? AND direction = 'in'"
                " AND read_at IS NULL AND id <= ?",
                (now(), customer_id, up_to),
            ).rowcount
            if n:
                self._event("customer", customer_id, "read", up_to=up_to)
                self.bump("customers")
            return n

    def message_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Nachrichtenereignisse (neu, Status, Anhänge) mit Cursor > ``after``; jedes Ereignis
        eines Auftrags mit Systemkarte liefert diese Karte erneut (Stufe, Ergebnis, Fehler)."""
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.entity_id AS message_id"
            " FROM events e WHERE e.entity = 'message' AND e.id > ?"
            " UNION ALL"
            " SELECT e.id, e.created_at, m.id FROM events e"
            " JOIN channel_messages m ON m.order_id = e.entity_id AND m.direction = 'system'"
            " WHERE e.entity = 'order' AND e.id > ?"
            " ORDER BY cursor DESC LIMIT ?",
            (after, after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit

    def customer_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.entity_id AS customer_id"
            " FROM events e WHERE e.entity = 'customer' AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit

    # ------------------------------------------------------------------ Inhaltsstufe (Regel 13)

    def media_tier(self, media_id: int) -> str | None:
        row = self.db.execute("SELECT content_tier FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            raise StoreError(f"Medium {media_id} unbekannt.")
        return row[0]

    def raise_content_tier(self, media_id: int) -> None:
        """Inhaltsstufe eines Mediums auf „explizit“ anheben – nie absenken (Regel 13)."""
        with self.tx() as db:
            if self.media_tier(media_id) == "explizit":
                raise StoreError("Medium ist bereits explizit.")
            db.execute("UPDATE media SET content_tier = 'explizit' WHERE id = ?", (media_id,))
            self._event("media", media_id, "tier", content_tier="explizit")
            self.bump("media")

    def backfill_content_tiers(self, workflow_tiers: dict[str, str]) -> int:
        """Erstzuordnung für Jobs/Medien vor Migration 14: Stufe des Workflows (unbekannter
        Workflow = explizit) und höhere Stufe des Ausgangsmediums; Medien erben vom Job."""
        from .media.models import higher_tier

        with self.tx() as db:
            rows = db.execute(
                "SELECT j.id, j.workflow, m.content_tier AS parent_tier, j.parent_media_id"
                " FROM jobs j LEFT JOIN media m ON m.id = j.parent_media_id"
                " WHERE j.content_tier IS NULL ORDER BY j.id"
            ).fetchall()
            for r in rows:
                parent = r["parent_tier"] if r["parent_media_id"] else "standard"
                tier = higher_tier(workflow_tiers.get(r["workflow"]), parent)
                db.execute("UPDATE jobs SET content_tier = ? WHERE id = ?", (tier, r["id"]))
            n = db.execute(
                "UPDATE media SET content_tier = (SELECT content_tier FROM jobs j"
                " WHERE j.id = media.job_id) WHERE content_tier IS NULL AND job_id IS NOT NULL"
            ).rowcount
            return len(rows) + n

    # ------------------------------------------------------------------ Alter und KI-Hinweis

    AGE_MARKS = ("unclear", "under_18", "self_declared_adult")

    def set_age_mark(self, customer_id: int, mark: str) -> None:
        """Altersangabe der Akte (nur Betreiber; Regel 13): unklar | unter 18 | Angabe ≥ 18."""
        if mark not in self.AGE_MARKS:
            raise StoreError(f"Alter: {mark} unbekannt.")
        self.customer_by_id(customer_id)
        with self.tx() as db:
            db.execute("UPDATE customers SET age_mark = ? WHERE id = ?", (mark, customer_id))
            self._event("customer", customer_id, "age", age_mark=mark)
            self.bump("customers")

    def queue_ai_notice(self, customer_id: int, identity_id: int, text: str) -> int:
        """KI-Hinweis genau einmal je Kanalidentität in den Postausgang (Regel 12 b)."""
        with self.tx() as db:
            ident = db.execute(
                "SELECT i.ai_notice_message_id, c.id AS conversation_id, c.revision"
                " FROM channel_identities i JOIN channel_conversations c ON c.identity_id = i.id"
                " WHERE i.id = ? AND i.customer_id = ?",
                (identity_id, customer_id),
            ).fetchone()
            if ident is None:
                raise StoreError("Kanalidentität gehört nicht zu dieser Kundenakte.")
            if ident["ai_notice_message_id"]:
                raise StoreError("KI-Hinweis für diese Kanalidentität bereits ausgelöst.")
            message_id = self.queue_outbound(
                customer_id, ident["conversation_id"], text, revision=ident["revision"]
            )
            db.execute(
                "UPDATE channel_identities SET ai_notice_message_id = ? WHERE id = ?",
                (message_id, identity_id),
            )
            return message_id

    # ------------------------------------------------------------------ Angebote (C5/C5a)

    def create_offer(
        self,
        customer_id: int,
        conversation_id: int,
        product: str,
        hd: bool,
        price_cents: int,
        expires_at: str,
        amounts: dict[str, tuple[str, str, float, int]],
    ) -> Order:
        """Kundenauftrag mit Angebot (Status offered) und eindeutigen Beträgen je Zahlungsweg
        (method -> (Dezimaltext, genannte Adresse, Kurs, Kurszeit)). Alles in einer Transaktion."""
        with self.tx() as db:
            label = f"{product} + HD" if hd else product
            order = self.create_order(customer_id, "image", label)
            self.set_offer(order.order_no, label, price_cents, "EUR")
            db.execute(
                "INSERT INTO offers (order_id, conversation_id, product, hd, price_cents,"
                " expires_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (order.id, conversation_id, product, int(hd), price_cents, expires_at, now()),
            )
            for method, (amount, address, rate, rate_ms) in amounts.items():
                db.execute(
                    "INSERT INTO offer_amounts (order_id, method, amount, address, rate, rate_ms)"
                    " VALUES (?,?,?,?,?,?)",
                    (order.id, method, amount, address, rate, rate_ms),
                )
            return self.order(order.order_no)

    def amount_taken(self, method: str, amount: str) -> bool:
        return bool(
            self.db.execute(
                "SELECT 1 FROM offer_amounts WHERE method = ? AND amount = ?", (method, amount)
            ).fetchone()
        )

    def offer(self, order_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM offers WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return None
        amounts = self.db.execute(
            "SELECT method, amount FROM offer_amounts WHERE order_id = ? ORDER BY method",
            (order_id,),
        )
        return dict(row) | {"amounts": {r["method"]: r["amount"] for r in amounts}}

    def offer_amount_rows(self, order_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM offer_amounts WHERE order_id = ? ORDER BY method", (order_id,)
        )
        return [dict(r) for r in rows]

    def conversation_platform(self, conversation_id: int) -> str:
        row = self.db.execute(
            "SELECT i.platform FROM channel_conversations c JOIN channel_identities i"
            " ON i.id = c.identity_id WHERE c.id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Konversation {conversation_id} unbekannt.")
        return row[0]

    def customer_orders(self, customer_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT o.*, f.product, f.hd, f.price_cents, f.expires_at, f.conversation_id"
            " FROM orders o LEFT JOIN offers f ON f.order_id = o.id"
            " WHERE o.customer_id = ? ORDER BY o.id DESC",
            (customer_id,),
        )
        return [dict(r) for r in rows]

    def assign_inflow(self, payment_id: int, order_no: str, by: str) -> None:
        """Eingang einem Kundenauftrag zuordnen (automatisch bei passendem Angebot oder per
        Betreiber, Befehl 41): Zahlung im Gate (payments) erfassen, Auftrag auf paid, Karte."""
        with self.tx() as db:
            inflow = self.payment(payment_id)
            if inflow["status"] != "unassigned":
                raise StoreError("Eingang ist noch nicht bestätigt oder schon zugeordnet.")
            order = self.order(order_no)
            if order.source != "customer" or order.status not in ("offered", "accepted"):
                raise StoreError(f"{order_no}: kein offenes Angebot ({order.status}).")
            if reason := _uncovered(inflow, order.price_amount or 0, self.offer(order.id)):
                raise StoreError(
                    f"Eingang deckt den Angebotspreis nicht ({reason}) – bleibt nicht zugeordnet."
                )
            if order.status == "offered":
                self.transition(order_no, "accepted", by=by)
            self.record_payment(
                order_no,
                inflow["method"],
                f"{inflow['txid']}:{inflow['position']}",
                order.price_amount,
                order.currency,
            )  # setzt den Auftrag auf paid
            db.execute(
                "UPDATE payment_inflows SET status = 'assigned', order_id = ?, customer_id = ?,"
                " updated_at = ? WHERE id = ?",
                (order.id, order.customer_id, now(), payment_id),
            )
            self._event("payment", payment_id, "assigned", order_no=order_no, by=by)
            self.bump("payments")
            offer = self.offer(order.id)
            if offer:
                eur = f"{order.price_amount / 100:.2f}".replace(".", ",")
                way = (
                    "Amazon-Gutschein"
                    if inflow["method"] == "amazon"
                    else f"{inflow['asset']} {inflow['amount']}"
                )
                # schlichte Ereigniskarte; die Auftragskarte ist die Karte ANGEBOT
                self.add_system_card(
                    offer["conversation_id"], f"ZAHLUNG BESTÄTIGT · {way} · {eur} € · {order_no}"
                )

    def _match_offer(self, db, payment_id: int) -> None:
        """Bestätigter Chain-Eingang: genau passender Betrag eines noch gültigen Angebots."""
        inflow = db.execute("SELECT * FROM payment_inflows WHERE id = ?", (payment_id,)).fetchone()
        hit = db.execute(
            "SELECT o.order_no FROM offer_amounts a JOIN offers f ON f.order_id = a.order_id"
            " JOIN orders o ON o.id = a.order_id WHERE a.method = ? AND a.amount = ?"
            " AND f.created_at <= ? AND f.expires_at >= ? AND o.status IN ('offered', 'accepted')",
            (inflow["method"], inflow["amount"], inflow["detected_at"], inflow["detected_at"]),
        ).fetchone()
        if hit:
            self.assign_inflow(payment_id, hit["order_no"], "automatisch")

    def open_offers(self) -> list[dict]:
        """Angebote, die noch auf Zahlung warten (Ziele für Befehl 41), neueste zuerst."""
        rows = self.db.execute(
            "SELECT o.id, o.order_no, o.customer_id, c.customer_no, c.display_name, f.product,"
            " f.hd, f.price_cents, f.expires_at FROM orders o JOIN offers f ON f.order_id = o.id"
            " JOIN customers c ON c.id = o.customer_id WHERE o.status IN ('offered', 'accepted')"
            " ORDER BY o.id DESC"
        ).fetchall()
        return [dict(r) | {"amounts": self.offer(r["id"])["amounts"]} for r in rows]

    # ------------------------------------------------------------------ Zustellung (C5)

    def deliveries(self, order_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT d.*, m.id AS message_id, m.status AS message_status, m.error AS message_error,"
            " m.attachments FROM deliveries d"
            " LEFT JOIN channel_messages m ON m.delivery_id = d.id WHERE d.order_id = ?"
            " ORDER BY d.id",
            (order_id,),
        )
        return [dict(r) for r in rows]

    def delivery(self, delivery_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT d.*, o.order_no, c.customer_no FROM deliveries d"
            " JOIN orders o ON o.id = d.order_id JOIN customers c ON c.id = d.customer_id"
            " WHERE d.id = ?",
            (delivery_id,),
        ).fetchone()
        return dict(row) if row else None

    def delivery_by_message(self, message_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT d.* FROM deliveries d JOIN channel_messages m ON m.delivery_id = d.id"
            " WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        return dict(row) if row else None

    def fail_delivery(self, delivery_id: int, error: str) -> bool:
        """Endgültig fehlgeschlagene Zustellung (Plattform hat abgelehnt) – danach ist Befehl 47
        möglich. Eine ungeklärte (unknown) bleibt offen."""
        with self.tx() as db:
            n = db.execute(
                "UPDATE deliveries SET status = 'failed' WHERE id = ? AND status = 'pending'",
                (delivery_id,),
            ).rowcount
            if n:
                order_id = db.execute(
                    "SELECT order_id FROM deliveries WHERE id = ?", (delivery_id,)
                ).fetchone()[0]
                self._event("delivery", delivery_id, "failed", error=error)
                # Auftragsereignis: die Auftragskarte im Verlauf zeigt den neuen Zustellstand
                self._event("order", order_id, "delivery", status="failed", delivery=delivery_id)
                self.bump("orders")
            return bool(n)

    def pending_sent_deliveries(self) -> list[tuple[int, str]]:
        """Abgleich nach Neustart: Nachricht gesendet, Zustellung noch offen."""
        rows = self.db.execute(
            "SELECT d.id, m.platform_message_id FROM deliveries d JOIN channel_messages m"
            " ON m.delivery_id = d.id WHERE d.status = 'pending' AND m.status = 'sent'"
        )
        return [(r[0], r[1] or "") for r in rows]

    def set_order_kind(self, order_no: str, kind: str) -> None:
        if kind not in ORDER_KINDS:
            raise StoreError(f"Auftragstyp {kind!r} unbekannt.")
        with self.tx() as db:
            db.execute("UPDATE orders SET kind = ? WHERE order_no = ?", (kind, order_no))

    # ------------------------------------------------------------------ Gutscheine (C5a)

    def add_voucher(self, customer_id: int, message_id: int | None, code: str) -> int | None:
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO vouchers (customer_id, message_id, code, created_at)"
                " VALUES (?,?,?,?) ON CONFLICT (code) DO NOTHING",
                (customer_id, message_id, code, now()),
            )
            if not cur.rowcount:
                return None
            self._event("voucher", cur.lastrowid, "received", customer_id=customer_id)
            self.bump("payments")
            return cur.lastrowid

    def vouchers(self, decided_limit: int) -> list[dict]:
        """Offene Gutscheine und die zuletzt entschiedenen (Reiter Wallet)."""
        rows = self.db.execute(
            "SELECT * FROM (SELECT v.*, c.customer_no, c.display_name FROM vouchers v"
            " JOIN customers c ON c.id = v.customer_id WHERE v.status = 'pending'"
            " UNION ALL SELECT * FROM (SELECT v.*, c.customer_no, c.display_name FROM vouchers v"
            " JOIN customers c ON c.id = v.customer_id WHERE v.status != 'pending'"
            " ORDER BY v.id DESC LIMIT ?)) ORDER BY id DESC",
            (decided_limit,),
        )
        return [dict(r) for r in rows]

    def reject_voucher(self, voucher_id: int) -> None:
        with self.tx() as db:
            n = db.execute(
                "UPDATE vouchers SET status = 'rejected', decided_at = ? WHERE id = ?"
                " AND status = 'pending'",
                (now(), voucher_id),
            ).rowcount
            if not n:
                raise StoreError("Gutschein unbekannt oder schon entschieden.")
            self._event("voucher", voucher_id, "rejected")
            self.bump("payments")

    def redeem_voucher(self, voucher_id: int, amount_cents: int) -> int:
        """Betreiber hat den Gutschein bei Amazon eingelöst und trägt den Betrag ein (Befehl 42):
        erst dann ein bestätigter Eingang; passt ein offenes Angebot der Akte, wird zugeordnet."""
        if amount_cents <= 0:
            raise StoreError("Eingelöster Betrag muss positiv sein.")
        with self.tx() as db:
            v = db.execute("SELECT * FROM vouchers WHERE id = ?", (voucher_id,)).fetchone()
            if v is None or v["status"] != "pending":
                raise StoreError("Gutschein unbekannt oder schon entschieden.")
            ts = now()
            db.execute(
                "UPDATE vouchers SET status = 'redeemed', amount_cents = ?, decided_at = ?"
                " WHERE id = ?",
                (amount_cents, ts, voucher_id),
            )
            amount = f"{amount_cents / 100:.2f}"
            cur = db.execute(
                "INSERT INTO payment_inflows (method, network, asset, amount, txid, position,"
                " confirmations, required, status, eur, rate, rate_ms, customer_id, detected_at,"
                " updated_at) VALUES ('amazon','amazon','EUR',?,?,0,1,1,'unassigned',?,1,?,?,?,?)",
                (amount, f"voucher:{voucher_id}", amount_cents / 100,
                 int(datetime.now(UTC).timestamp() * 1000), v["customer_id"], ts, ts),
            )  # fmt: skip
            payment_id = cur.lastrowid
            self._event("payment", payment_id, "detected", status="unassigned")
            self._event("voucher", voucher_id, "redeemed", amount_cents=amount_cents)
            self.bump("payments")
            open_order = db.execute(
                "SELECT order_no FROM orders WHERE customer_id = ? AND source = 'customer'"
                " AND status IN ('offered', 'accepted') AND price_amount <= ? ORDER BY id DESC",
                (v["customer_id"], amount_cents),
            ).fetchone()
            if open_order:
                self.assign_inflow(payment_id, open_order["order_no"], "Gutschein")
            return payment_id

    # ------------------------------------------------------------------ Zahlungen (C5a)

    def upsert_payment(
        self,
        *,
        method: str,
        network: str,
        asset: str,
        amount: str,
        txid: str,
        position: int,
        block: int | None,
        confirmations: int,
        required: int,
        eur: float | None,
        rate: float | None,
        rate_ms: int | None,
    ) -> bool:
        """Eingang genau einmal anlegen bzw. Block/Bestätigungen fortschreiben; liefert True bei
        einer Änderung. Ausreichend bestätigt ohne passendes Angebot = nicht zugeordnet."""
        with self.tx() as db:
            row = db.execute(
                "SELECT id, block, confirmations, status FROM payment_inflows"
                " WHERE method = ? AND txid = ? AND position = ?",
                (method, txid, position),
            ).fetchone()
            ts = now()
            if row is None:
                status = "unassigned" if confirmations >= required else "detected"
                cur = db.execute(
                    "INSERT INTO payment_inflows (method, network, asset, amount, txid, position,"
                    " block, confirmations, required, status, eur, rate, rate_ms, detected_at,"
                    " updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (method, network, asset, amount, txid, position, block, confirmations,
                     required, status, eur, rate, rate_ms, ts, ts),
                )  # fmt: skip
                self._event("payment", cur.lastrowid, "detected", status=status)
                self.bump("payments")
                if status == "unassigned":
                    self._match_offer(db, cur.lastrowid)
                return True
            if row["status"] != "detected":
                return False  # bestätigt: unveränderlich (Reorg-Schutz über die Bestätigungszahl)
            return self._advance(db, row["id"], block, confirmations, required)

    def _advance(self, db, payment_id: int, block, confirmations: int, required: int) -> bool:
        row = db.execute(
            "SELECT block, confirmations, status FROM payment_inflows WHERE id = ?", (payment_id,)
        ).fetchone()
        if row["status"] != "detected":
            return False  # bestätigt: unveränderlich (keine Ereignisse je Runde)
        status = "unassigned" if confirmations >= required else "detected"
        if (row["block"], row["confirmations"], status) == (block, confirmations, "detected"):
            return False
        db.execute(
            "UPDATE payment_inflows SET block = coalesce(?, block), confirmations = ?, status = ?,"
            " updated_at = ? WHERE id = ?",
            (block, confirmations, status, now(), payment_id),
        )
        self._event("payment", payment_id, "status", status=status, confirmations=confirmations)
        self.bump("payments")
        if status == "unassigned":
            self._match_offer(db, payment_id)
        return True

    def unconfirmed_payments(self, network: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM payment_inflows WHERE network = ? AND status = 'detected'"
            " AND block IS NOT NULL",
            (network,),
        )
        return [dict(r) for r in rows]

    def update_confirmations(self, payment_id: int, confirmations: int, required: int) -> bool:
        with self.tx() as db:
            return self._advance(db, payment_id, None, confirmations, required)

    def payment(self, payment_id: int) -> dict:
        row = self.db.execute(
            "SELECT p.*, o.order_no, c.customer_no FROM payment_inflows p"
            " LEFT JOIN orders o ON o.id = p.order_id LEFT JOIN customers c ON c.id = p.customer_id"
            " WHERE p.id = ?",
            (payment_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Zahlung {payment_id} unbekannt.")
        return dict(row)

    _PAYMENT_FILTER = {
        "all": "1",
        "open": "p.status = 'detected'",
        "confirmed": "p.status IN ('confirmed', 'assigned')",
        "unassigned": "p.status = 'unassigned'",
    }

    def payment_page(self, before: int, limit: int, kind: str) -> tuple[list[dict], bool]:
        where = self._PAYMENT_FILTER.get(kind)
        if where is None:
            raise StoreError(f"Filter {kind} unbekannt.")
        rows = self.db.execute(
            "SELECT p.*, o.order_no, c.customer_no FROM payment_inflows p"
            " LEFT JOIN orders o ON o.id = p.order_id LEFT JOIN customers c ON c.id = p.customer_id"
            f" WHERE {where} AND (? = 0 OR p.id < ?) ORDER BY p.id DESC LIMIT ?",
            (before, before, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]], len(rows) > limit

    def payments_of_month(self, month: str) -> list[dict]:
        """Steuer-Monatsliste (V0 §8.5 Punkt 7): alle Eingänge eines Monats (UTC), aufsteigend."""
        rows = self.db.execute(
            "SELECT p.*, o.order_no, c.customer_no FROM payment_inflows p"
            " LEFT JOIN orders o ON o.id = p.order_id LEFT JOIN customers c ON c.id = p.customer_id"
            " WHERE substr(p.detected_at, 1, 7) = ? ORDER BY p.id",
            (month,),
        )
        return [dict(r) for r in rows]

    def payment_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.entity_id AS payment_id"
            " FROM events e WHERE e.entity = 'payment' AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit

    # ------------------------------------------------------------------ Vorlagen (C1)

    def add_reference(self, path: str, sha256: str, kind: str, source: str) -> tuple[int, bool]:
        """Vorlage genau einmal je Inhalt; liefert (ID, neu angelegt)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT id FROM reference_files WHERE sha256 = ?", (sha256,)
            ).fetchone()
            if row:
                return row[0], False
            cur = db.execute(
                "INSERT INTO reference_files (sha256, path, kind, source, created_at)"
                " VALUES (?,?,?,?,?)",
                (sha256, path, kind, source, now()),
            )
            self._event("reference", cur.lastrowid, "added")
            self.bump("references")
            return cur.lastrowid, True

    def reference(self, reference_id: int) -> dict:
        row = self.db.execute(
            "SELECT * FROM reference_files WHERE id = ?", (reference_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"Vorlage {reference_id} unbekannt.")
        return dict(row)

    def reference_page(self, before: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT * FROM reference_files WHERE (? = 0 OR id < ?) ORDER BY id DESC LIMIT ?",
            (before, before, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]], len(rows) > limit

    def reference_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.entity_id AS reference_id"
            " FROM events e WHERE e.entity = 'reference' AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit

    # ------------------------------------------------------------------ Influencerinnen (C5)

    def influencers(self) -> list[dict]:
        out = []
        for row in self.db.execute("SELECT * FROM influencers ORDER BY id"):
            prices = self.db.execute(
                "SELECT product, price_cents, hd_surcharge_cents FROM influencer_prices"
                " WHERE influencer_id = ? ORDER BY position",
                (row["id"],),
            )
            out.append(dict(row) | {"prices": [dict(p) for p in prices]})
        return out

    def save_influencer(
        self,
        influencer_id: int,
        revision: int,
        name: str,
        character_id: int | None,
        persona: str,
        ai_notice: str,
        prices: list[dict],
    ) -> int:
        """Profil anlegen (``influencer_id`` 0) oder ändern (CAS auf die Revision); die Preisliste
        wird in derselben Transaktion vollständig ersetzt. Liefert die Profil-ID."""
        name = name.strip()
        if not name:
            raise StoreError("Name der Influencerin fehlt.")
        with self.tx() as db:
            ts = now()
            if influencer_id == 0:
                influencer_id = db.execute(
                    "INSERT INTO influencers (name, character_id, persona, ai_notice, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?)",
                    (name, character_id, persona, ai_notice, ts, ts),
                ).lastrowid
            else:
                n = db.execute(
                    "UPDATE influencers SET name = ?, character_id = ?, persona = ?,"
                    " ai_notice = ?, revision = revision + 1, updated_at = ?"
                    " WHERE id = ? AND revision = ?",
                    (name, character_id, persona, ai_notice, ts, influencer_id, revision),
                ).rowcount
                if n != 1:
                    raise StoreError("Profil wurde inzwischen geändert – Ansicht ist aktuell.")
                db.execute(
                    "DELETE FROM influencer_prices WHERE influencer_id = ?", (influencer_id,)
                )
            for pos, item in enumerate(prices):
                db.execute(
                    "INSERT INTO influencer_prices (influencer_id, position, product, price_cents,"
                    " hd_surcharge_cents) VALUES (?,?,?,?,?)",
                    (influencer_id, pos, item["product"].strip(), item["price_cents"],
                     item["hd_surcharge_cents"]),
                )  # fmt: skip
            self._event("influencer", influencer_id, "saved", name=name)
            self.bump("influencers")
            return influencer_id

    # ------------------------------------------------------------------ Charakterprofile

    def characters(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM characters ORDER BY id")]

    def character(self, character_id: int) -> dict:
        row = self.db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
        if row is None:
            raise StoreError(f"Charakter {character_id} unbekannt.")
        return dict(row)

    def save_character(self, character_id: int, revision: int, name: str, photos_dir: str) -> dict:
        """Profil anlegen (``character_id`` 0: eigener Ordner ``local/characters/<id>``) oder
        Name/Trainingsdatenordner ändern (CAS auf die Revision)."""
        name = name.strip()
        if not name:
            raise StoreError("Name des Charakters fehlt.")
        with self.tx() as db:
            ts = now()
            if character_id == 0:
                new_id = db.execute("SELECT coalesce(max(id), 0) + 1 FROM characters").fetchone()[0]
                data_dir = f"local/characters/{new_id}"
                db.execute(
                    "INSERT INTO characters (id, name, data_dir, photos_dir, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?)",
                    (new_id, name, data_dir, photos_dir or f"{data_dir}/photos", ts, ts),
                )
                character_id = new_id
            else:
                current = self.character(character_id)
                if current["revision"] != revision:
                    raise StoreError("Charakter wurde inzwischen geändert – Ansicht ist aktuell.")
                db.execute(
                    "UPDATE characters SET name = ?, photos_dir = ?, revision = revision + 1,"
                    " updated_at = ? WHERE id = ?",
                    (name, photos_dir or current["photos_dir"], ts, character_id),
                )
            self._event("character", character_id, "saved", name=name)
            return self.character(character_id)

    # ------------------------------------------------------------------ Default-Kontakt

    def _move_identity(self, identity_id: int, old: int, new: int) -> None:
        """Identität samt Verlauf einer anderen Akte zuordnen (ausdrückliche Betreiberzuordnung,
        z. B. eigene Telegram-ID als Default-Absender). Eine dadurch leere Akte ohne Aufträge
        entfällt; Akten mit Aufträgen bleiben unangetastet."""
        db = self.db
        if db.execute("SELECT 1 FROM orders WHERE customer_id = ?", (old,)).fetchone():
            raise StoreError("Diese Plattform-ID gehört zu einer Kundenakte mit Aufträgen.")
        db.execute("UPDATE channel_identities SET customer_id = ? WHERE id = ?", (new, identity_id))
        db.execute(
            "UPDATE channel_messages SET customer_id = ? WHERE conversation_id IN"
            " (SELECT id FROM channel_conversations WHERE identity_id = ?)",
            (new, identity_id),
        )
        if not db.execute(
            "SELECT 1 FROM channel_identities WHERE customer_id = ?", (old,)
        ).fetchone():
            db.execute("DELETE FROM customers WHERE id = ?", (old,))
            self._event("customer", old, "removed", merged_into=new)

    def default_contact(self) -> dict:
        """Interner Kontakt Default (genau einer, beim ersten Zugriff angelegt)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT d.*, c.customer_no FROM default_contact d"
                " JOIN customers c ON c.id = d.customer_id"
            ).fetchone()
            if row is None:
                ts = now()
                cid = db.execute(
                    "INSERT INTO customers (kind, display_name, created_at)"
                    " VALUES ('internal', 'Default', ?)",
                    (ts,),
                ).lastrowid
                db.execute(
                    "INSERT INTO default_contact (customer_id, updated_at) VALUES (?,?)", (cid, ts)
                )
                self._event("customer", cid, "created", internal=True)
                self.bump("customers")
                row = db.execute(
                    "SELECT d.*, c.customer_no FROM default_contact d"
                    " JOIN customers c ON c.id = d.customer_id"
                ).fetchone()
            ids = {
                r["platform"]: r["platform_user_id"]
                for r in db.execute(
                    "SELECT platform, platform_user_id FROM channel_identities"
                    " WHERE customer_id = ?",
                    (row["customer_id"],),
                )
            }
            commands = dict(db.execute("SELECT command, workflow FROM default_commands"))
            return dict(row) | {"sender_ids": ids, "command_workflows": commands}

    def update_default_contact(
        self, revision: int, fields: dict, sender_ids: dict, commands: dict | None = None
    ) -> dict:
        """Operator-Felder speichern (CAS auf die Revision); Absender-IDs sind Identitäten des
        internen Kontakts je Plattform (Konto = Kanal der Influencerin)."""
        allowed = {
            "process_commands",
            "auto_orders",
            "approval_mode",
            "influencer",
            "media_workflow",
            "video_workflow",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"Unbekannte Felder: {sorted(unknown)}")
        with self.tx() as db:
            current = self.default_contact()
            if current["revision"] != revision:
                raise StoreError(
                    "Default-Kontakt wurde inzwischen geändert – Ansicht ist aktualisiert."
                )
            if fields:
                cols = ", ".join(f"{k} = ?" for k in fields)
                db.execute(
                    f"UPDATE default_contact SET {cols}, revision = revision + 1, updated_at = ?",
                    (*fields.values(), now()),
                )
            else:
                db.execute(
                    "UPDATE default_contact SET revision = revision + 1, updated_at = ?", (now(),)
                )
            if commands is not None:  # vollständige Zuordnung ersetzt die bisherige
                db.execute("DELETE FROM default_commands")
                db.executemany(
                    "INSERT INTO default_commands (command, workflow) VALUES (?,?)",
                    [(c, w) for c, w in commands.items() if w],
                )
            cid = current["customer_id"]
            for (platform, account), sender in sender_ids.items():
                db.execute(
                    "DELETE FROM channel_identities WHERE customer_id = ? AND platform = ?"
                    " AND NOT EXISTS (SELECT 1 FROM channel_conversations WHERE identity_id ="
                    " channel_identities.id)",
                    (cid, platform),
                )
                if sender:
                    taken = db.execute(
                        "SELECT id, customer_id FROM channel_identities WHERE platform = ? AND"
                        " account = ? AND platform_user_id = ?",
                        (platform, account, sender),
                    ).fetchone()
                    if taken and taken["customer_id"] != cid:
                        self._move_identity(taken["id"], taken["customer_id"], cid)
                    if not taken:
                        db.execute(
                            "INSERT INTO channel_identities (customer_id, platform, account,"
                            " platform_user_id, verified, created_at) VALUES (?,?,?,?,0,?)",
                            (cid, platform, account, sender, now()),
                        )
            self._event("customer", cid, "updated", default=True)
            self.bump("customers")
            return self.default_contact()

    # ------------------------------------------------------------------ Aufträge

    def order(self, order_no: str) -> Order:
        row = self.db.execute(
            "SELECT o.*, c.customer_no FROM orders o LEFT JOIN customers c ON c.id = o.customer_id "
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

    # ------------------------------------------------------------------ Aufträge mit Stufen

    def create_production_order(self, source: str, kind: str, request: str) -> Order:
        """Auftrag ohne Kunden (Betreiber, Kloner) direkt in Produktion (V0 §4.3)."""
        if source not in ORDER_SOURCES or source == "customer":
            raise StoreError(f"Auftragsquelle {source!r}: hier nur Betreiber oder Kloner.")
        if kind not in ORDER_KINDS:
            raise StoreError(f"Auftragstyp {kind!r} unbekannt (erlaubt: {ORDER_KINDS}).")
        with self.tx() as db:
            ts = now()
            cur = db.execute(
                "INSERT INTO orders (source, kind, request, status, created_at, updated_at)"
                " VALUES (?,?,?,'producing',?,?)",
                (source, kind, request, ts, ts),
            )
            no = db.execute("SELECT order_no FROM orders WHERE id = ?", (cur.lastrowid,))
            order = self.order(no.fetchone()[0])
            self._event(
                "order", order.id, "created", order_no=order.order_no, kind=kind, source=source
            )
            self.bump("orders")
            return order

    def order_by_id(self, order_id: int) -> Order:
        row = self.db.execute("SELECT order_no FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise StoreError(f"Auftrag {order_id} unbekannt.")
        return self.order(row[0])

    def add_stage(self, order_id: int, kind: str, workflow: str, params: dict, count: int) -> Stage:
        """Nächste Stufe eines Auftrags (läuft sofort)."""
        if kind not in STAGE_KINDS:
            raise StoreError(f"Stufenart {kind!r} unbekannt (erlaubt: {STAGE_KINDS}).")
        with self.tx() as db:
            seq = db.execute(
                "SELECT coalesce(max(seq), 0) + 1 FROM order_stages WHERE order_id = ?", (order_id,)
            ).fetchone()[0]
            ts = now()
            cur = db.execute(
                "INSERT INTO order_stages (order_id, seq, kind, status, workflow, params, count,"
                " created_at, updated_at) VALUES (?,?,?,'running',?,?,?,?,?)",
                (
                    order_id,
                    seq,
                    kind,
                    workflow,
                    json.dumps(params, ensure_ascii=False),
                    count,
                    ts,
                    ts,
                ),
            )
            self._event("order", order_id, "stage", seq=seq, kind=kind, status="running")
            self.bump("orders")
            return self.stage(cur.lastrowid)

    def stage(self, stage_id: int) -> Stage:
        row = self.db.execute("SELECT * FROM order_stages WHERE id = ?", (stage_id,)).fetchone()
        if row is None:
            raise StoreError(f"Stufe {stage_id} unbekannt.")
        return _stage(row)

    def stages(self, order_id: int) -> list[Stage]:
        rows = self.db.execute(
            "SELECT * FROM order_stages WHERE order_id = ? ORDER BY seq", (order_id,)
        )
        return [_stage(r) for r in rows]

    def set_stage(
        self,
        stage_id: int,
        status: str,
        *,
        selected_media_id: int | None = None,
        error: str | None = None,
        retry: bool = False,
    ) -> Stage:
        """Statuswechsel einer Stufe mit Journal-Ereignis (``retry``: weiterer Versuch)."""
        with self.tx() as db:
            stage = self.stage(stage_id)
            db.execute(
                "UPDATE order_stages SET status = ?, selected_media_id = coalesce(?,"
                " selected_media_id), error = ?, attempts = attempts + ?, updated_at = ?"
                " WHERE id = ?",
                (status, selected_media_id, error, int(retry), now(), stage_id),
            )
            self._event(
                "order",
                stage.order_id,
                "stage",
                seq=stage.seq,
                kind=stage.kind,
                status=status,
                detail=error or (f"Medium {selected_media_id}" if selected_media_id else ""),
            )
            self.bump("orders")
            return self.stage(stage_id)

    def stage_jobs(self, stage_id: int) -> list[dict]:
        """Jobs einer Stufe mit ihrem ersten Galerie-Medium (Kandidat)."""
        rows = self.db.execute(
            "SELECT j.id, j.status, j.error, j.seeds, m.id AS media_id, m.path, m.content_tier"
            " FROM jobs j"
            " LEFT JOIN media m ON m.id = (SELECT min(id) FROM media WHERE job_id = j.id)"
            " WHERE j.stage_id = ? ORDER BY j.id",
            (stage_id,),
        )
        return [dict(r) | {"seeds": json.loads(r["seeds"])} for r in rows]

    def active_orders(self, status: str = "producing") -> list[Order]:
        """Aufträge in Produktion (Stufen laufen oder warten auf den Betreiber); ``paid``: bezahlte
        Kundenaufträge, die auf die Produktion warten."""
        rows = self.db.execute(
            "SELECT order_no FROM orders WHERE status = ? ORDER BY id", (status,)
        )
        return [self.order(r[0]) for r in rows]

    def order_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Auftragsereignisse aus dem Journal mit Cursor > ``after`` (neueste ``limit``)."""
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.event, e.data, o.order_no,"
            " o.status FROM events e JOIN orders o ON o.id = e.entity_id"
            " WHERE e.entity = 'order' AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) | {"data": json.loads(r["data"])} for r in rows[:limit]]
        return recent[::-1], len(rows) > limit

    def transition(self, order_no: str, new_status: str, **data: object) -> Order:
        with self.tx() as db:
            order = self.order(order_no)
            allowed = TRANSITIONS if order.source == "customer" else OPERATOR_TRANSITIONS
            if new_status not in allowed.get(order.status, set()):
                raise StoreError(
                    f"{order_no}: Übergang {order.status} -> {new_status} nicht erlaubt."
                )
            db.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now(), order.id),
            )
            self._event("order", order.id, "status", old=order.status, new=new_status, **data)
            self.bump("orders")
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
            # eigene Ereignisart: "payment" sind die Eingänge im Reiter Wallet (payment_events)
            self._event(
                "gate_payment", cur.lastrowid, "confirmed", order_no=order_no, amount=amount
            )
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
            self._event("gate_payment", row["id"], "refunded")
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
        stage_id: int | None = None,
        content_tier: str | None = None,
    ) -> int:
        """Job anlegen; ``order_no=None`` für Renderungen ohne Kundenbezug (Evaluation).
        ``command``: auslösender Befehl (``record_command``-Argumente) – Job und Befehlsjournal
        entstehen in EINEM Commit, damit eine Wiederholung nie einen zweiten Job erzeugt."""
        with self.tx() as db:
            order_id = self.order(order_no).id if order_no else None
            if (
                order_id is None and stage_id is not None
            ):  # bugs_v1 BUG-006: Kundenauftrag ab Anlage
                row = db.execute(
                    "SELECT o.id FROM order_stages s JOIN orders o ON o.id = s.order_id"
                    " WHERE s.id = ? AND o.source = 'customer'",
                    (stage_id,),
                ).fetchone()
                order_id = row[0] if row else None
            ts = now()
            cur = db.execute(
                "INSERT INTO jobs (order_id, engine, workflow, prompt, params, seeds, created_at,"
                " updated_at, parent_media_id, request_id, stage_id, content_tier)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    stage_id,
                    content_tier,
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

    def job_segments(self, job_id: int) -> dict[int, dict]:
        rows = self.db.execute("SELECT * FROM job_segments WHERE job_id = ?", (job_id,))
        return {r["idx"]: dict(r) for r in rows}

    def copy_segments(self, source_job: int, target_job: int) -> int:
        """Fertige Abschnitte eines gescheiterten Jobs in seinen Wiederholungs-Job übernehmen
        (gleiche Parameter: dieselbe Fortsetzung, kein erneutes Rendern). Liefert die Anzahl."""
        with self.tx() as db:
            return db.execute(
                "INSERT INTO job_segments (job_id, idx, video, last_frame, duration_s, done_at)"
                " SELECT ?, idx, video, last_frame, duration_s, done_at FROM job_segments"
                " WHERE job_id = ? AND done_at IS NOT NULL AND idx < ("
                "   SELECT coalesce(min(idx), 1000000) FROM job_segments"
                "   WHERE job_id = ? AND done_at IS NULL)",
                (target_job, source_job, source_job),
            ).rowcount

    def segment_submitted(self, job_id: int, idx: int, prompt_id: str) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO job_segments (job_id, idx, prompt_id) VALUES (?,?,?)"
                " ON CONFLICT (job_id, idx) DO UPDATE SET prompt_id = excluded.prompt_id",
                (job_id, idx, prompt_id),
            )

    def segment_done(
        self, job_id: int, idx: int, video: str, last_frame: str, duration_s: float
    ) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO job_segments (job_id, idx, video, last_frame, duration_s, done_at)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT (job_id, idx) DO UPDATE SET"
                " video = excluded.video, last_frame = excluded.last_frame,"
                " duration_s = excluded.duration_s, done_at = excluded.done_at",
                (job_id, idx, video, last_frame, duration_s, now()),
            )
            self._event("job", job_id, "segment", idx=idx)

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

    def running_since(self) -> float | None:
        """Startzeit (Unix-Sekunden) des ältesten laufenden Jobs; None, wenn keiner läuft."""
        row = self.db.execute("SELECT min(updated_at) FROM jobs WHERE status = 'running'")
        since = row.fetchone()[0]
        return datetime.fromisoformat(since).timestamp() if since else None

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

    def engine_peak_gb(self, engine: str) -> float | None:
        """Gemessener Speicherbedarf (freier Speicher Start minus Minimum) des letzten
        abgeschlossenen Laufs dieser Engine; None ohne Messung."""
        row = self.db.execute(
            "SELECT json_extract(e.data, '$.memory.ram_free_start_gb'),"
            " json_extract(e.data, '$.memory.ram_free_min_gb') FROM events e"
            " JOIN jobs j ON j.id = e.entity_id WHERE e.entity = 'job' AND e.event = 'status'"
            " AND json_extract(e.data, '$.status') = 'done' AND j.engine = ?"
            " AND json_extract(e.data, '$.memory.ram_free_min_gb') IS NOT NULL"
            " AND json_extract(e.data, '$.memory.ram_free_start_gb') IS NOT NULL"
            " ORDER BY e.id DESC LIMIT 1",
            (engine,),
        ).fetchone()
        return None if row is None else max(0.0, row[0] - row[1])

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
            tier_job = job_id
            if artifact_id is not None:
                art = self.artifact(artifact_id)
                order_id, tier_job = art.order_id, art.job_id
            elif job_id is not None:
                order_id = db.execute(
                    "SELECT order_id FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()[0]
            tier_row = (
                db.execute("SELECT content_tier FROM jobs WHERE id = ?", (tier_job,)).fetchone()
                if tier_job is not None
                else None
            )
            content_tier = tier_row[0] if tier_row else None
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
                " number, created_at, content_tier) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                    content_tier,
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
            + ") x ON x.id = e.entity_id WHERE e.entity = 'media' AND e.event IN ('added', 'tier')"
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

    def media_by_path(self, rel: str) -> dict | None:
        row = self.db.execute("SELECT * FROM media WHERE path = ?", (rel,)).fetchone()
        return dict(row) if row else None

    def media_by_sha(self, sha256: str) -> dict | None:
        """Medium mit genau diesem Inhalt (Herkunftsprüfung, z. B. Kloner-Befehl edit)."""
        if not sha256:
            return None
        row = self.db.execute("SELECT * FROM media WHERE sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None

    def media_children(self, media_id: int) -> list[int]:
        """Medien aus Aufträgen, deren Ausgangsmedium ``media_id`` ist (abgeleitete Versionen)."""
        rows = self.db.execute(
            "SELECT m.id FROM media m JOIN jobs j ON j.id = m.job_id"
            " WHERE j.parent_media_id = ? ORDER BY m.id",
            (media_id,),
        )
        return [r[0] for r in rows]

    def media_by_id(self, media_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return dict(row) if row else None

    def media_path_by_sha(self) -> dict[str, str]:
        """SHA-256 -> Pfad der indizierten Datei (gleicher Inhalt steht nur einmal im Index)."""
        return {r[0]: r[1] for r in self.db.execute("SELECT sha256, path FROM media")}

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
