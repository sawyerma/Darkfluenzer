"""Kunden und Kanalidentitäten (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

from .db import (
    Customer,
    StoreError,
    _customer,
    now,
)


class CustomersMixin:
    """Kunden und Kanalidentitäten; Teil von ``Store``."""

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

    def customer_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.entity_id AS customer_id"
            " FROM events e WHERE e.entity = 'customer' AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit
