"""Modell-Registry aus ``workflows/manifest.toml``: Ablage, Status, Download, Verifikation.

Jede Datei steht genau einmal im Manifest (Revision + SHA-256) und liegt unter
``local/models/<target>``. Engines referenzieren Dateien per Schlüssel, damit gemeinsam genutzte
Encoder/VAEs nie doppelt geladen werden.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomlkit

log = logging.getLogger("darkfluenzer.models")

MANIFEST_RELATIVE = Path("workflows") / "manifest.toml"
# Lokale, nicht versionierte Registry-Einträge (BUG-092): trainierte LoRAs und Schalter „aktiviert“
LOCAL_REGISTRY = Path("local") / "registry.toml"
# Eingänge des Prüfknotens Gesichtsidentität, die das Backend setzt (SP3 Schritt 7)
IDENTITY_INPUTS = ("reference_dir", "min_face_px", "min_score")
GATES = ("load", "render", "quality", "license_pass")
GATE_VALUES = {"OFFEN", "PASS", "FAIL", "GESPERRT"}
USAGES = {"evaluation", "production"}
KINDS = {"image", "video", "text"}
# Sprachworkflows (SP4 Schritt 1, E19, E26): jeder Profilblock und jeder Kontexteingang ist ein
# eigener Textknoten, der in einen Sprachknoten fließt; Reihenfolge = core.persona.PROFILE_BLOCKS
PROFILE_INPUTS = (
    "system_prompt", "persona", "positive_rules", "negative_rules", "strategy", "examples",
    "classification", "wish_summary", "offer", "delivery", "consolation", "fansly",
)  # fmt: skip
CONTEXT_INPUTS = ("context", "memory", "facts", "message")
SESSION_NODE = "LLMSessionChatNode"
TEXT_NODE = "PrimitiveStringMultiline"
PREVIEW_NODE = "PreviewAny"
# setzt nodes/llm.isolate_sessions je Lauf (SPEC-018)
SESSION_RUNTIME = ("history_dir", "session_id", "reset_session", "persistent_cache", "max_turns")
INSTANCES = ("media", "ai")
STAGING = ".staging"
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(Exception):
    """Manifest ist ungültig – die Registry darf dann nicht benutzt werden."""


class ModelError(Exception):
    """Download/Verifikation fehlgeschlagen."""


@dataclass(frozen=True)
class ModelFile:
    key: str
    repo: str
    revision: str
    source: str
    target: str
    size: int
    sha256: str
    # dieselbe Datei wie ein anderer Eintrag (z. B. gleiche Konfiguration in zwei Modellordnern):
    # ausdrücklich erlaubt, beim Laden wird sie aus dessen Ziel kopiert statt neu geladen
    duplicate_of: str = ""

    @property
    def comfy_name(self) -> str:
        """Name, unter dem ComfyUI die Datei im Loader anbietet (ohne Typ-Ordner)."""
        return self.target.split("/", 1)[1]


@dataclass(frozen=True)
class Engine:
    key: str
    title: str
    kind: str
    role: str
    arch: str
    precision: str
    wave: int
    files: tuple[str, ...]
    license: str
    usage: str
    gates: dict[str, str]
    note: str
    # ausführende ComfyUI-Instanz (PHASENPLAN_V0 §4.2): media (Foto/Video) oder ai (KI-Workflows)
    instance: str
    # Ausgabeprofile (V0 §9.7): Name -> (Breite, Höhe), in denen diese Engine erzeugt
    formats: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def modelfree(self) -> bool:
        """Reine Bildverarbeitung ohne Modell (arch "none"): kein Laden, kein Entladen."""
        return not self.files


PARAM_TYPES = {"str": str, "int": int, "float": float}


@dataclass(frozen=True)
class Param:
    node: str
    input: str
    type: str
    required: bool = False
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    multiple_of: int | None = None
    upload: bool = False  # Datei wird vor dem Lauf zu ComfyUI hochgeladen
    label: str = ""  # Feldname im Cockpit (leer: Standardbezeichnung des Parameternamens)
    expert: bool | None = None  # None: Zahlen sind Experte, Texte und Dateien Grundeinstellung
    reference: bool = False  # Vorlage (Bild aus Dateien/Kloner-Eingang), nur mit upload
    # weitere Ziele (Node, Eingang) mit demselben Wert, z. B. Schritte beider Wan-Sampler
    also: tuple[tuple[str, str], ...] = ()
    below: str = ""  # Wert muss kleiner sein als der dieses Parameters (Wechsel < Schritte)
    tier_exempt: bool = False  # Maske: zählt nicht für die Inhaltsstufe (SP2 Schritt 2), nur Upload

    @property
    def is_expert(self) -> bool:
        return self.expert if self.expert is not None else self.type != "str" and not self.upload

    def coerce(self, name: str, value: object) -> object:
        typ = PARAM_TYPES[self.type]
        if isinstance(value, bool) or not isinstance(
            value, typ if typ is not float else (int, float)
        ):
            raise ValueError(
                f"Parameter {name}: {self.type} erwartet, nicht {type(value).__name__}"
            )
        if self.min is not None and value < self.min:
            raise ValueError(f"Parameter {name}={value} < Minimum {self.min}")
        if self.max is not None and value > self.max:
            raise ValueError(f"Parameter {name}={value} > Maximum {self.max}")
        if self.choices and value not in self.choices:
            raise ValueError(f"Parameter {name}={value!r} nicht in {list(self.choices)}")
        if self.multiple_of and value % self.multiple_of:
            raise ValueError(f"Parameter {name}={value} ist kein Vielfaches von {self.multiple_of}")
        if self.type == "str" and not value.strip():
            raise ValueError(f"Parameter {name} darf nicht leer sein")
        return float(value) if self.type == "float" else value


@dataclass(frozen=True)
class VideoSpec:
    """Videolänge in Sekunden, für alle Video-Workflows gleich bedient (SP1 Schritt 10).

    ``frames`` (Wan, Remix; V0 §10 Langvideo): Darkfluenzer teilt die Gesamtlänge in Abschnitte
    höchstens ``segment_frames_max`` Frames (Trainingslänge des Modells), jeder Folgeabschnitt
    startet mit dem letzten Bild des vorigen; danach werden die Abschnitte zusammengesetzt.
    ``seconds`` (LTX): die Gesamtlänge geht direkt auf den Sekunden-Eingang, ein Lauf bis zur
    Engine-Grenze ``seconds_max``."""

    length_node: str  # frames: Framezahl eines Abschnitts; seconds: Länge in Sekunden
    length_input: str
    fps: str  # Parameter mit der Bildrate
    start_image: str  # Upload-Parameter des Startbilds
    mode: str = "frames"  # frames | seconds
    frames_multiple: int = 0  # frames: Framezahl = n · frames_multiple + 1 (Wan: 4)
    segment_frames_max: int = 0
    decode: str = ""  # frames: Node, dessen Bilder das Video ergeben (letztes Bild je Abschnitt)
    seconds_max: float = 0.0  # seconds: Engine-Grenze eines Laufs


@dataclass(frozen=True)
class LoraSlot:
    """Lader der Charakter-LoRA im Graphen (SP3 Schritt 5). Name, Stärke und Trigger setzt das
    Backend aus der LoRA des Auftrags; ohne LoRA entfernt es den Lader und reicht seine Eingänge
    durch (``through``: Eingang des Laders je Ausgang, z. B. ``model``, ``clip``)."""

    node: str
    through: tuple[str, ...]
    name: str = "lora_name"
    strength: str = "character_strength"  # Parameter der Stärke; Startwert aus der LoRA
    prompt: str = "prompt"  # Parameter, dem der Trigger vorangestellt wird


@dataclass(frozen=True)
class KeyframeSlot:
    """Weitere Schlüsselbilder eines Video-Workflows (Zeitachse B4): je Schlüsselbild kopiert das
    Backend die Bildvorbereitung ``chain`` (erster Knoten liest das Bild) und den Guide-Knoten
    ``before`` und setzt sie in die Kette zwischen ``after`` und ``before``
    (Ausgänge 0, 1, 2 = positive, negative, latent; z. B. ``LTXVAddGuide``)."""

    after: str
    before: str
    chain: tuple[str, ...]
    image_input: str = "image"  # Bildeingang des Guide-Knotens
    frame_input: str = "frame_idx"
    strength_input: str = "strength"


@dataclass(frozen=True)
class TextSpec:
    """Sprachworkflow (SP4 Schritt 1): fester Ehrlichkeitsblock (Regel 12 c) und Ausgabeknoten
    (PreviewAny) für Antwort, Einstufung (E26), Systemprompt und Nutzertext."""

    honesty_node: str
    honesty: str  # wortgleich im Graphen; nicht im Cockpit bearbeitbar
    answer: str
    classification: str
    system: str
    user: str


@dataclass(frozen=True)
class Workflow:
    key: str
    title: str
    engine: str
    ui: str
    api: str
    status: str
    # Betreiberentscheidung; ersetzt keine Modell-, Lizenz- oder Test-Gates.
    enabled: bool
    params: dict[str, Param]
    # SaveImage-Node, der die im Graphen erzeugte Maske speichert (leer: keine). Alle übrigen
    # Ausgaben müssen außerhalb dieser Maske dem Quellbild ``image`` gleichen (Pixelprüfung).
    mask_output: str = ""
    # Trainingsworkflow: Node, der den Datensatz lädt (folder), und SaveLoRA-Node (prefix);
    # beide setzt das Backend, nicht der Betreiber.
    train_dataset: str = ""
    train_lora: str = ""
    # Trainingsknoten mit Wiederaufnahme-Checkpoints (SP3 Schritt 3): checkpoint_dir setzt das
    # Backend je Figur, Datensatz und Einstellungen
    train_checkpoint: str = ""
    # Inhaltsstufe der Ergebnisse (PHASENPLAN_V0 Regel 13): fail-closed – ohne Eintrag „explizit“;
    # „standard“ nur, wenn ausdrücklich so im Manifest markiert
    content: str = "explizit"
    video: VideoSpec | None = None
    lora: LoraSlot | None = None  # Lader der Charakter-LoRA (SP3 Schritt 5)
    # Prüfknoten Gesichtsidentität (SP3 Schritt 7): Referenzordner der Figur, Mindestgröße und
    # -sicherheit setzt das Backend; der Knoten liefert Messwerte (ui.darkfluenzer_checks)
    identity: str = ""
    keyframes: KeyframeSlot | None = None  # weitere Schlüsselbilder (Zeitachse B4)
    text: TextSpec | None = None  # Sprachworkflow auf ComfyUI 2 (Engine-Art text)

    @property
    def training(self) -> bool:
        return bool(self.train_dataset)

    @property
    def runtime_inputs(self) -> set[tuple[str, str]]:
        """Eingänge, die erst zur Laufzeit gesetzt werden (Uploads, Datensatz, LoRA-Name)."""
        found = {(p.node, p.input) for p in self.params.values() if p.upload}
        if self.training:
            found.add((self.train_dataset, "folder"))
        if self.train_checkpoint:
            found.add((self.train_checkpoint, "checkpoint_dir"))
        if self.lora:
            found.add((self.lora.node, self.lora.name))
        if self.identity:
            found.add((self.identity, "reference_dir"))
        return found

    def session_nodes(self, graph: dict) -> list[str]:
        """Sprachknoten des Graphen (je Lauf an einen isolierten Sitzungsordner gebunden)."""
        return [nid for nid, n in graph.items() if n.get("class_type") == SESSION_NODE]


CONTENT_TIERS = ("standard", "explizit")


def higher_tier(*tiers: str | None) -> str:
    """Höhere Inhaltsstufe; unbekannt (None) zählt als „explizit“ (fail-closed)."""
    return "explizit" if any(t != "standard" for t in tiers) else "standard"


@dataclass(frozen=True)
class Lora:
    """Selbst trainierte Charakter-LoRA (B1): Datei, Architekturbindung und Herkunft."""

    key: str
    target: str  # unter local/models/, z. B. loras/characters/<key>.safetensors
    size: int
    sha256: str
    base_engine: str
    base_file: str  # Dateischlüssel des Basismodells (dessen SHA-256 steht in [files.*])
    dataset: str
    trigger: str
    steps: int
    rank: int
    learning_rate: float
    strength: float
    status: str
    created_at: str
    trainer: str
    character: str = ""  # Kürzel der Figur (SP3 Schritt 4); nie für eine andere Figur laden
    # weitere Engines derselben Architektur, erst nach bestandenem Probelauf mit Identitätswert
    # (SPEC-012); die Trainings-Engine gilt immer
    compatible: tuple[str, ...] = ()

    @property
    def comfy_name(self) -> str:
        return self.target.split("/", 1)[1]


@dataclass(frozen=True)
class CheckSpec:
    """Prüfknoten der Prüfkette (E16/E17, SP5 Schritt 7): das Backend setzt ihn beim Einreichen
    zwischen Dekodieren und jeden SaveImage-Knoten eines Bild-Workflows (Eingang ``image``); er
    liefert Messwerte (``ui.darkfluenzer_checks``), das gespeicherte Bild bleibt unverändert."""

    name: str
    node: str  # Knotenklasse in ComfyUI (comfy_nodes/darkfluenzer)
    engine: str  # Engine mit den Modelldateien (Bereitschaft)
    inputs: dict  # feste Eingänge (Modelldateien, Grenzen)
    character: bool = False  # nur mit Figur (Referenzsatz, z. B. Gesichtsidentität)
    prompt: bool = False  # bekommt den Prompt des Auftrags (Prompttreue)
    image: bool = True  # in Bild-Workflows vor jedem SaveImage
    video: str = ""  # Video-Workflows: "frames" = Stichprobe, "all" = alle Frames, "" = nicht


@dataclass(frozen=True)
class FrameSampling:
    """Stichprobe der Videoframes für Prüfknoten mit ``video = "frames"`` (SP5 Schritt 7)."""

    node: str  # Knotenklasse (comfy_nodes/darkfluenzer/frames.py)
    every: int
    max_frames: int


@dataclass(frozen=True)
class Manifest:
    root: Path
    reserve_gb: float
    roles: dict[str, str]
    files: dict[str, ModelFile]
    engines: dict[str, Engine]
    workflows: dict[str, Workflow]
    loras: dict[str, Lora]
    checks: dict[str, CheckSpec] = field(default_factory=dict)
    check_frames: FrameSampling | None = None

    def engine_files(self, engine: str) -> list[ModelFile]:
        return [self.files[k] for k in self.engines[engine].files]


def _str(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        raise ManifestError(f"Manifest: {where}.{key} fehlt oder ist kein Text.")
    return value


def _video(t: object, params: dict[str, Param], w: str) -> VideoSpec | None:
    if t is None:
        return None
    if not isinstance(t, dict):
        raise ManifestError(f"Manifest: {w}.video muss eine Tabelle sein.")
    mode = str(t.get("mode", "frames"))
    try:
        if mode == "frames":
            spec = VideoSpec(
                length_node=str(t["length_node"]),
                length_input=str(t["length_input"]),
                fps=str(t["fps"]),
                start_image=str(t["start_image"]),
                frames_multiple=int(t["frames_multiple"]),
                segment_frames_max=int(t["segment_frames_max"]),
                decode=str(t["decode"]),
            )
        elif mode == "seconds":
            spec = VideoSpec(
                length_node=str(t["length_node"]),
                length_input=str(t["length_input"]),
                fps=str(t["fps"]),
                start_image=str(t["start_image"]),
                mode="seconds",
                seconds_max=float(t["seconds_max"]),
            )
        else:
            raise ManifestError(f"Manifest: {w}.video.mode '{mode}' (frames | seconds).")
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"Manifest: {w}.video: {exc}") from exc
    if spec.fps not in params or spec.start_image not in params:
        raise ManifestError(f"Manifest: {w}.video: fps und start_image müssen Parameter sein.")
    if not params[spec.start_image].upload:
        raise ManifestError(f"Manifest: {w}.video: start_image muss ein Upload sein.")
    if mode == "frames" and (
        spec.frames_multiple < 1 or (spec.segment_frames_max - 1) % spec.frames_multiple
    ):
        raise ManifestError(f"Manifest: {w}.video.segment_frames_max passt nicht zum Raster.")
    if mode == "seconds" and spec.seconds_max <= 0:
        raise ManifestError(f"Manifest: {w}.video.seconds_max muss größer 0 sein.")
    return spec


def format_problems(wf: Workflow, formats: dict[str, tuple[int, int]]) -> list[str]:
    """Benannte Formate der Engine müssen für jeden Workflow mit Breite und Höhe gültige Werte sein
    (Grenzen und Raster, BUG-093)."""
    if not {"width", "height"} <= set(wf.params):
        return []
    problems = []
    for name, size in formats.items():
        for param, value in zip(("width", "height"), size, strict=True):
            p = wf.params[param]
            if (p.min is not None and value < p.min) or (p.max is not None and value > p.max):
                problems.append(f"formats.{name}: {param} {value} außerhalb {p.min}…{p.max}.")
            elif p.multiple_of and value % p.multiple_of:
                problems.append(
                    f"formats.{name}: {param} {value} kein Vielfaches von {p.multiple_of}."
                )
    return problems


def _merge_local(root: Path, data: dict) -> None:
    """Lokale Registry (``local/registry.toml``) einlesen: LoRAs und Schalter „aktiviert“ stehen nur
    dort, nie im versionierten Manifest (BUG-092)."""
    for key, wt in (data.get("workflows") or {}).items():
        if "enabled" in wt:
            raise ManifestError(f"Manifest: workflows.{key}.enabled gehört nach {LOCAL_REGISTRY}.")
    if data.get("loras"):
        raise ManifestError(f"Manifest: [loras] gehört nach {LOCAL_REGISTRY}.")
    path = root / LOCAL_REGISTRY
    try:
        local = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{path} ist kein gültiges TOML: {exc}") from exc
    data["loras"] = dict(local.get("loras") or {})
    for key, t in (local.get("workflows") or {}).items():
        if key in (data.get("workflows") or {}) and "enabled" in t:
            data["workflows"][key]["enabled"] = t["enabled"]  # Typ prüft der Lader


def edit_local(root: Path, change: Callable[[tomlkit.TOMLDocument], None]) -> Manifest:
    """Ändert die lokale Registry; gespeichert wird nur, wenn die Registry danach gültig lädt."""
    path = root / LOCAL_REGISTRY
    with _EDIT_LOCK:
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        doc = tomlkit.parse(before)
        change(doc)
        text = tomlkit.dumps(doc).rstrip("\n") + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, text)
        try:
            return load_manifest(root)
        except ManifestError:
            if before:
                _atomic_write(path, before)
            else:
                path.unlink(missing_ok=True)
            raise


def _keyframe_slot(t: object, w: str) -> KeyframeSlot | None:
    if t is None:
        return None
    if not isinstance(t, dict):
        raise ManifestError(f"Manifest: {w}.keyframes muss eine Tabelle sein.")
    try:
        slot = KeyframeSlot(**{**t, "chain": tuple(str(x) for x in t.get("chain", ()))})
    except TypeError as exc:
        raise ManifestError(f"Manifest: {w}.keyframes: {exc}") from exc
    if not slot.chain:
        raise ManifestError(f"Manifest: {w}.keyframes.chain fehlt.")
    return slot


def _text_spec(t: object, params: dict[str, Param], w: str) -> TextSpec | None:
    if t is None:
        return None
    if not isinstance(t, dict):
        raise ManifestError(f"Manifest: {w}.text muss eine Tabelle sein.")
    try:
        spec = TextSpec(**{k: str(v) for k, v in t.items()})
    except TypeError as exc:
        raise ManifestError(f"Manifest: {w}.text: {exc}") from exc
    empty = [k for k, v in vars(spec).items() if not v.strip()]
    if empty:
        raise ManifestError(f"Manifest: {w}.text.{empty[0]} fehlt.")
    missing = [n for n in (*PROFILE_INPUTS, *CONTEXT_INPUTS) if n not in params]
    if missing:
        raise ManifestError(f"Manifest: {w}: Profil- bzw. Kontexteingang {missing[0]} fehlt.")
    wrong = [n for n in (*PROFILE_INPUTS, *CONTEXT_INPUTS) if params[n].type != "str"]
    if wrong:
        raise ManifestError(f"Manifest: {w}.params.{wrong[0]} muss Text sein.")
    return spec


def _lora_slot(t: object, params: dict[str, Param], w: str) -> LoraSlot | None:
    if t is None:
        return None
    if not isinstance(t, dict):
        raise ManifestError(f"Manifest: {w}.lora muss eine Tabelle sein.")
    try:
        slot = LoraSlot(**{**t, "through": tuple(str(x) for x in t.get("through", ()))})
    except TypeError as exc:
        raise ManifestError(f"Manifest: {w}.lora: {exc}") from exc
    if not slot.through:
        raise ManifestError(f"Manifest: {w}.lora.through fehlt.")
    strength = params.get(slot.strength)
    if strength is None or strength.node != slot.node or strength.type != "float":
        raise ManifestError(f"Manifest: {w}.lora.strength: float-Parameter am Lader fehlt.")
    if slot.prompt not in params or params[slot.prompt].type != "str":
        raise ManifestError(f"Manifest: {w}.lora.prompt: Text-Parameter fehlt.")
    return slot


def load_manifest(root: Path, *, require_ui: bool = True, text: str | None = None) -> Manifest:
    """Lädt und validiert die Registry. ``require_ui=False`` nur für das Erzeugen der UI-Exporte;
    ``text`` prüft einen geänderten Manifest-Inhalt, bevor er gespeichert wird."""
    path = root / MANIFEST_RELATIVE
    try:
        data = tomllib.loads(text if text is not None else path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"Manifest fehlt: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"Manifest {path} ist kein gültiges TOML: {exc}") from exc
    if data.get("schema") != 1:
        raise ManifestError("Manifest: schema = 1 erwartet.")
    _merge_local(root, data)

    files: dict[str, ModelFile] = {}
    targets: dict[str, str] = {}
    for key, t in (data.get("files") or {}).items():
        w = f"files.{key}"
        mf = ModelFile(
            key=key,
            repo=_str(t, "repo", w),
            revision=_str(t, "revision", w),
            source=_str(t, "source", w),
            target=_str(t, "target", w),
            size=t.get("size") if isinstance(t.get("size"), int) else -1,
            sha256=_str(t, "sha256", w),
            duplicate_of=str(t.get("duplicate_of", "")),
        )
        if mf.size <= 0:
            raise ManifestError(f"Manifest: {w}.size muss eine positive Ganzzahl sein.")
        if not _SHA.match(mf.sha256):
            raise ManifestError(f"Manifest: {w}.sha256 ist kein SHA-256.")
        tp = Path(mf.target)
        if tp.is_absolute() or ".." in tp.parts or len(tp.parts) < 3:
            raise ManifestError(f"Manifest: {w}.target muss '<typ>/<familie>/<datei>' sein.")
        if mf.target in targets:
            raise ManifestError(
                f"Manifest: Ziel {mf.target} doppelt ({targets[mf.target]}, {key})."
            )
        targets[mf.target] = key
        files[key] = mf
    shas: dict[str, str] = {}
    for mf in files.values():
        if mf.duplicate_of:
            twin = files.get(mf.duplicate_of)
            if twin is None or twin.sha256 != mf.sha256 or twin.size != mf.size:
                raise ManifestError(
                    f"Manifest: {mf.key}.duplicate_of passt nicht zu {mf.duplicate_of}."
                )
            continue
        if mf.sha256 in shas:
            raise ManifestError(f"Manifest: {mf.key} und {shas[mf.sha256]} sind dieselbe Datei.")
        shas[mf.sha256] = mf.key

    engines: dict[str, Engine] = {}
    for key, t in (data.get("engines") or {}).items():
        w = f"engines.{key}"
        gates = t.get("gates") or {}
        if set(gates) != set(GATES) or not set(gates.values()) <= GATE_VALUES:
            raise ManifestError(f"Manifest: {w}.gates braucht {GATES} mit Werten {GATE_VALUES}.")
        refs = t.get("files") or []
        missing = [r for r in refs if r not in files]
        if missing or (not refs and t.get("arch") != "none"):
            raise ManifestError(f"Manifest: {w}.files leer oder unbekannt: {missing}")
        formats = {}
        for name, size in (t.get("formats") or {}).items():
            if not (isinstance(size, list) and len(size) == 2 and all(int(v) > 0 for v in size)):
                raise ManifestError(f"Manifest: {w}.formats.{name} braucht [Breite, Höhe].")
            formats[name] = (int(size[0]), int(size[1]))
        eng = Engine(
            key=key,
            title=_str(t, "title", w),
            kind=_str(t, "kind", w),
            role=_str(t, "role", w),
            arch=_str(t, "arch", w),
            precision=_str(t, "precision", w),
            wave=int(t.get("wave", 0)),
            files=tuple(refs),
            license=_str(t, "license", w),
            usage=_str(t, "usage", w),
            gates=dict(gates),
            note=str(t.get("note", "")),
            instance=str(t.get("instance", "media")),
            formats=formats,
        )
        if eng.instance not in INSTANCES:
            raise ManifestError(f"Manifest: {w}.instance muss {INSTANCES} sein.")
        if eng.kind not in KINDS:
            raise ManifestError(f"Manifest: {w}.kind muss {KINDS} sein.")
        if eng.usage not in USAGES:
            raise ManifestError(f"Manifest: {w}.usage muss {USAGES} sein.")
        if eng.usage == "production" and any(v != "PASS" for v in gates.values()):
            raise ManifestError(f"Manifest: {w} ist 'production' ohne vier PASS-Gates.")
        engines[key] = eng

    roles = {k: v for k, v in (data.get("roles") or {}).items() if isinstance(v, str)}
    for role, eng_key in roles.items():
        if eng_key and (eng_key not in engines or engines[eng_key].usage != "production"):
            raise ManifestError(
                f"Manifest: Rolle {role} -> {eng_key} ist keine freigegebene Produktions-Engine."
            )

    loras: dict[str, Lora] = {}
    for key, t in (data.get("loras") or {}).items():
        w = f"loras.{key}"
        try:
            lora = Lora(
                key=key,
                target=_str(t, "target", w),
                size=int(t["size"]),
                sha256=_str(t, "sha256", w),
                base_engine=_str(t, "base_engine", w),
                base_file=_str(t, "base_file", w),
                dataset=_str(t, "dataset", w),
                trigger=_str(t, "trigger", w),
                steps=int(t["steps"]),
                rank=int(t["rank"]),
                learning_rate=float(t["learning_rate"]),
                strength=float(t.get("strength", 1.0)),
                status=_str(t, "status", w),
                created_at=_str(t, "created_at", w),
                trainer=_str(t, "trainer", w),
                character=str(t.get("character", "")),
                compatible=tuple(str(e) for e in t.get("compatible", ())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"Manifest: {w}: {exc}") from exc
        if not _SHA.match(lora.sha256) or not lora.target.startswith("loras/"):
            raise ManifestError(f"Manifest: {w}: sha256 oder target (loras/…) ungültig.")
        if lora.base_engine not in engines or lora.base_file not in engines[lora.base_engine].files:
            raise ManifestError(
                f"Manifest: {w}: Basis {lora.base_engine}/{lora.base_file} unbekannt."
            )
        if lora.status not in GATE_VALUES:
            raise ManifestError(f"Manifest: {w}.status muss {GATE_VALUES} sein.")
        if unknown := [e for e in lora.compatible if e not in engines]:
            raise ManifestError(f"Manifest: {w}.compatible: Engine {', '.join(unknown)} unbekannt.")
        loras[key] = lora

    workflows: dict[str, Workflow] = {}
    for key, t in (data.get("workflows") or {}).items():
        w = f"workflows.{key}"
        params = {}
        for name, spec in (t.get("params") or {}).items():
            spec = dict(spec)
            if "choices_from" in spec:  # gemeinsame Auswahlliste ([choices], z. B. Sampler)
                shared = (data.get("choices") or {}).get(spec.pop("choices_from"))
                if not isinstance(shared, list):
                    raise ManifestError(f"Manifest: {w}.params.{name}.choices_from unbekannt.")
                spec["choices"] = shared
            try:
                also = tuple(
                    tuple(str(x).rsplit(":", 1)) for x in spec.pop("also", ())
                )  # Untergraph-IDs: "398:341"
                if any(len(a) != 2 for a in also):
                    raise TypeError('also: Einträge als "Node:Eingang"')
                params[name] = Param(
                    **{**spec, "choices": tuple(spec.get("choices", ())), "also": also}
                )
            except TypeError as exc:
                raise ManifestError(f"Manifest: {w}.params.{name}: {exc}") from exc
            if params[name].reference and not params[name].upload:
                raise ManifestError(f"Manifest: {w}.params.{name}: reference nur mit upload.")
            if params[name].tier_exempt and not params[name].upload:
                raise ManifestError(f"Manifest: {w}.params.{name}: tier_exempt nur mit upload.")
            if params[name].type not in PARAM_TYPES:
                raise ManifestError(
                    f"Manifest: {w}.params.{name}.type muss {set(PARAM_TYPES)} sein."
                )
            if any(type(c) is not PARAM_TYPES[params[name].type] for c in params[name].choices):
                raise ManifestError(f"Manifest: {w}.params.{name}.choices passen nicht zum Typ.")
        enabled = t.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ManifestError(f"Manifest: {w}.enabled muss true oder false sein.")
        wf = Workflow(
            key=key,
            title=t.get("title") if isinstance(t.get("title"), str) else key,
            engine=_str(t, "engine", w),
            ui=_str(t, "ui", w),
            api=_str(t, "api", w),
            status=_str(t, "status", w),
            enabled=enabled,
            params=params,
            mask_output=str(t.get("mask_output", "")),
            train_dataset=str((t.get("training") or {}).get("dataset", "")),
            train_lora=str((t.get("training") or {}).get("lora", "")),
            train_checkpoint=str((t.get("training") or {}).get("checkpoint", "")),
            content=str(t.get("content", "explizit")),
            video=_video(t.get("video"), params, w),
            lora=_lora_slot(t.get("lora"), params, w),
            identity=str((t.get("identity") or {}).get("node", "")),
            keyframes=_keyframe_slot(t.get("keyframes"), w),
            text=_text_spec(t.get("text"), params, w),
        )
        for name, prm in params.items():
            if prm.below and prm.below not in params:
                raise ManifestError(f"Manifest: {w}.params.{name}.below: {prm.below} unbekannt.")
        if wf.content not in CONTENT_TIERS:
            raise ManifestError(f"Manifest: {w}.content muss {CONTENT_TIERS} sein.")
        if bool(wf.train_dataset) != bool(wf.train_lora):
            raise ManifestError(f"Manifest: {w}.training braucht dataset und lora.")
        if wf.training and not {"steps", "rank", "learning_rate"} <= set(params):
            raise ManifestError(f"Manifest: {w}: Training braucht steps, rank, learning_rate.")
        if wf.mask_output and "image" not in params:
            raise ManifestError(f"Manifest: {w}.mask_output braucht den Parameter 'image'.")
        if wf.engine not in engines:
            raise ManifestError(f"Manifest: {w}.engine '{wf.engine}' unbekannt.")
        if (engines[wf.engine].kind == "text") != (wf.text is not None):
            raise ManifestError(f"Manifest: {w}.text genau dann, wenn die Engine-Art text ist.")
        if wf.status not in GATE_VALUES:
            raise ManifestError(f"Manifest: {w}.status muss {GATE_VALUES} sein.")
        for rel in (wf.ui, wf.api) if require_ui else (wf.api,):
            if not (root / "workflows" / rel).is_file():
                raise ManifestError(f"Manifest: {w} verweist auf fehlende Datei workflows/{rel}.")
        graph = json.loads((root / "workflows" / wf.api).read_text(encoding="utf-8"))
        problems = graph_problems(wf, graph, engine_model_names(files, engines, loras, wf.engine))
        problems += format_problems(wf, engines[wf.engine].formats)
        if problems:
            raise ManifestError(f"Manifest: {w}: {problems[0]}")
        workflows[key] = wf

    checks: dict[str, CheckSpec] = {}
    for name, t in (data.get("checks") or {}).items():
        w = f"checks.{name}"
        spec = CheckSpec(
            name=name,
            node=_str(t, "node", w),
            engine=_str(t, "engine", w),
            inputs=dict(t.get("inputs") or {}),
            character=bool(t.get("character", False)),
            prompt=bool(t.get("prompt", False)),
            image=bool(t.get("image", True)),
            video=str(t.get("video", "")),
        )
        if spec.engine not in engines:
            raise ManifestError(f"Manifest: {w}.engine '{spec.engine}' unbekannt.")
        if spec.video not in ("", "frames", "all"):
            raise ManifestError(f"Manifest: {w}.video muss frames, all oder leer sein.")
        checks[name] = spec
    sampling = None
    if (t := data.get("check_frames")) is not None:
        w = "[check_frames]"
        sampling = FrameSampling(
            node=_str(t, "node", w), every=int(t.get("every", 8)),
            max_frames=int(t.get("max_frames", 12)),
        )  # fmt: skip
        if sampling.every < 1 or sampling.max_frames < 1:
            raise ManifestError(f"Manifest: {w} every und max_frames ≥ 1.")
    elif any(c.video == "frames" for c in checks.values()):
        raise ManifestError("Manifest: Prüfungen mit video = frames brauchen [check_frames].")

    return Manifest(
        root=root,
        reserve_gb=float(data.get("reserve_gb", 30)),
        roles=roles,
        files=files,
        engines=engines,
        workflows=workflows,
        loras=loras,
        checks=checks,
        check_frames=sampling,
    )


def engine_model_names(
    files: dict[str, ModelFile], engines: dict[str, Engine], loras: dict[str, Lora], engine: str
) -> set[str]:
    """Modelldateien, die ein Workflow dieser Engine laden darf: ihre Dateien und die auf ihr
    trainierten LoRAs."""
    names = {files[f].comfy_name for f in engines[engine].files}
    return names | {
        lo.comfy_name
        for lo in loras.values()
        if lo.base_engine == engine or engine in lo.compatible
    }


def graph_problems(wf: Workflow, graph: dict, model_names: set[str]) -> list[str]:
    """Registry-Vertrag eines API-Graphen: alle Parameter-Bindungen vorhanden, nur Modelldateien
    der eigenen Engine. Gilt für das Laden wie für das Übernehmen eines bearbeiteten Graphen."""
    problems = [
        f"params.{name} -> {node}.{key} fehlt im API-Graph."
        for name, p in wf.params.items()
        for node, key in ((p.node, p.input), *p.also)
        if key not in (graph.get(node) or {}).get("inputs", {})
    ]
    for name, p in wf.params.items():  # Standardwert aus dem Graph muss gültig sein (live 17.11.)
        value = (graph.get(p.node) or {}).get("inputs", {}).get(p.input)
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        if isinstance(value, (int, float)) and (
            (p.min is not None and value < p.min) or (p.max is not None and value > p.max)
        ):
            problems.append(f"params.{name}: Graph-Wert {value} außerhalb {p.min}…{p.max}.")
        if p.choices and value not in p.choices:
            problems.append(f"params.{name}: Graph-Wert {value} nicht in der Auswahl.")
    if wf.video:
        v = wf.video
        if v.length_input not in (graph.get(v.length_node) or {}).get("inputs", {}):
            problems.append(f"video.length -> {v.length_node}.{v.length_input} fehlt im API-Graph.")
        if v.mode == "frames" and v.decode not in graph:
            problems.append(f"video.decode -> {v.decode} fehlt im API-Graph.")
        if v.mode == "seconds":  # Sekunden-Eingang: Graph-Wert innerhalb der Engine-Grenze
            value = (graph.get(v.length_node) or {}).get("inputs", {}).get(v.length_input)
            if not isinstance(value, (int, float)) or not 1 <= value <= v.seconds_max:
                problems.append(f"video.length: Graph-Wert {value} außerhalb 1…{v.seconds_max:g}.")
    if wf.keyframes:
        k = wf.keyframes
        for node in (k.after, k.before, *k.chain):
            if node not in graph:
                problems.append(f"keyframes -> Knoten {node} fehlt im API-Graph.")
        guide = (graph.get(k.before) or {}).get("inputs", {})
        for name in (
            "positive",
            "negative",
            "latent",
            k.image_input,
            k.frame_input,
            k.strength_input,
        ):
            if name not in guide:
                problems.append(f"keyframes.before -> {k.before} hat keinen Eingang '{name}'.")
    if wf.identity:
        inputs = (graph.get(wf.identity) or {}).get("inputs", {})
        missing = [n for n in IDENTITY_INPUTS if n not in inputs]
        if missing:
            problems.append(f"identity -> {wf.identity} hat keine Eingänge {missing} im API-Graph.")
    if wf.mask_output and (graph.get(wf.mask_output) or {}).get("class_type") != "SaveImage":
        problems.append(f"mask_output -> {wf.mask_output} ist kein SaveImage-Node im API-Graph.")
    for role, node, name in (
        ("training.dataset", wf.train_dataset, "folder"),
        ("training.lora", wf.train_lora, "prefix"),
        ("training.checkpoint", wf.train_checkpoint, "checkpoint_dir"),
    ):
        if node and name not in (graph.get(node) or {}).get("inputs", {}):
            problems.append(f"{role} -> {node} hat keinen Eingang '{name}' im API-Graph.")
    if wf.lora:
        loader = (graph.get(wf.lora.node) or {}).get("inputs", {})
        for name in (wf.lora.name, *wf.lora.through):
            if name not in loader:
                problems.append(f"lora -> {wf.lora.node} hat keinen Eingang '{name}' im API-Graph.")
            elif name in wf.lora.through and not isinstance(loader[name], list):
                problems.append(f"lora.through -> {wf.lora.node}.{name} ist keine Verbindung.")
    if wf.text:
        problems += _text_problems(wf, graph)
    for node_id, node in graph.items():
        for name, value in node.get("inputs", {}).items():
            is_model = isinstance(value, str) and value.endswith((".safetensors", ".gguf"))
            if wf.lora and (node_id, name) == (wf.lora.node, wf.lora.name):
                continue  # setzt das Backend aus der LoRA des Auftrags
            if is_model and value not in model_names:
                problems.append(
                    f"Node {node_id} lädt '{value}', das nicht zur Engine {wf.engine} gehört."
                )
    return problems


def _reaches(graph: dict, start: str) -> set[tuple[str, str]]:
    """Alle (Knoten, Eingang), in die der Ausgang von ``start`` direkt oder über Zwischenknoten
    fließt."""
    found: set[tuple[str, str]] = set()
    todo, seen = [start], {start}
    while todo:
        src = todo.pop()
        for nid, node in graph.items():
            for name, value in (node.get("inputs") or {}).items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]) == src:
                    found.add((nid, name))
                    if nid not in seen:
                        seen.add(nid)
                        todo.append(nid)
    return found


def _source(graph: dict, node: str, name: str) -> str:
    value = (graph.get(node) or {}).get("inputs", {}).get(name)
    return str(value[0]) if isinstance(value, list) and len(value) == 2 else ""


def _text_problems(wf: Workflow, graph: dict) -> list[str]:
    """Sprachworkflow: jeder Profil- und Kontexteingang ist ein eigener Textknoten, der in einen
    Sprachknoten fließt; Ehrlichkeitsblock wortgleich im Systemprompt der Persona-Antwort;
    neutraler Einstufungslauf vor der Antwort, deren Nutzertext die Einstufung enthält (E26)."""
    t = wf.text
    assert t is not None
    problems = []
    sessions = set(wf.session_nodes(graph))
    for name in (*PROFILE_INPUTS, *CONTEXT_INPUTS):
        p = wf.params[name]
        if (graph.get(p.node) or {}).get("class_type") != TEXT_NODE or p.input != "value":
            problems.append(f"params.{name}: eigener Textknoten ({TEXT_NODE}.value) fehlt.")
        elif not any(
            n in sessions and i in ("system_prompt", "user_text")
            for n, i in _reaches(graph, p.node)
        ):
            problems.append(f"params.{name}: Textknoten {p.node} fließt in keinen Sprachknoten.")
    outputs = {"answer": t.answer, "classification": t.classification, "system": t.system,
               "user": t.user}  # fmt: skip
    for role, node in outputs.items():
        if (graph.get(node) or {}).get("class_type") != PREVIEW_NODE:
            problems.append(f"text.{role} -> {node} ist kein {PREVIEW_NODE}-Knoten.")
    persona = _source(graph, t.answer, "source")
    neutral = _source(graph, t.classification, "source")
    if persona not in sessions or neutral not in sessions or persona == neutral:
        problems.append("text: Antwort und Einstufung brauchen je einen eigenen Sprachknoten.")
        return problems
    if (persona, "user_text") not in _reaches(graph, neutral):
        problems.append("text: Einstufung fließt nicht in den Nutzertext der Antwort (E26).")
    if (neutral, "system_prompt") not in _reaches(graph, wf.params["classification"].node):
        problems.append("text: Einstufungsblock ist nicht der Systemprompt des Einstufungslaufs.")
    honesty = graph.get(t.honesty_node) or {}
    value = honesty.get("inputs", {}).get("value")
    if honesty.get("class_type") != TEXT_NODE or value != t.honesty:
        problems.append("text: Ehrlichkeitsblock fehlt oder weicht ab (Regel 12 c).")
    elif (persona, "system_prompt") not in _reaches(graph, t.honesty_node):
        problems.append("text: Ehrlichkeitsblock ist nicht mit dem Systemprompt verbunden.")
    if _source(graph, t.system, "source") != _source(graph, persona, "system_prompt"):
        problems.append("text.system zeigt nicht den Systemprompt der Antwort.")
    if _source(graph, t.user, "source") != _source(graph, persona, "user_text"):
        problems.append("text.user zeigt nicht den Nutzertext der Antwort.")
    return problems


def honesty_text(man: Manifest) -> str:
    """Ehrlichkeitsblock aus dem registrierten Sprachworkflow (leer ohne Sprachworkflow)."""
    return next((wf.text.honesty for wf in man.workflows.values() if wf.text), "")


# --------------------------------------------------------------------------------- Bearbeiten


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


# Cockpit-Befehle und Trainingsläufe (Worker-Thread) ändern die Registry nie gleichzeitig
_EDIT_LOCK = threading.Lock()


def edit_manifest(root: Path, change: Callable[[tomlkit.TOMLDocument], None]) -> Manifest:
    """Ändert die Registry formatbewahrend; gespeichert wird nur ein gültiges Ergebnis."""
    path = root / MANIFEST_RELATIVE
    with _EDIT_LOCK:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        change(doc)
        # entfernte Tabellen sollen keine Leerzeilen am Dateiende hinterlassen
        text = tomlkit.dumps(doc).rstrip("\n") + "\n"
        manifest = load_manifest(root, text=text)
        _atomic_write(path, text)
    return manifest


def register_lora(root: Path, lora: Lora) -> Manifest:
    """Trägt eine trainierte LoRA in die Registry ein (Status OFFEN bis zur Freigabe)."""

    def change(doc: tomlkit.TOMLDocument) -> None:
        if "loras" not in doc:
            doc["loras"] = tomlkit.table(is_super_table=True)
        if lora.key in doc["loras"]:
            raise ManifestError(f"LoRA '{lora.key}' ist bereits registriert.")
        table = tomlkit.table()
        for name, value in asdict(lora).items():
            if name != "key":
                table[name] = list(value) if isinstance(value, tuple) else value
        doc["loras"][lora.key] = table

    return edit_local(root, change)  # nie ins versionierte Manifest (BUG-092)


def _workflow_table(doc: tomlkit.TOMLDocument, key: str):
    table = doc.get("workflows", {}).get(key)
    if table is None:
        raise ManifestError(f"Workflow '{key}' ist nicht registriert.")
    return table


def set_workflow_enabled(root: Path, key: str, enabled: bool) -> Manifest:
    """Schalter „aktiviert“ in der lokalen Registry (BUG-092)."""
    if key not in load_manifest(root).workflows:
        raise ManifestError(f"Workflow '{key}' ist nicht registriert.")

    def change(doc: tomlkit.TOMLDocument) -> None:
        if "workflows" not in doc:
            doc["workflows"] = tomlkit.table(is_super_table=True)
        if key not in doc["workflows"]:
            doc["workflows"][key] = tomlkit.table()
        doc["workflows"][key]["enabled"] = enabled

    return edit_local(root, change)


def delete_workflow(root: Path, key: str) -> Manifest:
    """Entfernt nur die Registrierung und die UI-/API-Dateien dieses Workflows. Modelle, Jobs,
    Medien und Nachweise bleiben unberührt."""
    wf = load_manifest(root).workflows.get(key)
    if wf is None:
        raise ManifestError(f"Workflow '{key}' ist nicht registriert.")
    man = edit_manifest(root, lambda doc: doc["workflows"].remove(key))
    for rel in {wf.ui, wf.api}:
        (root / "workflows" / rel).unlink(missing_ok=True)
    local = root / LOCAL_REGISTRY
    if local.is_file() and key in tomllib.loads(local.read_text("utf-8")).get("workflows", {}):
        # Schalter nicht an einen späteren Workflow mit gleichem Schlüssel vererben
        man = edit_local(root, lambda doc: doc["workflows"].remove(key))
    return man


def _slug(title: str) -> str:
    text = title.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:40]
    return slug if slug[:1].isalpha() else f"wf_{slug}"


def create_workflow(root: Path, source: str, title: str) -> tuple[Manifest, str]:
    """Registriert eine Kopie von ``source`` (Engine, Parameter, UI-/API-Graph) unter neuem Titel;
    Status OFFEN. Liefert die neue Registry und den vergebenen Schlüssel."""
    man = load_manifest(root)
    src = man.workflows.get(source)
    title = title.strip()
    if src is None:
        raise ManifestError(f"Vorlage '{source}' ist nicht registriert.")
    if not title:
        raise ManifestError("Titel fehlt.")
    if any(w.title == title for w in man.workflows.values()):
        raise ManifestError(f"Titel „{title}“ ist bereits vergeben.")
    base = _slug(title)
    key = next(
        k for k in (base, *(f"{base}_{n}" for n in range(2, 1000))) if k not in man.workflows
    )
    folder = Path(src.api).parent.as_posix()
    ui, api = f"{folder}/{key}.ui.json", f"{folder}/{key}.api.json"
    wdir = root / "workflows"
    if (wdir / ui).exists() or (wdir / api).exists():
        raise ManifestError(f"Workflow-Dateien für '{key}' existieren bereits.")

    def change(doc: tomlkit.TOMLDocument) -> None:
        # vollständige Kopie (Parameter, mask_output …); eigene Dateien, Titel, Abnahme offen
        table = tomlkit.parse(tomlkit.dumps({"t": doc["workflows"][source]}))["t"]
        table.pop("enabled", None)
        table["ui"] = ui
        table["api"] = api
        table["status"] = "OFFEN"
        table["title"] = title
        doc["workflows"][key] = table

    _atomic_write(wdir / api, (wdir / src.api).read_text(encoding="utf-8"))
    _atomic_write(wdir / ui, (wdir / src.ui).read_text(encoding="utf-8"))
    try:
        return edit_manifest(root, change), key
    except BaseException:
        (wdir / api).unlink(missing_ok=True)
        (wdir / ui).unlink(missing_ok=True)
        raise


def replace_workflow_graph(
    root: Path, key: str, ui: dict, api: dict, *, reset_status: bool
) -> Manifest:
    """Übernimmt einen bearbeiteten UI- und API-Graphen. Erst prüfen, dann atomar schreiben;
    ein geänderter Rendergraph verliert seine Abnahme (Status OFFEN) bis zum erneuten Test."""
    man = load_manifest(root)
    wf = man.workflows.get(key)
    if wf is None:
        raise ManifestError(f"Workflow '{key}' ist nicht registriert.")
    problems = graph_problems(
        wf, api, engine_model_names(man.files, man.engines, man.loras, wf.engine)
    )
    if problems:
        raise ManifestError("; ".join(problems))
    if reset_status and wf.status != "OFFEN":
        edit_manifest(root, lambda doc: _workflow_table(doc, key).__setitem__("status", "OFFEN"))
    _atomic_write(root / "workflows" / wf.api, json.dumps(api, indent=1, ensure_ascii=False) + "\n")
    _atomic_write(root / "workflows" / wf.ui, json.dumps(ui, indent=1, ensure_ascii=False) + "\n")
    return load_manifest(root)


# --------------------------------------------------------------------------------- Status


def models_dir(root: Path) -> Path:
    return root / "local" / "models"


def file_state(mf: ModelFile, base: Path) -> str:
    """present | missing | size_mismatch (Größe genügt für Status; SHA-256 siehe verify)."""
    p = base / mf.target
    if not p.is_file():
        return "missing"
    return "present" if p.stat().st_size == mf.size else "size_mismatch"


def status(man: Manifest, base: Path) -> dict:
    engines = {}
    for key, eng in man.engines.items():
        states = {f: file_state(man.files[f], base) for f in eng.files}
        missing = [f for f, s in states.items() if s != "present"]
        engines[key] = {
            "title": eng.title,
            "kind": eng.kind,
            "role": eng.role,
            "wave": eng.wave,
            "usage": eng.usage,
            "gates": eng.gates,
            "files": states,
            "ready": not missing,
            "missing_gb": round(sum(man.files[f].size for f in missing) / 1e9, 2),
        }
    free = shutil.disk_usage(base if base.exists() else man.root).free
    return {"free_gb": round(free / 1e9, 1), "reserve_gb": man.reserve_gb, "engines": engines}


def orphans(man: Manifest, base: Path) -> list[str]:
    """Dateien unter local/models, die keine Manifest-Datei sind (Kandidaten zum Aufräumen)."""
    known = {mf.target for mf in man.files.values()}
    found = []
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base)
            registered = rel.as_posix() in known
            if (
                p.is_file()
                and rel.parts[0] != STAGING
                and not p.name.startswith(".")
                and not registered
            ):
                found.append(rel.as_posix())
    return found


def sha256_of(path: Path, chunk: int = 16 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def verify(man: Manifest, base: Path, keys: list[str]) -> dict[str, str]:
    """SHA-256 aller angegebenen, vorhandenen Dateien prüfen: ok | missing | MISMATCH."""
    result = {}
    for key in keys:
        mf = man.files[key]
        p = base / mf.target
        if not p.is_file():
            result[key] = "missing"
            continue
        result[key] = "ok" if sha256_of(p) == mf.sha256 else "MISMATCH"
        log.info("verify %s: %s", key, result[key])
    return result


# --------------------------------------------------------------------------------- Download


def select(
    man: Manifest,
    *,
    engines: list[str] | None = None,
    wave: int | None = None,
    base: Path | None = None,
) -> list[str]:
    """Dateischlüssel (dedupliziert) für Engines bzw. eine Welle.

    Reihenfolge: Engine für Engine, kleinste verbleibende Downloadmenge zuerst – so werden bei
    langsamer Leitung möglichst früh vollständige, testbare Engines fertig.
    """
    unknown = set(engines or []) - set(man.engines)
    if unknown:
        raise ModelError(f"Unbekannte Engine(s): {', '.join(sorted(unknown))}")
    chosen = [
        key
        for key, eng in man.engines.items()
        if (engines and key in engines) or (wave is not None and eng.wave == wave)
    ]

    def remaining(key: str) -> int:
        return sum(
            mf.size
            for mf in man.engine_files(key)
            if base is None or file_state(mf, base) != "present"
        )

    ordered: list[str] = []
    for key in sorted(chosen, key=remaining):
        ordered += [f for f in man.engines[key].files if f not in ordered]
    return ordered


def download(man: Manifest, base: Path, keys: list[str]) -> dict[str, str]:
    """Lädt fehlende Dateien über die gepinnte Revision, prüft Größe + SHA-256, legt atomar ab."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

    todo = [man.files[k] for k in keys if file_state(man.files[k], base) != "present"]
    need = sum(mf.size for mf in todo)
    base.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(base).free
    if free - need < man.reserve_gb * 1e9:
        raise ModelError(
            f"Zu wenig Speicher: benötigt {need / 1e9:.1f} GB, frei {free / 1e9:.1f} GB, "
            f"Reserve {man.reserve_gb:.0f} GB."
        )
    results = {k: "present" for k in keys if man.files[k] not in todo}
    for mf in list(todo):  # ausdrücklich gleiche Datei: aus dem vorhandenen Ziel kopieren
        twin = man.files.get(mf.duplicate_of) if mf.duplicate_of else None
        if twin is not None and file_state(twin, base) == "present":
            target = base / mf.target
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / twin.target, target)
            if sha256_of(target) != mf.sha256:
                target.unlink(missing_ok=True)
                results[mf.key] = "MISMATCH"
            else:
                results[mf.key] = "copied"
            todo.remove(mf)
    for mf in todo:
        staging = base / STAGING / mf.key
        t0 = time.monotonic()
        log.info("Download %s (%s @ %s, %.2f GB)", mf.key, mf.repo, mf.revision[:12], mf.size / 1e9)
        try:
            got = Path(
                hf_hub_download(
                    repo_id=mf.repo, filename=mf.source, revision=mf.revision, local_dir=staging
                )
            )
        except GatedRepoError:
            results[mf.key] = "gated"
            log.error("%s: Repo %s ist gated – Lizenz auf HF akzeptieren", mf.key, mf.repo)
            continue
        except (HfHubHTTPError, OSError) as exc:
            results[mf.key] = f"error: {exc}"
            log.error("%s: Download fehlgeschlagen: %s", mf.key, exc)
            continue
        if got.stat().st_size != mf.size or sha256_of(got) != mf.sha256:
            got.unlink(missing_ok=True)
            results[mf.key] = "MISMATCH"
            log.error("%s: Größe/SHA-256 stimmt nicht – Datei verworfen", mf.key)
            continue
        target = base / mf.target
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(got, target)
        shutil.rmtree(staging, ignore_errors=True)
        dt = time.monotonic() - t0
        results[mf.key] = "downloaded"
        log.info("%s fertig: %.0f s, %.0f MB/s, SHA-256 ok", mf.key, dt, mf.size / 1e6 / dt)
    return results
