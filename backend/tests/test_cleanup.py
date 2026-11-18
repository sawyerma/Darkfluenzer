"""Testprozess-Leck (18.11.2026: 451 verwaiste Fake-ComfyUI-Prozesse): Tests, die über Cockpit oder
Pipeline rendern, starten die Fake-ComfyUI per ``runtime.start`` mit eigener Prozessgruppe; nach dem
Lauf darf keine davon zurückbleiben."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import fake_comfy_pids, reap_fake_comfy

LEAKED_BEFORE = [  # ließen vor der Bereinigung je Lauf eine Fake-ComfyUI zurück
    "tests/test_orders.py::test_failed_post_processing_ends_the_job_as_failed",
    "tests/test_server.py::test_provenance_of_a_rendered_medium",
]


def test_a_test_run_leaves_no_fake_comfy_behind(tmp_path):
    if os.environ.get("DF_INNER_RUN"):
        pytest.skip("innerer Lauf")
    inner = tmp_path / "inner"
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={inner}",
         *LEAKED_BEFORE],
        cwd=Path(__file__).resolve().parents[1], env=os.environ | {"DF_INNER_RUN": "1"},
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    left = fake_comfy_pids(inner)
    reap_fake_comfy(inner)  # nie selbst ein Leck hinterlassen
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    assert left == [], f"zurückgeblieben: {left}"
