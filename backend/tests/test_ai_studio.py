"""SP4 Schritt 1 (E19, E26): Sprachworkflow ``clara_chat_melody``.

Die Registrierung prüft Profil- und Kontexteingänge, den festen Ehrlichkeitsblock und die
Verkettung Einstufung → Antwort; ``llm.generate`` liest die Ausgaben getrennt; das KI-Studio
(Befehle 49/50) läuft über echtes HTTP und WebSocket gegen eine Ersatz-ComfyUI 2, die den
eingereichten Graphen tatsächlich auswertet (Textknoten, Verkettungen, zwei Sprachknoten)."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from conftest import free_port
from test_llm import FakeAi
from test_server import _csrf, _frame, _post, _run, _stream_after_catchup

from darkfluenzer.config import project_root
from darkfluenzer.core import persona
from darkfluenzer.media import models, pipeline
from darkfluenzer.nodes import comfy, llm
from darkfluenzer.store import Store
from darkfluenzer.v1 import ai_pb2, comfy_pb2, commands_pb2, influencer_pb2
from darkfluenzer.v1 import stream_pb2 as pb
from darkfluenzer.web import http as server

WF = "clara_chat_melody"
MARK = "EINSTUFUNG"  # Systemprompt des neutralen Laufs beginnt damit (nur in diesem Test)


class GraphAi(FakeAi):
    """Wertet den eingereichten Graphen aus wie ComfyUI 2: Textknoten, StringConcatenate,
    Sprachknoten (schreibt wie LLMSessionChatNode eine Verlaufsdatei nach history_dir) und
    PreviewAny."""

    def __init__(self, port: int) -> None:
        super().__init__(port)
        self.graphs: list[dict] = []

    def run(self, pid: str, graph: dict) -> None:
        self.graphs.append(graph)
        if self.mode == "error":
            error = {"node_id": "60", "node_type": models.SESSION_NODE,
                     "exception_message": "llama.cpp: Modell nicht geladen"}  # fmt: skip
            self.entries[pid] = {"status": {"status_str": "error", "completed": False,
                                            "messages": [["execution_error", error]]}}  # fmt: skip
            return
        values: dict[str, str] = {}

        def ev(nid: str) -> str:
            if nid in values:
                return values[nid]
            node, inputs = graph[nid], graph[nid]["inputs"]

            def arg(key: str) -> str:
                v = inputs[key]
                return ev(str(v[0])) if isinstance(v, list) else v

            kind = node["class_type"]
            if kind == models.TEXT_NODE:
                out = inputs["value"]
            elif kind == "StringConcatenate":
                out = arg("string_a") + inputs["delimiter"] + arg("string_b")
            elif kind == models.SESSION_NODE:
                system, user = arg("system_prompt"), arg("user_text")
                path = Path(inputs["history_dir"]) / f"{inputs['session_id']}.json"
                path.write_text(json.dumps({"turns": [user]}))
                self.written.append(path)
                last = user.strip().splitlines()[-1]
                out = '{"purchase_readiness": 1}' if system.startswith(MARK) else f"Antwort[{last}]"
            elif kind == models.PREVIEW_NODE:
                out = arg("source")
            else:
                raise AssertionError(f"unbekannter Knoten {kind}")
            values[nid] = out
            return out

        outputs = {nid: {"text": [ev(nid)]} for nid, n in graph.items()
                   if n["class_type"] == models.PREVIEW_NODE}  # fmt: skip
        self.entries[pid] = {
            "status": {"status_str": "success", "completed": True, "messages": [
                ["execution_start", {"timestamp": 1000}],
                ["execution_success", {"timestamp": 1900}]]},
            "outputs": outputs,
        }  # fmt: skip


@pytest.fixture
def ai(cfg, tmp_path):
    port = free_port()
    fake = GraphAi(port)
    inst = dataclasses.replace(cfg.comfyui, name="ai", port=port, data_dir=tmp_path / "ai")
    yield dataclasses.replace(cfg, comfyui_ai=inst), fake
    fake.server.shutdown()


def _man() -> models.Manifest:
    return models.load_manifest(project_root())


def _graph(man: models.Manifest) -> tuple[models.Workflow, dict]:
    wf = man.workflows[WF]
    return wf, json.loads((man.root / "workflows" / wf.api).read_text(encoding="utf-8"))


def _problems(man: models.Manifest, wf: models.Workflow, graph: dict) -> list[str]:
    names = models.engine_model_names(man.files, man.engines, man.loras, wf.engine)
    return models.graph_problems(wf, graph, names)


def _relink(graph: dict, old: str, new: str, only: str = "") -> None:
    """Jede Verbindung vom Knoten ``old`` auf ``new`` umhängen (optional nur an ``only``-Knoten)."""
    for node in graph.values():
        if only and node["class_type"] != only:
            continue
        for key, value in node["inputs"].items():
            if value == [old, 0]:
                node["inputs"][key] = [new, 0]


def test_registered_chat_workflow_passes_and_profile_keys_match():
    man = _man()
    wf, graph = _graph(man)
    assert _problems(man, wf, graph) == []
    assert tuple(k for k, _ in persona.PROFILE_BLOCKS) == models.PROFILE_INPUTS
    assert models.honesty_text(man) == wf.text.honesty != ""
    eng = man.engines[wf.engine]
    assert eng.kind == "text" and eng.instance == "ai"
    assert set(persona.model_params(man)) == {
        "max_tokens", "temperature", "top_p", "repeat_penalty", "repeat_last_n", "n_ctx"
    }  # fmt: skip


def test_registration_rejects_changed_detached_honesty_missing_e26_and_unbound_block():
    man = _man()
    wf, graph = _graph(man)
    t = wf.text

    def problems(change) -> str:
        g = copy.deepcopy(graph)
        change(g)
        return " | ".join(_problems(man, wf, g))

    changed = problems(lambda g: g[t.honesty_node]["inputs"].__setitem__("value", "Du bist echt."))
    assert "weicht ab" in changed
    assert "nicht mit dem Systemprompt verbunden" in problems(
        lambda g: _relink(g, t.honesty_node, "1")
    )
    neutral = models._source(graph, t.classification, "source")
    assert "E26" in problems(lambda g: _relink(g, neutral, "20", only="StringConcatenate"))
    strategy = wf.params["strategy"].node
    assert "params.strategy" in problems(lambda g: _relink(g, strategy, "1"))
    persona_node = models._source(graph, t.answer, "source")
    inputs = {"text": [persona_node, 0], "filename_prefix": "x", "format": "txt"}
    saver = {"class_type": "SaveText", "inputs": inputs}
    assert "PreviewAny" in problems(lambda g: g.__setitem__(t.answer, saver))


def test_chat_workflow_never_becomes_a_render_job(tmp_path):
    with pytest.raises(pipeline.PipelineError, match="Sprachworkflow"):
        pipeline.create_render(Store(tmp_path / "local"), _man(), WF, {"message": "x"}, {})


def test_generate_fills_blocks_runs_both_passes_and_reads_outputs(ai):
    cfg, fake = ai
    man = _man()
    wf = man.workflows[WF]
    values = {k: "" for k in models.PROFILE_INPUTS} | {
        "system_prompt": "SYS", "persona": "PERSONA", "classification": f"{MARK}: nur JSON",
        "context": "Kunde: Hi", "message": "Hallo Clara", "temperature": 0.5,
    }  # fmt: skip
    r = llm.generate(cfg, man, WF, values, timeout_s=5)
    assert r.answer == "Antwort[Hallo Clara]"
    assert json.loads(r.classification) == {"purchase_readiness": 1}
    assert r.system.startswith("SYS") and wf.text.honesty in r.system and "PERSONA" in r.system
    assert '{"purchase_readiness": 1}' in r.user and r.user.endswith("Hallo Clara")
    sent = fake.graphs[-1]
    assert sent["60"]["inputs"]["temperature"] == 0.5
    assert sent[wf.params["strategy"].node]["inputs"]["value"] == ""  # leer = Graph-Wert
    raw = (man.root / "workflows" / wf.api).read_bytes()
    assert r.workflow_sha == hashlib.sha256(raw).hexdigest()
    assert r.model_sha == man.files["melody1437_q6k"].sha256
    assert fake.written and not any(p.exists() for p in fake.written)  # SPEC-018
    with pytest.raises(comfy.ComfyError, match="Pflichtparameter"):
        llm.generate(cfg, man, WF, {"message": "  "}, timeout_s=5)
    with pytest.raises(llm.LlmError, match="kein registrierter Sprachworkflow"):
        llm.generate(cfg, man, "lustify_sdxl_t2i", {}, timeout_s=5)
    assert llm.parse_classification('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_classification("kein JSON {") is None


def test_studio_chat_over_http_records_runs_events_receipts_and_session(ai):
    cfg, fake = ai

    async def scenario(client, app, origin):
        store = app[server.COCKPIT_KEY].store
        clara = store.save_influencer(
            0, 0, "Clara", None, "", "KI-Hinweis",
            [{"product": "Foto", "price_cents": 2000, "hd_surcharge_cents": 500}],
        )  # fmt: skip
        store.save_persona_version(
            clara, {"system_prompt": "SYS", "classification": f"{MARK}: nur JSON"},
            {"temperature": 0.6}, "Test", activate=True,
        )  # fmt: skip
        csrf = await _csrf(client)
        ws = await _stream_after_catchup(client, app, origin, pb.TOPIC_AI_RESULT)

        async def send(**kw) -> commands_pb2.CommandResponse:
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body)

        async def chat(text: str, **kw) -> commands_pb2.CommandResponse:
            msg = commands_pb2.StudioChat(influencer_id=clara, text=text, **kw)
            return await send(studio_chat=msg)

        async def result() -> ai_pb2.AiRun:
            while True:
                frame = await _frame(ws)
                if frame.WhichOneof("msg") == "event" and frame.event.topic == pb.TOPIC_AI_RESULT:
                    return ai_pb2.AiResult.FromString(frame.event.payload).run

        first = await chat("Hallo")
        assert first.status == commands_pb2.COMMAND_STATUS_ACCEPTED
        run = await result()
        assert run.request_id == first.request_id and run.answer == "Antwort[Hallo]"
        assert run.classification_valid and run.persona_version == 1 and run.session == 1
        assert run.error == "" and run.duration_s == pytest.approx(0.9)
        assert "Foto: 20,00 €, HD-Aufschlag 5,00 €" in run.system_prompt  # Geschäftsfakten
        assert store.command(first.request_id)["status"] == "completed"

        await chat("Und jetzt?")
        second = await result()
        assert "Kunde: Hallo\nClara: Antwort[Hallo]" in second.user_text  # Verlauf der Sitzung
        assert fake.graphs[-1]["60"]["inputs"]["temperature"] == 0.6  # Parameter der Version

        fresh = commands_pb2.StudioSessionReset(influencer_id=clara)
        reset = await send(studio_session_reset=fresh)
        assert reset.status == commands_pb2.COMMAND_STATUS_ACCEPTED
        await chat("Neu")
        third = await result()
        assert third.session == 2 and "Kunde: Hallo" not in third.user_text
        state = influencer_pb2.Influencers.FromString(app[server.COCKPIT_KEY]._influencers())
        assert state.influencers[0].studio_session == 2  # STATE 9 nennt die laufende Sitzung

        fake.mode = "error"
        bad = await chat("Fehler")
        failed = await result()
        assert "Modell nicht geladen" in failed.error
        assert store.command(bad.request_id)["status"] == "failed"

        assert "Nachricht fehlt" in (await chat("  ")).detail
        assert "Profilversion" in (await chat("x", version=9)).detail
        unknown = commands_pb2.StudioChat(influencer_id=999, text="x")
        assert "unbekannt" in (await send(studio_chat=unknown)).detail
        rows = store.db.execute("SELECT kind, error FROM ai_runs ORDER BY id").fetchall()
        assert [r["kind"] for r in rows] == ["studio"] * 4 and bool(rows[-1]["error"])
        assert fake.written and not any(p.exists() for p in fake.written)  # SPEC-018

    _run(cfg, scenario)


def test_keep_loaded_ai_instance_is_never_freed_by_admission(ai, monkeypatch):
    """BUG-085: eine mit keep_loaded markierte KI-Instanz entlädt die Zulassung nie; ohne die
    Markierung wird sie wie bisher für einen Medienjob entladen."""
    base, _ = ai
    for keep, freed in ((True, False), (False, True)):
        inst = dataclasses.replace(base.comfyui_ai, keep_loaded=keep)
        cfg = dataclasses.replace(base, comfyui_ai=inst)
        calls: list[str] = []

        async def scenario(client, app, origin, calls=calls, freed=freed):
            cockpit = app[server.COCKPIT_KEY]
            lane, other = cockpit.lanes["media"], cockpit.lanes["ai"]
            other.engine = "melody_chat"
            monkeypatch.setattr(cockpit, "_need_gb", lambda engine: 100.0)
            monkeypatch.setattr(cockpit, "_measure", lambda: {"ram_free": 1 * 2**30})
            monkeypatch.setattr(cockpit.store, "job", lambda job_id: {"status": "queued"})
            monkeypatch.setattr(comfy.ComfyClient, "free", lambda self: calls.append("free"))
            assert await cockpit._admit(lane, 5, "lustify_sdxl") is True
            assert bool(calls) is freed and (other.engine == "") is freed

        _run(cfg, scenario)


def test_warmup_once_per_instance_start_marks_engine_and_status(ai):
    """BUG-061: nach dem Start der KI-Instanz ein Aufwärmlauf (ai_runs „warmup“), danach gilt Melody
    als geladen; derselbe Start wärmt nicht erneut, ein neuer Start schon. STATE 11 nennt Engine,
    Aufwärmzeit und die letzten Läufe; die Warteschlange ordnet einen laufenden Sprachlauf zu."""
    cfg, fake = ai
    cfg = dataclasses.replace(cfg, server=dataclasses.replace(cfg.server, observe_s=60))

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        lane = cockpit.lanes["ai"]

        async def settle() -> None:
            for task in list(cockpit._tasks):
                await task

        healthy = {"state": "running", "health": {"device": "mps"}, "instance_id": "a"}
        lane.status = healthy | {"started_at": "t1"}
        await cockpit.maybe_warmup()
        await settle()
        await cockpit.maybe_warmup()  # gleicher Start: kein zweiter Lauf
        await settle()
        rows = cockpit.store.db.execute("SELECT kind, error FROM ai_runs").fetchall()
        assert [(r["kind"], r["error"]) for r in rows] == [("warmup", "")]
        assert lane.engine == "melody_chat"
        status = ai_pb2.AiStatus.FromString(cockpit._ai_status())
        assert status.configured and status.engine.startswith("Melody1437")
        assert status.warmup_s > 0 and status.warmup_error == "" and not status.keep_loaded
        assert [r.kind for r in status.recent] == ["warmup"] and status.running == 0
        lane.status = {"state": "stopped"}
        await cockpit.maybe_warmup()  # gestoppt: Merker zurück
        lane.status = healthy | {"started_at": "t2"}
        await cockpit.maybe_warmup()
        await settle()
        assert cockpit.store.db.execute("SELECT count(*) FROM ai_runs").fetchone()[0] == 2

        cockpit._llm_runs["p1"] = "Clara · Chat (Melody)"
        lane.queue = [(0, True, "p1"), (0, False, "fremd")]
        jobs = comfy_pb2.JobsActive.FromString(cockpit._jobs_active()).jobs
        assert [(j.origin, j.workflow) for j in jobs] == [
            ("llm", "Clara · Chat (Melody)"),
            ("", ""),
        ]
        cockpit._llm_runs.clear()

    _run(cfg, scenario)


def test_comfy_start_without_instance_starts_both(monkeypatch, cfg):
    """BUG-061: ``comfy start`` (Starter) startet jede konfigurierte Instanz; scheitert eine, wird
    die andere trotzdem gestartet und der Fehler danach gemeldet."""
    from darkfluenzer import app as cli
    from darkfluenzer.nodes import local

    started: list[str] = []

    class Node:
        def __init__(self, inst):
            self.inst = inst

        def start(self):
            started.append(self.inst.name)
            if self.inst.name == fail:
                raise local.StartFailed("kaputt")
            return {"result": "started", "url": self.inst.url}

    ai_inst = dataclasses.replace(cfg.comfyui, name="ai", port=free_port())
    both = dataclasses.replace(cfg, comfyui_ai=ai_inst)
    monkeypatch.setattr(cli, "node_for", lambda c, inst: Node(inst))
    fail = ""
    payload, code = cli._comfy_start_all(both)
    assert code == 0 and started == ["media", "ai"] and set(payload["instances"]) == {"media", "ai"}
    started.clear()
    fail = "media"
    with pytest.raises(local.StartFailed) as err:
        cli._comfy_start_all(both)
    assert (
        started == ["media", "ai"] and err.value.details["instances"]["ai"]["result"] == "started"
    )
