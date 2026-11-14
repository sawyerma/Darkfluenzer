# DARKFLUENZER — PHASENPLAN V1

**Dokument:** `docs/PHASENPLAN_V1.md`  
**Version:** 1.0  
**Stand:** 14.11.2026  
**Status:** Verbindlicher Architektur- und Umsetzungsplan; Implementierung und lokale Abnahme noch ausstehend  
**Repository:** [sawyerma/Darkfluenzer](https://github.com/sawyerma/Darkfluenzer)  
**Zielsystem:** Apple-Silicon-Mac M4, 128 GB Unified Memory, macOS  
**Projektverzeichnis:** `/Users/sawyer_ma/Desktop/Firma/2_DarkMa/8_Darkfluenzer`

---

## 1. Produktziel und verbindlicher Endzustand

Darkfluenzer wird als **lokal betriebenes, modular aufgebautes KI-Medienproduktionssystem** entwickelt. Zunächst startet ein macOS-App-Icon ComfyUI zuverlässig mit einem Doppelklick. Darauf aufbauend kann ein autonomer Agent Kundenanfragen über einen privaten Telegram-Kanal bzw. Telegram-Bot entgegennehmen, im Charakter einer eindeutig virtuellen erwachsenen Influencerin antworten, durch ein lokales Sprachmodell Produktionsaufträge formulieren, lokale Bild-/Video-Workflows über die ComfyUI-API ausführen, je Auftrag **drei Vorschläge** erzeugen und sie dem Betreiber zur Prüfung vorlegen.

**Ohne ausdrückliche Betreiberfreigabe erfolgt keine Weiterleitung an den Kunden.** Nach Freigabe liefert das System ausschließlich die genehmigte Variante aus, protokolliert den Vorgang und hält die Unterhaltung getrennt vom Mediengenerator.

### 1.1 Zielablauf

1. Kunde sendet Telegram-Nachricht an den Bot.
2. Eingang wird validiert, dem Kundenkontext zugeordnet und als Auftrag erfasst.
3. Lokales LLM erstellt eine normale Kundenantwort und einen strukturierten internen Medienauftrag; Prompt-/Workflow-Erzeugung ist nachvollziehbar.
4. Orchestrator wählt einen freigegebenen Bild- oder Video-Workflow und startet bei Bedarf ComfyUI automatisch.
5. ComfyUI generiert standardmäßig **drei** Varianten mit nachvollziehbaren Seeds/Parametern.
6. Vorschauen werden ausschließlich dem Betreiber über einen privaten Freigabekanal und optional über ein lokales Dashboard zugestellt.
7. Betreiber genehmigt genau eine Variante, lehnt ab oder fordert Überarbeitung an.
8. Erst der autorisierte Freigabeentscheid erlaubt dem Versandmodul die Zustellung an den ursprünglichen Kunden.
9. Status, Fehlermeldungen, Zeiten, Modellversionen und Auslieferung werden revisionsfähig protokolliert.

### 1.2 Qualitätsziel

- Eine über Bilder und Videos wiedererkennbare **vollständig synthetische, eindeutig erwachsene** Figur.
- Fotorealistische Haut, Haare, Proportionen, Perspektive, Lichtsetzung und konsistente Identität.
- Bildvarianten, Inpainting, Detailer, Tiled Refinement und geeignetes Upscaling.
- Video: nachvollziehbare Referenzbilder, Pose-/Bewegungssteuerung, zeitliche Konsistenz, segmentierte Clips und Nachbearbeitung.
- Das Ziel „Hollywood-/Realfilm-Niveau“ ist eine **Qualitätsanforderung**, keine garantierte oder bereits nachgewiesene Modelleigenschaft. Abnahme erfolgt anhand festgelegter Testmotive und Sichtung der Ergebnisse.

### 1.3 Harte Grenzen

- Vollständige lokale Bild-/Videogenerierung; keine verpflichtende fremde Inferenz-API.
- Modulare Architektur: Telegram, LLM, Orchestrator, ComfyUI, Freigabe und Versand unabhängig austauschbar.
- Kein Versand an Kunden ohne nachweisbare, auftragsbezogene Freigabe.
- Keine vorgetäuschte technische Funktionsfähigkeit; jede Phase benötigt Tests auf dem tatsächlichen Mac.
- Keine Änderungen an anderen Projekten oder deren Laufzeitumgebungen.
- Nutzung ausschließlich eigener bzw. hinreichend lizenzierter Modellgewichte, Daten und Medien. Für Adult-Angebote: nur eindeutig erwachsene, synthetische Figuren; erforderliche Alters-/Inhalts- und Plattformvorgaben vor der Produktivschaltung prüfen.

---

## 2. Verbindliche Projekt- und Entwicklungsregeln

1. **Eine Autoritätsquelle:** Dieser Phasenplan ist maßgeblich. Ergänzungen und Statusänderungen werden dokumentiert, nicht mündlich unterstellt.
2. **Strikte Trennung:** Produktionscode, Konfiguration, Workflows, Modellgewichte, Daten, Ausgaben und Logs sind getrennte Bereiche.
3. **Keine stillen Nebenwirkungen:** Start/Stop betrifft ausschließlich die eigene ComfyUI-Instanz. Kein globales `pkill -9 -f "python main.py"`.
4. **Keine hartcodierten Zugangsdaten:** Telegram-Tokens, API-Secrets und Betreiberkennungen bleiben in lokalem Secret-Store bzw. ignorierten Konfigurationsdateien.
5. **Keine Modellgewichte in Git:** Große Checkpoints, virtuelle Umgebungen, temporäre Medien und personenbezogene Kundeninhalte niemals committen.
6. **Reproduzierbarkeit:** Git-Commit, Python-/Conda-Umgebung, Modell-Hashes, Workflow-Versionen und produktionsrelevante Parameter erfassbar.
7. **Robustheit:** Idempotente Starts, definierte Stopps, Health-Checks, Timeouts, Retry-Budgets, atomare Zustandsübergänge.
8. **Tests vor Fertigmeldung:** Jede Phase hat messbare Abnahmekriterien, dokumentierten Nachweis und Git-Commit.
9. **Keine Qualitätsbehauptung ohne A/B-Test:** Modellrankings, „professionell“ und „maximale Qualität“ gelten erst nach methodischer Prüfung als belegt.
10. **Auslieferung als privilegierte Aktion:** Nur ein autorisierter Approval-Service kann die Versandfreigabe erteilen; die LLM-Ausgabe niemals direkt.
11. **Direkt auf `main`:** Solange nichts anderes beschlossen wird; pro abgeschlossenem Paket sauber committen und pushen.
12. **Minimaler Initialumfang:** Zuerst der funktionierende Launcher. Telegram, LLM und Medienautomatisierung folgen erst in ihren vorgesehenen Phasen.

---

## 3. Ziel-Verzeichnisstruktur

```text
8_Darkfluenzer/
├── README.md
├── docs/
│   ├── PHASENPLAN_V1.md             # Verbindlicher Masterplan
│   ├── ARCHITEKTUR.md               # Komponenten, APIs, Zustandsübergänge
│   ├── BETRIEB.md                   # Installieren, Starten, Stoppen, Fehlerdiagnose
│   ├── MODELLE_LIZENZEN.md          # Modellstand, Hash, Lizenz, Apple-Abnahme
│   ├── TESTPLAN.md                  # Reproduzierbare Abnahmetests
│   └── STATUS.md                    # Ist-Zustand, offene Punkte, Evidenz
├── apps/
│   ├── macos-launcher/              # App-Bundle, pinkes Icon, Doppelklick-Starter
│   └── operator-ui/                 # Spätere lokale Freigabe-/Monitoring-Oberfläche
├── src/darkfluenzer/
│   ├── core/                        # Konfiguration, Typen, Zustände, Ereignisse
│   ├── runtime/                     # Prozessverwaltung, Start/Stop, Health
│   ├── comfy/                       # ComfyUI-API, Workflow-Registry, Queue
│   ├── llm/                         # Lokale Sprachmodell-Anbindung
│   ├── identity/                    # Figuren-/Referenzprofile
│   ├── jobs/                        # Auftragserzeugung, Orchestrierung
│   ├── review/                      # Freigabe, Reject, Revision
│   ├── telegram/                    # Kunden- und Betreiberkanal getrennt
│   ├── delivery/                    # Ausschließlich freigegebene Zustellung
│   ├── storage/                     # Metadaten und Artefaktverwaltung
│   └── observability/               # Logs, Metriken, Health
├── workflows/
│   ├── images/
│   │   ├── base/                    # LUSTIFY, SDXL
│   │   ├── identity/                # Character-LoRA, Referenzkontrolle
│   │   ├── inpainting/              # Lokale Korrektur
│   │   └── refinement/              # Detailer, Tiled Diffusion, Upscaling
│   └── video/
│       ├── wan/                     # Wan 2.2 I2V / Remix
│       ├── ltx/                     # LTX-Alternative
│       └── temporal/                # Clip-Fortsetzung, Frame-Konsistenz
├── configs/
│   ├── examples/                    # Vorlagen ohne Geheimnisse
│   └── schemas/                     # Konfigurations-/Auftragsverträge
├── scripts/                         # Installation, Diagnose, Migration, Tests
├── tests/
│   ├── unit/
│   ├── integration/
│   └── acceptance/
├── assets/
│   └── icons/                       # Eigene App-Icons (keine Kundendaten)
└── local/                            # Vollständig Git-ignoriert
    ├── ComfyUI/                     # Tatsächlicher ComfyUI-Checkout oder Symlink
    ├── models/                      # Gewichte und LoRAs
    ├── envs/                        # Lokale Umgebungen
    ├── config/                      # Lokale Konfiguration und Secrets
    ├── data/                        # Datenbank und Aufträge
    ├── input/                       # Referenz- und Eingangsmedien
    ├── output/                      # Generierte Medien
    ├── previews/                    # Betreiber-Vorschauen
    ├── logs/                        # Rotierende Laufzeitlogs
    └── run/                         # PID/Lock/Socket; keine dauerhaften Daten
```

**Pfadregel:** Das tatsächliche vorhandene ComfyUI-Verzeichnis ist zuerst zu ermitteln. Eine bestehende Installation wird **nicht** blind verschoben. Stattdessen wird ihr absoluter Pfad konfigurierbar hinterlegt oder kontrolliert unter `local/ComfyUI` verlinkt.

---

## 4. Phasen mit verbindlicher Abnahme

### P00 — Bestand und technische Grundlagen

**Ziel:** Ist-Zustand sichern, bevor etwas installiert oder überschrieben wird.

**Arbeiten**
- Lokalen Projektpfad, ComfyUI-Verzeichnis, Python/Conda-Umgebung und vorhandene Modelle ermitteln.
- macOS-Version, Chipvariante, PyTorch/MPS, freie SSD-Kapazität und die ComfyUI-Version aufnehmen.
- Repository-Zustand, `.gitignore`, Konfigurationspfade, Startup-Flags und vorhandene Prozesse dokumentieren.
- `docs/ARCHITEKTUR.md`, `docs/BETRIEB.md`, `docs/STATUS.md` anlegen.

**Abnahme**
- Pfade und verwendete Python-Umgebung eindeutig dokumentiert.
- Keine vorhandene Installation oder Konfiguration beschädigt.
- Diagnosebefehl liefert verständlichen Status und Fehlercodes.

**Status:** OFFEN.

### P01 — macOS-Launcher mit pinkem C (erste funktionale Lieferung)

**Ziel:** Ein Klick auf das App-Icon startet ComfyUI **ohne Terminalbedienung**.

**Arbeiten**
- Eigenes macOS-`.app`-Bundle mit **pinkem Hintergrund, weißem „C“** und dem App-Namen **Darkfluenzer** erstellen; im Dock/Launchpad startbar.
- Nach dem Start ComfyUI-Prozess im vorgesehenen Python-/Conda-Environment starten. Die genaue Python-Binärdatei wird aus P00 übernommen.
- `PYTORCH_ENABLE_MPS_FALLBACK=1` nur dort setzen, wo benötigt; Speicher-/Watermark-Variablen nach reproduziertem MPS-Test konfigurieren, nicht pauschal abschalten.
- `--enable-manager` nur verwenden, wenn von der installierten ComfyUI-Version unterstützt.
- Lokalen Health-Check auf `127.0.0.1:8188`; Browser erst nach erreichbarem Server öffnen.
- Bereits laufende eigene Instanz erkennen und Browser öffnen, **keinen zweiten Prozess erzeugen**.
- Starter beendet keine fremden Python-Prozesse. Separater sicherer Stop-Befehl und Status-Abfrage.
- Logs mit festen Dateipfaden, Fehlermeldung mit konkretem Reparaturhinweis, keine Pflicht zum Terminal.

**Abnahme**
- App per Doppelklick startet ComfyUI aus gestopptem Zustand.
- Zweiter Doppelklick öffnet denselben Server; genau eine verwaltete Instanz.
- ComfyUI-Oberfläche wird im Browser geöffnet.
- Beenden stoppt nur den verwalteten Prozess; Neustart funktioniert.
- Protokollierung vorhanden; Tests auf dem tatsächlichen Mac bestanden.
- App-Icon entspricht der Designvorgabe (pink/weiß/C).

**Status:** OFFEN. **Priorität: SOFORT.**

### P02 — Bildproduktion und Charakteridentität

**Ziel:** Reproduzierbare fotorealistische Bilder mit derselben virtuellen Figur.

**Arbeiten**
- `A01` Basisbild, `A02` SDXL-Character-LoRA, `A03` Img2Img, `A04` Inpainting strukturiert importieren.
- LUSTIFY und mindestens einen Vergleichscheckpoint getrennt testen; SDXL-Kompatibilität jedes LoRA nachweisen.
- Charakter-Referenzsatz versionieren (ohne ungeklärte fremde Bildrechte); eigene LoRA trainieren, falls qualitativ notwendig.
- Lokale Sampler-/Seed-/Modell-Registry; API-fähige Produktionsvorlagen und drei Varianten je Auftrag.
- Detailer und Tiled-Upscale als **separate optionale Stufen**; Ergebnisse gegen Ausgangsbilder vergleichen.
- Modelldateien und deren Lizenzen dokumentieren; fehlende oder inkompatible Nodes melden.

**Abnahme**
- Gleiche Prompt-/Seed-/Versionskombination ist reproduzierbar.
- Mindestens drei Varianten pro Auftrag werden gespeichert.
- Vergleich von Identität, Haut, Händen, Anatomie, Schatten und Auflösung dokumentiert.
- Keine zwingende Cloud-Inferenz.
- Nicht funktionierende oder nicht lizenzierte Modelle bleiben deaktiviert.

**Status:** OFFEN.

### P03 — Videoproduktion und zeitliche Konsistenz

**Ziel:** Aus freigegebenen Bildern brauchbare lokale Kurzvideos erzeugen.

**Arbeiten**
- Wan 2.2 I2V mit zusammengehörigem High-/Low-Noise-Paar, passendem VAE und Encoder.
- FP8/MPS-Kompatibilität **real messen**; falls ungeeignet, dokumentiert auf kompatiblen Datentyp/Backend wechseln.
- LTX Desktop beziehungsweise LTX-Workflows als unabhängigen Video-Pfad integrieren.
- Bewegungsreferenzen, Kontextverlängerung, SVI-/Segmentbildung, temporale Qualitätsprüfung und optionales Upscaling.
- Keine LoRA zwischen Wan/LTX/SDXL austauschen; nur standardisierte Medien als Übergabe.

**Abnahme**
- Nachweislich gerenderter Kurzclip auf dem Mac.
- Frameanzahl, Auflösung, Laufzeit, Spitzen-Speicherverbrauch und Artefaktbewertung erfasst.
- Längere Clips werden segmentiert und auf Identitäts-/Bewegungssprünge geprüft.
- Kein pauschaler „Hollywood“-PASS ohne Sichttest.

**Status:** OFFEN / Apple-FP8-Kompatibilität ungeklärt.

### P04 — Lokales Sprachmodell und Auftragsinterpretation

**Ziel:** Kundenwünsche in prüfbare, deterministische Produktionsaufträge übersetzen.

**Arbeiten**
- Lokalen LLM-Backend-Adapter (z. B. MLX/llama.cpp/Ollama) als austauschbare Schnittstelle erstellen.
- Charakterprofil, Chatverlauf und Auftragsinformationen getrennt halten.
- Freitext in typisierte Auftragseigenschaften umwandeln: Motiv, Kameraperspektive, Outfit, Format, Modellprofil, Variantenanzahl, Referenzen.
- Prompt-Validierung, zulässige Workflow-Parameter und Versionsverwaltung implementieren.
- Das LLM darf **weder Systembefehle noch direkte Versandfreigaben** erteilen.

**Abnahme**
- Derselbe Eingabevertrag wird ohne Telegram über Tests ausgeführt.
- Ungültige/fehlende Parameter führen zu einem definierten Fehlerzustand.
- Ein Prompt erzeugt einen eindeutig identifizierbaren Job mit drei vorgesehenen Varianten.

**Status:** OFFEN.

### P05 — Telegram-Eingang und Kundendialog

**Ziel:** Private Kundenkommunikation und Auftragserfassung.

**Arbeiten**
- Telegram-Bot anbinden; private Betreiber- und Kunden-Chat-IDs strikt trennen.
- Webhook oder Long-Polling mit Authentizität/Rate Limits, eindeutiger Nachrichten-ID und Deduplizierung.
- Nachrichtenhistorie pro Kunde verwalten; Bildaufträge getrennt vom Dialog speichern.
- Eingangsbestätigung und Bearbeitungsstatus; keine automatische Medienauslieferung.
- Gegebenenfalls transparent machen, dass die Figur eine KI ist; Adult-Angebote erst nach Prüfung der einschlägigen Telegram-Regeln und Altersanforderungen einschalten.

**Abnahme**
- Testnachricht erzeugt einen Job beim korrekten Kunden.
- Dubletten erzeugen keine doppelten Aufträge.
- Betreiber erhält keine Kundennachricht als versehentliche Kundenausgabe und umgekehrt.

**Status:** OFFEN.

### P06 — Betreiberfreigabe, Versionierung und kontrollierter Versand

**Ziel:** Betreiber entscheidet über jedes einzelne Kundenmedium.

**Arbeiten**
- Betreiber bekommt drei Vorschauen mit Auftrag, Seed, Modell, Zeitpunkt, Qualitätsstatus und Buttons **Freigeben**, **Ablehnen**, **Neu erstellen**.
- Freigaben sind authentifiziert, einem konkreten Medienhash und Auftrag zugeordnet, protokolliert und nicht wiederverwendbar.
- Medien nach Freigabe nicht mehr austauschbar; Zustellung nur des genehmigten Hashs.
- Ablauf-/Storno-Logik, Zeitüberschreitungen und Fehlerpfade einrichten.
- Versanddienst hat keine freie Generierungs- oder LLM-Berechtigung.

**Abnahme**
- Ohne Betreiberfreigabe: **0** Kundenlieferungen.
- Ablehnung: **0** Kundenlieferungen.
- Geänderte Bilddatei nach Freigabe wird nicht versendet.
- Freigabe von Kunde A kann nicht Kunde B beliefern.
- Erfolgreiche und fehlgeschlagene Zustellungen sind nachvollziehbar.

**Status:** OFFEN. **Produktiv-Gate zwingend.**

### P07 — Stabilität, Datenschutz, Sicherheit und Betrieb

**Ziel:** Dauerhaft nachvollziehbarer lokaler Betrieb.

**Arbeiten**
- Prozessüberwachung, Auto-Restart mit begrenztem Budget, Backpressure und Warteschlange.
- Sensible Tokens schützen, Logs bereinigen, Kundendaten begrenzt speichern und Löschprozesse definieren.
- Reproduzierbare Migration, Backup/Restore, Ressourcenlimits und Speicherüberwachung.
- Watchdogs für hängende ComfyUI-Jobs und abgesicherte Wiederaufnahme nach Neustart.
- Lizenz- und Inhaltsregeln einschließlich kommerzieller Nutzung dokumentieren.

**Abnahme**
- Absturz-, Neustart-, Netzwerkfehler- und Mehrfachanfragen-Test bestehen.
- Kein Token oder Kundenmedium in Git.
- Keine Auslieferung ohne Freigabe auch bei Restart/Race Conditions.
- Recovery eines unterbrochenen Auftrags ohne unkontrollierte Doppelzustellung.

**Status:** OFFEN.

### P08 — Kontrollierter Produktivstart und Qualitätssicherung

**Ziel:** Nachweisbare Ende-zu-Ende-Funktion im Betreiberbetrieb.

**Arbeiten**
- Begrenzter Testbetrieb mit synthetischen Testkunden.
- Qualitätsbenchmark-Satz für Identität, Anatomie, Beleuchtung, Hände, Gesichter, Bewegung, Zeitstabilität.
- A/B-Vergleich der Bild- und Videostacks; Gewinner nur nach dokumentierter Sichtprüfung/Prüfkriterien übernehmen.
- Betriebshandbuch, Statusübersicht, Recovery-Anleitung und reproduzierbare Release-Artefakte.

**Abnahme**
- Eingang → LLM → drei Medien → Betreiberfreigabe → korrekte Zustellung nachweislich PASS.
- Sämtliche Fehlerpfade getestet und mit Status versehen.
- Lizenz-/Plattform-Freigabe für den geplanten kommerziellen Betrieb dokumentiert.
- Versionsmarkierung `v1.0` erst nach vollständiger E2E-Abnahme.

**Status:** OFFEN.

---

## 5. Technische Verträge zwischen Modulen

### 5.1 Jobzustände (verbindlich)

```text
RECEIVED
  -> VALIDATED
  -> PROMPT_READY
  -> QUEUED
  -> GENERATING
  -> REVIEW_PENDING
  -> APPROVED | REJECTED | REVISION_REQUESTED
APPROVED -> DELIVERY_QUEUED -> DELIVERED
Alle aktiven Zustände -> FAILED oder CANCELLED (kontrolliert)
```

**Invariant A:** Nur `APPROVED` darf `DELIVERY_QUEUED` auslösen.  
**Invariant B:** Die Freigabe referenziert `job_id`, `artifact_id`, `content_hash`, `operator_id`, `approved_at`.  
**Invariant C:** Ein Medienartefakt ist nach der Freigabe unveränderlich.  
**Invariant D:** Pro eindeutiger Versandfreigabe höchstens eine tatsächliche Zustellung; Wiederholungsversuche sind idempotent.  
**Invariant E:** Keine Telegram-Antwort aus einem unvalidierten LLM-Toolaufruf oder Medienpfad.

### 5.2 Prozess- und Netzgrenzen

- ComfyUI zunächst nur auf `127.0.0.1:8188`; kein öffentlich erreichbarer Port.
- Launcher steuert ausschließlich einen eigenen Prozess samt PID-/Lock-Nachweis.
- Der Orchestrator nutzt die dokumentierte ComfyUI-HTTP-/WebSocket-API; keine Klick-Automation als Produktionsschnittstelle.
- Kundeneingaben können keine Dateipfade, Shell-Kommandos oder beliebige ComfyUI-Nodes vorgeben.
- Medienablage verwendet generierte interne IDs; kein direkter Zugriff aus Telegram auf das Dateisystem.
- Telegram-Tokens und Betreiber-ID werden nicht in Git eingecheckt.

### 5.3 Modell-/Workflow-Registry

Für jeden Eintrag sind vorzuhalten: eindeutiger Name, Architektur (SDXL/Wan/LTX), Basismodell, Dateipfad, Hash, VAE/Encoder, erforderliche Nodes, unterstützter Inferenzbackend, Lizenzstatus, erlaubte Eingaben/Ausgaben und letzter Mac-Abnahmestatus. **Nicht geprüfte Kombinationen dürfen nicht als „betriebsbereit“ markiert werden.**

---

## 6. Qualitätssicherung und Messwerte

### Bilder
- Reproduzierbare Seeds, Modell-/LoRA-Versionen, Workflow-Revisionen.
- Drei Kandidaten; getrennte Bewertung von Identität, Anatomie, Licht, Geometrie, Textur, Hintergrund und Artefakten.
- Vorher/Nachher-Vergleich für Inpainting, Tiled Refinement und Upscale; keine bloße Messung der Pixelzahl.

### Videos
- Auflösung, FPS, Dauer, Renderzeit, Peak-Unified-Memory, Fehlerrate.
- Identitätskonsistenz über Stichprobenframes; sichtbare Sprünge, Hand-/Körper-Drift, Szenen- und Kontaktfehler.
- Keine unabhängige Einzel-Frame-Nachschärfung ohne Flicker-Vergleich.

### Plattform
- Launcher: Zeit bis Health-Ready, Doppelklick-Idempotenz, Stop-/Restart-Korrektheit.
- Bot: Inbox-Deduplizierung, wartende Jobs, Abbruchquote, Fehlzustellungen.
- Freigabe: **0** unautorisierte Lieferungen in sämtlichen automatisierten Tests.

---

## 7. Explizit nicht Teil von P01

- Telegram-Kundendialog, LLM, Zahlungsabwicklung, Altersprüfungssystem, Kundenkonto und Versand.
- Training oder Download großer Bild-/Video-Modelle.
- Öffnen von ComfyUI-Ports ins Internet.
- Vollständige Bild-/Videoqualität für Werbe- oder Erwachsenencontent garantieren.
- Änderungen am bestehenden DarkBot-Projekt.

P01 wird **erst** als abgeschlossen markiert, wenn die `.app` auf dem realen Mac doppelklickbar startet und ComfyUI stabil erreichbar ist.

---

## 8. Fortschritts- und Änderungsregeln

`docs/STATUS.md` enthält pro Phase: `OFFEN / IN_ARBEIT / BLOCKIERT / PASS`, Git-Commit, getestete Version, Testdatum, reproduzierbaren Nachweis und offene Befunde. Kein PASS auf Grundlage bloßer Datei-Existenz oder syntaktisch gültiger Workflows.

Änderungen an der Architektur oder Qualitätspipeline erfolgen über einen dokumentierten Änderungsabschnitt im Plan und werden mit demselben Commit wie die Änderung umgesetzt.

**Nächste verbindliche Umsetzung:** P00 Bestand feststellen, unmittelbar darauf P01 macOS-Launcher bauen und auf dem tatsächlichen Mac testen.
