# DARKFLUENZER — PHASENPLAN V1

**Version:** 1.5 — SIMPLIFY + DROP-TO-TRAIN (S1 abgenommen)  
**Stand:** 14.11.2026  
**Status:** Zielarchitektur verabschiedet, technische Implementierung und Mac-Abnahme überwiegend OFFEN  
**Repository:** `sawyerma/Darkfluenzer`, Branch `main`  
**Lokal:** `/Users/sawyer_ma/Desktop/Firma/2_DarkMa/8_Darkfluenzer`  
**System:** Apple-Silicon-Mac M4, 128 GB Unified Memory

> **Ein verbindliches Dokument. Eine App. Eine lokale Datenbank. Ein Ordner pro Kunde. Wenige austauschbare Workflows.**  
> Die technische Leistung, Modellqualität, vollständige Kundenhistorie, Zahlungsprüfung und manuelle Betreiberfreigabe bleiben erhalten. Komplexität wird nur dort entfernt, wo sie keinen technischen Nutzen hat.

---

## 1. Exaktes Produktziel

Darkfluenzer ist ein **lokaler, modularer KI-Influencer-Produktionsbot**. Ein eindeutig als virtuell erkennbarer, vollständig synthetischer erwachsener Charakter führt einen privaten Telegram-Dialog. Das System erkennt Bild-/Videowünsche aus dem Gespräch, bietet nach standardmäßig drei qualifizierten Anfragen eine kostenpflichtige Medienerstellung an, prüft die Zahlung, erstellt mit einem lokalen Sprachmodell einen präzisen Prompt, startet bei Bedarf ComfyUI, produziert drei Medienkandidaten und legt sie dem Betreiber auf dem Handy zur Entscheidung vor. Nur ein **bezahltes und persönlich freigegebenes** Bild/Video wird dem richtigen Kunden zugestellt.

**Langfristiges Qualitätsziel:** überzeugende Film-/Fotorealität, konsistente Identität, hochwertige Anatomie, Beleuchtung und Bewegung; „Hollywood-Niveau“ ist kein ungeprüfter PASS-Wert.

**P01-Erstnutzen:** Mac-App mit **pinkem Icon und weißem „C“** startet die vorhandene ComfyUI-Installation per Doppelklick, ohne manuelles Terminal. Dieses Ziel wird **vor** Telegram, Zahlungen und LLM real getestet.

## 2. Ein durchgehender Ablauf

```text
TELEGRAM-KUNDE
    ↓
Kunden-ID anlegen/finden → Chat speichern → Wunsch aus Chat extrahieren
    ↓
3 qualifizierte Medienwünsche ODER explizite Kaufabsicht
    ↓
Klares Angebot für BILD oder VIDEO → Kunde nimmt an
    ↓
Zahlung vom Anbieter serverseitig bestätigt?
    ├─ NEIN → keine kostenpflichtige Produktion/keine Lieferung
    └─ JA
         ↓
Lokales LLM: Auftrag + überprüfbarer Prompt
         ↓
ComfyUI bei Bedarf automatisch starten
         ↓
BILD: Master → optionale Objektmaske/Spezial-Inpainting → Refinement
VIDEO: Master/Startbild → Wan/LTX I2V → zeitliche Prüfung
         ↓
3 Kandidaten mit Seeds, Modell- und Workflow-Versionen
         ↓
PRIVATE BETREIBER-VORSCHAU auf Handy / optional lokale Oberfläche
         ↓
Freigeben | Ablehnen | Neu erzeugen
         ↓
Gate: ZAHLUNG BESTÄTIGT UND BETREIBER FREIGEGEBEN?
    ├─ NEIN → kein Versand
    └─ JA → exakt gewähltes unveränderliches Medium an exakt diesen Kunden
         ↓
Chat, Auftrag, Geld, Medien, Freigabe und Zustellung protokollieren
```

**Zwei unverhandelbare Gates:** Ein LLM, ein Nutzertext oder ein Screenshot kann weder Zahlung bestätigen noch Betreiberfreigabe erteilen. Der Versanddienst prüft **beide** Bedingungen unmittelbar vor Auslieferung.

## 3. Kompakte Ordnerstruktur

Nur **fünf aktive Hauptbereiche** neben `README.md` und erforderlichen Projektdateien:

```text
8_Darkfluenzer/
├── README.md
├── docs/
│   └── PHASENPLAN_V1.md         # EINZIGE verbindliche Planung und Statusübersicht
├── src/darkfluenzer/            # Ein Backend-Prozess, klare Python-Module
│   ├── app.py                   # Start, Routing, Health (heute: CLI `darkfluenzer comfy …`)
│   ├── config.py                # EINZIGE Konfigurationsquelle local/config.toml, Logging
│   ├── runtime.py               # ComfyUI-Prozessstart/stop
│   ├── comfy.py                 # ComfyUI-API und Workflow-Queue
│   ├── pipeline.py              # Bild-/Videoroute, 3 Kandidaten
│   ├── llm.py                   # Kundentext → Intent und Prompt
│   ├── telegram.py              # Kunden-/Betreiber-Nachrichten
│   ├── sales.py                 # Zählung/Angebote
│   ├── payments.py              # Anbieterbestätigung, Erstattung
│   ├── approval.py              # Betreiberfreigabe und Versand-Gates
│   └── store.py                 # SQLite, Artefakte, Kunden-IDs
├── launcher/                    # macOS-.app, pinkes C, Installer
├── workflows/
│   ├── manifest.toml            # ZENTRALE Engine-/Workflow-Registry
│   ├── image/
│   │   ├── master.ui.json       # ComfyUI-Editoransicht
│   │   ├── master.api.json      # API-Aufruf
│   │   ├── edit.ui.json
│   │   ├── edit.api.json
│   │   ├── refine.ui.json
│   │   └── refine.api.json
│   └── video/
│       ├── wan.ui.json
│       ├── wan.api.json
│       ├── ltx.ui.json
│       └── ltx.api.json
├── tests/                       # Reproduzierbare Unit-/Integration-/Mac-Tests
└── local/                       # VOLLSTÄNDIG .gitignore; niemals Git-Upload
    ├── config.toml              # Maschinenpfade/Ports (Vorlage: config.example.toml im Repo)
    ├── comfyui.json             # Identität der verwalteten ComfyUI (PID, Startzeit, Kommando)
    ├── .venv/                   # Darkfluenzer-Python (uv.lock), getrennt von ComfyUI-Conda
    ├── ComfyUI/                 # Vorhandener Checkout oder kontrollierter Symlink
    ├── character/
    │   ├── photos/            # Trainingsbilder einfach hier ablegen
    │   ├── dataset/           # Vom System vorbereitete Daten
    │   └── previews/          # Trainingsvergleich und Identitätsprüfung
    ├── models/                  # Große Gewichte und LoRAs
    ├── darkfluenzer.sqlite3     # EINE zentrale Datenbank
    ├── customers/
    │   └── DF-C-000001/
    │       ├── chats/           # Optionale, aus SQLite erzeugte Exporte
    │       ├── payments/        # Quittungen; Zahlungsstatus bleibt in SQLite
    │       └── orders/
    │           └── DF-O-000001/
    │               ├── input/   # Auftrag, Referenzbilder
    │               ├── work/    # Master, Masken, 3 Kandidaten, Previews
    │               └── sent/    # Tatsächlich ausgelieferte Datei
    └── logs/                    # Rotierende technische Logs ohne Chat-Volltexte
```

**Nicht mehr zulässig:** weitere parallele `local/data`-Datenbanken, `artifacts`-Spiegel, doppelte Statusdateien, pro Workflow `v001/`-Unterordner mit identischen Manifests, zehn kleine Verzeichnisse nur für jeweils eine Backend-Datei.

**Praktische Regeln:**
- `ComfyUI` wird beim Bestandstest lokalisiert; eine bestehende Installation wird nicht blind verschoben.
- Der Git-Commit versioniert Workflows. `manifest.toml` hält pro Workflow nur Engine, Basis-/LoRA-Architektur, benötigte Dateien/Nodes, Status und Freigabe. Kein zusätzlicher Versionsbaum.
- Jeder Kunde erhält bei der ersten Bot-Nachricht einmalig eine **stabile Kundennummer** `DF-C-000001`, dann fortlaufend. Jede Bestellung hat `DF-O-000001`. Niemals Telegram-Nutzername als Dateipfad.
- Kundendaten werden über SQLite gesucht. Die Ordner sind nur Ablage/Export, **keine zweite Wahrheit**.
- Chats bleiben vollständig der Kunden-ID zugeordnet, ebenso Zahlungen, Aufträge, alle Kandidaten, Vorschauen und ausgelieferte Medien. Optionaler Chat-/Zahlungs-Export wird aus SQLite generiert.
- Innerhalb von `work/` gelten **klare Namen statt weiterer Unterordner**: `master.png`, `mask_01.png`, `candidate_01.png` bis `candidate_03.png`, `preview_01.jpg`; Videos `candidate_01.mp4`. Keine Dateiüberschreibung freigegebener Medien.

## 4. Festgelegte Engines — so wenig wie möglich, so viel wie nötig

| Rolle | Auswahl | Verbindlicher Stand |
|---|---|---|
| Medienlaufzeit | **ComfyUI** über `127.0.0.1:8188` | Architektur FIX; lokaler Startertest offen |
| Master-Fotografie | **FLUX 3 Image Klein Base** | Primärer Kandidat, noch kein M4-/Qualitäts-/Lizenz-PASS |
| Bild-Konkurrent | **Qwen-Image 2.1** | Nur A/B-Kandidat; kein paralleler Dauerbetrieb |
| Gezielte Spezialbearbeitung | **LUSTIFY! v2.0** (SDXL), maskiertes Inpainting | Testkandidat, nicht garantiert bester Editor |
| Bild-Nachbearbeitung | Regionale Detailer, Tiled Refine/Upscale | Optional innerhalb eines Refinement-Workflows |
| Video Hauptpfad | **Wan 2.2 Remix I2V**, passendes High-/Low-Noise-Paar | Experimentell; FP8/Apple-MPS-Abnahme offen |
| Video Ersatzpfad | **LTX 2.5 Fast** | Lokale Alternative, getrennte Laufzeit/Abnahme |
| Sprache | **Ein** lokales Textmodell über MLX oder llama.cpp | Checkpoint erst nach A/B-Test festlegen |
| Kundendialog | Telegram Bot API | Festgelegt, noch nicht integriert |
| Zahlungsprüfung | Provider-Adapter | Anbieter/Lizenz/Plattform-Freigabe vor LIVE offen |

**Master-First:** Ein hochwertiges Master-PNG wird einmalig und unveränderlich gespeichert. Normale und spezialisierte Versionen stammen **vom selben Master**. LUSTIFY bearbeitet ausschließlich maskierte Bildregionen; außerhalb der freigegebenen Maske bleibt das zusammengesetzte Bild pixelidentisch. Eine optionale Farbmarkierung von Kleidung ist nur eine **Maskenhilfe**, keine feste Verpflichtung für die sichtbare Bildfarbe. **Kleidungsfarben allein** sind wegen Reflexionen/Überlappungen keine sichere Segmentierung.

**Kein LoRA-Mischen über Architekturen:** FLUX-/Qwen-/SDXL-LoRAs sind nicht austauschbar. Modellwechsel nur über genormte PNG-/Masken- oder Video-Dateien. LUSTIFY rekonstruiert unter Kleidung nichts „Echtes“, sondern generiert die verdeckte Region.

**Keine unbelegten Qualitäts- oder Lizenzbehauptungen:** Ein Modell wird in `manifest.toml` erst nach **LOAD_PASS, RENDER_PASS, QUALITY_PASS, LICENSE_PASS** für die jeweilige Rolle freigegeben. MiniMax-H3-Gewichte gehören aufgrund der bekannten EU-Lizenzlage nicht zur Standardproduktion.

## 5. Eine Datenbank, minimale Tabellen, vollständiger Nachweis

**SQLite** ist zentrale Autorität. Die Tabellen werden nur so weit getrennt wie nötig:

| Tabelle | Inhalt |
|---|---|
| `customers` | Kundennummer, botgebundene Telegram-User-ID, Status |
| `messages` | Nachricht, Gesprächszuordnung, Zeit, deduplizierte Telegram-ID |
| `orders` | Wunsch, Angebot, Typ Bild/Video, Preis, Verkaufsstatus |
| `payments` | Transaktions-ID, Anbieter, Betrag, Währung, Zahlung/Refund |
| `jobs` | zugeordneter Auftrag, Engine, Prompt, Renderstatus, Seeds |
| `artifacts` | Master, Masken, Kandidaten, Dateien und unveränderliche Hashes |
| `approvals` | Freigegebenes Artefakt, Hash, Betreiber, Zeitpunkt |
| `deliveries` | tatsächlich versandtes Artefakt, Kunde, externe Versand-ID |
| `events` | nachvollziehbare Zustandsübergänge und technische Auditdaten |

**Primär-/Fremdschlüssel, Transaktionen und Eindeutigkeitsregeln bleiben Pflicht**, auch bei nur neun Tabellen. Bei mehreren Nachrichten derselben Person muss dieselbe Kundennummer zurückkommen; parallele Erstnachrichten dürfen keine Doppelanlage erzeugen. Eine Zahlung ist nur mit korrekter `order_id`, Betrag, Währung und verifiziertem Provider-Ereignis gültig. Kein API-Retry darf doppelt liefern.

Ein gesamter Kundenauftrag ist anhand seiner Kunden- und Bestellnummer wieder auffindbar. Die Datenbank ist die Quelle für Kundenhistorie, Zahlungen, Freigaben und Liefervorgänge, nicht kopierte Textdateien.

## 6. Verkauf, Bezahlung, Freigabe

- **Verkaufsauslöser:** Drei qualifizierte Medienanfragen pro aktivem Verkaufsdialog (Standard), oder ausdrückliche Kaufbitte. Smalltalk und Dubletten zählen nicht. Preis und Gegenleistung werden vor Kauf klar angegeben.
- **Zahlung:** Kein Auftrag wird als bezahlt markiert, solange der Anbieter kein endgültiges gültiges Zahlungsereignis geliefert hat; `pre_checkout` und Kundenscreenshots genügen nicht. Für digitale Güter in Telegram ist Telegram Stars der dokumentierte Zahlungsweg. Vor Erwachsenen-Content-LIVE sind die Plattformbedingungen separat zu prüfen; **PayPal ist hierfür nicht automatisch geeignet**.
- **Generierung:** Nach gültiger Zahlung aus dem Chat einen typisierten Auftrag erstellen; die Engine erzeugt genau drei Kandidaten. Erneute Generierung schafft neue Kandidaten-IDs, keine stille Überschreibung.
- **Freigabe:** Betreiber erhält private Handy-Vorschau oder lokale UI, sieht Kundennummer, Auftrag, Bezahlstatus, drei Bilder/Videos und kann **Freigeben, Ablehnen, Neu erzeugen**.
- **Lieferbedingung:** `PAYMENT_CONFIRMED && OPERATOR_APPROVED && ARTIFACT_HASH_MATCH && CUSTOMER_MATCH`. Der Delivery-Service prüft alle Bedingungen **erneut im Versandmoment**. Abbruch, Refund oder veränderte Datei sperren die Lieferung.
- **Zustellungsgenauigkeit:** idempotente Versand-ID; keine Doppelzustellung bei Neustart/Timeout. Nicht lieferbare bezahlte Aufträge bekommen eine geregelte Überarbeitung/Erstattung.
- **Trennung der Autoritäten:** Das Sprachmodell darf Kunden antworten und Prompts schreiben, aber keine Bestätigung von Zahlung/Freigabe oder freie Dateisystem-/Shellbefehle ausführen.

## 6A. Character-LoRA — Drag-and-drop ohne Einrichtung

**Nutzerinteraktion:** Einziger Eingabeordner `local/character/photos/`. Betreiber kopiert JPG-, PNG- oder WebP-Bilder der eigenen synthetischen erwachsenen Figur in diesen Ordner. **Keine manuellen Trainingsdateien, Caption-Texte, JSON-Konfigurationen oder ComfyUI-Node-Verdrahtung.** Ein Datei-Watcher erkennt abgeschlossene Kopiervorgänge und fasst die neuen Bilder zu **einem Datensatz-Batch** zusammen; er startet nicht nach jedem Bild ein neues Training.

**Implementierung im bestehenden Python-Paket**, vorzugsweise `training.py`; nur wenn ein realer Bedarf nachgewiesen wird, zusätzliche Dateien/Unterordner schaffen:

1. Dateibatch erkennen; unvollständige Dateien, Duplikate (SHA-256), defekte oder stark ungeeignete Bilder abweisen. Originaldateien unverändert lassen.
2. Bildprüfung und Qualitäts-/Identitätskonsistenzcheck lokal; unterschiedliche Personen oder zweifelhafte Zuordnungen dem Betreiber anzeigen.
3. Versionierten Trainingsdatensatz erzeugen und automatisch lokal beschriften; trainierte Identitätsmerkmale von Szenen-/Outfitdaten trennen, damit die LoRA flexibel bleibt.
4. Lokale Trainingsengine **modellfamilienabhängig** wählen: Master-Modell-LoRA für den gewählten FLUX-/Qwen-Pfad; eine eigene **SDXL-LoRA** für LUSTIFY nur bei Bedarf. **Keine Architektur-fremde LoRA.**
5. Training erst beginnen, wenn ausreichender, plausibler Datensatz vorliegt und die gewählte Trainingsengine nachweislich auf dem M4 läuft. Ansonsten eindeutig `DATASET_INCOMPLETE` oder `TRAINER_UNAVAILABLE`, keine Schein-Fertigmeldung.
6. Training und Ergebnis als unveränderliche Version mit Datensatz-Hash/Modellhash/Trainingsparametern speichern. Trainingsergebnisse unter `local/models/`, Vorschauen unter `local/character/previews/`.
7. Feste Vergleichsprompts erzeugen; Identität, Gesichtsvariationen und Generalisierung prüfen. **Aktivierung einer neuen LoRA nach Sichtfreigabe des Betreibers**, alte Version bleibt bis dahin aktiv.
8. Spätere neue Fotos ergeben eine neue Datensatz-/LoRA-Version statt ein unkontrolliertes Nachlernen im laufenden Rendering. Keine parallelen GPU-intensiven Trainings- und Kunden-Renderjobs.

**Apple-MPS-Verifikation:** Die gewählte Trainingssoftware muss mit dem konkreten Zielmodell real getestet werden. Keine Annahme, dass ein FLUX-3-Inferenzbackend auch FLUX-3-LoRA trainieren kann. Wenn dies auf dem Mac nicht unterstützt wird: den Engpass anzeigen und eine tatsächlich kompatible lokale Alternative prüfen, ohne die Ein-Ordner-Bedienung zu verändern.

## 6B. Bedienoberfläche — bewusst minimal

Darkfluenzer bekommt eine **kompakte, lokale Steuerseite in derselben App**, kein zweites Dashboard-Produkt und keine zusätzliche Backend-Infrastruktur. Die Bild-/Videographen bleiben in ComfyUI.

- **Charakter:** Ordnerpfad öffnen, Anzahl geprüfter Bilder, laufende Trainerphase/Fortschritt, aktuelle und neue LoRA, Ergebnisvorschauen, LoRA-Freigabe.
- **Produktion:** ComfyUI starten/öffnen, Status der verfügbaren Engines und Workflows, Warteschlange, letzte Ergebnisse.
- **Kunden:** Kundennummer, Chat-/Auftragsübersicht, Zahlungsstatus, drei private Vorschauen, manuelle Freigabe; die Freigabe per privatem Betreiber-Telegram ist weiterhin möglich.
- **Keine separate App**, kein eigener Microservice, kein zweiter Datenspeicher. Bedienseite nutzt vorhandenen lokalen Backend-Prozess und SQLite.

**S1 unverändert:** Das pinke C muss ComfyUI ohne Terminal starten. Die zusätzliche Steuerseite ist eine spätere Ergänzung; sie darf S1 nicht wieder öffnen oder seinen nachgewiesenen Status zurücksetzen.

## 7. Nur sechs Phasen

| Phase | Ziel | Abnahme |
|---|---|---|
| **S1 — Starter** | Mac-Bestand erfassen; pinke `C`-App startet/stoppt ComfyUI | Doppelklick, Health, idempotenter Neustart; keine fremden Prozesse gekillt |
| **S2 — Foto** | Masterbild + Identität + Masken/SDXL-Editing + Refinement | Drei reproduzierbare Fotos, Master-Herkunft, lokale Qualitätsbewertung |
| **S3 — Video** | Wan-I2V und LTX-Vergleich, Motion/Temporal/Export | Real gerenderter Mac-Clip, FPS, Dauer, Speicher, Flicker/Identität geprüft |
| **S4 — Dialog** | Lokales LLM + Telegram + stabile Kundennummer + SQLite + Drei-Anfragen-Angebot | Derselbe Kunde behält seine Nummer; Chat-/Intent- und Angebotsfälle getestet |
| **S5 — Verkauf** | Verifizierte Zahlung + private Vorschau + manuelle Freigabe + Versand | Ohne Zahlung ODER Freigabe: null Lieferungen; korrekter Kunde/Hash |
| **S6 — Betrieb** | Recovery, Backup, Sicherheit, Lizenzprüfung und Ende-zu-Ende-Abnahme | Neustart-/Dubletten-/Refund-Tests, vollständiger bezahlter Testauftrag |

Die bisherigen neun Phasen `P00–P08` werden **inhaltlich vollständig** in `S1–S6` übernommen: `P00+P01→S1`, `P02→S2`, `P03→S3`, `P04+P05→S4`, `P06→S5`, `P07+P08→S6`. **Keine funktionale Stufe wurde gestrichen.**

### Fortschritt

| Phase | Status | Nachweis |
|---|---|---|
| S1 | PASS | Mac-Abnahme 14.11.2026, siehe „S1-Nachweis“ |
| S2 | OFFEN | Keine reproduzierten Modell-Renderläufe |
| S3 | OFFEN | Wan-FP8/MPS nicht abgenommen |
| S4 | OFFEN | Keine implementierte Telegram-/LLM-/SQLite-Kette |
| S5 | OFFEN | Kein Payment-/Operator-Gate implementiert |
| S6 | OFFEN | Keine vollständige E2E-Abnahme |

### Mac-Bestand (14.11.2026)

| Punkt | Befund |
|---|---|
| Hardware/OS | MacBook Pro Mac16,6, **Apple M4 Max** (16 CPU = 12P+4E, 40 GPU), 128 GB, macOS 15.6.1 (24G90), 240 GB frei |
| ComfyUI | **0.14.1** (`v0.14.1-22-g602b2505`), Git-Checkout `…/2_DarkMa/0_HRDF/ComfyUI`, eingebunden als Symlink `local/ComfyUI`; unverändert |
| Python | Conda-Env `comfyui`: Python 3.11.14, torch 2.10.0 (Nightly), MPS verfügbar, FP16/BF16-Matmul OK, **FP8 auf MPS: nicht unterstützt** (geprüft) |
| Manager | `--enable-manager` von 0.14.1 unterstützt, `comfyui-manager` 4.1b1 lädt |
| Modelle | Nur VAEs (flux1/flux2/SeedVR2), `clip_l`, SAM ViT-B. **Keine Checkpoints/Diffusionsmodelle, keine LoRAs** |
| Custom Nodes | KJNodes, Impact Pack, essentials, LayerStyle, rgthree, SeedVR2 (2×), FluxTrainer, promptmodels |
| Umgebungsfehler (vorbestehend) | torchaudio 2.4.1 ≠ torch 2.10 → Audio-Nodes (inkl. `nodes_lt_audio`) laden nicht; FluxTrainer: `transformers` 5.2 ohne `CLIPFeatureExtractor`; LayerStyle: `opencv-contrib` fehlt (`guidedFilter`) |
| Projektordner | `1_ComfyUI /0_Software/ComfyUI_Cinematic_Studio` (Entwurfs-Workflows A01–A04 SDXL, B01/B02 Wan) – unverändert belassen, per `.gitignore` ausgeschlossen |

### S1-Nachweis (14.11.2026, echter Mac)

Start über `Finder → open /Applications/Darkfluenzer.app` (LaunchServices, identisch zum Doppelklick); Belege in `local/logs/app.log` und `local/logs/darkfluenzer.log`.

| Test | Ergebnis |
|---|---|
| Start aus vollständig gestopptem Zustand | PASS – bereit nach 5,1–11,3 s, `system_stats` meldet ComfyUI 0.14.1 / mps |
| Browser erst nach Bereitschaft | PASS – „ComfyUI bereit“ 44,189 s → „Browser öffnen“ 44,265 s; Chrome hält Verbindungen zu :8188 |
| Zweiter Doppelklick (App offen) / nach App-Ende | PASS – `already_running`, stets genau eine PID auf :8188; App-Ende lässt ComfyUI laufen |
| Stop beendet nur die eigene Instanz | PASS – `runtime.stop` (vom App-Button 1:1 aufgerufen) beendet eigene Gruppe; fremd gestartete ComfyUI (manuell, PID 34853) wird erkannt, Dialog „weder übernommen noch beendet“, Stop → `not_managed`, Prozess lebt weiter |
| Erneuter Start nach Stop | PASS |
| Fehlerhafter Python-Pfad | PASS – Dialog „ComfyUI-Python nicht gefunden …“, Exit 2, kein Zustand |
| Fehlgeschlagener Start | PASS – ungültiges ComfyUI-Argument → Exit 4 mit Logauszug, Zustand gelöscht, kein Restprozess |
| Kein Terminal nötig | PASS – Installation einmalig per `launcher/install.sh`, danach nur Doppelklick |
| Automatisierte Tests | 17/17 `pytest` (Prozess-Integration gegen Fake-ComfyUI: Idempotenz, fremde Instanz, PID-Wiederverwendung, Timeout, Crash) |

Nicht automatisiert geklickt: die Buttons im App-Fenster (keine Bedienungshilfen-Berechtigung angefordert); sie rufen ausschließlich die oben geprüften CLI-Befehle auf.

**PASS nur nach realem Test auf dem Mac, reproduzierbarem Nachweis und Git-Commit.** Ein dokumentierter Plan oder importierbares Workflow-JSON ist noch kein Funktions-PASS. Kein `v1.0`-Release vor S6.

## 8. Strenge Regeln trotz reduzierter Struktur

1. **Single Source of Truth:** Diese Datei ist der einzige normative Masterplan. Technische Kommentare oder Tests dürfen Regeln präzisieren, nicht widersprechen.
2. **Ein Programm, modulare Funktionen:** Ein lokaler Python-Dienst mit getrennten Modulen, kein selbstgebautes Microservice-System, kein zusätzlicher Message-Broker, kein Docker-Zwang.
3. **Wenig Ordner, klare Eigentümer:** Ein Codepaket, ein Workflow-Verzeichnis, ein Kundenbaum, eine SQLite-Datenbank. Keine redundanten Kopien und konkurrierenden Statusdateien.
4. **Workflow-Verträge:** ComfyUI braucht UI-JSON und separaten API-Export; nur registrierte und validierte API-Workflows dürfen vom Bot ausgeführt werden.
5. **Kein globales `pkill`:** Launcher verwaltet nur die eigene Instanz; ComfyUI an `127.0.0.1:8188` und startet ohne Terminal. Python-/Conda-Pfad wird lokal konfiguriert, nicht im Code erzwungen.
6. **Sicherheit und Reproduzierbarkeit:** Secrets außerhalb Git (macOS Keychain oder geschützte lokale Konfiguration), alle privaten Daten in `local/`; Modell-Hashes, Seeds, Workflow-Git-Revisionen und Freigaben dokumentieren.
7. **Deterministische kritische Regeln:** Zahlung, Sales-Zähler, Kundenzuordnung und Liefer-Gate werden durch Code/DB bestimmt, **nicht** durch den LLM-Wortlaut.
8. **Tests statt Annahmen:** Apple-MPS-Backend, Custom Nodes, Quantisierung, Lizenz und Renderqualität müssen tatsächlich geprüft werden; Qualitätsverbesserung nur mit A/B-Vergleich.
9. **Klarer Änderungsweg:** Änderungen auf `main` mit Commit und dokumentierter Planänderung. Kein neues Hilfsverzeichnis, solange nicht ein konkreter Test oder Bedienungsfall dies erforderlich macht.
10. **Fiktive erwachsene Figur:** keine fremde Person imitieren; Transparenz über künstliche Identität, vereinbarte Inhalte und kommerzielle Rechte.

## 9. Änderungsprotokoll

**V1.5 — DROP-TO-TRAIN (14.11.2026):** Ein Ordner für Charakterbilder, automatische lokale Datensatzaufbereitung und passende LoRA-Trainingspipeline; kompakte Steuerseite in derselben App. Keine Reduktion der Modell- oder Trainingstests. Alle nachweislichen S1-Fortschritte aus V1.4.1 bleiben unverändert.


**V1.4 — SIMPLIFY (14.11.2026):** Drei überlappende Architekturdokumente zu **einem** verbindlichen Plan konsolidiert; neun Phasen auf sechs zusammengeführt; die übertiefe Code-, Workflow- und Kundenverzeichnisstruktur reduziert; SQLite als einzige Kunden- und Zustandsautorität bestätigt. Bild-/Videotechnik, Zahlungsprüfung, manuelle Freigabe und alle Qualitätsanforderungen unverändert beibehalten.

**V1.4.1 — S1 (14.11.2026):** Mac-Bestand erfasst; Launcher-App, `runtime.py`, `config.py` (einzige Konfigurationsquelle `local/config.toml`), CLI und Tests umgesetzt und auf dem Mac abgenommen. Strukturbaum um `config.py` und die `local/`-Laufzeitdateien ergänzt. Die MPS-High-Watermark bleibt auf PyTorch-Standard.

**Nächste Umsetzung:** ComfyUI-API-Client (`comfy.py`), danach S2-Masterbild – blockiert, bis ein Master-Modell lokal liegt.