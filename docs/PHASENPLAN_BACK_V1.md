# DARKFLUENZER — PHASENPLAN BACK V1

**Version:** 1.7 — BACKEND + PROTOBUF (S1 abgenommen, S2 in Arbeit)
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

## 3. Kompakte Struktur: unabhängiges Backend, Frontend, Protocol

**Verbindliche Sollstruktur nach der kontrollierten Migration**, keine sofortige Verschiebung laufender Dateien:

```text
8_Darkfluenzer/
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/darkfluenzer/   # Python: Runtime, API, Store, Jobs, Modelle, Training, Adapter
│   └── tests/             # Nur gezielte fachliche Tests
├── frontend/              # React/TypeScript/Vite; siehe FRONT-Plan
├── protocol/
│   ├── schemas/darkfluenzer/v1/   # Protobuf-STATE/EVENT/Commands
│   ├── buf.yaml
│   └── buf.gen.yaml
├── launcher/               # Bestehendes pinkes C: nur Start, Stop, Health, Cockpit öffnen
├── workflows/
│   ├── manifest.toml       # Eine Modell-/Workflow-Registry
│   ├── image/              # ComfyUI UI/API-Exporte
│   └── video/
├── docs/
│   ├── PHASENPLAN_BACK_V1.md
│   └── PHASENPLAN_FRONT_V1.md
└── local/                  # Vollständig gitignored
    ├── config.toml
    ├── comfyui.json
    ├── .venv/
    ├── ComfyUI/
    ├── character/
    │   ├── photos/
    │   ├── dataset/
    │   └── previews/
    ├── models/
    ├── evaluation/
    ├── darkfluenzer.sqlite3
    ├── customers/
    │   └── DF-C-000001/
    │       ├── chats/
    │       ├── payments/
    │       └── orders/DF-O-000001/
    │           ├── input/
    │           ├── work/
    │           └── sent/
    └── logs/
```

**Quellstruktur und Laufzeit konsequent trennen:** Kein zweites Kunden-CRM, keine zweite SQLite-Datenbank, keine redundanten Modell-/Manifestdateien. Im laufenden Projekt liegen `pyproject.toml`, `uv.lock`, `src/` und `tests/` zurzeit noch im Root; vor ihrer Migration `launcher/install.sh`, Paketpfade, CI-/Testaufrufe und Konfiguration kontrolliert gemeinsam anpassen, damit das bereits abgenommene S1 nicht bricht.

**Praktische Regeln:** ComfyUI besitzt einen separaten gepinnten Checkout in `local/ComfyUI`. Modellgewichte, Bilddaten, Kundendaten und Secrets gehören ausschließlich nach `local/`, niemals in Git. Workflowversionen stammen aus Git und einer einzigen `workflows/manifest.toml`; jeder Graph hat seine Native-UI- und API-Datei. Kunden und Aufträge erhalten stabile IDs; Kundendatenstatus liegt nur in SQLite, während `input/`, `work/` und `sent/` die zugehörigen Dateien enthalten. Keine Überschreibung freigegebener Artefakte.

**Frontend-Vertrag:** [PHASENPLAN_FRONT_V1.md](PHASENPLAN_FRONT_V1.md) ist ausschließlich für sichtbare GUI, React-Code, Browserverhalten und UI-Protokollbindungsregeln maßgeblich. Dieses BACK-Dokument ist maßgeblich für Betrieb, ComfyUI, Modellinstallation, LoRA, Kundenstatus, Zahlungsprüfung, Persistenz, Plattform-Adapter und serverseitige Protobuf-Publikation.

## 4. Festgelegte Engines — so wenig wie möglich, so viel wie nötig

| Rolle | Auswahl | Verbindlicher Stand |
|---|---|---|
| Medienlaufzeit | **ComfyUI v0.45.3** (eigene Instanz) über `127.0.0.1:8188` | S1 PASS |
| Master-Fotografie | **FLUX 3 Image Klein Base** (BF16) | Primärer Kandidat; Repo gated, kein M4-/Qualitäts-/Lizenz-PASS |
| Master-Benchmarks | **FLUX.2 Dev 32B** (BF16), **Qwen-Image 20B** (BF16), **Qwen-Image 2.1** (BF16) | Nur A/B-Vergleich; kein paralleler Dauerbetrieb |
| Gezielte Spezialbearbeitung | **LUSTIFY! v2.0** (SDXL), maskiertes Inpainting; Vergleich **RealCore Illustrious** | Testkandidaten, nicht garantiert beste Editoren |
| Bild-Nachbearbeitung | Regionale Detailer, Tiled Refine/Upscale | Optional innerhalb eines Refinement-Workflows |
| Video Hauptpfad | **Wan 2.2 Remix NSFW I2V v3.0**, High-/Low-Noise-Paar (nur FP8 verfügbar) | Experimentell; FP8 auf MPS nicht nativ (geprüft) |
| Video Referenz | **Wan 2.2 I2V 14B offiziell** (FP16) | Vergleichsbasis für Remix |
| Video Ersatzpfad | **LTX 2.5 Fast** (22B distilliert, BF16) über ComfyUI | Repo gated; getrennte Abnahme |
| Sprache | **Ein** lokales Textmodell über MLX oder llama.cpp | Checkpoint erst nach A/B-Test festlegen |
| Kundendialog | Telegram Bot API | Festgelegt, noch nicht integriert |
| Zahlungsprüfung | Provider-Adapter | Anbieter/Lizenz/Plattform-Freigabe vor LIVE offen |

**Modellregeln (verbindlich):**
1. **BF16/FP16 bevorzugt**, sofern auf MPS tatsächlich lauffähig. Quantisierte oder kleinere Varianten nur nach dokumentiertem Kompatibilitätstest und **nie stillschweigend als Ersatz**.
2. **Nie alle Modelle gleichzeitig laden.** Pro Auftrag genau eine Engine; ComfyUI entlädt zwischen Engines.
3. Modelle mit nicht-kommerzieller oder ungeklärter Lizenz laufen ausschließlich mit `usage = "evaluation"`. `production` verlangt alle vier Gates PASS (vom Code erzwungen) und deine gesonderte Freigabe.
4. **Jede Datei genau einmal** in `manifest.toml` (Repo, Revision, SHA-256, Ziel). Engines referenzieren Dateien; gemeinsam genutzte Encoder/VAEs werden nie doppelt geladen (Loader verweigert Duplikate per SHA-256).
5. Jede Engine bekommt einen vollständig verdrahteten ComfyUI-Workspace (UI + API) bzw. den unterstützten lokalen Videopfad, auswählbar zum eigenen Vergleich.
6. **Jede Engine einzeln auf dem Mac testen:** Laden, Erzeugung, Dauer, Speicher, Qualität – Ergebnis in `manifest.toml` (Gates) und hier im Nachweis.
7. Die produktive Master-Engine (`[roles] image_master`) ist das beste **technisch funktionierende und für den Zweck lizenzierte** Modell nach A/B-Vergleich auf denselben Prompts/Seeds.
8. **Ablage und Pflege:** `local/models/<ComfyUI-Typ>/<Familie>/<Datei>`; `darkfluenzer models status | download --wave N | --engine ID | verify | orphans`. Entfernen: Engine aus dem Manifest streichen, `orphans` zeigt freiwerdende Dateien; gelöscht wird nur nach Betreiber-OK.
9. Downloads verweigern, wenn danach weniger als `reserve_gb` (30 GB) frei bleiben. Reihenfolge: kleinste fehlende Engine zuerst.

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

**Umsetzungsstand (14.11.2026):** `training.py` + CLI `darkfluenzer character scan|dataset|train-sdxl`: Eingangsprüfung (unvollständige Kopien, Formate, defekte Dateien, SHA-256-Dubletten, Mindestgröße), hash-versionierter Datensatz mit SDXL-Formatbuckets, Originale unverändert, `DATASET_INCOMPLETE` unter 15 Bildern; eigener SDXL-LoRA-Trainer (diffusers/peft, FP32 auf MPS, Attention-LoRA) mit Herkunfts-JSON und Status `trained_not_approved`; Architekturbindung (nur `arch = sdxl`) und Sperre bei laufenden ComfyUI-Renders. **Offen:** Betreiberbilder, Szenen-Captions per lokalem VLM, Gesichts-Identitätsprüfung, Datei-Watcher, Vorschau-/Freigabeschritt, Master-Modell-LoRA (FLUX 3/Qwen).

**Apple-MPS-Verifikation:** Die gewählte Trainingssoftware muss mit dem konkreten Zielmodell real getestet werden. Keine Annahme, dass ein FLUX-3-Inferenzbackend auch FLUX-3-LoRA trainieren kann. Wenn dies auf dem Mac nicht unterstützt wird: den Engpass anzeigen und eine tatsächlich kompatible lokale Alternative prüfen, ohne die Ein-Ordner-Bedienung zu verändern.

## 6B. Frontend-/Backend-Grenze (verbindlich)

Das Creator-Cockpit ist **eine eigenständige React-/TypeScript-/Vite-Webanwendung**, deren Spezifikation ausschließlich in [PHASENPLAN_FRONT_V1.md](PHASENPLAN_FRONT_V1.md) liegt. **Keine native zweite GUI, keine WKWebView, keine Abhängigkeit vom DarkBot-Laufzeitbetrieb.**

Das bestehende Python-Paket bleibt der einzige fachliche Owner. Es stellt beim Ausbau einen lokalen HTTP-Server bereit, der das gebaute React-Frontend und die eigene API **same-origin** ausliefert.

- **Server → GUI:** ein binärer Protobuf-WebSocket `/ws/v1/stream` mit `Hello/Welcome`, `STATE` (vollständige Zustände), `EVENT` (durable Ereignisse), Heartbeat, Cursor/Catch-up und Reconnect; **kein periodisches Frontend-Polling**.
- **GUI → Server:** autorisierte Protobuf-Kommandos `POST /api/v1/command` mit Request-ID, Idempotenz und klarer fachlicher Statusrückmeldung.
- **Große Historien:** auf ausdrückliches Öffnen hin paginierte Protobuf-HTTP-Antworten; Bilder/Videos als kontrollierte Medien-Endpunkte, nicht im WebSocket-STATE.
- **Nur Backend intern:** ComfyUI-Workflow-JSON und dessen JSON-HTTP-API bleiben an `comfy.py` gebunden. Keine JSON-Payload über die Darkfluenzer-GUI-/Backend-Grenze.
- **Plattformen:** Telegram, Meta/Instagram, TikTok, Fanvue und Shop werden nur als voneinander isolierte Backend-Adapter eingebunden, sofern offizielle APIs/Berechtigungen existieren. Eingänge vor Verarbeitung in SQLite persistieren, Nachrichten deduplizieren, Zustellung nur durch Betreiber- und Zahlungsgate.
- **Versionskompatibilität:** Minor-Protobuf-Felder additiv, alte Field-IDs reservieren; beim inkompatiblen Major oder falscher Payload-Bindung UI blockieren statt falsch ausführen. Einmaliges kontrolliertes Frontend-Reload nach Deployment, kein Reload-Loop.
- **Kein Rust-Gateway:** DarkBots Protobuf-/WebSocket-Mechanik **kopieren und unabhängig an Python anpassen**, nicht den Rust-Gateway oder fachfremde Engine-Module übernehmen.
- **Nur implementierte Fähigkeiten zeigen:** Ein noch nicht angebundener Adapter liefert einen ehrlichen `UNAVAILABLE`-Status, keinen Fake-Publisher.

**Betriebsstabilität:** Ein Adapterfehler darf ComfyUI und andere Plattformen nicht stoppen. API-Berechtigungs- und Verbindungsfehler sichtbar melden; nur notwendige Retries und konsistente Backups. Gekoppelte Versionen von Backend/Frontend/Protokoll zusammen deployen; bei fehlerhafter Version zur letzten getesteten Anwendung zurückkehren, ohne Kundendaten oder Freigaben zu verlieren.

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
| S2 | IN_ARBEIT | Erste reale Renders (LUSTIFY): Text-zu-Bild + maskiertes Editing PASS, siehe „S2-Nachweis“; FLUX 3 gated, übrige Modelle laden |
| S3 | OFFEN | Wan-FP8/MPS nicht abgenommen |
| S4 | IN_ARBEIT | SQLite-Kundenakte + stabile, lückenlose Kundennummern getestet (inkl. 12 parallele Erstnachrichten); Telegram/LLM offen |
| S5 | IN_ARBEIT | Liefer-Gate in `approval.py` + SQLite-Triggern isoliert getestet; keine echte Zahlung/Zustellung aktiv |
| S6 | OFFEN | Keine vollständige E2E-Abnahme |

### Mac-Bestand (14.11.2026)

| Punkt | Befund |
|---|---|
| Hardware/OS | MacBook Pro Mac16,6, **Apple M4 Max** (16 CPU = 12P+4E, 40 GPU), 128 GB, macOS 15.6.1 (24G90), 240 GB frei |
| ComfyUI (vorgefunden) | **0.14.1** (`v0.14.1-22-g602b2505`) unter `…/2_DarkMa/0_HRDF/ComfyUI` – unterstützt FLUX 3/Qwen-Image 2.1 nicht. Vom Betreiber am 14.11. nach `0_HRDF.zip` archiviert (Ordner 11:56 entfernt) |
| ComfyUI (Darkfluenzer) | **0.45.3**, eigener Checkout `local/ComfyUI` + venv (Python 3.12.13, torch 2.15.0, torchaudio 2.11.1), Lock `launcher/comfyui.lock.txt`; keine Import-Fehler |
| Netz | WLAN, gemessen ≈ 1,6 MB/s (networkQuality), Hugging Face ≈ 5 MB/s → volle Modellliste (393 GB) braucht Tage |
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

**Regression auf ComfyUI 0.45.3 (eigene Instanz):** CLI-Start 32,8 s (Erststart), App-Start per Finder 10,7 s → Browser danach, Reopen `already_running`, eine Instanz – PASS.

Nicht automatisiert geklickt: die Buttons im App-Fenster (keine Bedienungshilfen-Berechtigung angefordert); sie rufen ausschließlich die oben geprüften CLI-Befehle auf.

### S2-Nachweis (14.11.2026, echter Mac, ComfyUI 0.45.3, MPS)

| Test | Ergebnis |
|---|---|
| Download + Prüfung | LUSTIFY v2.0, 6.938.043.264 Byte, SHA-256 = Manifest, Revision `50b7486d60aa` |
| `lustify_sdxl_t2i` 896×1152, 36 Schritte, dpmpp_2m/karras, CFG 5,5 | PASS – 91,7 s (Kaltstart inkl. Laden), 125–139 s warm; Peak `phys_footprint` 13 GB |
| Reproduzierbarkeit | PASS – Seed 102416 nach Cache-Verdrängung neu berechnet: SHA-256 bitidentisch (`bcff1ea2…`). Hinweis: identische Wiederholung ohne Verdrängung liefert ComfyUI aus dem Cache (0,0 s) – kein Nachweis |
| `lustify_sdxl_inpaint` (Master + Maske 10,9 %) | PASS – 83,5 s; **0 Pixel außerhalb der Maske verändert** (automatische Prüfung); Herkunft: Master-/Masken-Hash, Workflow-Git-Revision |
| Qualität (Sichtprüfung) | OFFEN – fotorealistische Haut/Licht gut; LUSTIFY neigt ohne Kleidungsangabe zu unbekleideten Motiven; Rechteckmaske erzeugt sichtbare Kanten und überschreibt hineinragende Haare → objektgenaue Segmentierungsmasken erforderlich |
| Betreiberpaket `ComfyUI_Cinematic_Studio_M4.zip` (SHA-256 `56cf60f1…`, identisch in Downloads und Projektordner) | übernommen: A01 → `lustify_sdxl_t2i` (65,4 s), A03 → `lustify_sdxl_refine` (72,5 s; mittl. Abweichung 6,3/255, PSNR 27,2 dB, getrennt gespeichert), A04 → `lustify_sdxl_inpaint` (109,3 s; 0 Pixel außerhalb der Maske), B01/B02 → Wan-Workspaces (512×320, 49 Frames, 24 Schritte 12/12, CFG 5, Shift 5). Abweichungen begründet: A04 `VAEEncodeForInpaint`+denoise 0,8 → `SetLatentNoiseMask` (keine Grauflecken); B01/B02 16 statt 24 fps (Wan 2.2 14B nativ 16 fps), ohne CLIP-Vision (in Wan 2.2 14B nicht genutzt, Datei nicht registriert), Core-`CreateVideo/SaveVideo` statt nicht installiertem `VHS_VideoCombine`. A02 (Character-LoRA) erst nach trainierter SDXL-LoRA registrierbar |
| UI-Exporte (Frontend 1.58.5, `graphToPrompt`) | 9 Workspaces 0 Abweichungen, in ComfyUI unter Workflows → Darkfluenzer auswählbar (`darkfluenzer workflows install`); Wan-Video: einzig Alt-Schlüssel `codec`, den das Frontend bei SaveVideo selbst ergänzt |

**PASS nur nach realem Test auf dem Mac, reproduzierbarem Nachweis und Git-Commit.** Ein dokumentierter Plan oder importierbares Workflow-JSON ist noch kein Funktions-PASS. Kein `v1.0`-Release vor S6.

## 8. Strenge Regeln: Dieter Rams auch für Code

**Weniger, aber besser.** Einfachheit ist eine konkrete Entwicklungsanforderung, keine Reduktion der Bild-/Videoqualität oder der wirtschaftlichen Gates.

1. Eine Backend-Anwendung, eine SQLite-Datenbank, ein Modell-/Workflow-Manifest, ein Protobuf-Vertrag, ein React-Frontend. Kein zusätzlicher Broker, separater Gateway-Prozess, Plugin-Framework oder zweiter eigener Produktionsdienst.
2. Erst reale Funktion, dann mögliche Abstraktion. Keine ungenutzten Interface-Schichten, leeren Module, doppelten State-Owner oder Aufteilung einer kleinen Funktion in zehn Dateien.
3. **Wenige gezielte Tests statt Testmasse:** pro neuer Funktion Normalfall, relevanter Fehlerpfad und nur notwendige Regression; ein echter Mac-Test für ComfyUI und ein E2E-Test für die spätere Zahlungs-/Freigabekette. Keine pauschalen hohen Testzähler, großflächigen Mocks oder mehrfachen identischen Gate-Prüfungen ohne zusätzlichen Erkenntniswert.
4. **Sicherheit nicht künstlich maximieren:** Die tatsächlich notwendigen Grenzen bleiben strikt: validierte Eingaben, lokal gebundene Server, geschützte Tokens, autorisierte Schreibbefehle, verifizierte Zahlung, persönliche Betreiberfreigabe, exakte Kunden-/Artefaktbindung. Keine zusätzlichen Security-Subsysteme, komplexen Rollensysteme oder Auditrituale ohne nachgewiesenes Risiko.
5. Keine erfundenen PASS-Berichte: Modell- und GUI-Funktionen erst als betriebsbereit markieren, wenn die passende reale Ausführung tatsächlich geprüft ist. Tests sind Mittel zum Nachweis, kein Selbstzweck.
6. Eigenständige Darkfluenzer-Kopie der relevanten DarkBot-Technik; **niemals** Laufzeitabhängigkeiten, gemeinsame Datenbanken oder verborgene Imports zwischen beiden Projekten.
7. Änderungen direkt auf `main` mit sauberem Git-Paket und Push; bestehende Mac-Daten und S1-Abnahme respektieren.



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

**V1.7 — BACK/FRONT SPLIT (14.11.2026):** bisherigen Masterplan in `PHASENPLAN_BACK_V1.md` überführt; Frontend-Vertrag in `PHASENPLAN_FRONT_V1.md` getrennt. Eine browserbasierte React-GUI, ein Python-Backend, ein binärer Protobuf-WebSocket ohne Polling und ohne JSON-GUI-Payload, eigene statt DarkBot-gekoppelte Quellen. Rams-Prinzip „Weniger, aber besser“ für Oberfläche, Code, Testumfang und notwendige Sicherheit verbindlich. Bestehende S1-/S2-Nachweise erhalten.



**V1.6 — CREATOR-COCKPIT (14.11.2026):** Eine zentrale handlungsorientierte Inbox und Business-Übersicht; Plattform-Adapter für Instagram, TikTok, Telegram, Fanvue und Shop, aber keine API-Fähigkeiten ohne echte Berechtigung voraussetzen. Update-/Ausfallstrategie mit API-Versionen, Health, Retry, Backup und kontrolliertem Rollback, ohne neue Backend-Dienste oder zusätzliche Datenbanken.


**V1.5 — DROP-TO-TRAIN (14.11.2026):** Ein Ordner für Charakterbilder, automatische lokale Datensatzaufbereitung und passende LoRA-Trainingspipeline; kompakte Steuerseite in derselben App. Keine Reduktion der Modell- oder Trainingstests. Alle nachweislichen S1-Fortschritte aus V1.4.1 bleiben unverändert.


**V1.4 — SIMPLIFY (14.11.2026):** Drei überlappende Architekturdokumente zu **einem** verbindlichen Plan konsolidiert; neun Phasen auf sechs zusammengeführt; die übertiefe Code-, Workflow- und Kundenverzeichnisstruktur reduziert; SQLite als einzige Kunden- und Zustandsautorität bestätigt. Bild-/Videotechnik, Zahlungsprüfung, manuelle Freigabe und alle Qualitätsanforderungen unverändert beibehalten.

**V1.4.1 — S1 (14.11.2026):** Mac-Bestand erfasst; Launcher-App, `runtime.py`, `config.py` (einzige Konfigurationsquelle `local/config.toml`), CLI und Tests umgesetzt und auf dem Mac abgenommen. Strukturbaum um `config.py` und die `local/`-Laufzeitdateien ergänzt. Die MPS-High-Watermark bleibt auf PyTorch-Standard.

**V1.5.1 — Modelle (14.11.2026):** Eigene ComfyUI 0.45.3 statt 0.14.1 (FLUX 3/Qwen-Image 2.1 benötigen ≥ 0.4x). Engine-Liste nach Betreibervorgabe erweitert (FLUX.2 Dev, Qwen-Image 20B, RealCore, Wan offiziell); verbindliche Modellregeln §4; Workflow-Namensschema `<engine>_<aufgabe>`; `models.py` und `local/evaluation/` ergänzt. ComfyUI-API-Client (`comfy.py`) mit Parameter-Whitelist, gezieltem Abbruch und Herkunftsdaten.

**V1.5.2 — Kundenakte (14.11.2026):** `store.py` (9 Tabellen, generierte Nummern `DF-C-`/`DF-O-`, erlaubte Statusübergänge, unveränderliche Artefakte/Freigaben/Ereignisse per Trigger, Artefakte 0444 + SHA-256) und `approval.py` (Gate im Code, zweite Schicht als Insert-/Versand-Trigger, idempotente Lieferung je Auftrag). Zahlungen werden nur mit passendem Betrag/Währung im Status `accepted` angenommen; Aufrufer ist künftig ausschließlich der verifizierende Provider-Adapter.

**V1.5.3 — Workflows (14.11.2026):** Erste registrierte Workflows `lustify_sdxl_t2i` und `lustify_sdxl_inpaint` (VAEEncode → SetLatentNoiseMask → KSampler → ImageCompositeMasked; ersetzt das fehleranfällige VAEEncodeForInpaint+denoise<1 aus dem Entwurf A04). UI-Export wird aus dem API-Export mit den echten `/object_info`-Definitionen erzeugt; im ComfyUI-Frontend 1.58.5 per `loadGraphData → graphToPrompt` geprüft: 0 Abweichungen (7 bzw. 12 Nodes). `darkfluenzer workflows check|export-ui`, `darkfluenzer render`, `pipeline.py` mit Pixelprüfung außerhalb der Maske; Evaluationsläufe unter `local/evaluation/<engine>/` mit Herkunfts-JSON.

**V1.5.4 — Bild-Workspaces (14.11.2026):** Registrierte Workspaces für alle Bild-Engines der Welle 1 nach den offiziellen ComfyUI-0.45.3-Templates (vom Frontend selbst aus Subgraphen aufgelöst), jeweils mit BF16-Dateien statt der int8-Template-Varianten: `flux3_klein_base_t2i`, `qwen_image_21_t2i`, `qwen_image_20b_t2i` (ohne Lightning-LoRA), `realcore_illustrious_t2i` (ohne DMD2-Beschleuniger, Sampler wie LUSTIFY für faires A/B), `lustify_sdxl_t2i`, `lustify_sdxl_inpaint`. Frontend-Gegenprobe aller sechs UI-Exporte: 0 Abweichungen. Status je Workflow OFFEN bis zum realen Render.

**V1.6.1 — Erste reale Renders (14.11.2026):** LUSTIFY Text-zu-Bild und maskiertes Editing auf dem Mac PASS (Nachweis oben); Wan-2.2-I2V-Workspaces (offiziell FP16, Remix v3.0 FP8) aus dem offiziellen Template; ComfyUI-Vertragsfehler behoben (`prompt_id` muss UUID mit Bindestrichen sein).

**V1.6.2 — Betreiberpaket (14.11.2026):** Workflows aus `ComfyUI_Cinematic_Studio_M4` als Grundlage übernommen (A01, A03, A04, B01, B02; A02 vorbereitet), technisch notwendige Korrekturen dokumentiert; LUSTIFY-Workflows mit den Paketwerten erneut real abgenommen; Workspaces direkt in der ComfyUI-Seitenleiste.

**Nächste Umsetzung:** Character-LoRA aus den Betreiberbildern (`local/character/photos/`, §6A) für SDXL (A02) und den Master-Pfad; FLUX 3 Klein Base nach Lizenzannahme rendern (Master-Rolle), A/B gegen Qwen-Image 2.1/20B auf identischen Prompts/Seeds; objektgenaue Masken (SAM) für das Editing; LTX-2.5-Workspace; danach S4 (LLM/Telegram).