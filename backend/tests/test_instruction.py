"""Freie Default-Anweisungen (SP4 Schritt 4): registrierter Workflow ``default_instruction_melody``
deutet eine Nachricht ohne Kurzbefehl; das Backend typisiert streng und führt nur Erlaubtes aus
(Befehl, Workflow, Format/Dauer, Bezug auf Medien dieses Chats); Lauf in ``ai_runs``."""

from __future__ import annotations

import asyncio
import dataclasses
import json

from test_channels import _cloner_setup, cloner_cfg  # noqa: F401  (Fixture)
from test_orders import _finish
from test_server import _run

from darkfluenzer.core import instruction
from darkfluenzer.nodes import llm
from darkfluenzer.web import http as server


def test_parse_and_wish():
    ok, why = instruction.parse({"command": "remix", "prompt": "am Strand",
                                 "options": {"format": "9:16", "duration_s": 0},
                                 "reference": "letztes"})  # fmt: skip
    assert why == "" and ok.command == "remix" and ok.reference == "letztes"
    assert instruction.wish(ok) == "am Strand 9:16"
    assert instruction.parse({"command": "dance"})[1].startswith("Deutung: Befehl")
    assert "reference" in instruction.parse({"command": "clone", "reference": "das da"})[1]
    assert "options" in instruction.parse({"command": "clone", "options": {"duration_s": "5"}})[1]
    none, _ = instruction.parse({"command": "none", "question": "Welches Bild?"})
    assert none.command == "none" and none.question == "Welches Bild?"
    assert instruction.wish(instruction.Instruction("animate", duration_s=5)) == "5s"


class Deuter:
    def __init__(self) -> None:
        self.answers: list[dict] = []
        self.calls: list[dict] = []

    def __call__(self, cfg, man, workflow, values, *, timeout_s, on_submit=None):
        self.calls.append(values)
        answer = self.answers.pop(0)
        return llm.TextResult(
            answer=json.dumps(answer), classification="", system="S", user=values["message"],
            prompt_id="p", wait_s=0, duration_s=0.01, workflow_sha="w", model_sha="m",
        )  # fmt: skip


async def _quiet(cockpit, store, customer_id, before):
    for _ in range(100):
        if len(store.conversation_items(customer_id, 0, 80)[0]) > before:
            await asyncio.sleep(0.05)
            return
        await asyncio.sleep(0.02)


def test_free_instruction_runs_only_what_is_allowed(cloner_cfg, monkeypatch):  # noqa: F811
    deuter = Deuter()
    monkeypatch.setattr(llm, "instruct", deuter)
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        cockpit.cfg = dataclasses.replace(cockpit.cfg, comfyui_ai=cockpit.cfg.comfyui)
        send, photo = _cloner_setup(cfg, store, auto=True)
        # ein früheres Ergebnis im Chat (Rückversand), auf das sich „letztes“ bezieht
        first = send("1", "remix", "1", [photo])
        await cockpit._on_inbound(first)
        order = store.order_by_id(store.db.execute("SELECT max(id) FROM orders").fetchone()[0])
        (job,) = store.stage_jobs(store.stages(order.id)[0].id)
        media = _finish(cfg, store, job["id"])
        await cockpit._cloner_delivery(order.id)
        assert store.recent_returns(first.conversation_id, 5)[0]["media_id"] == media
        cust = first.customer.id

        async def say(update, text):
            before = len(store.conversation_items(cust, 0, 80)[0])
            await cockpit._on_inbound(send(update, text, update))
            await _quiet(cockpit, store, cust, before + 1)

        deuter.answers.append({"command": "style", "prompt": "wärmeres Licht",
                               "reference": "letztes", "options": {}})  # fmt: skip
        orders_before = store.db.execute("SELECT count(*) FROM orders").fetchone()[0]
        await say("2", "mach das letzte Bild wärmer")
        assert store.db.execute("SELECT count(*) FROM orders").fetchone()[0] == orders_before + 1
        assert (
            f"media:{media}" in deuter.calls[-1]["facts"] and "style:" in deuter.calls[-1]["facts"]
        )
        newest = store.order_by_id(store.db.execute("SELECT max(id) FROM orders").fetchone()[0])
        stage = store.stages(newest.id)[0]
        assert stage.params["command"] == "style"
        assert stage.params["values"]["prompt"].endswith("wärmeres Licht")
        run = store.db.execute("SELECT kind, error FROM ai_runs ORDER BY id DESC").fetchone()
        assert tuple(run) == ("instruction", "")
        # Rückfrage
        deuter.answers.append({"command": "none", "question": "Welches Bild meinst du?"})
        await say("3", "mach was Schönes")
        assert store.conversation_items(cust, 0, 80)[0][-1]["text"] == "Welches Bild meinst du?"
        # nicht erlaubt: fremder Workflow, fremder Bezug, Schemafehler
        deuter.answers.append(
            {"command": "remix", "workflow": "gibt_es_nicht", "reference": "letztes"}
        )
        await say("4", "nimm den geheimen Workflow")
        cards = [
            i["text"]
            for i in store.conversation_items(cust, 0, 80)[0]
            if i["direction"] == "system"
        ]
        assert any("Workflow gibt_es_nicht ist nicht registriert" in c for c in cards)
        deuter.answers.append({"command": "remix", "reference": "media:999999"})
        await say("5", "das von gestern")
        cards = [
            i["text"]
            for i in store.conversation_items(cust, 0, 80)[0]
            if i["direction"] == "system"
        ]
        assert any("Bezug media:999999 gehört zu keinem Medium" in c for c in cards)
        deuter.answers.append({"command": "dance"})
        await say("6", "tanz")
        last = store.conversation_items(cust, 0, 80)[0][-1]["text"]
        assert last.startswith("Anweisung nicht verstanden") and "Befehl" in last

    _run(cfg, scenario)
