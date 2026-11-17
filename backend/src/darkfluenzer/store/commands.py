"""Befehlsjournal und Quittungen (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

import json

from .db import (
    now,
)


class CommandsMixin:
    """Befehlsjournal und Quittungen; Teil von ``Store``."""

    def command(self, request_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM commands WHERE request_id = ?", (request_id,))
        found = row.fetchone()
        return dict(found) if found else None

    def record_command(
        self,
        request_id: str,
        payload_sha: str,
        command: str,
        status: str,
        *,
        entity: str = "",
        detail: str = "",
        version: int = 0,
    ) -> None:
        """Befehl genau einmal festhalten (PRIMARY KEY request_id) samt erster Receipt; die
        Antwort auf eine Wiederholung derselben request_id ergibt sich aus diesem Eintrag."""
        with self.tx() as db:
            ts = now()
            cur = db.execute(
                "INSERT INTO commands (request_id, payload_sha, command, entity, status, detail,"
                " version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (request_id, payload_sha, command, entity, status, detail, version, ts, ts),
            )
            self._receipt(cur.lastrowid, request_id, command, status, entity, detail, version)

    def finish_command(
        self, request_id: str, status: str, *, detail: str = "", version: int | None = None
    ) -> bool:
        """Terminales Ergebnis eines angenommenen Befehls; bereits beendete bleiben unverändert."""
        with self.tx() as db:
            row = db.execute(
                "SELECT rowid, * FROM commands WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None or row["status"] != "accepted":
                return False
            final_version = row["version"] if version is None else version
            db.execute(
                "UPDATE commands SET status = ?, detail = ?, version = ?, updated_at = ?"
                " WHERE request_id = ?",
                (status, detail, final_version, now(), request_id),
            )
            self._receipt(
                row["rowid"],
                request_id,
                row["command"],
                status,
                row["entity"],
                detail,
                final_version,
            )
            return True

    def _receipt(
        self,
        rowid: int,
        request_id: str,
        command: str,
        status: str,
        entity: str,
        detail: str,
        version: int,
    ) -> None:
        self._event(
            "command",
            rowid,
            "receipt",
            request_id=request_id,
            command=command,
            status=status,
            target=entity,
            detail=detail,
            version=version,
        )

    def open_commands(self) -> list[dict]:
        """Angenommene, noch nicht beendete Befehle (nach einem Neustart zu klären)."""
        return [
            dict(r) for r in self.db.execute("SELECT * FROM commands WHERE status = 'accepted'")
        ]

    def receipts(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Receipts aus dem Journal mit Cursor > ``after`` (neueste ``limit``, aufsteigend)."""
        rows = self.db.execute(
            "SELECT id AS cursor, created_at AS committed_at, data FROM events"
            " WHERE entity = 'command' AND event = 'receipt' AND id > ? ORDER BY id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = []
        for r in rows[:limit]:
            data = json.loads(r["data"])
            data["entity"] = data.pop("target")
            recent.append({"cursor": r["cursor"], "committed_at": r["committed_at"]} | data)
        return recent[::-1], len(rows) > limit
