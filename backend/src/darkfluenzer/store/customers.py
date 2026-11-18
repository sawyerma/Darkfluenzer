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
            # Sperre je Plattform-Identität (SP2 Schritt 9a): dieselbe Person bei einer anderen
            # Influencerin ist eine eigene Akte, „minderjährig vermutet“ gilt trotzdem
            if self.identity_locked(platform, platform_user_id):
                db.execute(
                    "UPDATE customers SET age_mark = 'under_18' WHERE id = ?", (customer_id,)
                )
            customer = self.customer_by_id(customer_id)
            self._event("customer", customer_id, "created", customer_no=customer.customer_no)
            self.bump("customers")
            return customer, identity, True

    def identity_locked(self, platform: str, platform_user_id: str) -> bool:
        return bool(self.db.execute(
            "SELECT 1 FROM channel_identities i JOIN customers c ON c.id = i.customer_id"
            " WHERE i.platform = ? AND i.platform_user_id = ? AND c.age_mark = 'under_18'",
            (platform, platform_user_id),
        ).fetchone())  # fmt: skip

    def customers_with_identity_of(self, customer_id: int) -> list[int]:
        """Alle Akten mit einer Plattform-Identität dieser Akte (gleiche Plattform und Nutzer-ID,
        auch an Konten einer anderen Influencerin)."""
        rows = self.db.execute(
            "SELECT DISTINCT o.customer_id FROM channel_identities i JOIN channel_identities o"
            " ON o.platform = i.platform AND o.platform_user_id = i.platform_user_id"
            " WHERE i.customer_id = ?",
            (customer_id,),
        ).fetchall()
        return sorted({r[0] for r in rows} | {customer_id})

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

    def age_mark(self, customer_id: int) -> str:
        """Altersmarke der Akte (``under_18`` = gesperrt, SP4 Schritt 4)."""
        row = self.db.execute("SELECT age_mark FROM customers WHERE id = ?", (customer_id,))
        found = row.fetchone()
        return (found[0] or "") if found else ""

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
        figures = self.customer_figures()
        empty = {"influencer_id": 0, "influencer_name": "", "account_key": ""}
        return [dict(r) | figures.get(r["id"], empty) for r in rows]

    def customer_figures(self) -> dict[int, dict]:
        """Influencerin und Kanalkonto je Akte ab dem ersten Eingang (C5.1): über die erste
        Identität und ihr Konto; nie die erste Influencerin."""
        rows = self.db.execute(
            "SELECT ci.customer_id, a.key, a.influencer_id, f.name FROM channel_identities ci"
            " JOIN channel_accounts a ON a.platform = ci.platform"
            " AND a.platform_account_id = ci.account"
            " LEFT JOIN influencers f ON f.id = a.influencer_id ORDER BY ci.id"
        )
        out: dict[int, dict] = {}
        for r in rows:
            out.setdefault(
                r[0],
                {"influencer_id": r[2] or 0, "influencer_name": r[3] or "", "account_key": r[1]},
            )
        return out

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
        """Ereignisse für EVENT 26 (BUG-048): Akten-Ereignisse und jede neue Nachricht einer Akte
        (Eingang, Sendung, Systemkarte) – Liste, Ungelesen und Übersicht folgen ohne Öffnen."""
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at,"
            " CASE WHEN e.entity = 'customer' THEN e.entity_id"
            "  ELSE json_extract(e.data, '$.customer_id') END AS customer_id"
            " FROM events e WHERE e.id > ? AND (e.entity = 'customer' OR (e.entity = 'message'"
            "  AND e.event = 'added' AND json_extract(e.data, '$.customer_id') IS NOT NULL))"
            " ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit
