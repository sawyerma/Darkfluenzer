"""Automatische Prüfung und Auswahl (SP5 Schritt 7): Regeln nur mit Kalibrierungsquelle
qualifiziert, fehlender Wert oder Status außer ok = nicht bestanden, Video: jedes Frame,
bester Gesamtwert gewinnt; ohne bestandenen Kandidaten neue Kandidatenstufe bis zur Obergrenze,
danach Meldung; ohne qualifizierte Schwellen wählt der Betreiber."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from test_channels import _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_customer_orders import _png
from test_server import _run

from darkfluenzer.config import ConfigError, SelectionConfig, SelectionRule, _parse_selection
from darkfluenzer.core import orders, selection
from darkfluenzer.web import http as server

SOON = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="milliseconds")
SRC = "Kalibrierung Testdaten"
RULES = {
    "identity": SelectionRule("identity", "auraface", min=0.5, source=SRC),
    "content": SelectionRule("content", "rating", allowed=("neutral",), source=SRC),
    "technical": SelectionRule("quality", "sharpness", min=100, source=SRC),
    "quality": SelectionRule("quality_score", "quality", min=0.6, source=SRC),
}
CFG = SelectionConfig(rules=RULES, weight_identity=0.5, weight_quality=0.5, regenerate_max=1)


def _rows(identity=0.8, rating="neutral", sharp=300.0, quality=0.9, frames=1, status="ok"):
    rows = []
    for item in range(frames):
        rows += [
            {
                "check_name": "identity",
                "status": status,
                "data": {"auraface": identity, "item": item},
            },
            {"check_name": "content", "status": "ok", "data": {"rating": rating, "item": item}},
            {"check_name": "quality", "status": "ok", "data": {"sharpness": sharp, "item": item}},
        ]
    rows.append({"check_name": "quality_score", "status": "ok", "data": {"quality": quality}})
    return rows


def test_rules_and_choice():
    assert selection.unqualified(SelectionConfig()) == list(selection.LABELS)
    no_source = dataclasses.replace(CFG, rules={**RULES, "quality": dataclasses.replace(
        RULES["quality"], source="")})  # fmt: skip
    assert selection.unqualified(no_source) == ["quality"]
    assert selection.judge(CFG, 1, _rows()).passed
    low = selection.judge(CFG, 2, _rows(identity=0.3))
    assert not low.passed and low.reasons == ("Identität: 0.3 < 0.5",)
    assert "Inhalt: low nicht erlaubt" in selection.judge(CFG, 3, _rows(rating="low")).reasons
    assert (
        "Identität: kein_gesicht" in selection.judge(CFG, 4, _rows(status="kein_gesicht")).reasons
    )
    missing = [r for r in _rows() if r["check_name"] != "quality_score"]
    assert "Qualität: Wert fehlt" in selection.judge(CFG, 5, missing).reasons
    video = _rows(frames=3)
    video[3]["data"]["auraface"] = 0.2  # ein Frame fällt durch
    assert not selection.judge(CFG, 6, video).passed
    best, verdicts = selection.choose(CFG, [(1, _rows(identity=0.6)), (2, _rows(identity=0.9)),
                                            (3, _rows(quality=0.1))])  # fmt: skip
    assert best.media_id == 2 and [v.passed for v in verdicts] == [True, True, False]


def test_config_rules_need_a_threshold(tmp_path):
    with pytest.raises(ConfigError, match="ohne Schwelle"):
        _parse_selection({"rules": {"identity": {"check": "identity", "value": "x"}}}, tmp_path)
    with pytest.raises(ConfigError, match="unbekannt"):
        _parse_selection({"rules": {"hands": {"check": "hands", "value": "x", "min": 1}}}, tmp_path)
    parsed = _parse_selection(
        {
            "rules": {
                "identity": {"check": "identity", "value": "auraface", "min": 0.5, "source": SRC}
            }
        },
        tmp_path,
    )
    assert parsed.rules["identity"].min == 0.5 and parsed.rules["identity"].source == SRC


def _waiting_order(cockpit, cfg, count=2):
    """Bezahlter Kundenauftrag mit fertiger Kandidatenstufe (wartet auf Auswahl)."""
    store, man = cockpit.store, cockpit.manifest
    first = _inbound(store, "1", "42", "Hallo", "10")
    order = store.create_offer(first.customer.id, first.conversation_id, "Foto", False, 2000,
                               SOON, {}, wish="Strand")  # fmt: skip
    store.transition(order.order_no, "accepted")
    store.record_payment(order.order_no, "usdt", f"0x{order.id}:0", 2000, "EUR")
    no, jobs = orders.create_order(store, man, "krea2_turbo_t2i", {"prompt": "Strand"}, {},
                                   count=count, customer_order_no=order.order_no)  # fmt: skip
    media = []
    for i, job in enumerate(jobs):
        data = _png((order.id * 30 % 255, i * 40, 7))
        rel = f"evaluation/k_{order.id}_{i}.png"
        (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
        (cfg.local / rel).write_bytes(data)
        media.append(store.add_media(rel, hashlib.sha256(data).hexdigest(), len(data),
                                     job_id=job))  # fmt: skip
        store.db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job,))
        orders.advance_order(store, job)
    return store.order(no), jobs, media


def _checks(store, job, media, **kw):
    rows = _rows(**kw)
    store.add_media_checks(job, media, "test", [
        {"check": r["check_name"], "status": r["status"], **r["data"]} for r in rows])  # fmt: skip


def _cards(store, order):
    offer = store.offer(order.id)
    return [
        i["text"]
        for i in store.conversation_items(store.order(order.order_no).customer_id, 0, 80)[0]
        if i["direction"] == "system" and i["conversation_id"] == offer["conversation_id"]
    ]


def test_auto_select_regenerate_and_unqualified(cloner_cfg, monkeypatch):  # noqa: F811
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        queued: list[int] = []
        monkeypatch.setattr(cockpit, "_enqueue", lambda jobs: queued.extend(jobs))
        # ohne qualifizierte Schwellen: Betreiber wählt, Urteil „nicht qualifiziert“
        order, jobs, media = _waiting_order(cockpit, cloner_cfg)
        cockpit._auto_select(order.id)
        cockpit._auto_select(order.id)
        assert store.stages(order.id)[-1].status == "waiting"
        assert sum(c.startswith("AUSWAHL DURCH BETREIBER") for c in _cards(store, order)) == 1
        assert orders._selection_text(store, media[0]).startswith("Prüfung nicht qualifiziert")
        # qualifiziert: bester bestandener Kandidat, Auftrag zur Prüfung (kein Fertigstellen)
        cockpit.cfg = dataclasses.replace(cockpit.cfg, selection=CFG)
        order, jobs, media = _waiting_order(cockpit, cloner_cfg)
        _checks(store, jobs[0], media[0], identity=0.6)
        _checks(store, jobs[1], media[1], identity=0.95)
        cockpit._auto_select(order.id)
        assert store.order(order.order_no).status == "review"
        assert store.stages(order.id)[-1].selected_media_id == media[1]
        assert orders._selection_text(store, media[1]) == "bestanden · 0,93"
        assert any(c.startswith("AUTOMATISCH AUSGEWÄHLT") for c in _cards(store, order))
        # keiner besteht: neue Kandidatenstufe, danach Obergrenze und Meldung
        order, jobs, media = _waiting_order(cockpit, cloner_cfg)
        for job, m in zip(jobs, media, strict=True):
            _checks(store, job, m, sharp=10.0)
        cockpit._auto_select(order.id)
        stages = store.stages(order.id)
        assert [s.status for s in stages] == ["failed", "running"] and len(queued) == 2
        assert orders._selection_text(store, media[0]).startswith("nicht bestanden: Technik")
        for i, job in enumerate(store.stage_jobs(stages[-1].id)):
            data = _png((i + 90, 200, order.id % 255))
            rel = f"evaluation/r_{order.id}_{i}.png"
            (cloner_cfg.local / rel).write_bytes(data)
            m = store.add_media(rel, hashlib.sha256(data).hexdigest(), len(data),
                                job_id=job["id"])  # fmt: skip
            _checks(store, job["id"], m, rating="medium")
            store.db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job["id"],))
            orders.advance_order(store, job["id"])
        cockpit._auto_select(order.id)
        assert len(store.stages(order.id)) == 2  # Obergrenze 1 Neuauflage
        assert any("Obergrenze erreicht" in c for c in _cards(store, order))
        assert store.selection_stats()["krea2_turbo_t2i"] == (2, 6)

    _run(cloner_cfg, scenario)
