# Darkfluenzer

Lokaler, freigabegesteuerter KI-Medien-Dienst auf Apple Silicon. Verbindliche Spezifikation und
Status: [`docs/PHASENPLAN_V1.md`](docs/PHASENPLAN_V1.md).

## Was heute funktioniert (S1)

- **Darkfluenzer.app** (pinkes Icon, weißes „C“): Doppelklick in Finder, Dock oder Launchpad
  startet die vorhandene ComfyUI und öffnet `http://127.0.0.1:8188` erst nach erfolgreichem
  Health-Check (`/system_stats`). Ein zweiter Doppelklick startet keine zweite Instanz.
- Fenster mit Status, **Stoppen**, **Starten**, **Im Browser öffnen**, **Logs**. Schließen des
  Fensters beendet ComfyUI nicht.
- Eine einzige Start-/Stop-Logik in `src/darkfluenzer/runtime.py`; App und künftiges Backend
  rufen dieselbe CLI/Funktion auf. Gestoppt wird nur die eigene Prozessgruppe (PID + Startzeit +
  Kommandozeile geprüft), nie per `pkill`. Fremd gestartete ComfyUI-Instanzen werden erkannt,
  aber weder übernommen noch beendet.

## Installation (einmalig)

Voraussetzungen: macOS 13+, Apple Silicon, [uv](https://docs.astral.sh/uv/), Xcode Command Line
Tools, eine vorhandene ComfyUI mit eigener Python-Umgebung.

```bash
cp config.example.toml local/config.toml     # Pfade anpassen (ComfyUI, Conda-Python)
ln -s /pfad/zur/ComfyUI local/ComfyUI         # kontrollierter Symlink, nichts wird verschoben
launcher/install.sh                           # venv (uv.lock) + App nach /Applications
```

## Bedienung ohne Terminal

Darkfluenzer im Launchpad/Dock/Finder doppelklicken. Für Diagnose dieselben Befehle per CLI:

```bash
local/.venv/bin/python -m darkfluenzer comfy start|stop|status|health [--json]
```

Logs: `local/logs/comfyui.log` (ComfyUI-Ausgabe, 3 Generationen), `local/logs/darkfluenzer.log`
(Launcher-Aktionen), `local/logs/app.log` (App-Ereignisse und angezeigte Dialoge).

## Struktur

```text
src/darkfluenzer/   app.py (CLI), config.py (local/config.toml), runtime.py (ComfyUI-Prozess)
launcher/           Darkfluenzer.swift, make_icon.swift, install.sh
tests/              pytest, inkl. Prozess-Integrationstests gegen Fake-ComfyUI
local/              NICHT in Git: config.toml, .venv, ComfyUI-Symlink, Modelle, Kunden, Logs
```

## Tests

```bash
UV_PROJECT_ENVIRONMENT=local/.venv uv run pytest
```
