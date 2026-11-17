"""Inhaltsprüfung als ComfyUI-Knoten (E16, SP5 Schritt 7; Betreiberentscheidung 17.11.: alle
Prüfungen als Knoten, keine Python-Bildprüfung im Backend).

Zwei unabhängige Signale je Bild:
- Stufe des ganzen Bildes: Freepik ``nsfw_image_detector`` (EVA02-base, 448 px) mit den Stufen
  neutral, low, medium, high (Wahrscheinlichkeiten, Summe 1).
- Körperstellen: NudeNet v3.4 ``640m`` (YOLOv8m, 640 px): höchster Wert je Klasse (z. B.
  ``FEMALE_BREAST_EXPOSED``), Vorverarbeitung und Auswertung wie ``nudenet.py`` (v3).

Ergebnis je Bild (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "content", "status": "ok", "rating", "neutral", "low", "medium", "high",
"regions": {Klasse: Wert}}``. Der Knoten misst nur; Schwellen und Inhaltsstufe setzt das Backend.
Modelle nur aus dem Modellordner ``checks`` (Registry mit SHA-256), kein Download.
"""

from __future__ import annotations

import json
from pathlib import Path

import comfy.model_management
import cv2
import folder_paths
import numpy as np
import timm
import torch
from safetensors.torch import load_file

from .memory import register

FOLDER = "checks"  # Modellordner (extra_model_paths.yaml: checks: checks)
DETECTOR_SIZE = 640
NMS_SCORE, NMS_IOU = 0.25, 0.45  # wie nudenet.py
LABELS = (
    "FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED", "ANUS_EXPOSED", "FEET_EXPOSED",
    "BELLY_COVERED", "FEET_COVERED", "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE",
    "BELLY_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
)  # fmt: skip

_detectors: dict[str, object] = register({})
_classifiers: dict[str, tuple] = register({})


def _detector(name: str):
    if name not in _detectors:
        _detectors[name] = cv2.dnn.readNetFromONNX(folder_paths.get_full_path_or_raise(FOLDER, name))
    return _detectors[name]


def _classifier(name: str) -> tuple:
    """EVA02-Klassifikator aus ``model.safetensors`` und der ``config.json`` daneben."""
    if name not in _classifiers:
        path = Path(folder_paths.get_full_path_or_raise(FOLDER, name))
        cfg = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
        model = timm.create_model(cfg["architecture"], pretrained=False, num_classes=cfg["num_classes"])
        state = {k.removeprefix("timm_model."): v for k, v in load_file(str(path)).items()}
        model.load_state_dict(state, strict=True)
        device = comfy.model_management.get_torch_device()
        dtype = torch.bfloat16 if device.type in ("mps", "cuda") else torch.float32
        model = model.to(device, dtype).eval()
        pre = cfg["pretrained_cfg"]
        mean = torch.tensor(pre["mean"]).view(1, 3, 1, 1)
        std = torch.tensor(pre["std"]).view(1, 3, 1, 1)
        _classifiers[name] = (model, tuple(cfg["label_names"]), int(pre["input_size"][1]), mean, std,
                              device, dtype)  # fmt: skip
    return _classifiers[name]


def _regions(net, bgr: np.ndarray, min_score: float) -> dict[str, float]:
    """Höchster Wert je NudeNet-Klasse nach NMS (Vorverarbeitung wie nudenet.py v3)."""
    height, width = bgr.shape[:2]
    side = max(height, width)
    padded = cv2.copyMakeBorder(bgr, 0, side - height, 0, side - width, cv2.BORDER_CONSTANT)
    net.setInput(cv2.dnn.blobFromImage(padded, 1 / 255.0, (DETECTOR_SIZE, DETECTOR_SIZE), (0, 0, 0),
                                       swapRB=True, crop=False))  # fmt: skip
    rows = np.transpose(np.squeeze(net.forward()))
    scores = rows[:, 4:]
    best = scores.max(axis=1)
    keep = best >= min(min_score, NMS_SCORE)
    boxes, values, classes = [], [], []
    scale = side / DETECTOR_SIZE
    for row, score, cls in zip(rows[keep], best[keep], scores[keep].argmax(axis=1), strict=True):
        x, y, w, h = row[:4]
        boxes.append([float((x - w / 2) * scale), float((y - h / 2) * scale), float(w * scale),
                      float(h * scale)])  # fmt: skip
        values.append(float(score))
        classes.append(int(cls))
    found: dict[str, float] = {}
    for i in np.array(cv2.dnn.NMSBoxes(boxes, values, NMS_SCORE, NMS_IOU)).flatten() if boxes else []:
        if values[i] >= min_score:
            label = LABELS[classes[i]]
            found[label] = max(found.get(label, 0.0), round(values[i], 4))
    return found


def _bgr(frame) -> np.ndarray:
    rgb = np.clip(frame.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


class ContentRating:
    """Inhaltsstufe und Körperstellen je Bild (nur Messwerte)."""

    CATEGORY = "Darkfluenzer/Prüfung"
    FUNCTION = "measure"
    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("werte",)

    @classmethod
    def INPUT_TYPES(cls):
        files = folder_paths.get_filename_list(FOLDER)
        return {
            "required": {
                "image": ("IMAGE",),
                "detector": (files,),
                "classifier": (files,),
                "min_region_score": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    def measure(self, image, detector, classifier, min_region_score):
        net = _detector(detector)
        model, labels, size, mean, std, device, dtype = _classifier(classifier)
        values = []
        for frame in image:
            rgb = frame.permute(2, 0, 1)[None].float().cpu()
            x = torch.nn.functional.interpolate(rgb, size=(size, size), mode="bicubic", antialias=True,
                                                align_corners=False).clamp(0, 1)  # fmt: skip
            x = ((x - mean) / std).to(device, dtype)
            with torch.inference_mode():
                probs = model(x).float().softmax(-1)[0].cpu().tolist()
            entry = {"check": "content", "status": "ok", "rating": labels[int(np.argmax(probs))]}
            entry |= {label: round(p, 4) for label, p in zip(labels, probs, strict=True)}
            entry["regions"] = _regions(net, _bgr(frame), min_region_score)
            values.append(entry)
        text = json.dumps(values, ensure_ascii=False)
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
