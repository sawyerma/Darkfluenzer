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
GATES = ("load", "render", "quality", "license_pass")
GATE_VALUES = {"OFFEN", "PASS", "FAIL", "GESPERRT"}
USAGES = {"evaluation", "production"}
KINDS = {"image", "video"}
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
    # Inhaltsstufe der Ergebnisse (PHASENPLAN_V0 Regel 13): fail-closed – ohne Eintrag „explizit“;
    # „standard“ nur, wenn ausdrücklich so im Manifest markiert
    content: str = "explizit"

    @property
    def training(self) -> bool:
        return bool(self.train_dataset)


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

    @property
    def comfy_name(self) -> str:
        return self.target.split("/", 1)[1]


@dataclass(frozen=True)
class Manifest:
    root: Path
    reserve_gb: float
    roles: dict[str, str]
    files: dict[str, ModelFile]
    engines: dict[str, Engine]
    workflows: dict[str, Workflow]
    loras: dict[str, Lora]

    def engine_files(self, engine: str) -> list[ModelFile]:
        return [self.files[k] for k in self.engines[engine].files]


def _str(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        raise ManifestError(f"Manifest: {where}.{key} fehlt oder ist kein Text.")
    return value


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
        loras[key] = lora

    workflows: dict[str, Workflow] = {}
    for key, t in (data.get("workflows") or {}).items():
        w = f"workflows.{key}"
        params = {}
        for name, spec in (t.get("params") or {}).items():
            try:
                params[name] = Param(**{**spec, "choices": tuple(spec.get("choices", ()))})
            except TypeError as exc:
                raise ManifestError(f"Manifest: {w}.params.{name}: {exc}") from exc
            if params[name].reference and not params[name].upload:
                raise ManifestError(f"Manifest: {w}.params.{name}: reference nur mit upload.")
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
            content=str(t.get("content", "explizit")),
        )
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
        if wf.status not in GATE_VALUES:
            raise ManifestError(f"Manifest: {w}.status muss {GATE_VALUES} sein.")
        for rel in (wf.ui, wf.api) if require_ui else (wf.api,):
            if not (root / "workflows" / rel).is_file():
                raise ManifestError(f"Manifest: {w} verweist auf fehlende Datei workflows/{rel}.")
        graph = json.loads((root / "workflows" / wf.api).read_text(encoding="utf-8"))
        problems = graph_problems(wf, graph, engine_model_names(files, engines, loras, wf.engine))
        if problems:
            raise ManifestError(f"Manifest: {w}: {problems[0]}")
        workflows[key] = wf

    return Manifest(
        root=root,
        reserve_gb=float(data.get("reserve_gb", 30)),
        roles=roles,
        files=files,
        engines=engines,
        workflows=workflows,
        loras=loras,
    )


def engine_model_names(
    files: dict[str, ModelFile], engines: dict[str, Engine], loras: dict[str, Lora], engine: str
) -> set[str]:
    """Modelldateien, die ein Workflow dieser Engine laden darf: ihre Dateien und die auf ihr
    trainierten LoRAs."""
    names = {files[f].comfy_name for f in engines[engine].files}
    return names | {lo.comfy_name for lo in loras.values() if lo.base_engine == engine}


def graph_problems(wf: Workflow, graph: dict, model_names: set[str]) -> list[str]:
    """Registry-Vertrag eines API-Graphen: alle Parameter-Bindungen vorhanden, nur Modelldateien
    der eigenen Engine. Gilt für das Laden wie für das Übernehmen eines bearbeiteten Graphen."""
    problems = [
        f"params.{name} -> {p.node}.{p.input} fehlt im API-Graph."
        for name, p in wf.params.items()
        if p.input not in (graph.get(p.node) or {}).get("inputs", {})
    ]
    if wf.mask_output and (graph.get(wf.mask_output) or {}).get("class_type") != "SaveImage":
        problems.append(f"mask_output -> {wf.mask_output} ist kein SaveImage-Node im API-Graph.")
    for role, node, name in (
        ("training.dataset", wf.train_dataset, "folder"),
        ("training.lora", wf.train_lora, "prefix"),
    ):
        if node and name not in (graph.get(node) or {}).get("inputs", {}):
            problems.append(f"{role} -> {node} hat keinen Eingang '{name}' im API-Graph.")
    for node_id, node in graph.items():
        for value in node.get("inputs", {}).values():
            is_model = isinstance(value, str) and value.endswith((".safetensors", ".gguf"))
            if is_model and value not in model_names:
                problems.append(
                    f"Node {node_id} lädt '{value}', das nicht zur Engine {wf.engine} gehört."
                )
    return problems


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
                table[name] = value
        doc["loras"][lora.key] = table

    return edit_manifest(root, change)


def _workflow_table(doc: tomlkit.TOMLDocument, key: str):
    table = doc.get("workflows", {}).get(key)
    if table is None:
        raise ManifestError(f"Workflow '{key}' ist nicht registriert.")
    return table


def set_workflow_enabled(root: Path, key: str, enabled: bool) -> Manifest:
    return edit_manifest(
        root, lambda doc: _workflow_table(doc, key).__setitem__("enabled", enabled)
    )


def delete_workflow(root: Path, key: str) -> Manifest:
    """Entfernt nur die Registrierung und die UI-/API-Dateien dieses Workflows. Modelle, Jobs,
    Medien und Nachweise bleiben unberührt."""
    wf = load_manifest(root).workflows.get(key)
    if wf is None:
        raise ManifestError(f"Workflow '{key}' ist nicht registriert.")
    man = edit_manifest(root, lambda doc: doc["workflows"].remove(key))
    for rel in {wf.ui, wf.api}:
        (root / "workflows" / rel).unlink(missing_ok=True)
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
