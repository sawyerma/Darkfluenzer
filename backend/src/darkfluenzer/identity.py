"""Gesichtsidentität (PHASENPLAN_V0 §9.2): misst, ob ein Bild dieselbe Person zeigt wie die
Referenzen eines Charakters.

YuNet findet das Gesicht samt fünf Landmarken, SFace richtet es auf das ArcFace-Raster (112 × 112)
aus. Zwei unabhängige Merkmalsvektoren: SFace und AuraFace (ArcFace ResNet100, glintr100).
Ähnlichkeit = Kosinus zum Schwerpunkt der Referenzvektoren. Zu kleine oder unsichere Gesichter
gelten als „nicht prüfbar“ statt als Treffer oder Fehlschlag. Modelldateien kommen ausschließlich
aus der Registry (workflows/manifest.toml), Schwellen aus local/config.toml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import Config
from .models import Manifest, models_dir

# Registry-Schlüssel der Modelldateien
DETECTOR, RECOGNIZER, ARCFACE = "face_yunet", "face_sface", "face_auraface"
ARCFACE_SIZE = 112  # Eingang von AuraFace (ArcFace-Raster, gleiche Ausrichtung wie SFace)
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # nur echte Fehler ins Log


class IdentityError(Exception):
    """Bild nicht lesbar oder Modelldatei fehlt."""


@dataclass(frozen=True)
class Face:
    """Größtes sicher erkanntes Gesicht eines Bildes."""

    box: tuple[int, int, int, int]  # x, y, Breite, Höhe in Pixeln
    score: float
    sface: np.ndarray  # normierter Merkmalsvektor
    auraface: np.ndarray


@dataclass(frozen=True)
class Match:
    sface: float
    auraface: float

    @property
    def mean(self) -> float:
        return (self.sface + self.auraface) / 2


class FaceIdentity:
    """Geladene Modelle; je Prozess einmal anlegen und für viele Bilder verwenden."""

    def __init__(self, cfg: Config, man: Manifest) -> None:
        base = models_dir(cfg.root)
        paths = {}
        for key in (DETECTOR, RECOGNIZER, ARCFACE):
            if key not in man.files:
                raise IdentityError(f"Registry: Datei '{key}' ist nicht eingetragen.")
            path = base / man.files[key].target
            if not path.is_file():
                raise IdentityError(f"Modelldatei fehlt: {path}")
            paths[key] = str(path)
        self.min_face_px = cfg.identity.min_face_px
        self.detector = cv2.FaceDetectorYN.create(
            paths[DETECTOR], "", (320, 320), cfg.identity.min_score
        )
        self.recognizer = cv2.FaceRecognizerSF.create(paths[RECOGNIZER], "")
        self.arcface = cv2.dnn.readNetFromONNX(paths[ARCFACE])

    def face(self, image: Path) -> Face | None:
        """Größtes Gesicht mit Merkmalen; None = kein (ausreichend großes) Gesicht erkannt."""
        img = cv2.imread(str(image), cv2.IMREAD_COLOR)
        if img is None:
            raise IdentityError(f"Bild nicht lesbar: {image}")
        height, width = img.shape[:2]
        self.detector.setInputSize((width, height))
        _, found = self.detector.detect(img)
        if found is None or len(found) == 0:
            return None
        best = max(found, key=lambda f: f[2] * f[3])  # größte Fläche
        if min(best[2], best[3]) < self.min_face_px:
            return None
        aligned = self.recognizer.alignCrop(img, best)
        sface = self.recognizer.feature(aligned).flatten()
        blob = cv2.dnn.blobFromImage(
            aligned, 1 / 127.5, (ARCFACE_SIZE, ARCFACE_SIZE), (127.5, 127.5, 127.5), swapRB=True
        )
        self.arcface.setInput(blob)
        auraface = self.arcface.forward().flatten()
        x, y, w, h = (int(v) for v in best[:4])
        return Face((x, y, w, h), float(best[-1]), _unit(sface), _unit(auraface))

    def compare(self, references: list[Path], image: Path) -> Match | None:
        """Ähnlichkeit von ``image`` zum Schwerpunkt der Referenzgesichter; None = nicht prüfbar
        (kein Gesicht im Bild oder in keiner Referenz)."""
        refs = [f for f in (self.face(p) for p in references) if f is not None]
        target = self.face(image)
        if not refs or target is None:
            return None
        center_s = _unit(np.mean([f.sface for f in refs], axis=0))
        center_a = _unit(np.mean([f.auraface for f in refs], axis=0))
        return Match(
            sface=float(np.dot(center_s, target.sface)),
            auraface=float(np.dot(center_a, target.auraface)),
        )


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector
