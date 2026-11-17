"""SP0 Schritt 6 (BUG-107): Galerie-Abgleich ab gemerkter Journal-Position, Zähler für Medien-ID
und laufende Nummer, schnelle Beobachterrunde auch mit sehr vielen Ereignissen.

Zahl der Ereignisse im Lasttest über ``DF_JOURNAL_EVENTS`` (Vorgabe 100000; Abnahme 1000000)."""

from __future__ import annotations

import json
import os
import sqlite3
import time

from darkfluenzer import store as store_module
from darkfluenzer.media import gallery
from darkfluenzer.store import Store, sha256_file

EVENTS = int(os.environ.get("DF_JOURNAL_EVENTS", "100000"))


def _done_job(s: Store, cfg, name: str) -> tuple[int, dict]:
    path = cfg.local / "evaluation" / "wf" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    out = {"path": f"evaluation/wf/{name}", "sha256": sha256_file(path), "node": "9"}
    job = s.create_job(None, "e", "wf", "p", {}, [])
    s.set_job_status(job, "done", outputs=[out])
    return job, out


def test_gallery_reads_only_after_the_cursor_and_skips_deleted_outputs(cfg):
    s = Store(cfg.local)
    try:
        job, out = _done_job(s, cfg, "a.png")
        found, cursor = gallery.media_candidates(cfg, s, set(), settle_s=0, folders=False)
        assert [(rel, j) for _, rel, _, _, j in found] == [(out["path"], job)] and cursor > 0
        assert gallery.media_candidates(cfg, s, set(), 0, after=cursor, folders=False) == (
            [],
            cursor,
        )
        # gelöschte Ausgabe eines fertigen Jobs hält die Position nicht auf
        gone = {"path": "evaluation/wf/b.png", "sha256": "0" * 64, "node": "9"}
        late = s.create_job(None, "e", "wf", "p", {}, [])
        s.set_job_status(late, "done", outputs=[gone])
        found, moved = gallery.media_candidates(cfg, s, set(), 0, after=cursor, folders=False)
        assert found == [] and moved > cursor
    finally:
        s.close()


def test_scan_media_keeps_the_cursor_between_rounds(cfg):
    s = Store(cfg.local)
    try:
        _done_job(s, cfg, "c.png")
    finally:
        s.close()
    seen: set[str] = set()
    assert gallery.scan_media(cfg, seen, 0, folders=False) == 1
    s = Store(cfg.local)
    try:
        assert int(s.adapter_get(*gallery.CURSOR)) > 0
    finally:
        s.close()
    assert gallery.scan_media(cfg, set(), 0, folders=False) == 0  # Position gemerkt


def test_migration_18_takes_counters_from_the_journal_and_never_reuses(tmp_path, monkeypatch):
    from darkfluenzer.store import db as store_db

    local = tmp_path / "local"
    monkeypatch.setattr(store_db, "SCHEMA_VERSION", 17)  # Datenbank im Stand von Version 17
    Store(local).close()
    monkeypatch.undo()
    db = sqlite3.connect(local / "darkfluenzer.sqlite3")
    # Journal kennt Medium 7 (gelöscht, Nummer 5) und Medium 9 (vorhanden, Nummer 6)
    ev = "INSERT INTO events (entity, entity_id, event, data, created_at) VALUES (?,?,?,?,'t')"
    db.execute(ev, ("media", 7, "added", "{}"))
    db.execute(ev, ("media", 7, "removed", json.dumps({"number": 5})))
    db.execute(ev, ("media", 9, "added", "{}"))
    db.execute(
        "INSERT INTO media (id, sha256, path, kind, size, number, created_at)"
        " VALUES (9, '" + "x" * 64 + "', 'evaluation/x.png', 'image', 1, 6, 't')"
    )
    db.commit()
    db.close()
    s = Store(local)
    try:
        assert s.db.execute("PRAGMA user_version").fetchone()[0] == store_module.SCHEMA_VERSION
        counters = dict(s.db.execute("SELECT name, value FROM counters").fetchall())
        assert counters == {"media_id": 9, "media_number": 6}
        assert s.add_media("evaluation/y.png", "y" * 64, 1) == 10
        assert s.db.execute("SELECT number FROM media WHERE id = 10").fetchone()[0] == 7
        assert list(local.glob("darkfluenzer.sqlite3.bak-*-vor-migration18"))  # SP0 Schritt 1
    finally:
        s.close()


def test_observer_round_stays_fast_with_many_events(cfg):
    s = Store(cfg.local)
    try:
        jobs = EVENTS // 4
        s.db.execute("BEGIN")
        s.db.executemany(
            "INSERT INTO jobs (id, engine, workflow, prompt, status, created_at, updated_at)"
            " VALUES (?, 'e', 'wf', 'p', 'done', 't', 't')",
            ((i,) for i in range(1, jobs + 1)),
        )
        done = json.dumps({"status": "done", "outputs": []})
        rows = (
            (("job", i // 4 + 1, "status", done), ("message", i // 4 + 1, "added", "{}"),
             ("media", i // 4 + 1, "added", "{}"), ("order", i // 4 + 1, "status", "{}"))[i % 4]
            for i in range(EVENTS)
        )  # fmt: skip
        s.db.executemany(
            "INSERT INTO events (entity, entity_id, event, data, created_at) VALUES (?,?,?,?,'t')",
            rows,
        )
        s.db.execute("COMMIT")
        s.db.execute(
            "UPDATE counters SET value = (SELECT max(entity_id) FROM events WHERE entity = 'media')"
            " WHERE name = 'media_id'"
        )
    finally:
        s.close()
    assert gallery.scan_media(cfg, set(), 0, folders=False) == 0  # erste Runde liest alles einmal
    start = time.perf_counter()
    gallery.scan_media(cfg, set(), 0, folders=False)  # jede weitere Runde: nur Neues
    round_ms = (time.perf_counter() - start) * 1000
    s = Store(cfg.local)
    try:
        start = time.perf_counter()
        s.add_media("evaluation/neu.png", "n" * 64, 1)
        add_ms = (time.perf_counter() - start) * 1000
    finally:
        s.close()
    assert round_ms < 50, f"Beobachterrunde {round_ms:.1f} ms bei {EVENTS} Ereignissen"
    assert add_ms < 10, f"add_media {add_ms:.1f} ms bei {EVENTS} Ereignissen"


def test_duration_estimate_uses_only_runs_with_the_same_parameters(cfg):
    s = Store(cfg.local)
    try:
        for steps, secs in ((8, 3.0), (8, 5.0), (36, 70.0)):
            job = s.create_job(None, "e", "wf", "p", {"steps": steps, "prompt": "x"}, [])
            s.set_job_status(job, "done", duration_s=secs, outputs=[])
        assert s.duration_estimate("wf", {"steps": 8, "prompt": "anders"}, 5) == 4.0
        assert s.duration_estimate("wf", {"steps": 36}, 5) == 70.0
        assert s.duration_estimate("wf", {"steps": 20}, 5) == 0.0  # keine Messung
    finally:
        s.close()
