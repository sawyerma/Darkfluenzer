"""Angebote, Zahlungseingänge, Gutscheine, Zahlungen (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
        *,
        product_id: int | None = None,
        kind: str = "image",
        facts: str = "",
        delivery_s: float | None = None,
        payments: list[dict] | None = None,
        test: bool = False,
        wish: str = "",
        wish_source: str = "",
    ) -> Order:
        """Kundenauftrag mit Angebot (Status offered) und eindeutigen Beträgen je Krypto-Weg
        (method -> (Dezimaltext, genannte Adresse, Kurs, Kurszeit)); ``payments`` = je
        angebotenem Zahlungsweg Betrag, Währung, Ziel, Hinweis (SP5 Schritt 2), ``facts`` = der
        Faktenblock wie gesendet. Alles in einer Transaktion."""
        with self.tx() as db:
            label = f"{product} + HD" if hd else product
            order = self.create_order(customer_id, kind, label, test=test)  # Art vom Produkt
            self.set_offer(order.order_no, label, price_cents, "EUR")
            db.execute(
                "INSERT INTO offers (order_id, conversation_id, product, hd, price_cents,"
                " expires_at, created_at, product_id, facts, delivery_s, wish, wish_source)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (order.id, conversation_id, product, int(hd), price_cents, expires_at, now(),
                 product_id, facts, delivery_s, wish.strip(), wish_source.strip()),
            )  # fmt: skip
            for p in payments or []:
                db.execute(
                    "INSERT INTO offer_payments (order_id, way, amount, currency, target, note)"
                    " VALUES (?,?,?,?,?,?)",
                    (order.id, p["way"], p["amount"], p["currency"], p.get("target", ""),
                     p.get("note", "")),
                )  # fmt: skip
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
        return dict(row) | {
            "amounts": {r["method"]: r["amount"] for r in amounts},
            "payments": self.offer_payments(order_id),
        }

    def release_test_order(self, order_no: str, by: str) -> None:
        """Testfreigabe statt Zahlung (SP5 Schritt 12): nur Testaufträge der internen Akte;
        offered -> accepted -> paid ohne Eingang und ohne Zahlung (Wallet bleibt leer)."""
        with self.tx():
            order = self.order(order_no)
            if not order.test:
                raise StoreError(f"{order_no} ist kein Testauftrag – Freigabe nur mit Zahlung.")
            self.transition(order_no, "accepted", by=by)
            self.transition(order_no, "paid", by=by, test=True)
            self.bump("payments")

    def open_test_orders(self, platform: str, account: str) -> list[str]:
        """Offene Testaufträge der internen Akte, deren Konversation zu diesem Konto gehört."""
        rows = self.db.execute(
            "SELECT o.order_no FROM orders o JOIN offers f ON f.order_id = o.id"
            " JOIN channel_conversations c ON c.id = f.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id WHERE o.test = 1"
            " AND i.platform = ? AND i.account = ?"
            " AND o.status NOT IN ('delivered', 'cancelled', 'refunded') ORDER BY o.id",
            (platform, account),
        )
        return [r[0] for r in rows]

    def test_delivery_allowed(self, order_id: int) -> bool:
        """Gleiche Bedingungen wie die Liefer-Trigger (SP5 Schritt 12): Testauftrag der internen
        Default-Akte, Ziel = Konversation des Angebots, Identität verifiziert, Betriebsart test."""
        row = self.db.execute(
            "SELECT 1 FROM orders o JOIN customers cu ON cu.id = o.customer_id"
            " AND cu.kind = 'internal' JOIN default_contact d ON d.customer_id = o.customer_id"
            " JOIN offers f ON f.order_id = o.id"
            " JOIN channel_conversations c ON c.id = f.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id AND i.customer_id = o.customer_id"
            " AND i.verified = 1 JOIN channel_accounts a ON a.platform = i.platform"
            " AND a.platform_account_id = i.account AND a.operating_mode = 'test'"
            " WHERE o.id = ? AND o.test = 1",
            (order_id,),
        ).fetchone()
        return row is not None

    def parked_orders(self, conversation_id: int) -> list[str]:
        """Aufträge dieser Konversation, deren Zustellung auf Kontakt wartet (awaiting_contact)."""
        rows = self.db.execute(
            "SELECT o.order_no FROM orders o JOIN offers f ON f.order_id = o.id"
            " WHERE f.conversation_id = ? AND o.status = 'awaiting_contact' ORDER BY o.id",
            (conversation_id,),
        )
        return [r[0] for r in rows]

    def last_approved_artifact(self, order_id: int):
        """Artefakt der letzten Freigabe eines Auftrags (oder None)."""
        row = self.db.execute(
            "SELECT artifact_id, decision FROM approvals WHERE order_id = ? ORDER BY id DESC"
            " LIMIT 1",
            (order_id,),
        ).fetchone()
        if row is None or row["decision"] != "approved":
            return None
        return self.artifact(row["artifact_id"])

    def mark_production_started(self, order_id: int) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE offers SET production_started_at = ? WHERE order_id = ?", (now(), order_id)
            )

    def delayed_orders(self, at: str) -> list[dict]:
        """Aufträge in Produktion, deren zugesagte Lieferzeit (Start + Lieferzeit) vorbei ist und
        die noch keine Verzugsnachricht haben (SP5 Schritt 6: genau eine)."""
        rows = self.db.execute(
            "SELECT o.order_no, o.id, o.customer_id, o.test, f.conversation_id,"
            " f.production_started_at, f.delivery_s FROM orders o JOIN offers f"
            " ON f.order_id = o.id WHERE o.status IN ('producing', 'review')"
            " AND f.production_started_at IS NOT NULL AND f.delivery_s > 0"
            " AND f.delay_notice_at IS NULL"
        ).fetchall()
        out = []
        for r in rows:
            due = datetime.fromisoformat(r["production_started_at"]) + timedelta(
                seconds=r["delivery_s"]
            )
            if due.isoformat(timespec="milliseconds") < at:
                out.append(dict(r))
        return out

    def mark_delay_notice(self, order_id: int) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE offers SET delay_notice_at = ? WHERE order_id = ?", (now(), order_id)
            )

    def set_offer_facts(self, order_id: int, facts: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE offers SET facts = ? WHERE order_id = ?", (facts, order_id))

    def offer_payments(self, order_id: int) -> list[dict]:
        """Angebotene Zahlungswege in der Reihenfolge der Influencerin (Anlage)."""
        rows = self.db.execute(
            "SELECT way, amount, currency, target, note FROM offer_payments WHERE order_id = ?"
            " ORDER BY rowid",
            (order_id,),
        )
        return [dict(r) for r in rows]

    def open_offer_of(self, conversation_id: int) -> dict | None:
        """Jüngstes Angebot der Konversation, das noch auf Zahlung wartet (offered,
        payment_review); None, wenn keins."""
        row = self.db.execute(
            "SELECT o.order_no, o.status, f.* FROM orders o JOIN offers f ON f.order_id = o.id"
            " WHERE f.conversation_id = ? AND o.status IN ('offered', 'payment_review')"
            " ORDER BY o.id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return dict(row) if row else None

    def last_rejection(self, conversation_id: int) -> str | None:
        """Zeit der letzten Ablehnung eines Angebots in der Konversation (Sperrzeit)."""
        row = self.db.execute(
            "SELECT max(o.updated_at) FROM orders o JOIN offers f ON f.order_id = o.id"
            " WHERE f.conversation_id = ? AND o.status = 'cancelled'"
            " AND o.status_reason = 'abgelehnt'",
            (conversation_id,),
        ).fetchone()
        return row[0] if row else None

    def reject_offer(self, order_no: str, by: str) -> None:
        """Kunde lehnt ab (Einstufung, SP5 Schritt 2): Auftrag cancelled mit Grund „abgelehnt“;
        danach gilt die Sperrzeit der Influencerin."""
        with self.tx():
            self.transition(order_no, "cancelled", reason="abgelehnt", by=by)
            order = self.order(order_no)
            offer = self.offer(order.id)
            if offer:
                self.add_system_card(
                    offer["conversation_id"], f"ANGEBOT ABGELEHNT · {order_no}", order_id=order.id
                )

    def expire_offers(self, at: str) -> list[str]:
        """Zeitaufgabe (SP5 Schritt 2): Angebote im Status offered mit abgelaufener Frist ->
        cancelled mit Grund „abgelaufen“ und Karte; in payment_review ruht die Frist."""
        rows = self.db.execute(
            "SELECT o.order_no, o.id, f.conversation_id FROM orders o"
            " JOIN offers f ON f.order_id = o.id WHERE o.status = 'offered' AND f.expires_at < ?",
            (at,),
        ).fetchall()
        done = []
        for r in rows:
            with self.tx():
                self.transition(r["order_no"], "cancelled", reason="abgelaufen", by="Frist")
                self.add_system_card(
                    r["conversation_id"], f"ANGEBOT ABGELAUFEN · {r['order_no']}", order_id=r["id"]
                )
            done.append(r["order_no"])
        return done

    def start_payment_review(self, customer_id: int, why: str) -> str | None:
        """Zahlungsnachweis eingegangen (Gutscheincode, später begonnene PayPal-Zahlung): jüngstes
        offenes Angebot der Akte nach payment_review, die Frist ruht ab jetzt. Liefert die
        Auftragsnummer oder None."""
        with self.tx() as db:
            row = db.execute(
                "SELECT o.order_no, o.id, f.conversation_id FROM orders o"
                " JOIN offers f ON f.order_id = o.id WHERE o.customer_id = ?"
                " AND o.status = 'offered' ORDER BY o.id DESC LIMIT 1",
                (customer_id,),
            ).fetchone()
            if row is None:
                return None
            self.transition(row["order_no"], "payment_review", by=why)
            db.execute(
                "UPDATE offers SET review_started_at = ? WHERE order_id = ?", (now(), row["id"])
            )
            self.add_system_card(
                row["conversation_id"],
                f"ZAHLUNG IN PRÜFUNG · {why} · {row['order_no']} – Frist ruht",
                order_id=row["id"],
            )
            return row["order_no"]

    def end_payment_review(self, customer_id: int, why: str) -> str | None:
        """Nachweis abgelehnt: zurück nach offered, die Frist verlängert sich um die Prüfdauer
        (Restfrist). Nur, wenn kein weiterer Gutschein der Akte offen ist."""
        with self.tx() as db:
            pending = db.execute(
                "SELECT 1 FROM vouchers WHERE customer_id = ? AND status = 'pending'",
                (customer_id,),
            ).fetchone()
            row = db.execute(
                "SELECT o.order_no, o.id, f.conversation_id, f.expires_at, f.review_started_at"
                " FROM orders o JOIN offers f ON f.order_id = o.id WHERE o.customer_id = ?"
                " AND o.status = 'payment_review' ORDER BY o.id DESC LIMIT 1",
                (customer_id,),
            ).fetchone()
            if row is None or pending:
                return None
            started = datetime.fromisoformat(row["review_started_at"] or now())
            paused = datetime.now(UTC) - started
            expires = datetime.fromisoformat(row["expires_at"]) + paused
            until = expires.isoformat(timespec="milliseconds")
            db.execute(
                "UPDATE offers SET expires_at = ?, review_started_at = NULL WHERE order_id = ?",
                (until, row["id"]),
            )
            self.transition(row["order_no"], "offered", by=why)
            local = expires.astimezone().strftime("%d.%m.%Y, %H:%M Uhr")
            self.add_system_card(
                row["conversation_id"],
                f"ZAHLUNG ABGELEHNT · {why} · {row['order_no']} – Angebot gilt bis {local}",
                order_id=row["id"],
            )
            return row["order_no"]

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
            if order.source != "customer" or order.status not in (
                "offered",
                "payment_review",
                "accepted",
            ):
                raise StoreError(f"{order_no}: kein offenes Angebot ({order.status}).")
            if reason := _uncovered(inflow, order.price_amount or 0, self.offer(order.id)):
                raise StoreError(
                    f"Eingang deckt den Angebotspreis nicht ({reason}) – bleibt nicht zugeordnet."
                )
            if order.status in ("offered", "payment_review"):
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
            " AND f.created_at <= ? AND (f.expires_at >= ? OR o.status = 'payment_review')"
            " AND o.status IN ('offered', 'payment_review', 'accepted')",
            (inflow["method"], inflow["amount"], inflow["detected_at"], inflow["detected_at"]),
        ).fetchone()
        if hit:
            self.assign_inflow(payment_id, hit["order_no"], "automatisch")
            return
        late = db.execute(
            "SELECT o.order_no, o.id, f.conversation_id FROM offer_amounts a"
            " JOIN offers f ON f.order_id = a.order_id JOIN orders o ON o.id = a.order_id"
            " WHERE a.method = ? AND a.amount = ? AND o.status = 'cancelled'",
            (inflow["method"], inflow["amount"]),
        ).fetchone()
        if late:  # E24: keine automatische Neuzuordnung, der Betreiber entscheidet
            text = (
                f"EINGANG NACH ABLAUF · {inflow['asset']} {inflow['amount']} passt zu "
                f"{late['order_no']} (nicht mehr gültig) – neuem Angebot zuordnen oder erstatten"
            )
            self.add_system_card(late["conversation_id"], text, order_id=late["id"])
            self.notify_default(text)

    def open_offers(self) -> list[dict]:
        """Angebote, die noch auf Zahlung warten (Ziele für Befehl 41), neueste zuerst."""
        rows = self.db.execute(
            "SELECT o.id, o.order_no, o.status, o.customer_id, c.customer_no, c.display_name,"
            " f.product, f.hd, f.price_cents, f.expires_at FROM orders o"
            " JOIN offers f ON f.order_id = o.id"
            " JOIN customers c ON c.id = o.customer_id"
            " WHERE o.status IN ('offered', 'payment_review', 'accepted') AND o.test = 0"
            " ORDER BY o.id DESC"
        ).fetchall()
        return [dict(r) | {"payments": self.offer_payments(r["id"])} for r in rows]

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
            customer = db.execute(
                "SELECT customer_id FROM vouchers WHERE id = ?", (voucher_id,)
            ).fetchone()[0]
            self.end_payment_review(customer, "Gutschein abgelehnt")

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
                " AND status IN ('offered', 'payment_review', 'accepted') AND price_amount <= ?"
                " ORDER BY id DESC",
                (v["customer_id"], amount_cents),
            ).fetchone()
            if open_order:
                self.assign_inflow(payment_id, open_order["order_no"], "Gutschein")
            else:  # deckt keinen Angebotspreis: Prüfung endet, Angebot läuft mit Restfrist
                self.end_payment_review(v["customer_id"], "Gutschein deckt den Preis nicht")
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
        block = row["block"] if block is None else block  # None: Block unverändert
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

    def update_confirmations(
        self, payment_id: int, confirmations: int, required: int, block: int | None = None
    ) -> bool:
        """Bestätigungen fortschreiben; ``block``: Transaktion liegt inzwischen in diesem Block."""
        with self.tx() as db:
            return self._advance(db, payment_id, block, confirmations, required)

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
