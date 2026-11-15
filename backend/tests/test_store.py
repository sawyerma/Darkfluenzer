"""Kundenakte und Liefer-Gate: jede Gate-Bedingung einzeln verletzt, DB-Schicht angegriffen."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest

from darkfluenzer import approval
from darkfluenzer import store as store_module
from darkfluenzer.store import Store, StoreError

BOT = "bot-1"


@pytest.fixture
def store(tmp_path: Path):
    s = Store(tmp_path / "local")
    yield s
    s.close()


def _paid_order_in_review(store: Store, user: int = 100, candidates: int = 3):
    customer, _ = store.customer_for_telegram(BOT, user)
    order = store.create_order(customer.id, "image", "Portrait am Meer")
    store.set_offer(order.order_no, "1 Bild", 250, "XTR")
    store.transition(order.order_no, "accepted")
    store.record_payment(order.order_no, "telegram_stars", f"tx-{order.id}", 250, "XTR")
    store.transition(order.order_no, "producing")
    work = store.order_dir(order) / "work"
    arts = []
    for i in range(1, candidates + 1):
        f = work / f"candidate_{i:02d}.png"
        f.write_bytes(f"png-{order.id}-{i}".encode())
        arts.append(store.add_artifact(order.order_no, "candidate", f))
    store.transition(order.order_no, "review")
    return customer, store.order(order.order_no), arts


# ---------------------------------------------------------------------- Kunden & Nachrichten


def test_customer_numbers_are_stable_and_sequential(store):
    a, created_a = store.customer_for_telegram(BOT, 111)
    again, created_again = store.customer_for_telegram(BOT, 111)
    b, _ = store.customer_for_telegram(BOT, 222)
    other_bot, _ = store.customer_for_telegram("bot-2", 111)
    assert (a.customer_no, created_a) == ("DF-C-000001", True)
    assert (again.customer_no, created_again) == ("DF-C-000001", False)
    assert b.customer_no == "DF-C-000002"
    assert other_bot.customer_no == "DF-C-000003"


def test_parallel_first_messages_create_exactly_one_customer(tmp_path):
    local = tmp_path / "local"
    Store(local).close()
    results, errors = [], []
    barrier = threading.Barrier(12)

    def first_message():
        s = Store(local)
        try:
            barrier.wait()
            results.append(s.customer_for_telegram(BOT, 4242)[0].customer_no)
        except Exception as exc:  # pragma: no cover - würde Test scheitern lassen
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=first_message) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert set(results) == {"DF-C-000001"}
    s = Store(local)
    assert s.db.execute("SELECT count(*) FROM customers").fetchone()[0] == 1
    s.close()


def test_duplicate_telegram_update_is_stored_once(store):
    c, _ = store.customer_for_telegram(BOT, 1)
    first = store.add_message(c.id, "in", 1, "hallo", "2026-11-14T10:00:00Z", 77)
    retry = store.add_message(c.id, "in", 1, "hallo", "2026-11-14T10:00:00Z", 77)
    assert first[1] is True and retry == (first[0], False)
    assert store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


# ---------------------------------------------------------------------- Aufträge & Zahlungen


def test_order_folders_and_transitions(store):
    c, _ = store.customer_for_telegram(BOT, 5)
    order = store.create_order(c.id, "video", "kurzer Clip")
    assert order.order_no == "DF-O-000001"
    base = store.local / "customers" / "DF-C-000001" / "orders" / "DF-O-000001"
    assert all((base / d).is_dir() for d in ("input", "work", "sent"))
    with pytest.raises(StoreError, match="nicht erlaubt"):
        store.transition(order.order_no, "paid")
    with pytest.raises(StoreError, match="unbekannt"):
        store.create_order(c.id, "audio", "x")


def test_payment_must_match_offer_and_is_idempotent(store):
    c, _ = store.customer_for_telegram(BOT, 6)
    order = store.create_order(c.id, "image", "x")
    store.set_offer(order.order_no, "1 Bild", 250, "XTR")
    with pytest.raises(StoreError, match="nur im Status accepted"):
        store.record_payment(order.order_no, "telegram_stars", "t1", 250, "XTR")
    store.transition(order.order_no, "accepted")
    with pytest.raises(StoreError, match="passt nicht"):
        store.record_payment(order.order_no, "telegram_stars", "t1", 100, "XTR")
    with pytest.raises(StoreError, match="passt nicht"):
        store.record_payment(order.order_no, "telegram_stars", "t1", 250, "EUR")
    pid = store.record_payment(order.order_no, "telegram_stars", "t1", 250, "XTR")
    assert store.record_payment(order.order_no, "telegram_stars", "t1", 250, "XTR") == pid
    assert store.order(order.order_no).status == "paid"
    other = store.create_order(c.id, "image", "y")
    with pytest.raises(StoreError, match="anderen Auftrag"):
        store.record_payment(other.order_no, "telegram_stars", "t1", 250, "XTR")


def test_artifacts_are_immutable(store):
    _, order, arts = _paid_order_in_review(store)
    path = store.local / arts[0].path
    assert not os.access(path, os.W_OK)
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE artifacts SET sha256 = ? WHERE id = ?", ("0" * 64, arts[0].id))
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("DELETE FROM artifacts WHERE id = ?", (arts[0].id,))
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("DELETE FROM events")
    outside = store.local / "elsewhere.png"
    outside.write_bytes(b"x")
    with pytest.raises(StoreError, match="nicht im Ordner"):
        store.add_artifact(order.order_no, "candidate", outside)


# ---------------------------------------------------------------------- Liefer-Gate


def test_happy_path_delivers_exactly_once(store):
    customer, order, arts = _paid_order_in_review(store)
    store.record_approval(order.order_no, arts[1].id, "approved", "betreiber")
    assert approval.check_gate(store, order.order_no, arts[1].id, customer.customer_no).ok
    d1 = approval.prepare_delivery(store, order.order_no, arts[1].id, customer.customer_no)
    d2 = approval.prepare_delivery(store, order.order_no, arts[1].id, customer.customer_no)
    assert d1 == d2, "Retry darf keine zweite Lieferung erzeugen"
    approval.confirm_sent(store, d1, "tg-msg-1")
    approval.confirm_sent(store, d1, "tg-msg-1")  # Retry nach Timeout: idempotent
    assert store.order(order.order_no).status == "delivered"
    assert store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 1
    with pytest.raises(StoreError, match="gesperrt"):
        approval.prepare_delivery(store, order.order_no, arts[0].id, customer.customer_no)
    events = [e["event"] for e in store.events("order", order.id)]
    assert events[0] == "created" and events.count("status") >= 6


def test_unpaid_order_never_delivers(store):
    c, _ = store.customer_for_telegram(BOT, 9)
    order = store.create_order(c.id, "image", "x")
    store.set_offer(order.order_no, "1 Bild", 250, "XTR")
    store.transition(order.order_no, "accepted")
    f = store.order_dir(order) / "work" / "candidate_01.png"
    f.write_bytes(b"png")
    art = store.add_artifact(order.order_no, "candidate", f)
    gate = approval.check_gate(store, order.order_no, art.id, c.customer_no)
    assert not gate.ok and "PAYMENT_NOT_CONFIRMED" in gate.reasons
    with pytest.raises(StoreError, match="nur im Status review"):
        store.record_approval(order.order_no, art.id, "approved", "betreiber")


def test_paid_but_not_approved_is_blocked(store):
    customer, order, arts = _paid_order_in_review(store)
    gate = approval.check_gate(store, order.order_no, arts[0].id, customer.customer_no)
    assert not gate.ok
    assert any(r.startswith("OPERATOR_NOT_APPROVED") for r in gate.reasons)


def test_modified_file_is_blocked(store):
    customer, order, arts = _paid_order_in_review(store)
    store.record_approval(order.order_no, arts[0].id, "approved", "betreiber")
    path = store.local / arts[0].path
    os.chmod(path, 0o644)
    path.write_bytes(b"manipuliert")
    gate = approval.check_gate(store, order.order_no, arts[0].id, customer.customer_no)
    assert any(r.startswith("ARTIFACT_HASH_MISMATCH") for r in gate.reasons)
    with pytest.raises(StoreError, match="HASH"):
        approval.prepare_delivery(store, order.order_no, arts[0].id, customer.customer_no)


def test_wrong_customer_is_blocked(store):
    _, order, arts = _paid_order_in_review(store, user=1)
    other, _ = store.customer_for_telegram(BOT, 2)
    store.record_approval(order.order_no, arts[0].id, "approved", "betreiber")
    gate = approval.check_gate(store, order.order_no, arts[0].id, other.customer_no)
    assert any(r.startswith("CUSTOMER_MISMATCH") for r in gate.reasons)


def test_only_latest_decision_counts(store):
    customer, order, arts = _paid_order_in_review(store)
    store.record_approval(order.order_no, arts[0].id, "regenerate", "betreiber")
    store.transition(order.order_no, "review")
    store.record_approval(order.order_no, arts[2].id, "approved", "betreiber")
    assert approval.check_gate(store, order.order_no, arts[2].id, customer.customer_no).ok
    assert not approval.check_gate(store, order.order_no, arts[0].id, customer.customer_no).ok


def test_refund_after_preparation_blocks_sending(store):
    customer, order, arts = _paid_order_in_review(store)
    store.record_approval(order.order_no, arts[0].id, "approved", "betreiber")
    did = approval.prepare_delivery(store, order.order_no, arts[0].id, customer.customer_no)
    store.record_refund("telegram_stars", f"tx-{order.id}")
    with pytest.raises(StoreError, match="Versand gesperrt"):
        approval.confirm_sent(store, did, "tg-1")
    # auch direkt per SQL am Code vorbei nicht möglich
    with pytest.raises(sqlite3.IntegrityError, match="Gate beim Versand"):
        store.db.execute("UPDATE deliveries SET status = 'sent' WHERE id = ?", (did,))


def test_database_rejects_delivery_bypassing_code(store):
    customer, order, arts = _paid_order_in_review(store)
    with pytest.raises(sqlite3.IntegrityError, match="delivery"):
        store.db.execute(
            "INSERT INTO deliveries (order_id, customer_id, artifact_id, artifact_sha256,"
            " idempotency_key, status, created_at) VALUES (?,?,?,?,?,'pending','now')",
            (order.id, customer.id, arts[0].id, arts[0].sha256, "k"),
        )
    with pytest.raises(sqlite3.IntegrityError, match="approval"):
        store.db.execute(
            "INSERT INTO approvals (order_id, artifact_id, artifact_sha256, decision, operator,"
            " decided_at) VALUES (?,?,?,'approved','x','now')",
            (order.id, arts[0].id, "f" * 64),
        )


# ---------------------------------------------------------------------- Medienindex (Galerie)


def test_media_index_migrates_v1_dedupes_numbers_and_customer_names(tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    db = sqlite3.connect(local / "darkfluenzer.sqlite3")  # bestehende v1-Datenbank mit Kunde
    for statement in store_module._statements(store_module.SCHEMA):
        db.execute(statement)
    db.execute("PRAGMA user_version = 1")
    db.execute(
        "INSERT INTO customers (bot_id, telegram_user_id, created_at) VALUES (?, ?, ?)",
        (BOT, 77, "2026-11-14T00:00:00.000+00:00"),
    )
    db.commit()
    db.close()
    s = Store(local)
    try:
        assert s.db.execute("PRAGMA user_version").fetchone()[0] == store_module.SCHEMA_VERSION
        assert s.customer("DF-C-000001").telegram_user_id == 77  # Bestand bleibt
        assert s.add_media("evaluation/x/a.png", "a" * 64, 10)
        assert s.add_media("evaluation/x/b.png", "b" * 64, 10)
        assert s.add_media("ComfyUI/output/a.png", "a" * 64, 10) is None  # gleiche Bytes
        s.db.execute("UPDATE customers SET display_name = 'Mia' WHERE id = 1")
        _paid_order_in_review(s, user=77)  # drei Kandidaten -> drei Kundenmedien
        page, more = s.media_page(0, 10)
        assert not more and [r["id"] for r in page] == sorted((r["id"] for r in page), reverse=True)
        assert sorted(r["number"] for r in page if not r["order_id"]) == [1, 2]
        customer = [r for r in page if r["order_id"]]
        assert len(customer) == 3
        assert all(r["display_name"] == "Mia" and r["number"] is None for r in customer)
        older, _ = s.media_page(page[1]["id"], 10)
        assert [r["id"] for r in older] == [r["id"] for r in page[2:]]
        # Unterschrift: Kundenname bzw. Kundennummer, eigene Medien vierstellige Nummer
        from darkfluenzer.server import _media_item

        captions = {_media_item(r).caption for r in page}
        assert captions == {"Mia", "0001", "0002"}
        s.db.execute("UPDATE customers SET display_name = NULL WHERE id = 1")
        assert {_media_item(r).caption for r in s.media_page(0, 10)[0] if r["order_id"]} == {
            "DF-C-000001"
        }
        # Löschen nur eigener Medien (Code und Trigger); IDs und Nummern nie wieder vergeben
        with pytest.raises(StoreError):
            s.remove_media([customer[0]["id"]])
        with pytest.raises(sqlite3.IntegrityError):
            s.db.execute("DELETE FROM media WHERE id = ?", (customer[0]["id"],))
        c = s.add_media("evaluation/x/c.png", "c" * 64, 10)  # neuester Eintrag, Nummer 3
        assert [r["id"] for r in s.remove_media([c, c + 1])] == [c]
        assert s.remove_media([c]) == []  # bereits gelöscht
        d = s.add_media("evaluation/x/d.png", "d" * 64, 10)
        assert d == c + 1 and s.media_by_path("evaluation/x/d.png")["number"] == 4
        removed, gap = s.media_removed(0, 10)
        assert [(r["media_id"], r["path"]) for r in removed] == [(c, "evaluation/x/c.png")]
        assert not gap
    finally:
        s.close()


def test_job_ends_its_command_and_only_unsubmitted_jobs_are_requeued(tmp_path):
    store = Store(tmp_path)
    rid = "6f1c2c8e-0d1e-4f5a-9b7c-3a2d1e0f9a8b"
    command = {
        "request_id": rid,
        "payload_sha": "0" * 64,
        "command": "render",
        "status": "accepted",
    }
    job = store.create_job(None, "eng", "wf", "p", {"seed": 1}, [1], command=command)
    assert store.command(rid)["entity"] == f"job:{job}"
    store.set_job_status(job, "running", pid=1)
    store.requeue_job(job)  # nie eingereicht: läuft nach dem Neustart erneut
    assert store.job(job)["status"] == "queued"
    store.set_job_status(job, "running", pid=1)
    store.set_job_submitted(job, "prompt-1", {"1": {"class_type": "X", "inputs": {}}}, "a" * 64)
    store.requeue_job(job)  # eingereicht: wird abgeholt, nie zweimal gerendert
    assert store.job(job)["status"] == "running" and store.job(job)["prompt_id"] == "prompt-1"
    store.set_job_status(job, "failed", error="abgebrochen", cancelled=True)
    assert store.command(rid)["status"] == "cancelled"
    assert [r["status"] for r in store.receipts(0, 10)[0]] == ["accepted", "cancelled"]
    assert store.finish_command(rid, "completed") is False  # terminal bleibt terminal
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE commands SET status = 'completed' WHERE request_id = ?", (rid,))
    store.close()


def test_comfy_output_of_a_running_job_is_indexed_with_the_job(cfg):
    """Frühe Ausgabe eines laufenden Jobs (z. B. die Maske) erscheint nicht vorab ohne Auftrag:
    nach dem Abschluss gewinnt die Job-Ausgabe mit Auftragsbezug."""
    from PIL import Image

    from darkfluenzer import pipeline
    from darkfluenzer.store import sha256_file

    s = Store(cfg.local)
    try:
        job = s.create_job(None, "e", "wf", "p", {}, [])
        s.set_job_status(job, "running")
        early = cfg.comfyui.path / "output" / "darkfluenzer" / "mask_00001_.png"
        early.parent.mkdir(parents=True)
        Image.new("L", (4, 4), 255).save(early)
        assert pipeline.media_candidates(cfg, s, set(), settle_s=0) == []

        copy = cfg.local / "evaluation" / "wf" / "wf_x_01.png"
        copy.parent.mkdir(parents=True)
        copy.write_bytes(early.read_bytes())
        out = {"path": "evaluation/wf/wf_x_01.png", "sha256": sha256_file(copy), "node": "19"}
        s.set_job_status(job, "done", outputs=[out])
        found = pipeline.media_candidates(cfg, s, set(), settle_s=0)
        assert [(rel, job_id) for _, rel, _, _, job_id in found] == [(out["path"], job)]
    finally:
        s.close()
