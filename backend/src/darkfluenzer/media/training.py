"""Charakter-LoRA (Phasenplan §6A): ein Eingangsordner → geprüfter, versionierter Datensatz →
architekturgebundenes LoRA-Training auf Apple MPS → Vorschau → Aktivierung erst nach Freigabe.

Bedienung: Bilder in den Trainingsdatenordner des Charakterprofils kopieren (Profil 1:
``local/character/photos/``). Originale werden nie verändert.
Gleiche Bildmenge ergibt dieselbe Datensatzversion (Hash), neue Bilder eine neue Version.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import TrainingConfig

log = logging.getLogger("darkfluenzer.training")

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


@dataclass(frozen=True)
class Photo:
    name: str
    status: str  # ok | incomplete | unsupported | unreadable | duplicate | too_small
    sha256: str = ""
    width: int = 0
    height: int = 0
    note: str = ""


@dataclass(frozen=True)
class Folders:
    """Ordner eines Charakters (SP3 Schritt 1): ``local/characters/<kürzel>/`` mit Trainingsfotos
    (nur gelesen), Referenzfotos für die Gesichtsprüfung, Datensatzversionen und Trainingsstände."""

    photos: Path
    reference: Path
    datasets: Path
    training: Path

    @property
    def root(self) -> Path:
        return self.photos.parent


def character_folders(local: Path, slug: str) -> Folders:
    """Das eine Ordnerschema je Charakter (BUG-078)."""
    root = local / "characters" / slug
    return Folders(root / "photos", root / "reference", root / "datasets", root / "training")


def copy_verified(src: Path, dst: Path) -> list[Path]:
    """Alle Dateien unter ``src`` nach ``dst`` (gleiche relative Pfade), jede per SHA-256
    geprüft; eine vorhandene gleiche Datei bleibt, eine abweichende bricht ab, bevor etwas
    festgeschrieben wird. Liefert die Quelldateien, die jetzt sicher am Ziel liegen."""
    if not src.is_dir() or src.resolve() == dst.resolve():
        return []
    done = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        target = dst / path.relative_to(src)
        sha = _sha256(path)
        if target.exists():
            if _sha256(target) != sha:
                raise TrainingError(
                    f"{target} existiert schon mit anderem Inhalt – Umzug gestoppt."
                )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if _sha256(target) != sha:
                raise TrainingError(f"{target}: Kopie weicht ab – Umzug gestoppt.")
        done.append(path)
    return done


def remove_moved(moved: list[Path], roots: list[Path]) -> None:
    """Nach dem Festschreiben: umgezogene Quelldateien löschen, danach nur leere Ordner unter den
    alten Wurzeln (keine fremden Dateien)."""
    for path in moved:
        path.unlink(missing_ok=True)
    for root in roots:
        if not root.is_dir():
            continue
        for folder in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
        if not any(root.iterdir()):
            root.rmdir()


def add_photos(target: Path, files: list[tuple[str, bytes]], rules: TrainingConfig) -> int:
    """Fotos aus dem Cockpit ablegen (Befehl 67): erst alle prüfen, dann schreiben. Gleiche Bytes
    schon vorhanden -> übersprungen; gleicher Name, anderer Inhalt -> Name mit Nummer. Liefert die
    Zahl neu abgelegter Dateien."""
    checked = []
    for filename, data in files:
        name = Path(filename).name
        suffix = Path(name).suffix.lower()
        if not name or name.startswith(".") or suffix not in rules.suffixes:
            raise TrainingError(f"{filename or 'Datei'}: nur {', '.join(rules.suffixes)}.")
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise TrainingError(f"{name}: kein lesbares Bild ({str(exc)[:80]}).") from exc
        checked.append((name, data))
    target.mkdir(parents=True, exist_ok=True)
    present = {_sha256(p) for p in target.iterdir() if p.is_file()}
    added = 0
    for name, data in checked:
        sha = hashlib.sha256(data).hexdigest()
        if sha in present:
            continue
        dest, n = target / name, 1
        while dest.exists():
            n += 1
            dest = target / f"{Path(name).stem}-{n}{Path(name).suffix}"
        tmp = dest.with_name(f".{dest.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        present.add(sha)
        added += 1
    return added


_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def slugify(name: str) -> str:
    """Kürzel aus dem Namen: Kleinbuchstaben, Ziffern und Bindestriche (Ordnername)."""
    text = "".join(_UMLAUTS.get(c, c) for c in name.strip().lower())
    out, dash = [], False
    for c in text:
        if c.isascii() and c.isalnum():
            out.append(c)
            dash = False
        elif not dash and out:
            out.append("-")
            dash = True
    return "".join(out).strip("-") or "charakter"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def scan(folder: Path, rules: TrainingConfig, now: float | None = None) -> list[Photo]:
    """Prüft alle Dateien im Trainingsdatenordner ``folder``, ohne sie zu verändern."""
    now = time.time() if now is None else now
    seen: dict[str, str] = {}
    result: list[Photo] = []
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() == CAPTION_SUFFIX:  # Beschriftung eines Fotos (SP3 Schritt 2)
            if not any(path.with_suffix(sfx).is_file() for sfx in rules.suffixes):
                result.append(Photo(path.name, "unsupported", note="Beschriftung ohne Foto"))
            continue
        if path.suffix.lower() not in rules.suffixes:
            result.append(Photo(path.name, "unsupported", note="nur " + ", ".join(rules.suffixes)))
            continue
        if now - path.stat().st_mtime < rules.settle_s:
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
        if min(width, height) < rules.min_side:
            note = f"< {rules.min_side} px kurze Seite"
            result.append(Photo(path.name, "too_small", sha, width, height, note))
            continue
        good = min(width, height) >= rules.recommended_side
        note = "" if good else f"< {rules.recommended_side} px"
        result.append(Photo(path.name, "ok", sha, width, height, note))
    return result


def signature(folders: Folders, rules: TrainingConfig, now: float | None = None) -> tuple:
    """Günstiger Änderungsstempel von Trainingsordner und Datensätzen (Name, Größe, mtime) ohne
    Hashen. Solange eine Datei noch kopiert wird, ändert er sich mit der Zeit (erneut prüfen)."""
    now = time.time() if now is None else now
    entries = []
    for folder in (folders.photos, folders.datasets):
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            stat = path.stat()
            entries.append((folder.name, path.name, stat.st_size, stat.st_mtime_ns))
            if now - stat.st_mtime < rules.settle_s:
                entries.append(("settling", int(now)))
    return tuple(entries)


def datasets(root: Path) -> list[dict]:
    """Vorhandene Datensatzversionen unter ``root`` (neueste zuerst) aus ihren ``dataset.json``."""
    found = []
    for meta in root.glob("ds_*/dataset.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found.append(
            {
                "id": meta.parent.name,
                "images": len(data.get("items") or []),
                "created_at": str(data.get("created_at", "")),
                "trigger": str(data.get("trigger", "")),
            }
        )
    return sorted(found, key=lambda d: d["created_at"], reverse=True)


def stage_dataset(dataset_dir: Path, input_dir: Path) -> str:
    """Legt eine Datensatzversion für ComfyUI-Training in dessen Eingang ab: Bilder und je Bild
    die Caption als ``.txt`` (gleicher Name). Liefert den Ordner relativ zum Eingang; eine schon
    abgelegte Version bleibt unverändert (gleiche ID = gleicher Inhalt)."""
    meta = json.loads((dataset_dir / "dataset.json").read_text(encoding="utf-8"))
    rel = f"darkfluenzer_datasets/{dataset_dir.name}"
    target = input_dir / rel
    if target.is_dir():
        return rel
    tmp = target.with_name(f".{target.name}.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for item in meta["items"]:
        shutil.copy2(dataset_dir / item["file"], tmp / item["file"])
        (tmp / Path(item["file"]).with_suffix(".txt").name).write_text(
            item["caption"], encoding="utf-8"
        )
    os.replace(tmp, target)
    return rel


def take_lora(output_dir: Path, prefix: str) -> Path:
    """Die von SaveLoRA unter ``prefix`` gespeicherte Datei (``<prefix>_<n>_steps_<z>_``)."""
    found = sorted(output_dir.glob(f"{prefix}_*.safetensors"))
    if len(found) != 1:
        raise TrainingError(f"LoRA-Datei unter {prefix} nicht eindeutig gefunden ({len(found)}).")
    return found[0]


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


CAPTION_SUFFIX = ".txt"


def caption_for(photo: Path, base: str, trigger: str) -> str:
    """Beschriftung eines Fotos: gleichnamige .txt daneben (mit Trigger und Klasse davor, falls der
    Text den Trigger nicht schon enthält), sonst nur Trigger und Klasse."""
    path = photo.with_suffix(CAPTION_SUFFIX)
    text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if not text:
        return base
    return text if trigger in text.split() else f"{base}, {text}"


def build_dataset(
    folders: Folders,
    rules: TrainingConfig,
    trigger: str,
    class_word: str,
) -> Path:
    """Erzeugt (oder findet) die Datensatzversion zur aktuellen geprüften Bildmenge."""
    ok = [p for p in scan(folders.photos, rules) if p.status == "ok"]
    min_images = rules.min_images
    if len(ok) < min_images:
        raise DatasetIncomplete(
            f"{len(ok)} geeignete Bilder in {folders.photos}, mindestens {min_images} nötig."
        )
    base = f"photo of {trigger} {class_word}"
    captions = {p.name: caption_for(folders.photos / p.name, base, trigger) for p in ok}
    # Datensatz-ID aus Bildern, Beschriftungen, Trigger und Klasse (SP3 Schritt 2)
    material = json.dumps(
        [trigger, class_word, sorted((p.sha256, captions[p.name]) for p in ok)], ensure_ascii=False
    )
    set_id = hashlib.sha256(material.encode()).hexdigest()[:12]
    root = folders.datasets
    target = root / f"ds_{set_id}"
    if (target / "dataset.json").is_file():
        return target  # gleiche Bildmenge -> gleiche, unveränderte Version
    tmp = root / f".ds_{set_id}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    items = []
    for i, photo in enumerate(ok, 1):
        with Image.open(folders.photos / photo.name) as raw:
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
                "caption": captions[photo.name],
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
        "captions": "Trigger + Klasse; Beschriftung aus gleichnamiger .txt neben dem Foto",
        "identity_check": "nicht durchgeführt – lokales Gesichtsmodell fehlt noch",
    }
    (tmp / "dataset.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    log.info("Datensatz ds_%s mit %d Bildern erzeugt", set_id, len(items))
    return target
