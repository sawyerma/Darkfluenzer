"""Galerie: Medien aus den Ausgabeordnern aufnehmen, auflisten und löschen (SP0 Schritt 2, bisher
``pipeline.py``)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config
from ..nodes.base import node_for
from ..store import MEDIA_KINDS, Store, sha256_file
from .pipeline import WORK_PREFIX


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


def media_candidates(cfg: Config, store: Store, seen: set[str], settle_s: float) -> list[tuple]:
    """Noch nicht erfasste erzeugte Bilder/Videos, chronologisch: Ausgaben abgeschlossener Jobs
    (mit Job-Bezug), Dateien unter ``local/evaluation`` (ohne Eingaben) und direkt in der
    verwalteten ComfyUI erzeugte Ausgaben. Gleiche Bytes zählen einmal (Job vor Evaluation vor
    ComfyUI); nur ruhende Dateien. Liefert (mtime, Pfad, SHA-256, Größe, Job-ID) und ergänzt
    ``seen`` um alle geprüften Pfade."""
    cutoff = time.time() - settle_s
    found: dict[str, tuple] = {}  # sha -> (Vorrang, mtime, Pfad, Größe, Job-ID)

    def offer(prio: int, path: Path, rel: str, sha: str, job_id: int | None) -> None:
        stat = path.stat()
        best = found.get(sha)
        if best is None or (prio, stat.st_mtime) < best[:2]:
            found[sha] = (prio, stat.st_mtime, rel, stat.st_size, job_id)

    for row in store.finished_jobs(0, 1_000_000)[0]:
        for out in row["data"].get("outputs") or []:
            rel, path = out["path"], cfg.local / out["path"]
            if rel in seen or Path(rel).suffix.lower() not in MEDIA_KINDS or not path.is_file():
                continue
            seen.add(rel)
            offer(0, path, rel, out["sha256"], row["job_id"])
    # Seit dem Start eines laufenden Jobs in ComfyUI entstandene Dateien gehören wahrscheinlich ihm
    # (frühe Zwischenausgaben wie eine Maske): erst nach seinem Abschluss aufnehmen, damit die
    # Job-Ausgabe mit Auftragsbezug Vorrang hat.
    busy = store.running_since()
    for prio, path, rel in _gallery_files(cfg):
        if rel in seen:
            continue
        mtime = path.stat().st_mtime
        if mtime > cutoff or (prio == 2 and busy is not None and mtime >= busy):
            continue  # wird noch geschrieben bzw. gehört zu einem laufenden Job: später
        seen.add(rel)
        offer(prio, path, rel, sha256_file(path), None)
    return sorted((m, rel, sha, size, job) for sha, (_, m, rel, size, job) in found.items())


def delete_media(cfg: Config, ids: list[int]) -> list[str]:
    """Löscht Galerie-Einträge ohne Kundenbezug endgültig: Index-Eintrag (Journal 'removed')
    und Datei samt aller byte-gleichen Kopien in den Galerie-Quellen (z. B. ComfyUIs eigene
    Ausgabe eines Renderjobs), damit nichts beim nächsten Durchlauf wieder auftaucht. Liefert
    die entfernten Pfade relativ zu ``local/``."""
    store = Store(cfg.local)
    try:
        with store.tx():
            rows = store.remove_media(ids)
            wanted = {(r["size"], r["sha256"]) for r in rows}
            doomed = {r["path"]: cfg.local / r["path"] for r in rows}
            sizes = {size for size, _ in wanted}
            for _, path, rel in _gallery_files(cfg):
                size = path.stat().st_size
                if rel not in doomed and size in sizes and (size, sha256_file(path)) in wanted:
                    doomed[rel] = path
            for path in doomed.values():  # Fehler -> Index bleibt unverändert (Rollback)
                path.unlink(missing_ok=True)
        return list(doomed)
    finally:
        store.close()


def scan_media(cfg: Config, seen: set[str], settle_s: float) -> int:
    """Nimmt alle noch nicht erfassten erzeugten Medien chronologisch in den Galerie-Index auf;
    liefert die Zahl neuer Einträge."""
    store = Store(cfg.local)
    try:
        added = 0
        for mtime, rel, sha, size, job_id in media_candidates(cfg, store, seen, settle_s):
            created = datetime.fromtimestamp(mtime, UTC).isoformat(timespec="milliseconds")
            added += bool(store.add_media(rel, sha, size, job_id=job_id, created_at=created))
        return added
    finally:
        store.close()
