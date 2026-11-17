"""SP0 Schritt 5 (BUG-106): Während eine große Videodatei gehasht und gekennzeichnet wird, bleibt
der Hauptstrang frei; die gemessene Verzögerung erscheint im STATE ``resources``.

Größe der Probedatei über ``DF_MAINLOOP_MB`` (Vorgabe 64; Abnahme am Mac mit 500)."""

from __future__ import annotations

import asyncio
import os
import struct

from test_channels import BOT
from test_server import _run

from darkfluenzer.v1 import comfy_pb2
from darkfluenzer.web import http as server

SIZE_MB = int(os.environ.get("DF_MAINLOOP_MB", "64"))
LAG_LIMIT_MS = 100.0


def _write_mp4(path, size_mb: int) -> None:
    """Gültige MP4-Kistenfolge (ftyp, moov, mdat) mit ``size_mb`` MB Nutzdaten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"isom" + struct.pack(">I", 0)
    moov = struct.pack(">I4s", 8, b"moov")
    payload = size_mb * 2**20
    with open(path, "wb") as f:
        f.write(ftyp + moov + struct.pack(">I4s", payload + 8, b"mdat"))
        block = os.urandom(2**20)
        for _ in range(size_mb):
            f.write(block)


def test_big_video_is_marked_off_the_main_loop(cfg):
    async def scenario(client, app, origin):
        cockpit = app[server.COCKPIT_KEY]
        store = cockpit.store
        default = store.default_contact()
        store.update_default_contact(default["revision"], {}, {("telegram", BOT): "99"})
        tg = store.record_inbound(
            "telegram", BOT, "t1", sender_id="99", conversation_id="99", platform_message_id="1",
            text="hi", sent_at="2026-11-17T00:00:00+00:00",
        )  # fmt: skip
        rel = "evaluation/video/gross.mp4"
        _write_mp4(cfg.local / rel, SIZE_MB)
        loop = asyncio.get_running_loop()
        lags: list[float] = []
        done = asyncio.Event()

        async def probe():
            while not done.is_set():
                start = loop.time()
                await asyncio.sleep(0.01)
                lags.append((loop.time() - start - 0.01) * 1000)

        task = asyncio.create_task(probe())
        await asyncio.sleep(0.05)  # Probe läuft an
        result = cockpit._reply_internal(tg.conversation_id, "Ergebnis", [rel])
        if asyncio.iscoroutine(result):  # vor SP0 Schritt 5 synchron
            await result
        done.set()
        await task
        row = store.db.execute(
            "SELECT attachments FROM channel_messages WHERE conversation_id = ?"
            " AND direction = 'out' ORDER BY id DESC LIMIT 1",
            (tg.conversation_id,),
        ).fetchone()
        assert row and "gross_ki.mp4" in row[0], row
        assert len(lags) >= 5, lags
        assert max(lags) < LAG_LIMIT_MS, f"Hauptstrang blockiert: {max(lags):.0f} ms"
        # die Messung des Cockpits selbst landet im STATE resources
        cockpit._lags.append((loop.time(), max(lags) / 1000))
        res = comfy_pb2.Resources.FromString(cockpit._resources())
        assert res.loop_lag_ms >= 0 and res.loop_lag_max_ms >= res.loop_lag_ms

    _run(cfg, scenario)
