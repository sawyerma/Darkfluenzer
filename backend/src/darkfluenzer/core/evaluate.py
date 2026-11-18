"""Testsätze der strukturierten Einstufung (SP4 Schritt 4): jeden Fall durch den registrierten
Sprachworkflow schicken und die typisierte Einstufung mit der Erwartung vergleichen. Ergebnis:
Trefferquote je Funktion, Minderjährigkeit mit Fehlalarmen und Verfehlungen getrennt,
Manipulationsversuche, Schema-Gültigkeit und Laufzeiten. Schreibt nichts in die Datenbank.

Aufruf: ``darkfluenzer ai eval --cases <toml> (--influencer ID | --profile <toml>)``."""

from __future__ import annotations

import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..media import models
from ..nodes import llm
from . import assessment


@dataclass(frozen=True)
class Case:
    category: str
    message: str
    context: str = ""
    minor: bool | None = None
    explicit: bool | None = None
    readiness: int | None = None
    readiness_min: int | None = None
    readiness_max: int | None = None


def load_cases(path: Path) -> list[Case]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = [Case(**c) for c in data.get("case", [])]
    if not cases:
        raise ValueError(f"{path}: keine Fälle ([[case]]).")
    return cases


def load_profile(path: Path) -> tuple[dict, dict]:
    """Profil aus einer TOML-Datei: ``[blocks]`` (Profilblöcke) und optional ``[params]``."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("blocks", {})), dict(data.get("params", {}))


def judge(case: Case, typed: assessment.Assessment | None) -> dict[str, bool | None]:
    """Je Funktion: True (getroffen), False (verfehlt), None (nicht erwartet)."""
    if typed is None:
        return {"minor": None if case.minor is None else False,
                "explicit": None if case.explicit is None else False,
                "readiness": None if _no_readiness(case) else False}  # fmt: skip
    readiness = None
    if not _no_readiness(case):
        low = case.readiness if case.readiness is not None else case.readiness_min
        high = case.readiness if case.readiness is not None else case.readiness_max
        readiness = (low is None or typed.purchase_readiness >= low) and (
            high is None or typed.purchase_readiness <= high
        )
    return {
        "minor": None if case.minor is None else typed.minor_hint == case.minor,
        "explicit": None if case.explicit is None else typed.explicit_wish == case.explicit,
        "readiness": readiness,
    }


def _no_readiness(case: Case) -> bool:
    return case.readiness is None and case.readiness_min is None and case.readiness_max is None


def run(
    cfg: Config,
    man: models.Manifest,
    workflow: str,
    blocks: dict,
    params: dict,
    cases: list[Case],
    *,
    facts: str = "",
    progress: Callable[[dict], None] | None = None,
) -> dict:
    rows = []
    for case in cases:
        values = {k: blocks.get(k, "") for k in models.PROFILE_INPUTS}
        values |= {"context": case.context, "memory": "", "facts": facts, "message": case.message}
        values |= {k: v for k, v in params.items() if k in man.workflows[workflow].params}
        started = time.monotonic()
        try:
            result = llm.generate(cfg, man, workflow, values, timeout_s=cfg.ai.run_timeout_s)
            raw, error = result.classification, ""
        except (llm.LlmError, ValueError, OSError) as exc:
            raw, error = "", str(exc)
        typed, why = assessment.parse(llm.parse_classification(raw))
        row = {
            "category": case.category,
            "message": case.message,
            "expected": {
                "minor": case.minor,
                "explicit": case.explicit,
                "readiness": [case.readiness_min, case.readiness_max]
                if case.readiness is None
                else [case.readiness, case.readiness],
            },  # fmt: skip
            "got": vars(typed) | {"wish": vars(typed.wish)} if typed else None,
            "schema_error": why or error,
            "hits": judge(case, typed),
            "seconds": round(time.monotonic() - started, 2),
        }
        rows.append(row)
        if progress:
            progress(row)
    return {"summary": summarize(rows), "rows": rows}


def summarize(rows: list[dict]) -> dict:
    def rate(key: str, only: Callable[[dict], bool] = lambda r: True) -> dict:
        judged = [r for r in rows if only(r) and r["hits"][key] is not None]
        hit = sum(1 for r in judged if r["hits"][key])
        return {
            "cases": len(judged),
            "hits": hit,
            "rate": round(hit / len(judged), 3) if judged else None,
        }

    def minor_is(expected: bool) -> Callable[[dict], bool]:
        return lambda r: r["expected"]["minor"] is expected

    misses = [
        r["message"]
        for r in rows
        if r["expected"]["minor"] is True and r["hits"]["minor"] is not True
    ]
    alarms = [
        r["message"]
        for r in rows
        if r["expected"]["minor"] is False and r["hits"]["minor"] is False
    ]
    seconds = sorted(r["seconds"] for r in rows)
    return {
        "cases": len(rows),
        "schema_valid": sum(1 for r in rows if r["got"] is not None),
        "minor": rate("minor"),
        "minor_misses": misses,  # Abnahme: 0
        "minor_false_alarms": alarms,
        "minor_true_cases": rate("minor", minor_is(True)),
        "minor_false_cases": rate("minor", minor_is(False)),
        "explicit": rate("explicit"),
        "readiness": rate("readiness"),
        "manipulation": {
            key: rate(key, lambda r: r["category"] == "manipulation")
            for key in ("minor", "explicit", "readiness")
        },
        "seconds_p50": seconds[len(seconds) // 2] if seconds else 0,
        "seconds_max": seconds[-1] if seconds else 0,
    }
