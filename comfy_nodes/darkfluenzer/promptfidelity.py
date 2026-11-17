"""Prompttreue als ComfyUI-Knoten (E17, SP5 Schritt 7): VQAScore auf Qwen3-VL-8B-Instruct (BF16).
Das Modell bekommt das Bild und die Frage „Does this figure show "<Prompt>"? Please answer yes or
no.“; der Wert ist die Wahrscheinlichkeit, dass die Antwort mit „yes“ beginnt (wie VQAScore,
t2v_metrics; summiert über die Schreibweisen Yes/yes/YES, Qwen antwortet meist klein). Lange
Prompts werden in Teile getrennt; ausgegeben werden Mittel und Minimum.

Ergebnis je Bild (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "prompt_fidelity", "status": "ok" | "kein_prompt", "score", "min", "parts"}``.
Nur Messwerte; Schwellen setzt das Backend. Modell nur aus dem Modellordner ``checks``, ohne
Download; freigegeben mit ComfyUIs ``unload_all_models`` (``memory.py``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import comfy.model_management
import folder_paths
import numpy as np
import torch
from PIL import Image

from .memory import register

FOLDER = "checks"
QUESTION = 'Does this figure show "{}"? Please answer yes or no.'
YES_FORMS = ("Yes", "yes", "YES", " Yes", " yes")  # erstes Antwort-Token, alle Schreibweisen
MAX_PART_CHARS = 200  # längere Prompts in Teile an Satz- und Kommagrenzen
_models = register({})


def parts_of(prompt: str) -> list[str]:
    """Prompt in Teile bis ``MAX_PART_CHARS`` an Satz- bzw. Kommagrenzen (auch ohne ComfyUI)."""
    prompt = " ".join(prompt.split())
    if len(prompt) <= MAX_PART_CHARS:
        return [prompt] if prompt else []
    pieces = [p.strip() for p in re.split(r"(?<=[.;,])\s+", prompt) if p.strip()]
    out, current = [], ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > MAX_PART_CHARS:
            out.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    return [p[:MAX_PART_CHARS] for p in out]


def _load(config_name: str) -> tuple:
    if config_name not in _models:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        folder = str(Path(folder_paths.get_full_path_or_raise(FOLDER, config_name)).parent)
        processor = AutoProcessor.from_pretrained(folder, local_files_only=True)
        device = comfy.model_management.get_torch_device()
        model = AutoModelForImageTextToText.from_pretrained(
            folder, dtype=torch.bfloat16, local_files_only=True
        ).to(device).eval()
        tok = processor.tokenizer
        yes = sorted({tok(form, add_special_tokens=False).input_ids[0] for form in YES_FORMS})
        _models[config_name] = (processor, model, yes, device)
    return _models[config_name]


def _p_yes(processor, model, yes: list[int], device, image: Image.Image, text: str) -> float:
    messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": QUESTION.format(text)}]}]
    chat = processor.apply_chat_template(messages, add_generation_prompt=True)
    inputs = processor(text=[chat], images=[image], return_tensors="pt").to(device)
    with torch.inference_mode():
        logits = model(**inputs).logits[0, -1].float()
    return float(logits.softmax(-1)[yes].sum().cpu())


class PromptFidelity:
    """Wie gut zeigt das Bild den Prompt (VQAScore 0…1, nur Messwerte)."""

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
                "prompt": ("STRING", {"default": "", "multiline": True}),
            }
        }

    def measure(self, image, model, prompt):
        parts = parts_of(prompt)
        values = []
        loaded = _load(model) if parts else None
        for frame in image:
            if not parts:
                values.append({"check": "prompt_fidelity", "status": "kein_prompt"})
                continue
            rgb = np.clip(frame.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
            picture = Image.fromarray(rgb)
            scores = [_p_yes(*loaded, picture, part) for part in parts]
            values.append({
                "check": "prompt_fidelity", "status": "ok", "score": round(float(np.mean(scores)), 4),
                "min": round(min(scores), 4), "parts": len(parts),
            })  # fmt: skip
        text = json.dumps(values, ensure_ascii=False)
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
