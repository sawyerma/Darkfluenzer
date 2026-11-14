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
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("darkfluenzer.models")

MANIFEST_RELATIVE = Path("workflows") / "manifest.toml"
GATES = ("load", "render", "quality", "license_pass")
GATE_VALUES = {"OFFEN", "PASS", "FAIL", "GESPERRT"}
USAGES = {"evaluation", "production"}
KINDS = {"image", "video"}
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
    engine: str
    ui: str
    api: str
    status: str
    params: dict[str, Param]


@dataclass(frozen=True)
class Manifest:
    root: Path
    reserve_gb: float
    roles: dict[str, str]
    files: dict[str, ModelFile]
    engines: dict[str, Engine]
    workflows: dict[str, Workflow]

    def engine_files(self, engine: str) -> list[ModelFile]:
        return [self.files[k] for k in self.engines[engine].files]


def _str(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        raise ManifestError(f"Manifest: {where}.{key} fehlt oder ist kein Text.")
    return value


def load_manifest(root: Path) -> Manifest:
    path = root / MANIFEST_RELATIVE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
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
        if not refs or missing:
            raise ManifestError(f"Manifest: {w}.files leer oder unbekannt: {missing}")
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
        )
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

    workflows: dict[str, Workflow] = {}
    for key, t in (data.get("workflows") or {}).items():
        w = f"workflows.{key}"
        params = {}
        for name, spec in (t.get("params") or {}).items():
            try:
                params[name] = Param(**{**spec, "choices": tuple(spec.get("choices", ()))})
            except TypeError as exc:
                raise ManifestError(f"Manifest: {w}.params.{name}: {exc}") from exc
            if params[name].type not in PARAM_TYPES:
                raise ManifestError(
                    f"Manifest: {w}.params.{name}.type muss {set(PARAM_TYPES)} sein."
                )
        wf = Workflow(
            key=key,
            engine=_str(t, "engine", w),
            ui=_str(t, "ui", w),
            api=_str(t, "api", w),
            status=_str(t, "status", w),
            params=params,
        )
        if wf.engine not in engines:
            raise ManifestError(f"Manifest: {w}.engine '{wf.engine}' unbekannt.")
        if wf.status not in GATE_VALUES:
            raise ManifestError(f"Manifest: {w}.status muss {GATE_VALUES} sein.")
        for rel in (wf.ui, wf.api):
            if not (root / "workflows" / rel).is_file():
                raise ManifestError(f"Manifest: {w} verweist auf fehlende Datei workflows/{rel}.")
        graph = json.loads((root / "workflows" / wf.api).read_text(encoding="utf-8"))
        for name, prm in params.items():
            if prm.input not in (graph.get(prm.node) or {}).get("inputs", {}):
                raise ManifestError(
                    f"Manifest: {w}.params.{name} -> {prm.node}.{prm.input} fehlt im API-Graph."
                )
        names = {mf.comfy_name for mf in (files[f] for f in engines[wf.engine].files)}
        for node_id, node in graph.items():
            for value in node.get("inputs", {}).values():
                is_model = isinstance(value, str) and value.endswith((".safetensors", ".gguf"))
                if is_model and value not in names:
                    raise ManifestError(
                        f"Manifest: {w} Node {node_id} lädt '{value}', das nicht zur Engine "
                        f"{wf.engine} gehört."
                    )
        workflows[key] = wf

    return Manifest(
        root=root,
        reserve_gb=float(data.get("reserve_gb", 30)),
        roles=roles,
        files=files,
        engines=engines,
        workflows=workflows,
    )


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
