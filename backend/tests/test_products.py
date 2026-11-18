"""Produkte (SP5 Schritt 1): feste ID je Position, Art, Workflow (Video mit Animation), Kandidaten,
Höchstlänge, Zusatzleistungen; entfernte Positionen bleiben; Zahlungswege und Gültigkeit an der
Influencerin; angeboten wird nur Lieferbares (Gates §9.1, Inhaltsstufe, Produktion, aktive LoRA)."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from test_channels import cloner_cfg  # noqa: F401  (Fixture)
from test_server import _csrf, _post, _run

from darkfluenzer.media import models
from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import commands_pb2, influencer_pb2
from darkfluenzer.web import http as server


def test_products_keep_their_id_and_removed_ones_stay(tmp_path):
    store = Store(tmp_path / "local")
    fid = store.save_influencer(0, 0, "Clara", None, "", "", [
        {"product": "Foto", "price_cents": 2000, "hd_surcharge_cents": 500},
        {"product": "Video", "price_cents": 6000, "hd_surcharge_cents": 0, "kind": "video",
         "workflow": "lustify_sdxl_t2i", "finish_workflow": "ltx25_i2v", "max_duration_s": 8},
    ])  # fmt: skip
    foto, video = store.influencers()[0]["prices"]
    assert video["kind"] == "video" and video["max_duration_s"] == 8
    store.save_influencer(fid, 0, "Clara", None, "", "", [
        {"id": video["id"], "product": "Clip", "price_cents": 6500, "hd_surcharge_cents": 0,
         "kind": "video", "max_duration_s": 5},
        {"product": "Set", "price_cents": 3000, "hd_surcharge_cents": 0, "candidates": 3},
    ])  # fmt: skip
    clip, new = store.influencers()[0]["prices"]
    assert clip["id"] == video["id"] and clip["product"] == "Clip"  # ID bleibt, Position 0
    assert new["id"] not in (foto["id"], video["id"]) and new["candidates"] == 3
    assert store.product(foto["id"])["status"] == "removed"  # entfernt, nicht gelöscht
    with pytest.raises(StoreError, match="gehört nicht"):
        store.save_influencer(fid, 1, "Clara", None, "", "", [
            {"id": 999, "product": "X", "price_cents": 1, "hd_surcharge_cents": 0}])  # fmt: skip
    store.set_influencer_sales(fid, ["amazon", "btc"], 45)
    row = store.influencers()[0]
    assert row["payment_ways"] == ["amazon", "btc"] and row["offer_valid_min"] == 45
    store.close()


def test_deliverability(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        figure = {"id": 1, "character_id": 1}

        def problems(**kw):
            base = {"product": "Foto", "kind": "image", "workflow": "lustify_sdxl_refine",
                    "finish_workflow": "", "max_duration_s": 0}  # fmt: skip
            return cockpit._product_problems(figure, base | kw, test=kw.pop("_test", False))

        assert "Workflow fehlt" in problems(workflow="")
        assert any("nicht registriert" in p for p in problems(workflow="gibts_nicht"))
        strict = problems()
        assert any("nicht für Produktion" in p for p in strict)  # Qualifikation steht aus
        assert any("Charakter-LoRA" in p for p in strict)  # E14
        assert "Video: Höchstlänge fehlt" in problems(kind="video", finish_workflow="ltx25_i2v")
        # Produktion freigegeben und aktive LoRA der Figur: lieferbar
        man = cockpit.manifest
        eng = man.engines["lustify_sdxl"]
        cockpit.manifest = dataclasses.replace(
            man,
            engines={**man.engines, "lustify_sdxl": dataclasses.replace(eng, usage="production")},
        )
        slug = store.character(1)["slug"]
        lora = models.Lora(
            key="figur_sdxl", target=f"loras/characters/{slug}/figur_sdxl.safetensors", size=1,
            sha256="c" * 64, base_engine="lustify_sdxl", base_file=eng.files[0], dataset="ds",
            trigger="dfchar", steps=10, rank=16, learning_rate=1e-4, strength=0.8,
            status="OFFEN", created_at="t", trainer="t", character=slug,
        )  # fmt: skip
        registered = models.register_lora(cfg.root, lora)
        cockpit.manifest = dataclasses.replace(cockpit.manifest, loras=registered.loras)
        store.set_active_lora(1, "sdxl", "figur_sdxl")
        assert problems() == ["LUSTIFY · Verfeinern: Inhaltsstufe nicht standard"]  # Regel 13
        wf = cockpit.manifest.workflows["lustify_sdxl_refine"]
        cockpit.manifest = dataclasses.replace(
            cockpit.manifest,
            workflows={**cockpit.manifest.workflows,
                       "lustify_sdxl_refine": dataclasses.replace(wf, content="standard")},
        )  # fmt: skip
        assert problems() == []  # lieferbar

    _run(cfg, scenario)


def test_influencer_update_products_and_sales(cloner_cfg):  # noqa: F811
    cfg = cloner_cfg

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        csrf = await _csrf(client)

        async def send(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        item = influencer_pb2.PriceItem
        upd = commands_pb2.InfluencerUpdate(
            name="Clara", prices=[item(product="Foto", price_cents=2000, kind="image",
                                       workflow="lustify_sdxl_refine", candidates=2)],
            payment_ways=["amazon", "btc"], offer_valid_min=30,
        )  # fmt: skip
        assert await send(influencer_update=upd) == ""
        state = influencer_pb2.Influencers.FromString(cockpit._influencers()).influencers[0]
        (foto,) = state.prices
        assert foto.id and foto.workflow == "lustify_sdxl_refine" and foto.candidates == 2
        assert not foto.deliverable and any("Produktion" in p for p in foto.problems)
        assert list(state.payment_ways) == ["amazon", "btc"] and state.offer_valid_min == 30
        assert list(state.payment_ways_available) == ["amazon"]  # ohne Wallet nur Gutschein
        bad = commands_pb2.InfluencerUpdate(
            influencer_id=1, revision=0, name="Clara",
            prices=[item(product="Foto", price_cents=2000, kind="gif")],
        )  # fmt: skip
        assert "Art nur Bild oder Video" in await send(influencer_update=bad)
        bad.prices[0].kind = "image"
        bad.payment_ways.append("bargeld")
        assert "Zahlungsweg unbekannt" in await send(influencer_update=bad)

    _run(cfg, scenario)
