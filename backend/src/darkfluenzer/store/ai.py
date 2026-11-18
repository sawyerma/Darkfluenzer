"""KI-Läufe (SP4 Schritt 1): ai_runs und Studio-Sitzungen; Teil von ``Store``."""

from __future__ import annotations

import json

from .db import now


class AiMixin:
    """Messwerte und Nachweis je Lauf eines Sprachworkflows; Studio-Verlauf je Influencerin."""

    def add_ai_run(self, kind: str, workflow: str, **fields: object) -> int:
        """Lauf festhalten (Ergebnis oder Fehler) und im Journal melden (EVENT ai.result)."""
        cols = {"kind": kind, "workflow": workflow, **fields, "created_at": now()}
        for key in ("context", "gates"):
            if isinstance(cols.get(key), dict | list):
                cols[key] = json.dumps(cols[key], ensure_ascii=False)
        with self.tx() as db:
            run_id = db.execute(
                f"INSERT INTO ai_runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                tuple(cols.values()),
            ).lastrowid
            self._event("ai_run", run_id, "done", kind=kind, error=bool(fields.get("error")))
        return run_id

    def ai_run(self, run_id: int) -> dict:
        row = self.db.execute("SELECT * FROM ai_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else {}

    def ai_results(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Beendete Läufe aus dem Journal mit Cursor (events.id) > ``after``: höchstens die
        neuesten ``limit``, aufsteigend; zweiter Wert: ältere ausgelassen."""
        rows = self.db.execute(
            "SELECT e.id AS cursor, r.*, v.version AS persona_number FROM events e"
            " JOIN ai_runs r ON r.id = e.entity_id"
            " LEFT JOIN persona_versions v ON v.id = r.persona_version"
            " WHERE e.entity = 'ai_run' AND e.event = 'done' AND e.id > ?"
            " ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]][::-1], len(rows) > limit

    def studio_session(self, influencer_id: int) -> int:
        row = self.db.execute(
            "SELECT session FROM studio_sessions WHERE influencer_id = ?", (influencer_id,)
        ).fetchone()
        return row[0] if row else 1

    def reset_studio_session(self, influencer_id: int) -> int:
        """Neue Studio-Sitzung; frühere Läufe bleiben erhalten."""
        with self.tx() as db:
            db.execute(
                "INSERT INTO studio_sessions (influencer_id, session) VALUES (?, 2)"
                " ON CONFLICT(influencer_id) DO UPDATE SET session = session + 1",
                (influencer_id,),
            )
            session = self.studio_session(influencer_id)
            self._event("studio", influencer_id, "reset", session=session)
        return session

    def studio_turns(self, influencer_id: int, session: int, limit: int) -> list[dict]:
        """Letzte erfolgreiche Wechsel der Studio-Sitzung (Nachricht, Antwort), aufsteigend."""
        rows = self.db.execute(
            "SELECT message, answer FROM ai_runs WHERE kind = 'studio' AND influencer_id = ?"
            " AND session = ? AND error = '' ORDER BY id DESC LIMIT ?",
            (influencer_id, session, limit),
        ).fetchall()
        return [dict(r) for r in rows][::-1]

    def recent_ai_runs(self, limit: int) -> list[dict]:
        """Letzte Läufe (neueste zuerst) für den KI-Status, ohne Inhalte."""
        rows = self.db.execute(
            "SELECT id, kind, duration_ms, total_ms, error, created_at FROM ai_runs"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
