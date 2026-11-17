"""Kundenauftrag (V0 §8.4/§8.5, C5/C5a): Angebot mit eindeutigem Betrag, automatische und
manuelle Zuordnung, Produktion erst nach Zahlung, „Freigeben & senden“ hinter approval.py mit
KI-Kennzeichnung, Wiederholung nach Fehlschlag, Gutschein, Monatsliste."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import io
import struct
import types
import uuid

import pytest
from PIL import Image
from test_channels import _inbound
from test_server import _csrf, _post, _run

from darkfluenzer.config import TokenConfig, WalletConfig
from darkfluenzer.core import orders
from darkfluenzer.media import aimeta, pipeline
from darkfluenzer.payments import vouchers
from darkfluenzer.payments.chain import WalletWatcher
from darkfluenzer.store import Store, StoreError
from darkfluenzer.v1 import commands_pb2
from darkfluenzer.web import http as server

BTC = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"  # BIP-173-Testvektor
EVM = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"  # EIP-55-Testvektor


def _png(color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, "PNG", pnginfo=_info())
    return buf.getvalue()


def _info():
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("prompt", '{"geheim": "Workflow"}')  # wie ComfyUI
    return info


def test_ai_mark_png_jpeg_mp4(tmp_path):
    """Regel 12 d: Zustellkopie trägt DigitalSourceType, Erzeugungsdaten entfallen, Original
    bleibt unverändert, Datei bleibt lesbar."""
    src = tmp_path / "a.png"
    src.write_bytes(_png())
    before = src.read_bytes()
    aimeta.mark(src, tmp_path / "out" / "a.png")
    out = tmp_path / "out" / "a.png"
    assert src.read_bytes() == before and aimeta.is_marked(out)
    assert b"geheim" not in out.read_bytes() and b"geheim" in before
    assert Image.open(out).size == (16, 16)

    jpg = tmp_path / "b.jpg"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(jpg, "JPEG")
    aimeta.mark(jpg, tmp_path / "out" / "b.jpg")
    assert aimeta.is_marked(tmp_path / "out" / "b.jpg")
    assert Image.open(tmp_path / "out" / "b.jpg").size == (16, 16)

    def box(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I4s", len(body) + 8, kind) + body

    mp4 = tmp_path / "c.mp4"
    udta = box(b"udta", b"comment: geheimer Prompt")
    mp4.write_bytes(
        box(b"ftyp", b"isom")
        + box(b"moov", box(b"mvhd", b"x" * 8) + udta)
        + box(b"mdat", b"0" * 32)
    )
    aimeta.mark(mp4, tmp_path / "out" / "c.mp4")
    data = (tmp_path / "out" / "c.mp4").read_bytes()
    assert aimeta.is_marked(tmp_path / "out" / "c.mp4") and b"udta" not in data
    assert b"geheim" not in data and data[: mp4.stat().st_size - 40] != b""  # Inhalt genullt
    assert len(data) > mp4.stat().st_size and data.startswith(mp4.read_bytes()[:12])
    (tmp_path / "d.webp").write_bytes(b"RIFF")
    with pytest.raises(aimeta.AiMetaError, match="webp"):
        aimeta.mark(tmp_path / "d.webp", tmp_path / "out" / "d.webp")


def test_voucher_codes_are_masked():
    text, codes = vouchers.extract("hier: ab12-cd34ef-gh56 danke, Tel 0171-123456-7890")
    assert codes == ["AB12-CD34EF-GH56"] and "ab12" not in text and "0171-123456-7890" in text
    assert vouchers.extract("AB12CD34EFGH567")[1] == ["AB12-CD34EF-GH567"]
    assert vouchers.extract("ganz normale Nachricht")[1] == []


def test_offer_matching_store(tmp_path):
    """Exakter Betrag im Zeitfenster -> automatisch zugeordnet (paid); falscher Betrag ->
    nicht zugeordnet -> manuelle Zuordnung; Betrag nie zweimal vergeben."""
    store = Store(tmp_path / "local")
    first = _inbound(store, "1", "42", "hallo", "10")
    amounts = {"usdt": ("24.9901", EVM, 0.92, 1)}
    order = store.create_offer(
        first.customer.id, first.conversation_id, "Foto", False, 2299,
        "2099-01-01T00:00:00.000+00:00", amounts,
    )  # fmt: skip
    assert order.status == "offered" and store.amount_taken("usdt", "24.9901")
    with pytest.raises(Exception, match="UNIQUE"):
        store.create_offer(
            first.customer.id, first.conversation_id, "Foto", False, 2299,
            "2099-01-01T00:00:00.000+00:00", amounts,
        )  # fmt: skip
    pay = dict(network="bsc", asset="USDT", position=0, block=1, required=15, eur=22.99,
               rate=0.92, rate_ms=1)  # fmt: skip
    # falscher Betrag (nicht der eindeutige, aber höher): nicht automatisch, manuell zuordenbar
    store.upsert_payment(method="usdt", amount="25.5", txid="0xa", confirmations=20, **pay)
    wrong = store.payment_page(0, 10, "unassigned")[0][0]
    assert store.order(order.order_no).status == "offered"  # falscher Betrag: nichts
    store.upsert_payment(method="usdt", amount="24.9901", txid="0xb", confirmations=3, **pay)
    assert store.order(order.order_no).status == "offered"  # noch nicht bestätigt
    (open_row,) = store.unconfirmed_payments("bsc")
    store.update_confirmations(open_row["id"], 15, 15)
    assert store.order(order.order_no).status == "paid"
    assert store.payment(open_row["id"])["status"] == "assigned"
    texts = [i["text"] for i in store.conversation_items(first.customer.id, 0, 20)[0]]
    assert any(t.startswith("ZAHLUNG BESTÄTIGT · USDT 24.9901") for t in texts)
    with pytest.raises(StoreError, match="kein offenes Angebot"):
        store.assign_inflow(wrong["id"], order.order_no, "Betreiber")  # schon bezahlt
    second = store.create_offer(
        first.customer.id, first.conversation_id, "Foto", False, 2299,
        "2099-01-01T00:00:00.000+00:00", {"usdt": ("24.9902", EVM, 0.92, 1)},
    )  # fmt: skip
    store.upsert_payment(method="usdt", amount="24.99", txid="0xc", confirmations=20, **pay)
    short = [p for p in store.payment_page(0, 10, "unassigned")[0] if p["txid"] == "0xc"][0]
    with pytest.raises(StoreError, match="deckt"):  # Unterzahlung (bugs_v1 BUG-005)
        store.assign_inflow(short["id"], second.order_no, "Betreiber")
    store.assign_inflow(wrong["id"], second.order_no, "Betreiber")
    assert store.order(second.order_no).status == "paid"
    with pytest.raises(StoreError, match="schon zugeordnet"):
        store.assign_inflow(wrong["id"], second.order_no, "Betreiber")
    store.close()


def _wallet(cfg) -> WalletConfig:
    return WalletConfig(
        btc_address=BTC, btc_error="", bsc_address=EVM, bsc_error="",
        btc_api="https://mempool.space/api", bsc_rpc="https://bsc-dataseed.bnbchain.org",
        price_api="https://api.coingecko.com/api/v3/simple/price", btc_price_id="bitcoin",
        tokens=(TokenConfig("USDT", "0x55d398326f99059fF775485246999027B3197955", 18, "tether"),),
        btc_confirmations=2, bsc_confirmations=15, poll_s=60, bsc_header_batch=100,
        offer_valid_min=60,
    )  # fmt: skip


def test_customer_order_chain(cfg):
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        man = cockpit.manifest
        csrf = await _csrf(client)
        # echte Watcher-Instanz ohne Netz (nicht gestartet), Kurse wie aus der Kursquelle
        cockpit.cfg = dataclasses.replace(cockpit.cfg, wallet=_wallet(cockpit.cfg))
        cockpit.wallet = WalletWatcher(cockpit.cfg, store, lambda: None, lambda: None)
        import time

        cockpit.wallet.rates = {"bitcoin": 80000.0, "tether": 0.9}
        cockpit.wallet.rate_ms = int(time.time() * 1000)
        channel = types.SimpleNamespace(state="READY", wake=asyncio.Event())  # Kanal verbunden
        cockpit.telegram = channel

        async def send(**kw):
            req = commands_pb2.CommandRequest(request_id=str(uuid.uuid4()), **kw)
            status, body = await _post(client, origin, csrf, req)
            assert status == 200
            return commands_pb2.CommandResponse.FromString(body).detail

        first = _inbound(store, "1", "42", "hallo", "10")
        cust = first.customer.id
        (ident,) = store.identities(cust)
        figure = store.save_influencer(
            0, 0, "Clara", None, "", "Ich bin eine KI.",
            [{"product": "Foto", "price_cents": 2000, "hd_surcharge_cents": 500}],
        )  # fmt: skip

        def offer(**over):
            (i,) = store.identities(cust)
            args = dict(customer_id=cust, identity_id=i["id"], conversation_id=i["conversation_id"],
                        revision=i["revision"], influencer_id=figure, position=0, hd=True,
                        note="Gern!")  # fmt: skip
            return commands_pb2.CreateOffer(**(args | over))

        assert "Altersangabe" in await send(create_offer=offer())
        store.set_age_mark(cust, "self_declared_adult")
        assert "KI-Hinweis" in await send(create_offer=offer())
        notice = store.queue_ai_notice(cust, ident["id"], "Ich bin eine KI.")
        store.set_message_status(notice, "sent", platform_message_id="1")
        assert "Position" in await send(create_offer=offer(position=3))
        assert await send(create_offer=offer()) == ""
        assert await send(create_offer=offer()) == ""  # zweites Angebot: andere Beträge
        o1, o2 = [
            store.order(r[0])
            for r in store.db.execute(
                "SELECT order_no FROM orders WHERE source = 'customer' ORDER BY id"
            )
        ]
        a1, a2 = store.offer(o1.id)["amounts"], store.offer(o2.id)["amounts"]
        assert o1.price_amount == 2500 and a1["usdt"] == "27.7801" and a2["usdt"] == "27.7802"
        assert a1["btc"] == "0.00031251" and a1["btc"] != a2["btc"]
        (text,) = [
            r[0]
            for r in store.db.execute("SELECT text FROM channel_messages WHERE direction = 'out'")
            if "27.7801" in r[0]
        ]
        assert text.startswith("Gern!") and EVM in text and BTC in text
        assert channel.wake.is_set()

        # Zahlung: exakter Betrag, bestätigt -> zugeordnet, Auftrag bezahlt
        store.upsert_payment(
            method="usdt", network="bsc", asset="USDT", amount="27.7801", txid="0x1", position=0,
            block=1, confirmations=15, required=15, eur=25.0, rate=0.9, rate_ms=1,
        )  # fmt: skip
        assert store.order(o1.order_no).status == "paid"

        # Produktion nur mit Inhaltsstufe standard
        with pytest.raises(pipeline.PipelineError, match="standard"):
            orders.create_order(
                store, man, "lustify_sdxl_t2i", {"prompt": "p"}, {}, count=1,
                customer_order_no=o1.order_no,
            )  # fmt: skip
        with pytest.raises(pipeline.PipelineError, match="kein bezahlter"):
            orders.create_order(
                store, man, "krea2_turbo_t2i", {"prompt": "p"}, {}, count=1,
                customer_order_no=o2.order_no,
            )  # fmt: skip
        no, (job,) = orders.create_order(
            store, man, "krea2_turbo_t2i", {"prompt": "Strand"}, {}, count=1,
            customer_order_no=o1.order_no,
        )  # fmt: skip
        assert no == o1.order_no and store.order(no).status == "producing"
        result = cfg.local / "evaluation" / "kunde.png"
        result.parent.mkdir(parents=True, exist_ok=True)
        data = _png((200, 100, 50))
        result.write_bytes(data)
        media = store.add_media(
            "evaluation/kunde.png", hashlib.sha256(data).hexdigest(), len(data), job_id=job
        )
        store.db.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job,))
        orders.advance_order(store, job)
        orders.select_candidate(cfg, store, man, no, media, None)
        assert store.order(no).status == "review" and store.media_tier(media) == "standard"

        approve = commands_pb2.ApproveArtifact(order_no=no, media_id=media)
        assert "nicht explizit" in await send(approve_artifact=approve)
        approve.not_explicit = True
        assert await send(approve_artifact=approve) == ""
        assert store.order(no).status == "approved"
        (d1,) = store.deliveries(o1.id)
        item = store.message(d1["message_id"])
        att = item["attachments"][0]
        assert aimeta.is_marked(cfg.local / att["path"]) and b"geheim" in result.read_bytes()
        assert b"geheim" not in (cfg.local / att["path"]).read_bytes()
        assert cockpit._delivery_gate(item | {"delivery_id": d1["id"]}) == ""
        assert (await client.get(f"/api/v1/media/{att['path']}")).status == 200  # Vorschau
        assert "nicht explizit" not in await send(approve_artifact=approve)  # nicht zweimal

        # endgültig fehlgeschlagen -> Karte, Wiederholung möglich; ungeklärt nie
        assert "fehlgeschlagener" in await send(
            retry_delivery=commands_pb2.RetryDelivery(order_no=no)
        )
        store.set_message_status(item["id"], "failed", error="Telegram: Chat not found")
        cockpit._message_changed(item["id"])
        assert store.deliveries(o1.id)[0]["status"] == "failed"
        assert await send(retry_delivery=commands_pb2.RetryDelivery(order_no=no)) == ""
        d2 = store.deliveries(o1.id)[-1]
        assert d2["id"] != d1["id"] and d2["status"] == "pending"
        store.set_message_status(d2["message_id"], "sent", platform_message_id="77")
        cockpit._message_changed(d2["message_id"])
        assert store.order(no).status == "delivered"
        texts = [i["text"] for i in store.conversation_items(cust, 0, 50)[0]]
        assert any(t.startswith("ANGEBOT · Foto + HD · 25,00 €") for t in texts)
        assert any(t.startswith("ZUSTELLUNG FEHLGESCHLAGEN") for t in texts)
        assert texts.count(f"VERSENDET · {no}") == 1
        cockpit._message_changed(d2["message_id"])  # wiederholt: keine zweite Karte
        texts = [i["text"] for i in store.conversation_items(cust, 0, 50)[0]]
        assert texts.count(f"VERSENDET · {no}") == 1

        # Gutschein: Code nie im Verlauf, erst nach Betragseintrag bestätigt -> offenes Angebot
        voucher_msg = _inbound(store, "2", "42", "Code: AB12-CD34EF-GH56", "11")
        await cockpit._on_inbound(voucher_msg)
        texts = [i["text"] for i in store.conversation_items(cust, 0, 60)[0]]
        assert (
            "AB12" not in " ".join(texts)
            and "GUTSCHEIN ERHALTEN · im Reiter Wallet prüfen" in texts
        )
        (v,) = store.vouchers(10)
        assert v["code"] == "AB12-CD34EF-GH56" and v["status"] == "pending"
        gift = commands_pb2.GiftCardConfirm(voucher_id=v["id"])
        assert "Betrag" in await send(gift_card_confirm=gift)
        gift.amount_cents = 2500
        assert await send(gift_card_confirm=gift) == ""
        assert store.order(o2.order_no).status == "paid"  # offenes Angebot desselben Kunden
        assert "schon entschieden" in await send(gift_card_confirm=gift)

        # Monatsliste
        month = store.payments_of_month(store.payment(1)["detected_at"][:7])
        resp = await client.get(f"/api/v1/payment-export/{month[0]['detected_at'][:7]}")
        body = (await resp.read()).decode("utf-8-sig")
        assert resp.status == 200 and "27.7801" in body and o1.order_no in body
        assert (await client.get("/api/v1/payment-export/2026-13")).status == 400

    _run(cfg, scenario)
