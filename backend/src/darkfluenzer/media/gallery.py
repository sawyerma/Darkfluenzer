"""Galerie: Medien aus den Ausgabeordnern aufnehmen, auflisten und löschen (SP0 Schritt 2, bisher
``pipeline.py``)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config
from ..nodes.base import node_for
from ..store import MEDIA_KINDS, Store, StoreError, sha256_file
from .pipeline import WORK_PREFIX

log = logging.getLogger("darkfluenzer.gallery")

JOURNAL_BATCH = 1000  # Job-Ereignisse je Abfrage beim Abgleich
CURSOR = ("gallery", "", "job_cursor")  # gemerkte Journal-Position (adapter_state)


def sidecar_for(cfg: Config, output_rel: str) -> dict | None:
    """Herkunftsdatei eines Laufs zu einer Ausgabe (``<stem>_NN.ext`` -> ``<stem>.json``)."""
    out = Path(output_rel)
    sidecar = cfg.local / out.parent / f"{out.stem.rsplit('_', 1)[0]}.json"
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gallery_files(cfg: Config) -> Iterator[tuple[int, Path, str]]:
    """Bild-/Videodateien der Galerie-Quellen mit Vorrang: ``local/evaluation`` (ohne Eingaben)
    und die Ausgabe der verwalteten ComfyUI. Liefert (Vorrang, Datei, Pfad relativ zu local/)."""
    local = cfg.local.resolve()
    for prio, root, skip in (
        (1, cfg.local / "evaluation", "inputs"),
        (
            2,
            node_for(cfg, cfg.comfyui).output_dir(),
            WORK_PREFIX,
        ),  # Zwischenstände der Videoabschnitte
    ):
        if not root.is_dir() or not root.resolve().is_relative_to(local):
            continue
        for path in root.rglob("*"):
            if (
                path.name.startswith(".")
                or path.suffix.lower() not in MEDIA_KINDS
                or not path.is_file()
                or (skip and path.relative_to(root).parts[0] == skip)
            ):
                continue
            yield prio, path, path.resolve().relative_to(local).as_posix()


def media_candidates(
    cfg: Config,
    store: Store,
    seen: set[str],
    settle_s: float,
    *,
    after: int = 0,
    folders: bool = True,
) -> tuple[list[tuple], int]:
    """Noch nicht erfasste erzeugte Bilder/Videos, chronologisch: Ausgaben abgeschlossener Jobs
    (mit Job-Bezug) ab der gemerkten Journal-Position ``after``, dazu – nur mit ``folders`` –
    Dateien unter ``local/evaluation`` (ohne Eingaben) und direkt in der verwalteten ComfyUI
    erzeugte Ausgaben. Gleiche Bytes zählen einmal (Job vor Evaluation vor ComfyUI); nur ruhende
    Dateien. Liefert ((mtime, Pfad, SHA-256, Größe, Job-ID), …) und die neue Position; ``seen``
    wird um alle geprüften Pfade ergänzt. Ein Job gilt erst als fertig, wenn seine Ausgaben in
    ``local/`` liegen (``pipeline.run_render``); fehlt eine, wurde sie gelöscht und entfällt."""
    cutoff = time.time() - settle_s
    found: dict[str, tuple] = {}  # sha -> (Vorrang, mtime, Pfad, Größe, Job-ID)

    def offer(prio: int, path: Path, rel: str, sha: str, job_id: int | None) -> None:
        stat = path.stat()
        best = found.get(sha)
        if best is None or (prio, stat.st_mtime) < best[:2]:
            found[sha] = (prio, stat.st_mtime, rel, stat.st_size, job_id)

    cursor = after
    while rows := store.finished_jobs_after(cursor, JOURNAL_BATCH):
        for row in rows:
            for out in row["data"].get("outputs") or []:
                rel, path = out["path"], cfg.local / out["path"]
                if rel in seen or Path(rel).suffix.lower() not in MEDIA_KINDS:
                    continue
                if not path.is_file():  # gelöscht
                    continue
                seen.add(rel)
                offer(0, path, rel, out["sha256"], row["job_id"])
        cursor = rows[-1]["id"]
        if len(rows) < JOURNAL_BATCH:
            break
    if folders:
        # Seit dem Start eines laufenden Jobs in ComfyUI entstandene Dateien gehören wahrscheinlich
        # ihm (frühe Zwischenausgaben wie eine Maske): erst nach seinem Abschluss aufnehmen, damit
        # die Job-Ausgabe mit Auftragsbezug Vorrang hat.
        busy = store.running_since()
        for prio, path, rel in _gallery_files(cfg):
            if rel in seen:
                continue
            mtime = path.stat().st_mtime
            if mtime > cutoff or (prio == 2 and busy is not None and mtime >= busy):
                continue  # wird noch geschrieben bzw. gehört zu einem laufenden Job: später
            seen.add(rel)
            offer(prio, path, rel, sha256_file(path), None)
    candidates = sorted((m, rel, sha, size, job) for sha, (_, m, rel, size, job) in found.items())
    return candidates, cursor


def delete_media(cfg: Config, ids: list[int]) -> tuple[list[str], list[str]]:
    """Löscht Galerie-Einträge ohne Kundenbezug endgültig: Index-Eintrag (Journal 'removed')
    und Datei samt aller byte-gleichen Kopien in den Galerie-Quellen (z. B. ComfyUIs eigene
    Ausgabe eines Renderjobs), damit nichts beim nächsten Durchlauf wieder auftaucht.

    Drei Schritte (FABLE-011): Kopien suchen und hashen ohne Sperre; Index-Einträge in einer kurzen
    Transaktion entfernen; danach die Dateien löschen. Eine Datei, die nicht gelöscht werden kann,
    bleibt liegen (und erscheint beim nächsten Abgleich wieder) – nie umgekehrt ein Index-Eintrag
    ohne Datei. Liefert (gelöschte Pfade, nicht löschbare Pfade) relativ zu ``local/``."""
    store = Store(cfg.local)
    try:
        rows = [r for r in (store.media_by_id(i) for i in ids) if r is not None]
        if any(r["order_id"] is not None for r in rows):
            raise StoreError("Medien eines Kundenauftrags können nicht gelöscht werden.")
        wanted = {(r["size"], r["sha256"]) for r in rows}
        doomed = {r["path"]: cfg.local / r["path"] for r in rows}
        sizes = {size for size, _ in wanted}
        for _, path, rel in _gallery_files(cfg):  # ohne Schreibsperre: Ordner und Hashes
            size = path.stat().st_size
            if rel not in doomed and size in sizes and (size, sha256_file(path)) in wanted:
                doomed[rel] = path
        store.remove_media([r["id"] for r in rows])  # kurze Transaktion
        removed, failed = [], []
        for rel, path in doomed.items():
            try:
                path.unlink(missing_ok=True)
                removed.append(rel)
            except OSError as exc:
                log.warning("Galerie: %s nicht gelöscht: %s", rel, exc)
                failed.append(rel)
        return removed, failed
    finally:
        store.close()


SIZE_BATCH = 200  # so viele Bilder je Runde bekommen ihre Abmessungen nachgetragen


def fill_sizes(cfg: Config, store: Store, resizing: frozenset[str], limit: int) -> int:
    """Abmessungen für Bilder ohne Eintrag nachtragen (Dateikopf, älteste zuerst, damit das
    Ausgangsmedium vor seinem Hochskalierten steht). Liefert die Zahl bearbeiteter Bilder."""
    from .pipeline import image_size, native_size

    rows = store.media_without_size(limit)
    for row in rows:
        size_px = image_size(cfg.local / row["path"]) or (0, 0)
        resized = (row["workflow"] or "") in resizing
        native = (
            native_size(store, size_px, resized, row["parent_media_id"]) if any(size_px) else None
        )
        store.set_media_size(row["id"], size_px, native)
    return len(rows)


def scan_media(
    cfg: Config,
    seen: set[str],
    settle_s: float,
    folders: bool = True,
    resizing: frozenset[str] = frozenset(),
) -> int:
    """Nimmt alle noch nicht erfassten erzeugten Medien chronologisch in den Galerie-Index auf;
    liest das Job-Journal ab der gespeicherten Position, die Ordner nur mit ``folders``. Eigener
    Strang mit eigener Verbindung (SP0 Schritt 5/6). Trägt danach fehlende Bildabmessungen nach
    (``resizing``: Workflows, deren Ergebnis nie als nativ gilt). Liefert die neuen Einträge."""
    store = Store(cfg.local)
    try:
        after = int(store.adapter_get(*CURSOR) or 0)
        found, cursor = media_candidates(cfg, store, seen, settle_s, after=after, folders=folders)
        added = 0
        for mtime, rel, sha, size, job_id in found:
            created = datetime.fromtimestamp(mtime, UTC).isoformat(timespec="milliseconds")
            added += bool(store.add_media(rel, sha, size, job_id=job_id, created_at=created))
        if cursor != after:
            store.adapter_set(*CURSOR, str(cursor))
        fill_sizes(cfg, store, resizing, SIZE_BATCH)
        return added
    finally:
        store.close()
