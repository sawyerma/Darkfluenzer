"""Bild-/Videoroute über registrierte Workflows; Master-First-Prüfungen.

Heute: Evaluationsläufe je Engine (``local/evaluation/<engine>/``, ohne Kundenbezug) und die
Prüfung, dass maskierte Bearbeitungen außerhalb der Maske pixelidentisch zum Master bleiben.
Die Kundenroute (3 Kandidaten je Auftrag in ``work/``) baut auf denselben Funktionen auf (S2/S5).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy
from .config import Config
from .models import Manifest, Workflow
from .store import MEDIA_KINDS, Store, sha256_file

log = logging.getLogger("darkfluenzer.pipeline")


class PipelineError(Exception):
    """Ergebnis verletzt eine Pipeline-Garantie (z. B. Pixel außerhalb der Maske verändert)."""


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Quadratische Dilatation (L∞) – Obermenge von ComfyUIs GrowMask (mit/ohne tapered)."""
    if radius <= 0:
        return mask
    h, w = mask.shape
    padded = np.pad(mask, radius)
    out = np.zeros_like(mask)
    for dy in range(2 * radius + 1):
        row = padded[dy : dy + h]
        for dx in range(2 * radius + 1):
            out |= row[:, dx : dx + w]
    return out


def unmasked_difference(master: Path, edited: Path, mask: Path, grow: int) -> int:
    """Anzahl Pixel, die AUSSERHALB der (um ``grow`` erweiterten) Maske vom Master abweichen."""
    a = np.asarray(Image.open(master).convert("RGB"))
    b = np.asarray(Image.open(edited).convert("RGB"))
    m = np.asarray(Image.open(mask).convert("L")) > 0
    if a.shape != b.shape or a.shape[:2] != m.shape:
        raise PipelineError(
            f"Formate passen nicht: Master {a.shape}, Ergebnis {b.shape}, Maske {m.shape}"
        )
    outside = ~_dilate(m, grow + 1)
    return int(np.any(a != b, axis=2)[outside].sum())


def evaluation_dir(cfg: Config, engine: str) -> Path:
    return cfg.local / "evaluation" / engine


INPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def store_input(cfg: Config, data: bytes, filename: str) -> str:
    """Eingabebild (Quellbild, Maske, Startbild) inhaltsadressiert unter ``local/evaluation/inputs``
    ablegen; liefert den Pfad relativ zu ``local/``. Gleiche Bytes -> dieselbe Datei."""
    suffix = Path(filename).suffix.lower()
    if suffix not in INPUT_SUFFIXES:
        raise PipelineError(f"{filename}: nur {', '.join(sorted(INPUT_SUFFIXES))} erlaubt.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as exc:
        raise PipelineError(f"{filename}: kein lesbares Bild ({exc}).") from exc
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem)[:60] or "bild"
    target = (
        cfg.local
        / "evaluation"
        / "inputs"
        / f"{hashlib.sha256(data).hexdigest()[:16]}_{stem}{suffix}"
    )
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return target.relative_to(cfg.local).as_posix()


def create_render(
    store: Store, man: Manifest, workflow_key: str, values: dict, inputs: dict
) -> int:
    """Prüft einen Renderauftrag gegen die Registry und legt ihn als Job (Status queued) an.

    ``inputs``: Upload-Parameter -> abgelegte Eingabedatei relativ zu ``local/``.
    """
    wf = man.workflows.get(workflow_key)
    if wf is None:
        raise PipelineError(f"Workflow '{workflow_key}' ist nicht registriert.")
    for name in inputs:
        if name not in wf.params or not wf.params[name].upload:
            raise PipelineError(f"{workflow_key}: '{name}' ist kein Upload-Parameter.")
    as_text = [n for n in values if n in wf.params and wf.params[n].upload]
    if as_text:
        raise PipelineError(f"{', '.join(as_text)}: Datei erwartet.")
    # Typen, Grenzen, Pflichtangaben und unbekannte Namen prüft die Registry-Bindung.
    comfy.apply_params(comfy.load_graph(man, wf), wf, {**values, **inputs})
    seeds = [values["seed"]] if "seed" in values else []
    prompt = str(values.get("prompt", ""))
    return store.create_job(None, wf.engine, workflow_key, prompt, {**values, **inputs}, seeds)


def run_render(
    cfg: Config,
    man: Manifest,
    job_id: int,
    timeout_s: float = 3600.0,
    client_id: str | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> comfy.RenderResult:
    """Führt einen angelegten Job über den registrierten API-Workflow aus und hält das Ergebnis im
    Journal fest (``job.completed``). Für maskierte Bearbeitungen wird geprüft, dass außerhalb der
    Maske kein Pixel vom Master abweicht – sonst Fehler statt stiller Akzeptanz."""
    store = Store(cfg.local)
    try:
        job = store.job(job_id)
        try:
            wf = man.workflows.get(job["workflow"])
            if wf is None:
                raise PipelineError(f"Workflow '{job['workflow']}' ist nicht mehr registriert.")
            params = job["params"]
            uploads = {
                n: cfg.local / v
                for n, v in params.items()
                if n in wf.params and wf.params[n].upload
            }
            values = {n: v for n, v in params.items() if n not in uploads}
            store.set_job_status(job_id, "running", pid=os.getpid())
            result, outputs = _render(cfg, man, wf, job_id, values, uploads, timeout_s, client_id)
        except BaseException as exc:
            if is_cancelled():
                store.set_job_status(
                    job_id, "failed", error="Vom Betreiber abgebrochen.", cancelled=True
                )
            else:
                store.set_job_status(job_id, "failed", error=str(exc) or type(exc).__name__)
            raise
        for out in outputs:  # erst in die Galerie, dann gilt der Job als fertig
            if Path(out["path"]).suffix.lower() in MEDIA_KINDS:
                store.add_media(out["path"], out["sha256"], out["size"], job_id=job_id)
        store.set_job_status(
            job_id,
            "done",
            prompt_id=result.prompt_id,
            duration_s=result.duration_s,
            outputs=outputs,
        )
        return result
    finally:
        store.close()


def render_evaluation(
    cfg: Config,
    man: Manifest,
    workflow_key: str,
    values: dict,
    uploads: dict[str, Path] | None = None,
    timeout_s: float = 3600.0,
) -> comfy.RenderResult:
    """Evaluationslauf von der Kommandozeile: derselbe Weg wie im Cockpit (Job ohne Kundenbezug)."""
    inputs = {n: store_input(cfg, p.read_bytes(), p.name) for n, p in (uploads or {}).items()}
    store = Store(cfg.local)
    try:
        job_id = create_render(store, man, workflow_key, values, inputs)
    finally:
        store.close()
    return run_render(cfg, man, job_id, timeout_s)


def _render(
    cfg: Config,
    man: Manifest,
    wf: Workflow,
    job_id: int,
    values: dict,
    uploads: dict[str, Path],
    timeout_s: float,
    client_id: str | None = None,
) -> tuple[comfy.RenderResult, list[dict]]:
    workflow_key = wf.key
    from . import runtime

    runtime.start(cfg)
    client = comfy.ComfyClient(cfg.comfyui.url)
    for name, path in uploads.items():
        values[name] = client.upload_image(path)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = evaluation_dir(cfg, wf.engine)
    result = comfy.run_workflow(
        cfg,
        man,
        workflow_key,
        values,
        dest,
        stem=f"{workflow_key}_{stamp}",
        timeout_s=timeout_s,
        job_id=job_id,
        client_id=client_id,
    )
    checks: dict = {}
    if {"image", "mask"} <= set(uploads):
        graph = comfy.load_graph(man, wf)
        grow_param = wf.params.get("mask_grow")
        grow = values.get(
            "mask_grow", graph[grow_param.node]["inputs"][grow_param.input] if grow_param else 0
        )
        for out in result.outputs:
            diff = unmasked_difference(uploads["image"], out.path, uploads["mask"], int(grow))
            checks[out.path.name] = {"unmasked_changed_pixels": diff}
            if diff:
                raise PipelineError(
                    f"{out.path.name}: {diff} Pixel außerhalb der Maske verändert – verworfen."
                )
    record = {
        "created_at": stamp,
        "prompt_id": result.prompt_id,
        "duration_s": result.duration_s,
        "outputs": [
            {**asdict(o), "path": o.path.relative_to(cfg.local).as_posix()} for o in result.outputs
        ],
        "inputs": {
            k: {"file": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for k, p in uploads.items()
        },
        "checks": checks,
        "provenance": result.provenance,
    }
    sidecar = dest / f"{workflow_key}_{stamp}.json"
    sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Evaluation %s: %s (%.1f s)", workflow_key, sidecar.name, result.duration_s)
    return result, record["outputs"]


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
    local = cfg.local.resolve()
    for prio, root, skip in (
        (1, cfg.local / "evaluation", "inputs"),
        (2, cfg.comfyui.path / "output", None),
    ):
        if not root.is_dir() or not root.resolve().is_relative_to(local):
            continue
        for path in root.rglob("*"):
            rel = path.resolve().relative_to(local).as_posix()
            if (
                rel in seen
                or path.name.startswith(".")
                or path.suffix.lower() not in MEDIA_KINDS
                or not path.is_file()
                or (skip and path.relative_to(root).parts[0] == skip)
            ):
                continue
            if path.stat().st_mtime > cutoff:
                continue  # wird noch geschrieben: beim nächsten Durchlauf
            seen.add(rel)
            offer(prio, path, rel, sha256_file(path), None)
    return sorted((m, rel, sha, size, job) for sha, (_, m, rel, size, job) in found.items())


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
