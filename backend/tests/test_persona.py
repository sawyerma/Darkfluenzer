"""SP4 Schritt 2: Promptprofile je Influencerin – unveränderliche Versionen, aktivieren und
zurücksetzen ohne Neustart, Migration des bisherigen Persona-Texts, Befehle 35 (additiv) und 68."""

from __future__ import annotations

import dataclasses
import sqlite3
import uuid

import pytest
from test_server import _csrf, _post, _run

from darkfluenzer.core import persona
from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import commands_pb2, influencer_pb2
from darkfluenzer.web import http as server


def test_migration_26_turns_the_old_persona_into_version_1(tmp_path, monkeypatch):
    from darkfluenzer.store import db as store_db

    local = tmp_path / "local"
    monkeypatch.setattr(store_db, "SCHEMA_VERSION", 25)
    old = Store(local)
    old.save_influencer(0, 0, "Clara", None, "warm, direkt", "", [])
    old.save_influencer(0, 0, "Lucy", None, "", "", [])
    old.close()
    monkeypatch.undo()
    s = Store(local)
    try:
        assert list(local.glob("darkfluenzer.sqlite3.bak-*-vor-migration26"))
        clara, lucy = s.influencers()
        (v1,) = s.persona_versions(clara["id"])
        assert (v1["version"], v1["blocks"]) == (1, {"persona": "warm, direkt"})
        assert s.active_persona(clara["id"])["version"] == 1
        assert s.persona_versions(lucy["id"]) == [] and s.active_persona(lucy["id"]) is None
    finally:
        s.close()


def test_versions_are_immutable_and_an_older_one_can_be_reactivated(tmp_path):
    s = Store(tmp_path)
    try:
        fid = s.save_influencer(0, 0, "Clara", None, "", "", [])
        assert s.save_persona_version(
            fid, {"persona": "A", "strategy": " "}, {}, "", activate=True
        ) == (1, True)
        assert s.persona_versions(fid)[0]["blocks"] == {"persona": "A"}  # leere Blöcke entfallen
        assert s.save_persona_version(fid, {"persona": "A"}, {}, "gleich", activate=False) == (
            1,
            False,
        )
        assert s.save_persona_version(fid, {"persona": "B"}, {}, "neu", activate=False) == (2, True)
        assert s.active_persona(fid)["version"] == 1  # gespeichert, nicht aktiviert
        rev = s.influencers()[0]["revision"]
        assert s.activate_persona_version(fid, 2) is True
        clara = s.influencers()[0]
        assert clara["persona"] == "B" and clara["revision"] == rev + 1  # sichtbarer Text geändert
        assert s.activate_persona_version(fid, 2) is False  # schon aktiv
        assert s.activate_persona_version(fid, 1) is True  # zurücksetzen
        assert s.active_persona(fid)["blocks"] == {"persona": "A"}
        with pytest.raises(StoreError, match="gibt es nicht"):
            s.activate_persona_version(fid, 9)
        with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
            s.db.execute("UPDATE persona_versions SET note = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
            s.db.execute("DELETE FROM persona_versions")
        other = s.save_influencer(0, 0, "Lucy", None, "", "", [])
        assert s.persona_versions(other) == []  # Profile je Influencerin getrennt
    finally:
        s.close()


def test_draft_check_knows_blocks_and_takes_model_params_only_from_a_text_workflow(cfg):
    from darkfluenzer.media import models

    shutil = __import__("shutil")
    from darkfluenzer.config import project_root

    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    man = models.load_manifest(cfg.root)
    assert persona.check_draft(man, {"persona": "x", "examples": "y"}, {}) == ""
    assert "Unbekannter Profilblock: foo" in persona.check_draft(man, {"foo": "x"}, {})
    # SP4 Schritt 1: Modellparameter aus dem registrierten Sprachworkflow, nur in dessen Grenzen
    assert persona.check_draft(man, {}, {"temperature": 0.7, "max_tokens": 300}) == ""
    assert "außerhalb" in persona.check_draft(man, {}, {"temperature": 3.0})
    assert "gibt es im Sprachworkflow nicht" in persona.check_draft(man, {}, {"top_k": 40})
    without = dataclasses.replace(
        man, workflows={k: w for k, w in man.workflows.items() if w.text is None}
    )
    assert "registriertem Sprachworkflow" in persona.check_draft(without, {}, {"temperature": 0.7})
    assert [k for k, _ in persona.PROFILE_BLOCKS][:2] == ["system_prompt", "persona"]


def test_profile_commands_save_activate_and_reset(cfg):
    """Befehl 35 mit Profilentwurf und Befehl 68: Version anlegen, aktivieren, zurücksetzen;
    STATE 9 mit Blockliste, Versionen und aktiver Version."""

    async def scenario(client, app, origin):
        csrf = await _csrf(client)
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store

        async def send(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        def update(fid=0, **kw):
            rev = store.influencers()[0]["revision"] if fid else 0
            return commands_pb2.InfluencerUpdate(
                influencer_id=fid, revision=rev, name="Clara", **kw
            )

        assert await send(influencer_update=update(persona="warm")) == ""
        fid = store.influencers()[0]["id"]
        assert store.active_persona(fid)["blocks"] == {"persona": "warm"}
        bad = commands_pb2.ProfileDraft(blocks={"foo": "x"})
        assert "Unbekannter Profilblock" in await send(influencer_update=update(fid, profile=bad))
        params = commands_pb2.ProfileDraft(blocks={"persona": "warm"}, params={"temperature": 3.0})
        assert "außerhalb" in await send(influencer_update=update(fid, profile=params))
        draft = commands_pb2.ProfileDraft(
            blocks={"system_prompt": "Du bist Clara.", "persona": "warm, frech"}, note="frecher"
        )
        assert await send(influencer_update=update(fid, persona="warm", profile=draft)) == ""
        assert store.active_persona(fid)["version"] == 1  # gespeichert, noch nicht aktiv
        activate = commands_pb2.PromptProfileActivate(influencer_id=fid, version=2)
        assert await send(prompt_profile_activate=activate) == ""
        state = influencer_pb2.Influencers.FromString(cockpit._influencers())
        (clara,) = state.influencers
        assert clara.persona_active == 2 and clara.persona == "warm, frech"
        assert [v.version for v in clara.persona_versions] == [1, 2]
        assert clara.persona_versions[1].note == "frecher"
        assert [b.key for b in state.profile_blocks] == [k for k, _ in persona.PROFILE_BLOCKS]
        back = commands_pb2.PromptProfileActivate(influencer_id=fid, version=1)
        assert await send(prompt_profile_activate=back) == ""
        assert store.active_persona(fid)["version"] == 1
        missing = commands_pb2.PromptProfileActivate(influencer_id=fid, version=7)
        assert "gibt es nicht" in await send(prompt_profile_activate=missing)

    _run(cfg, scenario)
