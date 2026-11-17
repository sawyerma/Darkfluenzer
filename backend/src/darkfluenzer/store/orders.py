"""Aufträge, Stufen, Artefakte, Freigaben, Lieferungen (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .db import (
    Artifact,
    Order,
    Stage,
    StoreError,
    _order,
    _stage,
    now,
    sha256_file,
)
from .schema import (
    ARTIFACT_ROLES,
    GALLERY_ROLES,
    MEDIA_KINDS,
    OPERATOR_TRANSITIONS,
    ORDER_KINDS,
    ORDER_SOURCES,
    STAGE_KINDS,
    TRANSITIONS,
)


class OrdersMixin:
    """Aufträge, Stufen, Artefakte, Freigaben, Lieferungen; Teil von ``Store``."""

    def set_order_kind(self, order_no: str, kind: str) -> None:
        if kind not in ORDER_KINDS:
            raise StoreError(f"Auftragstyp {kind!r} unbekannt.")
        with self.tx() as db:
            db.execute("UPDATE orders SET kind = ? WHERE order_no = ?", (kind, order_no))

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
            " LEFT JOIN media m ON m.id = coalesce("
            "(SELECT min(id) FROM media WHERE job_id = j.id), j.media_id)"
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

    def customer_orders(self, customer_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT o.*, f.product, f.hd, f.price_cents, f.expires_at, f.conversation_id"
            " FROM orders o LEFT JOIN offers f ON f.order_id = o.id"
            " WHERE o.customer_id = ? ORDER BY o.id DESC",
            (customer_id,),
        )
        return [dict(r) for r in rows]

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
