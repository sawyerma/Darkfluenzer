"""Influencerinnen, Charaktere, Default-Kontakt (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

from .db import (
    StoreError,
    now,
)


class ProfilesMixin:
    """Influencerinnen, Charaktere, Default-Kontakt; Teil von ``Store``."""

    def influencers(self) -> list[dict]:
        out = []
        for row in self.db.execute("SELECT * FROM influencers ORDER BY id"):
            prices = self.db.execute(
                "SELECT product, price_cents, hd_surcharge_cents FROM influencer_prices"
                " WHERE influencer_id = ? ORDER BY position",
                (row["id"],),
            )
            out.append(dict(row) | {"prices": [dict(p) for p in prices]})
        return out

    def save_influencer(
        self,
        influencer_id: int,
        revision: int,
        name: str,
        character_id: int | None,
        persona: str,
        ai_notice: str,
        prices: list[dict],
    ) -> int:
        """Profil anlegen (``influencer_id`` 0) oder ändern (CAS auf die Revision); die Preisliste
        wird in derselben Transaktion vollständig ersetzt. Liefert die Profil-ID."""
        name = name.strip()
        if not name:
            raise StoreError("Name der Influencerin fehlt.")
        with self.tx() as db:
            ts = now()
            if influencer_id == 0:
                influencer_id = db.execute(
                    "INSERT INTO influencers (name, character_id, persona, ai_notice, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?)",
                    (name, character_id, persona, ai_notice, ts, ts),
                ).lastrowid
            else:
                n = db.execute(
                    "UPDATE influencers SET name = ?, character_id = ?, persona = ?,"
                    " ai_notice = ?, revision = revision + 1, updated_at = ?"
                    " WHERE id = ? AND revision = ?",
                    (name, character_id, persona, ai_notice, ts, influencer_id, revision),
                ).rowcount
                if n != 1:
                    raise StoreError("Profil wurde inzwischen geändert – Ansicht ist aktuell.")
                db.execute(
                    "DELETE FROM influencer_prices WHERE influencer_id = ?", (influencer_id,)
                )
            for pos, item in enumerate(prices):
                db.execute(
                    "INSERT INTO influencer_prices (influencer_id, position, product, price_cents,"
                    " hd_surcharge_cents) VALUES (?,?,?,?,?)",
                    (influencer_id, pos, item["product"].strip(), item["price_cents"],
                     item["hd_surcharge_cents"]),
                )  # fmt: skip
            self._event("influencer", influencer_id, "saved", name=name)
            self.bump("influencers")
            return influencer_id

    def characters(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM characters ORDER BY id")]

    def character(self, character_id: int) -> dict:
        row = self.db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
        if row is None:
            raise StoreError(f"Charakter {character_id} unbekannt.")
        return dict(row)

    def save_character(self, character_id: int, revision: int, name: str, photos_dir: str) -> dict:
        """Profil anlegen (``character_id`` 0: eigener Ordner ``local/characters/<id>``) oder
        Name/Trainingsdatenordner ändern (CAS auf die Revision)."""
        name = name.strip()
        if not name:
            raise StoreError("Name des Charakters fehlt.")
        with self.tx() as db:
            ts = now()
            if character_id == 0:
                new_id = db.execute("SELECT coalesce(max(id), 0) + 1 FROM characters").fetchone()[0]
                data_dir = f"local/characters/{new_id}"
                db.execute(
                    "INSERT INTO characters (id, name, data_dir, photos_dir, created_at,"
                    " updated_at) VALUES (?,?,?,?,?,?)",
                    (new_id, name, data_dir, photos_dir or f"{data_dir}/photos", ts, ts),
                )
                character_id = new_id
            else:
                current = self.character(character_id)
                if current["revision"] != revision:
                    raise StoreError("Charakter wurde inzwischen geändert – Ansicht ist aktuell.")
                db.execute(
                    "UPDATE characters SET name = ?, photos_dir = ?, revision = revision + 1,"
                    " updated_at = ? WHERE id = ?",
                    (name, photos_dir or current["photos_dir"], ts, character_id),
                )
            self._event("character", character_id, "saved", name=name)
            return self.character(character_id)

    def _move_identity(self, identity_id: int, old: int, new: int) -> None:
        """Identität samt Verlauf einer anderen Akte zuordnen (ausdrückliche Betreiberzuordnung,
        z. B. eigene Telegram-ID als Default-Absender). Eine dadurch leere Akte ohne Aufträge
        entfällt; Akten mit Aufträgen bleiben unangetastet."""
        db = self.db
        if db.execute("SELECT 1 FROM orders WHERE customer_id = ?", (old,)).fetchone():
            raise StoreError("Diese Plattform-ID gehört zu einer Kundenakte mit Aufträgen.")
        db.execute("UPDATE channel_identities SET customer_id = ? WHERE id = ?", (new, identity_id))
        db.execute(
            "UPDATE channel_messages SET customer_id = ? WHERE conversation_id IN"
            " (SELECT id FROM channel_conversations WHERE identity_id = ?)",
            (new, identity_id),
        )
        if not db.execute(
            "SELECT 1 FROM channel_identities WHERE customer_id = ?", (old,)
        ).fetchone():
            db.execute("DELETE FROM customers WHERE id = ?", (old,))
            self._event("customer", old, "removed", merged_into=new)

    def default_contact(self) -> dict:
        """Interner Kontakt Default (genau einer, beim ersten Zugriff angelegt)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT d.*, c.customer_no FROM default_contact d"
                " JOIN customers c ON c.id = d.customer_id"
            ).fetchone()
            if row is None:
                ts = now()
                cid = db.execute(
                    "INSERT INTO customers (kind, display_name, created_at)"
                    " VALUES ('internal', 'Default', ?)",
                    (ts,),
                ).lastrowid
                db.execute(
                    "INSERT INTO default_contact (customer_id, updated_at) VALUES (?,?)", (cid, ts)
                )
                self._event("customer", cid, "created", internal=True)
                self.bump("customers")
                row = db.execute(
                    "SELECT d.*, c.customer_no FROM default_contact d"
                    " JOIN customers c ON c.id = d.customer_id"
                ).fetchone()
            ids = {
                r["platform"]: r["platform_user_id"]
                for r in db.execute(
                    "SELECT platform, platform_user_id FROM channel_identities"
                    " WHERE customer_id = ?",
                    (row["customer_id"],),
                )
            }
            commands = dict(db.execute("SELECT command, workflow FROM default_commands"))
            return dict(row) | {"sender_ids": ids, "command_workflows": commands}

    def update_default_contact(
        self, revision: int, fields: dict, sender_ids: dict, commands: dict | None = None
    ) -> dict:
        """Operator-Felder speichern (CAS auf die Revision); Absender-IDs sind Identitäten des
        internen Kontakts je Plattform (Konto = Kanal der Influencerin)."""
        allowed = {
            "process_commands",
            "auto_orders",
            "approval_mode",
            "influencer",
            "media_workflow",
            "video_workflow",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"Unbekannte Felder: {sorted(unknown)}")
        with self.tx() as db:
            current = self.default_contact()
            if current["revision"] != revision:
                raise StoreError(
                    "Default-Kontakt wurde inzwischen geändert – Ansicht ist aktualisiert."
                )
            if fields:
                cols = ", ".join(f"{k} = ?" for k in fields)
                db.execute(
                    f"UPDATE default_contact SET {cols}, revision = revision + 1, updated_at = ?",
                    (*fields.values(), now()),
                )
            else:
                db.execute(
                    "UPDATE default_contact SET revision = revision + 1, updated_at = ?", (now(),)
                )
            if commands is not None:  # vollständige Zuordnung ersetzt die bisherige
                db.execute("DELETE FROM default_commands")
                db.executemany(
                    "INSERT INTO default_commands (command, workflow) VALUES (?,?)",
                    [(c, w) for c, w in commands.items() if w],
                )
            cid = current["customer_id"]
            for (platform, account), sender in sender_ids.items():
                db.execute(
                    "DELETE FROM channel_identities WHERE customer_id = ? AND platform = ?"
                    " AND NOT EXISTS (SELECT 1 FROM channel_conversations WHERE identity_id ="
                    " channel_identities.id)",
                    (cid, platform),
                )
                if sender:
                    taken = db.execute(
                        "SELECT id, customer_id FROM channel_identities WHERE platform = ? AND"
                        " account = ? AND platform_user_id = ?",
                        (platform, account, sender),
                    ).fetchone()
                    if taken and taken["customer_id"] != cid:
                        self._move_identity(taken["id"], taken["customer_id"], cid)
                    if not taken:
                        db.execute(
                            "INSERT INTO channel_identities (customer_id, platform, account,"
                            " platform_user_id, verified, created_at) VALUES (?,?,?,?,0,?)",
                            (cid, platform, account, sender, now()),
                        )
            self._event("customer", cid, "updated", default=True)
            self.bump("customers")
            return self.default_contact()
