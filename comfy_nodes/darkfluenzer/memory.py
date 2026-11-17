"""Speicher der Darkfluenzer-Knoten: zwischengespeicherte Modelle (Prüfmodelle außerhalb von ComfyUIs
Modellverwaltung) werden mit ComfyUIs ``unload_all_models`` freigegeben. Das Backend ruft beim
Engine-Wechsel ``/free`` auf (``unload_models``); damit gehen auch diese Modelle aus dem Speicher.
"""

from __future__ import annotations

import gc
import logging

import comfy.model_management as mm
import torch

_caches: list[dict] = []


def register(cache: dict) -> dict:
    """Modell-Zwischenspeicher eines Knotens anmelden; liefert ihn zurück."""
    _caches.append(cache)
    return cache


def release() -> int:
    """Alle angemeldeten Zwischenspeicher leeren; liefert die Zahl freigegebener Modelle."""
    count = sum(len(c) for c in _caches)
    for cache in _caches:
        cache.clear()
    if count:
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        logging.info("Darkfluenzer: %d Prüfmodell(e) freigegeben", count)
    return count


if not getattr(mm.unload_all_models, "_darkfluenzer", False):
    _original = mm.unload_all_models

    def unload_all_models(*args, **kwargs):
        result = _original(*args, **kwargs)
        release()
        return result

    unload_all_models._darkfluenzer = True
    mm.unload_all_models = unload_all_models
