"""Renderjobs und Abschnitte (SP0 Schritt 2, bisher ``store.py``)."""

from __future__ import annotations

import json
from datetime import datetime

from .db import (
    StoreError,
    now,
)

# Laufparameter, die die Dauer bestimmen (Schätzung nur aus Läufen mit denselben Werten)
RUN_SIGNATURE = ("steps", "width", "height", "duration_s", "segment_s", "train_size", "batch_size")
ESTIMATE_SCAN = 20  # so viele Läufe je gewünschter Messung werden nach gleichen Werten durchsucht


class JobsMixin:
    """Renderjobs und Abschnitte; Teil von ``Store``."""

    def create_job(
        self,
        order_no: str | None,
        engine: str,
        workflow: str,
        prompt: str,
        params: dict,
        seeds: list,
        *,
        parent_media_id: int | None = None,
        command: dict | None = None,
        stage_id: int | None = None,
        content_tier: str | None = None,
        priority: str = "cockpit",
    ) -> int:
        """Job anlegen; ``order_no=None`` für Renderungen ohne Kundenbezug (Evaluation).
        ``command``: auslösender Befehl (``record_command``-Argumente) – Job und Befehlsjournal
        entstehen in EINEM Commit, damit eine Wiederholung nie einen zweiten Job erzeugt."""
        with self.tx() as db:
            order_id = self.order(order_no).id if order_no else None
            if (
                order_id is None and stage_id is not None
            ):  # bugs_v1 BUG-006: Kundenauftrag ab Anlage
                row = db.execute(
                    "SELECT o.id FROM order_stages s JOIN orders o ON o.id = s.order_id"
                    " WHERE s.id = ? AND o.source = 'customer'",
                    (stage_id,),
                ).fetchone()
                order_id = row[0] if row else None
            ts = now()
            cur = db.execute(
                "INSERT INTO jobs (order_id, engine, workflow, prompt, params, seeds, created_at,"
                " updated_at, parent_media_id, request_id, stage_id, content_tier, priority)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    order_id,
                    engine,
                    workflow,
                    prompt,
                    json.dumps(params),
                    json.dumps(seeds),
                    ts,
                    ts,
                    parent_media_id,
                    command["request_id"] if command else None,
                    stage_id,
                    content_tier,
                    priority,
                ),
            )
            job_id = cur.lastrowid
            self._event("job", job_id, "created", order_no=order_no, workflow=workflow)
            self.bump("jobs")
            if command:
                self.record_command(**command, entity=f"job:{job_id}")
            return job_id

    def set_job_status(
        self, job_id: int, status: str, error: str | None = None, **result: object
    ) -> None:
        """Statuswechsel mit Journal-Ereignis; der Abschluss (done/failed) trägt das Ergebnis und
        beendet im selben Commit den auslösenden Befehl (Receipt)."""
        with self.tx() as db:
            db.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, now(), job_id),
            )
            self._event("job", job_id, "status", status=status, error=error, **result)
            self.bump("jobs")
            if status in ("done", "failed"):
                rid = db.execute("SELECT request_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if rid and rid[0]:
                    final = (
                        "completed"
                        if status == "done"
                        else "cancelled"
                        if result.get("cancelled")
                        else "failed"
                    )
                    self.finish_command(rid[0], final, detail=error or "")

    def job_segments(self, job_id: int) -> dict[int, dict]:
        rows = self.db.execute("SELECT * FROM job_segments WHERE job_id = ?", (job_id,))
        return {r["idx"]: dict(r) for r in rows}

    def copy_segments(self, source_job: int, target_job: int) -> int:
        """Fertige Abschnitte eines gescheiterten Jobs in seinen Wiederholungs-Job übernehmen
        (gleiche Parameter: dieselbe Fortsetzung, kein erneutes Rendern). Liefert die Anzahl."""
        with self.tx() as db:
            return db.execute(
                "INSERT INTO job_segments (job_id, idx, video, last_frame, duration_s, done_at)"
                " SELECT ?, idx, video, last_frame, duration_s, done_at FROM job_segments"
                " WHERE job_id = ? AND done_at IS NOT NULL AND idx < ("
                "   SELECT coalesce(min(idx), 1000000) FROM job_segments"
                "   WHERE job_id = ? AND done_at IS NULL)",
                (target_job, source_job, source_job),
            ).rowcount

    def segment_submitted(self, job_id: int, idx: int, prompt_id: str) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO job_segments (job_id, idx, prompt_id) VALUES (?,?,?)"
                " ON CONFLICT (job_id, idx) DO UPDATE SET prompt_id = excluded.prompt_id",
                (job_id, idx, prompt_id),
            )

    def segment_done(
        self, job_id: int, idx: int, video: str, last_frame: str, duration_s: float
    ) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO job_segments (job_id, idx, video, last_frame, duration_s, done_at)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT (job_id, idx) DO UPDATE SET"
                " video = excluded.video, last_frame = excluded.last_frame,"
                " duration_s = excluded.duration_s, done_at = excluded.done_at",
                (job_id, idx, video, last_frame, duration_s, now()),
            )
            self._event("job", job_id, "segment", idx=idx)

    def set_job_submitted(
        self, job_id: int, prompt_id: str, graph: dict, workflow_sha: str
    ) -> None:
        """Bei ComfyUI eingereicht: exakter API-Graph, Workflow-Hash und prompt_id (Wiederanlauf
        und Reproduzierbarkeit)."""
        with self.tx() as db:
            db.execute(
                "UPDATE jobs SET prompt_id = ?, graph = ?, workflow_sha256 = ?, updated_at = ?"
                " WHERE id = ?",
                (prompt_id, json.dumps(graph, ensure_ascii=False), workflow_sha, now(), job_id),
            )
            self._event("job", job_id, "submitted", prompt_id=prompt_id)

    def requeue_job(self, job_id: int) -> None:
        """Nie bei ComfyUI eingereichter, unterbrochener Job läuft nach dem Neustart erneut."""
        with self.tx() as db:
            cur = db.execute(
                "UPDATE jobs SET status = 'queued', updated_at = ? WHERE id = ?"
                " AND status = 'running' AND prompt_id IS NULL",
                (now(), job_id),
            )
            if cur.rowcount:
                self._event("job", job_id, "status", status="queued", error=None, requeued=True)
                self.bump("jobs")

    def job(self, job_id: int) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise StoreError(f"Job {job_id} ist unbekannt.")
        return dict(row) | {
            "params": json.loads(row["params"]),
            "seeds": json.loads(row["seeds"]),
            "graph": json.loads(row["graph"]) if row["graph"] else None,
        }

    def running_job_ids(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT id FROM jobs WHERE status = 'running'")]

    def running_since(self) -> float | None:
        """Startzeit (Unix-Sekunden) des ältesten laufenden Jobs; None, wenn keiner läuft."""
        row = self.db.execute("SELECT min(updated_at) FROM jobs WHERE status = 'running'")
        since = row.fetchone()[0]
        return datetime.fromisoformat(since).timestamp() if since else None

    def queued_jobs(self, order: tuple[str, ...] = ()) -> list[tuple[int, str]]:
        """Angelegte, noch nicht gestartete Jobs: (ID, Workflow). Mit ``order`` (Klassen in
        Vorrangfolge, SP5 Schritt 5) zuerst nach Klasse, dann FIFO; ohne reines FIFO."""
        rank = " ".join(f"WHEN ? THEN {i}" for i in range(len(order)))
        sql = "SELECT id, workflow FROM jobs WHERE status = 'queued' ORDER BY " + (
            f"CASE priority {rank} ELSE {len(order)} END, id" if order else "id"
        )
        rows = self.db.execute(sql, order)
        return [(r["id"], r["workflow"]) for r in rows]

    def job_priorities(self, ids: list[int]) -> dict[int, str]:
        """Vorrangklasse je Job (Anzeige in der Warteschlange)."""
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.db.execute(f"SELECT id, priority FROM jobs WHERE id IN ({marks})", ids)
        return {r["id"]: r["priority"] for r in rows}

    def order_source_of_stage(self, stage_id: int) -> str | None:
        row = self.db.execute(
            "SELECT o.source FROM order_stages s JOIN orders o ON o.id = s.order_id WHERE s.id = ?",
            (stage_id,),
        ).fetchone()
        return row[0] if row else None

    def request_cancel(self, job_id: int) -> None:
        """Abbruchwunsch des Betreibers im Journal: gilt auch über einen Neustart (FABLE-015)."""
        with self.tx():
            self._event("job", job_id, "cancel_requested")

    def cancel_requested(self, job_id: int) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM events WHERE entity = 'job' AND entity_id = ?"
            " AND event = 'cancel_requested'",
            (job_id,),
        )
        return row.fetchone() is not None

    def running_jobs(self) -> list[tuple[int, int | None]]:
        """Jobs im Status running mit der Prozess-ID, die sie ausführt (aus dem Journal)."""
        rows = self.db.execute(
            "SELECT j.id, json_extract(e.data, '$.pid') AS pid FROM jobs j"
            " JOIN events e ON e.entity = 'job' AND e.entity_id = j.id AND e.event = 'status'"
            " AND json_extract(e.data, '$.status') = 'running' WHERE j.status = 'running'"
        )
        return [(r["id"], r["pid"]) for r in rows]

    def engine_peak_gb(self, engine: str) -> float | None:
        """Gemessener Speicherbedarf (freier Speicher Start minus Minimum) des letzten
        abgeschlossenen Laufs dieser Engine; None ohne Messung."""
        row = self.db.execute(
            "SELECT json_extract(e.data, '$.memory.ram_free_start_gb'),"
            " json_extract(e.data, '$.memory.ram_free_min_gb') FROM events e"
            " JOIN jobs j ON j.id = e.entity_id WHERE e.entity = 'job' AND e.event = 'status'"
            " AND json_extract(e.data, '$.status') = 'done' AND j.engine = ?"
            " AND json_extract(e.data, '$.memory.ram_free_min_gb') IS NOT NULL"
            " AND json_extract(e.data, '$.memory.ram_free_start_gb') IS NOT NULL"
            " ORDER BY e.id DESC LIMIT 1",
            (engine,),
        ).fetchone()
        return None if row is None else max(0.0, row[0] - row[1])

    def jobs_brief(self, job_ids: list[int]) -> dict[int, tuple[str, dict]]:
        """(Workflow, Parameter) je Job-ID (unbekannte IDs fehlen im Ergebnis)."""
        marks = ",".join("?" * len(job_ids))
        rows = self.db.execute(
            f"SELECT id, workflow, params FROM jobs WHERE id IN ({marks})", job_ids
        )
        return {r["id"]: (r["workflow"], json.loads(r["params"])) for r in rows}

    def set_job_media(self, job_id: int, media_id: int) -> None:
        """Ergebnis-Medium eines Jobs festhalten (auch ein vorhandenes, bitgleiches; BUG-064)."""
        with self.tx() as db:
            db.execute("UPDATE jobs SET media_id = ? WHERE id = ?", (media_id, job_id))

    def job_started_at(self, job_id: int) -> float | None:
        """Beginn des letzten Laufs (Statuswechsel auf running) als Unix-Sekunden."""
        row = self.db.execute(
            "SELECT created_at FROM events WHERE entity = 'job' AND entity_id = ?"
            " AND event = 'status' AND json_extract(data, '$.status') = 'running'"
            " ORDER BY id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return datetime.fromisoformat(row[0]).timestamp() if row else None

    def duration_estimate(self, workflow: str, params: dict, runs: int) -> float:
        """Median der Dauer der letzten ``runs`` erfolgreichen Läufe des Workflows mit denselben
        Laufparametern (Schritte, Größe, Länge; ``RUN_SIGNATURE``); 0 = keine Messung."""
        want = {k: params.get(k) for k in RUN_SIGNATURE}
        rows = self.db.execute(
            "SELECT json_extract(e.data, '$.duration_s'), j.params FROM events e JOIN jobs j"
            " ON j.id = e.entity_id WHERE e.entity = 'job' AND e.event = 'status'"
            " AND json_extract(e.data, '$.status') = 'done' AND j.workflow = ?"
            " AND json_extract(e.data, '$.duration_s') IS NOT NULL ORDER BY e.id DESC LIMIT ?",
            (workflow, runs * ESTIMATE_SCAN),
        ).fetchall()
        same = [
            float(d) for d, p in rows if {k: json.loads(p).get(k) for k in RUN_SIGNATURE} == want
        ]
        values = sorted(same[:runs])
        if not values:
            return 0.0
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    def training_jobs(self, workflows: list[str], slug: str, limit: int) -> list[dict]:
        """Letzte Trainingsjobs einer Figur (Datensatz unter ``characters/<kürzel>/``)."""
        if not workflows:
            return []
        marks = ",".join("?" * len(workflows))
        rows = self.db.execute(
            f"SELECT id, workflow, params FROM jobs WHERE workflow IN ({marks})"
            " AND json_extract(params, '$.dataset') LIKE ? ORDER BY id DESC LIMIT ?",
            (*workflows, f"characters/{slug}/%", limit),
        )
        return [dict(r) | {"params": json.loads(r["params"])} for r in rows]

    def seconds_per_step(self, workflow: str, runs: int) -> float:
        """Median Sekunden je Schritt der letzten ``runs`` erfolgreichen Läufe des Workflows
        (Dauer / Parameter ``steps``), z. B. für die Trainingsschätzung vor dem Start (SP3
        Schritt 3); 0 = keine Messung."""
        rows = self.db.execute(
            "SELECT json_extract(e.data, '$.duration_s'), json_extract(j.params, '$.steps')"
            " FROM events e JOIN jobs j ON j.id = e.entity_id WHERE e.entity = 'job'"
            " AND e.event = 'status' AND json_extract(e.data, '$.status') = 'done'"
            " AND j.workflow = ? AND json_extract(e.data, '$.duration_s') IS NOT NULL"
            " AND json_extract(j.params, '$.steps') > 0 ORDER BY e.id DESC LIMIT ?",
            (workflow, runs),
        ).fetchall()
        values = sorted(float(d) / float(n) for d, n in rows)
        if not values:
            return 0.0
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    def run_seconds(self, workflow: str, runs: int) -> float:
        """Median der Laufdauer (s) der letzten ``runs`` erfolgreichen Läufe des Workflows
        (Lieferzeit, SP5 Schritt 2); 0 = keine Messung."""
        rows = self.db.execute(
            "SELECT json_extract(e.data, '$.duration_s') FROM events e JOIN jobs j"
            " ON j.id = e.entity_id WHERE e.entity = 'job' AND e.event = 'status'"
            " AND json_extract(e.data, '$.status') = 'done' AND j.workflow = ?"
            " AND json_extract(e.data, '$.duration_s') > 0 ORDER BY e.id DESC LIMIT ?",
            (workflow, runs),
        ).fetchall()
        values = sorted(float(r[0]) for r in rows)
        if not values:
            return 0.0
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    def pending_jobs(self) -> list[dict]:
        """Laufende und wartende Jobs mit Workflow, Vorrangklasse, Startzeit und Schrittzahl
        (Lieferzeit, SP5 Schritt 2)."""
        rows = self.db.execute(
            "SELECT id, workflow, status, priority, updated_at,"
            " json_extract(params, '$.steps') AS steps FROM jobs"
            " WHERE status IN ('queued', 'running') ORDER BY id"
        )
        return [dict(r) for r in rows]

    def finished_jobs_after(self, after: int, limit: int) -> list[dict]:
        """Abgeschlossene Jobs mit Cursor (events.id) > ``after``, aufsteigend, höchstens
        ``limit`` – für den Abgleich ab einer gemerkten Position (SP0 Schritt 6, BUG-107)."""
        rows = self.db.execute(
            "SELECT e.id, e.entity_id AS job_id, e.data FROM events e"
            " WHERE e.entity = 'job' AND e.event = 'status' AND e.id > ?"
            " AND json_extract(e.data, '$.status') IN ('done', 'failed')"
            " ORDER BY e.id LIMIT ?",
            (after, limit),
        ).fetchall()
        return [dict(r) | {"data": json.loads(r["data"])} for r in rows]

    def finished_jobs(self, after: int, limit: int) -> tuple[list[dict], bool]:
        """Abgeschlossene Jobs aus dem Journal mit Cursor (events.id) > ``after``: höchstens die
        neuesten ``limit``, aufsteigend. Zweiter Wert: dazwischen wurden ältere ausgelassen."""
        rows = self.db.execute(
            "SELECT e.id, e.entity_id AS job_id, e.created_at, e.data, j.workflow, j.engine,"
            " j.params,"
            " o.order_no FROM events e"
            " JOIN jobs j ON j.id = e.entity_id LEFT JOIN orders o ON o.id = j.order_id"
            " WHERE e.entity = 'job' AND e.event = 'status' AND e.id > ?"
            " AND json_extract(e.data, '$.status') IN ('done', 'failed')"
            " ORDER BY e.id DESC LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        recent = [
            dict(r) | {"data": json.loads(r["data"]), "params": json.loads(r["params"])}
            for r in rows[:limit]
        ]
        return recent[::-1], len(rows) > limit
