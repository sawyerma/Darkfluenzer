"""Angebote, Zahlungseingänge, Gutscheine, Zahlungen (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

from datetime import UTC, datetime

from .db import (
    Order,
    StoreError,
    _uncovered,
    now,
)


class PaymentsMixin:
    """Angebote, Zahlungseingänge, Gutscheine, Zahlungen; Teil von ``Store``."""

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
