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

    def upload_image(self, path: Path, subfolder: str = "darkfluenzer") -> str:
        """Lädt eine Eingabedatei (Master/Maske) in ComfyUIs input-Ordner; liefert LoadImage-Namen.

        Der Dateiname enthält den SHA-256-Präfix, damit gleiche Namen nie fremde Inhalte treffen.
        """
        data = path.read_bytes()
        name = f"{hashlib.sha256(data).hexdigest()[:16]}_{path.name}"
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="subfolder"\r\n\r\n'
            f"{subfolder}\r\n",
            f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"'
            "\r\nContent-Type: application/octet-stream\r\n\r\n",
        ]
        body = "".join(parts).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + "/upload/image", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                res = json.loads(resp.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ComfyError(f"Upload von {path.name} fehlgeschlagen: {exc}") from exc
        return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]

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


# -------------------------------------------------------------------- Workflow-Verträge

_WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


def _is_link(value: object) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)


def _spec_options(spec: list) -> dict:
    return spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}


def _combo_values(spec: list) -> list | None:
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO":
        return _spec_options(spec).get("options")
    return None


def _is_widget(spec: list) -> bool:
    return isinstance(spec[0], list) or spec[0] in _WIDGET_TYPES


def _default(spec: list) -> object:
    opts = _spec_options(spec)
    if "default" in opts:
        return opts["default"]
    values = _combo_values(spec)
    return values[0] if values else None


def _node_spec(object_info: dict, class_type: str) -> dict:
    info = object_info.get(class_type)
    if info is None:
        raise ComfyError(f"Node-Typ '{class_type}' ist in dieser ComfyUI nicht vorhanden.")
    return {**info["input"].get("required", {}), **info["input"].get("optional", {})}


def check_graph(graph: dict, object_info: dict, runtime_inputs: set[tuple[str, str]]) -> list[str]:
    """Prüft einen API-Graphen gegen die echte Node-Definition der laufenden ComfyUI.

    Findet unbekannte Nodes/Eingänge, fehlende Pflichteingänge, ungültige Verweise und
    COMBO-Werte, die ComfyUI nicht kennt (z. B. fehlende Modelldatei). ``runtime_inputs``
    (Node, Eingang) werden erst zur Laufzeit gesetzt und nicht als COMBO geprüft.
    """
    problems = []
    for nid, node in graph.items():
        try:
            spec = _node_spec(object_info, node["class_type"])
        except ComfyError as exc:
            problems.append(f"{nid}: {exc}")
            continue
        required = object_info[node["class_type"]]["input"].get("required", {})
        for name in required:
            if name not in node["inputs"]:
                problems.append(f"{nid} {node['class_type']}: Pflichteingang '{name}' fehlt")
        for name, value in node["inputs"].items():
            if name not in spec:
                problems.append(f"{nid} {node['class_type']}: unbekannter Eingang '{name}'")
                continue
            if _is_link(value):
                if value[0] not in graph:
                    problems.append(f"{nid}.{name}: Verweis auf fehlenden Node {value[0]}")
                continue
            values = _combo_values(spec[name])
            if values is not None and (nid, name) not in runtime_inputs and value not in values:
                problems.append(f"{nid} {node['class_type']}.{name}: '{value}' nicht verfügbar")
    return problems


def api_to_ui(graph: dict, object_info: dict) -> dict:
    """Erzeugt aus einem API-Graphen den ComfyUI-Editor-Workflow (gleiche Nodes, Werte, Links).

    Widget-Reihenfolge und Ausgänge stammen aus ``/object_info`` der laufenden ComfyUI, damit
    UI- und API-Export garantiert denselben Graphen beschreiben.
    """
    ids = sorted(graph, key=int)
    depth: dict[str, int] = {}

    def level(nid: str, trail: frozenset = frozenset()) -> int:
        if nid in trail:
            raise ComfyError(f"Zyklus im Graphen bei Node {nid}")
        if nid not in depth:
            ups = [v[0] for v in graph[nid]["inputs"].values() if _is_link(v)]
            depth[nid] = 1 + max((level(u, trail | {nid}) for u in ups), default=-1)
        return depth[nid]

    for nid in ids:
        level(nid)
    rows: dict[int, int] = {}
    nodes: dict[str, dict] = {}
    for order, nid in enumerate(sorted(ids, key=lambda n: (depth[n], int(n)))):
        node = graph[nid]
        info = object_info.get(node["class_type"])
        spec = _node_spec(object_info, node["class_type"])
        unknown = set(node["inputs"]) - set(spec)
        if unknown:
            raise ComfyError(f"Node {nid}: unbekannte Eingänge {sorted(unknown)}")
        inputs, widgets = [], []
        for name, sp in spec.items():
            value = node["inputs"].get(name)
            if _is_widget(sp):
                if _is_link(value):
                    typ = "COMBO" if _combo_values(sp) is not None else sp[0]
                    inputs.append(
                        {"name": name, "type": typ, "link": None, "widget": {"name": name}}
                    )
                    widgets.append(_default(sp))
                else:
                    widgets.append(value if name in node["inputs"] else _default(sp))
                if _spec_options(sp).get("control_after_generate"):
                    widgets.append("fixed")
            else:
                inputs.append({"name": name, "type": sp[0], "link": None})
        outputs = [
            {"name": oname, "type": otype, "links": [], "slot_index": i}
            for i, (otype, oname) in enumerate(
                zip(info["output"], info["output_name"], strict=True)
            )
        ]
        col = depth[nid]
        y = rows.get(col, 0)
        height = 46 + 24 * (len(inputs) + len(outputs) + len(widgets))
        rows[col] = y + height + 60
        nodes[nid] = {
            "id": int(nid),
            "type": node["class_type"],
            "pos": [40 + col * 420, 40 + y],
            "size": [360, height],
            "flags": {},
            "order": order,
            "mode": 0,
            "inputs": inputs,
            "outputs": outputs,
            "properties": {"Node name for S&R": node["class_type"]},
            "widgets_values": widgets,
        }
        if title := (node.get("_meta") or {}).get("title"):
            nodes[nid]["title"] = title
    links = []
    for nid in ids:
        for slot, inp in enumerate(nodes[nid]["inputs"]):
            value = graph[nid]["inputs"].get(inp["name"])
            if _is_link(value):
                src, src_slot = value
                link_id = len(links) + 1
                out = nodes[src]["outputs"][src_slot]
                links.append([link_id, int(src), src_slot, int(nid), slot, out["type"]])
                inp["link"] = link_id
                out["links"].append(link_id)
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(graph, sort_keys=True))),
        "revision": 0,
        "last_node_id": max(int(n) for n in ids),
        "last_link_id": len(links),
        "nodes": [nodes[n] for n in ids],
        "links": links,
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 0.75, "offset": [0, 0]}},
        "version": 0.4,
    }
