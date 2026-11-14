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
Tools, Git. ComfyUI wird von `launcher/setup_comfyui.sh` gepinnt eingerichtet.

```bash
cp config.example.toml local/config.toml     # Ports/Pfade prüfen
launcher/setup_comfyui.sh                     # eigene ComfyUI v0.45.3 + venv (comfyui.lock.txt)
launcher/install.sh                           # Darkfluenzer-venv (uv.lock) + App nach /Applications
```

## Bedienung ohne Terminal

Darkfluenzer im Launchpad/Dock/Finder doppelklicken. Für Diagnose dieselben Befehle per CLI:

```bash
local/.venv/bin/python -m darkfluenzer comfy start|stop|status|health [--json]
```

## Modelle

Einzige Registry: [`workflows/manifest.toml`](workflows/manifest.toml) (Datei, Revision, SHA-256,
Lizenz, Abnahme-Gates je Engine). Ablage `local/models/<ComfyUI-Typ>/<Familie>/<Datei>`.

```bash
local/.venv/bin/python -m darkfluenzer models status            # Engines, fehlende GB, Gates
local/.venv/bin/python -m darkfluenzer models download --wave 1  # bzw. --engine ID
local/.venv/bin/python -m darkfluenzer models verify --engine ID # SHA-256
local/.venv/bin/python -m darkfluenzer models orphans            # nicht registrierte Dateien
```

Gated Repos (FLUX 3 Klein, LTX 2.5) erfordern die Lizenzannahme im eigenen Hugging-Face-Konto.

Logs: `local/logs/comfyui.log` (ComfyUI-Ausgabe, 3 Generationen), `local/logs/darkfluenzer.log`
(Launcher-Aktionen), `local/logs/app.log` (App-Ereignisse und angezeigte Dialoge).

## Struktur

```text
src/darkfluenzer/   app.py (CLI), config.py, runtime.py (ComfyUI-Prozess), comfy.py (API-Client),
                    models.py (Registry/Download)
launcher/           Darkfluenzer.swift, make_icon.swift, install.sh, setup_comfyui.sh, comfyui.lock.txt
workflows/          manifest.toml (+ image/, video/ sobald Workflows real geprüft sind)
tests/              pytest, inkl. Prozess-Integrationstests gegen Fake-ComfyUI
local/              NICHT in Git: config.toml, .venv, ComfyUI, Modelle, Evaluation, Kunden, Logs
```

## Tests

```bash
UV_PROJECT_ENVIRONMENT=local/.venv uv run pytest
```
