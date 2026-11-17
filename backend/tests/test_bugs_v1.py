"""Regressionstests zu docs/bugs_v1.md (P0): jeder Test zeigt zuerst den gemeldeten Fehlerfall."""

from __future__ import annotations

import hashlib

from test_channels import BOT
from test_server import _csrf, _run

from darkfluenzer import server


def test_bug001_active_attachments_never_render_in_cockpit_origin(cfg):
    """BUG-001: ein Kundenanhang .html/.svg darf unter der Cockpit-Origin nie als aktives
    Dokument ausgeliefert werden; Bilder bleiben anzeigbar, alles mit nosniff und Sandbox."""

    async def scenario(client, app, origin):
        store = app[server.COCKPIT_KEY].store
        inbound = store.record_inbound(
            "telegram", BOT, "1", sender_id="42", conversation_id="42", platform_message_id="1",
            text="anhang", sent_at="2026-11-17T00:00:00+00:00",
            attachments=[{"kind": "document", "size": 1, "mime": "", "status": "pending"}],
        )  # fmt: skip
        files = {
            "evil.html": b"<script>fetch('/api/v1/command')</script>",
            "evil.svg": b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            "foto.png": b"\x89PNG\r\n\x1a\nfake",
        }
        saved = []
        for name, data in files.items():
            rel = f"channels/telegram/42/{name}"
            (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
            (cfg.local / rel).write_bytes(data)
            saved.append({"kind": "document", "path": rel, "status": "saved", "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest(), "mime": ""})  # fmt: skip
        store.set_attachments(inbound.message_id, saved)
        await _csrf(client)
        for name in ("evil.html", "evil.svg"):
            resp = await client.get(f"/api/v1/media/channels/telegram/42/{name}")
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("application/octet-stream"), name
            assert resp.headers["Content-Disposition"].startswith("attachment"), name
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert "sandbox" in resp.headers["Content-Security-Policy"]
        resp = await client.get("/api/v1/media/channels/telegram/42/foto.png")
        assert resp.headers["Content-Type"].startswith("image/png")
        assert "Content-Disposition" not in resp.headers
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    _run(cfg, scenario)


def test_bug002_tunnel_never_reaches_cockpit_even_with_rewritten_host(cfg, monkeypatch):
    """BUG-002: Ein Tunnel, der den Host auf 127.0.0.1 umschreibt, darf keine Cockpit-Pfade
    erreichen. Öffentlich sind nur Webhook/OAuth/signierte Medien – auf einem eigenen Port."""
    import asyncio
    import dataclasses
    from pathlib import Path

    from aiohttp.test_utils import TestClient, TestServer

    from darkfluenzer import config
    from darkfluenzer.channels import instagram

    async def idle(self):
        await asyncio.Event().wait()

    monkeypatch.setattr(instagram.InstagramAccount, "run", idle)
    ig = config._parse_instagram({"public_base_url": "https://clara.example.ts.net"}, Path("x"))
    cfg = dataclasses.replace(cfg, instagram=ig)
    local = f"127.0.0.1:{cfg.server.port}"

    async def scenario(client, app, origin):
        # Tunnel mit umgeschriebenem Host: Weiterleitungs-Header verraten ihn -> abgewiesen
        tunnel = [
            {"X-Forwarded-For": "203.0.113.9"},
            {"Forwarded": "for=203.0.113.9"},
            {"Tailscale-Funnel-Request": "?1"},
            {"CF-Connecting-IP": "203.0.113.9"},
        ]
        for header in tunnel:
            resp = await client.get("/api/v1/session", headers={"Host": local, **header})
            assert resp.status == 403, header
        # öffentliche Pfade gibt es im Cockpit nicht (auch nicht mit lokalem Host)
        assert (await client.get(ig.webhook_path, headers={"Host": local})).status == 404
        # eigene öffentliche App: nur die drei Pfade
        public = server.create_public_app(app[server.COCKPIT_KEY])
        async with TestClient(TestServer(public)) as pub:
            assert (await pub.get("/api/v1/session")).status == 404
            assert (await pub.get("/")).status == 404
            assert (await pub.post("/api/v1/command")).status in (404, 405)
            resp = await pub.post(
                ig.webhook_path, data=b"{}", headers={"X-Hub-Signature-256": "sha256=00"}
            )
            assert resp.status == 403  # Signatur falsch, aber der Pfad existiert

    _run(cfg, scenario)


def test_bug003_explicit_default_return_never_over_instagram(cfg):
    """BUG-003: Default-Rückversand – `explizit` nur über Telegram; über Instagram nie, mit
    sichtbarer Sperrkarte. `standard` geht über beide Kanäle."""
    import io

    from PIL import Image

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        default = store.default_contact()
        store.update_default_contact(
            default["revision"], {}, {("telegram", BOT): "99", ("instagram", "1784"): "77"}
        )
        tg = store.record_inbound(
            "telegram", BOT, "t1", sender_id="99", conversation_id="99", platform_message_id="1",
            text="hi", sent_at="2026-11-17T00:00:00+00:00",
        )  # fmt: skip
        ig = store.record_inbound(
            "instagram", "1784", "i1", sender_id="77", conversation_id="77",
            platform_message_id="m1", text="hi", sent_at="2026-11-17T00:00:00+00:00",
        )  # fmt: skip
        assert tg.customer.kind == ig.customer.kind == "internal"
        paths = {}
        for tier, color in (("explizit", (200, 0, 0)), ("standard", (0, 200, 0))):
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), color).save(buf, "PNG")
            rel = f"evaluation/x/{tier}.png"
            (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
            (cfg.local / rel).write_bytes(buf.getvalue())
            media = store.add_media(
                rel, hashlib.sha256(buf.getvalue()).hexdigest(), len(buf.getvalue())
            )
            if tier == "standard":
                store.db.execute(
                    "UPDATE media SET content_tier = 'standard' WHERE id = ?", (media,)
                )
            paths[tier] = rel

        def sent(conv):
            rows = store.db.execute(
                "SELECT attachments FROM channel_messages WHERE conversation_id = ?"
                " AND direction = 'out' ORDER BY id DESC LIMIT 1",
                (conv,),
            ).fetchone()
            return rows[0] if rows else ""

        cockpit._reply_internal(ig.conversation_id, "Ergebnis", [paths["explizit"]])
        assert "explizit_ki" not in sent(ig.conversation_id)  # nie über Instagram
        cards = [r[0] for r in store.db.execute(
            "SELECT text FROM channel_messages WHERE conversation_id = ? AND direction = 'system'",
            (ig.conversation_id,))]  # fmt: skip
        assert any("explizit" in c and "Instagram" in c for c in cards)
        cockpit._reply_internal(ig.conversation_id, "Ergebnis", [paths["standard"]])
        assert "standard_ki" in sent(ig.conversation_id)
        cockpit._reply_internal(tg.conversation_id, "Ergebnis", [paths["explizit"]])
        assert "explizit_ki" in sent(tg.conversation_id)  # Default über Telegram: erlaubt

    _run(cfg, scenario)


def test_bug004_same_name_different_content_never_sends_the_wrong_copy(cfg):
    """BUG-004: zwei Ergebnisse mit gleichem Dateinamen, aber anderem Inhalt – jede Zustellkopie
    gehört zu genau ihrer Quelle (inhaltsadressiert), auch nach erneutem Versand."""
    import io
    import json

    from PIL import Image

    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        default = store.default_contact()
        store.update_default_contact(default["revision"], {}, {("telegram", BOT): "99"})
        tg = store.record_inbound(
            "telegram", BOT, "t1", sender_id="99", conversation_id="99", platform_message_id="1",
            text="hi", sent_at="2026-11-17T00:00:00+00:00",
        )  # fmt: skip
        sources = {}
        for folder, color in (("a", (255, 0, 0)), ("b", (0, 0, 255))):
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), color).save(buf, "PNG")
            rel = f"evaluation/{folder}/bild_01.png"
            (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
            (cfg.local / rel).write_bytes(buf.getvalue())
            sources[rel] = color

        def last_copy():
            row = store.db.execute(
                "SELECT attachments FROM channel_messages WHERE conversation_id = ?"
                " AND direction = 'out' ORDER BY id DESC LIMIT 1",
                (tg.conversation_id,),
            ).fetchone()
            return cfg.local / json.loads(row[0])[0]["path"]

        for _ in range(2):  # auch beim erneuten Versand die richtige Datei
            for rel, color in sources.items():
                cockpit._reply_internal(tg.conversation_id, "Ergebnis", [rel])
                with Image.open(last_copy()) as im:
                    assert im.convert("RGB").getpixel((0, 0)) == color, rel

    _run(cfg, scenario)


def test_bug005_underpayment_never_books_the_full_price(tmp_path):
    """BUG-005: manuelle Zuordnung (Befehl 41) und Gutschein nur bei ausreichendem Eingang;
    eine Unterzahlung bleibt offen, der Auftrag unbezahlt."""
    import pytest
    from test_channels import _inbound

    from darkfluenzer.store import Store, StoreError

    store = Store(tmp_path / "local")
    first = _inbound(store, "1", "42", "hallo", "10")
    evm = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
    order = store.create_offer(
        first.customer.id, first.conversation_id, "Foto", False, 2500,
        "2099-01-01T00:00:00.000+00:00", {"usdt": ("27.7801", evm, 0.9, 1)},
    )  # fmt: skip
    pay = dict(network="bsc", asset="USDT", position=0, block=1, confirmations=15, required=15,
               rate=0.9, rate_ms=1)  # fmt: skip
    store.upsert_payment(method="usdt", amount="10.0", txid="0xklein", eur=9.0, **pay)
    small = store.payment_page(0, 10, "unassigned")[0][0]
    with pytest.raises(StoreError, match="deckt"):
        store.assign_inflow(small["id"], order.order_no, "Betreiber")
    assert store.order(order.order_no).status == "offered"
    assert store.payment(small["id"])["status"] == "unassigned"
    # Gutschein unter dem Preis: nicht automatisch, auch nicht manuell
    store.record_inbound(
        "telegram", "7000001", "2", sender_id="42", conversation_id="42", platform_message_id="11",
        text="AB12-CD34EF-GH56", sent_at="2026-11-17T00:00:00+00:00",
    )  # fmt: skip
    (voucher,) = store.vouchers(10)
    inflow = store.redeem_voucher(voucher["id"], 1000)
    assert store.order(order.order_no).status == "offered"
    with pytest.raises(StoreError, match="deckt"):
        store.assign_inflow(inflow, order.order_no, "Betreiber")
    # ausreichender Eingang (gleicher Weg, mindestens der Angebotsbetrag) wird zugeordnet
    store.upsert_payment(method="usdt", amount="27.80", txid="0xvoll", eur=25.02, **pay)
    full = [p for p in store.payment_page(0, 10, "unassigned")[0] if p["txid"] == "0xvoll"][0]
    store.assign_inflow(full["id"], order.order_no, "Betreiber")
    assert store.order(order.order_no).status == "paid"
    store.close()


def test_bug006_customer_order_jobs_and_media_carry_the_order(cfg):
    """BUG-006: Jobs eines bezahlten Kundenauftrags tragen den Auftrag ab der Anlage; seine Medien
    sind Kundenmedien und lassen sich weder über die Galerie noch per Befehl löschen."""
    import shutil

    import pytest
    from test_channels import _inbound

    from darkfluenzer.config import project_root
    from darkfluenzer.core import orders
    from darkfluenzer.media import models
    from darkfluenzer.store import Store, StoreError

    shutil.copytree(project_root() / "workflows", cfg.root / "workflows", dirs_exist_ok=True)
    man = models.load_manifest(cfg.root)
    store = Store(cfg.local)
    first = _inbound(store, "1", "42", "hallo", "10")
    evm = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
    order = store.create_offer(
        first.customer.id, first.conversation_id, "Foto", False, 2500,
        "2099-01-01T00:00:00.000+00:00", {"usdt": ("27.7801", evm, 0.9, 1)},
    )  # fmt: skip
    store.upsert_payment(
        method="usdt", network="bsc", asset="USDT", amount="27.7801", txid="0x1", position=0,
        block=1, confirmations=15, required=15, eur=25.0, rate=0.9, rate_ms=1,
    )  # fmt: skip
    assert store.order(order.order_no).status == "paid"
    _, (job,) = orders.create_order(
        store, man, "krea2_turbo_t2i", {"prompt": "Strand"}, {}, count=1,
        customer_order_no=order.order_no,
    )  # fmt: skip
    assert store.job(job)["order_id"] == order.id  # Auftragsbezug ab der Anlage
    rel = "evaluation/krea2_turbo/kunde.png"
    (cfg.local / rel).parent.mkdir(parents=True, exist_ok=True)
    (cfg.local / rel).write_bytes(b"\\x89PNG\\r\\n\\x1a\\nkunde")
    media = store.add_media(rel, hashlib.sha256(b"x").hexdigest(), 20, job_id=job)
    assert store.media_by_id(media)["order_id"] == order.id
    with pytest.raises(StoreError, match="Kundenauftrags"):
        store.remove_media([media])
    store.close()
