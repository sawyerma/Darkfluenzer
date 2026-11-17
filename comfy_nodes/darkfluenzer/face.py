"""Gesichtsidentität als ComfyUI-Knoten (SP3 Schritt 7; Betreiberentscheidung 17.11.: alle Prüfungen
als Knoten, keine Python-Bildprüfung im Backend).

YuNet findet das Gesicht samt fünf Landmarken, SFace richtet es auf das ArcFace-Raster (112 × 112)
aus. Zwei unabhängige Merkmalsvektoren: SFace und AuraFace (ArcFace ResNet100, glintr100).
Ähnlichkeit = Kosinus zum Schwerpunkt der Referenzgesichter (Ordner ``reference/`` der Figur, den
das Backend setzt). Der Knoten misst nur; Schwellen und Entscheidung liegen im Backend.

Ergebnis je Bild (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "identity", "status": "ok" | "kein_gesicht" | "keine_referenz", "sface", "auraface",
"face_px", "score", "references"}``. Zu kleine oder unsichere Gesichter sind „kein_gesicht“
(nicht prüfbar), nie ein Treffer oder Fehlschlag.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import folder_paths
import numpy as np

from .memory import register

FOLDER = "face"  # Modellordner (extra_model_paths.yaml: face: face)
ARCFACE_SIZE = 112
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)

_models: dict[tuple, tuple] = register({})  # (Dateien, Schwelle) -> (Detektor, Erkenner, ArcFace)
_centers: dict[str, tuple] = {}  # Signatur des Referenzsatzes -> (Schwerpunkte, Anzahl)


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def _load(detector: str, recognizer: str, arcface: str, min_score: float) -> tuple:
    key = (detector, recognizer, arcface, min_score)
    if key not in _models:
        paths = [folder_paths.get_full_path_or_raise(FOLDER, n) for n in (detector, recognizer, arcface)]
        _models[key] = (
            cv2.FaceDetectorYN.create(paths[0], "", (320, 320), min_score),
            cv2.FaceRecognizerSF.create(paths[1], ""),
            cv2.dnn.readNetFromONNX(paths[2]),
        )
    return _models[key]


def _face(models: tuple, bgr: np.ndarray, min_face_px: int) -> dict | None:
    """Größtes sicher erkanntes Gesicht mit beiden Merkmalsvektoren; None = nicht prüfbar."""
    det, rec, arc = models
    height, width = bgr.shape[:2]
    det.setInputSize((width, height))
    _, found = det.detect(bgr)
    if found is None or len(found) == 0:
        return None
    best = max(found, key=lambda f: f[2] * f[3])
    if min(best[2], best[3]) < min_face_px:
        return None
    aligned = rec.alignCrop(bgr, best)
    sface = rec.feature(aligned).flatten()
    blob = cv2.dnn.blobFromImage(
        aligned, 1 / 127.5, (ARCFACE_SIZE, ARCFACE_SIZE), (127.5, 127.5, 127.5), swapRB=True
    )
    arc.setInput(blob)
    return {
        "sface": _unit(sface),
        "auraface": _unit(arc.forward().flatten()),
        "face_px": int(min(best[2], best[3])),
        "score": float(best[-1]),
    }


def _reference_files(folder: str) -> list[Path]:
    path = Path(folder)
    if not folder or not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.suffix.lower() in SUFFIXES and p.is_file())


def _signature(files: list[Path], key: tuple) -> str:
    digest = hashlib.sha256(repr(key).encode())
    for p in files:
        st = p.stat()
        digest.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return digest.hexdigest()


def _centers_for(models: tuple, folder: str, min_face_px: int, key: tuple) -> tuple:
    """Schwerpunkte der Referenzgesichter, je Referenzsatz zwischengespeichert."""
    files = _reference_files(folder)
    sig = _signature(files, (*key, min_face_px))
    if sig not in _centers:
        faces = []
        for p in files:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            face = _face(models, img, min_face_px) if img is not None else None
            if face is not None:
                faces.append(face)
        if faces:
            center = (
                _unit(np.mean([f["sface"] for f in faces], axis=0)),
                _unit(np.mean([f["auraface"] for f in faces], axis=0)),
            )
        else:
            center = None
        _centers[sig] = (center, len(faces))
    return _centers[sig]


def _bgr(image) -> np.ndarray:
    """ComfyUI-Bild (H × W × 3, float 0…1, RGB) als 8-Bit-BGR."""
    rgb = np.clip(image.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


class FaceIdentity:
    """Misst die Gesichtsidentität jedes Bildes gegen den Referenzsatz einer Figur."""

    CATEGORY = "Darkfluenzer/Prüfung"
    FUNCTION = "measure"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("werte",)

    @classmethod
    def INPUT_TYPES(cls):
        files = folder_paths.get_filename_list(FOLDER)
        return {
            "required": {
                "image": ("IMAGE",),
                "reference_dir": ("STRING", {"default": ""}),
                "detector": (files,),
                "recognizer": (files,),
                "arcface": (files,),
                "min_face_px": ("INT", {"default": 64, "min": 8, "max": 4096}),
                "min_score": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, reference_dir, detector, recognizer, arcface, min_face_px, min_score, **_):
        # geänderter Referenzsatz misst neu (das Bild selbst prüft ComfyUI über seinen Eingang)
        return _signature(
            _reference_files(reference_dir), (detector, recognizer, arcface, min_face_px, min_score)
        )

    def measure(self, image, reference_dir, detector, recognizer, arcface, min_face_px, min_score):
        key = (detector, recognizer, arcface, min_score)
        models = _load(*key)
        center, count = _centers_for(models, reference_dir, min_face_px, key)
        values = []
        for frame in image:
            face = _face(models, _bgr(frame), min_face_px)
            entry = {"check": "identity", "references": count}
            if center is None:
                entry["status"] = "keine_referenz"
            elif face is None:
                entry["status"] = "kein_gesicht"
            else:
                entry |= {
                    "status": "ok",
                    "sface": float(np.dot(center[0], face["sface"])),
                    "auraface": float(np.dot(center[1], face["auraface"])),
                }
            if face is not None:
                entry |= {"face_px": face["face_px"], "score": face["score"]}
            values.append(entry)
        text = json.dumps(values, ensure_ascii=False)
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
