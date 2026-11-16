"""Claras Instagram-Konto (V0 §6, §6.1) ohne Netz und ohne echten Schlüsselbund: Meta-Signatur und
Webhook-Abonnement, Eingang genau einmal mit sofort gesicherten Medien, Echo der eigenen Sendung
gegenüber Handy-Nachricht (Übergabe), 24-h-Fenster mit Human-Agent-Ausnahme, signierte
Medien-URL, OAuth-state, Token-Erneuerung."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from darkfluenzer import config
from darkfluenzer.channels import instagram
from darkfluenzer.store import Store

CLARA = "17841400000000001"
LEON = "5550001"
BASE = "https://clara.example.ts.net"
APP_SECRET = "app-geheimnis"
VERIFY = "verify-wert"
SERVICES = {
    name: f"darkfluenzer.instagram.{name}"
    for name in ("app_id", "app_secret", "verify_token", "token", "token_expiry", "media_key")
}


class FakeHttp:
    """Antwortet wie Graph-API und CDN und merkt sich jeden Aufruf."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.files: dict[str, tuple[bytes, str]] = {}
        self.fail: Exception | None = None
        self.sent = 0

    async def json(
        self, method, url, *, params=None, data=None, body=None, token=None, timeout_s=None
    ):
        self.calls.append((method, url, {"params": params, "data": data, "body": body}))
        if url.endswith("/messages"):
            if self.fail is not None:
                raise self.fail
            self.sent += 1
            return {"recipient_id": body["recipient"]["id"], "message_id": f"m-own-{self.sent}"}
        if url.endswith("/me"):
            return {"user_id": CLARA, "username": "clara"}
        if url.endswith("/me/subscribed_apps"):
            return {"success": True}
        if url.endswith("/oauth/access_token"):
            return {"data": [{"access_token": "kurz", "user_id": CLARA, "permissions": "x"}]}
        if url.endswith("/refresh_access_token"):
            return {"access_token": "erneuert", "token_type": "bearer", "expires_in": 5184000}
        if url.endswith("/access_token"):
            return {"access_token": "lang", "token_type": "bearer", "expires_in": 5184000}
        if re.search(r"/v\d+\.\d+/\d+$", url):  # Profil eines Absenders
            return {"username": f"u{url.rsplit('/', 1)[1]}", "name": "Leon"}
        raise AssertionError(url)

    async def download(self, url, target, limit, timeout_s):
        data, ctype = self.files[url]
        if len(data) > limit:
            raise instagram.TooLarge
        target.write_bytes(data)
        return ctype

    async def close(self) -> None:
        pass

    def posts(self) -> list[dict]:
        return [c[2]["body"] for c in self.calls if c[1].endswith("/messages")]


@pytest.fixture
def vault(monkeypatch):
    """Schlüsselbund im Speicher (der echte bleibt unberührt)."""
    values = {
        SERVICES["app_id"]: "4242",
        SERVICES["app_secret"]: APP_SECRET,
        SERVICES["verify_token"]: VERIFY,
        SERVICES["token"]: "tok",
        SERVICES["token_expiry"]: str(int(time.time()) + 50 * 86400),
    }

    def store_secret(service, value):
        values[service] = value
        return True

    monkeypatch.setattr(instagram, "secret", lambda service: values.get(service) or None)
    monkeypatch.setattr(instagram, "store_secret", store_secret)
    return values


def _account(cfg, store, **overrides):
    ig = config._parse_instagram({"public_base_url": BASE}, Path("config.toml"))
    inbound: list = []
    changed: list[int] = []

    async def on_inbound(i):
        inbound.append(i)

    acc = instagram.InstagramAccount(
        dataclasses.replace(cfg, instagram=dataclasses.replace(ig, **overrides)),
        store,
        on_inbound,
        lambda: None,
    )
    acc.http = FakeHttp()
    acc.on_change_message = changed.append
    return acc, inbound, changed


def _hook(*events) -> bytes:
    entry = {"id": CLARA, "time": int(time.time() * 1000), "messaging": list(events)}
    return json.dumps({"object": "instagram", "entry": [entry]}).encode()


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _msg(mid, *, text="hallo", at=None, partner=LEON, echo=False, attachments=None) -> dict:
    message: dict = {"mid": mid, "text": text}
    if attachments:
        message["attachments"] = attachments
    if echo:
        message["is_echo"] = True
    sender, recipient = (CLARA, partner) if echo else (partner, CLARA)
    return {
        "sender": {"id": sender},
        "recipient": {"id": recipient},
        "timestamp": at or int(time.time() * 1000),
        "message": message,
    }


async def _deliver(acc, *events) -> int:
    body = _hook(*events)
    status = await acc.handle_webhook(body, _sig(body))
    await acc.drain()
    return status


def _queue(store, conv, customer, text) -> int:
    return store.queue_outbound(customer, conv, text, revision=store.conversation_revision(conv))


def test_webhook_signature_and_verify_handshake(cfg, vault):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, store)

    async def scenario():
        await acc._check()
        assert acc.status()["state"] == "READY" and acc.status()["account"] == "@clara"
        body = _hook(_msg("m1"))
        wrong = "sha256=" + hmac.new(b"falsch", body, hashlib.sha256).hexdigest()
        for header in ("", "sha256=" + "0" * 64, wrong):
            assert await acc.handle_webhook(body, header) == 403
        assert await acc.handle_webhook(body + b" ", _sig(body)) == 403  # Bytes verändert
        assert store.db.execute("SELECT count(*) FROM channel_messages").fetchone()[0] == 0
        assert await acc.handle_webhook(b"{kaputt", _sig(b"{kaputt")) == 400
        assert await _deliver(acc, _msg("m1")) == 200
        assert len(inbound) == 1
        acc.account = ""  # Konto noch unbekannt: nicht quittieren, Meta stellt erneut zu
        assert await acc.handle_webhook(body, _sig(body)) == 503

    asyncio.run(scenario())
    ok = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"}
    assert acc.verify(ok) == (200, "1158201444")
    assert acc.verify(ok | {"hub.verify_token": "falsch"})[0] == 403
    assert acc.verify(ok | {"hub.mode": "unsubscribe"})[0] == 403
    store.close()


def test_inbound_once_with_media_saved_immediately(cfg, vault):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, store, max_download_mb=0.0001)  # rund 100 Bytes
    acc.http.files = {
        "https://cdn.example/bild": (b"png-bytes", "image/png"),
        "https://cdn.example/reel": (b"mp4-bytes", "video/mp4"),
        "https://cdn.example/beitrag": (b"<html></html>", "text/html; charset=utf-8"),
        "https://cdn.example/gross": (b"x" * 500, "video/mp4"),
    }
    attachments = [
        {"type": "image", "payload": {"url": "https://cdn.example/bild"}},
        {
            "type": "ig_reel",
            "payload": {
                "url": "https://cdn.example/reel",
                "title": "Strand",
                "reel_video_id": "77",
            },
        },
        {"type": "share", "payload": {"url": "https://cdn.example/beitrag"}},
        {"type": "video", "payload": {"url": "https://cdn.example/gross"}},
        {"type": "ig_post", "payload": {"ig_post_media_id": "88"}},
    ]

    async def scenario():
        await acc._check()
        body = _hook(_msg("m1", text="schau mal", attachments=attachments))
        assert await acc.handle_webhook(body, _sig(body)) == 200
        # vor der 200 gespeichert; die Sicherung der Anhänge läuft sofort danach
        assert store.db.execute("SELECT count(*) FROM channel_messages").fetchone()[0] == 1
        assert await acc.handle_webhook(body, _sig(body)) == 200  # erneut zugestellt
        await acc.drain()
        assert len(inbound) == 1
        (item,) = store.conversation_items(inbound[0].customer.id, 0, 10)[0]
        assert item["text"] == "schau mal" and item["handle"] == f"u{LEON}"
        atts = item["attachments"]
        assert [(a["kind"], a["status"]) for a in atts] == [
            ("photo", "saved"),
            ("reel", "saved"),
            ("share", "not_importable"),
            ("video", "too_large"),
            ("post", "not_importable"),
        ]
        assert (cfg.local / atts[0]["path"]).read_bytes() == b"png-bytes"
        assert atts[0]["sha256"] == hashlib.sha256(b"png-bytes").hexdigest()
        assert atts[0]["path"].startswith(f"channels/instagram/{LEON}/")
        assert atts[0]["path"].endswith(".png") and store.message_file_known(atts[0]["path"])
        assert atts[1]["ref_id"] == "77" and "Strand" in atts[1]["note"]
        assert not any("source" in a for a in atts)  # CDN-Adressen nach dem Sichern verworfen
        assert not list((cfg.local / "channels" / "instagram" / LEON).glob("*.part"))
        assert store.adapter_get("instagram", CLARA, instagram.PENDING) == ""
        assert acc.window_open(LEON)
        assert len([c for c in acc.http.calls if c[1].endswith(f"/{LEON}")]) == 1  # Profil 1×

    asyncio.run(scenario())
    store.close()


def test_echo_of_own_send_vs_phone_handoff(cfg, vault):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, store)

    async def scenario():
        await acc._check()
        await _deliver(acc, _msg("m1"))
        conv, customer = inbound[0].conversation_id, inbound[0].customer.id
        out = _queue(store, conv, customer, "hi")
        (item,) = store.outbox("instagram", CLARA)
        await acc._send(item)
        row = store.message(out)
        assert (row["status"], row["platform_message_id"]) == ("sent", "m-own-1")
        assert acc.http.posts() == [{"recipient": {"id": LEON}, "message": {"text": "hi"}}]
        assert await _deliver(acc, _msg("m-own-1", text="hi", echo=True)) == 200  # eigene
        for _ in range(2):  # Handy-Nachricht, zweimal zugestellt
            assert await _deliver(acc, _msg("m-phone", text="bin gleich da", echo=True)) == 200
        items, _ = store.conversation_items(customer, 0, 10)
        assert [(i["direction"], i["text"].split("\n")[0]) for i in items] == [
            ("in", "hallo"),
            ("out", "hi"),
            ("out", "bin gleich da"),
            ("system", instagram.HANDOFF_CARD),
        ]

    asyncio.run(scenario())
    store.close()


def test_send_unknown_on_timeout_confirmed_by_echo_failed_on_error(cfg, vault):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, store)

    async def scenario():
        await acc._check()
        await _deliver(acc, _msg("m1"))
        conv, customer = inbound[0].conversation_id, inbound[0].customer.id
        acc.http.fail = instagram.HttpError("Keine Antwort von Instagram", maybe_sent=True)
        out = _queue(store, conv, customer, "noch was")
        await acc._send(store.outbox("instagram", CLARA)[0])
        assert store.message(out)["status"] == "unknown"
        assert store.outbox("instagram", CLARA) == []  # nie blind wiederholt
        acc.http.fail = None
        await _deliver(acc, _msg("m-late", text="noch was", echo=True))
        row = store.message(out)
        assert (row["status"], row["platform_message_id"]) == ("sent", "m-late")
        items, _ = store.conversation_items(customer, 0, 10)
        assert [i["direction"] for i in items] == ["in", "out"]  # keine Übergabe-Karte
        acc.http.fail = instagram.GraphError(400, 100, "Invalid parameter")
        bad = _queue(store, conv, customer, "kaputt")
        await acc._send(store.outbox("instagram", CLARA)[0])
        row = store.message(bad)
        assert row["status"] == "failed" and row["error"].startswith("Instagram: Invalid")

    asyncio.run(scenario())
    store.close()


def test_reply_window_refuses_and_human_agent_override(cfg, vault):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, store)

    async def scenario():
        await acc._check()
        await _deliver(acc, _msg("m1", at=int((time.time() - 25 * 3600) * 1000)))
        conv, customer = inbound[0].conversation_id, inbound[0].customer.id
        assert not acc.window_open(LEON) and acc.window_remaining_ms(LEON) == 0
        assert "Human-Agent" in acc.send_check(LEON)
        assert acc.send_check(LEON, human_agent=True) == ""
        late = _queue(store, conv, customer, "spät")
        await acc._send(store.outbox("instagram", CLARA)[0])
        row = store.message(late)
        assert row["status"] == "failed" and "(24 h) abgelaufen" in row["error"]
        assert acc.http.posts() == []
        manual = _queue(store, conv, customer, "manuell")
        acc.mark_human_agent(manual)
        await acc._send(store.outbox("instagram", CLARA)[0])
        assert store.message(manual)["status"] == "sent"
        assert acc.http.posts()[-1] == {
            "recipient": {"id": LEON},
            "message": {"text": "manuell"},
            "messaging_type": "MESSAGE_TAG",
            "tag": "HUMAN_AGENT",
        }
        assert store.adapter_get("instagram", CLARA, instagram.HUMAN) == ""
        # älter als 7 Tage: auch mit Kennzeichnung abgewiesen
        await _deliver(acc, _msg("m2", at=int((time.time() - 8 * 86400) * 1000), partner="77"))
        old = inbound[1]
        too_old = _queue(store, old.conversation_id, old.customer.id, "viel zu spät")
        acc.mark_human_agent(too_old)
        await acc._send(store.outbox("instagram", CLARA)[0])
        row = store.message(too_old)
        assert row["status"] == "failed" and "nur 7 Tage" in row["error"]
        # neue Kundennachricht öffnet das Fenster: normale Antwort ohne Tag
        await _deliver(acc, _msg("m3"))
        _queue(store, conv, customer, "jetzt")
        await acc._send(store.outbox("instagram", CLARA)[0])
        assert acc.http.posts()[-1] == {"recipient": {"id": LEON}, "message": {"text": "jetzt"}}

    asyncio.run(scenario())
    store.close()


def test_signed_media_url_valid_expired_tampered(cfg, vault):
    store = Store(cfg.local)
    acc, _, _ = _account(cfg, store)
    rel = "outputs/2026/bild 1.png"
    url = acc.sign_media_url(rel)
    parts = urlsplit(url)
    assert url.startswith(f"{BASE}/instagram/media/outputs/2026/bild%201.png?t=")
    assert acc.is_public(parts.path) and acc.public_host == "clara.example.ts.net"
    assert not acc.is_public("/api/v1/media/outputs/2026/bild 1.png")
    path = unquote(parts.path.removeprefix("/instagram/media/"))
    token = parse_qs(parts.query)[instagram.MEDIA_TOKEN_PARAM][0]
    assert path == rel and acc.check_media_token(path, token)
    exp, mac = token.split(".")
    assert not acc.check_media_token("outputs/2026/bild 2.png", token)  # anderer Pfad
    assert not acc.check_media_token(path, f"{int(exp) + 3600}.{mac}")  # verlängert
    assert not acc.check_media_token(path, f"{exp}.{mac[:-1]}{'B' if mac[-1] == 'A' else 'A'}")
    key = vault[SERVICES["media_key"]]  # beim ersten Signieren im Schlüsselbund angelegt
    past = int(time.time()) - 1
    assert not acc.check_media_token(path, f"{past}.{instagram._mac(key, rel, past)}")
    assert not acc.check_media_token("../local/darkfluenzer.sqlite3", token)
    with pytest.raises(instagram.InstagramError):
        acc.sign_media_url("../geheim.png")
    store.close()


def test_oauth_state_checked_once_and_token_stored(cfg, vault):
    del vault[SERVICES["token"]], vault[SERVICES["token_expiry"]]
    store = Store(cfg.local)
    acc, _, _ = _account(cfg, store)

    async def scenario():
        await acc._check()
        assert (acc.state, acc.missing) == ("OFF", "Instagram-Anmeldung fehlt")
        query = parse_qs(urlsplit(acc.authorize_url()).query)
        assert query["redirect_uri"] == [f"{BASE}/instagram/oauth"]
        assert query["client_id"] == ["4242"] and query["response_type"] == ["code"]
        state = query["state"][0]
        assert (await acc.oauth_callback({"state": "fremd", "code": "abc"}))[0] == 403
        assert (await acc.oauth_callback({"code": "abc"}))[0] == 403
        assert acc.http.calls == []  # ohne gültigen state kein Tokentausch
        status, text = await acc.oauth_callback({"state": state, "code": "abc#_"})
        assert status == 200 and "@clara" in text
        data = acc.http.calls[0][2]["data"]
        assert data["code"] == "abc" and data["redirect_uri"] == f"{BASE}/instagram/oauth"
        assert vault[SERVICES["token"]] == "lang"
        assert abs(int(vault[SERVICES["token_expiry"]]) - (time.time() + 5184000)) < 60
        assert (acc.state, acc.account) == ("READY", CLARA)
        assert (await acc.oauth_callback({"state": state, "code": "abc"}))[0] == 403  # einmalig

    asyncio.run(scenario())
    store.close()


def test_status_missing_refresh_before_expiry_and_logout(cfg, vault):
    store = Store(cfg.local)
    acc, _, _ = _account(cfg, store)
    saved = dict(vault)
    vault.clear()

    async def scenario():
        await acc._check()
        assert acc.state == "OFF"
        assert acc.missing == "Meta-App und Tunnel einrichten (app_id, app_secret, verify_token)"
        vault.update(saved)
        vault[SERVICES["token_expiry"]] = str(int(time.time()) + 5 * 86400)  # in der Frist
        await acc._check()
        assert acc.state == "READY" and vault[SERVICES["token"]] == "erneuert"
        assert int(vault[SERVICES["token_expiry"]]) > time.time() + 50 * 86400
        assert acc.status()["login_state"] == "ready"
        assert await acc.logout() == ""
        assert (acc.state, acc.missing, acc.account) == ("OFF", "Instagram-Anmeldung fehlt", "")

    asyncio.run(scenario())
    store.close()


def test_config_instagram_section(project, tmp_path):
    where = tmp_path / "config.toml"
    ig = config._parse_instagram({}, where)
    assert (ig.public_base_url, ig.graph_version, ig.reply_window_h) == ("", "v24.0", 24.0)
    assert config._parse_instagram(None, where) is None
    for bad in (
        {"public_base_url": "http://clara.example.ts.net"},
        {"public_base_url": "https://clara.example.ts.net/pfad"},
        {"webhook_path": "/api/hook"},
        {"oauth_path": "/instagram/webhook"},
        {"graph_version": "24"},
        {"human_agent_window_h": 12},
    ):
        with pytest.raises(config.ConfigError):
            config._parse_instagram(bad, where)
    with (project / "local" / "config.toml").open("a") as fh:
        fh.write(f'\n[instagram]\npublic_base_url = "{BASE}/"\n')
    loaded = config.load(project).instagram
    assert loaded is not None and loaded.redirect_uri == f"{BASE}/instagram/oauth"


def test_server_routes_only_public_paths_through_tunnel(cfg, vault, monkeypatch):
    """Über den Tunnel-Host nur Webhook, OAuth und signierte Medien; alles andere 403. Anmeldelink
    nur mit Sitzung; Webhook nur mit Meta-Signatur."""
    from test_server import _csrf, _run

    from darkfluenzer import server

    async def idle(self):  # kein Netz: Kontoprüfung gegen Meta läuft im Test nicht
        await asyncio.Event().wait()

    monkeypatch.setattr(instagram.InstagramAccount, "run", idle)
    ig = config._parse_instagram({"public_base_url": BASE}, Path("config.toml"))
    cfg = dataclasses.replace(cfg, instagram=ig)
    public = {"Host": urlsplit(BASE).netloc}

    async def scenario(client, app, origin):
        assert (await client.get("/api/v1/session", headers=public)).status == 403
        assert (await client.get("/", headers=public)).status == 403
        query = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "c-1"}
        resp = await client.get(ig.webhook_path, params=query, headers=public)
        assert resp.status == 200 and await resp.text() == "c-1"
        query["hub.verify_token"] = "falsch"
        assert (await client.get(ig.webhook_path, params=query, headers=public)).status == 403
        body = _hook(_msg("m-1"))
        bad = public | {"X-Hub-Signature-256": "sha256=00"}
        assert (await client.post(ig.webhook_path, data=body, headers=bad)).status == 403
        assert (await client.get(ig.media_path + "/x.png?t=1.abc", headers=public)).status == 403
        assert (await client.get("/api/v1/instagram/login", allow_redirects=False)).status == 401
        await _csrf(client)
        resp = await client.get("/api/v1/instagram/login", allow_redirects=False)
        assert resp.status == 302 and resp.headers["Location"].startswith(ig.oauth_authorize_url)
        cockpit = app[server.COCKPIT_KEY]
        assert {c["platform"] for c in [cockpit.instagram.status()]} == {"instagram"}

    _run(cfg, scenario)
