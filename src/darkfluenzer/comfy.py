"""ComfyUI-HTTP-API: registrierte API-Workflows parametrisieren, ausführen, Ergebnisse sichern.

Nur Workflows aus ``workflows/manifest.toml`` sind ausführbar, und nur ihre dort deklarierten
Parameter dürfen gesetzt werden. Keine Browser-Automation. Die Serverbereitschaft wird über die
einzige Startlogik (``runtime.start``) hergestellt.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import runtime
from .config import Config
from .models import Manifest, Workflow

log = logging.getLogger("darkfluenzer.comfy")


class ComfyError(Exception):
    """Fehler bei Übermittlung, Ausführung oder Ergebnisabruf. ``details`` maschinenlesbar."""

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.details = details


class ComfyTimeout(ComfyError):
    pass


@dataclass(frozen=True)
class OutputFile:
    node: str
    path: Path
    sha256: str
    size: int


@dataclass
class RenderResult:
    prompt_id: str
    workflow: str
    engine: str
    params: dict
    outputs: list[OutputFile] = field(default_factory=list)
    duration_s: float = 0.0
    provenance: dict = field(default_factory=dict)


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ---------------------------------------------------------------- HTTP
    def _request(self, method: str, path: str, body: dict | None = None) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(payload)
            except ValueError:
                parsed = {"raw": payload[:2000]}
            raise ComfyError(
                f"ComfyUI {method} {path} -> HTTP {exc.code}", status=exc.code, response=parsed
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyError(f"ComfyUI nicht erreichbar ({self.base}): {exc}") from exc

    def _json(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            return json.loads(self._request(method, path, body))
        except ValueError as exc:
            raise ComfyError(f"Ungültige JSON-Antwort von {path}") from exc

    # ---------------------------------------------------------------- API
    def ready(self) -> bool:
        try:
            return "system" in self._json("GET", "/system_stats")
        except ComfyError:
            return False

    def object_info(self) -> dict:
        return self._json("GET", "/object_info")

    def submit(self, graph: dict, prompt_id: str | None = None) -> str:
        prompt_id = prompt_id or uuid.uuid4().hex
        try:
            res = self._json(
                "POST",
                "/prompt",
                {"prompt": graph, "client_id": self.client_id, "prompt_id": prompt_id},
            )
        except ComfyError as exc:
            if "status" not in exc.details:  # Netzwerkfehler, keine Antwort von ComfyUI
                raise
            resp = exc.details.get("response") or {}
            raise ComfyError(
                f"Workflow von ComfyUI abgelehnt: {_describe_error(resp)}",
                node_errors=resp.get("node_errors"),
                error=resp.get("error"),
            ) from exc
        if res.get("node_errors"):
            raise ComfyError("Workflow-Validierung fehlgeschlagen", node_errors=res["node_errors"])
        return res.get("prompt_id", prompt_id)

    def history(self, prompt_id: str) -> dict | None:
        return self._json("GET", f"/history/{prompt_id}").get(prompt_id)

    def queue(self) -> dict:
        return self._json("GET", "/queue")

    def cancel(self, prompt_id: str) -> None:
        """Nur den eigenen Auftrag abbrechen: wartend -> aus Queue löschen, laufend -> gezielt."""
        q = self.queue()
        if any(item[1] == prompt_id for item in q.get("queue_pending", [])):
            self._request("POST", "/queue", {"delete": [prompt_id]})
        elif any(item[1] == prompt_id for item in q.get("queue_running", [])):
            self._request("POST", "/interrupt", {"prompt_id": prompt_id})

    def wait(self, prompt_id: str, timeout_s: float, poll_s: float = 1.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while True:
            entry = self.history(prompt_id)
            if entry is not None:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyError(
                        f"Ausführung fehlgeschlagen: {_execution_error(status)}",
                        prompt_id=prompt_id,
                        messages=status.get("messages"),
                    )
                if status.get("completed"):
                    return entry
            if time.monotonic() > deadline:
                self.cancel(prompt_id)
                raise ComfyTimeout(
                    f"Auftrag {prompt_id} nach {timeout_s:.0f} s abgebrochen.", prompt_id=prompt_id
                )
            time.sleep(poll_s)

    def fetch(self, image: dict) -> bytes:
        query = urllib.parse.urlencode(
            {
                "filename": image["filename"],
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            }
        )
        return self._request("GET", f"/view?{query}")


# -------------------------------------------------------------------- Workflow-Parameter


def load_graph(man: Manifest, wf: Workflow) -> dict:
    return json.loads((man.root / "workflows" / wf.api).read_text(encoding="utf-8"))


def apply_params(graph: dict, wf: Workflow, values: dict) -> dict:
    """Setzt NUR deklarierte Parameter (Typ- und Bereichsprüfung). Original bleibt unverändert."""
    unknown = set(values) - set(wf.params)
    if unknown:
        raise ComfyError(f"Nicht freigegebene Parameter für {wf.key}: {sorted(unknown)}")
    missing = [k for k, p in wf.params.items() if p.required and k not in values]
    if missing:
        raise ComfyError(f"Pflichtparameter fehlen für {wf.key}: {missing}")
    out = copy.deepcopy(graph)
    for name, value in values.items():
        spec = wf.params[name]
        try:
            out[spec.node]["inputs"][spec.input] = spec.coerce(name, value)
        except ValueError as exc:
            raise ComfyError(str(exc)) from exc
    return out


def _git_revision(root: Path, rel: str) -> str:
    try:
        rev = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%H", "--", rel],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--", rel],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except OSError:
        return "unbekannt"
    return (rev or "uncommitted") + ("+dirty" if dirty else "")


def provenance(man: Manifest, wf: Workflow, values: dict) -> dict:
    """Reproduzierbare Herkunft: Workflow-Revision + Datei-Hash, Modelldateien mit Revision/SHA."""
    api_path = man.root / "workflows" / wf.api
    return {
        "workflow": wf.key,
        "workflow_file": f"workflows/{wf.api}",
        "workflow_sha256": hashlib.sha256(api_path.read_bytes()).hexdigest(),
        "workflow_git": _git_revision(man.root, f"workflows/{wf.api}"),
        "engine": wf.engine,
        "models": [
            {"file": mf.key, "repo": mf.repo, "revision": mf.revision, "sha256": mf.sha256}
            for mf in man.engine_files(wf.engine)
        ],
        "params": values,
    }


def run_workflow(
    cfg: Config,
    man: Manifest,
    workflow_key: str,
    values: dict,
    dest: Path,
    *,
    stem: str,
    timeout_s: float = 1800.0,
) -> RenderResult:
    """Server sicherstellen, Workflow ausführen, alle Ausgabedateien unter ``dest`` sichern.

    Ausgaben werden niemals überschrieben (vorhandene Zieldatei -> Fehler).
    """
    if workflow_key not in man.workflows:
        raise ComfyError(f"Workflow '{workflow_key}' ist nicht registriert.")
    wf = man.workflows[workflow_key]
    if wf.status == "GESPERRT":
        raise ComfyError(f"Workflow '{workflow_key}' ist gesperrt.")
    graph = apply_params(load_graph(man, wf), wf, values)
    runtime.start(cfg)  # einzige Startlogik; idempotent
    client = ComfyClient(cfg.comfyui.url)
    t0 = time.monotonic()
    prompt_id = client.submit(graph)
    log.info("Auftrag %s: Workflow %s übermittelt", prompt_id, workflow_key)
    entry = client.wait(prompt_id, timeout_s)
    dest.mkdir(parents=True, exist_ok=True)
    result = RenderResult(
        prompt_id=prompt_id,
        workflow=workflow_key,
        engine=wf.engine,
        params=values,
        provenance=provenance(man, wf, values),
    )
    index = 0
    for node_id, out in (entry.get("outputs") or {}).items():
        for item in out.get("images", []) + out.get("gifs", []) + out.get("videos", []):
            index += 1
            data = client.fetch(item)
            suffix = Path(item["filename"]).suffix or ".bin"
            target = dest / f"{stem}_{index:02d}{suffix}"
            with open(target, "xb") as fh:  # "x": niemals überschreiben
                fh.write(data)
            result.outputs.append(
                OutputFile(
                    node=node_id,
                    path=target,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size=len(data),
                )
            )
    if not result.outputs:
        raise ComfyError(f"Auftrag {prompt_id} lieferte keine Ausgabedatei.", prompt_id=prompt_id)
    result.duration_s = round(time.monotonic() - t0, 1)
    log.info(
        "Auftrag %s fertig: %d Datei(en) in %.1f s",
        prompt_id,
        len(result.outputs),
        result.duration_s,
    )
    return result


def _describe_error(resp: dict) -> str:
    err = resp.get("error") or {}
    msg = err.get("message", "") if isinstance(err, dict) else str(err)
    for node_id, info in (resp.get("node_errors") or {}).items():
        for e in info.get("errors", []):
            node = f"Node {node_id} ({info.get('class_type')})"
            msg += f" | {node}: {e.get('message')} {e.get('details', '')}"
    return msg.strip() or "unbekannt"


def _execution_error(status: dict) -> str:
    for kind, data in status.get("messages") or []:
        if kind == "execution_error":
            node = f"Node {data.get('node_id')} ({data.get('node_type')})"
            return f"{node}: {data.get('exception_message', '').strip()}"
        if kind == "execution_interrupted":
            return "abgebrochen"
    return "unbekannter Fehler"
