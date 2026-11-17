"""Darkfluenzer-Knoten für ComfyUI 1: eigenes, im Repository gepinntes Paket;
``launcher/setup_comfyui.sh`` verlinkt es nach ``local/ComfyUI/custom_nodes``.

- Prüfknoten (Gesicht SP3 Schritt 7, Inhalt E16, weitere E17) geben Messwerte aus
  (``ui.darkfluenzer_checks``);
  entschieden wird im Backend.
- Training mit Wiederaufnahme-Checkpoints (SP3 Schritt 3) auf Basis von ``TrainLoraNode``.
"""

from .content import ContentRating
from .face import FaceIdentity
from .frames import FrameSample
from .hands import HandCheck
from .promptfidelity import PromptFidelity
from .quality import ImageQuality
from .qualityscore import QualityScore
from .temporal import TemporalConsistency
from .train import TrainLoraResumable

NODE_CLASS_MAPPINGS = {
    "DarkfluenzerContentRating": ContentRating,
    "DarkfluenzerFaceIdentity": FaceIdentity,
    "DarkfluenzerFrameSample": FrameSample,
    "DarkfluenzerHandCheck": HandCheck,
    "DarkfluenzerImageQuality": ImageQuality,
    "DarkfluenzerPromptFidelity": PromptFidelity,
    "DarkfluenzerQualityScore": QualityScore,
    "DarkfluenzerTemporal": TemporalConsistency,
    "DarkfluenzerTrainLora": TrainLoraResumable,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DarkfluenzerContentRating": "Darkfluenzer · Inhaltsprüfung",
    "DarkfluenzerFaceIdentity": "Darkfluenzer · Gesichtsidentität",
    "DarkfluenzerFrameSample": "Darkfluenzer · Videoframes (Stichprobe)",
    "DarkfluenzerHandCheck": "Darkfluenzer · Handprüfung",
    "DarkfluenzerImageQuality": "Darkfluenzer · Bildqualität (technisch)",
    "DarkfluenzerPromptFidelity": "Darkfluenzer · Prompttreue (VQAScore)",
    "DarkfluenzerQualityScore": "Darkfluenzer · Bildqualität (Q-ReAlign)",
    "DarkfluenzerTemporal": "Darkfluenzer · Zeitliche Konsistenz (Video)",
    "DarkfluenzerTrainLora": "Darkfluenzer · LoRA trainieren (Checkpoints)",
}
