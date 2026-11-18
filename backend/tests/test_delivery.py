"""Zustellung (SP5 Schritt 9): Anhangart aus dem Produkt (Foto, Video, Dokument nur mit
Originaldatei), selbstlöschend über TDLib, TDLib-1.8.70-Eingaben (Datei in inputPhoto/inputVideo/
inputDocument), Kanalformat (WebP → PNG, WebM abgewiesen) und Größengrenze, Begleittext aus dem
Profilblock mit wörtlich angehängtem KI-Hinweis, Instagram-Fenster: Zustellung parkt
(awaiting_contact) und geht beim nächsten Kundenkontakt raus."""

from __future__ import annotations

import dataclasses
import hashlib
import types
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from test_channels import _inbound, cloner_cfg  # noqa: F401  (Fixture)
from test_chat import Melody, _setup
from test_customer_orders import _png
from test_server import _run

from darkfluenzer.channels.base import Capabilities
from darkfluenzer.channels.telegram import _content
from darkfluenzer.core import orders
from darkfluenzer.core.base import _Call
from darkfluenzer.core.delivery import _media_attachment
from darkfluenzer.media import aimeta
from darkfluenzer.nodes import llm
from darkfluenzer.store import StoreError
from darkfluenzer.v1 import commands_pb2
from darkfluenzer.web import http as server

SOON = (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="milliseconds")
CAP = {"@type": "formattedText", "text": "t"}


def test_telegram_input_content_by_kind(tmp_path):
    photo = _content(tmp_path, {"kind": "photo", "path": "a.png", "width": 10, "height": 20,
                                "self_destruct_s": 30}, CAP)  # fmt: skip
    assert photo["@type"] == "inputMessagePhoto" and photo["photo"]["@type"] == "inputPhoto"
    assert photo["photo"]["photo"] == {"@type": "inputFileLocal", "path": str(tmp_path / "a.png")}
    assert photo["self_destruct_type"] == {
        "@type": "messageSelfDestructTypeTimer", "self_destruct_time": 30,
    }  # fmt: skip
    video = _content(tmp_path, {"kind": "video", "path": "a.mp4"}, CAP)
    assert video["video"]["@type"] == "inputVideo" and video["self_destruct_type"] is None
    doc = _content(tmp_path, {"kind": "document", "path": "a.png"}, CAP)
    assert doc["document"]["@type"] == "inputDocument"  # Datei nicht direkt im Feld (1.8.70)
    assert doc["document"]["document"]["@type"] == "inputFileLocal"


def test_attachment_limits_and_photo_size(tmp_path):
    path = tmp_path / "x.png"
    Image.new("RGB", (32, 24)).save(path)
    att = _media_attachment(tmp_path, path, "photo", self_destruct_s=10, limit_mb=1)
    assert (att["kind"], att["width"], att["height"], att["self_destruct_s"]) == (
        "photo", 32, 24, 10,
    )  # fmt: skip
    with pytest.raises(StoreError, match="Zu groß für den Kanal"):
        _media_attachment(tmp_path, path, "photo", limit_mb=0.00001)


def _review_order(cockpit, cfg, first, product):
    """Bezahlter Kundenauftrag mit fertigem Ergebnis in review (Inhaltsstufe standard)."""
    store, man = cockpit.store, cockpit.manifest
    order = store.create_offer(
        first.customer.id, first.conversation_id, product["product"], False,
        product["price_cents"], SOON, {}, product_id=product["id"], kind=product["kind"],
        wish="Strand",
    )  # fmt: skip
    store.transition(order.order_no, "accepted")
    store.record_payment(order.order_no, "usdt", f"0x{order.id}:0", product["price_cents"], "EUR")
    no, (job,) = orders.create_order(
        store, man, "krea2_turbo_t2i", {"prompt": "Strand"}, {}, count=1,
        customer_order_no=order.order_no,
    )  # fmt: skip
    data = _png((order.id * 20 % 255, 100, 50))
    rel = f"evaluation/kunde_{order.id}.png"
    (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
    (cfg.local / rel).write_bytes(data)
    media = store.add_media(rel, hashlib.sha256(data).hexdigest(), len(data), job_id=job)
    store.db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job,))
    orders.advance_order(store, job)
    orders.select_candidate(cfg, store, man, no, media, None)
    return store.order(no), media


def test_kind_copy_caption_window_and_resume(cloner_cfg, monkeypatch):  # noqa: F811
    melody = Melody()
    monkeypatch.setattr(llm, "generate", melody)

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        clara, adapter = _setup(cockpit)
        store.save_influencer(clara, store.influencers()[0]["revision"], "Clara", None, "",
                              "Ich bin eine KI.", [{"product": "Foto", "price_cents": 2000,
                              "hd_surcharge_cents": 0, "workflow": "krea2_turbo_t2i",
                              "self_destruct": True}])  # fmt: skip
        store.save_persona_version(clara, {"persona": "Clara, 24", "delivery": "Begleite kurz."},
                                   {}, "mit Zustellung", activate=True)  # fmt: skip
        product = store.influencers()[0]["prices"][0]
        cockpit.cfg = dataclasses.replace(
            cockpit.cfg, telegram=types.SimpleNamespace(self_destruct_s=20)
        )
        caps = Capabilities(document=True, self_destruct=True, reply_window=True,
                            read_receipts=False, typing=False,
                            max_attachment_mb={"photo": 10.0})  # fmt: skip
        window = {"open": False}
        adapter.capabilities = lambda: caps
        adapter.window_open = lambda _p: window["open"]
        first = _inbound(store, "1", "42", "Hallo", "10")
        # Anhangart: Foto, mit Originaldatei Dokument (nur wo der Kanal Dateien kennt)
        order, media = _review_order(cockpit, cloner_cfg, first, product)
        assert cockpit._delivery_kind(order, product, caps) == ("photo", 20)
        assert cockpit._delivery_kind(order, {**product, "original_file": True}, caps)[0] == (
            "document"
        )
        insta = dataclasses.replace(caps, document=False, self_destruct=False)
        assert cockpit._delivery_kind(order, {**product, "original_file": True}, insta) == (
            "photo", 0,
        )  # fmt: skip
        # Kanalformat: WebP -> PNG (gekennzeichnet), WebM abgewiesen
        webp = cloner_cfg.local / "evaluation" / "x.webp"
        Image.new("RGB", (8, 8)).save(webp, "WEBP")
        copy = cockpit._delivery_copy(order, webp, 9)
        assert copy.suffix == ".png" and aimeta.is_marked(copy)
        with pytest.raises(StoreError, match="WebM"):
            cockpit._delivery_copy(order, webp.with_suffix(".webm"), 9)
        # Fenster zu: Freigabe parkt die Zustellung
        approve = commands_pb2.ApproveArtifact(
            order_no=order.order_no, media_id=media, not_explicit=True
        )
        assert await cockpit._approve_artifact(approve, _Call("r1", "", "approve")) == ""
        assert store.order(order.order_no).status == "awaiting_contact"
        assert store.deliveries(order.id) == []
        # Kunde schreibt wieder: Zustellung mit Begleittext und KI-Hinweis
        window["open"] = True
        melody.answers.append("Hier ist dein Bild!")
        await cockpit._on_inbound(_inbound(store, "2", "42", "Und?", "11"))
        assert store.order(order.order_no).status == "approved"
        (delivery,) = store.deliveries(order.id)
        item = store.message(delivery["message_id"])
        assert item["text"] == "Hier ist dein Bild!\n\nIch bin eine KI."
        att = item["attachments"][0]
        assert att["kind"] == "photo" and att["self_destruct_s"] == 20 and att["width"] == 16
        assert melody.calls[0]["message"] == "Begleite kurz."
        # Begleittext mit fremdem Betrag: verworfen, nur der KI-Hinweis
        melody.answers.append("Nur heute 50 € günstiger!")
        offer = store.offer(order.id)
        assert await cockpit._delivery_caption(order, offer) == "Ich bin eine KI."
        cards = [i["text"] for i in store.conversation_items(first.customer.id, 0, 80)[0]
                 if i["direction"] == "system"]  # fmt: skip
        assert any(c.startswith("ZUSTELLUNG WARTET AUF KONTAKT") for c in cards)
        assert any(c.startswith("BEGLEITTEXT VERWORFEN") for c in cards)

    _run(cloner_cfg, scenario)


def test_video_finish_redo_with_new_seed(cloner_cfg):  # noqa: F811
    """E23: Fertigstellen (Animation) eines Videos in Prüfung mit neuem Seed wiederholen, ohne das
    Bild neu zu erzeugen."""

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store, man = cockpit.store, cockpit.manifest
        first = _inbound(store, "1", "42", "Hallo", "10")
        order = store.create_offer(first.customer.id, first.conversation_id, "Clip", False, 6000,
                                   SOON, {}, kind="video", wish="Tanz")  # fmt: skip
        store.transition(order.order_no, "accepted")
        store.record_payment(order.order_no, "usdt", "0xv:0", 6000, "EUR")
        no, (job,) = orders.create_order(
            store, man, "krea2_turbo_t2i", {"prompt": "Tanz"}, {}, count=1,
            customer_order_no=order.order_no, finish_workflow="ltx25_i2v",
            finish_values={"prompt": "Tanz", "duration_s": 2.0},
            video_max_s=cockpit.cfg.production.video_max_s,
        )  # fmt: skip
        data = _png((1, 2, 3))
        (cloner_cfg.local / "evaluation").mkdir(parents=True, exist_ok=True)
        (cloner_cfg.local / "evaluation" / "bild.png").write_bytes(data)
        image = store.add_media("evaluation/bild.png", hashlib.sha256(data).hexdigest(),
                                len(data), job_id=job)  # fmt: skip
        store.db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job,))
        orders.advance_order(store, job)
        (finish_job,) = orders.select_candidate(cloner_cfg, store, man, no, image, None)
        clip = store.add_media("evaluation/clip.mp4", "c" * 64, 9, job_id=finish_job)
        store.db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (finish_job,))
        orders.advance_order(store, finish_job)
        assert store.order(no).status == "review" and clip
        finish = store.stages(order.id)[-1]
        (new,) = orders.retry_stage(store, man, no, finish.seq, 3, None,
                                    video_max_s=cockpit.cfg.production.video_max_s)  # fmt: skip
        assert store.order(no).status == "producing" and store.order(no).kind == "video"
        wf = man.workflows["ltx25_i2v"]
        graph_seed = __import__("darkfluenzer.nodes.comfy", fromlist=["load_graph"]).load_graph(
            man, wf
        )[wf.params["seed"].node]["inputs"][wf.params["seed"].input]
        old_seed = store.job(finish_job)["params"].get("seed", graph_seed)
        assert store.job(new)["params"]["seed"] == int(old_seed) + 1 + finish.attempts  # neu
        assert len(store.stages(order.id)) == 2  # keine neue Bildstufe

    _run(cloner_cfg, scenario)
