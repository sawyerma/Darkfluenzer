"""Zugangsdaten über `darkfluenzer secret` (wie p0ctl credential set): Formatprüfung, nie Werte in
der Ausgabe, Ersetzen nur ausdrücklich. Schlüsselbund im Speicher – der echte bleibt unberührt."""

from __future__ import annotations

import io
import json

from darkfluenzer import app, keychain


def _run(monkeypatch, capsys, argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = app.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_secret_set_validates_never_prints_and_replaces_only_explicitly(monkeypatch, capsys):
    vault: dict[str, str] = {}
    monkeypatch.setattr(keychain, "secret", lambda service: vault.get(service))
    monkeypatch.setattr(
        keychain, "store_secret", lambda service, value: vault.update({service: value}) or True
    )
    monkeypatch.setattr(app, "_secret_service", lambda name: f"test.{name}")

    code, out = _run(monkeypatch, capsys, ["secret", "set", "telegram.api_id"], "12ab\n")
    assert code == 1 and "ungültiges Format" in out["error"] and vault == {}
    code, out = _run(monkeypatch, capsys, ["secret", "set", "telegram.api_id"], "1234567\n")
    assert code == 0 and out["verified"] and vault == {"test.telegram.api_id": "1234567"}
    assert "1234567" not in json.dumps(out)
    code, out = _run(monkeypatch, capsys, ["secret", "set", "telegram.api_id"], "7654321\n")
    assert code == 1 and "--replace" in out["error"] and vault["test.telegram.api_id"] == "1234567"
    code, _ = _run(
        monkeypatch, capsys, ["secret", "set", "telegram.api_id", "--replace"], "7654321\n"
    )
    assert code == 0 and vault["test.telegram.api_id"] == "7654321"
    code, out = _run(
        monkeypatch,
        capsys,
        ["secret", "set", "telegram.api_hash"],
        "0123456789abcdef0123456789abcdef\n",
    )
    assert code == 0
    code, out = _run(monkeypatch, capsys, ["secret", "status"])
    assert out["entries"] == {"telegram.api_id": True, "telegram.api_hash": True}
    assert "0123456789abcdef" not in json.dumps(out)
    code, out = _run(monkeypatch, capsys, ["secret", "set", "instagram.token"], "x\n")
    assert code == 2
