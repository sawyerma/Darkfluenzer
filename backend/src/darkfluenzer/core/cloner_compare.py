"""Vergleich der Kloner-Methoden je Befehl (SP3 Schritt 8, Regel 1: nur echte Vergleiche
entscheiden). Jede Vorlage läuft durch jeden Kandidaten-Workflow – mit der aktiven Charakter-LoRA
der Figur, sofern der Workflow sie laden darf, und der Bildanweisung des Befehls –, die Prüfkette
misst je Ergebnis die Gesichtsidentität (SFace, AuraFace gegen ``reference/`` der Figur). Bericht
als JSON unter ``local/evaluation/cloner/``; die Entscheidung trifft der Betreiber, übernommen als
``cloner = [...]`` im Manifest und im Default-Kontakt.

Aufruf: ``darkfluenzer cloner compare --command clone --templates <ordner> --workflow A
[--workflow B …] --character <id> [--limit 10]``. Schreibt keine Aufträge, nur Evaluationsjobs."""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..config import Config
from ..media import models, pipeline
from ..nodes import comfy
from ..store import Store
from . import cloner_text
from .cloner import _slots

SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def templates(folder: Path, limit: int) -> list[Path]:
    found = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUFFIXES)
    if not found:
        raise ValueError(f"{folder}: keine Vorlagen ({', '.join(SUFFIXES)}).")
    return found[:limit] if limit else found


def plan(
    store: Store,
    man: models.Manifest,
    command: str,
    files: list[Path],
    workflows: list[str],
    character_id: int | None,
) -> list[dict]:
    """Läufe Vorlage × Workflow mit Werten, Bild-Eingang und LoRA; Fehler vor dem ersten Lauf."""
    if command not in cloner_text.COMMANDS:
        raise ValueError(f"Befehl {command!r} unbekannt ({', '.join(cloner_text.COMMANDS)}).")
    runs = []
    for key in workflows:
        wf = man.workflows.get(key)
        if wf is None or wf.training:
            raise ValueError(f"Workflow {key!r} ist kein Medien-Workflow.")
        slots = _slots(wf)
        if len(slots) != 1:
            raise ValueError(f"{wf.title}: Vergleich braucht genau einen Bild-Eingang ({slots}).")
        lora = pipeline.active_lora(store, man, character_id, wf) if character_id else ""
        text = cloner_text.prompt(command, "", templated=wf.params[slots[0]].reference)
        graph = comfy.load_graph(man, wf)
        values = {"prompt": text} if text and "prompt" in wf.params else {}
        for name, p in wf.params.items():  # Pflichtwerte ohne Angabe: geprüfter Graph-Standard
            if p.required and not p.upload and name not in values:
                values[name] = graph[p.node]["inputs"][p.input]
        runs += [
            {"workflow": key, "template": f, "slot": slots[0], "values": dict(values), "lora": lora}
            for f in files
        ]
    return runs


def _render(cfg: Config, man: models.Manifest, run: dict) -> comfy.RenderResult:
    """Ein Evaluationsjob wie im Cockpit (Job ohne Auftrag), mit LoRA und Prüfkette."""
    store = Store(cfg.local)
    try:
        src: Path = run["template"]
        inputs = {run["slot"]: pipeline.store_input(cfg, src.read_bytes(), src.name)}
        job_id = pipeline.create_render(
            store, man, run["workflow"], run["values"], inputs,
            video_max_s=cfg.production.video_max_s, lora=run["lora"],
        )  # fmt: skip
    finally:
        store.close()
    return pipeline.run_render(cfg, man, job_id)


def identity_of(checks: list[dict]) -> dict:
    """Erster Identitätswert eines Laufs (Status, SFace, AuraFace)."""
    found = next((c for c in checks if c.get("check") == "identity"), None)
    if found is None:
        return {"status": "nicht_gemessen"}
    return {k: found.get(k) for k in ("status", "sface", "auraface", "face_px")}


def run(
    cfg: Config,
    man: models.Manifest,
    runs: list[dict],
    *,
    render: Callable[[Config, models.Manifest, dict], comfy.RenderResult] = _render,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    rows = []
    for r in runs:
        started = time.monotonic()
        try:
            result = render(cfg, man, r)
            row = {
                "outputs": [str(o.path) for o in result.outputs],
                "identity": identity_of(result.checks),
                "error": "",
            }
        except (comfy.ComfyError, pipeline.PipelineError, OSError, ValueError) as exc:
            row = {"outputs": [], "identity": {"status": "fehler"}, "error": str(exc)}
        row |= {
            "workflow": r["workflow"],
            "template": r["template"].name,
            "lora": r["lora"],
            "seconds": round(time.monotonic() - started, 1),
        }
        rows.append(row)
        if progress:
            progress(row)
    return {"rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for key in dict.fromkeys(r["workflow"] for r in rows):
        mine = [r for r in rows if r["workflow"] == key]
        measured = [r["identity"] for r in mine if r["identity"].get("status") == "ok"]
        auraface = [m["auraface"] for m in measured if m.get("auraface") is not None]
        out[key] = {
            "runs": len(mine),
            "errors": sum(1 for r in mine if r["error"]),
            "measured": len(measured),
            "not_measurable": sum(1 for r in mine if r["identity"].get("status") == "kein_gesicht"),
            "auraface_median": round(statistics.median(auraface), 3) if auraface else None,
            "auraface_min": round(min(auraface), 3) if auraface else None,
            "lora": mine[0]["lora"] if mine else "",
        }
    return out


def write_report(cfg: Config, command: str, report: dict) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = cfg.local / "evaluation" / "cloner" / f"{command}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
