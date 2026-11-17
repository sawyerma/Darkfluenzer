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
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ComfyConfig, Config
from ..media.models import Manifest, Workflow
from . import local as runtime

log = logging.getLogger("darkfluenzer.comfy")

# Schlüssel in ComfyUIs extra_data, unter dem ein Auftrag seine Darkfluenzer-Job-ID trägt.
JOB_KEY = "darkfluenzer_job_id"


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
    # Speicherverlauf während des Laufs (MemoryTrace.summary)
    memory: dict = field(default_factory=dict)


def swap_used_mb() -> float:
    """Belegter macOS-Swap in MB (``sysctl vm.swapusage``)."""
    out = subprocess.run(
        ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5, check=False
    ).stdout
    for part in out.split("  "):
        key, _, value = part.strip().partition(" = ")
        if key == "used" and value.endswith("M"):
            return float(value[:-1])
    return 0.0


class MemoryTrace:
    """Speicherverlauf eines Laufs: freier Arbeitsspeicher laut ComfyUI (Unified Memory) und
    macOS-Swap – zu Beginn, Extremwert während des Wartens und am Ende."""

    def __init__(self, client: ComfyClient) -> None:
        self.client = client
        self.ram_total = 0
        self.free = []
        self.swap = []

    def sample(self) -> None:
        try:
            stats = self.client._json("GET", "/system_stats").get("system") or {}
        except ComfyError:
            return
        self.ram_total = int(stats.get("ram_total") or 0)
        self.free.append(int(stats.get("ram_free") or 0))
        self.swap.append(swap_used_mb())

    def summary(self) -> dict:
        if not self.free:
            return {}
        gb = 1024**3
        return {
            "ram_total_gb": round(self.ram_total / gb, 2),
            "ram_free_start_gb": round(self.free[0] / gb, 2),
            "ram_free_min_gb": round(min(self.free) / gb, 2),
            "ram_free_end_gb": round(self.free[-1] / gb, 2),
            "swap_start_mb": round(self.swap[0], 1),
            "swap_max_mb": round(max(self.swap), 1),
            "swap_end_mb": round(self.swap[-1], 1),
            "samples": len(self.free),
        }


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30.0, client_id: str | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        # ComfyUI meldet Fortschritt nur an den einreichenden Client (siehe progress_events)
        self.client_id = client_id or uuid.uuid4().hex
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

    def submit(self, graph: dict, job_id: int | None = None) -> str:
        """Auftrag einreichen; ``job_id`` (Darkfluenzer-Job) reist in ``extra_data`` mit und
        macht den Auftrag in ``/queue`` zuordenbar (siehe ``queued_jobs``)."""
        prompt_id = str(uuid.uuid4())  # ComfyUI verlangt UUID-Format
        body: dict = {"prompt": graph, "client_id": self.client_id, "prompt_id": prompt_id}
        if job_id is not None:
            body["extra_data"] = {JOB_KEY: job_id}
        try:
            res = self._json("POST", "/prompt", body)
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

    def free(self) -> None:
        """Modelle entladen und Speicher freigeben (Engine-Wechsel, PHASENPLAN_V0 §4.2)."""
        self._request("POST", "/free", {"unload_models": True, "free_memory": True})

    def history(self, prompt_id: str) -> dict | None:
        return self._json("GET", f"/history/{prompt_id}").get(prompt_id)

    def queue(self) -> dict:
        return self._json("GET", "/queue")

    def queued_jobs(self) -> list[tuple[int, bool, str]]:
        """(Darkfluenzer-Job-ID oder 0, läuft?, prompt_id) für alle Aufträge der Warteschlange."""
        q = self.queue()
        return [
            (int((item[3] or {}).get(JOB_KEY) or 0), running, str(item[1]))
            for running, items in (
                (True, q.get("queue_running", [])),
                (False, q.get("queue_pending", [])),
            )
            for item in items
        ]

    def _queued(self, prompt_id: str) -> bool:
        q = self.queue()
        return any(
            item[1] == prompt_id
            for key in ("queue_running", "queue_pending")
            for item in q.get(key, [])
        )

    def cancel(self, prompt_id: str) -> None:
        """Nur den eigenen Auftrag abbrechen: wartend -> aus Queue löschen, laufend -> gezielt."""
        q = self.queue()
        if any(item[1] == prompt_id for item in q.get("queue_pending", [])):
            self._request("POST", "/queue", {"delete": [prompt_id]})
        elif any(item[1] == prompt_id for item in q.get("queue_running", [])):
            self._request("POST", "/interrupt", {"prompt_id": prompt_id})

    def wait(
        self,
        prompt_id: str,
        timeout_s: float | None,
        poll_s: float = 1.0,
        on_poll: Callable[[], None] | None = None,
        lost_after_s: float | None = None,
    ) -> dict:
        """Auf das Ergebnis warten. Mit ``timeout_s`` gilt eine feste Frist (danach Abbruch).
        Ohne Frist (``None``) gibt es keinen zeitbasierten Abbruch. Das Warten endet durch Ergebnis,
        Fehler von ComfyUI, Abbruch durch den Betreiber (Unterbrechung in ComfyUI) oder wenn ComfyUI
        erreichbar ist und den Auftrag länger als ``lost_after_s`` weder in der Warteschlange noch
        im Verlauf kennt. Antwortet ComfyUI nicht, ist der Zustand unbekannt: es wird weiter
        gewartet und nach der Wiederverbindung abgeglichen, nie als Fehler gewertet."""
        if timeout_s is None and lost_after_s is None:
            raise ValueError("wait ohne Frist braucht lost_after_s")
        deadline = time.monotonic() + timeout_s if timeout_s is not None else None
        lost_since: float | None = None
        unknown_since: float | None = None
        while True:
            if on_poll is not None:
                on_poll()
            if deadline is not None:
                entry = self.history(prompt_id)
            else:
                try:
                    entry = self.history(prompt_id)
                    alive = entry is not None or self._queued(prompt_id)
                except ComfyError as exc:  # nicht erreichbar: Zustand unbekannt, weiter warten
                    if unknown_since is None:
                        unknown_since = time.monotonic()
                        log.warning("Auftrag %s: Zustand unbekannt, %s", prompt_id, exc)
                    lost_since = None
                    time.sleep(poll_s)
                    continue
                if unknown_since is not None:
                    log.info(
                        "Auftrag %s: ComfyUI wieder erreichbar nach %.0f s, Abgleich",
                        prompt_id,
                        time.monotonic() - unknown_since,
                    )
                    unknown_since = None
                if alive:
                    lost_since = None
                else:
                    lost_since = lost_since or time.monotonic()
                    if time.monotonic() - lost_since > lost_after_s:
                        raise ComfyError(
                            f"Auftrag {prompt_id}: ComfyUI kennt ihn weder in der Warteschlange "
                            "noch im Verlauf.",
                            prompt_id=prompt_id,
                        )
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
            if deadline is not None and time.monotonic() > deadline:
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
            coerced = spec.coerce(name, value)
        except ValueError as exc:
            raise ComfyError(str(exc)) from exc
        for node, key in ((spec.node, spec.input), *spec.also):
            out[node]["inputs"][key] = coerced
    for name, spec in wf.params.items():  # Bedingung zwischen Parametern (z. B. Wechsel < Schritte)
        if spec.below:
            low, high = wf.params[name], wf.params[spec.below]
            a = out[low.node]["inputs"][low.input]
            b = out[high.node]["inputs"][high.input]
            if not a < b:
                raise ComfyError(f"Parameter {name}={a} muss kleiner sein als {spec.below}={b}.")
    return out


def unique_outputs(graph: dict, tag: str) -> dict:
    """Hängt ``tag`` an jedes ``filename_prefix`` (SaveImage, SaveVideo …): Speicher-Nodes laufen
    je Auftrag neu und schreiben eigene Dateien. Ohne das meldet ComfyUI für unveränderte
    Teilgraphen die Datei eines früheren Laufs aus seinem Cache – die evtl. schon gelöscht ist;
    Modelle und Zwischenergebnisse bleiben weiter im Cache."""
    out = copy.deepcopy(graph)
    for node in out.values():
        prefix = node.get("inputs", {}).get("filename_prefix")
        if isinstance(prefix, str):
            node["inputs"]["filename_prefix"] = f"{prefix}_{tag}"
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
    timeout_s: float | None = None,
    job_id: int | None = None,
    client_id: str | None = None,
    on_submit: Callable[[str, dict], None] | None = None,
    unload_first: bool = False,
    overrides: dict[tuple[str, str], object] | None = None,
    extra: dict | None = None,
) -> RenderResult:
    """Server sicherstellen, Workflow ausführen, alle Ausgabedateien unter ``dest`` sichern.
    ``overrides``: (Node, Eingang) -> Wert, die das Backend selbst setzt (z. B. Trainingsdaten).
    ``extra``: zusätzliche Nodes des Backends (z. B. letztes Bild eines Videoabschnitts).

    ``on_submit(prompt_id, graph)`` hält den exakt eingereichten Graphen fest, bevor gewartet wird
    (Wiederanlauf nach einem Backend-Neustart: ``collect_workflow``). Ausgaben werden niemals
    überschrieben (vorhandene Zieldatei -> Fehler).
    """
    if workflow_key not in man.workflows:
        raise ComfyError(f"Workflow '{workflow_key}' ist nicht registriert.")
    wf = man.workflows[workflow_key]
    if wf.status == "GESPERRT":
        raise ComfyError(f"Workflow '{workflow_key}' ist gesperrt.")
    tag = f"job{job_id}" if job_id is not None else stem.rsplit("_", 1)[-1]
    graph = apply_params(load_graph(man, wf), wf, values)
    for (node, name), value in (overrides or {}).items():
        graph[node]["inputs"][name] = value
    graph.update(extra or {})
    graph = unique_outputs(graph, tag)
    inst = instance_of(cfg, man, wf)
    runtime.start(cfg, inst.name)  # einzige Startlogik; idempotent
    client = ComfyClient(inst.url, client_id=client_id)
    if unload_first:  # andere Engine als zuletzt: deren Modelle vorher kontrolliert entladen
        client.free()
        log.info("Engine-Wechsel zu %s: Modelle entladen", wf.engine)
    t0 = time.monotonic()
    prompt_id = client.submit(graph, job_id)
    log.info("Auftrag %s: Workflow %s übermittelt", prompt_id, workflow_key)
    if on_submit is not None:
        on_submit(prompt_id, graph)
    return collect_workflow(
        cfg, man, workflow_key, values, prompt_id, dest, stem=stem, timeout_s=timeout_s, t0=t0
    )


def collect_workflow(
    cfg: Config,
    man: Manifest,
    workflow_key: str,
    values: dict,
    prompt_id: str,
    dest: Path,
    *,
    stem: str,
    timeout_s: float | None,
    t0: float | None = None,
) -> RenderResult:
    """Auf einen eingereichten Auftrag warten und seine Ausgaben unter ``dest`` sichern – auch für
    einen vor einem Backend-Neustart eingereichten (dann ist ``t0`` unbekannt)."""
    wf = man.workflows[workflow_key]
    return collect_graph(
        instance_of(cfg, man, wf),
        prompt_id,
        dest,
        stem=stem,
        timeout_s=timeout_s,
        lost_after_s=cfg.production.comfy_lost_s,
        t0=t0,
        base=RenderResult(
            prompt_id=prompt_id,
            workflow=workflow_key,
            engine=wf.engine,
            params=values,
            provenance=provenance(man, wf, values),
        ),
        allow_empty=wf.training,  # Training liefert die LoRA-Datei (SaveLoRA)
    )


def run_graph(
    inst: ComfyConfig,
    graph: dict,
    dest: Path,
    *,
    stem: str,
    timeout_s: float | None,
    base: RenderResult,
    job_id: int | None = None,
    client_id: str | None = None,
    on_submit: Callable[[str, dict], None] | None = None,
    lost_after_s: float | None = None,
) -> RenderResult:
    """Vom Backend gebauten Graphen ausführen (z. B. Abschnitte eines Videos zusammensetzen)."""
    client = ComfyClient(inst.url, client_id=client_id)
    t0 = time.monotonic()
    prompt_id = client.submit(graph, job_id)
    if on_submit is not None:
        on_submit(prompt_id, graph)
    base.prompt_id = prompt_id
    return collect_graph(
        inst, prompt_id, dest, stem=stem, timeout_s=timeout_s, t0=t0, base=base,
        lost_after_s=lost_after_s,
    )  # fmt: skip


def collect_graph(
    inst: ComfyConfig,
    prompt_id: str,
    dest: Path,
    *,
    stem: str,
    timeout_s: float | None,
    base: RenderResult,
    t0: float | None = None,
    allow_empty: bool = False,
    lost_after_s: float | None = None,
) -> RenderResult:
    """Auf einen eingereichten Graphen warten und seine Ausgaben unter ``dest`` sichern."""
    client = ComfyClient(inst.url)
    start = time.monotonic() if t0 is None else t0
    trace = MemoryTrace(client)
    entry = client.wait(prompt_id, timeout_s, on_poll=trace.sample, lost_after_s=lost_after_s)
    trace.sample()
    dest.mkdir(parents=True, exist_ok=True)
    result = base
    result.memory = trace.summary()
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
    if not result.outputs and not allow_empty:
        raise ComfyError(f"Auftrag {prompt_id} lieferte keine Ausgabedatei.", prompt_id=prompt_id)
    result.duration_s = round(time.monotonic() - start, 1)
    log.info(
        "Auftrag %s fertig: %d Datei(en) in %.1f s, Speicher %s",
        prompt_id,
        len(result.outputs),
        result.duration_s,
        result.memory,
    )
    return result


def instance_of(cfg: Config, man: Manifest, wf: Workflow) -> ComfyConfig:
    """ComfyUI-Instanz, die diesen Workflow ausführt (Engine-Feld ``instance``)."""
    return cfg.instance(man.engines[wf.engine].instance)


def prompt_state(inst: ComfyConfig, prompt_id: str) -> str:
    """Wo steht ein eingereichter Auftrag? ``queued`` (wartet/läuft), ``finished`` (im Verlauf)
    oder ``unknown`` (ComfyUI kennt ihn nicht mehr, z. B. nach eigenem Neustart)."""
    client = ComfyClient(inst.url)
    if client.history(prompt_id) is not None:
        return "finished"
    if any(p == prompt_id for _, _, p in client.queued_jobs()):
        return "queued"
    return "unknown"


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
# Widgets, die das ComfyUI-Frontend zusätzlich anlegt; Listenwerte sendet es als {"__value__": …}
_FRONTEND_WIDGET_TYPES = {"IMAGECOMPARE", "BOUNDING_BOXES"}
# Startwert reiner Anzeige-Widgets, die der Editor nicht speichert (Frontend sendet ihn trotzdem)
_FRONTEND_WIDGET_DEFAULTS = {"IMAGECOMPARE": ("", "")}


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
    """Eingang mit Widget im Editor (Wert in ``widgets_values``) – nicht bei ``forceInput``."""
    opts = _spec_options(spec)
    if opts.get("forceInput"):
        return False
    return (
        isinstance(spec[0], list)
        or spec[0] in _WIDGET_TYPES
        or spec[0] in _FRONTEND_WIDGET_TYPES
        or opts.get("widgetType") in _WIDGET_TYPES
    )


def _widget_value(value: object) -> object:
    """Wie ``graphToPrompt``: Listenwerte von Widgets als ``{"__value__": …}``."""
    return {"__value__": value} if isinstance(value, list) else value


def _default(spec: list) -> object:
    if spec[0] in _FRONTEND_WIDGET_DEFAULTS:
        return list(_FRONTEND_WIDGET_DEFAULTS[spec[0]])
    opts = _spec_options(spec)
    if "default" in opts:
        return opts["default"]
    values = _combo_values(spec)
    return values[0] if values else None


def _is_dynamic_combo(spec: list) -> bool:
    return isinstance(spec[0], str) and spec[0].startswith("COMFY_DYNAMICCOMBO")


def _dynamic_widgets(name: str, spec: list, inputs: dict) -> list:
    """Widget-Werte einer dynamischen Combo wie im ComfyUI-UI-Format: Wert, dann Unterwerte."""
    options = _spec_options(spec).get("options", [])
    value = inputs.get(
        name, _spec_options(spec).get("default", options[0]["key"] if options else None)
    )
    values = [value]
    option = next((o for o in options if o.get("key") == value), {})
    sub_specs = {
        **option.get("inputs", {}).get("required", {}),
        **option.get("inputs", {}).get("optional", {}),
    }
    for sub, sub_spec in sub_specs.items():
        key = f"{name}.{sub}"
        if _is_dynamic_combo(sub_spec):
            values += _dynamic_widgets(key, sub_spec, inputs)
        elif _is_widget(sub_spec):
            values.append(inputs.get(key, _default(sub_spec)))
    return values


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
        for name, sp in required.items():
            dynamic = isinstance(sp[0], str) and sp[0].startswith("COMFY_")  # z. B. AUTOGROW
            if name not in node["inputs"] and not dynamic:
                problems.append(f"{nid} {node['class_type']}: Pflichteingang '{name}' fehlt")
        for name, value in node["inputs"].items():
            base = name.split(".")[0]
            if name not in spec and not (base in spec and _is_dynamic_combo(spec[base])):
                problems.append(f"{nid} {node['class_type']}: unbekannter Eingang '{name}'")
                continue
            if name not in spec:
                continue  # Unterwert einer dynamischen Combo
            if _is_link(value):
                if value[0] not in graph:
                    problems.append(f"{nid}.{name}: Verweis auf fehlenden Node {value[0]}")
                continue
            values = _combo_values(spec[name])
            if values is not None and (nid, name) not in runtime_inputs and value not in values:
                problems.append(f"{nid} {node['class_type']}.{name}: '{value}' nicht verfügbar")
    return problems


_MATCHTYPE = "COMFY_MATCHTYPE_V3"  # Ein-/Ausgang übernimmt den Typ der Verbindung


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
        unknown = {k for k in node["inputs"] if k.split(".")[0] not in spec}
        if unknown:
            raise ComfyError(f"Node {nid}: unbekannte Eingänge {sorted(unknown)}")
        inputs, widgets = [], []
        for name, sp in spec.items():
            value = node["inputs"].get(name)
            if _is_dynamic_combo(sp):
                widgets += _dynamic_widgets(name, sp, node["inputs"])
                continue
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
            elif isinstance(sp[0], str) and sp[0].startswith("COMFY_AUTOGROW"):
                # dynamische Eingangsgruppe: wie ComfyUI-Templates als erster Einzelslot
                tmpl = _spec_options(sp).get("template", {})
                first = (tmpl.get("names") or ["1"])[0]
                slot_type = next(iter(tmpl.get("input", {}).get("required", {}).values()), ["*"])
                inputs.append(
                    {"name": f"{name}.{first}", "type": slot_type[0], "link": None, "shape": 7}
                )
            elif sp[0] == _MATCHTYPE:  # Typvorlage: wie das Frontend die erlaubten Typen
                allowed = _spec_options(sp).get("template", {}).get("allowed_types", "*")
                inputs.append({"name": name, "type": allowed, "link": None})
            else:
                inputs.append({"name": name, "type": sp[0], "link": None})
        outputs = [
            {
                "name": oname,
                "type": "*" if otype == _MATCHTYPE else otype,
                "links": [],
                "slot_index": i,
            }
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


# -------------------------------------------------------------------- Editor-Rückweg

# Reine Anmerkungen ohne Einfluss auf den Rendergraphen.
_NOTE_NODES = {"Note", "MarkdownNote"}


def _take_dynamic(name: str, spec: list, values: list, inputs: dict) -> None:
    """Umkehrung von ``_dynamic_widgets``: Wert und Unterwerte aus der Widget-Liste lesen."""
    value = values.pop(0)
    inputs[name] = value
    option = next((o for o in _spec_options(spec).get("options", []) if o.get("key") == value), {})
    sub_specs = {
        **option.get("inputs", {}).get("required", {}),
        **option.get("inputs", {}).get("optional", {}),
    }
    for sub, sub_spec in sub_specs.items():
        if _is_dynamic_combo(sub_spec):
            _take_dynamic(f"{name}.{sub}", sub_spec, values, inputs)
        elif _is_widget(sub_spec):
            inputs[f"{name}.{sub}"] = values.pop(0)


# Virtuelle Editor-Nodes: werden nicht ausgeführt, nur durchgereicht bzw. als Wert eingesetzt
_VIRTUAL = {"Reroute", "PrimitiveNode"}
_SUBGRAPH_IN, _SUBGRAPH_OUT = -10, -20
_MUTED, _BYPASSED = 2, 4


class _Scope:
    """Ein Graph (Hauptgraph oder Untergraph-Instanz) mit API-ID-Präfix und den Quellen seiner
    Untergraph-Eingänge (``boundary``: Eingang -> ("node", id, slot) | ("value", v) | None)."""

    def __init__(self, graph: dict, prefix: str, boundary: list) -> None:
        self.nodes = {n["id"]: n for n in graph.get("nodes") or []}
        self.links = {}
        self.outputs: dict[int, int] = {}  # Untergraph-Ausgang -> Link zum Ausgangsknoten
        for link in graph.get("links") or []:
            if isinstance(link, dict):
                lid, origin, oslot = link["id"], link["origin_id"], link["origin_slot"]
                target, tslot, typ = link["target_id"], link["target_slot"], link.get("type")
            else:
                lid, origin, oslot, target, tslot = link[:5]
                typ = link[5] if len(link) > 5 else None
            self.links[lid] = (origin, oslot, typ)
            if target == _SUBGRAPH_OUT:
                self.outputs[tslot] = lid
        self.prefix = prefix
        self.boundary = boundary


def ui_to_api(ui: dict, object_info: dict) -> dict:
    """Editor-Workflow (UI-Format) -> API-Graph wie ``graphToPrompt`` des ComfyUI-Frontends.

    Löst Untergraphen auf (innere Nodes als ``Instanz:Node``, hochgereichte Widget-Werte und
    Verbindungen über die Untergraph-Grenzen), setzt Primitive-Node-Werte ein, reicht Reroutes und
    umgangene Nodes (Bypass) durch und lässt stumme Nodes und Anmerkungen weg.
    """
    defs = {sg["id"]: sg for sg in (ui.get("definitions") or {}).get("subgraphs") or []}
    graph: dict[str, dict] = {}

    def resolve(scope: _Scope, link_id: int, trail: frozenset = frozenset()):
        """Quelle eines Links: ("node", api_id, slot), ("value", v) oder None (stumm)."""
        if link_id not in scope.links:
            raise ComfyError(f"Link {link_id} fehlt im Workflow.")
        origin, slot, typ = scope.links[link_id]
        if origin == _SUBGRAPH_IN:
            return scope.boundary[slot]
        node = scope.nodes.get(origin)
        if node is None:
            raise ComfyError(f"Link {link_id} verweist auf fehlenden Node {origin}.")
        key = (scope.prefix, origin)
        if key in trail:
            raise ComfyError(f"Zyklus über Node {origin}.")
        trail = trail | {key}
        if node["type"] == "Reroute":
            upstream = (node.get("inputs") or [{}])[0].get("link")
            return None if upstream is None else resolve(scope, upstream, trail)
        if node["type"] == "PrimitiveNode":
            return ("value", (node.get("widgets_values") or [None])[0])
        mode = node.get("mode", 0)
        if mode == _MUTED:
            return None
        if mode == _BYPASSED:  # Ausgang -> passender Eingang (gleicher Index, sonst gleicher Typ)
            ins = node.get("inputs") or []
            out_type = (node.get("outputs") or [{}] * (slot + 1))[slot].get("type", typ)
            same = ins[slot] if slot < len(ins) and ins[slot].get("type") == out_type else None
            match = same or next((i for i in ins if i.get("type") == out_type), None)
            if match is None or match.get("link") is None:
                return None
            return resolve(scope, match["link"], trail)
        if node["type"] in defs:  # Ausgang einer Untergraph-Instanz: innere Quelle
            inner = instance_scope(scope, node)
            lid = inner.outputs.get(slot)
            return None if lid is None else resolve(inner, lid, trail)
        return ("node", f"{scope.prefix}{origin}", slot)

    def instance_scope(scope: _Scope, inst: dict) -> _Scope:
        """Untergraph-Instanz: Grenzquellen aus äußeren Links bzw. Widget-Werten der Instanz."""
        sub = defs[inst["type"]]
        if (inst.get("properties") or {}).get("proxyWidgets"):
            raise ComfyError(f"Untergraph {inst['id']}: proxyWidgets-Format nicht unterstützt.")
        sockets = {i["name"]: i for i in inst.get("inputs") or []}
        values = list(inst.get("widgets_values") or [])
        boundary = []
        for sin in sub.get("inputs") or []:
            sock = sockets.get(sin["name"])
            is_widget = sock is None or "widget" in sock
            value = values.pop(0) if is_widget and values else None
            if sock is not None and sock.get("link") is not None:
                boundary.append(resolve(scope, sock["link"]))
            else:
                boundary.append(("value", value) if is_widget else None)
        return _Scope(sub, f"{scope.prefix}{inst['id']}:", boundary)

    def emit(scope: _Scope) -> None:
        for nid, node in scope.nodes.items():
            typ = node["type"]
            if typ in _NOTE_NODES or typ in _VIRTUAL or node.get("mode", 0) in (_MUTED, _BYPASSED):
                continue
            if typ in defs:
                emit(instance_scope(scope, node))
                continue
            if not isinstance(node.get("widgets_values", []), list):
                raise ComfyError(f"Node {nid} ({typ}): Widget-Format wird nicht unterstützt.")
            linked = {
                i["name"]: i["link"] for i in node.get("inputs") or [] if i.get("link") is not None
            }
            values = list(node.get("widgets_values") or [])
            inputs: dict = {}

            def put(name: str, link_id: int, into: dict) -> None:
                src = resolve(scope, link_id)
                if src is not None:  # stumme Quelle: Eingang entfällt wie im Frontend
                    into[name] = src[1] if src[0] == "value" else [src[1], src[2]]

            for name, sp in _node_spec(object_info, typ).items():
                if _is_dynamic_combo(sp):
                    _take_dynamic(name, sp, values, inputs)
                    for k, v in linked.items():  # verbundene Unterwerte ersetzen ihr Widget
                        if k.startswith(f"{name}."):
                            put(k, v, inputs)
                elif _is_widget(sp):
                    value = values.pop(0) if values else _default(sp)
                    if name in linked:
                        put(name, linked[name], inputs)
                    else:
                        inputs[name] = _widget_value(value)
                    if _spec_options(sp).get("control_after_generate") and values:
                        values.pop(0)
                elif isinstance(sp[0], str) and sp[0].startswith("COMFY_AUTOGROW"):
                    for k, v in linked.items():
                        if k.startswith(f"{name}."):
                            put(k, v, inputs)
                elif name in linked:
                    put(name, linked[name], inputs)
            api_id = f"{scope.prefix}{nid}"
            graph[api_id] = {"class_type": typ, "inputs": inputs}
            if node.get("title"):
                graph[api_id]["_meta"] = {"title": node["title"]}

    emit(_Scope(ui, "", []))
    return graph


def editor_file(inst: ComfyConfig, key: str) -> Path:
    """Editor-Kopie eines Workflows in der ausführenden Instanz: je Workflow ein eigener Ordner der
    ComfyUI-Seitenleiste, damit ``/?workflows=<key>`` genau diesen Graphen lädt."""
    return inst.folder("user") / "default" / "workflows" / key / f"{key}.json"


def install_editor_copy(cfg: Config, man: Manifest, key: str, *, replace: bool = False) -> Path:
    """Legt die Editor-Kopie aus dem registrierten UI-Export an, falls sie fehlt; vorhandene
    (ggf. bearbeitete, noch nicht übernommene) Kopien bleiben unangetastet, außer ``replace``
    (nach einer Übernahme: Kopie = registrierte Fassung)."""
    target = editor_file(instance_of(cfg, man, man.workflows[key]), key)
    if replace or not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((man.root / "workflows" / man.workflows[key].ui).read_bytes())
    return target


def remove_editor_copy(inst: ComfyConfig, key: str) -> None:
    target = editor_file(inst, key)
    target.unlink(missing_ok=True)
    if target.parent.is_dir() and not any(target.parent.iterdir()):
        target.parent.rmdir()


async def progress_events(url: str, client_id: str) -> AsyncIterator[tuple[str, int, int]]:
    """Fortschritt der unter ``client_id`` eingereichten Aufträge aus ComfyUIs WebSocket:
    liefert (prompt_id, Wert, Maximum); Maximum 0 heißt: Auftrag beendet. Endet, wenn ComfyUI
    die Verbindung schließt. Vorschaubilder (Binärframes) werden ignoriert."""
    import aiohttp

    ws_url = url.replace("http://", "ws://", 1).rstrip("/") + f"/ws?clientId={client_id}"
    async with aiohttp.ClientSession() as session, session.ws_connect(ws_url) as ws:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            event = json.loads(msg.data)
            data = event.get("data") or {}
            kind, prompt_id = event.get("type"), data.get("prompt_id")
            if not prompt_id:
                continue
            if kind == "progress":
                yield prompt_id, int(data.get("value", 0)), int(data.get("max", 0))
            elif kind in ("execution_success", "execution_error", "execution_interrupted") or (
                kind == "executing" and data.get("node") is None
            ):
                yield prompt_id, 0, 0
