"""Handprüfung als ComfyUI-Knoten (E17, SP5 Schritt 7).

1. Hände finden: MediaPipe-Handflächen-Detektor (OpenCV-Zoo, 192 × 192, 2016 Anker; Vor- und
   Nachbearbeitung wie ``mp_palmdet.py``, die Anker werden berechnet statt als Tabelle geführt).
2. Je Hand ein Ausschnitt (Handfläche ×2,6, zu den Fingern verschoben, wie MediaPipe) und die
   Wahrscheinlichkeit „zählbar“ des CountHallu-Qualitätsklassifikators (MaxViT-small, 224 px,
   ImageNet-Normierung; Index 1). Zählbar heißt laut Modellkarte: alle Finger sichtbar und ohne
   sichtbares Versagen. Eine Hand, die eine Tasse hält, ist deshalb oft „nicht zählbar“ – der Wert
   ist kein Anatomie-Urteil (echte Probe 17.11.: natürliche Hände an Tasse und Buch 0,09/0,12).

Die Fingerzahl (CountHallu-Detektor, Ultralytics YOLO-v13) folgt erst nach Durchsicht von dessen Code;
bis dahin gibt es kein Urteil über Fingerzahl oder Fehlbildungen.

Ergebnis je Bild (``ui.darkfluenzer_checks`` und Ausgang ``werte``, JSON):
``{"check": "hands", "status": "ok" | "keine_haende", "hands", "countable_min", "countable_mean",
"palm_min"}``. Nur Messwerte; Schwellen setzt das Backend.
"""

from __future__ import annotations

import json

import comfy.model_management
import cv2
import folder_paths
import numpy as np
import timm
import torch

from .memory import register

FOLDER = "checks"
PALM_SIZE = 192
GATE_SIZE = 224
CROP_SCALE = 2.6  # Ausschnitt um die Handfläche (MediaPipe)
CROP_SHIFT = 0.25  # Verschiebung zu den Fingern (Anteil der Ausschnittseite)
NMS_IOU = 0.3
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
_models = register({})


def palm_anchors() -> np.ndarray:
    """SSD-Anker des MediaPipe-Handflächen-Detektors: 24×24×2 (Schritt 8) + 12×12×6 (Schritt 16)."""
    out = []
    for grid, per in ((24, 2), (12, 6)):
        for y in range(grid):
            for x in range(grid):
                out += [((x + 0.5) / grid, (y + 0.5) / grid)] * per
    return np.array(out, np.float32)


def _load(palm: str, gate: str) -> tuple:
    key = (palm, gate)
    if key not in _models:
        net = cv2.dnn.readNetFromONNX(folder_paths.get_full_path_or_raise(FOLDER, palm))
        model = timm.create_model("maxvit_small_tf_224", pretrained=False, num_classes=2)
        state = torch.load(folder_paths.get_full_path_or_raise(FOLDER, gate), map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        device = comfy.model_management.get_torch_device()
        _models[key] = (net, model.to(device).eval(), device, palm_anchors())
    return _models[key]


def detect_palms(net, anchors: np.ndarray, bgr: np.ndarray, min_score: float) -> list[tuple]:
    """Handflächen als (Box x1, y1, x2, y2, Landmarken 7×2, Wert) in Bildkoordinaten."""
    height, width = bgr.shape[:2]
    ratio = min(PALM_SIZE / height, PALM_SIZE / width)
    new_h, new_w = int(height * ratio), int(width * ratio)
    image = cv2.resize(bgr, (new_w, new_h))
    left, top = (PALM_SIZE - new_w) // 2, (PALM_SIZE - new_h) // 2
    image = cv2.copyMakeBorder(image, top, PALM_SIZE - new_h - top, left, PALM_SIZE - new_w - left,
                               cv2.BORDER_CONSTANT, None, (0, 0, 0))  # fmt: skip
    blob = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32)[np.newaxis] / 255.0
    net.setInput(blob)
    regress, scores = net.forward(net.getUnconnectedOutLayersNames())
    score = 1 / (1 + np.exp(-scores[0, :, 0].astype(np.float64)))
    pad = np.array([left, top]) / ratio
    scale = max(width, height)
    delta = regress[0, :, :4]
    cxy, wh = delta[:, :2] / PALM_SIZE, delta[:, 2:] / PALM_SIZE
    boxes = np.concatenate([(cxy - wh / 2 + anchors) * scale, (cxy + wh / 2 + anchors) * scale], 1)
    boxes -= np.tile(pad, 2)
    xywh = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes.tolist()]
    keep = cv2.dnn.NMSBoxes(xywh, score.tolist(), min_score, NMS_IOU)
    found = []
    for i in np.array(keep).flatten() if len(keep) else []:
        marks = (regress[0, i, 4:].reshape(7, 2) / PALM_SIZE + anchors[i]) * scale - pad
        found.append((boxes[i], marks, float(score[i])))
    return found


def hand_crop(bgr: np.ndarray, box: np.ndarray, marks: np.ndarray) -> np.ndarray:
    """Quadratischer Ausschnitt um die Hand: Handfläche ×2,6, zu den Fingern verschoben
    (Richtung Handgelenk → Mittelfingeransatz, Landmarken 0 und 2)."""
    side = CROP_SCALE * max(box[2] - box[0], box[3] - box[1])
    direction = marks[2] - marks[0]
    norm = float(np.linalg.norm(direction)) or 1.0
    center = (box[:2] + box[2:]) / 2 + CROP_SHIFT * side * direction / norm
    x1, y1 = (center - side / 2).astype(int)
    x2, y2 = (center + side / 2).astype(int)
    height, width = bgr.shape[:2]
    pad = max(0, -x1, -y1, x2 - width, y2 - height)
    padded = cv2.copyMakeBorder(bgr, pad, pad, pad, pad, cv2.BORDER_CONSTANT, None, (0, 0, 0))
    return padded[y1 + pad : y2 + pad, x1 + pad : x2 + pad]


def _countable(model, device, crop_bgr: np.ndarray) -> float:
    rgb = cv2.cvtColor(cv2.resize(crop_bgr, (GATE_SIZE, GATE_SIZE), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    x = (torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0 - torch.tensor(MEAN).view(3, 1, 1)) / torch.tensor(
        STD
    ).view(3, 1, 1)
    with torch.inference_mode():
        return float(model(x[None].to(device)).softmax(-1)[0, 1].cpu())


class HandCheck:
    """Hände je Bild und ob sie zählbar sind (nur Messwerte)."""

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
                "palm": (files,),
                "gate": (files,),
                "min_palm_score": ("FLOAT", {"default": 0.6, "min": 0.05, "max": 1.0, "step": 0.05}),
            }
        }

    def measure(self, image, palm, gate, min_palm_score):
        net, model, device, anchors = _load(palm, gate)
        values = []
        for frame in image:
            rgb = np.clip(frame.cpu().numpy() * 255.0 + 0.5, 0, 255).astype(np.uint8)
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            palms = detect_palms(net, anchors, bgr, min_palm_score)
            if not palms:
                values.append({"check": "hands", "status": "keine_haende", "hands": 0})
                continue
            countable = [_countable(model, device, hand_crop(bgr, box, marks)) for box, marks, _ in palms]
            values.append({
                "check": "hands", "status": "ok", "hands": len(palms),
                "countable_min": round(min(countable), 4), "countable_mean": round(float(np.mean(countable)), 4),
                "palm_min": round(min(p[2] for p in palms), 4),
            })  # fmt: skip
        text = json.dumps(values, ensure_ascii=False)
        return {"ui": {"darkfluenzer_checks": [text]}, "result": (text,)}
