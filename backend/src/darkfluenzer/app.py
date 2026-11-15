"""Einstiegspunkt des Darkfluenzer-Dienstes (CLI). Die macOS-App ruft genau diese Befehle auf.

    python -m darkfluenzer comfy start|stop|status|health [--json]
    python -m darkfluenzer models status|orphans [--json]
    python -m darkfluenzer models download|verify (--wave N | --engine ID ...) [--json]
    python -m darkfluenzer workflows check|export-ui|install [--json]
    python -m darkfluenzer render WORKFLOW --set name=wert ... [--input name=datei ...] [--json]
    python -m darkfluenzer character scan|dataset|train-sdxl [--dataset ID] [--steps N] [--json]
    python -m darkfluenzer serve          (Cockpit: React-Build + Protobuf-API, blockierend)
    python -m darkfluenzer up|restart|down [--json]  (Cockpit starten / nur Cockpit neu starten /
                                                      Cockpit + eigene ComfyUI stoppen)

Exit-Codes: 0 ok, 1 Fehler, 2 Konfiguration, 3 fremde Instanz, 4 Start fehlgeschlagen,
5 belegt, 6 Stop fehlgeschlagen, 7 nicht gesund, 8 Modell-/Manifestfehler,
9 Workflow-/Renderfehler, 10 Training (DATASET_INCOMPLETE, TRAINER_UNAVAILABLE, …).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, comfy, models, pipeline, runtime, training
from .config import INSTANCE_SECTIONS, ConfigError, load, project_root, setup_logging

log = logging.getLogger("darkfluenzer.app")

_HUMAN = {
    "started": "ComfyUI gestartet",
    "already_running": "ComfyUI läuft bereits (verwaltete Instanz)",
    "stopped": "Verwaltete ComfyUI-Instanz beendet",
    "not_running": "Keine verwaltete ComfyUI-Instanz aktiv",
    "not_managed": "Laufende ComfyUI ist fremd und wird nicht beendet",
}


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if not payload.get("ok", True) and "error" in payload:
        print(f"FEHLER [{payload['error']}]: {payload['message']}", file=sys.stderr)
        tail = payload.get("details", {}).get("log_tail")
        if tail:
            print("--- Log-Ende ---\n" + tail, file=sys.stderr)
        return
    if "engines" in payload:
        print(f"frei {payload['free_gb']} GB (Reserve {payload['reserve_gb']:.0f} GB)")
        for key, e in payload["engines"].items():
            mark = "bereit" if e["ready"] else f"fehlt {e['missing_gb']} GB"
            gates = " ".join(f"{g}={v}" for g, v in e["gates"].items())
            print(f"  W{e['wave']} {key:<22} {e['kind']:<5} {mark:<16} {e['usage']:<10} {gates}")
        return
    if "photos" in payload:
        print(
            f"{payload['usable']} geeignete Bilder (Minimum {payload['min_images']}) in "
            f"{payload['folder']}"
        )
        for ph in payload["photos"]:
            size = f"{ph['width']}×{ph['height']}" if ph["width"] else ""
            print(f"  {ph['status']:<11} {ph['name']:<40} {size:<11} {ph['note']}")
        return
    if "lora_file" in payload:
        print(
            f"LoRA trainiert: {payload['lora_file']} ({payload['s_per_step']} s/Schritt, "
            f"Loss {payload['loss_first_25']} -> {payload['loss_last_25']})"
        )
        print("  Status: trainiert, NICHT freigegeben – Vorschau prüfen, dann aktivieren.")
        return
    if "workflows" in payload:
        for key, problems in payload["workflows"].items():
            print(f"  {key:<28} {'OK' if not problems else 'FEHLER'}")
            for problem in problems:
                print(f"      - {problem}")
        return
    if "outputs" in payload:
        print(f"Render fertig in {payload['duration_s']} s (prompt {payload['prompt_id']})")
        for out in payload["outputs"]:
            print(f"  {out}")
        return
    if "files" in payload or "orphans" in payload:
        for key, value in (payload.get("files") or {}).items():
            print(f"  {key:<32} {value}")
        for rel in payload.get("orphans") or []:
            print(f"  nicht registriert: {rel}")
        return
    head = _HUMAN.get(payload.get("result", ""), payload.get("state", ""))
    print(head)
    for key in ("url", "pid", "startup_s", "log", "foreign_pids", "message"):
        if payload.get(key) is not None:
            print(f"  {key}: {payload[key]}")
    if payload.get("health"):
        h = payload["health"]
        print(
            f"  comfyui {h['comfyui_version']} · torch {h['pytorch_version']} · "
            f"python {h['python_version']} · {h['device']}"
        )


def _comfy(action: str, instance: str) -> tuple[dict, int]:
    cfg = load()
    setup_logging(cfg)
    if action == "start":
        return {"ok": True, **runtime.start(cfg, instance)}, 0
    if action == "stop":
        return {"ok": True, **runtime.stop(cfg, instance)}, 0
    st = runtime.status(cfg, instance)
    if action == "status":
        return {"ok": True, **st}, 0
    if st["state"] == "running":
        return {"ok": True, **st}, 0
    message = f"Verwaltete ComfyUI nicht gesund (Zustand: {st['state']})."
    return {"ok": False, **st, "error": "unhealthy", "message": message}, 7


def _models(args: argparse.Namespace) -> tuple[dict, int]:
    root = project_root()
    man = models.load_manifest(root)
    base = models.models_dir(root)
    if args.action == "status":
        return {"ok": True, **models.status(man, base)}, 0
    if args.action == "orphans":
        return {"ok": True, "orphans": models.orphans(man, base)}, 0
    if not args.engine and args.wave is None:
        raise models.ModelError("--wave N oder --engine ID angeben.")
    keys = models.select(man, engines=args.engine, wave=args.wave, base=base)
    if args.action == "verify":
        res = models.verify(man, base, keys)
        bad = [k for k, v in res.items() if v == "MISMATCH"]
        return {"ok": not bad, "files": res}, 8 if bad else 0
    setup_logging(load(), "models.log")
    res = models.download(man, base, keys)
    failed = {k: v for k, v in res.items() if v not in ("present", "downloaded")}
    return {"ok": not failed, "files": res, "failed": failed}, 8 if failed else 0


def _workflows(action: str) -> tuple[dict, int]:
    """Prüft UI-/API-Exporte gegen die laufende ComfyUI, erzeugt UI-Exporte oder stellt die
    Editor-Kopien (je Workflow ein eigener Seitenleisten-Ordner) bereit."""
    cfg = load()
    setup_logging(cfg)
    man = models.load_manifest(cfg.root, require_ui=action != "export-ui")
    if action == "install":  # frühere Sammel-Ablage aufräumen (nur eigene, registrierte Dateien)
        legacy = cfg.comfyui.path / "user" / "default" / "workflows" / "Darkfluenzer"
        for key in man.workflows:
            (legacy / f"{key}.json").unlink(missing_ok=True)
        if legacy.is_dir() and not any(legacy.iterdir()):
            legacy.rmdir()
    runtime.start(cfg)
    object_info = comfy.ComfyClient(cfg.comfyui.url, timeout=120).object_info()
    report: dict[str, list[str]] = {}
    for key, wf in man.workflows.items():
        graph = comfy.load_graph(man, wf)
        ui_path = man.root / "workflows" / wf.ui
        if action == "export-ui":
            ui = comfy.api_to_ui(graph, object_info)
            ui_path.write_text(json.dumps(ui, indent=1, ensure_ascii=False) + "\n")
        if action == "install":
            comfy.install_editor_copy(cfg, man, key)
        uploads = {(p.node, p.input) for p in wf.params.values() if p.upload}
        problems = comfy.check_graph(graph, object_info, uploads)
        normal = comfy.ui_to_api(comfy.api_to_ui(graph, object_info), object_info)
        if (
            not ui_path.is_file()
            or comfy.ui_to_api(json.loads(ui_path.read_text(encoding="utf-8")), object_info)
            != normal
        ):
            problems.append("UI-Export beschreibt einen anderen Rendergraphen als der API-Export")
        report[key] = problems
    ok = not any(report.values())
    return {"ok": ok, "workflows": report}, 0 if ok else 9


def _render(args: argparse.Namespace) -> tuple[dict, int]:
    cfg = load()
    setup_logging(cfg)
    man = models.load_manifest(cfg.root)
    if args.workflow not in man.workflows:
        raise comfy.ComfyError(f"Workflow '{args.workflow}' ist nicht registriert.")
    wf = man.workflows[args.workflow]
    values: dict = {}
    for item in args.set or []:
        name, _, raw = item.partition("=")
        if name not in wf.params:
            raise comfy.ComfyError(f"Parameter '{name}' ist für {args.workflow} nicht freigegeben.")
        typ = wf.params[name].type
        values[name] = int(raw) if typ == "int" else float(raw) if typ == "float" else raw
    uploads = {}
    for item in args.input or []:
        name, _, path = item.partition("=")
        uploads[name] = Path(path).expanduser().resolve()
    result = pipeline.render_evaluation(cfg, man, args.workflow, values, uploads)
    return {
        "ok": True,
        "prompt_id": result.prompt_id,
        "duration_s": result.duration_s,
        "outputs": [str(o.path) for o in result.outputs],
    }, 0


def _character(args: argparse.Namespace) -> tuple[dict, int]:
    cfg = load()
    setup_logging(cfg)
    if args.action == "scan":
        photos = training.scan(cfg.local)
        usable = sum(p.status == "ok" for p in photos)
        return {
            "ok": True,
            "photos": [asdict(p) for p in photos],
            "usable": usable,
            "min_images": training.MIN_IMAGES,
            "folder": str(training.character_dir(cfg.local) / "photos"),
        }, 0
    if args.action == "dataset":
        path = training.build_dataset(cfg.local, args.trigger, args.class_word)
        meta = json.loads((path / "dataset.json").read_text())
        return {"ok": True, "dataset": path.name, "images": len(meta["items"])}, 0
    # train-sdxl: Architekturbindung – nur SDXL-Basismodelle
    man = models.load_manifest(cfg.root)
    engine = man.engines.get(args.engine)
    if engine is None or engine.arch != "sdxl":
        raise training.TrainerUnavailable(
            f"Engine '{args.engine}' ist keine SDXL-Engine – SDXL-LoRAs nur für arch=sdxl."
        )
    if not args.dataset:
        raise training.DatasetIncomplete("--dataset ds_… angeben (siehe character dataset).")
    dataset = training.character_dir(cfg.local) / "dataset" / args.dataset
    if not (dataset / "dataset.json").is_file():
        raise training.DatasetIncomplete(f"Datensatz {args.dataset} existiert nicht.")
    if runtime.status(cfg)["state"] == "running":  # keine parallelen GPU-Jobs
        queue = comfy.ComfyClient(cfg.comfyui.url).queue()
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise training.TrainingError("ComfyUI rendert gerade – Training erst danach starten.")
    base = models.models_dir(cfg.root) / man.engine_files(args.engine)[0].target
    out = (
        models.models_dir(cfg.root)
        / "loras"
        / "sdxl_character"
        / f"{args.dataset}_{args.engine}_r{args.rank}_s{args.steps}.safetensors"
    )
    params = training.TrainParams(steps=args.steps, rank=args.rank, seed=args.seed)
    return {"ok": True, **training.train_sdxl_lora(base, dataset, out, params)}, 0


def _serve() -> tuple[dict, int]:
    from . import server  # aiohttp nur für den Server laden

    cfg = load()
    setup_logging(cfg)
    server.serve(cfg)
    return {"ok": True, "result": "stopped"}, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="darkfluenzer", description="Darkfluenzer-Dienst")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="area", required=True)
    cmd = sub.add_parser("comfy", help="verwaltete ComfyUI-Instanzen")
    cmd.add_argument("action", choices=["start", "stop", "status", "health"])
    cmd.add_argument("--instance", choices=list(INSTANCE_SECTIONS), default="media")
    cmd.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    mod = sub.add_parser("models", help="Modell-Registry workflows/manifest.toml")
    mod.add_argument("action", choices=["status", "download", "verify", "orphans"])
    mod.add_argument("--wave", type=int)
    mod.add_argument("--engine", action="append")
    mod.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    wfp = sub.add_parser("workflows", help="registrierte Workflows prüfen / UI-Export erzeugen")
    wfp.add_argument("action", choices=["check", "export-ui", "install"])
    wfp.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    ren = sub.add_parser("render", help="Evaluationslauf eines registrierten Workflows")
    ren.add_argument("workflow")
    ren.add_argument("--set", action="append", metavar="NAME=WERT")
    ren.add_argument("--input", action="append", metavar="NAME=DATEI")
    ren.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    chp = sub.add_parser("character", help="Charakter-LoRA: Bilder prüfen, Datensatz, Training")
    chp.add_argument("action", choices=["scan", "dataset", "train-sdxl"])
    chp.add_argument("--trigger", default="dfchar")
    chp.add_argument("--class-word", default="woman")
    chp.add_argument("--dataset")
    chp.add_argument("--engine", default="lustify_sdxl")
    chp.add_argument("--steps", type=int, default=1500)
    chp.add_argument("--rank", type=int, default=16)
    chp.add_argument("--seed", type=int, default=1)
    chp.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    srv = sub.add_parser("serve", help="Cockpit-Server (React-Build + Protobuf-API)")
    srv.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    for name, text in (
        ("up", "Cockpit-Server starten (idempotent)"),
        ("restart", "nur den Cockpit-Server neu starten"),
        ("down", "Cockpit + ComfyUI stoppen"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    args = parser.parse_args(argv)

    try:
        if args.area == "comfy":
            payload, code = _comfy(args.action, args.instance)
        elif args.area == "models":
            payload, code = _models(args)
        elif args.area == "workflows":
            payload, code = _workflows(args.action)
        elif args.area == "character":
            payload, code = _character(args)
        elif args.area == "serve":
            payload, code = _serve()
        elif args.area in ("up", "restart", "down"):
            cfg = load()
            setup_logging(cfg)
            fn = {
                "up": runtime.cockpit_up,
                "restart": runtime.cockpit_restart,
                "down": runtime.cockpit_down,
            }[args.area]
            payload, code = {"ok": True, **fn(cfg)}, 0
        else:
            payload, code = _render(args)
    except (comfy.ComfyError, pipeline.PipelineError, ValueError) as exc:
        details = getattr(exc, "details", {})
        payload = {"ok": False, "error": "workflow", "message": str(exc), "details": details}
        code = 9
    except training.TrainingError as exc:
        payload, code = {"ok": False, "error": exc.code, "message": str(exc)}, 10
    except (models.ManifestError, models.ModelError) as exc:
        payload, code = {"ok": False, "error": "models", "message": str(exc)}, 8
    except ConfigError as exc:
        payload, code = {"ok": False, "error": "config_invalid", "message": str(exc)}, 2
    except runtime.RuntimeFailure as exc:
        log.error("%s fehlgeschlagen: %s", getattr(args, "action", args.area), exc)
        payload = {"ok": False, "error": exc.code, "message": str(exc), "details": exc.details}
        code = exc.exit_code
    except Exception as exc:  # letzte Linie: nie still scheitern, immer melden
        log.exception("Unerwarteter Fehler bei %s", getattr(args, "action", args.area))
        payload, code = {"ok": False, "error": "internal", "message": repr(exc)}, 1
    _emit(payload, args.json)
    return code
