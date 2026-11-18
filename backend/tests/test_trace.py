"""Rückverfolgung der Default-Kette (SP1 Schritt 1): jede Station mit Befund, die erste
Unterbrechung benannt; nur lesend (schreibgeschützte Verbindung, auch neben dem Server)."""

from __future__ import annotations

import sqlite3

import pytest
from test_channels import _cloner_setup, _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_server import _run

from darkfluenzer.app import main
from darkfluenzer.core import trace
from darkfluenzer.media import models
from darkfluenzer.store.db import DB_NAME
from darkfluenzer.web import http as server


def _steps(result: dict) -> dict[str, bool | None]:
    return {s["step"]: s["ok"] for s in result["steps"]}


def test_trace_names_each_station_and_the_first_break(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg
    found: dict = {}

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        send, photo = _cloner_setup(cfg, store, auto=True)
        ok = send("1", "remix roter Bikini", "1", [photo])
        await cockpit._on_inbound(ok)
        bare = send("2", "clone", "2")  # ohne Referenz: Rückfrage im Chat
        await cockpit._on_inbound(bare)
        stranger = _inbound(store, "3", "42", "clone", "3")  # nicht der Default-Kontakt
        found.update(ok=ok.message_id, bare=bare.message_id, stranger=stranger.message_id)
        man = models.load_manifest(cfg.root)
        db = trace.connect(cfg.local / DB_NAME)
        try:
            found["r_ok"] = trace.trace_message(db, man, ok.message_id)
            found["r_bare"] = trace.trace_message(db, man, bare.message_id)
            found["r_stranger"] = trace.trace_message(db, man, stranger.message_id)
            found["r_order"] = trace.trace_order(db, man, "DF-O-000001")
            with pytest.raises(sqlite3.OperationalError):  # schreibgeschützt
                db.execute("DELETE FROM orders")
        finally:
            db.close()

    _run(cfg, scenario)
    ok = _steps(found["r_ok"])
    for station in ("Nachricht", "Identität", "Default-Zuordnung", "Schalter", "Befehl",
                    "Workflow", "Vorprüfung", "Auftrag", "Stufe 1"):  # fmt: skip
        assert ok[station] is True, station
    assert any(s["step"].startswith("Job ") for s in found["r_ok"]["steps"])
    assert found["r_ok"]["first_break"] == ""  # Jobs warten noch: keine Unterbrechung
    assert found["r_bare"]["first_break"] == "Vorprüfung: Workflow braucht ein Referenzbild"
    bare_answer = next(s for s in found["r_bare"]["steps"] if s["step"] == "Antwort im Chat")
    assert "Referenzbild" in bare_answer["detail"]
    assert found["r_stranger"]["first_break"].startswith("Default-Zuordnung")
    assert found["r_order"]["order"] == "DF-O-000001"
    assert found["r_order"]["message"] == found["ok"]  # über die Ursprungsnachricht


def test_trace_cli_reads_without_server(cfg, monkeypatch, capsys):
    from darkfluenzer.store import Store

    store = Store(cfg.local)
    msg = _inbound(store, "1", "42", "Hallo", "10")
    store.close()
    monkeypatch.setattr("darkfluenzer.app.load", lambda: cfg)
    empty = models.Manifest(cfg.root, 0.0, {}, {}, {}, {}, {})
    monkeypatch.setattr(models, "load_manifest", lambda *_a, **_k: empty)
    assert main(["trace", "--message", str(msg.message_id)]) == 0
    out = capsys.readouterr().out
    assert "✗ Default-Zuordnung" in out and "Erste Unterbrechung: Default-Zuordnung" in out
    assert main(["trace", "--order", "DF-O-999999", "--json"]) == 0
    assert '"first_break": "Auftrag: Auftrag DF-O-999999 unbekannt"' in capsys.readouterr().out
