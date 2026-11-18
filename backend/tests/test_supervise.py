"""SP2 Schritt 1 (BUG-015): Daueraufgaben unter Aufsicht – Fehler protokolliert und gemeldet,
Neustart mit wachsender Pause, Abbruch bleibt Abbruch; ein Fehler im Versand hält den Postausgang
nicht an (die nächste Nachricht geht raus) und steht bis zur Erholung im Kanal-STATE."""

from __future__ import annotations

import asyncio

import pytest
from test_telegram import CLARA, TEST_CHAT, _account, _msg

from darkfluenzer.core import supervise as sup
from darkfluenzer.store import Store


def test_restart_with_growing_pause_and_report(monkeypatch):
    calls, reports, pauses = [], [], []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        pauses.append(s)
        await real_sleep(0)

    monkeypatch.setattr(sup.asyncio, "sleep", fake_sleep)

    async def job():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Netz weg")
        if len(calls) == 2:
            return  # unerwartet beendet
        await asyncio.Event().wait()  # läuft dann dauerhaft

    async def scenario():
        task = asyncio.create_task(
            sup.supervise("Test", job, report=reports.append, base_s=2, max_s=60)
        )
        for _ in range(20):
            await real_sleep(0)
        assert len(calls) == 3 and not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert pauses == [2, 4]  # verdoppelt
    assert reports == ["Test: RuntimeError: Netz weg – Neustart in 2 s",
                       "Test: unerwartet beendet – Neustart in 4 s"]  # fmt: skip


def test_send_error_does_not_stop_the_outbox(cfg, tmp_path):
    store = Store(cfg.local)
    acc, inbound, _ = _account(cfg, tmp_path, store)
    real_send = acc._send
    failed = []

    async def flaky(item):
        if not failed:
            failed.append(item["id"])
            raise RuntimeError("TDLib kaputt")
        await real_send(item)

    acc._send = flaky
    reports: list[str] = []

    def report(message):
        acc.task_error = message
        reports.append(message)

    async def scenario():
        await acc._message(_msg(TEST_CHAT, 10))
        conv = inbound[0].conversation_id
        first = store.queue_outbound(inbound[0].customer.id, conv, "eins",
                                     revision=store.conversation_revision(conv))  # fmt: skip
        second = store.queue_outbound(inbound[0].customer.id, conv, "zwei",
                                      revision=store.conversation_revision(conv))  # fmt: skip
        task = asyncio.create_task(sup.supervise("telegram: Postausgang", acc.outbox_worker,
                                                 report=report, base_s=0.01, max_s=1))  # fmt: skip
        acc.wake.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if store.message(second)["status"] == "sending":
                break
        assert failed == [first] and reports and "TDLib kaputt" in acc.status()["error"]
        acc.wake.set()  # nächste Runde nach dem Neustart
        for _ in range(100):
            await asyncio.sleep(0.01)
            if store.message(second)["status"] == "sending" and not acc.task_error:
                break
        assert store.message(second)["status"] == "sending"  # die nächste Nachricht ging raus
        assert acc.task_error == "" and acc.status()["error"] == ""  # Erholung löscht die Meldung
        task.cancel()

    asyncio.run(scenario())
    assert CLARA
    store.close()
