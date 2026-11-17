"""Rechenknoten-Schnittstelle (SP0 Schritt 3).

Alles, was auf Prozesse und Ordner einer ComfyUI-Instanz zugreift, läuft über ``Node``: starten,
stoppen, Zustand, Speicher messen, Trainingsdatensatz ablegen, LoRA abholen, Ausgabeordner,
Editor-Kopien. ``LocalNode`` (``nodes/local.py``) ist die heutige Logik auf diesem Mac;
``nodes/remote.py`` ist die Stelle für einen zweiten Rechner und bleibt bis dahin leer.

Eingaben hochladen, Ausgaben abholen, Verlauf und Warteschlange laufen über HTTP
(``ComfyClient(node.url)``) und sind damit schon knotenunabhängig. Der Modellstatus prüft heute den
gemeinsamen Modellordner dieses Macs (``media.models``); ein entfernter Knoten meldet ihn später
selbst.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import ComfyConfig, Config


class Node(ABC):
    """Eine ComfyUI-Instanz als Rechenknoten."""

    def __init__(self, cfg: Config, inst: ComfyConfig) -> None:
        self.cfg = cfg
        self.inst = inst

    @property
    def name(self) -> str:
        return self.inst.name

    @property
    def url(self) -> str:
        return self.inst.url

    @abstractmethod
    def start(self) -> dict:
        """Startet die Instanz (idempotent) und liefert ihren Zustand."""

    @abstractmethod
    def stop(self) -> dict:
        """Stoppt nur die eigene Instanz."""

    @abstractmethod
    def status(self) -> dict:
        """Zustand: läuft, gestoppt, fremd belegt, Gesundheit."""

    @abstractmethod
    def memory(self, timeout: float) -> dict:
        """Speicher des Knotens: ``ram_total``, ``ram_free`` (Bytes), ``swap`` (MB).
        Wirft ``ComfyError``, wenn die Instanz nicht antwortet."""

    @abstractmethod
    def swap_mb(self) -> float:
        """Belegter Swap des Knotens in MB (auch ohne laufende Instanz)."""

    @abstractmethod
    def stage_dataset(self, dataset_dir: Path) -> str:
        """Legt eine Datensatzversion im Eingang der Instanz ab; Ordner relativ zum Eingang."""

    @abstractmethod
    def take_lora(self, prefix: str) -> Path:
        """Holt die zuletzt gespeicherte LoRA mit diesem Präfix aus der Ausgabe der Instanz."""

    @abstractmethod
    def output_dir(self) -> Path:
        """Ausgabeordner der Instanz (Zwischenstände der Videoabschnitte für die Galerie)."""

    @abstractmethod
    def editor_file(self, key: str) -> Path:
        """Editor-Kopie eines Workflows im Benutzerordner der Instanz."""

    @abstractmethod
    def install_editor_copy(self, ui_file: Path, key: str, *, replace: bool = False) -> Path:
        """Legt die Editor-Kopie aus dem registrierten UI-Export an (vorhandene bleibt, außer
        ``replace``)."""

    @abstractmethod
    def remove_editor_copy(self, key: str) -> None:
        """Entfernt die Editor-Kopie."""


def node_for(cfg: Config, inst: ComfyConfig) -> Node:
    """Der Rechenknoten einer konfigurierten Instanz; heute immer dieser Mac."""
    from .local import LocalNode

    return LocalNode(cfg, inst)
