"""Stichprobe der Videoframes als ComfyUI-Knoten (SP5 Schritt 7: Frameprüfung bei Video). Die
Prüfknoten bekommen nicht jedes Bild eines Videos, sondern jedes ``every``-te und das letzte,
höchstens ``max_frames`` gleichmäßig verteilt. Ohne Modell.

Ergebnis (``ui.darkfluenzer_checks``): ``{"check": "frames", "status": "ok", "total", "count",
"indices"}``
(welche Frames geprüft wurden, in der Reihenfolge der Messwerte der Prüfknoten); Ausgang
``frames`` (IMAGE) für die Prüfknoten.
"""

from __future__ import annotations

import json


def frame_indices(total: int, every: int, max_frames: int) -> list[int]:
    """Indizes der geprüften Frames: jedes ``every``-te ab 0 und das letzte; mehr als
    ``max_frames`` werden gleichmäßig ausgedünnt (erstes und letztes bleiben). Auch ohne ComfyUI."""
    if total <= 0:
        return []
    every, max_frames = max(1, int(every)), max(1, int(max_frames))
    picked = list(range(0, total, every))
    if picked[-1] != total - 1:
        picked.append(total - 1)
    if len(picked) > max_frames:
        if max_frames == 1:
            return [picked[0]]
        step = (len(picked) - 1) / (max_frames - 1)
        picked = sorted({picked[round(i * step)] for i in range(max_frames)})
    return picked


class FrameSample:
    """Jedes n-te Frame und das letzte für die Prüfknoten (nur Auswahl, keine Bewertung)."""

    CATEGORY = "Darkfluenzer/Prüfung"
    FUNCTION = "sample"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frames",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "every": ("INT", {"default": 8, "min": 1, "max": 1000}),
                "max_frames": ("INT", {"default": 12, "min": 1, "max": 1000}),
            }
        }

    def sample(self, image, every, max_frames):
        indices = frame_indices(int(image.shape[0]), every, max_frames)
        total = int(image.shape[0])
        entry = {"check": "frames", "status": "ok", "total": total, "count": len(indices)}
        text = json.dumps([entry | {"indices": indices}])
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (image[indices],)}
