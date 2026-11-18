"""Bild-/Videoroute über registrierte Workflows; Master-First-Prüfungen.

Heute: Evaluationsläufe je Engine (``local/evaluation/<engine>/``, ohne Kundenbezug) und die
Prüfung, dass maskierte Bearbeitungen außerhalb der Maske pixelidentisch zum Master bleiben.
Die Kundenroute (3 Kandidaten je Auftrag in ``work/``) baut auf denselben Funktionen auf (S2/S5).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import ComfyConfig, Config
from ..nodes import comfy
from ..nodes.base import node_for
from ..store import MEDIA_KINDS, Store, sha256_file
from . import models, training
from .models import Lora, Manifest, Workflow

log = logging.getLogger("darkfluenzer.pipeline")

# Langvideo (V0 §10): Zwischenstände der Abschnitte in eigenem Ordner (ComfyUI-Ausgabe und local/),
# den die Galerie nicht aufnimmt; Länge und Abschnittslänge in Sekunden (keine Graph-Eingänge)
WORK_PREFIX = "darkfluenzer_work"
VIDEO_KEYS = ("duration_s", "segment_s")
# Vorrangklasse aus der Auftragsquelle; Kundentest-Aufträge laufen als Default (SP5 Schritt 6)
PRIORITY_OF_SOURCE = {
    "customer": "customer", "test": "default", "cloner": "default", "operator": "cockpit",
}  # fmt: skip
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
LAST_FRAME, LAST_SAVE = "df_last_frame", "df_last_save"  # zusätzliche Nodes je Abschnitt


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


def input_from_file(cfg: Config, rel: str, sha256: str) -> str:
    """Datei unter local/ (z. B. Vorlage) als Eingabebild: Inhalt gegen den gespeicherten
    SHA-256 geprüft, inhaltsadressiert unter ``local/evaluation/inputs`` abgelegt."""
    path = cfg.local / rel
    data = path.read_bytes() if path.is_file() else b""
    if hashlib.sha256(data).hexdigest() != sha256:
        raise PipelineError(f"{rel}: Datei fehlt oder wurde verändert.")
    return store_input(cfg, data, path.name)


def input_from_media(cfg: Config, media_id: int) -> str:
    """Vorhandenes Galerie-Medium als Eingabebild: exakt diese Datei (SHA-256 gegen den Index
    geprüft), inhaltsadressiert unter ``local/evaluation/inputs`` abgelegt wie ein Upload."""
    store = Store(cfg.local)
    try:
        row = store.media_by_id(media_id)
    finally:
        store.close()
    if row is None:
        raise PipelineError(f"Medium {media_id} ist nicht (mehr) in der Galerie.")
    if row["kind"] != "image":
        raise PipelineError(f"Medium {media_id} ist kein Bild.")
    path = cfg.local / row["path"]
    data = path.read_bytes() if path.is_file() else b""
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise PipelineError(f"Medium {media_id}: Datei fehlt oder wurde verändert.")
    return store_input(cfg, data, Path(row["path"]).name)


def video_plan(wf: Workflow, graph: dict, values: dict, max_s: float | None) -> dict | None:
    """Gesamtlänge und Abschnittslänge (Sekunden) in Abschnitte zerlegen; entfernt beide Werte aus
    ``values``. Jeder Abschnitt hat n·m+1 Frames (höchstens die Trainingslänge), Folgeabschnitte
    beginnen mit dem letzten Bild des vorigen – deren erstes Bild zählt nicht neu."""
    video = {k: values.pop(k) for k in VIDEO_KEYS if k in values}
    spec = wf.video
    if spec is None:
        if video:
            raise PipelineError(f"{wf.title}: Videolänge gibt es nur bei Video-Workflows.")
        return None
    if max_s is None:
        raise PipelineError("Obergrenze der Videolänge fehlt (production.video_max_s).")
    fps_param = wf.params[spec.fps]
    fps = float(values.get(spec.fps, graph[fps_param.node]["inputs"][fps_param.input]))
    if spec.mode == "seconds":  # ein Lauf, Länge direkt in Sekunden (LTX, SP1 Schritt 10)
        if video.get("segment_s", 0.0) != 0.0:  # 0 = keine Abschnitte (so im Job gespeichert)
            raise PipelineError(f"{wf.title}: Abschnitte gibt es bei diesem Workflow nicht.")
        top = min(max_s, spec.seconds_max)
        default = float(graph[spec.length_node]["inputs"][spec.length_input])
        duration = float(video.get("duration_s", default))
        seconds = round(duration)
        if not 1 <= seconds <= top or abs(duration - seconds) > 1e-9:
            raise PipelineError(f"Gesamtlänge {duration:g} s: ganze Sekunden von 1 bis {top:g}.")
        return {"fps": fps, "duration_s": float(seconds), "segment_s": 0.0, "frames": [],
                "length": seconds}  # fmt: skip
    m = spec.frames_multiple
    segment_max = (spec.segment_frames_max - 1) / fps
    default_frames = int(graph[spec.length_node]["inputs"][spec.length_input])
    duration = float(video.get("duration_s", (default_frames - 1) / fps))
    segment = float(video.get("segment_s", segment_max))
    if not 0 < duration <= max_s:
        raise PipelineError(f"Gesamtlänge {duration:g} s: erlaubt über 0 bis {max_s:g} s.")
    if not 0 < segment <= segment_max + 1e-9:
        raise PipelineError(
            f"Abschnitt höchstens {segment_max:.2f} s bei {fps:g} fps "
            f"({spec.segment_frames_max} Frames, Trainingslänge des Modells)."
        )
    step = max(m, round(segment * fps / m) * m)  # neue Frames je vollem Abschnitt
    left = max(m, round(duration * fps / m) * m)  # neue Frames insgesamt (ohne Startbild)
    frames = []
    while left > 0:
        frames.append(min(step, left) + 1)
        left -= min(step, left)
    return {
        "fps": fps,
        "duration_s": duration,
        "segment_s": segment,
        "frames": frames,
        "length": frames[0],
    }


def _input_tier(store: Store, rel: str) -> str | None:
    """Inhaltsstufe einer Eingabedatei: Stufe des byte-gleichen Galerie-Mediums, sonst explizit."""
    media = store.media_by_sha(sha256_file(store.local / rel))
    return store.media_tier(media["id"]) if media else "explizit"


LORA_KEY = "character_lora"  # Schlüssel der Charakter-LoRA in Job- und Stufenparametern
CHARACTER_KEY = "character"  # Kürzel der Figur, gegen deren Referenzsatz geprüft wird
KEYFRAMES_KEY = "keyframes"  # weitere Schlüsselbilder (Zeitachse B4) in den Jobparametern


def check_keyframes(wf: Workflow, plan: dict | None, frames: list[dict], limit: int) -> list[dict]:
    """Weitere Schlüsselbilder prüfen: nur Workflows mit Schlüsselbild-Kette, Zeitpunkt innerhalb
    der Videolänge (ohne Anfang und Ende, die Start- und Endbild tragen), Stärke 0…1, höchstens
    ``limit``. Liefert sie nach Zeit sortiert (``at_s``, ``image`` unter local/, ``strength``)."""
    if not frames:
        return []
    if wf.keyframes is None or not plan:
        raise PipelineError(f"{wf.title} nimmt keine weiteren Schlüsselbilder.")
    if len(frames) > limit:
        raise PipelineError(f"Höchstens {limit} weitere Schlüsselbilder.")
    duration = float(plan["duration_s"])
    out = []
    for f in frames:
        at, strength = float(f["at_s"]), float(f.get("strength", 1.0))
        if not 0 < at < duration:
            raise PipelineError(
                f"Schlüsselbild bei {at:g} s liegt nicht innerhalb 0…{duration:g} s."
            )
        if not 0 < strength <= 1:
            raise PipelineError(f"Schlüsselbild-Stärke {strength:g} muss in (0, 1] liegen.")
        out.append({"at_s": at, "image": str(f["image"]), "strength": strength})
    return sorted(out, key=lambda f: f["at_s"])


# Einstellungen, die einen Trainingslauf bestimmen (Gesamtschritte und Checkpoint-Abstand nicht:
# Verlängern, Beenden und Fortsetzen nutzen denselben Ordner)
RUN_SETTINGS = ("rank", "learning_rate", "seed")


def checkpoint_dir(cfg: Config, man: Manifest, wf: Workflow, dataset: str, values: dict) -> Path:
    """Checkpoint-Ordner eines Trainingslaufs (SP3 Schritt 3):
    ``characters/<kürzel>/training/<Datensatz>_<Einstellungen>/``. Ein erneuter Lauf mit derselben
    Figur, demselben Datensatz und denselben Einstellungen (fehlende aus dem Graphen) setzt dort
    fort."""
    parts = Path(dataset).parts  # characters/<kürzel>/datasets/<id>
    if len(parts) < 4 or parts[0] != "characters" or parts[2] != "datasets":
        raise PipelineError(f"Datensatz {dataset} liegt nicht im Charakterschema.")
    graph = comfy.load_graph(man, wf)
    settings = {
        k: values.get(k, graph[wf.params[k].node]["inputs"][wf.params[k].input])
        for k in RUN_SETTINGS
        if k in wf.params
    }
    tag = hashlib.sha256(json.dumps([wf.key, settings], sort_keys=True).encode()).hexdigest()[:10]
    return training.character_folders(cfg.local, parts[1]).training / f"{parts[3]}_{tag}"


def check_plan(
    cfg: Config,
    man: Manifest,
    wf: Workflow,
    lora: comfy.LoraUse | None,
    values: dict | None = None,
) -> list[tuple[models.CheckSpec, dict]]:
    """Prüfknoten der Prüfkette für diesen Lauf (E16/E17): Bild- und Video-Workflows, die Medien
    erzeugen (keine Analyse, kein Training), nur Prüfungen mit vorhandenen Modelldateien; Video
    nur Prüfungen mit ``video`` (Frameprüfung, zeitliche Konsistenz); Prüfungen mit Figur
    (Gesichtsidentität) nur, wenn der Auftrag die LoRA einer Figur trägt."""
    eng = man.engines[wf.engine]
    if wf.training or eng.kind not in ("image", "video") or eng.role == "analysis":
        return []
    video = eng.kind == "video"
    base = models.models_dir(cfg.root)
    plan = []
    for spec in man.checks.values():
        if (video and not spec.video) or (not video and not spec.image):
            continue
        files = man.engines[spec.engine].files
        if any(models.file_state(man.files[f], base) != "present" for f in files):
            log.info("Prüfung %s übersprungen: Modelldateien fehlen", spec.name)
            continue
        runtime: dict = {}
        if spec.character:
            if lora is None or not lora.lora.character:
                continue
            folder = training.character_folders(cfg.local, lora.lora.character).reference
            runtime = {
                "reference_dir": str(folder),
                "min_face_px": cfg.identity.min_face_px,
                "min_score": cfg.identity.min_score,
            }
        if spec.prompt:  # Prompttreue: der Prompt des Auftrags (ohne vorangestellten Trigger)
            runtime["prompt"] = str((values or {}).get("prompt", ""))
        plan.append((spec, runtime))
    return plan


def _check_media(store: Store, checks: list[dict], targets: dict, outputs: list[dict]) -> dict:
    """Messwerte je geprüftem Medium: Prüfknoten -> SaveImage-Knoten -> Ausgabe -> Medium."""
    by_node = {}
    for out in outputs:
        row = store.media_by_sha(out["sha256"])
        if row is not None:
            by_node.setdefault(str(out.get("node", "")), int(row["id"]))
    grouped: dict[int | None, list[dict]] = {}
    for c in checks:
        save = targets.get(str(c.get("node", "")))
        if save is not None:
            c = {**c, "save_node": save}
        grouped.setdefault(by_node.get(save) if save is not None else None, []).append(c)
    return grouped


def identity_overrides(cfg: Config, wf: Workflow, character: str) -> dict[tuple[str, str], object]:
    """Eingänge des Prüfknotens Gesichtsidentität (SP3 Schritt 7): Referenzordner ``reference/``
    der Figur, Mindestgröße und -sicherheit aus der Konfiguration ``[identity]``."""
    if not wf.identity:
        return {}
    folder = training.character_folders(cfg.local, character).reference
    return {
        (wf.identity, "reference_dir"): str(folder),
        (wf.identity, "min_face_px"): cfg.identity.min_face_px,
        (wf.identity, "min_score"): cfg.identity.min_score,
    }


def _fps(man: Manifest, wf: Workflow, values: dict) -> float:
    """Bildrate eines Video-Workflows: Wert des Auftrags, sonst aus dem Graphen."""
    name = wf.video.fps if wf.video else ""
    if name in values:
        return float(values[name])
    spec = wf.params.get(name)
    if spec is None:
        raise PipelineError(f"{wf.title}: Bildrate unbekannt (Schlüsselbilder).")
    return float(comfy.load_graph(man, wf)[spec.node]["inputs"][spec.input])


def check_lora(man: Manifest, wf: Workflow, key: str, character: str | None = None) -> Lora:
    """Die LoRA ist registriert, der Workflow hat einen Lader, und seine Engine darf sie laden
    (Trainings-Engine oder eingetragen in ``compatible``, SP3 Schritt 4). ``character``: Kürzel
    der Figur des Auftrags – eine Figur lädt nie die LoRA einer anderen (SP3 Schritt 6)."""
    lo = man.loras.get(key)
    if lo is None:
        raise PipelineError(f"LoRA '{key}' ist nicht registriert.")
    if character is not None and lo.character != character:
        raise PipelineError(f"LoRA '{key}' gehört zu einer anderen Figur.")
    if wf.lora is None:
        raise PipelineError(f"{wf.title} hat keinen Lader für eine Charakter-LoRA.")
    if lo.comfy_name not in models.engine_model_names(man.files, man.engines, man.loras, wf.engine):
        raise PipelineError(f"LoRA '{key}' passt nicht zur Engine {wf.engine}.")
    return lo


def active_lora(store: Store, man: Manifest, character_id: int, wf: Workflow) -> str:
    """Aktive LoRA der Figur für die Architektur der Workflow-Engine (SP3 Schritt 6), wenn diese
    Engine sie laden darf; sonst leer (Auftrag läuft „ohne Charakter-LoRA“)."""
    if wf.lora is None:
        return ""
    row = store.character(character_id)
    key = store.active_loras(character_id).get(man.engines[wf.engine].arch, "")
    if not key:
        return ""
    try:
        check_lora(man, wf, key, character=row["slug"])
    except PipelineError:
        return ""
    return key


def lora_use(store: Store, man: Manifest, wf: Workflow, params: dict) -> comfy.LoraUse | None:
    """Charakter-LoRA eines Jobs mit Trigger und Klasse aus dem Charakterprofil der LoRA."""
    key = str(params.get(LORA_KEY) or "")
    if not key:
        return None
    lo = check_lora(man, wf, key)
    row = store.character_by_slug(lo.character) if lo.character else None
    class_word = str(row["class_word"]) if row else ""
    return comfy.LoraUse(lo, " ".join(filter(None, (lo.trigger, class_word))))


def create_render(
    store: Store,
    man: Manifest,
    workflow_key: str,
    values: dict,
    inputs: dict,
    *,
    parent_media_id: int | None = None,
    command: dict | None = None,
    dataset: str | None = None,
    stage_id: int | None = None,
    video_max_s: float | None = None,
    inherit_tier: str | None = None,
    lora: str = "",
    character: str = "",
    keyframes: list[dict] | None = None,
    keyframes_max: int = 0,
) -> int:
    """Prüft einen Renderauftrag gegen die Registry und legt ihn als Job (Status queued) an.
    ``dataset``: Datensatzversion eines Trainingsworkflows (beim Anlegen festgelegt).
    ``lora``: Schlüssel der Charakter-LoRA (SP3 Schritt 5); leer = ohne Charakter-LoRA.

    ``inputs``: Upload-Parameter -> abgelegte Eingabedatei relativ zu ``local/``.
    ``command``: auslösender Befehl; Job und Befehlsjournal entstehen im selben Commit.
    """
    wf = man.workflows.get(workflow_key)
    if wf is None:
        raise PipelineError(f"Workflow '{workflow_key}' ist nicht registriert.")
    if wf.text is not None:  # Sprachworkflows laufen über nodes/llm, nie als Renderjob
        raise PipelineError(f"{wf.title} ist ein Sprachworkflow (KI-Studio), kein Render.")
    for name in inputs:
        if name not in wf.params or not wf.params[name].upload:
            raise PipelineError(f"{workflow_key}: '{name}' ist kein Upload-Parameter.")
    as_text = [n for n in values if n in wf.params and wf.params[n].upload]
    if as_text:
        raise PipelineError(f"{', '.join(as_text)}: Datei erwartet.")
    values = dict(values)
    graph = comfy.load_graph(man, wf)
    plan = video_plan(wf, graph, values, video_max_s)
    # Typen, Grenzen, Pflichtangaben und unbekannte Namen prüft die Registry-Bindung.
    comfy.apply_params(graph, wf, {**values, **inputs})
    if parent_media_id is not None and store.media_by_id(parent_media_id) is None:
        raise PipelineError(f"Ausgangsmedium {parent_media_id} ist nicht in der Galerie.")
    if wf.training != bool(dataset):
        raise PipelineError(f"{workflow_key}: Datensatz nur und immer für Trainingsworkflows.")
    if lora:
        check_lora(man, wf, lora)
    if wf.identity and not character:
        raise PipelineError(f"{wf.title}: eine Figur wählen (Referenzsatz für die Prüfung).")
    keyframes = check_keyframes(wf, plan, list(keyframes or []), keyframes_max)
    seeds = [values["seed"]] if "seed" in values else []
    prompt = str(values.get("prompt", ""))
    # Inhaltsstufe (Regel 13) an einer Stelle (SP2 Schritt 2, BUG-047): höchste Stufe aus
    # Workflow, Ausgangsmedium, jeder Eingabedatei (Galerie-Treffer über SHA-256, sonst explizit;
    # Masken ausgenommen) und beim Wiederholen der Stufe des Ursprungsjobs; fail-closed
    parent_tier = store.media_tier(parent_media_id) if parent_media_id is not None else "standard"
    upload_tiers = [
        _input_tier(store, rel) for name, rel in inputs.items() if not wf.params[name].tier_exempt
    ] + [_input_tier(store, kf["image"]) for kf in keyframes]  # Schlüsselbilder (FABLE-008)
    content_tier = models.higher_tier(
        wf.content,
        parent_tier,
        *upload_tiers,
        *([inherit_tier] if inherit_tier is not None else []),
    )
    if wf.training:  # Vorrang (SP5 Schritt 5): Training immer zuletzt
        priority = "training"
    elif stage_id is not None:
        priority = PRIORITY_OF_SOURCE.get(store.order_source_of_stage(stage_id) or "", "cockpit")
    else:
        priority = "cockpit"
    return store.create_job(
        None,
        wf.engine,
        workflow_key,
        prompt,
        {
            **values,
            **inputs,
            **({"dataset": dataset} if dataset else {}),
            **({LORA_KEY: lora} if lora else {}),
            **({CHARACTER_KEY: character} if character else {}),
            **({KEYFRAMES_KEY: keyframes} if keyframes else {}),
            **(
                {"duration_s": plan["duration_s"], "segment_s": plan["segment_s"], "video": plan}
                if plan
                else {}
            ),
        },
        seeds,
        parent_media_id=parent_media_id,
        command=command,
        stage_id=stage_id,
        content_tier=content_tier,
        priority=priority,
    )


# ------------------------------------------------------------------ Auftrag mit Stufen (V0 §4.3)


def run_render(
    cfg: Config,
    man: Manifest,
    job_id: int,
    timeout_s: float | None = None,
    client_id: str | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
    unload_first: bool = False,
) -> comfy.RenderResult:
    """Führt einen angelegten Job über den registrierten API-Workflow aus und hält das Ergebnis im
    Journal fest (``job.completed``). Ein bereits bei ComfyUI eingereichter Job (prompt_id, z. B.
    vor einem Backend-Neustart) wird nicht erneut eingereicht, sondern abgeholt. Für maskierte
    Bearbeitungen wird geprüft, dass außerhalb der Maske kein Pixel vom Master abweicht – sonst
    Fehler statt stiller Akzeptanz."""
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
            values = {n: v for n, v in params.items() if n not in uploads and n in wf.params}
            if is_cancelled():  # vor der Übermittlung abgebrochen: nichts starten
                if job["prompt_id"]:  # Wiederanlauf nach Abbruchwunsch (FABLE-015): Lauf beenden
                    inst = comfy.instance_of(cfg, man, wf)
                    with contextlib.suppress(comfy.ComfyError, OSError):
                        comfy.ComfyClient(inst.url, timeout=cfg.server.timeout_s).cancel(
                            job["prompt_id"]
                        )
                raise PipelineError("Vom Betreiber abgebrochen.")
            if job["status"] != "running":
                store.set_job_status(job_id, "running", pid=os.getpid())

            sent: dict = dict(job.get("graph") or {})  # Wiederanlauf: der eingereichte Graph

            def submitted(prompt_id: str, graph: dict) -> None:
                sent.clear()
                sent.update(graph)
                api = man.root / "workflows" / wf.api
                store.set_job_submitted(
                    job_id, prompt_id, graph, hashlib.sha256(api.read_bytes()).hexdigest()
                )
                if is_cancelled():  # Abbruch kam während der Übermittlung
                    inst = comfy.instance_of(cfg, man, wf)
                    comfy.ComfyClient(inst.url, timeout=cfg.server.timeout_s).cancel(prompt_id)

            plan = params.get("video") if wf.video else None
            if plan and len(plan["frames"]) > 1:  # Langvideo: Abschnitte, dann zusammensetzen
                result, outputs = _render_video(
                    cfg, man, wf, job_id, values, uploads, timeout_s, client_id, store=store,
                    plan=plan, on_submit=submitted, unload_first=unload_first,
                    is_cancelled=is_cancelled,
                    checks=check_plan(cfg, man, wf, lora_use(store, man, wf, params), values),
                )  # fmt: skip
            else:
                result, outputs = _render(
                    cfg,
                    man,
                    wf,
                    job_id,
                    values,
                    uploads,
                    timeout_s,
                    client_id,
                    lora=lora_use(store, man, wf, params),
                    keyframes=params.get(KEYFRAMES_KEY),
                    resume=job["prompt_id"],
                    on_submit=submitted,
                    unload_first=unload_first,
                    dataset=params.get("dataset"),
                    overrides=(
                        {(wf.video.length_node, wf.video.length_input): plan["length"]}
                        if plan and wf.video
                        else {}
                    )
                    | identity_overrides(cfg, wf, str(params.get(CHARACTER_KEY) or "")),
                )
            if is_cancelled():  # fertig, obwohl abgebrochen: Ergebnis verwerfen (BUG-043)
                for out in outputs:
                    (cfg.local / out["path"]).unlink(missing_ok=True)
                raise PipelineError("Vom Betreiber abgebrochen – Ergebnis verworfen.")
        except BaseException as exc:
            if is_cancelled():
                store.set_job_status(
                    job_id, "failed", error="Vom Betreiber abgebrochen.", cancelled=True
                )
            else:
                store.set_job_status(job_id, "failed", error=str(exc) or type(exc).__name__)
            raise
        try:  # Nachbearbeitung scheitert -> Job failed, nie running (FABLE-004)
            first = register_outputs(  # erst in die Galerie, dann gilt der Job als fertig
                store, job_id, outputs, local=cfg.local, parent=job["parent_media_id"],
                resized=man.engines[wf.engine].role in RESIZING_ROLES,
            )  # fmt: skip
            if result.checks:  # Messwerte je geprüftem Medium (Prüfkette), sonst Eingabebild
                reference = str(params.get(CHARACTER_KEY) or "")
                if not reference and (lora := params.get(LORA_KEY)) and lora in man.loras:
                    reference = man.loras[lora].character
                grouped = _check_media(store, result.checks, comfy.check_targets(sent), outputs)
                for media_id, entries in grouped.items():
                    checked = (
                        media_id or first or job["parent_media_id"] or _input_media(store, uploads)
                    )
                    store.add_media_checks(job_id, checked, reference, entries)
            store.set_job_status(
                job_id,
                "done",
                prompt_id=result.prompt_id,
                duration_s=result.duration_s,
                outputs=outputs,
                memory=result.memory,
                **({"checks": result.checks} if result.checks else {}),
            )
        except BaseException as exc:
            store.set_job_status(
                job_id,
                "failed",
                error=f"Nachbearbeitung fehlgeschlagen: {exc or type(exc).__name__}",
            )
            raise
        return result
    finally:
        store.close()


def _input_media(store: Store, uploads: dict[str, Path]) -> int | None:
    """Galerie-Medium des (ersten) Eingabebildes über seinen Inhalt, sonst None."""
    for path in uploads.values():
        if path.is_file():
            row = store.media_by_sha(sha256_file(path))
            if row:
                return int(row["id"])
    return None


RESIZING_ROLES = ("upscale", "output")  # Engines, deren Ergebnis nie als nativ gilt


def image_size(path: Path) -> tuple[int, int] | None:
    """Abmessungen aus dem Dateikopf (Dateiprüfung, keine Bildbewertung); None = kein Bild."""
    try:
        with Image.open(path) as img:
            return img.size
    except (OSError, ValueError):
        return None


def native_size(
    store: Store, size_px: tuple[int, int] | None, resized: bool, parent: int | None
) -> tuple[int, int] | None:
    """Native Erzeugungsgröße: eigene Größe, außer nach Hochskalieren/Ausgabeformat – dann die
    native Größe des Ausgangsmediums (unbekannt bleibt unbekannt, nie die Ausgabegröße)."""
    if not resized:
        return size_px
    row = store.media_by_id(parent) if parent else None
    if row and row.get("native_width") and row.get("native_height"):
        return int(row["native_width"]), int(row["native_height"])
    return None


def register_outputs(
    store: Store,
    job_id: int,
    outputs: list[dict],
    *,
    resized: bool = False,
    parent: int | None = None,
    local: Path | None = None,
) -> int | None:
    """Ausgaben eines Jobs in die Galerie; liefert das erste Ergebnis-Medium. Ist eine Ausgabe
    bitgleich zu einem vorhandenen Medium, zählt dieses als Ergebnis (BUG-064). ``resized``:
    Hochskalieren oder Ausgabeformat – native Größe vom Ausgangsmedium ``parent``."""
    first = None
    for out in outputs:
        if Path(out["path"]).suffix.lower() not in MEDIA_KINDS:
            continue
        size_px = image_size(local / out["path"]) if local is not None else None
        media_id = store.add_media(
            out["path"], out["sha256"], out["size"], job_id=job_id, size_px=size_px,
            native_px=native_size(store, size_px, resized, parent) if size_px else None,
        )  # fmt: skip
        if media_id is None:
            existing = store.media_by_sha(out["sha256"])
            media_id = existing["id"] if existing else None
        first = first or media_id
    if first is not None:
        store.set_job_media(job_id, first)
    return first


def render_evaluation(
    cfg: Config,
    man: Manifest,
    workflow_key: str,
    values: dict,
    uploads: dict[str, Path] | None = None,
    timeout_s: float | None = None,
) -> comfy.RenderResult:
    """Evaluationslauf von der Kommandozeile: derselbe Weg wie im Cockpit (Job ohne Kundenbezug)."""
    inputs = {n: store_input(cfg, p.read_bytes(), p.name) for n, p in (uploads or {}).items()}
    store = Store(cfg.local)
    try:
        job_id = create_render(
            store, man, workflow_key, values, inputs, video_max_s=cfg.production.video_max_s
        )
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
    timeout_s: float | None,
    client_id: str | None = None,
    *,
    resume: str | None = None,
    on_submit: Callable[[str, dict], None] | None = None,
    unload_first: bool = False,
    dataset: str | None = None,
    overrides: dict[tuple[str, str], object] | None = None,
    lora: comfy.LoraUse | None = None,
    keyframes: list[dict] | None = None,
) -> tuple[comfy.RenderResult, list[dict]]:
    workflow_key = wf.key

    inst = comfy.instance_of(cfg, man, wf)
    node = node_for(cfg, inst)
    node.start()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = evaluation_dir(cfg, wf.engine)
    overrides = dict(overrides or {})
    lora_prefix = f"loras/darkfluenzer/job{job_id}"  # SaveLoRA-Ziel unter ComfyUIs Ausgabe
    if wf.training:  # Datensatz in den ComfyUI-Eingang, Ziel der LoRA festlegen
        folder = node.stage_dataset(cfg.local / str(dataset))
        overrides |= {(wf.train_dataset, "folder"): folder, (wf.train_lora, "prefix"): lora_prefix}
        if wf.train_checkpoint:  # gleiche Figur, Datensatz, Einstellungen -> gleicher Ordner
            ckpt = checkpoint_dir(cfg, man, wf, str(dataset), values)
            overrides[(wf.train_checkpoint, "checkpoint_dir")] = str(ckpt)
    if resume:  # vor einem Neustart eingereicht: nur abholen, nie ein zweites Mal rendern
        if comfy.prompt_state(inst, resume) == "unknown":
            raise PipelineError(
                "Nach dem Neustart ist der Auftrag in ComfyUI nicht mehr vorhanden."
            )
        result = comfy.collect_workflow(
            cfg,
            man,
            workflow_key,
            values,
            resume,
            dest,
            stem=f"{workflow_key}_{stamp}",
            timeout_s=timeout_s,
            lora=lora,
        )
    else:
        client = comfy.ComfyClient(inst.url)
        for name, path in uploads.items():
            values[name] = client.upload_image(path)
        frames = [  # weitere Schlüsselbilder: Bildindex aus Zeit und Bildrate (Zeitachse B4)
            comfy.Keyframe(
                client.upload_image(cfg.local / kf["image"]),
                round(float(kf["at_s"]) * _fps(man, wf, values)),
                float(kf["strength"]),
            )
            for kf in keyframes or []
        ]
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
            on_submit=on_submit,
            unload_first=unload_first,
            overrides=overrides,
            lora=lora,
            checks=check_plan(cfg, man, wf, lora, values),
            keyframes=frames,
            sampling=man.check_frames,
        )
    checks: dict = {}
    masked: tuple[Path, int, list] | None = None  # (Maske, Randerweiterung, geprüfte Ausgaben)
    if wf.mask_output and "image" in uploads:
        mask_out = next((o for o in result.outputs if o.node == wf.mask_output), None)
        if mask_out is None:
            raise PipelineError(f"Ausgabe-Maske (Node {wf.mask_output}) fehlt – verworfen.")
        masked = (mask_out.path, 0, [o for o in result.outputs if o is not mask_out])
    elif {"image", "mask"} <= set(uploads):
        graph = comfy.load_graph(man, wf)
        grow_param = wf.params.get("mask_grow")
        grow = values.get(
            "mask_grow", graph[grow_param.node]["inputs"][grow_param.input] if grow_param else 0
        )
        masked = (uploads["mask"], int(grow), result.outputs)
    if masked:
        mask, grow, edited = masked
        for out in edited:
            diff = unmasked_difference(uploads["image"], out.path, mask, grow)
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
        "memory": result.memory,
        "provenance": result.provenance,
    }
    if wf.training:  # Ergebnis eines Trainings ist die registrierte LoRA-Datei
        record["outputs"].append(
            _adopt_lora(cfg, man, wf, inst, lora_prefix, dataset, values, stamp)
        )
    sidecar = dest / f"{workflow_key}_{stamp}.json"
    sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Evaluation %s: %s (%.1f s)", workflow_key, sidecar.name, result.duration_s)
    return result, record["outputs"]


def _render_video(
    cfg: Config,
    man: Manifest,
    wf: Workflow,
    job_id: int,
    values: dict,
    uploads: dict[str, Path],
    timeout_s: float | None,
    client_id: str | None,
    *,
    store: Store,
    plan: dict,
    on_submit: Callable[[str, dict], None],
    unload_first: bool,
    is_cancelled: Callable[[], bool],
    checks: list[tuple[models.CheckSpec, dict]] | None = None,
) -> tuple[comfy.RenderResult, list[dict]]:
    """Langvideo (V0 §10): Abschnitte nacheinander, jeder Folgeabschnitt startet mit dem letzten
    Bild des vorigen; danach in ComfyUI zusammengesetzt (doppeltes Übergangsbild entfernt). Fertige
    Abschnitte überstehen einen Neustart; fortgesetzt wird nur der unfertige. Die Prüfkette läuft
    nur im Zusammensetzen, auf den Frames des fertigen Videos (SP5 Schritt 7)."""

    spec = wf.video
    assert spec is not None
    inst = comfy.instance_of(cfg, man, wf)
    node = node_for(cfg, inst)
    node.start()
    client = comfy.ComfyClient(inst.url, client_id=client_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    work = cfg.local / WORK_PREFIX / f"job{job_id}"
    graph = comfy.load_graph(man, wf)
    create = next(k for k, n in graph.items() if n["class_type"] == "CreateVideo")
    save = next(k for k, n in graph.items() if n["class_type"] == "SaveVideo")
    frames = plan["frames"]
    start = uploads[spec.start_image]

    def submitted(idx: int) -> Callable[[str, dict], None]:
        def note(prompt_id: str, g: dict) -> None:
            store.segment_submitted(job_id, idx, prompt_id)
            on_submit(prompt_id, g)

        return note

    def pending(idx: int) -> str | None:
        row = store.job_segments(job_id).get(idx)
        known = row and row["prompt_id"] and comfy.prompt_state(inst, row["prompt_id"]) != "unknown"
        return row["prompt_id"] if known else None

    for idx, count in enumerate(frames):
        row = store.job_segments(job_id).get(idx)
        if row and row["done_at"]:
            start = cfg.local / row["last_frame"]
            continue
        if is_cancelled():
            raise PipelineError("Vom Betreiber abgebrochen.")
        log.info("Job %s: Abschnitt %d/%d (%d Frames)", job_id, idx + 1, len(frames), count)
        stem = f"s{idx + 1}_{stamp}"
        result = None
        if prompt_id := pending(idx):  # vor einem Neustart eingereicht: abholen
            try:
                result = comfy.collect_workflow(
                    cfg, man, wf.key, values, prompt_id, work, stem=stem, timeout_s=timeout_s
                )
            except comfy.ComfyError as exc:  # dort gescheitert: Abschnitt neu einreichen
                log.warning("Job %s: Abschnitt %d neu (%s)", job_id, idx + 1, exc)
        if result is None:
            vals = dict(values)
            for name, path in uploads.items():
                vals[name] = client.upload_image(start if name == spec.start_image else path)
            result = comfy.run_workflow(
                cfg, man, wf.key, vals, work, stem=stem, timeout_s=timeout_s, job_id=job_id,
                client_id=client_id, on_submit=submitted(idx),
                unload_first=unload_first and idx == 0,
                overrides={
                    (spec.length_node, spec.length_input): count,
                    (save, "filename_prefix"): f"{WORK_PREFIX}/{wf.key}_s{idx + 1}",
                },
                extra={
                    LAST_FRAME: {"class_type": "ImageFromBatch", "inputs": {
                        "image": [spec.decode, 0], "batch_index": count - 1, "length": 1}},
                    LAST_SAVE: {"class_type": "SaveImage", "inputs": {
                        "images": [LAST_FRAME, 0],
                        "filename_prefix": f"{WORK_PREFIX}/{wf.key}_last"}},
                },
            )  # fmt: skip
        video = next((o for o in result.outputs if o.path.suffix.lower() in VIDEO_SUFFIXES), None)
        last = next((o for o in result.outputs if o.node == LAST_SAVE), None)
        if video is None or last is None:
            raise PipelineError(f"Abschnitt {idx + 1}: Video oder letztes Bild fehlt.")
        rel = lambda p: p.relative_to(cfg.local).as_posix()  # noqa: E731
        store.segment_done(job_id, idx, rel(video.path), rel(last.path), result.duration_s)
        start = last.path

    segments = store.job_segments(job_id)
    joined: dict = {}
    prev: list | None = None
    for idx, count in enumerate(frames):
        name = client.upload_image(cfg.local / segments[idx]["video"])
        joined[f"v{idx}"] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        joined[f"c{idx}"] = {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [f"v{idx}", 0]},
        }
        image: list = [f"c{idx}", 0]
        if prev is not None:  # erstes Bild = letztes des vorigen Abschnitts: nicht doppelt
            joined[f"t{idx}"] = {
                "class_type": "ImageFromBatch",
                "inputs": {"image": image, "batch_index": 1, "length": count - 1},
            }
            joined[f"b{idx}"] = {
                "class_type": "ImageBatch",
                "inputs": {"image1": prev, "image2": [f"t{idx}", 0]},
            }
            image = [f"b{idx}", 0]
        prev = image
    plain = lambda node: {k: v for k, v in graph[node]["inputs"].items() if not isinstance(v, list)}  # noqa: E731
    joined["create"] = {
        "class_type": "CreateVideo",
        "inputs": {**plain(create), "images": prev, "fps": plan["fps"]},
    }
    joined["save"] = {"class_type": "SaveVideo", "inputs": {**plain(save), "video": ["create", 0]}}
    joined = comfy.inject_checks(joined, wf, checks or [], man.check_frames)
    joined = comfy.unique_outputs(joined, f"job{job_id}")
    dest = evaluation_dir(cfg, wf.engine)
    base = comfy.RenderResult(
        prompt_id="", workflow=wf.key, engine=wf.engine, params=values,
        provenance={**comfy.provenance(man, wf, values), "video": plan},
    )  # fmt: skip
    stem = f"{wf.key}_{stamp}"
    result = None
    if prompt_id := pending(len(frames)):
        base.prompt_id = prompt_id
        try:
            result = comfy.collect_graph(
                inst, prompt_id, dest, stem=stem, timeout_s=timeout_s, base=base,
                lost_after_s=cfg.production.comfy_lost_s,
            )  # fmt: skip
        except comfy.ComfyError as exc:
            log.warning("Job %s: Zusammensetzen neu (%s)", job_id, exc)
    if result is None:
        result = comfy.run_graph(
            inst, joined, dest, stem=stem, timeout_s=timeout_s, base=base, job_id=job_id,
            client_id=client_id, on_submit=submitted(len(frames)),
            lost_after_s=cfg.production.comfy_lost_s,
        )  # fmt: skip
    result.duration_s = round(
        result.duration_s
        + sum(r["duration_s"] or 0 for i, r in segments.items() if i < len(frames)),
        1,
    )
    record = {
        "created_at": stamp,
        "prompt_id": result.prompt_id,
        "duration_s": result.duration_s,
        "video": plan,
        "segments": [segments[i]["video"] for i in range(len(frames))],
        "outputs": [
            {**asdict(o), "path": o.path.relative_to(cfg.local).as_posix()} for o in result.outputs
        ],
        "inputs": {
            k: {"file": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for k, p in uploads.items()
        },
        "memory": result.memory,
        "provenance": result.provenance,
    }
    sidecar = dest / f"{stem}.json"
    sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Langvideo %s: %d Abschnitte, %s (%.1f s)", wf.key, len(frames), sidecar.name,
             result.duration_s)  # fmt: skip
    return result, record["outputs"]


def _adopt_lora(
    cfg: Config,
    man: Manifest,
    wf: Workflow,
    inst: ComfyConfig,
    prefix: str,
    dataset: str | None,
    values: dict,
    stamp: str,
) -> dict:
    """Trainierte LoRA aus ComfyUIs Ausgabe in die Modellablage übernehmen und registrieren
    (Basis, Datensatz, Trigger, Einstellungen; Status OFFEN bis zur Freigabe)."""
    src = node_for(cfg, inst).take_lora(prefix)
    graph = comfy.load_graph(man, wf)

    def value(name: str) -> object:  # gewählter oder im Graphen hinterlegter Wert
        p = wf.params[name]
        return values.get(name, graph[p.node]["inputs"][p.input])

    meta_file = cfg.local / str(dataset) / "dataset.json"  # Datensatz relativ zu local/
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    steps, rank = int(value("steps")), int(value("rank"))
    dataset_id = Path(str(dataset)).name
    parts = Path(str(dataset)).parts  # characters/<kürzel>/datasets/<id> (SP3 Schritt 1)
    character = parts[1] if len(parts) > 2 and parts[0] == "characters" else ""
    key = f"{dataset_id}_r{rank}_s{steps}_{stamp}"
    target = f"loras/characters/{character or 'ohne-figur'}/{key}.safetensors"
    dest = models.models_dir(cfg.root) / target
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)
    lora = Lora(
        key=key,
        target=target,
        size=dest.stat().st_size,
        sha256=sha256_file(dest),
        base_engine=wf.engine,
        base_file=man.engines[wf.engine].files[0],
        dataset=dataset_id,
        trigger=str(meta.get("trigger", "")),
        steps=steps,
        rank=rank,
        learning_rate=float(value("learning_rate")),
        strength=1.0,
        status="OFFEN",
        created_at=stamp,
        trainer="ComfyUI TrainLoraNode",
        character=character,
    )
    models.register_lora(man.root, lora)
    log.info("LoRA %s trainiert und registriert (%s)", key, target)
    return {
        "node": wf.train_lora,
        "path": dest.relative_to(cfg.local).as_posix(),
        "sha256": lora.sha256,
        "size": lora.size,
    }
