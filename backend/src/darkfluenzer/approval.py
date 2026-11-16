"""Liefer-Gate: PAYMENT_CONFIRMED && OPERATOR_APPROVED && ARTIFACT_HASH_MATCH && CUSTOMER_MATCH
&& CONTENT_TIER standard (PHASENPLAN_V0 Regel 13).

Wird im Backend erzwungen (hier) und zusätzlich durch SQLite-Trigger (store.py). Weder LLM noch
Frontend können das Gate umgehen. Diese Stufe bereitet Lieferungen nur vor und markiert sie –
echter Versand (Telegram) folgt in S5 und muss ``confirm_sent`` im Versandmoment aufrufen.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .store import Store, StoreError, now, sha256_file


@dataclass
class GateResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def check_gate(store: Store, order_no: str, artifact_id: int, customer_no: str) -> GateResult:
    """Prüft alle vier Bedingungen frisch gegen Datenbank UND Datei auf der Platte."""
    reasons: list[str] = []
    try:
        order = store.order(order_no)
        art = store.artifact(artifact_id)
    except StoreError as exc:
        return GateResult(False, [str(exc)])

    if order.customer_no != customer_no:
        reasons.append("CUSTOMER_MISMATCH: Auftrag gehört nicht zu diesem Kunden")
    if order.status != "approved":
        reasons.append(f"ORDER_STATUS: {order.status} (erwartet approved)")

    paid = store.db.execute(
        "SELECT 1 FROM payments WHERE order_id = ? AND status = 'confirmed' "
        "AND amount = ? AND currency = ?",
        (order.id, order.price_amount, order.currency),
    ).fetchone()
    if not paid:
        reasons.append("PAYMENT_NOT_CONFIRMED")

    last = store.db.execute(
        "SELECT decision, artifact_id, artifact_sha256 FROM approvals WHERE order_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (order.id,),
    ).fetchone()
    if last is None or last["decision"] != "approved" or last["artifact_id"] != art.id:
        reasons.append("OPERATOR_NOT_APPROVED: letzte Entscheidung gilt nicht diesem Artefakt")

    if art.order_id != order.id:
        reasons.append("ARTIFACT_ORDER_MISMATCH")
    # Regel 13: an Kunden nur Inhaltsstufe „standard“ (unbekannt zählt als explizit)
    tier = store.db.execute(
        "SELECT content_tier FROM media WHERE artifact_id = ?", (art.id,)
    ).fetchone()
    if tier is None or tier[0] != "standard":
        reasons.append("CONTENT_TIER: nur Inhaltsstufe standard an Kunden")
    path = store.local / art.path
    try:
        disk_sha = sha256_file(path)
    except OSError:
        disk_sha = None
    if disk_sha != art.sha256 or (last is not None and last["artifact_sha256"] != art.sha256):
        reasons.append("ARTIFACT_HASH_MISMATCH: Datei fehlt oder wurde verändert")

    return GateResult(not reasons, reasons)


def prepare_delivery(store: Store, order_no: str, artifact_id: int, customer_no: str) -> int:
    """Legt genau eine Lieferung je Auftrag an (idempotent). Gate wird vorher geprüft."""
    gate = check_gate(store, order_no, artifact_id, customer_no)
    if not gate.ok:
        raise StoreError("Lieferung gesperrt: " + "; ".join(gate.reasons))
    order = store.order(order_no)
    art = store.artifact(artifact_id)
    key = f"{order.order_no}:{art.sha256}"
    with store.tx() as db:
        existing = db.execute(
            "SELECT id FROM deliveries WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if existing:
            return existing["id"]
        try:
            cur = db.execute(
                "INSERT INTO deliveries (order_id, customer_id, artifact_id, artifact_sha256,"
                " idempotency_key, status, created_at) VALUES (?,?,?,?,?,'pending',?)",
                (order.id, order.customer_id, art.id, art.sha256, key, now()),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"Lieferung von der Datenbank abgewiesen: {exc}") from exc
        store._event("delivery", cur.lastrowid, "prepared", order_no=order_no, artifact=art.id)
        return cur.lastrowid


def confirm_sent(store: Store, delivery_id: int, external_id: str) -> None:
    """Nach erfolgreichem Versand: Gate im Versandmoment erneut prüfen, dann festschreiben."""
    row = store.db.execute(
        "SELECT d.*, o.order_no, c.customer_no FROM deliveries d "
        "JOIN orders o ON o.id = d.order_id JOIN customers c ON c.id = d.customer_id "
        "WHERE d.id = ?",
        (delivery_id,),
    ).fetchone()
    if row is None:
        raise StoreError(f"Lieferung {delivery_id} unbekannt.")
    if row["status"] == "sent":
        return  # idempotent: Retry nach Timeout liefert nicht doppelt
    gate = check_gate(store, row["order_no"], row["artifact_id"], row["customer_no"])
    if not gate.ok:
        raise StoreError("Versand gesperrt: " + "; ".join(gate.reasons))
    with store.tx() as db:
        try:
            db.execute(
                "UPDATE deliveries SET status = 'sent', external_id = ?, sent_at = ? WHERE id = ?",
                (external_id, now(), delivery_id),
            )
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"Versand von der Datenbank abgewiesen: {exc}") from exc
        store._event("delivery", delivery_id, "sent", external_id=external_id)
        store.transition(row["order_no"], "delivered", delivery_id=delivery_id)
