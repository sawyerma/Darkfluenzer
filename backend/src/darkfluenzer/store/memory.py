"""Gedächtnis (SP4 Schritt 5): Erinnerungen je Bereich mit Quelle, Zeit und Verlauf; Abruf über
FTS5; Teil von ``Store``."""

from __future__ import annotations

import re

from .db import StoreError, now

SCOPES = ("customer", "studio", "test")
LEVELS = ("customer", "memo", "event", "self")
_WORD = re.compile(r"[\wÄÖÜäöüß]{3,}")


def fts_query(text: str) -> str:
    """Suchanfrage aus den Wörtern eines Textes (ODER-Verknüpfung, in Anführungszeichen)."""
    words = list(dict.fromkeys(w.lower() for w in _WORD.findall(text)))
    return " OR ".join(f'"{w}"' for w in words[:24])


class MemoryMixin:
    """Erinnerungen strikt je (Bereich, Besitzer, Sitzung); nie bereichsübergreifend."""

    def add_memory(
        self, scope: str, owner_id: int, session: int, level: str, text: str, *,
        source: str, origin: str,
    ) -> int:  # fmt: skip
        if scope not in SCOPES or level not in LEVELS:
            raise StoreError(f"Gedächtnis: Bereich {scope} oder Ebene {level} unbekannt.")
        if not text.strip():
            raise StoreError("Gedächtnis: Text fehlt.")
        ts = now()
        with self.tx() as db:
            mid = db.execute(
                "INSERT INTO memories (scope, owner_id, session, level, text, source, origin,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (scope, owner_id, session, level, text.strip(), source, origin, ts, ts),
            ).lastrowid
            self._event("memory", mid, "added", scope=scope, owner=owner_id, origin=origin)
        return mid

    def memory(self, memory_id: int) -> dict:
        row = self.db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise StoreError(f"Erinnerung {memory_id} unbekannt.")
        return dict(row)

    def replace_memory(self, memory_id: int, text: str, *, source: str, origin: str) -> int:
        """Korrektur oder neuere Aussage: neue Erinnerung, die alte bleibt als ``replaced`` mit
        Verweis erhalten (Verlauf)."""
        old = self.memory(memory_id)
        if old["status"] != "active":
            raise StoreError(f"Erinnerung {memory_id} ist nicht mehr aktiv.")
        with self.tx() as db:
            new = self.add_memory(old["scope"], old["owner_id"], old["session"], old["level"],
                                  text, source=source, origin=origin)  # fmt: skip
            db.execute(
                "UPDATE memories SET status = 'replaced', replaced_by = ?, updated_at = ?"
                " WHERE id = ?",
                (new, now(), memory_id),
            )
            self._event("memory", memory_id, "replaced", by=new, origin=origin)
        return new

    def delete_memory(self, memory_id: int, *, origin: str) -> None:
        old = self.memory(memory_id)
        if old["status"] == "deleted":
            return
        with self.tx() as db:
            db.execute(
                "UPDATE memories SET status = 'deleted', updated_at = ? WHERE id = ?",
                (now(), memory_id),
            )
            self._event("memory", memory_id, "deleted", origin=origin)

    def memories(
        self, scope: str, owner_id: int, session: int, *, active_only: bool = True
    ) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM memories WHERE scope = ? AND owner_id = ? AND session = ?"
            + (" AND status = 'active'" if active_only else "")
            + " ORDER BY id",
            (scope, owner_id, session),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_memories(
        self, scope: str, owner_id: int, session: int, level: str, query: str, limit: int
    ) -> list[dict]:
        """Aktive Erinnerungen einer Ebene im Bereich: FTS5-Treffer zuerst (Rang), danach die
        jüngsten bis ``limit``."""
        if limit <= 0:
            return []
        base = (
            "SELECT m.*, {score} AS score FROM memories m {join} WHERE m.scope = ? AND"
            " m.owner_id = ? AND m.session = ? AND m.level = ? AND m.status = 'active'"
        )
        args = (scope, owner_id, session, level)
        hits: list[dict] = []
        q = fts_query(query)
        if q:
            hits = [dict(r) for r in self.db.execute(
                base.format(score="bm25(memories_fts)",
                            join="JOIN memories_fts f ON f.rowid = m.id")
                + " AND memories_fts MATCH ? ORDER BY score LIMIT ?",
                (*args, q, limit),
            )]  # fmt: skip
        seen = {h["id"] for h in hits}
        recent = [dict(r) for r in self.db.execute(
            base.format(score="NULL", join="") + " ORDER BY m.id DESC LIMIT ?", (*args, limit),
        )]  # fmt: skip
        return hits + [r for r in recent if r["id"] not in seen][: max(0, limit - len(hits))]

    def memory_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.event, e.created_at AS committed_at, m.* FROM events e"
            " JOIN memories m ON m.id = e.entity_id WHERE e.entity = 'memory' AND e.id > ?"
            " ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]][::-1], len(rows) > limit
