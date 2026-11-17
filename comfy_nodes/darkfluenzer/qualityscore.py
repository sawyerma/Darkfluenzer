"""Gelernte Bildqualität als ComfyUI-Knoten (E17, SP5 Schritt 7): Q-ReAlign-Pro-9B (Qwen3.5-VL,
BF16). Wie in der Modellkarte: das Modell wird nach Qualität bzw. Ästhetik gefragt; die
Wahrscheinlichkeiten der Wörter excellent, good, fair, poor, bad ergeben mit den Gewichten
1, 0,75, 0,5, 0,25, 0 einen Wert von 0 (schlecht) bis 1 (sehr gut).

Ergebnis je Bild (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "quality_score", "status": "ok", "quality", "aesthetics"}``. Nur Messwerte; Schwellen
setzt das Backend. Modell nur aus dem Modellordner ``checks`` (Registry mit SHA-256), ohne
Download; freigegeben mit ComfyUIs ``unload_all_models`` (``memory.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import comfy.model_management
import folder_paths
import numpy as np
import torch
from PIL import Image

from .memory import register

FOLDER = "checks"
LEVELS = ("excellent", "good", "fair", "poor", "bad")
WEIGHTS = (1.0, 0.75, 0.5, 0.25, 0.0)
QUESTIONS = {
    "quality": ("How would you rate the quality of this image?", "The quality of the image is"),
    "aesthetics": ("How would you rate the aesthetics of this image?", "The aesthetics of the image is"),
}

_models = register({})


def _load(config_name: str) -> tuple:
    """Prozessor und Modell aus dem Ordner der ``config.json`` (nur lokale Dateien)."""
    if config_name not in _models:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        folder = str(Path(folder_paths.get_full_path_or_raise(FOLDER, config_name)).parent)
        processor = AutoProcessor.from_pretrained(folder, local_files_only=True)
        device = comfy.model_management.get_torch_device()
        model = AutoModelForImageTextToText.from_pretrained(
            folder, dtype=torch.bfloat16, local_files_only=True
        ).to(device).eval()
        ids = [processor.tokenizer(" " + w, add_special_tokens=False).input_ids[0] for w in LEVELS]
        _models[config_name] = (processor, model, ids, device)
    return _models[config_name]


def _score(processor, model, ids, device, image: Image.Image, question: str, stem: str) -> float:
    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": question}]}]
    text = processor.apply_chat_template(messages, add_generation_prompt=True) + stem
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(device)
    with torch.inference_mode():
        probs = model(**inputs).logits[0, -1, ids].float().softmax(-1).cpu()
    return round(float((probs * torch.tensor(WEIGHTS)).sum()), 4)


class QualityScore:
    """Qualität und Ästhetik je Bild (0…1, nur Messwerte)."""

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
                "model": (folder_paths.get_filename_list(FOLDER),),
                "aesthetics": ("BOOLEAN", {"default": True}),
            }
        }

    def measure(self, image, model, aesthetics):
        processor, net, ids, device = _load(model)
        values = []
        for frame in image:
            rgb = np.clip(frame.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
            picture = Image.fromarray(rgb)
            entry = {"check": "quality_score", "status": "ok"}
            for name, (question, stem) in QUESTIONS.items():
                if name == "aesthetics" and not aesthetics:
                    continue
                entry[name] = _score(processor, net, ids, device, picture, question, stem)
            values.append(entry)
        text = json.dumps(values, ensure_ascii=False)
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
