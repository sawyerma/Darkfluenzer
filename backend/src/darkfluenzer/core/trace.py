"""Rückverfolgung der Default-Kette (SP1 Schritt 1): ``darkfluenzer trace --message <id>`` bzw.
``--order <nr>``. Nur lesend über eine schreibgeschützte SQLite-Verbindung – auch während der
Server läuft. Jede Station der Kette wird mit Befund aufgeführt; die erste Unterbrechung wird
benannt: Nachricht, Identität, Default-Zuordnung, Schalter, Befehl, Referenzen, Workflow,
Vorprüfung (Karte und Antwort), Auftrag, Stufen, Jobs mit ``prompt_id`` und Fehler, Medien,
Rückversand."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..media import models
from . import cloner_text


def connect(db_path: Path) -> sqlite3.Connection:
    """Schreibgeschützt öffnen: keine Migration, keine Sperre gegen den laufenden Server."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


class _Trace:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def add(self, step: str, ok: bool | None, detail: str, **data: object) -> None:
        """ok: True bestanden, False Unterbrechung, None nicht zutreffend/zur Kenntnis."""
        self.steps.append({"step": step, "ok": ok, "detail": detail, **data})

    def result(self, **head: object) -> dict:
        first = next((s for s in self.steps if s["ok"] is False), None)
        return {
            "ok": True,
            **head,
            "steps": self.steps,
            "first_break": f"{first['step']}: {first['detail']}" if first else "",
        }


def _rows(db: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return db.execute(sql, args).fetchall()


def _message(db: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT m.*, i.platform, i.account, i.platform_user_id, i.handle, c.customer_no,"
        " c.kind AS customer_kind FROM channel_messages m"
        " JOIN channel_conversations v ON v.id = m.conversation_id"
        " JOIN channel_identities i ON i.id = v.identity_id"
        " JOIN customers c ON c.id = m.customer_id WHERE m.id = ?",
        (message_id,),
    ).fetchone()


def _attachments(row: sqlite3.Row) -> list[dict]:
    return json.loads(row["attachments"] or "[]")


def trace_message(db: sqlite3.Connection, man: models.Manifest, message_id: int) -> dict:
    t = _Trace()
    msg = _message(db, message_id)
    if msg is None:
        t.add("Nachricht", False, f"Nachricht {message_id} unbekannt")
        return t.result(message=message_id)
    atts = _attachments(msg)
    saved = [a for a in atts if a.get("status") == "saved"]
    t.add(
        "Nachricht", msg["direction"] == "in",
        f"#{msg['id']} {msg['direction']} · „{msg['text'][:60]}“ · Anhänge {len(saved)}/{len(atts)}"
        f" gesichert · Status {msg['status']}",
    )  # fmt: skip
    for a in atts:
        if a.get("status") != "saved":
            note = f"{a.get('kind', '?')} {a.get('status', '?')}: {a.get('note', '')}"
            t.add("Anhang", False, note)
    t.add(
        "Identität", True,
        f"{msg['platform']} · Konto {msg['account']} · Nutzer {msg['platform_user_id']}"
        f" (@{msg['handle'] or '–'}) · Akte {msg['customer_no']}",
    )  # fmt: skip
    default = db.execute("SELECT * FROM default_contact").fetchone()
    is_default = default is not None and default["customer_id"] == msg["customer_id"]
    t.add(
        "Default-Zuordnung", is_default,
        "Akte ist der Default-Kontakt" if is_default else "Akte ist nicht der Default-Kontakt",
    )  # fmt: skip
    if not is_default:
        return t.result(message=message_id)
    t.add(
        "Schalter", bool(default["process_commands"]),
        f"Befehle {'an' if default['process_commands'] else 'aus'} · automatische Aufträge "
        f"{'an' if default['auto_orders'] else 'aus'} · Freigabe {default['approval_mode']}",
    )  # fmt: skip
    parsed = cloner_text.parse(msg["text"])
    t.add(
        "Befehl", parsed is not None,
        f"{parsed[0]} · Wunsch „{parsed[1] or '–'}“" if parsed else "kein Befehl erkannt",
    )  # fmt: skip
    replied = None
    if msg["reply_to_platform_id"]:
        replied = db.execute(
            "SELECT * FROM channel_messages WHERE conversation_id = ? AND platform_message_id = ?",
            (msg["conversation_id"], msg["reply_to_platform_id"]),
        ).fetchone()
    quoted = [a for a in _attachments(replied) if a.get("status") == "saved"] if replied else []
    refs = saved or quoted
    source = "keine"
    if saved:
        source = "eigene Anhänge"
    elif replied is not None:
        source = f"Antwort auf #{replied['id']}"
    t.add("Referenzen", None, f"{len(refs)} · {source}", files=[a.get("path") for a in refs])
    if parsed is not None:
        command = parsed[0]
        rows = _rows(db, "SELECT * FROM default_commands")
        commands = {r["command"]: r["workflow"] for r in rows}
        video = command == "animate"
        key = commands.get(command) or default["video_workflow" if video else "media_workflow"]
        wf = man.workflows.get(key or "")
        missing = f"kein registrierter Workflow für {command} ({key or 'leer'})"
        t.add("Workflow", wf is not None, f"{key} · {wf.title}" if wf else missing)
        if wf is not None:
            needs = any(p.upload for p in wf.params.values())
            t.add(
                "Vorprüfung", not needs or bool(refs),
                "Referenz vorhanden" if refs or not needs else "Workflow braucht ein Referenzbild",
            )  # fmt: skip
    _answers(db, t, msg)
    order_id = msg["order_id"] or _card_order(db, message_id)
    if order_id is None:
        t.add("Auftrag", False, "kein Auftrag angelegt")
        return t.result(message=message_id)
    _order_chain(db, t, order_id, msg["conversation_id"])
    return t.result(message=message_id)


def _card_order(db: sqlite3.Connection, message_id: int) -> int | None:
    row = db.execute(
        "SELECT order_id FROM channel_messages WHERE origin_message_id = ? AND direction = 'system'"
        " ORDER BY id LIMIT 1",
        (message_id,),
    ).fetchone()
    return row["order_id"] if row and row["order_id"] else None


def _answers(db: sqlite3.Connection, t: _Trace, msg: sqlite3.Row) -> None:
    """Karte und Chat-Antwort nach der Nachricht bis zur nächsten eingehenden Nachricht."""
    later = _rows(
        db,
        "SELECT id, direction, text, status FROM channel_messages WHERE conversation_id = ?"
        " AND id > ? ORDER BY id LIMIT 30",
        (msg["conversation_id"], msg["id"]),
    )
    cards, replies = [], []
    for row in later:
        if row["direction"] == "in":
            break
        (cards if row["direction"] == "system" else replies).append(row)
    t.add(
        "Karte", bool(cards) or None,
        " | ".join(r["text"].replace("\n", " · ")[:90] for r in cards) or "keine Karte",
    )  # fmt: skip
    t.add(
        "Antwort im Chat", None,
        " | ".join(f"#{r['id']} {r['status']}: {r['text'][:60]}" for r in replies) or "keine",
    )  # fmt: skip


def _order_chain(db: sqlite3.Connection, t: _Trace, order_id: int, conv: int | None) -> None:
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        t.add("Auftrag", False, f"Auftrag {order_id} unbekannt")
        return
    ended_badly = order["status"] in ("cancelled", "refunded")
    head = f"{order['order_no']} · Quelle {order['source']} · {order['kind']}"
    t.add("Auftrag", not ended_badly, f"{head} · Status {order['status']}")
    stages = _rows(db, "SELECT * FROM order_stages WHERE order_id = ? ORDER BY seq", (order_id,))
    if not stages:
        t.add("Stufen", False, "keine Stufe")
    media_paths: list[str] = []
    for stage in stages:
        failed = stage["status"] == "failed"
        detail = f"{stage['kind']} · {stage['workflow']} · {stage['status']}"
        detail += f" · Kandidaten {stage['count']}"
        if stage["selected_media_id"]:
            detail += f" · gewählt Medium {stage['selected_media_id']}"
        if stage["error"]:
            detail += f" · Fehler {stage['error']}"
        t.add(f"Stufe {stage['seq']}", not failed, detail)
        for job in _rows(db, "SELECT * FROM jobs WHERE stage_id = ? ORDER BY id", (stage["id"],)):
            media = _rows(db, "SELECT path FROM media WHERE job_id = ?", (job["id"],))
            media_paths += [m["path"] for m in media]
            bad = job["status"] in ("failed", "cancelled")
            t.add(
                f"Job {job['id']}", not bad,
                f"{job['status']} · prompt_id {job['prompt_id'] or '–'}"
                + (f" · Fehler {job['error']}" if job["error"] else "")
                + (f" · Medien {', '.join(m['path'] for m in media)}" if media else ""),
            )  # fmt: skip
    t.add(
        "Medien", bool(media_paths) or (None if order["status"] == "producing" else False),
        f"{len(media_paths)} Ergebnis(se)" if media_paths else "kein Ergebnis",
    )  # fmt: skip
    if order["source"] != "cloner" or conv is None:
        return
    returns = _rows(
        db,
        "SELECT r.media_id, r.message_id, m.status FROM cloner_returns r"
        " LEFT JOIN channel_messages m ON m.id = r.message_id WHERE r.order_id = ?",
        (order_id,),
    )
    sent = [r for r in returns if r["status"] == "sent"]
    expected = bool(media_paths) and order["status"] not in ("producing", "cancelled")
    listed = " | ".join(
        f"Medium {r['media_id']} → #{r['message_id'] or '–'} {r['status'] or 'offen'}"
        for r in returns
    )
    t.add("Rückversand", bool(sent) if expected else None, listed or "nichts gesendet")


def trace_order(db: sqlite3.Connection, man: models.Manifest, order_no: str) -> dict:
    order = db.execute("SELECT * FROM orders WHERE order_no = ?", (order_no,)).fetchone()
    if order is None:
        t = _Trace()
        t.add("Auftrag", False, f"Auftrag {order_no} unbekannt")
        return t.result(order=order_no)
    stage = db.execute(
        "SELECT params FROM order_stages WHERE order_id = ? ORDER BY seq LIMIT 1", (order["id"],)
    ).fetchone()
    origin = json.loads(stage["params"] or "{}").get("origin") if stage else None
    linked = db.execute(
        "SELECT id FROM channel_messages WHERE order_id = ? AND direction = 'in'"
        " ORDER BY id LIMIT 1",
        (order["id"],),
    ).fetchone()
    message_id = int(origin) if origin else (linked["id"] if linked else None)
    if message_id is not None:
        result = trace_message(db, man, message_id)
        result["order"] = order_no
        return result
    t = _Trace()
    t.add("Nachricht", None, f"{order_no} hat keine Ursprungsnachricht (Quelle {order['source']})")
    _order_chain(db, t, order["id"], None)
    return t.result(order=order_no)


def human(payload: dict) -> str:
    marks = {True: "✓", False: "✗", None: "·"}
    lines = [f"{marks[s['ok']]} {s['step']}: {s['detail']}" for s in payload["steps"]]
    lines.append(f"Erste Unterbrechung: {payload['first_break'] or 'keine'}")
    return "\n".join(lines)


__all__ = ["connect", "human", "trace_message", "trace_order"]
