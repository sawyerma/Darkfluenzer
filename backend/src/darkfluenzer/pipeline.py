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
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy, models, training
from .config import ComfyConfig, Config
from .models import Lora, Manifest, Workflow
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
) -> int:
    """Prüft einen Renderauftrag gegen die Registry und legt ihn als Job (Status queued) an.
    ``dataset``: Datensatzversion eines Trainingsworkflows (beim Anlegen festgelegt).

    ``inputs``: Upload-Parameter -> abgelegte Eingabedatei relativ zu ``local/``.
    ``command``: auslösender Befehl; Job und Befehlsjournal entstehen im selben Commit.
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
    if parent_media_id is not None and store.media_by_id(parent_media_id) is None:
        raise PipelineError(f"Ausgangsmedium {parent_media_id} ist nicht in der Galerie.")
    if wf.training != bool(dataset):
        raise PipelineError(f"{workflow_key}: Datensatz nur und immer für Trainingsworkflows.")
    seeds = [values["seed"]] if "seed" in values else []
    prompt = str(values.get("prompt", ""))
    return store.create_job(
        None,
        wf.engine,
        workflow_key,
        prompt,
        {**values, **inputs, **({"dataset": dataset} if dataset else {})},
        seeds,
        parent_media_id=parent_media_id,
        command=command,
        stage_id=stage_id,
    )


# ------------------------------------------------------------------ Auftrag mit Stufen (V0 §4.3)


def _journal(store: Store, command: dict | None, entity: str) -> None:
    """Befehl im selben Commit wie sein Effekt festhalten und abschließen."""
    if command:
        store.record_command(**command, entity=entity)
        store.finish_command(command["request_id"], "completed")


def create_order(
    store: Store,
    man: Manifest,
    workflow_key: str,
    values: dict,
    inputs: dict,
    *,
    count: int,
    finish_workflow: str = "",
    parent_media_id: int | None = None,
    command: dict | None = None,
    source: str = "operator",
    origin: int | None = None,
) -> tuple[str, list[int]]:
    """Auftrag des Betreibers: Stufe 1 rendert ``count`` Kandidaten mit fortlaufenden Seeds und
    wartet dann auf die Auswahl; optional wird der ausgewählte Kandidat mit ``finish_workflow``
    (Eingang ``image``) fertiggestellt. Auftrag, Stufe, Jobs und Befehl in einem Commit."""
    wf = man.workflows.get(workflow_key)
    if wf is None:
        raise PipelineError(f"Workflow '{workflow_key}' ist nicht registriert.")
    if wf.training:
        raise PipelineError("Ein Training ist kein Kandidatenauftrag.")
    seed = wf.params.get("seed")
    if count < 1 or (count > 1 and seed is None):
        raise PipelineError(f"{workflow_key}: mehrere Kandidaten brauchen einen Seed-Parameter.")
    if finish_workflow:
        fw = man.workflows.get(finish_workflow)
        if fw is None or "image" not in fw.params or not fw.params["image"].upload or fw.training:
            raise PipelineError(f"Fertigstellen mit '{finish_workflow}' ist nicht möglich.")
        extra = [n for n, p in fw.params.items() if p.required and n != "image"]
        if extra:
            raise PipelineError(f"Fertigstellen mit {fw.title} braucht zusätzlich: {extra}.")
    graph = comfy.load_graph(man, wf)
    base = int(values.get("seed", graph[seed.node]["inputs"][seed.input])) if seed else 0
    top = int(seed.max) if seed and seed.max is not None else 2**32 - 1
    params = {"values": values, "inputs": inputs, "finish": finish_workflow, "origin": origin}
    with store.tx():
        order = store.create_production_order(
            source, man.engines[wf.engine].kind, str(values.get("prompt", "")) or wf.title
        )
        stage = store.add_stage(order.id, "candidates", workflow_key, params, count)
        jobs = [
            create_render(
                store,
                man,
                workflow_key,
                {**values, "seed": (base + i) % (top + 1)} if seed else dict(values),
                inputs,
                parent_media_id=parent_media_id,
                stage_id=stage.id,
            )
            for i in range(count)
        ]
        _journal(store, command, f"order:{order.order_no}")
    return order.order_no, jobs


def advance_order(store: Store, job_id: int) -> None:
    """Nach dem Ende eines Jobs: ist seine Stufe vollständig, wartet sie auf die Auswahl
    (Kandidaten), ist fertig (Fertigstellen -> Auftrag zur Prüfung) oder fehlgeschlagen."""
    stage_id = store.job(job_id).get("stage_id")
    if not stage_id:
        return
    stage = store.stage(stage_id)
    jobs = store.stage_jobs(stage_id)
    if stage.status != "running" or any(j["status"] in ("queued", "running") for j in jobs):
        return
    done = [j for j in jobs if j["status"] == "done" and j["media_id"]]
    with store.tx():
        if not done:
            error = next((j["error"] for j in reversed(jobs) if j["error"]), "kein Ergebnis")
            store.set_stage(stage_id, "failed", error=error)
        elif stage.kind == "candidates":  # die kreative Auswahl trifft immer der Betreiber
            store.set_stage(stage_id, "waiting")
        else:
            store.set_stage(stage_id, "done", selected_media_id=done[-1]["media_id"])
            store.transition(store.order_by_id(stage.order_id).order_no, "review")


def select_candidate(
    cfg: Config, store: Store, man: Manifest, order_no: str, media_id: int, command: dict
) -> list[int]:
    """Auswahl des Betreibers; danach Fertigstellen (falls gewählt) mit genau diesem Medium,
    sonst geht der Auftrag zur Prüfung. Liefert neu angelegte Jobs."""
    order = store.order(order_no)
    stages = store.stages(order.id)
    stage = stages[-1] if stages else None
    if stage is None or stage.kind != "candidates" or stage.status != "waiting":
        raise PipelineError(f"{order_no} wartet nicht auf eine Auswahl.")
    if media_id not in {j["media_id"] for j in store.stage_jobs(stage.id)}:
        raise PipelineError(f"Medium {media_id} ist kein Kandidat von {order_no}.")
    finish = str(stage.params.get("finish") or "")
    image = input_from_media(cfg, media_id) if finish else ""
    with store.tx():
        store.set_stage(stage.id, "done", selected_media_id=media_id)
        jobs = []
        if finish:
            nxt = store.add_stage(order.id, "finish", finish, {"inputs": {"image": image}}, 1)
            jobs.append(
                create_render(
                    store,
                    man,
                    finish,
                    {},
                    {"image": image},
                    parent_media_id=media_id,
                    stage_id=nxt.id,
                )
            )
        else:
            store.transition(order_no, "review")
        _journal(store, command, f"order:{order_no}")
    return jobs


def retry_stage(
    store: Store, man: Manifest, order_no: str, seq: int, max_attempts: int, command: dict
) -> list[int]:
    """Fehlgeschlagene Jobs einer Stufe mit denselben Parametern erneut anlegen."""
    order = store.order(order_no)
    stage = next((st for st in store.stages(order.id) if st.seq == seq), None)
    if stage is None or stage.status not in ("failed", "waiting"):
        raise PipelineError(f"{order_no}: Stufe {seq} ist nicht wiederholbar.")
    failed = [j for j in store.stage_jobs(stage.id) if j["status"] == "failed"]
    if not failed:
        raise PipelineError(f"{order_no}: Stufe {seq} hat keine fehlgeschlagenen Jobs.")
    if stage.attempts >= max_attempts:
        raise PipelineError(f"{order_no}: höchstens {max_attempts} Versuche je Stufe.")
    wf = man.workflows.get(stage.workflow)
    if wf is None:
        raise PipelineError(f"Workflow '{stage.workflow}' ist nicht mehr registriert.")
    with store.tx():
        store.set_stage(stage.id, "running", retry=True)
        jobs = []
        for j in failed:
            old = store.job(j["id"])
            uploads = {n for n, p in wf.params.items() if p.upload}
            jobs.append(
                create_render(
                    store,
                    man,
                    stage.workflow,
                    {n: v for n, v in old["params"].items() if n in wf.params and n not in uploads},
                    {n: v for n, v in old["params"].items() if n in uploads},
                    parent_media_id=old["parent_media_id"],
                    stage_id=stage.id,
                )
            )
        _journal(store, command, f"order:{order_no}")
    return jobs


def run_render(
    cfg: Config,
    man: Manifest,
    job_id: int,
    timeout_s: float = 3600.0,
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
            if job["status"] != "running":
                store.set_job_status(job_id, "running", pid=os.getpid())

            def submitted(prompt_id: str, graph: dict) -> None:
                api = man.root / "workflows" / wf.api
                store.set_job_submitted(
                    job_id, prompt_id, graph, hashlib.sha256(api.read_bytes()).hexdigest()
                )

            result, outputs = _render(
                cfg,
                man,
                wf,
                job_id,
                values,
                uploads,
                timeout_s,
                client_id,
                resume=job["prompt_id"],
                on_submit=submitted,
                unload_first=unload_first,
                dataset=params.get("dataset"),
            )
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
            memory=result.memory,
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
    *,
    resume: str | None = None,
    on_submit: Callable[[str, dict], None] | None = None,
    unload_first: bool = False,
    dataset: str | None = None,
) -> tuple[comfy.RenderResult, list[dict]]:
    workflow_key = wf.key
    from . import runtime

    inst = comfy.instance_of(cfg, man, wf)
    runtime.start(cfg, inst.name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = evaluation_dir(cfg, wf.engine)
    overrides: dict[tuple[str, str], object] = {}
    lora_prefix = f"loras/darkfluenzer/job{job_id}"  # SaveLoRA-Ziel unter ComfyUIs Ausgabe
    if wf.training:  # Datensatz in den ComfyUI-Eingang, Ziel der LoRA festlegen
        folder = training.stage_dataset(cfg.local / str(dataset), inst.folder("input"))
        overrides = {(wf.train_dataset, "folder"): folder, (wf.train_lora, "prefix"): lora_prefix}
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
        )
    else:
        client = comfy.ComfyClient(inst.url)
        for name, path in uploads.items():
            values[name] = client.upload_image(path)
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
    src = training.take_lora(inst.folder("output"), prefix)
    graph = comfy.load_graph(man, wf)

    def value(name: str) -> object:  # gewählter oder im Graphen hinterlegter Wert
        p = wf.params[name]
        return values.get(name, graph[p.node]["inputs"][p.input])

    meta_file = cfg.local / str(dataset) / "dataset.json"  # Datensatz relativ zu local/
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    steps, rank = int(value("steps")), int(value("rank"))
    dataset_id = Path(str(dataset)).name
    key = f"{dataset_id}_r{rank}_s{steps}_{stamp}"
    target = f"loras/characters/{key}.safetensors"
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
    )
    models.register_lora(man.root, lora)
    log.info("LoRA %s trainiert und registriert (%s)", key, target)
    return {
        "node": wf.train_lora,
        "path": dest.relative_to(cfg.local).as_posix(),
        "sha256": lora.sha256,
        "size": lora.size,
    }


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
        (2, cfg.comfyui.path / "output", None),
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
