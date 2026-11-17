"""Migrationen je Schemaversion (SP0 Schritt 2, bisher ``store.py``); vor jeder Migration sichert
``Store._migrate`` die Datenbank (SP0 Schritt 1)."""

from __future__ import annotations

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
    18: """
-- Journal (SP0 Schritt 6, BUG-107): Index für Abfragen je Art und Ereignis ab einer Position;
-- Medien-ID und laufende Nummer aus einer Zählertabelle statt aus dem Maximum über das Journal
CREATE INDEX events_entity_event ON events(entity, event, id);
CREATE TABLE counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT INTO counters (name, value) VALUES
    ('media_id', max(
        coalesce((SELECT max(entity_id) FROM events WHERE entity = 'media'), 0),
        coalesce((SELECT max(id) FROM media), 0))),
    ('media_number', max(
        coalesce((SELECT max(number) FROM media), 0),
        coalesce((SELECT max(json_extract(data, '$.number')) FROM events
                  WHERE entity = 'media' AND event = 'removed'), 0)));
""",
    19: """
-- Ergebnis eines Jobs, auch wenn es bitgleich zu einem vorhandenen Medium ist (BUG-064): dann
-- zeigt media_id auf dieses Medium (ohne Fremdschlüssel, damit Löschen in der Galerie frei bleibt)
ALTER TABLE jobs ADD COLUMN media_id INTEGER;
""",
    20: """
-- Vorrang auf der Renderbahn (SP5 Schritt 5, BUG-101): Klasse je Job; die Reihenfolge der Klassen
-- steht in der Konfiguration (production.priority), innerhalb einer Klasse FIFO
ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT 'cockpit'
    CHECK (priority IN ('customer', 'default', 'cockpit', 'training'));
""",
    21: """
-- Ein Ordnerschema je Charakter (SP3 Schritt 1, BUG-078): local/characters/<slug>/; Trigger und
-- Klasse für Datensatz und Prompt. slug füllt der Ordnerumzug beim Start (mit Hash-Abgleich).
ALTER TABLE characters ADD COLUMN slug TEXT;
ALTER TABLE characters ADD COLUMN trigger TEXT NOT NULL DEFAULT 'dfchar';
ALTER TABLE characters ADD COLUMN class_word TEXT NOT NULL DEFAULT 'woman';
CREATE UNIQUE INDEX characters_slug ON characters(slug) WHERE slug IS NOT NULL;
""",
}

# Schritte mit Tabellenneubau: Fremdschlüssel währenddessen aus, danach vollständig geprüft
REBUILDS = {5, 6, 7}
