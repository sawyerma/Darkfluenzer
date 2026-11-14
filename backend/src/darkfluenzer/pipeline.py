"""Bild-/Videoroute über registrierte Workflows; Master-First-Prüfungen.

Heute: Evaluationsläufe je Engine (``local/evaluation/<engine>/``, ohne Kundenbezug) und die
Prüfung, dass maskierte Bearbeitungen außerhalb der Maske pixelidentisch zum Master bleiben.
Die Kundenroute (3 Kandidaten je Auftrag in ``work/``) baut auf denselben Funktionen auf (S2/S5).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy
from .config import Config
from .models import Manifest, Workflow
from .store import Store

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


def render_evaluation(
    cfg: Config,
    man: Manifest,
    workflow_key: str,
    values: dict,
    uploads: dict[str, Path] | None = None,
    timeout_s: float = 3600.0,
) -> comfy.RenderResult:
    """Evaluationslauf: Eingaben hochladen, Workflow rendern, Ergebnis + Herkunft ablegen.

    Für maskierte Bearbeitungen wird zusätzlich geprüft, dass außerhalb der Maske kein Pixel
    vom Master abweicht – sonst Fehler statt stiller Akzeptanz. Jede Renderung ist ein Job ohne
    Kundenbezug im SQLite-Journal; ihr Abschluss erscheint im Cockpit als ``job.completed``.
    """
    wf = man.workflows[workflow_key]
    uploads = uploads or {}
    for name in uploads:
        if name not in wf.params or not wf.params[name].upload:
            raise PipelineError(f"{workflow_key}: '{name}' ist kein Upload-Parameter.")
    store = Store(cfg.local)
    try:
        seeds = [values["seed"]] if "seed" in values else []
        prompt = str(values.get("prompt", ""))
        job_id = store.create_job(None, wf.engine, workflow_key, prompt, values, seeds)
        store.set_job_status(job_id, "running")
        try:
            result, outputs = _render(cfg, man, wf, workflow_key, dict(values), uploads, timeout_s)
        except BaseException as exc:
            store.set_job_status(job_id, "failed", error=str(exc) or type(exc).__name__)
            raise
        store.set_job_status(
            job_id,
            "done",
            prompt_id=result.prompt_id,
            duration_s=result.duration_s,
            outputs=outputs,
        )
    finally:
        store.close()
    return result


def _render(
    cfg: Config,
    man: Manifest,
    wf: Workflow,
    workflow_key: str,
    values: dict,
    uploads: dict[str, Path],
    timeout_s: float,
) -> tuple[comfy.RenderResult, list[dict]]:
    from . import runtime

    runtime.start(cfg)
    client = comfy.ComfyClient(cfg.comfyui.url)
    for name, path in uploads.items():
        values[name] = client.upload_image(path)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = evaluation_dir(cfg, wf.engine)
    result = comfy.run_workflow(
        cfg, man, workflow_key, values, dest, stem=f"{workflow_key}_{stamp}", timeout_s=timeout_s
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
