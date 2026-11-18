"""Konversationen, Nachrichten, Postausgang (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

import json
from pathlib import Path

from ..payments.vouchers import extract as extract_vouchers
from .db import (
    Inbound,
    StoreError,
    now,
)


class MessagesMixin:
    """Konversationen, Nachrichten, Postausgang; Teil von ``Store``."""

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
        album_id: str | None = None,
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
                " created_at, album_id) VALUES (?,?,'in',?,?,?,?,'received',?,?,?)"
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
                    album_id or None,
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

    def _platform_messages(
        self, platform: str, account: str, partner_id: str, ids: list[str]
    ) -> list[tuple[int, int, str, str | None]]:
        """Gespeicherte Nachrichten einer Plattform-Konversation zu Plattform-IDs:
        (ID, Akte, Text, Löschzeit)."""
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return self.db.execute(
            "SELECT m.id, m.customer_id, m.text, m.deleted_at FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE i.platform = ? AND i.account = ? AND c.platform_conversation_id = ?"
            f" AND m.direction IN ('in', 'out') AND m.platform_message_id IN ({marks})",
            (platform, account, partner_id, *ids),
        ).fetchall()

    def edit_platform_message(
        self, platform: str, account: str, partner_id: str, platform_message_id: str, text: str
    ) -> int | None:
        """Die Plattform meldet neuen Text (SP2 Schritt 5): Text ersetzen, den ersten Text und die
        Zeit behalten, Ereignis ``edited``. None, wenn unbekannt, gelöscht oder unverändert."""
        rows = self._platform_messages(platform, account, partner_id, [platform_message_id])
        if not rows or rows[0][3] is not None or rows[0][2] == text:
            return None
        message_id, customer_id, _, _ = rows[0]
        with self.tx() as db:
            db.execute(
                "UPDATE channel_messages SET original_text = COALESCE(original_text, text),"
                " text = ?, edited_at = ? WHERE id = ?",
                (text, now(), message_id),
            )
            self._event("message", message_id, "edited", customer_id=customer_id)
            self.bump("conversations")
        return message_id

    def delete_platform_messages(
        self, platform: str, account: str, partner_id: str, ids: list[str]
    ) -> list[int]:
        """Die Plattform meldet gelöschte Nachrichten: Löschmarke setzen (Inhalt bleibt bis zur
        Entscheidung in SP6 Schritt 8), Ereignis ``deleted``; liefert die neu markierten IDs."""
        rows = [r for r in self._platform_messages(platform, account, partner_id, ids) if not r[3]]
        if not rows:
            return []
        with self.tx() as db:
            for message_id, customer_id, _, _ in rows:
                db.execute(
                    "UPDATE channel_messages SET deleted_at = ? WHERE id = ?", (now(), message_id)
                )
                self._event("message", message_id, "deleted", customer_id=customer_id)
            self.bump("conversations")
        return [r[0] for r in rows]

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
            before = db.execute(
                "SELECT status, conversation_id FROM channel_messages WHERE id = ?", (message_id,)
            ).fetchone()
            db.execute(
                "UPDATE channel_messages SET status = ?, platform_message_id ="
                " coalesce(?, platform_message_id), error = ?, sent_at = CASE WHEN ? = 'sent'"
                " THEN ? ELSE sent_at END WHERE id = ?",
                (status, platform_message_id, error, status, now(), message_id),
            )
            self._event("message", message_id, "status", status=status, error=error)
            self.bump("conversations")
            if status == "unknown" and before and before[0] != "unknown":  # SPEC-009: Karte
                self.add_system_card(
                    before[1],
                    f"VERSAND UNGEKLÄRT · Nachricht {message_id} · ohne Beleg der Plattform kein "
                    "neuer Versuch – als gesendet markieren oder erneut senden",
                )
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

    def pending_inbound(self, platform: str, account: str) -> list[dict]:
        """Eingänge eines Kontos mit noch nicht geladenen Anhängen (``pending``): ihre
        Verarbeitung wurde unterbrochen (SP1 Schritt 3), älteste zuerst."""
        rows = self.db.execute(
            "SELECT m.*, c.platform_conversation_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE m.direction = 'in' AND i.platform = ? AND i.account = ?"
            " AND m.attachments LIKE '%\"pending\"%' ORDER BY m.id",
            (platform, account),
        )
        found = [dict(r) | {"attachments": json.loads(r["attachments"])} for r in rows]
        return [m for m in found if any(a.get("status") == "pending" for a in m["attachments"])]

    def inbound_of(self, message_id: int) -> Inbound:
        """Gespeicherten Eingang erneut als ``Inbound`` (Verarbeitung nach Wiederaufnahme)."""
        row = self.db.execute(
            "SELECT m.customer_id, m.conversation_id, c.identity_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Nachricht {message_id} unbekannt.")
        customer = self.customer_by_id(row["customer_id"])
        return Inbound(customer, row["identity_id"], row["conversation_id"], message_id, False)

    def album_messages(self, conversation_id: int, album_id: str) -> list[dict]:
        """Alle eingehenden Nachrichten eines Albums in Reihenfolge."""
        rows = self.db.execute(
            "SELECT id FROM channel_messages WHERE conversation_id = ? AND album_id = ?"
            " AND direction = 'in' ORDER BY id",
            (conversation_id, album_id),
        )
        return [self.message(r[0]) for r in rows]

    def unknown_outgoing(self, platform: str, account: str) -> list[dict]:
        """Sendungen mit unbekanntem Ergebnis eines Kontos (SP2 Schritt 6, SPEC-009)."""
        rows = self.db.execute(
            "SELECT m.*, c.platform_conversation_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE m.direction = 'out' AND m.status = 'unknown' AND i.platform = ?"
            " AND i.account = ? ORDER BY m.id",
            (platform, account),
        )
        return [dict(r) | {"attachments": json.loads(r["attachments"])} for r in rows]

    def match_unknown(
        self, platform: str, account: str, partner_id: str, text: str, file_names=()
    ) -> int | None:
        """Eigene Nachricht aus Echo oder Verlauf einer offenen Sendung derselben Konversation
        zuordnen: gleicher Text oder gleiche Datei (Dateiname der Zustellkopie); älteste zuerst."""
        names = {n for n in file_names if n}
        for row in self.unknown_outgoing(platform, account):
            if row["platform_conversation_id"] != partner_id:
                continue
            files = {Path(str(a.get("path", ""))).name for a in row["attachments"]}
            if (text.strip() and row["text"] == text) or names & files:
                return row["id"]
        return None

    def known_platform_ids(self, platform: str, account: str, partner_id: str) -> set[str]:
        """Plattform-IDs, die in dieser Konversation schon einer Nachricht gehören."""
        rows = self.db.execute(
            "SELECT m.platform_message_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE i.platform = ? AND i.account = ? AND c.platform_conversation_id = ?"
            " AND m.platform_message_id IS NOT NULL",
            (platform, account, partner_id),
        )
        return {r[0] for r in rows}

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

    def conversation_item(self, message_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT m.*, i.platform, i.handle, c.platform_conversation_id FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        return dict(row) | {"attachments": json.loads(row["attachments"])} if row else None

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

    def queue_ai_notice(self, customer_id: int, identity_id: int, text: str) -> int:
        """KI-Hinweis genau einmal je Kanalidentität in den Postausgang (Regel 12 b); erneut nur,
        wenn die verknüpfte Nachricht ``failed`` ist – nie bei ``queued``, ``sending``, ``sent``
        oder ``unknown`` (SP2 Schritt 7)."""
        with self.tx() as db:
            ident = db.execute(
                "SELECT i.ai_notice_message_id, c.id AS conversation_id, c.revision, n.status"
                " FROM channel_identities i JOIN channel_conversations c ON c.identity_id = i.id"
                " LEFT JOIN channel_messages n ON n.id = i.ai_notice_message_id"
                " WHERE i.id = ? AND i.customer_id = ?",
                (identity_id, customer_id),
            ).fetchone()
            if ident is None:
                raise StoreError("Kanalidentität gehört nicht zu dieser Kundenakte.")
            if ident["ai_notice_message_id"] and ident["status"] != "failed":
                raise StoreError(
                    "KI-Hinweis für diese Kanalidentität bereits ausgelöst"
                    f" ({ident['status'] or 'unbekannt'})."
                )
            message_id = self.queue_outbound(
                customer_id, ident["conversation_id"], text, revision=ident["revision"]
            )
            db.execute(
                "UPDATE channel_identities SET ai_notice_message_id = ? WHERE id = ?",
                (message_id, identity_id),
            )
            return message_id

    def conversation_platform(self, conversation_id: int) -> str:
        return self.conversation_account(conversation_id)[0]

    def conversation_account(self, conversation_id: int) -> tuple[str, str]:
        """Plattform und eigenes Konto (Plattform-Konto-ID) einer Konversation."""
        row = self.db.execute(
            "SELECT i.platform, i.account FROM channel_conversations c JOIN channel_identities i"
            " ON i.id = c.identity_id WHERE c.id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Konversation {conversation_id} unbekannt.")
        return row[0], row[1] or ""
