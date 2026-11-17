"""Darkfluenzer-Knoten für ComfyUI 1: eigenes, im Repository gepinntes Paket;
``launcher/setup_comfyui.sh`` verlinkt es nach ``local/ComfyUI/custom_nodes``.

- Prüfknoten (Gesicht SP3 Schritt 7, Inhalt E16, weitere E17) geben Messwerte aus
  (``ui.darkfluenzer_checks``);
  entschieden wird im Backend.
- Training mit Wiederaufnahme-Checkpoints (SP3 Schritt 3) auf Basis von ``TrainLoraNode``.
"""

from .content import ContentRating
from .face import FaceIdentity
from .train import TrainLoraResumable

NODE_CLASS_MAPPINGS = {
    "DarkfluenzerContentRating": ContentRating,
    "DarkfluenzerFaceIdentity": FaceIdentity,
    "DarkfluenzerTrainLora": TrainLoraResumable,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DarkfluenzerContentRating": "Darkfluenzer · Inhaltsprüfung",
    "DarkfluenzerFaceIdentity": "Darkfluenzer · Gesichtsidentität",
    "DarkfluenzerTrainLora": "Darkfluenzer · LoRA trainieren (Checkpoints)",
}
