"""Kanalkonten (SP2 Schritt 9a): Liste der Konten je Plattform mit Influencerin, Testbetrieb,
Betriebsart und Default-Absender; Teil von ``Store``."""

from __future__ import annotations

import json

from .db import StoreError, now

TRANSPORTS = {"telegram": "tdlib", "instagram": "graph", "whatsapp": "business_bot"}
MODES = ("production", "test", "off")


def _row(r) -> dict:
    return dict(r) | {
        "test_chat_ids": json.loads(r["test_chat_ids"]),
        "test_mode": bool(r["test_mode"]),
    }


class AccountsMixin:
    """Ein Konto je Zeile; die Plattform-Konto-ID ist nach der ersten Anmeldung unveränderlich."""

    def channel_accounts(self, *, active_only: bool = True) -> list[dict]:
        rows = self.db.execute(
            "SELECT a.*, i.name AS influencer_name FROM channel_accounts a"
            " LEFT JOIN influencers i ON i.id = a.influencer_id"
            + (" WHERE a.status = 'active'" if active_only else "")
            + " ORDER BY a.id"
        ).fetchall()
        return [_row(r) for r in rows]

    def channel_account(self, key: str) -> dict:
        row = self.db.execute(
            "SELECT a.*, i.name AS influencer_name FROM channel_accounts a"
            " LEFT JOIN influencers i ON i.id = a.influencer_id WHERE a.key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise StoreError(f"Kanalkonto {key} unbekannt.")
        return _row(row)

    def account_for(self, platform: str, platform_account_id: str) -> dict | None:
        """Konto zu einer Plattform-Konto-ID (Eingang, Identität); ohne ID das einzige Konto der
        Plattform, solange es genau eines gibt."""
        rows = [a for a in self.channel_accounts() if a["platform"] == platform]
        hit = [a for a in rows if a["platform_account_id"] == platform_account_id]
        if hit:
            return hit[0]
        return rows[0] if len(rows) == 1 and not rows[0]["platform_account_id"] else None

    def import_channel_account(self, seed: dict) -> bool:
        """Konto aus der bisherigen Konfiguration übernehmen, falls das Kürzel noch fehlt."""
        ts = now()
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO channel_accounts (key, platform, influencer_id, test_mode,"
                " test_chat_ids, default_sender_id, customer_transport, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO NOTHING",
                (seed["key"], seed["platform"], seed.get("influencer_id"),
                 int(seed.get("test_mode", True)), json.dumps(list(seed.get("test_chat_ids", ()))),
                 seed.get("default_sender_id", ""), TRANSPORTS[seed["platform"]], ts, ts),
            )  # fmt: skip
            if cur.rowcount:
                self._event("channel_account", cur.lastrowid, "imported", key=seed["key"])
                self.bump("channels")
            return bool(cur.rowcount)

    def set_account_platform_id(self, key: str, platform_account_id: str) -> None:
        """Nach der Anmeldung: Konto-ID festhalten; eine andere ID als die gespeicherte ist ein
        anderes Konto und wird abgewiesen."""
        acc = self.channel_account(key)
        if acc["platform_account_id"] == platform_account_id or not platform_account_id:
            return
        if acc["platform_account_id"]:
            raise StoreError(
                f"Kanalkonto {key} gehört zu {acc['platform_account_id']}, angemeldet ist "
                f"{platform_account_id}."
            )
        with self.tx() as db:
            db.execute(
                "UPDATE channel_accounts SET platform_account_id = ?, updated_at = ? WHERE key = ?",
                (platform_account_id, now(), key),
            )
            self._event("channel_account", acc["id"], "bound", account=platform_account_id)
            self.bump("channels")

    def set_account_mode(self, key: str, mode: str) -> None:
        """Betriebsart des Kontos für seine Default-Identität (SP1 Schritt 12): production,
        test oder off."""
        if mode not in MODES:
            raise StoreError(f"Betriebsart {mode!r} unbekannt (erlaubt: {', '.join(MODES)}).")
        acc = self.channel_account(key)
        if acc["operating_mode"] == mode:
            return
        with self.tx() as db:
            db.execute(
                "UPDATE channel_accounts SET operating_mode = ?, updated_at = ? WHERE key = ?",
                (mode, now(), key),
            )
            self._event("channel_account", acc["id"], "mode", mode=mode)
            self.bump("channels")

    def account_mode(self, platform: str, account: str) -> str:
        """Betriebsart des Kontos einer Plattform-Konto-ID; ohne Konto ``production``."""
        acc = self.account_for(platform, account)
        return acc["operating_mode"] if acc else "production"

    def assign_account_influencer(self, key: str, influencer_id: int | None) -> None:
        acc = self.channel_account(key)
        if (
            influencer_id
            and not self.db.execute(
                "SELECT 1 FROM influencers WHERE id = ?", (influencer_id,)
            ).fetchone()
        ):
            raise StoreError("Influencerin unbekannt.")
        with self.tx() as db:
            db.execute(
                "UPDATE channel_accounts SET influencer_id = ?, updated_at = ? WHERE key = ?",
                (influencer_id or None, now(), key),
            )
            self._event("channel_account", acc["id"], "influencer", influencer=influencer_id or 0)
            self.bump("channels")

    def influencer_for_identity(self, identity: dict) -> int | None:
        """Influencerin einer Kanalidentität über ihr Konto (nie die erste Influencerin)."""
        acc = self.account_for(identity["platform"], identity["account"])
        return acc["influencer_id"] if acc else None
