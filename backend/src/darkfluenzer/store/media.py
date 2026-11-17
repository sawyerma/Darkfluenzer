"""Medienindex, Inhaltsstufen, Vorlagen (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .db import (
    StoreError,
    now,
)
from .schema import (
    MEDIA_KINDS,
)


class MediaMixin:
    """Medienindex, Inhaltsstufen, Vorlagen; Teil von ``Store``."""

    def media_tier(self, media_id: int) -> str | None:
        row = self.db.execute("SELECT content_tier FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            raise StoreError(f"Medium {media_id} unbekannt.")
        return row[0]

    def raise_content_tier(self, media_id: int) -> None:
        """Inhaltsstufe eines Mediums auf „explizit“ anheben – nie absenken (Regel 13)."""
        with self.tx() as db:
            if self.media_tier(media_id) == "explizit":
                raise StoreError("Medium ist bereits explizit.")
            db.execute("UPDATE media SET content_tier = 'explizit' WHERE id = ?", (media_id,))
            self._event("media", media_id, "tier", content_tier="explizit")
            self.bump("media")

    def backfill_content_tiers(self, workflow_tiers: dict[str, str]) -> int:
        """Erstzuordnung für Jobs/Medien vor Migration 14: Stufe des Workflows (unbekannter
        Workflow = explizit) und höhere Stufe des Ausgangsmediums; Medien erben vom Job."""
        from ..media.models import higher_tier

        with self.tx() as db:
            rows = db.execute(
                "SELECT j.id, j.workflow, m.content_tier AS parent_tier, j.parent_media_id"
                " FROM jobs j LEFT JOIN media m ON m.id = j.parent_media_id"
                " WHERE j.content_tier IS NULL ORDER BY j.id"
            ).fetchall()
            for r in rows:
                parent = r["parent_tier"] if r["parent_media_id"] else "standard"
                tier = higher_tier(workflow_tiers.get(r["workflow"]), parent)
                db.execute("UPDATE jobs SET content_tier = ? WHERE id = ?", (tier, r["id"]))
            n = db.execute(
                "UPDATE media SET content_tier = (SELECT content_tier FROM jobs j"
                " WHERE j.id = media.job_id) WHERE content_tier IS NULL AND job_id IS NOT NULL"
            ).rowcount
            return len(rows) + n

    def add_reference(self, path: str, sha256: str, kind: str, source: str) -> tuple[int, bool]:
        """Vorlage genau einmal je Inhalt; liefert (ID, neu angelegt)."""
        with self.tx() as db:
            row = db.execute(
                "SELECT id FROM reference_files WHERE sha256 = ?", (sha256,)
            ).fetchone()
            if row:
                return row[0], False
            cur = db.execute(
                "INSERT INTO reference_files (sha256, path, kind, source, created_at)"
                " VALUES (?,?,?,?,?)",
                (sha256, path, kind, source, now()),
            )
            self._event("reference", cur.lastrowid, "added")
            self.bump("references")
            return cur.lastrowid, True

    def reference(self, reference_id: int) -> dict:
        row = self.db.execute(
            "SELECT * FROM reference_files WHERE id = ?", (reference_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"Vorlage {reference_id} unbekannt.")
        return dict(row)

    def reference_page(self, before: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT * FROM reference_files WHERE (? = 0 OR id < ?) ORDER BY id DESC LIMIT ?",
            (before, before, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]], len(rows) > limit

    def reference_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, e.entity_id AS reference_id"
            " FROM events e WHERE e.entity = 'reference' AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [dict(r) for r in rows[:limit]]
        return recent[::-1], len(rows) > limit

    def add_media(
        self,
        rel: str,
        sha: str,
        size: int,
        *,
        job_id: int | None = None,
        artifact_id: int | None = None,
        created_at: str | None = None,
    ) -> int | None:
        """Nimmt eine erzeugte Datei (Pfad relativ zu ``local/``) genau einmal in die Galerie auf.
        Gleiche Bytes oder gleicher Pfad -> keine zweite Aufnahme (None). Kundenbezug nur über
        Auftrag (Job/Artefakt), sonst eine stabile fortlaufende Nummer."""
        kind = MEDIA_KINDS.get(Path(rel).suffix.lower())
        if kind is None:
            raise StoreError(f"{rel}: kein Bild-/Videoformat")
        with self.tx() as db:
            if db.execute(
                "SELECT 1 FROM media WHERE sha256 = ? OR path = ?", (sha, rel)
            ).fetchone():
                return None
            order_id = None
            tier_job = job_id
            if artifact_id is not None:
                art = self.artifact(artifact_id)
                order_id, tier_job = art.order_id, art.job_id
            elif job_id is not None:
                order_id = db.execute(
                    "SELECT order_id FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()[0]
            tier_row = (
                db.execute("SELECT content_tier FROM jobs WHERE id = ?", (tier_job,)).fetchone()
                if tier_job is not None
                else None
            )
            content_tier = tier_row[0] if tier_row else None
            # IDs und Nummern gelöschter Einträge werden nie wieder vergeben: Zähler steigen nur
            # (SP0 Schritt 6, Migration 18 übernimmt den Stand aus dem Journal).
            media_id = db.execute(
                "UPDATE counters SET value = value + 1 WHERE name = 'media_id' RETURNING value"
            ).fetchone()[0]
            number = None
            if order_id is None:
                number = db.execute(
                    "UPDATE counters SET value = value + 1 WHERE name = 'media_number'"
                    " RETURNING value"
                ).fetchone()[0]
            db.execute(
                "INSERT INTO media (id, sha256, path, kind, size, job_id, artifact_id, order_id,"
                " number, created_at, content_tier) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    media_id,
                    sha,
                    rel,
                    kind,
                    size,
                    job_id,
                    artifact_id,
                    order_id,
                    number,
                    created_at or now(),
                    content_tier,
                ),
            )
            self._event("media", media_id, "added", path=rel)
            self.bump("media")
            return media_id

    def remove_media(self, ids: list[int]) -> list[dict]:
        """Entfernt Galerie-Einträge (nur ohne Kundenbezug) und hält jeden im Journal als
        'removed' fest; bereits gelöschte IDs werden übergangen. Liefert die entfernten Zeilen."""
        with self.tx() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    f"SELECT * FROM media WHERE id IN ({','.join('?' * len(ids))})", ids
                )
            ]
            if any(r["order_id"] is not None for r in rows):
                raise StoreError("Medien eines Kundenauftrags können nicht gelöscht werden.")
            for r in rows:
                db.execute("DELETE FROM media WHERE id = ?", (r["id"],))
                self._event("media", r["id"], "removed", path=r["path"], number=r["number"])
            if rows:
                self.bump("media")
        return rows

    _MEDIA_SELECT = (
        "SELECT m.*, j.workflow, j.params, o.order_no, c.customer_no, c.display_name FROM media m"
        " LEFT JOIN jobs j ON j.id = m.job_id LEFT JOIN orders o ON o.id = m.order_id"
        " LEFT JOIN customers c ON c.id = o.customer_id"
    )

    def _media_rows(self, rows: list[sqlite3.Row]) -> list[dict]:
        return [dict(r) | {"params": json.loads(r["params"] or "{}")} for r in rows]

    def media_page(self, before: int, limit: int) -> tuple[list[dict], bool]:
        """Galerieseite, neueste zuerst; ``before`` = 0 beginnt bei der neuesten Datei."""
        rows = self.db.execute(
            self._MEDIA_SELECT + " WHERE (? = 0 OR m.id < ?) ORDER BY m.id DESC LIMIT ?",
            (before, before, limit + 1),
        ).fetchall()
        return self._media_rows(rows[:limit]), len(rows) > limit

    def media_events(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Aufgenommene Medien aus dem Journal mit Cursor > ``after`` (neueste ``limit``,
        aufsteigend); zweiter Wert: ältere wurden ausgelassen."""
        rows = self.db.execute(
            "SELECT e.id AS cursor, e.created_at AS committed_at, x.* FROM events e JOIN ("
            + self._MEDIA_SELECT
            + ") x ON x.id = e.entity_id WHERE e.entity = 'media' AND e.event IN ('added', 'tier')"
            " AND e.id > ? ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return self._media_rows(rows[:limit])[::-1], len(rows) > limit

    def media_removed(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Gelöschte Medien aus dem Journal mit Cursor > ``after`` (neueste ``limit``,
        aufsteigend); zweiter Wert: ältere wurden ausgelassen."""
        rows = self.db.execute(
            "SELECT id AS cursor, created_at AS committed_at, entity_id AS media_id,"
            " json_extract(data, '$.path') AS path FROM events WHERE entity = 'media'"
            " AND event = 'removed' AND id > ? ORDER BY id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        return [dict(r) for r in rows[:limit]][::-1], len(rows) > limit

    def media_by_path(self, rel: str) -> dict | None:
        row = self.db.execute("SELECT * FROM media WHERE path = ?", (rel,)).fetchone()
        return dict(row) if row else None

    def add_media_checks(
        self, job_id: int, media_id: int | None, reference: str, checks: list[dict]
    ) -> None:
        """Messwerte der Prüfknoten eines Jobs festhalten (SP3 Schritt 7); ``media_id`` ist das
        geprüfte Medium (Ergebnis oder Eingabe), ``reference`` der Referenzsatz (Figur)."""
        with self.tx() as db:
            for c in checks:
                data = {k: v for k, v in c.items() if k not in ("check", "status")}
                db.execute(
                    "INSERT INTO media_checks (media_id, job_id, check_name, status, data,"
                    " reference, created_at) VALUES (?,?,?,?,?,?,?)",
                    (media_id, job_id, str(c.get("check", "")), str(c.get("status", "")),
                     json.dumps(data), reference, now()),
                )  # fmt: skip

    def media_checks(self, media_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM media_checks WHERE media_id = ? ORDER BY id", (media_id,)
        )
        return [dict(r) | {"data": json.loads(r["data"])} for r in rows]

    def media_by_sha(self, sha256: str) -> dict | None:
        """Medium mit genau diesem Inhalt (Herkunftsprüfung, z. B. Kloner-Befehl edit)."""
        if not sha256:
            return None
        row = self.db.execute("SELECT * FROM media WHERE sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None

    def media_children(self, media_id: int) -> list[int]:
        """Medien aus Aufträgen, deren Ausgangsmedium ``media_id`` ist (abgeleitete Versionen)."""
        rows = self.db.execute(
            "SELECT m.id FROM media m JOIN jobs j ON j.id = m.job_id"
            " WHERE j.parent_media_id = ? ORDER BY m.id",
            (media_id,),
        )
        return [r[0] for r in rows]

    def media_by_id(self, media_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return dict(row) if row else None

    def media_path_by_sha(self) -> dict[str, str]:
        """SHA-256 -> Pfad der indizierten Datei (gleicher Inhalt steht nur einmal im Index)."""
        return {r[0]: r[1] for r in self.db.execute("SELECT sha256, path FROM media")}

    def media_paths(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT path FROM media")}
