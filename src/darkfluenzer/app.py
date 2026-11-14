"""Einstiegspunkt des Darkfluenzer-Dienstes (CLI). Die macOS-App ruft genau diese Befehle auf.

    python -m darkfluenzer comfy start|stop|status|health [--json]
    python -m darkfluenzer models status|orphans [--json]
    python -m darkfluenzer models download|verify (--wave N | --engine ID ...) [--json]

Exit-Codes: 0 ok, 1 Fehler, 2 Konfiguration, 3 fremde Instanz, 4 Start fehlgeschlagen,
5 belegt, 6 Stop fehlgeschlagen, 7 nicht gesund, 8 Modell-/Manifestfehler.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__, models, runtime
from .config import ConfigError, load, project_root, setup_logging

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
    if not payload.get("ok", True):
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


def _comfy(action: str) -> tuple[dict, int]:
    cfg = load()
    setup_logging(cfg)
    if action == "start":
        return {"ok": True, **runtime.start(cfg)}, 0
    if action == "stop":
        return {"ok": True, **runtime.stop(cfg)}, 0
    st = runtime.status(cfg)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="darkfluenzer", description="Darkfluenzer-Dienst")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="area", required=True)
    comfy = sub.add_parser("comfy", help="verwaltete ComfyUI-Instanz")
    comfy.add_argument("action", choices=["start", "stop", "status", "health"])
    comfy.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    mod = sub.add_parser("models", help="Modell-Registry workflows/manifest.toml")
    mod.add_argument("action", choices=["status", "download", "verify", "orphans"])
    mod.add_argument("--wave", type=int)
    mod.add_argument("--engine", action="append")
    mod.add_argument("--json", action="store_true", help="maschinenlesbare Ausgabe")
    args = parser.parse_args(argv)

    try:
        payload, code = _comfy(args.action) if args.area == "comfy" else _models(args)
    except (models.ManifestError, models.ModelError) as exc:
        payload, code = {"ok": False, "error": "models", "message": str(exc)}, 8
    except ConfigError as exc:
        payload, code = {"ok": False, "error": "config_invalid", "message": str(exc)}, 2
    except runtime.RuntimeFailure as exc:
        log.error("%s fehlgeschlagen: %s", args.action, exc)
        payload = {"ok": False, "error": exc.code, "message": str(exc), "details": exc.details}
        code = exc.exit_code
    except Exception as exc:  # letzte Linie: nie still scheitern, immer melden
        log.exception("Unerwarteter Fehler bei %s", args.action)
        payload, code = {"ok": False, "error": "internal", "message": repr(exc)}, 1
    _emit(payload, args.json)
    return code
