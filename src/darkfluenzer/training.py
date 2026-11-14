"""Charakter-LoRA (Phasenplan §6A): ein Eingangsordner → geprüfter, versionierter Datensatz →
architekturgebundenes LoRA-Training auf Apple MPS → Vorschau → Aktivierung erst nach Freigabe.

Bedienung: Bilder nach ``local/character/photos/`` kopieren. Originale werden nie verändert.
Gleiche Bildmenge ergibt dieselbe Datensatzversion (Hash), neue Bilder eine neue Version.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger("darkfluenzer.training")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SETTLE_S = 10.0  # Datei gilt erst als vollständig kopiert, wenn so lange unverändert
MIN_SIDE = 768
RECOMMENDED_SIDE = 1024
MIN_IMAGES = 15
# SDXL-Trainingsformate (≈1 MP), Bilder werden dem nächstgelegenen Seitenverhältnis zugeordnet
BUCKETS = [
    (1024, 1024),
    (896, 1152),
    (1152, 896),
    (832, 1216),
    (1216, 832),
    (768, 1344),
    (1344, 768),
]


class TrainingError(Exception):
    code = "TRAINING_FAILED"


class DatasetIncomplete(TrainingError):
    code = "DATASET_INCOMPLETE"


class TrainerUnavailable(TrainingError):
    code = "TRAINER_UNAVAILABLE"


@dataclass(frozen=True)
class Photo:
    name: str
    status: str  # ok | incomplete | unsupported | unreadable | duplicate | too_small
    sha256: str = ""
    width: int = 0
    height: int = 0
    note: str = ""


def character_dir(local: Path) -> Path:
    return local / "character"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def scan(local: Path, now: float | None = None) -> list[Photo]:
    """Prüft alle Dateien im Eingangsordner, ohne sie zu verändern."""
    folder = character_dir(local) / "photos"
    now = time.time() if now is None else now
    seen: dict[str, str] = {}
    result: list[Photo] = []
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXT:
            result.append(Photo(path.name, "unsupported", note="nur JPG, PNG, WebP"))
            continue
        if now - path.stat().st_mtime < SETTLE_S:
            result.append(Photo(path.name, "incomplete", note="Kopiervorgang läuft noch"))
            continue
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                width, height = ImageOps.exif_transpose(im).size
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            result.append(Photo(path.name, "unreadable", note=str(exc)[:120]))
            continue
        sha = _sha256(path)
        if sha in seen:
            result.append(Photo(path.name, "duplicate", sha, width, height, f"= {seen[sha]}"))
            continue
        seen[sha] = path.name
        if min(width, height) < MIN_SIDE:
            result.append(
                Photo(path.name, "too_small", sha, width, height, f"< {MIN_SIDE} px kurze Seite")
            )
            continue
        note = "" if min(width, height) >= RECOMMENDED_SIDE else f"< {RECOMMENDED_SIDE} px"
        result.append(Photo(path.name, "ok", sha, width, height, note))
    return result


def bucket(width: int, height: int) -> tuple[int, int]:
    aspect = width / height
    return min(BUCKETS, key=lambda b: abs(math.log((b[0] / b[1]) / aspect)))


def _fit(im: Image.Image, size: tuple[int, int]) -> tuple[Image.Image, int, int]:
    """Deckend skalieren und mittig beschneiden; liefert Bild und Crop-Offset (oben, links)."""
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    rw, rh = round(im.width * scale), round(im.height * scale)
    resized = im.resize((rw, rh), Image.Resampling.LANCZOS)
    left, top = (rw - tw) // 2, (rh - th) // 2
    return resized.crop((left, top, left + tw, top + th)), top, left


def build_dataset(
    local: Path, trigger: str = "dfchar", class_word: str = "woman", min_images: int = MIN_IMAGES
) -> Path:
    """Erzeugt (oder findet) die Datensatzversion zur aktuellen geprüften Bildmenge."""
    ok = [p for p in scan(local) if p.status == "ok"]
    if len(ok) < min_images:
        raise DatasetIncomplete(
            f"{len(ok)} geeignete Bilder in local/character/photos, mindestens {min_images} nötig."
        )
    set_id = hashlib.sha256("".join(sorted(p.sha256 for p in ok)).encode()).hexdigest()[:12]
    root = character_dir(local) / "dataset"
    target = root / f"ds_{set_id}"
    if (target / "dataset.json").is_file():
        return target  # gleiche Bildmenge -> gleiche, unveränderte Version
    tmp = root / f".ds_{set_id}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    items = []
    for i, photo in enumerate(ok, 1):
        with Image.open(character_dir(local) / "photos" / photo.name) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
        size = bucket(im.width, im.height)
        fitted, top, left = _fit(im, size)
        name = f"{i:03d}.png"
        fitted.save(tmp / name)
        items.append(
            {
                "file": name,
                "source": photo.name,
                "source_sha256": photo.sha256,
                "caption": f"photo of {trigger} {class_word}",
                "original_size": [im.height, im.width],
                "crop_top_left": [top, left],
                "target_size": [size[1], size[0]],
            }
        )
    meta = {
        "id": set_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "trigger": trigger,
        "class_word": class_word,
        "items": items,
        "captions": "Identitäts-Caption (Trigger + Klasse); Szenen-Captions per lokalem VLM: offen",
        "identity_check": "nicht durchgeführt – lokales Gesichtsmodell fehlt noch",
    }
    (tmp / "dataset.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    log.info("Datensatz ds_%s mit %d Bildern erzeugt", set_id, len(items))
    return target


@dataclass(frozen=True)
class TrainParams:
    steps: int = 1500
    rank: int = 16
    learning_rate: float = 1e-4
    seed: int = 1
    log_every: int = 25


def train_sdxl_lora(base_ckpt: Path, dataset_dir: Path, out_file: Path, p: TrainParams) -> dict:
    """SDXL-LoRA (UNet-Attention) auf MPS in FP32. Nur für SDXL-Basismodelle (z. B. LUSTIFY)."""
    try:
        import numpy as np
        import torch
        import torch.nn.functional as F
        from diffusers import DDPMScheduler, StableDiffusionXLPipeline
        from diffusers.utils import convert_state_dict_to_diffusers
        from peft import LoraConfig
        from peft.utils import get_peft_model_state_dict
    except ImportError as exc:
        raise TrainerUnavailable(
            f"Trainings-Abhängigkeiten fehlen ({exc.name}): uv sync --extra train"
        ) from exc
    if not torch.backends.mps.is_available():
        raise TrainerUnavailable("Apple MPS ist nicht verfügbar.")
    if out_file.exists():
        raise TrainingError(
            f"{out_file.name} existiert bereits – Versionen werden nie überschrieben."
        )
    meta = json.loads((dataset_dir / "dataset.json").read_text())
    device = torch.device("mps")
    torch.manual_seed(p.seed)
    t_start = time.monotonic()
    pipe = StableDiffusionXLPipeline.from_single_file(str(base_ckpt), torch_dtype=torch.float32)

    # 1) Latents und Text-Embeddings einmalig vorberechnen (Encoder bleiben eingefroren)
    for module in (pipe.vae, pipe.text_encoder, pipe.text_encoder_2):
        module.to(device).requires_grad_(False)
    cache = []
    with torch.no_grad():
        for item in meta["items"]:
            img = np.asarray(Image.open(dataset_dir / item["file"]).convert("RGB"))
            x = torch.from_numpy(img).float().div(127.5).sub(1).permute(2, 0, 1)[None].to(device)
            latent = pipe.vae.encode(x).latent_dist.sample() * pipe.vae.config.scaling_factor
            emb, _, pooled, _ = pipe.encode_prompt(
                item["caption"],
                device=device,
                num_images_per_prompt=1,
                do_classifier_free_guidance=False,
            )
            time_ids = torch.tensor(
                [[*item["original_size"], *item["crop_top_left"], *item["target_size"]]],
                dtype=torch.float32,
            )
            cache.append((latent.cpu(), emb.cpu(), pooled.cpu(), time_ids))
    for module in (pipe.vae, pipe.text_encoder, pipe.text_encoder_2):
        module.to("cpu")
    torch.mps.empty_cache()
    t_prep = time.monotonic() - t_start

    # 2) LoRA auf die Attention-Projektionen des UNet
    unet = pipe.unet.to(device)
    unet.requires_grad_(False)
    unet.add_adapter(
        LoraConfig(
            r=p.rank,
            lora_alpha=p.rank,
            init_lora_weights="gaussian",
            target_modules=["to_k", "to_q", "to_v", "to_out.0"],
        )
    )
    unet.enable_gradient_checkpointing()
    unet.train()
    trainable = [q for q in unet.parameters() if q.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=p.learning_rate, weight_decay=1e-2)
    scheduler = DDPMScheduler.from_config(pipe.scheduler.config)
    prediction = scheduler.config.prediction_type
    rng = random.Random(p.seed)
    losses: list[float] = []
    t_train = time.monotonic()
    for step in range(1, p.steps + 1):
        latent, emb, pooled, time_ids = (t.to(device) for t in cache[rng.randrange(len(cache))])
        noise = torch.randn_like(latent)
        timesteps = torch.randint(
            0, scheduler.config.num_train_timesteps, (1,), device=device
        ).long()
        noisy = scheduler.add_noise(latent, noise, timesteps)
        pred = unet(
            noisy,
            timesteps,
            encoder_hidden_states=emb,
            added_cond_kwargs={"text_embeds": pooled, "time_ids": time_ids},
        ).sample
        target = (
            noise if prediction == "epsilon" else scheduler.get_velocity(latent, noise, timesteps)
        )
        loss = F.mse_loss(pred.float(), target.float())
        loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        value = loss.item()
        if not math.isfinite(value):
            raise TrainingError(
                f"Loss ist bei Schritt {step} nicht endlich ({value}) – abgebrochen."
            )
        losses.append(value)
        if step % p.log_every == 0 or step == p.steps:
            rate = (time.monotonic() - t_train) / step
            log.info(
                "LoRA Schritt %d/%d loss=%.4f %.2f s/Schritt",
                step,
                p.steps,
                sum(losses[-p.log_every :]) / len(losses[-p.log_every :]),
                rate,
            )

    # 3) Speichern im diffusers-LoRA-Format (lädt in ComfyUI über LoraLoader)
    state = convert_state_dict_to_diffusers(get_peft_model_state_dict(unet))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_file.parent) as tmp:
        StableDiffusionXLPipeline.save_lora_weights(
            tmp, unet_lora_layers=state, safe_serialization=True
        )
        os.replace(Path(tmp) / "pytorch_lora_weights.safetensors", out_file)
    train_s = time.monotonic() - t_train
    provenance = {
        "lora_file": out_file.name,
        "lora_sha256": _sha256(out_file),
        "architecture": "sdxl",
        "base_checkpoint": base_ckpt.name,
        "dataset": meta["id"],
        "trigger": meta["trigger"],
        "params": asdict(p),
        "precision": "fp32",
        "device": "mps",
        "prepare_s": round(t_prep, 1),
        "train_s": round(train_s, 1),
        "s_per_step": round(train_s / p.steps, 2),
        "loss_first_25": round(sum(losses[:25]) / min(25, len(losses)), 4),
        "loss_last_25": round(sum(losses[-25:]) / min(25, len(losses)), 4),
        "versions": {"torch": torch.__version__, "diffusers": __import__("diffusers").__version__},
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "trained_not_approved",
    }
    out_file.with_suffix(".json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance
