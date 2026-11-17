"""Darkfluenzer-Prüfknoten für ComfyUI 1 (SP3 Schritt 7, E16/E17): eigenes, im Repository gepinntes
Paket; ``launcher/setup_comfyui.sh`` verlinkt es nach ``local/ComfyUI/custom_nodes``. Die Knoten
geben Messwerte aus (``ui.darkfluenzer_checks``); entschieden wird im Backend."""

from .face import FaceIdentity

NODE_CLASS_MAPPINGS = {"DarkfluenzerFaceIdentity": FaceIdentity}
NODE_DISPLAY_NAME_MAPPINGS = {"DarkfluenzerFaceIdentity": "Darkfluenzer · Gesichtsidentität"}
