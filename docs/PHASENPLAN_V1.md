# DARKFLUENZER — PHASENPLAN V1

**Dokument:** `docs/PHASENPLAN_V1.md`  
**Version:** 1.3  
**Stand:** 14.11.2026  
**Status:** Verbindlicher Architektur- und Umsetzungsplan; Implementierung und lokale Abnahme noch ausstehend  
**Repository:** [sawyerma/Darkfluenzer](https://github.com/sawyerma/Darkfluenzer)  
**Verbindliche Unterdokumente:** [ENGINES_WORKFLOWS_V1.md](ENGINES_WORKFLOWS_V1.md) · [KUNDEN_DATENMODELL_V1.md](KUNDEN_DATENMODELL_V1.md)  
**Zielsystem:** Apple-Silicon-Mac M4, 128 GB Unified Memory, macOS  
**Projektverzeichnis:** `/Users/sawyer_ma/Desktop/Firma/2_DarkMa/8_Darkfluenzer`

---

## 1. Produktziel und verbindlicher Endzustand

Darkfluenzer wird als **lokal betriebenes, modular aufgebautes KI-Medienproduktionssystem** entwickelt. Zunächst startet ein macOS-App-Icon ComfyUI zuverlässig mit einem Doppelklick. Darauf aufbauend kann ein autonomer Agent Kundenanfragen über einen privaten Telegram-Kanal bzw. Telegram-Bot entgegennehmen, im Charakter einer eindeutig virtuellen erwachsenen Influencerin antworten, durch ein lokales Sprachmodell Produktionsaufträge formulieren, lokale Bild-/Video-Workflows über die ComfyUI-API ausführen, je Auftrag **drei Vorschläge** erzeugen und sie dem Betreiber zur Prüfung vorlegen.

**Ohne bestätigte Zahlung UND ausdrückliche Betreiberfreigabe erfolgt keine Auslieferung an den Kunden.** Der Betreiber genehmigt ein konkretes, unveränderliches Artefakt. Das Zahlungssystem und der Freigabedienst sind voneinander unabhängige Autoritäten; das LLM darf keines der beiden Gates übersteuern.

### 1.1 Zielablauf

1. Ein Kunde führt im privaten Telegram-Bot einen fortlaufenden Dialog mit der **als virtuell gekennzeichneten** Influencerin.
2. Die lokale LLM-Schicht extrahiert aus dem Chat nur die zur Leistungserbringung nötigen Informationen: Bild/Video, Motiv, Pose, Gesichtsausschnitt, Kleidung, Perspektive, Stil, Format, bereits genannte Änderungswünsche.
3. Ein deterministischer **Sales-Trigger** zählt je Kundenkonversation eindeutig zuordenbare, wiederholte Medienanfragen. **Konfigurierbare Vorgabe: nach der dritten qualifizierten Anfrage** unterbreitet der Bot ein klares kostenpflichtiges Angebot mit Leistung, Preis und Lieferbedingung. Eine explizite Kaufabsicht kann das Angebot früher auslösen; bloßes Smalltalk-Zählen ist unzulässig. Keine künstliche Dringlichkeit oder Täuschung über reale Identität.
4. Kunde nimmt das Angebot an und erhält eine dem Auftrag eindeutig zugeordnete Zahlungsanforderung. **Kein Produktionsauftrag ohne bestätigten Zahlungseingang**, soweit keine ausdrücklich konfigurierte Test-/Gratisregel greift.
5. Der Payment-Adapter validiert die finale Zahlung serverseitig und ordnet die Transaktions-ID genau einem Auftrag zu; eine Nachricht oder ein Screenshot des Kunden ist niemals ein Zahlungsnachweis.
6. Das LLM erstellt aus dem gespeicherten Gespräch einen **strukturierten Medienauftrag und konkreten Bild- bzw. Videoprompt**. Der Orchestrator wählt **zwei strikt getrennte Produktionswege**: `image` → SDXL/LoRA/Inpainting/Refinement; `video` → Wan/LTX/Video-Refinement.
7. ComfyUI wird bei Bedarf automatisch gestartet und erzeugt standardmäßig **drei Kandidaten** des bestellten Medientyps, mit nachvollziehbaren Modellversionen, Seeds und Parametern.
8. Vorschauen und Auftragsbeschreibung werden ausschließlich dem Betreiber auf dem Handy (privater Betreiber-Chat) und optional am lokalen Operator-Dashboard angezeigt. Auswahl: **Freigeben / Ablehnen / Neu erstellen**.
9. **Nur wenn `payment_confirmed = true` UND `operator_approved = true`** ist, darf der Delivery-Service ausschließlich das konkret genehmigte Bild oder Video an den zugehörigen Kunden versenden.
10. Chat, Angebot, Auftrag, Zahlung, Generierung, Freigabe und Versand werden konsistent protokolliert; Ausfall-/Storno-/Erstattungsfälle haben definierte Zustände.

### 1.2 Qualitätsziel

- Eine über Bilder und Videos wiedererkennbare **vollständig synthetische, eindeutig erwachsene** Figur.
- Fotorealistische Haut, Haare, Proportionen, Perspektive, Lichtsetzung und konsistente Identität.
- **Ein gemeinsames fotografisches Masterbild** pro Szene als kanonische, unveränderliche Ausgangsbasis; sowohl reguläre als auch NSFW-Bearbeitungen werden davon abgeleitet.
- Bildvarianten, **maskiertes Inpainting mit separat ladbaren spezialisierten SDXL-Checkpoints**, Detailer, Tiled Refinement und geeignetes Upscaling.
- Video: nachvollziehbare Referenzbilder, Pose-/Bewegungssteuerung, zeitliche Konsistenz, segmentierte Clips und Nachbearbeitung.
- Das Ziel „Hollywood-/Realfilm-Niveau“ ist eine **Qualitätsanforderung**, keine garantierte oder bereits nachgewiesene Modelleigenschaft. Abnahme erfolgt anhand festgelegter Testmotive und Sichtung der Ergebnisse.

### 1.3 Harte Grenzen

- Vollständige lokale Bild-/Videogenerierung; keine verpflichtende fremde Inferenz-API.
- Modulare Architektur: Telegram, LLM, Orchestrator, ComfyUI, Freigabe und Versand unabhängig austauschbar.
- Kein Versand an Kunden ohne **beides**: bestätigte, auftragsgebundene Zahlung **und** nachweisbare, auftragsbezogene Betreiberfreigabe.
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
10. **Auslieferung als privilegierte Aktion:** Ausschließlich der Delivery-Service mit zwei unabhängigen, serverseitig geprüften Gates (Payment-Service + Approval-Service) darf liefern; die LLM-Ausgabe niemals direkt.
11. **Direkt auf `main`:** Solange nichts anderes beschlossen wird; pro abgeschlossenem Paket sauber committen und pushen.
12. **Minimaler Initialumfang:** Zuerst der funktionierende Launcher. Telegram, LLM, Zahlungsanbindung und Medienautomatisierung folgen erst in ihren vorgesehenen Phasen.
13. **Nachvollziehbarer Verkauf:** Die festgelegte Grenze von drei qualifizierten Medienanfragen wird unabhängig vom LLM über einen zustandsbehafteten Sales-Service gezählt; ein abgelehntes Angebot darf nicht durch wiederholte ungefragte Verkaufsaufforderungen umgangen werden.
14. **Zahlungsautorisierung:** Nur ein vom Zahlungsanbieter bestätigtes, idempotent verarbeitetes Ereignis darf den Auftrag als bezahlt markieren. Weder Nutzertext noch Modellantwort noch lokale UI dürfen dies simulieren.
15. **Getrennte Medienwege:** Bild- und Videoworkflows teilen nur kontrollierte Auftrags-/Dateischnittstellen, niemals inkompatible Modellgewichte/LoRAs.

---

## 3. Ziel-Verzeichnisstruktur

```text
8_Darkfluenzer/
├── README.md
├── docs/
│   ├── PHASENPLAN_V1.md             # Verbindlicher Masterplan
│   ├── ARCHITEKTUR.md               # Komponenten, APIs, Zustandsübergänge
│   ├── BETRIEB.md                   # Installieren, Starten, Stoppen, Fehlerdiagnose
│   ├── ENGINES_WORKFLOWS_V1.md      # Engines, Workspace-Versionen, Registry
│   ├── KUNDEN_DATENMODELL_V1.md     # Kunden-ID, SQLite, Aktenstruktur
│   ├── MODELLE_LIZENZEN.md          # Modellstand, Hash, Lizenz, Apple-Abnahme
│   ├── ZAHLUNG_UND_VERTRIEB.md      # Angebot, Zahlstatus, Erstattung, Plattformprüfung
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
│   ├── sales/                       # Qualifizierte Anfragen, Angebote, Preisliste
│   ├── payments/                    # Zahlungs-Adapter, Bestätigungen, Erstattungen
│   ├── review/                      # Freigabe, Reject, Revision
│   ├── telegram/                    # Kunden- und Betreiberkanal getrennt
│   ├── delivery/                    # Ausschließlich freigegebene Zustellung
│   ├── storage/                     # Metadaten und Artefaktverwaltung
│   └── observability/               # Logs, Metriken, Health
├── workflows/
│   ├── images/
│   │   ├── base/                    # Master-Fotogenerierung, Qualitätsbenchmark
│   │   ├── identity/                # Einheitliches Charakterprofil, passende LoRAs
│   │   ├── inpainting/              # SDXL/LUSTIFY: nur maskierte Bereiche
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
    ├── data/                        # Zentrale SQLite-Datenbank und Backups
    ├── customers/                   # DF-C-000001: Chat, Aufträge, Medien
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

**Ziel:** Reproduzierbare fotorealistische Bilder mit derselben virtuellen Figur und **einer einheitlichen Master-Ausgangsbasis** für reguläre und spezialisierte Bildbearbeitung.

**Arbeiten**
- `A01` Basisbild, `A02` SDXL-Character-LoRA, `A03` Img2Img, `A04` Inpainting strukturiert importieren. Die bestehenden Workflows bleiben als technische Module erhalten, ihre Produktionsrolle wird neu geordnet.
- **Master-Engine**: fotorealistische Szene mit dem qualitativ besten lokal geprüften, zulässigen Bildmodell erzeugen (FLUX/MiniMax/Qwen/vergleichbares Modell nur nach Mac-Test). Das Ergebnis wird als **unveränderliches Master-PNG** einschließlich Prompt, Seed, Modellhash, Charakterreferenz und Version gespeichert.
- **Zwei Ableitungen vom selben Master-PNG**: (A) normales Bild → normale Korrektur/Upscaling; (B) spezialisierte Erwachsenen-Bildbearbeitung → gezielte, **maskierte** regionale Bearbeitung z. B. mit LUSTIFY (SDXL) → Korrektur/Upscaling.
- **Der komplette Basis-Frame darf beim NSFW-Schritt nicht als neues Vollbild generiert werden.** Nur eine definierte Maske und eine begrenzte Übergangszone werden über Inpainting neu berechnet; außerhalb bleibt das Masterbild im finalen Composite pixelidentisch. Optional Cropping/Region Upscale mit Rückprojektion.
- Die von Kleidung verdeckten Regionen sind im Ausgangsbild nicht vorhanden; Inpainting erzeugt diese Details synthetisch. Keine Behauptung einer physikalisch oder anatomisch garantiert korrekten Rekonstruktion.
- Architekturwechsel erfolgen an **standardisierten PNG-/Masken-Dateien**; FLUX-/MiniMax-/Qwen-Latents sowie deren LoRAs **dürfen nicht direkt an SDXL/LUSTIFY angeschlossen werden**. Für SDXL-Identität separate kompatible LoRA oder passende Referenzkonditionierung vorsehen.
- LUSTIFY ist ein **gewöhnlicher SDXL-Checkpoint**, nicht automatisch ein speziell konditioniertes Inpainting-Modell. Unterstützten Maskenpfad mit `VAEEncode` + `SetLatentNoiseMask` testen; `VAEEncodeForInpaint` oder dedizierte Inpaint-Modelle als gesonderten Versuch führen, nicht ungeprüft vermischen.
- Charakter-Referenzsatz versionieren (ohne ungeklärte fremde Bildrechte); eigene Charakter-LoRA pro verwendeter Modellfamilie trainieren, soweit erforderlich.
- Lokale Sampler-/Seed-/Modell-Registry; API-fähige Produktionsvorlagen und drei Varianten je Auftrag.
- Detailer und Tiled-Upscale als **separate optionale Stufen**; Ergebnisse gegen das originale Masterbild vergleichen.
- Modelldateien und deren Lizenzen dokumentieren; fehlende oder inkompatible Nodes melden.

**Abnahme**
- Gleiche Prompt-/Seed-/Versionskombination ist reproduzierbar.
- Mindestens drei Varianten pro Auftrag werden gespeichert.
- Vergleich von Identität, Haut, Händen, Anatomie, Schatten und Auflösung dokumentiert.
- Master-PNG bleibt unverändert; bei maskierten Ableitungen bleiben alle Pixel außerhalb der Maske und ihres definierten Rands identisch.
- Beide Bearbeitungsarten liefern kontrolliert aus derselben Master-Datei; unverwechselbare Zuordnung über `master_artifact_id`.
- Cross-Architecture-Übergänge erfolgen ausschließlich über Bilddateien/Masken, nicht Modell-Latents.
- Kein unbewiesener Qualitätsvorteil von LUSTIFY-Inpainting: Vergleich mit anderen Inpaint-/Edit-Modellen am identischen Bild und identischer Maske dokumentiert.
- Keine zwingende Cloud-Inferenz.
- Nicht funktionierende oder nicht lizenzierte Modelle bleiben deaktiviert.

**Status:** OFFEN.

### P03 — Videoproduktion und zeitliche Konsistenz

**Ziel:** Aus freigegebenen Bildern brauchbare lokale Kurzvideos erzeugen.

**Arbeiten**
- Wan 2.2 I2V mit zusammengehörigem High-/Low-Noise-Paar, passendem VAE und Encoder.
- FP8/MPS-Kompatibilität **real messen**; falls ungeeignet, dokumentiert auf kompatiblen Datentyp/Backend wechseln.
- LTX Desktop beziehungsweise LTX-Workflows als unabhängigen Video-Pfad integrieren.
- Bild-zu-Video übernimmt ausschließlich ein versioniertes, geeignetes fertiges Master- oder bearbeitetes PNG; beide Varianten behalten ihre gemeinsame Herkunft (`master_artifact_id`) und ihre eigene, unveränderliche `artifact_id`.
- Bewegungsreferenzen, Kontextverlängerung, SVI-/Segmentbildung, temporale Qualitätsprüfung und optionales Upscaling.
- Keine LoRA zwischen Wan/LTX/SDXL austauschen; nur standardisierte Medien als Übergabe.

**Abnahme**
- Nachweislich gerenderter Kurzclip auf dem Mac.
- Frameanzahl, Auflösung, Laufzeit, Spitzen-Speicherverbrauch und Artefaktbewertung erfasst.
- Längere Clips werden segmentiert und auf Identitäts-/Bewegungssprünge geprüft.
- Kein pauschaler „Hollywood“-PASS ohne Sichttest.

**Status:** OFFEN / Apple-FP8-Kompatibilität ungeklärt.

### P04 — Lokales Sprachmodell und Auftragsinterpretation

**Ziel:** Kundenwünsche aus dem Gespräch extrahieren und nach bestätigter Zahlung in prüfbare, deterministische Medienaufträge übersetzen.

**Arbeiten**
- Lokalen LLM-Backend-Adapter (z. B. MLX/llama.cpp/Ollama) als austauschbare Schnittstelle erstellen.
- Charakterprofil, Chatverlauf und Auftragsinformationen getrennt halten.
- Freitext über mehrere Dialognachrichten hinweg in typisierte Auftragseigenschaften umwandeln: Medienart (`image`/`video`), Motiv, Pose, Kameraperspektive, Outfit, Format, Modellprofil, Variantenanzahl, Referenzen und Änderungswünsche.
- Prompt-Validierung, zulässige Workflow-Parameter und Versionsverwaltung implementieren.
- Das LLM darf **weder Systembefehle noch Zahlungserfolg noch direkte Versandfreigaben** erteilen.
- Für `image` ausschließlich passende SDXL-/LoRA-/Inpainting-Workflows; für `video` ausschließlich passende Wan-/LTX-/Temporal-Workflows zuordnen.

**Abnahme**
- Derselbe Eingabevertrag wird ohne Telegram über Tests ausgeführt.
- Ungültige/fehlende Parameter führen zu einem definierten Fehlerzustand.
- Ein Prompt erzeugt einen eindeutig identifizierbaren Job mit drei vorgesehenen Varianten.

**Status:** OFFEN.

### P05 — Telegram-Eingang, Kundendialog und Angebotslogik

**Ziel:** Ein fortlaufender Kundendialog extrahiert Informationen, erkennt die wiederholte Kaufabsicht und bietet das konkret angefragte Medium kostenpflichtig an.

**Arbeiten**
- Telegram-Bot anbinden; private Betreiber- und Kunden-Chat-IDs strikt trennen.
- Webhook oder Long-Polling mit Authentizität/Rate Limits, eindeutiger Nachrichten-ID und Deduplizierung.
- Nachrichtenhistorie pro Kunde verwalten; Bild- und Videoaufträge getrennt vom Dialog speichern.
- **Sales-Service:** qualifizierte, eindeutig abgegrenzte Medienanfragen zählen; Standard-Trigger beim **dritten** relevanten Wunsch; ausdrückliche Kaufbitte kann frühere Angebotslegung auslösen.
- Angebot und Preis pro Bild/Video als versionierte Produktkonfiguration bereitstellen; Leistung und Kosten vor Annahme eindeutig benennen.
- Ablehnungen und bereits beantwortete Angebote erkennen; keine aufdringlichen Wiederholungen; Bot ist als KI-Charakter erkennbar.
- Eingangsbestätigung und Bearbeitungsstatus; keine automatische Medienauslieferung.
- Gegebenenfalls transparent machen, dass die Figur eine KI ist; Adult-Angebote erst nach Prüfung der einschlägigen Telegram-Regeln und Altersanforderungen einschalten.

**Abnahme**
- Testnachricht erzeugt eine kundenspezifische Dialog-/Intent-Erfassung; ein kostenpflichtiger Produktionsjob wird erst nach bestätigter Zahlung freigegeben.
- Drei unterschiedliche qualifizierte Medienanfragen führen zu genau einem Angebot; Smalltalk, Dubletten und wiederholte Updates lösen keine zusätzlichen Angebote aus.
- Dubletten erzeugen keine doppelten Aufträge.
- Betreiber erhält keine Kundennachricht als versehentliche Kundenausgabe und umgekehrt.

**Status:** OFFEN.

### P06 — Zahlungsabgleich, Betreiberfreigabe und kontrollierter Versand

**Ziel:** Kundenauslieferung ausschließlich nach erfolgreich verifizierter Zahlung und persönlicher Betreiberfreigabe.

**Arbeiten**
- Payment-Service als eigenständigen, austauschbaren Adapter integrieren: Angebot, Rechnung, `payment_pending`, signierte/verifizierte Zahlungsbestätigung, Refund, Storno, Timeout.
- Telegram-Digitalverkäufe gemäß Telegram-Zahlungsdokumentation über Stars (`XTR`) prüfen; **PayPal ist für sexuell orientierte digitale Inhalte nach den PayPal-Regeln nicht zugelassen.** Anbieter/Verkauf dürfen erst nach inhaltlicher und kommerzieller Freigabe produktiv sein.
- Zahlungs-ID mit `customer_id`, `order_id`, Betrag, Währung und eindeutigem Zahlungsstatus verknüpfen; Zahlungsereignisse idempotent verarbeiten.
- Betreiber bekommt drei Vorschauen mit Auftrag, Seed, Modell, Zeitpunkt, Qualitätsstatus und Buttons **Freigeben**, **Ablehnen**, **Neu erstellen**.
- Freigaben sind authentifiziert, einem konkreten Medienhash und Auftrag zugeordnet, protokolliert und nicht wiederverwendbar.
- Medien nach Freigabe nicht mehr austauschbar; Zustellung nur des genehmigten Hashs.
- Ablauf-/Storno-Logik, Zeitüberschreitungen und Fehlerpfade einrichten.
- Versanddienst hat keine freie Generierungs- oder LLM-Berechtigung.
- **Doppelte Lieferbedingung:** serverseitig bestätigte Zahlung plus gültige Betreiberfreigabe für exakt den unveränderlichen Medienhash.
- Bereits bezahlte, aber abgelehnte oder nicht erfüllbare Bestellungen gehen in einen ausdrücklich geregelten Revision-/Refund-Prozess.

**Abnahme**
- Ohne Betreiberfreigabe: **0** Kundenlieferungen.
- Ohne erfolgreich bestätigte Zahlung: **0** Kundenlieferungen.
- Falsche, ausstehende, widerrufene, mehrfach gemeldete oder zu einem anderen Auftrag gehörende Zahlungen: **0** Freigaben zum Versand.
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
- Keine Auslieferung ohne **Zahlung und Freigabe** auch bei Restart/Race Conditions.
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
- Telegram-Dialog → dritter qualifizierter Medienwunsch → Angebot → bestätigte Zahlung → LLM-Prompt → passende Bild-/Videopipeline → drei Medien → Betreiberfreigabe → korrekte Zustellung nachweislich PASS.
- Sämtliche Fehlerpfade getestet und mit Status versehen.
- Lizenz-/Plattform-Freigabe für den geplanten kommerziellen Betrieb dokumentiert.
- Versionsmarkierung `v1.0` erst nach vollständiger E2E-Abnahme.

**Status:** OFFEN.

---

## 5. Technische Verträge zwischen Modulen

### 5.1 Jobzustände (verbindlich)

```text
DIALOG_ACTIVE
  -> INTENT_QUALIFIED
  -> OFFERED
  -> PAYMENT_PENDING
  -> PAYMENT_CONFIRMED
  -> PROMPT_READY
  -> QUEUED
  -> GENERATING
  -> REVIEW_PENDING
  -> APPROVED | REJECTED | REVISION_REQUESTED
APPROVED + PAYMENT_CONFIRMED -> DELIVERY_QUEUED -> DELIVERED
REJECTED/FAILED nach Zahlung -> REVISION_PENDING oder REFUND_PENDING
Alle zulässigen aktiven Zustände -> FAILED oder CANCELLED (kontrolliert)
```

**Invariant A:** Nur **`APPROVED` UND `PAYMENT_CONFIRMED`** dürfen gemeinsam `DELIVERY_QUEUED` auslösen.  
**Invariant B:** Die Freigabe referenziert `job_id`, `artifact_id`, `content_hash`, `operator_id`, `approved_at`.  
**Invariant C:** Ein Medienartefakt ist nach der Freigabe unveränderlich.  
**Invariant D:** Pro eindeutiger Versandfreigabe höchstens eine tatsächliche Zustellung; Wiederholungsversuche sind idempotent.  
**Invariant E:** Keine Telegram-Antwort aus einem unvalidierten LLM-Toolaufruf oder Medienpfad.  
**Invariant F:** `payment_confirmed` kann nur durch den Payment-Service mit verifiziertem Anbieterereignis gesetzt werden.  
**Invariant G:** Eine bestätigte Zahlung gilt nur für den eindeutig zugeordneten Auftrag und vereinbarten Inhalt/Preis.  
**Invariant H:** Bei unbekanntem Zahlungsstatus oder fehlender Betreiberfreigabe bleibt die Auslieferung gesperrt.  
**Invariant I:** `image` und `video` wählen getrennte, versionierte, kompatible Workflows; Bilddateien dürfen als kontrollierte Übergabe an I2V dienen.

### 5.2 Prozess- und Netzgrenzen

- ComfyUI zunächst nur auf `127.0.0.1:8188`; kein öffentlich erreichbarer Port.
- Launcher steuert ausschließlich einen eigenen Prozess samt PID-/Lock-Nachweis.
- Der Orchestrator nutzt die dokumentierte ComfyUI-HTTP-/WebSocket-API; keine Klick-Automation als Produktionsschnittstelle.
- Kundeneingaben können keine Dateipfade, Shell-Kommandos oder beliebige ComfyUI-Nodes vorgeben.
- Medienablage verwendet generierte interne IDs; kein direkter Zugriff aus Telegram auf das Dateisystem.
- Telegram-Tokens, Zahlungs-Provider-Secrets und Betreiber-ID werden nicht in Git eingecheckt.
- Der Sales-Service nimmt nur validierte Dialog-Intents entgegen; er führt keine Zahlungen aus.
- Der Payment-Service akzeptiert ausschließlich authentifizierte Zahlungs-Provider-Ereignisse; keine manuell eingegebene `PAID`-Markierung im Kundenchat.
- Der Delivery-Service holt Zahlung und Freigabe unabhängig aus ihren jeweiligen Autoritätsquellen.

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
- Zahlung: **0** Lieferungen bei `PENDING`, `FAILED`, `CANCELLED`, falscher `order_id` oder unvalidiertem Zahlungsereignis.
- Sales: Triggerschwelle von drei qualifizierten Anfragen sowie Dubletten-/Rücksetzregeln mit Tests abgedeckt.

---

## 7. Explizit nicht Teil von P01

- Telegram-Kundendialog, LLM, Sales-Trigger, Zahlungsabwicklung, Altersprüfungssystem, Kundenkonto und Versand.
- Training oder Download großer Bild-/Video-Modelle.
- Öffnen von ComfyUI-Ports ins Internet.
- Vollständige Bild-/Videoqualität für Werbe- oder Erwachsenencontent garantieren.
- Änderungen am bestehenden DarkBot-Projekt.

P01 wird **erst** als abgeschlossen markiert, wenn die `.app` auf dem realen Mac doppelklickbar startet und ComfyUI stabil erreichbar ist.

---

## 8. Fortschritts- und Änderungsregeln

`docs/STATUS.md` enthält pro Phase: `OFFEN / IN_ARBEIT / BLOCKIERT / PASS`, Git-Commit, getestete Version, Testdatum, reproduzierbaren Nachweis und offene Befunde. Kein PASS auf Grundlage bloßer Datei-Existenz oder syntaktisch gültiger Workflows.

Änderungen an der Architektur oder Qualitätspipeline erfolgen über einen dokumentierten Änderungsabschnitt im Plan und werden mit demselben Commit wie die Änderung umgesetzt.

### Änderung V1.3 — Engines, Workspaces und Kundenakte (14.11.2026)

- [ENGINES_WORKFLOWS_V1.md](ENGINES_WORKFLOWS_V1.md) ist der verbindliche Engine-/ComfyUI-Workspace-Vertrag. Engine-Rollen sind fixiert, konkrete Checkpoints bleiben bis zur Mac-, Lizenz- und Qualitätsabnahme Kandidaten.
- [KUNDEN_DATENMODELL_V1.md](KUNDEN_DATENMODELL_V1.md) ist der verbindliche Kunden-/Auftrags-/Zahlungs-Datenvertrag. **SQLite** ist die alleinige Statusautorität; Medien und Exporte liegen in getrennten lokalen Kundenordnern.
- Jeder Telegram-Kontakt erhält eine eindeutige Kundennummer im Format `DF-C-000001`. Technische Zuordnung über Telegram-User-ID und Bot-Konto, niemals ausschließlich Username.
- Je Kunde: Chats, Angebote, Aufträge, Zahlungsereignisse, Masterbilder, Masken, drei Kandidaten, Freigaben, ausgelieferte Artefakte.
- Jeder kostenpflichtige Auftrag: zugehörige verifizierte Zahlung + drei Kandidaten + Betreiberfreigabe + konkret autorisierte Lieferung. Bild und Video haben getrennte Workflows.
- Workflows: versionierte UI-/API-Exporte, Manifest, Testnachweis und Modelldatei-/Node-Versionen.
- Diese Kurzstruktur wird durch die beiden Fachkonzepte normativ präzisiert.

### Änderung V1.2 — Einheitliche Master-Bildpipeline (14.11.2026)

- **Master-First** ist verbindlich: Erst das bestgeeignete lokale Bildmodell für die gesamte Fotografie, danach normale oder spezialisierte regionale Bearbeitung.
- LUSTIFY ist ein **optionaler SDXL-Region-Editor**, nicht die erzwungene Master-Engine und nicht automatisch das beste Inpainting-Modell.
- **Ein Master-PNG** mit identischem Gesicht, Szene und Kameraperspektive; die Normal-/NSFW-Versionen sind getrennte, reproduzierbare Derivate.
- Bei maskierter Bearbeitung bleiben unmaskierte Pixel im Endbild exakt erhalten. Anatomie und Übergänge sind zusätzlich visuell abzunehmen.
- Modellfamilien werden ausschließlich über Bild-/Maskenartefakte kombiniert; keine cross-family LoRA- oder Latent-Kompatibilität behaupten.
- Echte Qualitätskontrolle durch A/B-Tests am identischen Originalmotiv.
- Technische Grundlagen: https://github.com/Comfy-Org/ComfyUI/blob/master/nodes.py und https://huggingface.co/docs/diffusers/using-diffusers/inpaint

### Änderung V1.1 — Verkaufs- und Zahlungsgates (14.11.2026)

- Wiederholte Medienanfragen (`3` qualifizierte Wünsche als konfigurierbare Standardschwelle), explizite Angebote und Auftragserstellung wurden verbindlich definiert.
- **Zahlung vor automatischer Generierung** ist Standard; Lieferung ist ausnahmslos zusätzlich von der Betreiberfreigabe abhängig.
- Medienart `image` oder `video` verzweigt in **getrennte** ComfyUI-Workflows mit eigenen Abnahmekriterien.
- Zahlungsanbieter ist kein fest codierter Dienst. Für digitale Güter innerhalb von Telegram schreibt Telegram Stars vor: https://core.telegram.org/bots/payments-stars ; die Nutzung für konkret geplante Adult-Inhalte ist getrennt zu prüfen.
- PayPal ist **nicht** als Standard für digitale XXX-Bilder/-Videos vorgesehen: https://www.paypal.com/de/legalhub/paypal/acceptableuse-full?locale.x=en_US und https://www.paypal.com/us/cshelp/article/what-is-paypal%E2%80%99s-policy-on-transactions-that-involve-sexually-oriented-goods-and-services-help384
- Die Darstellung der virtuellen Figur darf den Käufer nicht über eine angeblich reale menschliche Identität täuschen; Angebot, Preis und Lieferbedingungen müssen klar sein.

**Nächste verbindliche Umsetzung:** P00 Bestand feststellen, unmittelbar darauf P01 macOS-Launcher bauen und auf dem tatsächlichen Mac testen.
