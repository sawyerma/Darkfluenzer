"""Technische Bildqualität als ComfyUI-Knoten (E17 Teil 1, SP5 Schritt 7): Messwerte ohne
Modellgewichte, auf eine feste Kantenlänge verkleinert, damit Werte über Auflösungen vergleichbar
sind. Ein gelerntes Qualitätsmodell folgt als eigener Knoten.

Ergebnis je Bild (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "quality", "status": "ok", "sharpness", "noise", "clipped_dark", "clipped_bright",
"contrast"}``
- ``sharpness``: Varianz des Laplace-Bildes der Helligkeit (größer = schärfer)
- ``noise``: Rauschstärke nach Immerkær (1996), Grauwerte 0…255
- ``clipped_dark``/``clipped_bright``: Anteil der Pixel ≤ 2 bzw. ≥ 253
- ``contrast``: Standardabweichung der Helligkeit
Der Knoten misst nur; Schwellen setzt das Backend.
"""

from __future__ import annotations

import json
import math

import cv2
import numpy as np

SIDE = 1024  # längste Kante für die Messung
_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)


def _gray(frame) -> np.ndarray:
    rgb = np.clip(frame.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    scale = SIDE / max(height, width)
    if scale < 1:
        gray = cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    return gray


def measure_gray(gray: np.ndarray) -> dict:
    """Messwerte eines 8-Bit-Graubildes (auch ohne ComfyUI aufrufbar)."""
    height, width = gray.shape
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    conv = cv2.filter2D(gray.astype(np.float64), -1, _IMMERKAER)[1:-1, 1:-1]
    noise = math.sqrt(math.pi / 2) * np.abs(conv).sum() / (6 * (width - 2) * (height - 2))
    return {
        "sharpness": round(float(lap.var()), 2),
        "noise": round(float(noise), 3),
        "clipped_dark": round(float((gray <= 2).mean()), 4),
        "clipped_bright": round(float((gray >= 253).mean()), 4),
        "contrast": round(float(gray.std()), 2),
    }


class ImageQuality:
    """Schärfe, Rauschen, Beschnitt und Kontrast je Bild (nur Messwerte)."""

    CATEGORY = "Darkfluenzer/Prüfung"
    FUNCTION = "measure"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("werte",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    def measure(self, image):
        values = [{"check": "quality", "status": "ok", **measure_gray(_gray(frame))} for frame in image]
        text = json.dumps(values, ensure_ascii=False)
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
