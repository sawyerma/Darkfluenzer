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
                self.start_payment_review(customer.id, "Gutschein erhalten")
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
            # Nachricht vom Handy: der Betreiber hat übernommen (SP4 Schritt 6)
            self.set_conversation_mode(conv, "manual", "Nachricht vom Handy")
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
        """Wartende ausgehende Nachrichten eines Kanals: Sendungen an den Default zuerst
        (SP1 Schritt 9), sonst in Eingangsreihenfolge."""
        rows = self.db.execute(
            "SELECT m.*, c.platform_conversation_id, cu.kind AS customer_kind"
            " FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " JOIN customers cu ON cu.id = m.customer_id"
            " WHERE m.direction = 'out' AND m.status = 'queued' AND i.platform = ?"
            " AND i.account = ? AND (m.scheduled_at IS NULL OR m.scheduled_at <= ?)"
            " ORDER BY cu.kind = 'internal' DESC, m.id",
            (platform, account, now()),
        )
        return [dict(r) | {"attachments": json.loads(r["attachments"])} for r in rows]

    # ------------------------------------------------------------------ Dialogbetrieb (SP4 6)

    def conversation_mode(self, conversation_id: int) -> str:
        row = self.db.execute(
            "SELECT mode FROM channel_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"Konversation {conversation_id} unbekannt.")
        return row[0]

    def set_conversation_mode(self, conversation_id: int, mode: str, why: str = "") -> bool:
        """Modus der Konversation: auto (KI antwortet), draft (nur Entwurf), manual (Betreiber);
        True, wenn geändert."""
        if mode not in ("auto", "draft", "manual"):
            raise StoreError(f"Modus {mode!r} unbekannt (auto, draft, manual).")
        with self.tx() as db:
            n = db.execute(
                "UPDATE channel_conversations SET mode = ? WHERE id = ? AND mode != ?",
                (mode, conversation_id, mode),
            ).rowcount
            if n:
                self._event("conversation", conversation_id, "mode", mode=mode, why=why)
                self.bump("conversations")
            return bool(n)

    def queue_reply(
        self,
        customer_id: int,
        conversation_id: int,
        text: str,
        *,
        status: str,
        ai_run_id: int | None,
        scheduled_at: str | None = None,
        reason: str = "",
        test: bool = False,
    ) -> int:
        """KI-Antwort festhalten (SP4 Schritte 6, 7): ``queued`` (mit Sendezeit) oder ``draft``
        (mit Grund); Bezug auf den Sprachlauf. Keine Revisionsprüfung: die Antwort entsteht aus
        dem gespeicherten Verlauf, eine neue Kundennachricht storniert sie."""
        if status not in ("queued", "draft"):
            raise StoreError(f"KI-Antwort mit Status {status!r} nicht möglich.")
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO channel_messages (customer_id, conversation_id, direction, text,"
                " status, error, ai_run_id, scheduled_at, sent_at, created_at, test)"
                " VALUES (?,?,'out',?,?,?,?,?,?,?,?)",
                (customer_id, conversation_id, text, status, reason or None, ai_run_id,
                 scheduled_at, now(), now(), int(test)),
            )  # fmt: skip
            db.execute(
                "UPDATE channel_conversations SET revision = revision + 1 WHERE id = ?",
                (conversation_id,),
            )
            self._event("message", cur.lastrowid, "added", customer_id=customer_id)
            self.bump("conversations")
            return cur.lastrowid

    def open_ai_replies(self, conversation_id: int) -> list[int]:
        """KI-Antworten dieser Konversation, die noch nicht gesendet werden (Entwurf oder
        geplant)."""
        rows = self.db.execute(
            "SELECT id FROM channel_messages WHERE conversation_id = ? AND ai_run_id IS NOT NULL"
            " AND status IN ('draft', 'queued') ORDER BY id",
            (conversation_id,),
        )
        return [r[0] for r in rows]

    def cancel_message(self, message_id: int, reason: str) -> bool:
        """Noch nicht gesendete Nachricht stornieren (bleibt als Karte sichtbar)."""
        with self.tx() as db:
            n = db.execute(
                "UPDATE channel_messages SET status = 'cancelled', error = ?"
                " WHERE id = ? AND status IN ('draft', 'queued')",
                (reason, message_id),
            ).rowcount
            if n:
                self._event("message", message_id, "status", status="cancelled", error=reason)
                self.bump("conversations")
            return bool(n)

    def release_message(self, message_id: int, text: str | None, scheduled_at: str | None) -> None:
        """Entwurf oder geplante Antwort freigeben: Text (optional neu), Sendezeit (None =
        jetzt)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT status FROM channel_messages WHERE id = ?", (message_id,)
            ).fetchone()
            if row is None or row[0] not in ("draft", "queued"):
                raise StoreError("Nur Entwürfe und geplante Antworten lassen sich freigeben.")
            db.execute(
                "UPDATE channel_messages SET status = 'queued', error = NULL, scheduled_at = ?,"
                " text = COALESCE(?, text), released = 1 WHERE id = ?",
                (scheduled_at, text, message_id),
            )
            self._event("message", message_id, "status", status="queued")
            self.bump("conversations")

    def hold_message(self, message_id: int, reason: str) -> None:
        """Geplante Antwort zurückhalten: wird Entwurf."""
        with self.tx() as db:
            n = db.execute(
                "UPDATE channel_messages SET status = 'draft', error = ?, scheduled_at = NULL"
                " WHERE id = ? AND status = 'queued' AND ai_run_id IS NOT NULL",
                (reason, message_id),
            ).rowcount
            if not n:
                raise StoreError("Nur geplante KI-Antworten lassen sich zurückhalten.")
            self._event("message", message_id, "status", status="draft", error=reason)
            self.bump("conversations")

    def dialog_turns(self, conversation_id: int, limit: int, *, test: bool = False) -> list[dict]:
        """Letzte Ein- und Ausgänge einer Konversation (ohne Systemkarten, Entwürfe,
        stornierte), aufsteigend; ``test``: nur der Verlauf des Kundentests (SP4 Schritt 8), sonst
        nur der Produktionsverlauf."""
        rows = self.db.execute(
            "SELECT id, direction, text, status FROM channel_messages WHERE conversation_id = ?"
            " AND direction IN ('in', 'out') AND status NOT IN ('draft', 'cancelled', 'failed')"
            " AND deleted_at IS NULL AND test = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, int(test), limit),
        )
        return [dict(r) for r in rows][::-1]

    def default_conversation(self) -> int | None:
        """Jüngste Konversation des Default-Kontakts (Karten zum Kundentest)."""
        row = self.db.execute(
            "SELECT c.id FROM channel_conversations c JOIN channel_identities i"
            " ON i.id = c.identity_id JOIN default_contact d ON d.customer_id = i.customer_id"
            " ORDER BY c.id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def notify_default(self, text: str) -> int | None:
        """Meldung ans Handy des Betreibers (Default-Chat, Produktion), z. B. Eingang nach Ablauf
        (E24); None, wenn noch kein Default-Chat besteht."""
        conv = self.default_conversation()
        if conv is None:
            return None
        default = self.default_contact()
        return self.queue_reply(default["customer_id"], conv, text, status="queued", ai_run_id=None)

    def mark_test(self, message_id: int) -> None:
        """Eingang gehört zum Kundentest (eigener Verlauf, nie Produktion)."""
        with self.tx() as db:
            db.execute("UPDATE channel_messages SET test = 1 WHERE id = ?", (message_id,))

    def queue_test_notice(self, conversation_id: int, text: str) -> int:
        """KI-Hinweis des Kundentests (einmal je Testsitzung, wie bei einem Kunden)."""
        default = self.default_contact()
        message_id = self.queue_reply(
            default["customer_id"], conversation_id, text, status="queued", ai_run_id=None,
            test=True,
        )  # fmt: skip
        with self.tx() as db:
            db.execute("UPDATE default_contact SET test_notice_message_id = ?", (message_id,))
        return message_id

    def test_reset(self, influencer_id: int | None) -> int:
        """Kundentest zurücksetzen: neue Sitzung, Hinweisstatus leer, Testgedächtnis gelöscht;
        liefert die neue Sitzung."""
        with self.tx() as db:
            db.execute(
                "UPDATE default_contact SET test_session = test_session + 1,"
                " test_notice_message_id = NULL, revision = revision + 1, updated_at = ?",
                (now(),),
            )
            if influencer_id:
                db.execute(
                    "UPDATE memories SET status = 'deleted', updated_at = ? WHERE scope = 'test'"
                    " AND owner_id = ? AND status = 'active'",
                    (now(), influencer_id),
                )
            session = db.execute("SELECT test_session FROM default_contact").fetchone()[0]
            self._event("customer", self.default_contact()["customer_id"], "test_reset",
                        session=session)  # fmt: skip
            self.bump("customers")
            return session

    def last_sent_at(self, conversation_id: int) -> str | None:
        """Zeit der letzten gesendeten eigenen Nachricht (Pause, Erstkontakt; SP4 Schritt 7)."""
        row = self.db.execute(
            "SELECT max(sent_at) FROM channel_messages WHERE conversation_id = ?"
            " AND direction = 'out' AND status = 'sent'",
            (conversation_id,),
        ).fetchone()
        return row[0] if row else None

    def last_inbound_ids(self, conversation_id: int, limit: int = 1) -> list[str]:
        """Plattform-IDs der letzten Eingänge (gelesen markieren)."""
        rows = self.db.execute(
            "SELECT platform_message_id FROM channel_messages WHERE conversation_id = ?"
            " AND direction = 'in' AND platform_message_id IS NOT NULL ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        return [r[0] for r in rows][::-1]

    def next_scheduled(self, platform: str, account: str) -> str | None:
        """Früheste geplante Sendezeit eines Kontos (Postausgang wacht dann auf)."""
        row = self.db.execute(
            "SELECT min(m.scheduled_at) FROM channel_messages m"
            " JOIN channel_conversations c ON c.id = m.conversation_id"
            " JOIN channel_identities i ON i.id = c.identity_id"
            " WHERE m.status = 'queued' AND m.scheduled_at IS NOT NULL AND i.platform = ?"
            " AND i.account = ?",
            (platform, account),
        ).fetchone()
        return row[0] if row else None

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

    def recent_unassigned_media(
        self, conversation_id: int, before_id: int, since: str
    ) -> list[dict]:
        """Eingänge dieser Konversation (desselben Absenders) vor ``before_id`` seit ``since`` mit
        gesicherten Anhängen, die noch keinem Auftrag gehören (SP1 Schritt 4), älteste zuerst."""
        rows = self.db.execute(
            "SELECT id FROM channel_messages WHERE conversation_id = ? AND direction = 'in'"
            " AND id < ? AND created_at >= ? AND order_id IS NULL AND attachments LIKE '%saved%'"
            " ORDER BY id",
            (conversation_id, before_id, since),
        )
        return [self.message(r[0]) for r in rows]

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
