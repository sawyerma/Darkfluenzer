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
    22: """
-- Aktive Charakter-LoRA (SP3 Schritt 6): genau eine je Figur und Architektur; Probe-Prompts des
-- Profils (JSON-Liste) für die Probebilder einer LoRA.
CREATE TABLE character_loras (
    character_id INTEGER NOT NULL REFERENCES characters(id),
    arch         TEXT    NOT NULL,
    lora         TEXT    NOT NULL,
    activated_at TEXT    NOT NULL,
    PRIMARY KEY (character_id, arch)
);
ALTER TABLE characters ADD COLUMN probe_prompts TEXT NOT NULL DEFAULT '[]';
""",
    23: """
-- Messwerte der Prüfknoten je Medium (SP3 Schritt 7): Identität mit „nicht prüfbar“ als eigenem
-- Status; entschieden wird gegen die Schwellen in SP5 Schritt 7.
CREATE TABLE media_checks (
    id         INTEGER PRIMARY KEY,
    media_id   INTEGER REFERENCES media(id),
    job_id     INTEGER REFERENCES jobs(id),
    check_name TEXT    NOT NULL,
    status     TEXT    NOT NULL,
    data       TEXT    NOT NULL DEFAULT '{}',
    reference  TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX media_checks_media ON media_checks(media_id) WHERE media_id IS NOT NULL;
""",
    24: """
-- Abmessungen je Medium (SP3 Ausgabe): Datei und native Erzeugungsgröße getrennt; Hochskalieren
-- und Ausgabeformate werden nie als nativ ausgegeben. NULL = unbekannt (Video, noch nicht gelesen).
ALTER TABLE media ADD COLUMN width INTEGER;
ALTER TABLE media ADD COLUMN height INTEGER;
ALTER TABLE media ADD COLUMN native_width INTEGER;
ALTER TABLE media ADD COLUMN native_height INTEGER;
""",
    25: """
-- Versand nach dem Gate (FABLE-012): eine von der Plattform angenommene Zustellung wird immer
-- festgeschrieben. Ist das Gate danach verletzt (z. B. Erstattung während des Sendens), steht der
-- Grund in gate_violation; nur mit diesem Grund darf der Versand-Trigger den Status sent zulassen.
ALTER TABLE deliveries ADD COLUMN gate_violation TEXT;
DROP TRIGGER deliveries_send_gate;
CREATE TRIGGER deliveries_send_gate BEFORE UPDATE OF status ON deliveries
WHEN NEW.status = 'sent' AND (
    OLD.status != 'pending'
    OR (NEW.gate_violation IS NULL AND (
        NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = NEW.order_id
                    AND p.status = 'confirmed')
        OR NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.id =
                         (SELECT max(id) FROM approvals WHERE order_id = NEW.order_id)
                       AND ap.decision = 'approved' AND ap.artifact_id = NEW.artifact_id)
        OR NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = NEW.order_id
                       AND o.status = 'approved'))))
BEGIN SELECT RAISE(ABORT, 'delivery: Gate beim Versand nicht erfüllt'); END;
""",
    26: """
-- Promptprofile je Influencerin (SP4 Schritt 2, E19): jede gespeicherte Fassung ist eine eigene,
-- unveränderliche Version; aktiv ist genau eine (influencers.persona_active). Der bisherige
-- Persona-Text wird Version 1.
CREATE TABLE persona_versions (
    id            INTEGER PRIMARY KEY,
    influencer_id INTEGER NOT NULL REFERENCES influencers(id),
    version       INTEGER NOT NULL CHECK (version > 0),
    blocks        TEXT    NOT NULL DEFAULT '{}',
    params        TEXT    NOT NULL DEFAULT '{}',
    note          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    UNIQUE (influencer_id, version)
);
CREATE TRIGGER persona_versions_no_update BEFORE UPDATE ON persona_versions
BEGIN SELECT RAISE(ABORT, 'persona_versions: unveränderlich'); END;
CREATE TRIGGER persona_versions_no_delete BEFORE DELETE ON persona_versions
BEGIN SELECT RAISE(ABORT, 'persona_versions: unveränderlich'); END;
ALTER TABLE influencers ADD COLUMN persona_active INTEGER REFERENCES persona_versions(id);
INSERT INTO persona_versions (influencer_id, version, blocks, note, created_at)
    SELECT id, 1, json_object('persona', persona), 'aus dem bisherigen Profil', updated_at
    FROM influencers WHERE persona != '';
UPDATE influencers SET persona_active = (
    SELECT v.id FROM persona_versions v WHERE v.influencer_id = influencers.id AND v.version = 1);
""",
    27: """
-- KI-Läufe (SP4 Schritt 1): je Lauf eines Sprachworkflows Art, Workflow- und Modellversion,
-- Profilversion, zusammengesetzter Prompt (aus dem Graphen gelesen), Kontextauswahl, Ergebnis und
-- Messwerte. Gesprächsdaten liegen nur hier in SQLite (Regel 12 e, SPEC-018).
CREATE TABLE ai_runs (
    id              INTEGER PRIMARY KEY,
    kind            TEXT    NOT NULL CHECK (kind IN ('studio', 'chat', 'test', 'warmup')),
    workflow        TEXT    NOT NULL,
    workflow_sha    TEXT    NOT NULL DEFAULT '',
    model_sha       TEXT    NOT NULL DEFAULT '',
    influencer_id   INTEGER REFERENCES influencers(id),
    persona_version INTEGER REFERENCES persona_versions(id),
    customer_id     INTEGER REFERENCES customers(id),
    session         INTEGER NOT NULL DEFAULT 0,
    request_id      TEXT    NOT NULL DEFAULT '',
    message         TEXT    NOT NULL DEFAULT '',
    context         TEXT    NOT NULL DEFAULT '{}',
    system_prompt   TEXT    NOT NULL DEFAULT '',
    user_text       TEXT    NOT NULL DEFAULT '',
    answer          TEXT    NOT NULL DEFAULT '',
    classification  TEXT    NOT NULL DEFAULT '',
    prompt_id       TEXT    NOT NULL DEFAULT '',
    wait_ms         INTEGER,
    duration_ms     INTEGER,
    total_ms        INTEGER,
    error           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);
CREATE INDEX ai_runs_studio ON ai_runs(influencer_id, session) WHERE kind = 'studio';
-- laufende Studio-Sitzung je Influencerin (Befehl 50 erhöht sie)
CREATE TABLE studio_sessions (
    influencer_id INTEGER PRIMARY KEY REFERENCES influencers(id),
    session       INTEGER NOT NULL DEFAULT 1 CHECK (session > 0)
);
""",
    28: """
-- Gates vor dem Versand (SP4 Schritt 3): Ergebnis je Gate als JSON, ob die Antwort gesendet werden
-- dürfte (NULL = nicht geprüft, z. B. Aufwärmlauf) und wie viele Läufe sie brauchte.
ALTER TABLE ai_runs ADD COLUMN gates TEXT NOT NULL DEFAULT '[]';
ALTER TABLE ai_runs ADD COLUMN sendable INTEGER;
ALTER TABLE ai_runs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 1;
""",
    29: """
-- Gedächtnis (SP4 Schritt 5, B5.3): Ebenen Kundengedächtnis, Gesprächsmemo, Langzeitereignis und
-- eigene Aussagen der Influencerin; Kurzzeitgedächtnis ist der Verlauf. Bereiche strikt getrennt:
-- customer (Kundenakte), studio (KI-Studio je Influencerin und Sitzung), test (Kundentest). Jede
-- Erinnerung mit Quelle und Zeit; eine Korrektur ersetzt mit Verlauf (replaced_by), Löschen setzt
-- den Status. Abruf über FTS5.
CREATE TABLE memories (
    id          INTEGER PRIMARY KEY,
    scope       TEXT    NOT NULL CHECK (scope IN ('customer', 'studio', 'test')),
    owner_id    INTEGER NOT NULL,
    session     INTEGER NOT NULL DEFAULT 0,
    level       TEXT    NOT NULL CHECK (level IN ('customer', 'memo', 'event', 'self')),
    text        TEXT    NOT NULL CHECK (length(trim(text)) > 0),
    source      TEXT    NOT NULL DEFAULT '',
    origin      TEXT    NOT NULL CHECK (origin IN ('ai', 'operator')),
    status      TEXT    NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'replaced', 'deleted')),
    replaced_by INTEGER REFERENCES memories(id),
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX memories_owner ON memories(scope, owner_id, session, status);
CREATE VIRTUAL TABLE memories_fts USING fts5(text, content='memories', content_rowid='id');
CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (NEW.id, NEW.text);
END;
CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', OLD.id, OLD.text);
END;
CREATE TRIGGER memories_fts_update AFTER UPDATE OF text ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', OLD.id, OLD.text);
    INSERT INTO memories_fts(rowid, text) VALUES (NEW.id, NEW.text);
END;
""",
    30: """
-- Kanalkonten als Liste (SP2 Schritt 9a): je Konto Kürzel, Plattform, unveränderliche Konto-ID nach
-- der Anmeldung, Influencerin, Testbetrieb mit Test-Chats, Betriebsart und Default-Absender des
-- Kontos (E12), Kundentransport (je Konto genau ein Weg). Die bisherigen Abschnitte
-- [telegram_account]/[instagram] werden beim ersten Start als Konto übernommen.
CREATE TABLE channel_accounts (
    id                  INTEGER PRIMARY KEY,
    key                 TEXT    NOT NULL UNIQUE CHECK (length(trim(key)) > 0),
    platform            TEXT    NOT NULL CHECK (platform IN ('telegram', 'instagram', 'whatsapp')),
    platform_account_id TEXT    NOT NULL DEFAULT '',
    influencer_id       INTEGER REFERENCES influencers(id),
    test_mode           INTEGER NOT NULL DEFAULT 1 CHECK (test_mode IN (0, 1)),
    test_chat_ids       TEXT    NOT NULL DEFAULT '[]',
    operating_mode      TEXT    NOT NULL DEFAULT 'production'
                        CHECK (operating_mode IN ('production', 'test', 'off')),
    default_sender_id   TEXT    NOT NULL DEFAULT '',
    customer_transport  TEXT    NOT NULL DEFAULT 'tdlib'
                        CHECK (customer_transport IN ('tdlib', 'business_bot', 'graph')),
    status              TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
CREATE UNIQUE INDEX channel_accounts_platform_id ON channel_accounts(platform, platform_account_id)
    WHERE platform_account_id != '';
""",
    31: """
-- Telegram-Eingang vervollständigen (SP2 Schritt 5): bearbeitete Nachricht mit Zeit und erstem
-- Text, gelöschte mit Löschmarke. Der Inhalt bleibt; ob er bei Löschung entfernt wird, klärt
-- SP6 Schritt 8.
ALTER TABLE channel_messages ADD COLUMN edited_at TEXT;
ALTER TABLE channel_messages ADD COLUMN original_text TEXT;
ALTER TABLE channel_messages ADD COLUMN deleted_at TEXT;
""",
    32: """
-- Telegram-Alben (SP1 Schritt 3): Nachrichten eines Albums tragen dieselbe album_id; der Kloner
-- wertet ein Album erst aus, wenn es ruhig ist (SP1 Schritt 4).
ALTER TABLE channel_messages ADD COLUMN album_id TEXT;
CREATE INDEX channel_messages_album ON channel_messages(conversation_id, album_id)
    WHERE album_id IS NOT NULL;
""",
    33: """
-- Default-Kette (SP1 Schritte 6, 7, 8, 11): Kandidaten je Bild (NULL = Konfiguration), Chat-Wort
-- für den Abbruch, Ausgabeprofil je Befehl (Format, Dauer, Fertigstellen) und Rückversand je
-- Auftrag und Medium genau einmal.
ALTER TABLE default_contact ADD COLUMN candidates INTEGER
    CHECK (candidates IS NULL OR candidates BETWEEN 1 AND 12);
ALTER TABLE default_contact ADD COLUMN cancel_word TEXT NOT NULL DEFAULT '';
ALTER TABLE default_commands ADD COLUMN format TEXT NOT NULL DEFAULT '';
ALTER TABLE default_commands ADD COLUMN duration_s REAL NOT NULL DEFAULT 0
    CHECK (duration_s >= 0);
ALTER TABLE default_commands ADD COLUMN finish TEXT NOT NULL DEFAULT '';
CREATE TABLE cloner_returns (
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    media_id   INTEGER NOT NULL REFERENCES media(id),
    message_id INTEGER REFERENCES channel_messages(id),
    created_at TEXT    NOT NULL,
    PRIMARY KEY (order_id, media_id)
);
""",
    34: """
-- Dialogbetrieb (SP4 Schritt 6, BUG-097): KI-Antworten als Entwurf (draft) oder storniert
-- (cancelled), geplante Sendezeit, Bezug auf den Sprachlauf; Tabellenumbau wie Migration 7.
CREATE TABLE channel_messages_v34 (
    id                   INTEGER PRIMARY KEY,
    customer_id          INTEGER NOT NULL REFERENCES customers(id),
    conversation_id      INTEGER NOT NULL REFERENCES channel_conversations(id),
    direction            TEXT    NOT NULL CHECK (direction IN ('in', 'out', 'system')),
    platform_message_id  TEXT,
    reply_to_platform_id TEXT,
    text                 TEXT    NOT NULL DEFAULT '',
    attachments          TEXT    NOT NULL DEFAULT '[]',
    status               TEXT    NOT NULL CHECK (status IN ('received', 'queued', 'sending',
                         'sent', 'failed', 'unknown', 'draft', 'cancelled')),
    error                TEXT,
    request_id           TEXT,
    order_id             INTEGER REFERENCES orders(id),
    sent_at              TEXT    NOT NULL,
    read_at              TEXT,
    created_at           TEXT    NOT NULL,
    origin_message_id    INTEGER REFERENCES channel_messages(id),
    delivery_id          INTEGER REFERENCES deliveries(id),
    edited_at            TEXT,
    original_text        TEXT,
    deleted_at           TEXT,
    album_id             TEXT,
    scheduled_at         TEXT,
    ai_run_id            INTEGER REFERENCES ai_runs(id),
    -- vom Betreiber freigegeben (Entwurf gesendet, „Jetzt senden“): beim Versand nur harte Gates
    released             INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1)),
    UNIQUE (conversation_id, direction, platform_message_id)
);
INSERT INTO channel_messages_v34 (id, customer_id, conversation_id, direction,
    platform_message_id, reply_to_platform_id, text, attachments, status, error, request_id,
    order_id, sent_at, read_at, created_at, origin_message_id, delivery_id, edited_at,
    original_text, deleted_at, album_id)
SELECT id, customer_id, conversation_id, direction, platform_message_id, reply_to_platform_id,
       text, attachments, status, error, request_id, order_id, sent_at, read_at, created_at,
       origin_message_id, delivery_id, edited_at, original_text, deleted_at, album_id
FROM channel_messages;
DROP TABLE channel_messages;
ALTER TABLE channel_messages_v34 RENAME TO channel_messages;
CREATE INDEX channel_messages_customer ON channel_messages(customer_id, id);
CREATE UNIQUE INDEX channel_messages_request ON channel_messages(request_id)
    WHERE request_id IS NOT NULL;
CREATE INDEX channel_messages_order ON channel_messages(order_id) WHERE order_id IS NOT NULL;
CREATE INDEX channel_messages_album ON channel_messages(conversation_id, album_id)
    WHERE album_id IS NOT NULL;
CREATE INDEX channel_messages_scheduled ON channel_messages(scheduled_at)
    WHERE status = 'queued' AND scheduled_at IS NOT NULL;
-- Modus der Konversation: auto (KI antwortet), draft (nur Entwurf), manual (Betreiber)
ALTER TABLE channel_conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (mode IN ('auto', 'draft', 'manual'));
-- Schalter der Influencerin (C5.1): Text-KI und automatische Antworten
ALTER TABLE influencers ADD COLUMN text_ai INTEGER NOT NULL DEFAULT 0 CHECK (text_ai IN (0, 1));
ALTER TABLE influencers ADD COLUMN auto_replies INTEGER NOT NULL DEFAULT 0
    CHECK (auto_replies IN (0, 1));
""",
    35: """
-- Verhalten (SP4 Schritt 7): Verhaltensprofil je Influencerin (nur Zahlen, versioniert, eine
-- aktiv) und Vertröst-Texte, die der Workflow im Leerlauf aus der Profilanweisung erzeugt (je
-- Profilversion)
CREATE TABLE behavior_versions (
    id            INTEGER PRIMARY KEY,
    influencer_id INTEGER NOT NULL REFERENCES influencers(id),
    version       INTEGER NOT NULL,
    data          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    UNIQUE (influencer_id, version)
);
ALTER TABLE influencers ADD COLUMN behavior_active INTEGER REFERENCES behavior_versions(id);
CREATE TABLE consolations (
    id              INTEGER PRIMARY KEY,
    persona_version INTEGER NOT NULL REFERENCES persona_versions(id),
    text            TEXT    NOT NULL CHECK (length(trim(text)) > 0),
    ai_run_id       INTEGER REFERENCES ai_runs(id),
    created_at      TEXT    NOT NULL,
    used_message_id INTEGER REFERENCES channel_messages(id),
    used_at         TEXT
);
CREATE INDEX consolations_free ON consolations(persona_version) WHERE used_at IS NULL;
""",
    36: """
-- Kundentest im Default-Chat (SP4 Schritt 8): Testnachrichten bilden einen eigenen Verlauf
-- (Telegram kennt nur einen Chat je Absender); Testsitzung (Zurücksetzen), KI-Hinweis je Test,
-- Schalter „Verzögerung wie Kunde“.
ALTER TABLE channel_messages ADD COLUMN test INTEGER NOT NULL DEFAULT 0 CHECK (test IN (0, 1));
ALTER TABLE default_contact ADD COLUMN test_session INTEGER NOT NULL DEFAULT 1;
ALTER TABLE default_contact ADD COLUMN test_notice_message_id INTEGER
    REFERENCES channel_messages(id);
ALTER TABLE default_contact ADD COLUMN test_delay INTEGER NOT NULL DEFAULT 0
    CHECK (test_delay IN (0, 1));
""",
    37: """
-- Freie Default-Anweisungen (SP4 Schritt 4): eigene Laufart instruction in ai_runs (Umbau wegen
-- der CHECK-Bedingung, Spalten und IDs unverändert)
CREATE TABLE ai_runs_v37 (
    id              INTEGER PRIMARY KEY,
    kind            TEXT    NOT NULL
                    CHECK (kind IN ('studio', 'chat', 'test', 'warmup', 'instruction')),
    workflow        TEXT    NOT NULL,
    workflow_sha    TEXT    NOT NULL DEFAULT '',
    model_sha       TEXT    NOT NULL DEFAULT '',
    influencer_id   INTEGER REFERENCES influencers(id),
    persona_version INTEGER REFERENCES persona_versions(id),
    customer_id     INTEGER REFERENCES customers(id),
    session         INTEGER NOT NULL DEFAULT 0,
    request_id      TEXT    NOT NULL DEFAULT '',
    message         TEXT    NOT NULL DEFAULT '',
    context         TEXT    NOT NULL DEFAULT '{}',
    system_prompt   TEXT    NOT NULL DEFAULT '',
    user_text       TEXT    NOT NULL DEFAULT '',
    answer          TEXT    NOT NULL DEFAULT '',
    classification  TEXT    NOT NULL DEFAULT '',
    prompt_id       TEXT    NOT NULL DEFAULT '',
    wait_ms         INTEGER,
    duration_ms     INTEGER,
    total_ms        INTEGER,
    error           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    gates           TEXT    NOT NULL DEFAULT '[]',
    sendable        INTEGER,
    attempts        INTEGER NOT NULL DEFAULT 1
);
INSERT INTO ai_runs_v37 SELECT id, kind, workflow, workflow_sha, model_sha, influencer_id,
    persona_version, customer_id, session, request_id, message, context, system_prompt, user_text,
    answer, classification, prompt_id, wait_ms, duration_ms, total_ms, error, created_at, gates,
    sendable, attempts FROM ai_runs;
DROP TABLE ai_runs;
ALTER TABLE ai_runs_v37 RENAME TO ai_runs;
CREATE INDEX ai_runs_studio ON ai_runs(influencer_id, session) WHERE kind = 'studio';
""",
    38: """
-- Produkte (SP5 Schritt 1): feste ID je Position statt Listenindex, Art, Workflow (Video:
-- Bild-Workflow und Animation als Fertigstellen), Kandidaten, Höchstlänge, Lieferzeit-Grenze,
-- Zusatzleistungen; entfernte Positionen bleiben (Angebote verweisen darauf). Zahlungswege und
-- Angebotsgültigkeit an der Influencerin.
CREATE TABLE products (
    id                 INTEGER PRIMARY KEY,
    influencer_id      INTEGER NOT NULL REFERENCES influencers(id),
    position           INTEGER NOT NULL,
    product            TEXT    NOT NULL CHECK (length(trim(product)) > 0),
    price_cents        INTEGER NOT NULL CHECK (price_cents > 0),
    hd_surcharge_cents INTEGER NOT NULL DEFAULT 0 CHECK (hd_surcharge_cents >= 0),
    kind               TEXT    NOT NULL DEFAULT 'image' CHECK (kind IN ('image', 'video')),
    workflow           TEXT    NOT NULL DEFAULT '',
    finish_workflow    TEXT    NOT NULL DEFAULT '',
    candidates         INTEGER NOT NULL DEFAULT 1 CHECK (candidates BETWEEN 1 AND 12),
    max_duration_s     REAL    NOT NULL DEFAULT 0 CHECK (max_duration_s >= 0),
    max_delivery_s     REAL    NOT NULL DEFAULT 0 CHECK (max_delivery_s >= 0),
    original_file      INTEGER NOT NULL DEFAULT 0 CHECK (original_file IN (0, 1)),
    self_destruct      INTEGER NOT NULL DEFAULT 0 CHECK (self_destruct IN (0, 1)),
    status             TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL
);
INSERT INTO products (influencer_id, position, product, price_cents, hd_surcharge_cents,
    created_at, updated_at)
SELECT influencer_id, position, product, price_cents, hd_surcharge_cents,
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM influencer_prices ORDER BY influencer_id, position;
DROP TABLE influencer_prices;
CREATE INDEX products_influencer ON products(influencer_id, position) WHERE status = 'active';
ALTER TABLE influencers ADD COLUMN payment_ways TEXT NOT NULL DEFAULT '["amazon"]';
ALTER TABLE influencers ADD COLUMN offer_valid_min INTEGER NOT NULL DEFAULT 0
    CHECK (offer_valid_min >= 0);
ALTER TABLE offers ADD COLUMN product_id INTEGER REFERENCES products(id);
""",
    39: """
-- Angebot (SP5 Schritt 2): Zahlung in Prüfung (payment_review, die Frist ruht), geparkte Zustellung
-- (awaiting_contact, Übergänge SP5 Schritt 9) und Grund des Status (z. B. „abgelaufen“,
-- „abgelehnt“). Neubau der Tabelle wegen der CHECK-Liste, alle Zeilen behalten ihre ID.
CREATE TABLE orders_v39 (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no      TEXT GENERATED ALWAYS AS ('DF-O-' || printf('%06d', id)) STORED,
    source        TEXT    NOT NULL DEFAULT 'customer'
                  CHECK (source IN ('operator', 'cloner', 'customer')),
    customer_id   INTEGER REFERENCES customers(id),
    kind          TEXT    NOT NULL CHECK (kind IN ('image', 'video')),
    request       TEXT    NOT NULL,
    offer         TEXT,
    price_amount  INTEGER CHECK (price_amount IS NULL OR price_amount > 0),
    currency      TEXT,
    status        TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'offered',
                  'payment_review', 'accepted', 'paid', 'producing', 'review', 'approved',
                  'delivered', 'awaiting_contact', 'cancelled', 'refunded')),
    status_reason TEXT,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    CHECK ((source = 'customer') = (customer_id IS NOT NULL))
);
INSERT INTO orders_v39 (id, source, customer_id, kind, request, offer, price_amount, currency,
                        status, created_at, updated_at)
SELECT id, source, customer_id, kind, request, offer, price_amount, currency, status,
       created_at, updated_at FROM orders;
DROP TABLE orders;
ALTER TABLE orders_v39 RENAME TO orders;
CREATE UNIQUE INDEX orders_no ON orders(order_no);
CREATE INDEX orders_customer ON orders(customer_id);
-- Faktenblock wörtlich wie gesendet, Lieferzeit bei Angebot, Beginn der Zahlungsprüfung
ALTER TABLE offers ADD COLUMN facts TEXT NOT NULL DEFAULT '';
ALTER TABLE offers ADD COLUMN delivery_s REAL;
ALTER TABLE offers ADD COLUMN review_started_at TEXT;
-- je angebotenem Zahlungsweg: Betrag, Ziel (Adresse oder Link), Hinweis; die eindeutigen
-- Krypto-Beträge für die Zuordnung bleiben in offer_amounts
CREATE TABLE offer_payments (
    order_id INTEGER NOT NULL REFERENCES offers(order_id),
    way      TEXT    NOT NULL CHECK (way IN ('amazon', 'btc', 'usdt', 'usdc', 'paypal')),
    amount   TEXT    NOT NULL,
    currency TEXT    NOT NULL,
    target   TEXT    NOT NULL DEFAULT '',
    note     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (order_id, way)
);
-- Sperrzeit nach einer Ablehnung (Minuten, 0 = keine)
ALTER TABLE influencers ADD COLUMN offer_cooldown_min INTEGER NOT NULL DEFAULT 0
    CHECK (offer_cooldown_min >= 0);
""",
    40: """
-- Kundentest mit Bild (SP5 Schritt 12, SPEC-008): Testauftrag der internen Akte (orders.test,
-- unveränderlich, nur an der internen Default-Akte). Statt der Zahlung gilt die Testfreigabe
-- (Wort, Startwert „Cash“, oder automatisch). Ausnahme „ohne Zahlung“ in beiden Liefer-Triggern
-- nur, wenn alle Bedingungen gelten: test = 1, interne Default-Akte, Lieferziel = Konversation des
-- Angebots, Identität verifiziert und gehört zur Akte, Betriebsart des Kontos test; beim Versand
-- zusätzlich: die Zustellnachricht geht genau an diese Konversation. Testmedien dürfen gelöscht
-- werden.
ALTER TABLE orders ADD COLUMN test INTEGER NOT NULL DEFAULT 0 CHECK (test IN (0, 1));
CREATE TRIGGER orders_test_immutable BEFORE UPDATE OF test ON orders WHEN NEW.test != OLD.test
BEGIN SELECT RAISE(ABORT, 'orders: Testkennzeichen unveränderlich'); END;
CREATE TRIGGER orders_test_internal BEFORE INSERT ON orders WHEN NEW.test = 1
    AND NOT EXISTS (SELECT 1 FROM customers c JOIN default_contact d ON d.customer_id = c.id
                    WHERE c.id = NEW.customer_id AND c.kind = 'internal')
BEGIN SELECT RAISE(ABORT, 'orders: Testauftrag nur an der internen Default-Akte'); END;
ALTER TABLE default_contact ADD COLUMN test_pay_word TEXT NOT NULL DEFAULT 'Cash';
ALTER TABLE default_contact ADD COLUMN test_auto_pay INTEGER NOT NULL DEFAULT 0
    CHECK (test_auto_pay IN (0, 1));
DROP TRIGGER deliveries_gate;
CREATE TRIGGER deliveries_gate BEFORE INSERT ON deliveries
BEGIN
    SELECT RAISE(ABORT, 'delivery: Kunde/Auftrag ungültig oder storniert')
    WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = NEW.order_id
                      AND o.customer_id = NEW.customer_id AND o.status = 'approved');
    SELECT RAISE(ABORT, 'delivery: keine bestätigte, passende Zahlung')
    WHERE NOT EXISTS (SELECT 1 FROM payments p JOIN orders o ON o.id = p.order_id
                      WHERE p.order_id = NEW.order_id AND p.status = 'confirmed'
                      AND p.amount = o.price_amount AND p.currency = o.currency)
      AND NOT EXISTS (SELECT 1 FROM orders o
                  JOIN customers cu ON cu.id = o.customer_id AND cu.kind = 'internal'
                  JOIN default_contact d ON d.customer_id = o.customer_id
                  JOIN offers f ON f.order_id = o.id
                  JOIN channel_conversations c ON c.id = f.conversation_id
                  JOIN channel_identities i ON i.id = c.identity_id
                       AND i.customer_id = o.customer_id AND i.verified = 1
                  JOIN channel_accounts a ON a.platform = i.platform
                       AND a.platform_account_id = i.account AND a.operating_mode = 'test'
                  WHERE o.id = NEW.order_id AND o.test = 1);
    SELECT RAISE(ABORT, 'delivery: keine gültige Betreiberfreigabe für dieses Artefakt')
    WHERE NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.id =
                        (SELECT max(id) FROM approvals WHERE order_id = NEW.order_id)
                      AND ap.decision = 'approved' AND ap.artifact_id = NEW.artifact_id
                      AND ap.artifact_sha256 = NEW.artifact_sha256);
END;
DROP TRIGGER deliveries_send_gate;
CREATE TRIGGER deliveries_send_gate BEFORE UPDATE OF status ON deliveries
WHEN NEW.status = 'sent' AND (
    OLD.status != 'pending'
    OR (NEW.gate_violation IS NULL AND (
        (NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = NEW.order_id
                     AND p.status = 'confirmed')
         AND NOT (EXISTS (SELECT 1 FROM orders o
                  JOIN customers cu ON cu.id = o.customer_id AND cu.kind = 'internal'
                  JOIN default_contact d ON d.customer_id = o.customer_id
                  JOIN offers f ON f.order_id = o.id
                  JOIN channel_conversations c ON c.id = f.conversation_id
                  JOIN channel_identities i ON i.id = c.identity_id
                       AND i.customer_id = o.customer_id AND i.verified = 1
                  JOIN channel_accounts a ON a.platform = i.platform
                       AND a.platform_account_id = i.account AND a.operating_mode = 'test'
                  WHERE o.id = NEW.order_id AND o.test = 1)
                  AND EXISTS (SELECT 1 FROM channel_messages m JOIN offers f
                              ON f.order_id = NEW.order_id WHERE m.delivery_id = NEW.id
                              AND m.conversation_id = f.conversation_id)))
        OR NOT EXISTS (SELECT 1 FROM approvals ap WHERE ap.id =
                         (SELECT max(id) FROM approvals WHERE order_id = NEW.order_id)
                       AND ap.decision = 'approved' AND ap.artifact_id = NEW.artifact_id)
        OR NOT EXISTS (SELECT 1 FROM orders o WHERE o.id = NEW.order_id
                       AND o.status = 'approved'))))
BEGIN SELECT RAISE(ABORT, 'delivery: Gate beim Versand nicht erfüllt'); END;
DROP TRIGGER media_order_no_delete;
CREATE TRIGGER media_order_no_delete BEFORE DELETE ON media WHEN OLD.order_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM orders o JOIN customers c ON c.id = o.customer_id
                    WHERE o.id = OLD.order_id AND o.test = 1 AND c.kind = 'internal')
BEGIN SELECT RAISE(ABORT, 'media: Kundenmedien unveränderlich'); END;
""",
}

# Schritte mit Tabellenneubau: Fremdschlüssel währenddessen aus, danach vollständig geprüft
REBUILDS = {5, 6, 7, 34, 37, 39}
