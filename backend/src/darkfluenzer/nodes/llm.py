"""Sprach-KI über ComfyUI 2 (SP4 Schritt 1, E19): Graph einreichen, Textausgaben lesen.

SPEC-018 (Regel 12 e): Gesprächsdaten liegen nur in SQLite. Der Knoten ``LLMSessionChatNode``
schreibt je Sitzung eine Verlaufsdatei (auch mit ``reset_session``). Deshalb bekommt jeder Lauf
einen eigenen, isolierten Sitzungsordner unter ``<KI-Instanz>/temp/df_llm_sessions/<id>``:

- jeder Sitzungsknoten des Graphen schreibt nur dorthin (``history_dir``), mit eigener
  ``session_id``, ``reset_session``, ``max_turns`` 0 und ohne persistenten Cache – der Kontext kommt
  allein als Eingang aus SQLite;
- der Lauf hält eine ``flock``-Sperre auf ``.active`` im Ordner (prozessübergreifend, bei einem
  Absturz frei) und löscht den Ordner im ``finally`` – auch bei Fehler, Zeitüberschreitung und
  Abbruch;
- ``sweep`` entfernt jeden Sitzungsordner ohne gehaltene Sperre (verwaist nach Absturz oder durch
  spätes Schreiben eines abgebrochenen Laufs) und den Standardordner des Knotens; er läuft beim
  Start des Cockpits, nach jedem Lauf und – nach einem Abbruch – sobald ComfyUI den Auftrag nicht
  mehr ausführt (llama.cpp generiert nach dem Interrupt zu Ende, der Knoten legt den gelöschten
  Ordner dann neu an; echter Lauf 18.11.).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..media.models import Manifest
from . import comfy
from .comfy import ComfyClient, ComfyError

log = logging.getLogger("darkfluenzer.llm")

SESSION_NODE = "LLMSessionChatNode"
NODE_DEFAULT_DIR = "llm_session_sessions"  # Standardordner des Knotens unter output/
ROOT_NAME = "df_llm_sessions"
LOCK_NAME = ".active"
REMOVE_TRIES = 5
LATE_POLL_S = 0.5  # Abfrageabstand, bis ComfyUI einen abgebrochenen Auftrag nicht mehr ausführt


class LlmError(Exception):
    pass


@dataclass
class RunResult:
    prompt_id: str
    texts: dict[str, str]  # Ausgabeknoten -> Text (PreviewAny)
    wait_s: float  # Einreichen bis Ausführungsbeginn (Warteschlange)
    duration_s: float  # Ausführung
    graph: dict = field(default_factory=dict)  # eingereichter Graph (ohne Sitzungsordner)


def session_root(cfg: Config) -> Path:
    return cfg.instance("ai").folder("temp") / ROOT_NAME


def isolate_sessions(graph: dict, run_dir: Path) -> dict:
    """Bindet jeden Sitzungsknoten an den Ordner dieses Laufs; kein Verlauf im Knoten."""
    out = {}
    for nid, node in graph.items():
        if node.get("class_type") == SESSION_NODE:
            node = {**node, "inputs": {
                **node.get("inputs", {}),
                "history_dir": str(run_dir), "session_id": f"df-{uuid.uuid4().hex}",
                "reset_session": True, "persistent_cache": "off", "max_turns": 0,
                "summarize_old_history": False,
            }}  # fmt: skip
        out[nid] = node
    return out


def _remove(path: Path) -> bool:
    """Ordner vollständig entfernen; wiederholt, falls der Knoten noch schreibt."""
    for attempt in range(REMOVE_TRIES):
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return True
        except OSError as exc:
            if attempt == REMOVE_TRIES - 1:
                log.error("SPEC-018: Sitzungsordner %s nicht entfernt (%s)", path.name, exc)
                return False
            time.sleep(0.1 * (attempt + 1))
            continue
        if not path.exists():
            return True
    return not path.exists()


@contextlib.contextmanager
def session_dir(cfg: Config) -> Iterator[Path]:
    """Isolierter Sitzungsordner eines Laufs; nach dem Lauf immer gelöscht."""
    run = session_root(cfg) / uuid.uuid4().hex
    run.mkdir(parents=True, mode=0o700)
    fd = os.open(run / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield run
    finally:
        os.close(fd)  # gibt die Sperre frei
        _remove(run)
        sweep(cfg)


def _held(lock: Path) -> bool:
    """Gehört der Ordner zu einem laufenden Lauf (Sperre gehalten, auch von einem anderen
    Prozess)? Ohne Sperrdatei: nein."""
    try:
        fd = os.open(lock, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def sweep(cfg: Config) -> int:
    """Entfernt verwaiste Sitzungsordner und den Standardordner des Knotens (SPEC-018); liefert
    die Zahl der entfernten Ordner. Inhalte werden nie protokolliert."""
    removed = 0
    root = session_root(cfg)
    for run in sorted(root.iterdir()) if root.is_dir() else []:
        if run.is_dir() and not _held(run / LOCK_NAME) and _remove(run):
            removed += 1
    default = cfg.instance("ai").folder("output") / NODE_DEFAULT_DIR
    if default.exists() and _remove(default):
        removed += 1
    if removed:
        log.info("SPEC-018: %d verwaiste Sitzungsordner entfernt", removed)
    return removed


def sweep_when_done(
    cfg: Config, client: ComfyClient, prompt_id: str, limit_s: float
) -> threading.Thread:
    """Nach einem Abbruch: im Hintergrund warten, bis ComfyUI den Auftrag nicht mehr in der
    Warteschlange führt (höchstens ``limit_s``), dann aufräumen – späte Schreibzugriffe des Knotens
    bleiben so nicht bis zum nächsten Lauf liegen."""

    def wait_and_sweep() -> None:
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            try:
                if not client._queued(prompt_id):
                    break
            except ComfyError:
                pass  # nicht erreichbar: beim Start räumt der Sweep auf
            time.sleep(LATE_POLL_S)
        sweep(cfg)

    thread = threading.Thread(target=wait_and_sweep, name=f"llm-sweep-{prompt_id}", daemon=True)
    thread.start()
    return thread


def _texts(entry: dict) -> dict[str, str]:
    out = {}
    for nid, node_out in (entry.get("outputs") or {}).items():
        text = node_out.get("text")
        if isinstance(text, list) and text and isinstance(text[0], str):
            out[str(nid)] = text[0]
    return out


def _timing(entry: dict, submitted: float) -> tuple[float, float]:
    """(Wartezeit, Ausführungsdauer) aus den Statusmeldungen der Historie (ms-Zeitstempel)."""
    marks = {m[0]: m[1].get("timestamp") for m in (entry.get("status") or {}).get("messages", [])
             if isinstance(m, list) and len(m) == 2 and isinstance(m[1], dict)}  # fmt: skip
    start, end = marks.get("execution_start"), marks.get("execution_success")
    if not start or not end:
        return 0.0, 0.0
    return max(0.0, start / 1000 - submitted), max(0.0, (end - start) / 1000)


def run_graph(
    cfg: Config,
    graph: dict,
    *,
    timeout_s: float,
    client_id: str = "darkfluenzer-llm",
    on_submit: Callable[[str], None] | None = None,
) -> RunResult:
    """Graph auf ComfyUI 2 ausführen und die Textausgaben lesen – mit isoliertem Sitzungsordner.
    Kein Job, keine Herkunftsdatei, kein Start der Instanz je Nachricht (BUG-095, 098)."""
    inst = cfg.instance("ai")
    client = ComfyClient(inst.url, client_id=client_id, timeout=cfg.server.timeout_s)
    if not client.ready():
        raise LlmError("KI-Instanz (ComfyUI 2) ist nicht bereit.")
    with session_dir(cfg) as run:
        submitted = time.time()
        prompt_id = client.submit(isolate_sessions(graph, run))
        if on_submit is not None:  # Warteschlange und KI-Status ordnen den Lauf zu
            on_submit(prompt_id)
        try:
            entry = client.wait(prompt_id, timeout_s=timeout_s, poll_s=0.2)
        except BaseException:  # Fehler, Zeitüberschreitung, Abbruch des Wartenden
            with contextlib.suppress(ComfyError):
                client.cancel(prompt_id)  # nichts läuft nach dem Abbruch weiter
            sweep_when_done(cfg, client, prompt_id, cfg.server.timeout_s * 20)
            raise
    wait_s, duration_s = _timing(entry, submitted)
    return RunResult(prompt_id, _texts(entry), round(wait_s, 3), round(duration_s, 3), graph)


@dataclass
class TextResult:
    """Ergebnis eines Sprachworkflows: Antwort, Einstufung (E26), zusammengesetzte Prompts (Nachweis
    je Lauf) und Messwerte; Workflow- und Modellversion für ``ai_runs``."""

    answer: str
    classification: str
    system: str
    user: str
    prompt_id: str
    wait_s: float
    duration_s: float
    workflow_sha: str
    model_sha: str


def parse_classification(text: str) -> dict | None:
    """Einstufung als JSON-Objekt (Schema im Profil, SP4 Schritt 4); technische Entnahme des ersten
    Objekts aus dem Text, keine Sprachdeutung. ``None``, wenn kein gültiges Objekt vorliegt."""
    start = text.find("{")
    while start != -1:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            start = text.find("{", start + 1)
            continue
        return value if isinstance(value, dict) else None
    return None


def generate(
    cfg: Config,
    man: Manifest,
    workflow: str,
    values: dict,
    *,
    timeout_s: float,
    on_submit: Callable[[str], None] | None = None,
) -> TextResult:
    """``llm.generate(workflow, werte)`` (SP4 Schritt 1): registrierten Sprachworkflow mit den
    Werten füllen (Typen und Grenzen prüft die Registry), auf ComfyUI 2 ausführen und die
    Ausgabeknoten getrennt lesen. Kein Job, keine Herkunftsdatei (BUG-095, 098)."""
    wf = man.workflows.get(workflow)
    if wf is None or wf.text is None:
        raise LlmError(f"'{workflow}' ist kein registrierter Sprachworkflow.")
    if not wf.enabled or wf.status == "GESPERRT":
        raise LlmError(f"{wf.title} ist deaktiviert oder gesperrt.")
    raw = (man.root / "workflows" / wf.api).read_bytes()
    # leerer Block = nicht gesetzt: der Textknoten behält den (leeren) Wert des Graphen
    given = {k: v for k, v in values.items() if not (isinstance(v, str) and not v.strip())}
    graph = comfy.apply_params(json.loads(raw), wf, given)
    result = run_graph(cfg, graph, timeout_s=timeout_s, on_submit=on_submit)
    t = wf.text
    model = man.engines[wf.engine].files
    return TextResult(
        answer=result.texts.get(t.answer, ""),
        classification=result.texts.get(t.classification, ""),
        system=result.texts.get(t.system, ""),
        user=result.texts.get(t.user, ""),
        prompt_id=result.prompt_id,
        wait_s=result.wait_s,
        duration_s=result.duration_s,
        workflow_sha=hashlib.sha256(raw).hexdigest(),
        model_sha=",".join(man.files[f].sha256 for f in model),
    )


def instruct(
    cfg: Config,
    man: Manifest,
    workflow: str,
    values: dict,
    *,
    timeout_s: float,
    on_submit: Callable[[str], None] | None = None,
) -> TextResult:
    """Freie Default-Anweisung deuten (SP4 Schritt 4): registrierter Anweisungs-Workflow auf
    ComfyUI 2; ``answer`` ist das Ergebnis-JSON (Prüfung und Ausführung im Backend)."""
    wf = man.workflows.get(workflow)
    if wf is None or wf.instruction is None:
        raise LlmError(f"'{workflow}' ist kein registrierter Anweisungs-Workflow.")
    if not wf.enabled or wf.status == "GESPERRT":
        raise LlmError(f"{wf.title} ist deaktiviert oder gesperrt.")
    raw = (man.root / "workflows" / wf.api).read_bytes()
    given = {k: v for k, v in values.items() if not (isinstance(v, str) and not v.strip())}
    graph = comfy.apply_params(json.loads(raw), wf, given)
    result = run_graph(cfg, graph, timeout_s=timeout_s, on_submit=on_submit)
    t = wf.instruction
    model = man.engines[wf.engine].files
    return TextResult(
        answer=result.texts.get(t.answer, ""),
        classification="",
        system=result.texts.get(t.system, ""),
        user=result.texts.get(t.user, ""),
        prompt_id=result.prompt_id,
        wait_s=result.wait_s,
        duration_s=result.duration_s,
        workflow_sha=hashlib.sha256(raw).hexdigest(),
        model_sha=",".join(man.files[f].sha256 for f in model),
    )
