"""Influencerinnen, Charaktere, Default-Kontakt (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

import json

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

    def set_influencer_switches(
        self, influencer_id: int, text_ai: bool, auto_replies: bool
    ) -> None:
        """Schalter der Influencerin (C5.1): Text-KI und automatische Antworten."""
        with self.tx() as db:
            n = db.execute(
                "UPDATE influencers SET text_ai = ?, auto_replies = ? WHERE id = ?"
                " AND (text_ai != ? OR auto_replies != ?)",
                (int(text_ai), int(auto_replies), influencer_id, int(text_ai), int(auto_replies)),
            ).rowcount
            if n:
                self._event("influencer", influencer_id, "switches", text_ai=text_ai,
                            auto_replies=auto_replies)  # fmt: skip
                self.bump("influencers")

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

    # ------------------------------------------------------------------ Promptprofile (SP4 2)

    def persona_versions(self, influencer_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM persona_versions WHERE influencer_id = ? ORDER BY version",
            (influencer_id,),
        )
        return [
            dict(r) | {"blocks": json.loads(r["blocks"]), "params": json.loads(r["params"])}
            for r in rows
        ]

    def active_persona(self, influencer_id: int) -> dict | None:
        """Aktive Version des Promptprofils (Blöcke, Parameter) oder None."""
        row = self.db.execute(
            "SELECT v.* FROM influencers i JOIN persona_versions v ON v.id = i.persona_active"
            " WHERE i.id = ?",
            (influencer_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row) | {
            "blocks": json.loads(row["blocks"]),
            "params": json.loads(row["params"]),
        }

    def save_persona_version(
        self, influencer_id: int, blocks: dict, params: dict, note: str, *, activate: bool
    ) -> tuple[int, bool]:
        """Neue Version, wenn sich Blöcke oder Parameter von der letzten unterscheiden (leere
        Blöcke entfallen); mit ``activate`` sofort aktiv. Liefert (Version, neu angelegt)."""
        blocks = {k: v for k, v in blocks.items() if v.strip()}
        with self.tx() as db:
            if (
                db.execute("SELECT 1 FROM influencers WHERE id = ?", (influencer_id,)).fetchone()
                is None
            ):
                raise StoreError(f"Influencerin {influencer_id} unbekannt.")
            last = db.execute(
                "SELECT version, blocks, params FROM persona_versions WHERE influencer_id = ?"
                " ORDER BY version DESC LIMIT 1",
                (influencer_id,),
            ).fetchone()
            same = last is not None and (
                json.loads(last["blocks"]),
                json.loads(last["params"]),
            ) == (blocks, params)
            if same:
                version, created = last["version"], False
            else:
                version, created = (last["version"] + 1 if last else 1), True
                db.execute(
                    "INSERT INTO persona_versions (influencer_id, version, blocks, params, note,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (influencer_id, version, json.dumps(blocks, ensure_ascii=False),
                     json.dumps(params), note.strip(), now()),
                )  # fmt: skip
                self._event("influencer", influencer_id, "persona_saved", version=version)
            if activate:
                self.activate_persona_version(influencer_id, version)
            self.bump("influencers")
            return version, created

    def activate_persona_version(self, influencer_id: int, version: int) -> bool:
        """Version aktivieren bzw. auf einen früheren Stand zurücksetzen (Befehl 68); das Feld
        persona der Influencerin folgt dem Block „persona“. False: war schon aktiv."""
        with self.tx() as db:
            row = db.execute(
                "SELECT id, blocks FROM persona_versions WHERE influencer_id = ? AND version = ?",
                (influencer_id, version),
            ).fetchone()
            if row is None:
                raise StoreError(f"Version {version} des Promptprofils gibt es nicht.")
            text = json.loads(row["blocks"]).get("persona", "")
            # Revision (CAS des Profils) nur, wenn sich der sichtbare Persona-Text ändert
            n = db.execute(
                "UPDATE influencers SET persona_active = ?, revision = revision + (persona != ?),"
                " persona = ?, updated_at = ? WHERE id = ? AND coalesce(persona_active, 0) != ?",
                (row["id"], text, text, now(), influencer_id, row["id"]),
            ).rowcount
            if n:
                self._event("influencer", influencer_id, "persona_activated", version=version)
                self.bump("influencers")
            return bool(n)

    def characters(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM characters ORDER BY id")]

    def character(self, character_id: int) -> dict:
        row = self.db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
        if row is None:
            raise StoreError(f"Charakter {character_id} unbekannt.")
        return dict(row)

    def character_by_slug(self, slug: str) -> dict | None:
        """Charakter zum Kürzel (Ordner, LoRA-Ablage); None, wenn es keinen gibt."""
        row = self.db.execute("SELECT * FROM characters WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def save_character(
        self,
        character_id: int,
        revision: int,
        name: str,
        trigger: str,
        class_word: str,
        slug: str,
        probe_prompts: list[str] | None = None,
    ) -> dict:
        """Profil anlegen (``character_id`` 0: Ordner ``local/characters/<slug>``) oder Name,
        Trigger, Klasse und Probe-Prompts ändern (CAS auf die Revision); das Kürzel bleibt fest.
        ``probe_prompts=None`` lässt die gespeicherten Probe-Prompts unverändert."""
        name, trigger, class_word = name.strip(), trigger.strip(), class_word.strip()
        if not name or not trigger or not class_word:
            raise StoreError("Name, Trigger und Klasse des Charakters sind Pflicht.")
        probes = None if probe_prompts is None else [p.strip() for p in probe_prompts if p.strip()]
        with self.tx() as db:
            ts = now()
            if character_id == 0:
                taken = {
                    r[0] for r in db.execute("SELECT slug FROM characters WHERE slug IS NOT NULL")
                }
                unique, n = slug, 1
                while unique in taken:
                    n += 1
                    unique = f"{slug}-{n}"
                new_id = db.execute("SELECT coalesce(max(id), 0) + 1 FROM characters").fetchone()[0]
                folder = f"local/characters/{unique}"
                db.execute(
                    "INSERT INTO characters (id, name, data_dir, photos_dir, slug, trigger,"
                    " class_word, probe_prompts, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id, name, folder, f"{folder}/photos", unique, trigger, class_word,
                     json.dumps(probes or []), ts, ts),
                )  # fmt: skip
                character_id = new_id
            else:
                current = self.character(character_id)
                if current["revision"] != revision:
                    raise StoreError("Charakter wurde inzwischen geändert – Ansicht ist aktuell.")
                db.execute(
                    "UPDATE characters SET name = ?, trigger = ?, class_word = ?,"
                    " probe_prompts = coalesce(?, probe_prompts), revision = revision + 1,"
                    " updated_at = ? WHERE id = ?",
                    (name, trigger, class_word, None if probes is None else json.dumps(probes),
                     ts, character_id),
                )  # fmt: skip
            self._event("character", character_id, "saved", name=name)
            return self.character(character_id)

    def active_loras(self, character_id: int) -> dict[str, str]:
        """Aktive Charakter-LoRA je Architektur (SP3 Schritt 6)."""
        rows = self.db.execute(
            "SELECT arch, lora FROM character_loras WHERE character_id = ?", (character_id,)
        )
        return {r[0]: r[1] for r in rows}

    def set_active_lora(self, character_id: int, arch: str, lora: str) -> None:
        """Aktive LoRA einer Figur für eine Architektur setzen; leer = keine aktive mehr."""
        self.character(character_id)
        with self.tx() as db:
            if lora:
                db.execute(
                    "INSERT INTO character_loras (character_id, arch, lora, activated_at)"
                    " VALUES (?,?,?,?) ON CONFLICT (character_id, arch)"
                    " DO UPDATE SET lora = excluded.lora, activated_at = excluded.activated_at",
                    (character_id, arch, lora, now()),
                )
            else:
                db.execute(
                    "DELETE FROM character_loras WHERE character_id = ? AND arch = ?",
                    (character_id, arch),
                )
            db.execute(
                "UPDATE characters SET revision = revision + 1, updated_at = ? WHERE id = ?",
                (now(), character_id),
            )
            self._event("character", character_id, "lora_active", arch=arch, lora=lora)

    def set_character_slug(self, character_id: int, slug: str) -> dict:
        """Kürzel und Ordner nach dem Umzug in das Schema festschreiben (SP3 Schritt 1)."""
        folder = f"local/characters/{slug}"
        with self.tx() as db:
            db.execute(
                "UPDATE characters SET slug = ?, data_dir = ?, photos_dir = ?,"
                " revision = revision + 1, updated_at = ? WHERE id = ?",
                (slug, folder, f"{folder}/photos", now(), character_id),
            )
            self._event("character", character_id, "moved", slug=slug)
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
            rows = db.execute(
                "SELECT command, workflow, format, duration_s, finish FROM default_commands"
            ).fetchall()
            commands = {r["command"]: r["workflow"] for r in rows if r["workflow"]}
            profiles = {
                r["command"]: {
                    "format": r["format"], "duration_s": r["duration_s"], "finish": r["finish"]
                }
                for r in rows
            }  # fmt: skip
            return dict(row) | {
                "sender_ids": ids,
                "command_workflows": commands,
                "command_profiles": profiles,  # Ausgabeprofil je Befehl (SP1 Schritt 6)
            }

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
            "candidates",
            "cancel_word",
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
                rows = []
                for c, value in commands.items():  # Workflow oder {workflow, format, …}
                    v = value if isinstance(value, dict) else {"workflow": value}
                    row = (c, v.get("workflow", ""), v.get("format", ""),
                           float(v.get("duration_s") or 0), v.get("finish", ""))  # fmt: skip
                    if any(row[1:]):
                        rows.append(row)
                db.executemany(
                    "INSERT INTO default_commands (command, workflow, format, duration_s, finish)"
                    " VALUES (?,?,?,?,?)",
                    rows,
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
