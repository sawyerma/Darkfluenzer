"""Darkfluenzer-Knoten für ComfyUI 1: eigenes, im Repository gepinntes Paket;
``launcher/setup_comfyui.sh`` verlinkt es nach ``local/ComfyUI/custom_nodes``.

- Prüfknoten (SP3 Schritt 7, E16/E17) geben Messwerte aus (``ui.darkfluenzer_checks``);
  entschieden wird im Backend.
- Training mit Wiederaufnahme-Checkpoints (SP3 Schritt 3) auf Basis von ``TrainLoraNode``.
"""

from .face import FaceIdentity
from .train import TrainLoraResumable

NODE_CLASS_MAPPINGS = {
    "DarkfluenzerFaceIdentity": FaceIdentity,
    "DarkfluenzerTrainLora": TrainLoraResumable,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DarkfluenzerFaceIdentity": "Darkfluenzer · Gesichtsidentität",
    "DarkfluenzerTrainLora": "Darkfluenzer · LoRA trainieren (Checkpoints)",
}
