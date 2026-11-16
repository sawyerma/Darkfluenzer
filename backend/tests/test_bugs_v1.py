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
