"""Zeitliche Konsistenz eines Videos als ComfyUI-Knoten (SP5 Schritt 7) ohne Modell: Unterschied
aufeinanderfolgender Frames in der Helligkeit, auf ``SIDE`` verkleinert, damit Werte über
Auflösungen vergleichbar sind. Bekommt alle Frames (keine Stichprobe).

Ergebnis je Video (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "temporal", "status": "ok" | "zu_kurz", "frames", "mean_diff", "max_diff",
"max_step", "jumps", "frozen", "luma_flicker"}``
- ``mean_diff``/``max_diff``: mittlere absolute Differenz benachbarter Frames (Grauwerte 0…255);
  ``max_step``: Schritt mit dem größten Unterschied (zwischen Frame i und i+1)
- ``jumps``: Schritte über ``jump_factor`` × Median aller Schritte (Schnitt, Zerfall, Flackern)
- ``frozen``: Schritte unter ``FROZEN`` (Standbild)
- ``luma_flicker``: Standardabweichung der Änderung der mittleren Helligkeit je Schritt
Der Knoten misst nur; Schwellen setzt das Backend.
"""

from __future__ import annotations

import json

import cv2
import numpy as np

SIDE = 256  # längste Kante für die Messung
FROZEN = 0.1  # mittlere Differenz, unter der ein Schritt als Standbild zählt


def _gray(frame) -> np.ndarray:
    rgb = np.clip(frame.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    scale = SIDE / max(height, width)
    if scale < 1:
        gray = cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    return gray


def measure_frames(grays: list[np.ndarray], jump_factor: float) -> dict:
    """Messwerte einer Folge von 8-Bit-Graubildern gleicher Größe (auch ohne ComfyUI)."""
    if len(grays) < 2:
        return {"check": "temporal", "status": "zu_kurz", "frames": len(grays)}
    stack = np.stack([g.astype(np.float32) for g in grays])
    diffs = np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2))
    median = float(np.median(diffs))
    luma = stack.mean(axis=(1, 2))
    return {
        "check": "temporal",
        "status": "ok",
        "frames": len(grays),
        "mean_diff": round(float(diffs.mean()), 3),
        "max_diff": round(float(diffs.max()), 3),
        "max_step": int(diffs.argmax()),
        "jumps": int((diffs > jump_factor * max(median, FROZEN)).sum()),
        "frozen": int((diffs < FROZEN).sum()),
        "luma_flicker": round(float(np.diff(luma).std()), 3),
    }


class TemporalConsistency:
    """Sprünge, Standbilder und Helligkeitsflackern über alle Frames (nur Messwerte)."""

    CATEGORY = "Darkfluenzer/Prüfung"
    FUNCTION = "measure"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("werte",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "jump_factor": ("FLOAT", {"default": 4.0, "min": 1.0, "max": 100.0, "step": 0.5}),
            }
        }

    def measure(self, image, jump_factor):
        text = json.dumps([measure_frames([_gray(f) for f in image], float(jump_factor))])
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
