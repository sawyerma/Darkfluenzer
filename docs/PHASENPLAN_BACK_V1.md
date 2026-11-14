# DARKFLUENZER — PHASENPLAN BACK V1

**Version:** 1.9 — BACKEND + PROTOBUF + zwei ComfyUI-Instanzen + verbindlicher nativer M4-Max-/Chatwoot-Betrieb (Host-Abnahme OFFEN)
**Stand:** 15.11.2026  
**Status:** Zielarchitektur verabschiedet; Medien-ComfyUI 1 vorhanden; KI-ComfyUI 2 verbindlich beschlossen, Implementierung und Mac-Abnahme OFFEN  
**Repository:** `sawyerma/Darkfluenzer`, Branch `main`  
**Lokal:** `/Users/sawyer_ma/Desktop/Firma/2_DarkMa/8_Darkfluenzer`  
**System:** MacBook Pro Mac16,6, Apple M4 Max (12 Performance- + 4 Efficiency-CPU-Kerne, 128 GiB Unified Memory); ausschließlich natives macOS/ARM64, ohne Docker/Container/Linux-VM

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
    ├── ComfyUI/             # Instanz 1: unveränderte Medienlaufzeit
    ├── comfyui_ai/          # Instanz 2: eigenes User-/Node-/Temp-/Output-Profil (geplante Laufzeitdaten)
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

**Quellstruktur und Laufzeit konsequent trennen:** Kein zweites Kunden-CRM, keine zweite SQLite-Datenbank, keine redundanten Modell-/Manifestdateien. **Migration durchgeführt (14.11.2026):** `pyproject.toml`, `uv.lock`, `src/` und `tests/` per `git mv` nach `backend/`; `project_root()`, `launcher/install.sh` (`--project backend`, `--inexact` erhält installierte Extras), Testaufrufe und README gemeinsam angepasst; `local/` unverändert. Nachweis im S1-Abschnitt.

**Praktische Regeln:** Zwei unabhängig start-/stoppbare ComfyUI-Prozesse werden betrieben: bestehende Medieninstanz unter `local/ComfyUI` und eine eigene KI-Dialoginstanz mit separatem Laufzeit-/User-/Custom-Node-/Output-Profil unter `local/` (ein zweiter Quellcode-Checkout ist nur nötig, falls Isolation/Versionierung es verlangt). Beide erhalten eigene konfigurierbare Loopback-Ports, Client-IDs und Ausführungsqueues; **8188/8189 sind nur Vorschlagsdefaults, keine hart codierten Konstanten**. Modellgewichte, Kundendaten und Secrets gehören ausschließlich nach `local/`, niemals in Git. Workflowversionen beider Instanzen stammen aus Git und **einer** `workflows/manifest.toml`; jeder registrierte Graph hat UI- und API-Variante. Kunden und Aufträge erhalten stabile IDs; Kundendatenstatus liegt nur in SQLite, während `input/`, `work/` und `sent/` die zugehörigen Dateien enthalten. Keine Überschreibung freigegebener Artefakte.

**Frontend-Vertrag:** [PHASENPLAN_FRONT_V1.md](PHASENPLAN_FRONT_V1.md) ist ausschließlich für sichtbare GUI, React-Code, Browserverhalten und UI-Protokollbindungsregeln maßgeblich. Dieses BACK-Dokument ist maßgeblich für Betrieb, ComfyUI, Modellinstallation, LoRA, Kundenstatus, Zahlungsprüfung, Persistenz, Plattform-Adapter und serverseitige Protobuf-Publikation.

## 4. Festgelegte Engines — so wenig wie möglich, so viel wie nötig

| Rolle | Auswahl | Verbindlicher Stand |
|---|---|---|
| Medienlaufzeit | **ComfyUI-Instanz 1**: bestehende v0.45.3, konfigurierbarer Loopback-Port, bisher `127.0.0.1:8188`; Fotos/Video/Inpainting | S1/F3a PASS, unverändert erhalten |
| Master-Fotografie | **FLUX 3 Image Klein Base** (BF16) | Primärer Kandidat; Repo gated, kein M4-/Qualitäts-/Lizenz-PASS |
| Master-Benchmarks | **FLUX.2 Dev 32B** (BF16), **Qwen-Image 20B** (BF16), **Qwen-Image 2.1** (BF16) | Nur A/B-Vergleich; kein paralleler Dauerbetrieb |
| Gezielte Spezialbearbeitung | **LUSTIFY! v2.0** (SDXL), maskiertes Inpainting; Vergleich **RealCore Illustrious** | Testkandidaten, nicht garantiert beste Editoren |
| Bild-Nachbearbeitung | Regionale Detailer, Tiled Refine/Upscale | Optional innerhalb eines Refinement-Workflows |
| Video Hauptpfad | **Wan 2.2 Remix NSFW I2V v3.0**, High-/Low-Noise-Paar (nur FP8 verfügbar) | Experimentell; FP8 auf MPS nicht nativ (geprüft) |
| Video Referenz | **Wan 2.2 I2V 14B offiziell** (FP16) | Vergleichsbasis für Remix |
| Video Ersatzpfad | **LTX 2.5 Fast** (22B distilliert, BF16) über ComfyUI | Repo gated; getrennte Abnahme |
| Text-/Sprach-KI | **ComfyUI-Instanz 2**: LLM, Dialog-, Prompt-, Prüf- und TTS-Workflows; Cydonia 24B v4.1 GGUF als erster Kandidat; llama.cpp/MLX ggf. als interne Modell-Laufzeit innerhalb von ComfyUI-Nodes, **kein konkurrierender eigenständiger Dialogpfad** | Verbindliche Architektur; Modell-/Node-/Apple-MPS-Test OFFEN |
| Kundendialog | Chatwoot Community v4.19.1 als Kanal-Dienst (Telegram, Instagram, WhatsApp) → Darkfluenzer-Python → KI-ComfyUI 2 | ZIP vorhanden, Integration noch nicht abgenommen |
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

## 4A. Verbindliche neue Architektur: zwei ComfyUI-Instanzen, alle KI-Abläufe grafisch (Beschluss 14.11.2026)

**Architekturentscheidung — kein optionaler Alternativvorschlag:** Statt eines separaten, für Chatantworten obligatorischen MLX-/llama.cpp-HTTP-Dienstes wird eine **zweite, eigenständige ComfyUI-Instanz als primäre KI-Dialog- und Workflow-Laufzeit** eingeführt. Die erste, bereits funktionierende Medieninstanz bleibt unverändert zuständig für Bild-/Video-Produktion. ComfyUI 2 steuert Text-LLM, mehrstufige Dialoganalyse, Prompt-Erzeugung, optionale Zweit-KI-Prüfung und Sprachnachrichten/TTS über **in ComfyUI bearbeitbare Nodes und registrierte Graphen**. Cydonia 24B v4.1 GGUF ist der erste zu qualifizierende Kandidat, **nicht** als bereits laufend zu behaupten. Ein llama.cpp-Backend darf technisch **innerhalb** passender ComfyUI-Nodes arbeiten; es ist keine zweite, konkurrierende Anwendungslogik oder dritte fachliche Dialog-Pipeline. Installierte Custom Nodes/Loops/Conditionals nur nach realer Kompatibilitätsprüfung auf Mac/ComfyUI-Version einsetzen; ComfyUI selbst garantiert nicht jedes Schleifen-/Agentenfeature ohne Erweiterung.

**Zwei getrennte Instanzen:**
- **ComfyUI 1 – Medien:** bestehender Prozess und bisheriger Port (konfigurierter Default `127.0.0.1:8188`), bestehende Foto-/Video-/Inpainting-/Refinement-Workflows, bestehende **eine globale persistente Medien-FIFO** für sämtliche Kunden- und Test-Renderaufträge, unveränderte Medienablage, Artefakt- und Lizenzgates.
- **ComfyUI 2 – KI:** zweiter Prozess auf anderem konfigurierbarem Port (Vorschlag `127.0.0.1:8189`), **eigene** Queue, WebSocket-/Client-ID, Nodes und nutzerbezogene Workflow-Graphen, unabhängig von Medien-FIFO. Dies umfasst Antwortgenerierung, Dialogklassifikation/Intent, strukturierte Wunschzusammenfassung, Kontextkompression, Promptbildung, konditionale Verzweigungen, ggf. begrenzte Feedbackschleifen/zweite LLM-Kontrolle, Vision-Bildprüfung und TTS, sofern die tatsächlich installierten Modelle/Nodes diese Funktionen unterstützen. Ein Medienjob **blockiert nicht die Warteschlange** von ComfyUI 2; GPU und Unified Memory bleiben physisch gemeinsam und müssen gleichzeitig belastungsgeprüft werden.
- Der bestehende **eine Python-Backendprozess** verwaltet beide ComfyUI-Prozesse über **zwei gezielte Clients**, getrennte Health-/Queue-/Job-IDs, klare Lifecycle-Zuständigkeiten und sichere Starts/Stops. Der bestehende Launcher startet/überwacht auf Wunsch beide unabhängig, ohne laufende Renderungen zu unterbrechen oder fremde Prozesse zu beenden. Kein `pkill`, kein globaler Queue-Reset, keine unbeabsichtigten Neustarts bei laufenden Aufträgen.
- Eine zentrale **SQLite** bleibt einzige Autorität für Kundenidentität, Influencerinnen, Nachrichten, Persona, gemeinsame plattformübergreifende Historie, Freigabemodus, Aufträge, Zahlungsbelege, Medienreferenzen und Zustellungen. ComfyUI 2 bekommt je Aufruf nur den **vom Python-Backend vorbereiteten, auf die gewählte Influencerin und den Kunden begrenzten Kontext** und liefert Ergebnisdaten zurück. **Keine direkte ComfyUI-Manipulation an SQLite, keine eigenständige CRM-/Payment-Autorität in Nodes.**
- Der Python-Koordinator serialisiert Aufträge **derselben kanonischen Kundenakte kanalübergreifend**; andere Kunden laufen parallel, soweit KI-Queue/Ressourcen dies erlauben. Eingänge werden vor der KI-Übergabe in SQLite gespeichert und dedupliziert. Ergebnisse sind an `customer_id`, `influencer_id`, `channel_identity_id`, `conversation_id`, `message_id`, `workflow_id`, `workflow_version` und `request_id` gebunden; nach Operator-Handoff/Revision dürfen veraltete KI-Antworten nicht verschickt werden.
- **ComfyUI 2 übergibt Vorschläge, keine Autorisierung:** Modell/Nodes können Textantwort, strukturierte Felder, Prompt, Qualitätsbewertung und TTS-Audio erzeugen. Ob eine Plattformnachricht gesendet wird, ob Zahlung bestätigt ist, welcher Auftrag versandt werden darf und ob Betreiber-/Zweit-KI-Freigabe gilt, entscheidet **ausschließlich der deterministische Python-/SQLite-Gatekeeper**. Keine LLM-generierten Shellbefehle, ungeprüften Zielkanalwechsel oder Zahlungs-/Freigabeänderungen.

**Workflow-Nutzung und Bearbeitung:** Graphen für KI-Funktionen werden in **derselben bestehenden Registry `workflows/manifest.toml`** erfasst, mit eindeutigem Instanzziel (`media`/`ai`), Typ (`text`/`intent`/`vision`/`tts`), Modell-/Node-Abhängigkeiten, Ein-/Ausgabe-Verträgen, aktiviert/bereit-Status und versionierten **UI-/API-Graphen**. So können mehrere Influencerinnen unterschiedliche Persona-/LLM-/Stimm-/Prüfworkflows auswählen, ohne eigene Backend-Programmierung je Nodekette. **Loops, Bedingungen und Wiederholungen dürfen grafisch konfiguriert werden, aber mit Endbedingungen/Maximaliterationen und Fehlerzuständen.** Änderungen werden erst nach Graph-/Input-/Output-Validierung wirksam; laufende Aufträge behalten ihre zugewiesene Workflowversion. Profile und Kundenzuordnung stammen aus SQLite, nicht aus hardcodierten Node-Konstanten.

**Wesentliche Laufzeit-/Abnahmekriterien (keine vorzeitigen PASS-Angaben):**
1. Zwei gleichzeitig laufende ComfyUI-Prozesse auf dem Mac; separater Port, Client-ID, User-/Custom-Node- und Temp-Bereich sowie Queue; Medien-Health/Start/Stop/FIFO aus F3a weiterhin vollständig funktionsfähig.
2. Ein echter Cydonia- bzw. ausdrücklich benannter verfügbarer LLM-Workflow in ComfyUI 2: deutscher mehrteiliger Dialog mit derselben Persona, kontextgebundene Antwort, strukturierter Intent, reproduzierbares Ergebnis und gültige Python-Korrelations-IDs. Cydonia nur als qualifiziert melden, wenn die echte Version und deren Last auf dem Mac geprüft wurde.
3. Mindestens ein grafischer Zweig und eine begrenzte Korrekturschleife (sofern passende Nodes installiert) werden im echten ComfyUI-Editor bearbeitet, als API-Graph übernommen und durch Darkfluenzer ausgelöst; ohne Support den konkreten Node/Modell-BLOCKER dokumentieren, **keinen Mock**.
4. Gleichzeitig einen langen echten Medien-Render und mindestens zwei Kundenchat-Aufträge starten: **keine gemeinsame Queue-Blockade**, Dialoge trotzdem sequenziell **pro Kunde**; LLM-Latenz p50/p95, CPU/GPU-/Unified-Memory-Auslastung und Render-Verlangsamung messen, statt Echtzeit-Leistung zu versprechen.
5. ComfyUI-2-Ausfall/Neustart darf keine laufenden Medienaufträge abbrechen und keine Chatwoot-Doppelantworten erzeugen. Medieninstanz-Ausfall darf keinen anderen Kundenchat-/KI-Antwortpfad unterbrechen.
6. Sprach-/Vision-/TTS-Pfade erst aktivieren, nachdem ihre echten Custom Nodes, Modelle, Dateitypen und Ergebnisse verifiziert sind. KI-Qualitätsentscheidung ersetzt niemals serverseitiges Zahlungs- oder Freigabegate.

**Status:** `ComfyUI 1 = bestehend/abgenommen`; `ComfyUI 2 = BESCHLOSSEN, UMSETZUNG UND ECHTER TEST OFFEN`. Keine bestehenden Status oder PASS-Werte rückwirkend ändern.

## 4B. Native M4-Max-CPU- und macOS-Architektur: DarkBot-Quell-Reuse + Chatwoot ohne Docker (Beschluss 15.11.2026)

**VERBINDLICH:** Sämtliche Dienste von Darkfluenzer und Chatwoot laufen **nativ auf macOS/ARM64**; **kein Docker, Docker Compose, Podman, Container, Linux-VM oder Rosetta** als Betriebsschicht. Der Apple M4 Max hat 12 Performance- und 4 Efficiency-CPU-Kerne und 128 GiB physisch geteilten Unified Memory. Nicht alle CPU-Kerne müssen genutzt werden; macOS-QoS ist **keine garantierte Performance-Core-Affinität**. Die DarkBot-Methodik wird übernommen, nicht dessen Latenzziel, Trading-Threadstruktur oder CPU-Konfiguration.

**Klare Zuständigkeiten:** Darkfluenzer/Python = Kunden-, Nachrichten-, Job-, Zahlungs- und Freigabe-Koordination auf der CPU. **ComfyUI 1 und ComfyUI 2 einschließlich Modell-Backends = sämtliche Bild-/Video-/LLM-/TTS-Rechenarbeit**, mit ihrer eigenen Apple-Metal-/MPS-Nutzung. Darkfluenzer bekommt **keine** eigene KI-Modellengine und keine unnötige GPU-Ressourcenarchitektur. Chatwoot v4.19.1 **bleibt Original-Ruby/Rails**, wird nicht in Python/Rust übersetzt. Nur Chatwoot-Webhooks/-API werden vom bestehenden Python-Backend angebunden. Das ist eine einheitliche Bedienoberfläche, kein Auftrag zum Sprach-Rewrite.

### 4B.1 DarkBot – absolut konkrete Quellpfade für Claudes Übernahme

**Read-only-Quellroot auf diesem Mac:** \`/Users/sawyer_ma/Desktop/Firma/2_DarkMa/6_DarkBot/DarkBot/\`.
**GitHub:** \`sawyerma/darkbot\`, überprüfter Stand \`b5b3921b5a2dfb1c0b85e9213b98e933948c9aaf\` (15.11.2026). Alle folgenden Pfade sind **relativ zu diesem Root** und benennen tatsächlich geprüfte Dateien. Claude liest zuerst den realen Inhalt und die enthaltenen Tests, statt den Mechanismus ein zweites Mal zu erfinden. DarkBot, BSC, Project_0 und ihre Builds/Worktrees/Evidence **niemals ändern, aufräumen oder als Runtime-Abhängigkeit verlinken**. Passende generische Bash-/macOS-Prinzipien in Darkfluenzer lokal übernehmen; Rust-/Go-Code nur auf konzeptioneller Ebene in Python/Ruby adaptieren.

| Originalpfad in DarkBot | Im Quellcode belegter Mechanismus | Konkreter Reuse für Darkfluenzer |
|---|---|---|
| \`ops/darkbotctl\` | \`write_plist\`, \`write_capture_plist\`, \`p0_analytics_up\`, \`locked\`, \`foreign_capture\`, \`clean_stale_reporter\`, \`healthy\`, \`cmd_down\`, \`cmd_status\`; \`launchctl bootstrap/bootout\`, Benutzer-\`LaunchAgents\`, Start-/Stop-Lock, PID-/Ownership-/Health-Prüfung | **Shell-Mechanik selektiv übertragen** in einen **eigenen schlanken** Darkfluenzer-Dienstcontroller; projektspezifische Labels/Pfade. **Nicht** das komplette Trading-\`darkbotctl\` oder seine P0-/BSC-Kommandos kopieren. |
| \`project_0/native/crates/runtime/src/host.rs\` | \`HostEvidence\`, \`read\`, \`sample\`, \`qualifying\`, \`active_cpus\`, \`low_power_mode\`, \`thermal_pressure\`, \`install_qos\`, \`set_thread_qos\`; ARM64-/Rosetta-/VM-/Perflevel-Prüfung | **Host-Abfragen für Python/macOS nachbauen oder minimal nativ anbinden**, keine Rust-Engine einführen. Native \`sysctl\`-/libnotify-APIs, keine fixen Kernzahlen. |
| \`project_0/native/crates/common/src/qos.rs\` | \`ThreadRole\`, \`install\`, \`enter\`, \`refusals\`: Threadrollen, Plattform-Hook, Ablehnungszähler | Rollen-/Status-Prinzip übernehmen; Klassen nur auf geeigneten **echten OS-Threads**, nicht auf frei wandernden asynchronen Tasks. |
| \`bsc/engine/crates/geth_ipc/src/host.rs\` | \`HostTopology::capture\`, \`performance_cpus\`, \`set_current_thread_qos\`, \`QosOutcome\`: \`sysctl\` für P-/E- und Cache-Topologie, \`pthread_set_qos_class_self_np\` mit \`pthread_get_qos_class_np\`-Readback | **Exakte native macOS-API als Vorlage**, set/readback/failure dokumentieren. QoS bleibt advisory, **kein CPU-Pinning**. |
| \`bsc/geth/overlay/darkbot/fastlane/qos.go\` + \`bsc/geth/overlay/darkbot/fastlane/qos_darwin.go\` | \`applyPermanentThreadQoS\`, \`runtime.LockOSThread\` und native pthread-Bridge; standardmäßig QoS OFF | **Nur OS-Thread-Bindungsprinzip**, **kein Go-Code** oder geth übernehmen. |
| \`project_0/native/crates/common/src/channel.rs\` | \`bounded\`, \`Producer::try_push\`, \`Wakeup::notify/wait\`, Queue-/Overflow-Zähler | Bestehende Python- und ComfyUI-Jobqueues begrenzen, Backpressure und Wakeup sauber integrieren; **kein neuer Rust-Queue-Service**. |
| \`project_0/native/crates/runtime/src/orchestration/remote_workers.rs\` | \`result_queue\`, \`push_result\`, \`wait_stopped\`, blockierter Producer wird bei Platz/Shutdown geweckt | Geordnetes Stoppen, persistierte Python-Outbox und eventbasierte Worker-Wakeup-Semantik; Sidekiq bleibt Chatwoots eigener Worker. |
| \`project_0/native/crates/common/src/timing.rs\` | \`Clock::try_new\`, \`Timeline::mark/interval\` | Monotone \`time.monotonic_ns()\`-Messungen, getrennt von UTC-/Chatwoot-Zeitstempeln. |
| \`project_0/native/crates/common/src/histogram.rs\` | \`Histogram\`: p50/p95/p99-Messung mit ausdrücklich begrenzter Bucket-Auflösung | Für echte Latenzstichproben adaptieren, Quantile/Samplezahl korrekt ausweisen; **kein** 1-ms-Trading-Ziel. |
| \`project_0/native/crates/runtime/src/storage/preflight.rs\` | Disk-/Memory-/Swap-/Pressure-Messbasis und nicht geratene Kapazitätszustände | Nur generische Hosttelemetrie verwenden; keine Solana-Journal-/Chain-Kapazitätslogik kopieren. |
| \`bsc/native/evidence/c1/c1-10-gates-20261026T003339Z/c1-6.txt\` | Realer Mac16,6/M4 Max, 12P+4E/128 GiB; 11/11 C1.6-Hosttests PASS | **Bestehende Hardware-Evidence zitieren**, Darkfluenzer-Integration separat testen. |
| \`project_0/docs/STATUS.md\` | \`P6-MT.12 M4 runtime\`: umgesetzte Host-/Threadrollen, LOCAL_PASS; M4-Latenzgate P6-MT.15 offen | **Wahrheitsgemäßen Status** und Grenzen beachten; keinen P0-PASS als Darkfluenzer-PASS umdeuten. |
| \`bsc/docs/1_PLAN/STATUS.md\` | \`F3 (=AG1)\` CPU-QoS-A/B-Vergleich, \`P0 Iteration 2\` BSC-spezifische Spin-/QoS-Messungen | **A/B-Methode**, nicht Busy-Spin, INTERACTIVE-Default oder Trading-Limits übertragen. |
| \`darknode/docs/APPLE_SILICON_M4_HOST_UND_OPTIMIERUNG_V1.md\` | Beschreibt Reuse-Matrix; ausdrücklich **„VERBINDLICHE PLANUNG, KEIN IMPLEMENTIERTES HOST-GATE“** für DarkNode | Als sekundäre Planungsreferenz lesen; keine DarkNode-SOLL-Aussage als bestandene DarkBot-Abnahme ausgeben. |

**Reuse-Grenze:** macOS-/Shell-Primitiven und Prüf-/Prozessregeln sind fast direkt adaptierbar; existierende Rust- und Go-Typen sind **nicht 1:1** Python-/Ruby-Quellcode. Die manuelle Übertragung wird minimal gehalten: nur schon vorhandene Mechanismen, soweit benötigt; keine zusätzliche Rust-Laufzeit, kein selbstgebauter Service-Mesh, kein CPU-Pinning und kein aktiv wartender Spinloop.

### 4B.2 Native Umsetzung in Darkfluenzer und Chatwoot

1. **Bereits vorhandene Dateien zuerst bearbeiten:** \`launcher/\`, \`backend/src/darkfluenzer/runtime.py\`, \`config.py\`, \`server.py\`, \`backend/tests/test_runtime.py\` und \`config.example.toml\`. Bei Bedarf **einen** schlanken eigenen \`ops/darkfluenzerctl\` und wenige projektlokale \`launchd\`-Definitionen ergänzen. Keine zweite Runtime-Verwaltung. Pro Prozess gibt es genau **einen** Start-/Stop-/Restart-Owner (\`launchd\` **oder** der aktuelle Python-Supervisor), niemals beide zugleich. Bereits funktionierenden pinken C-Launcher, F3a/F3b und Medien-FIFO erhalten; laufende Jobs beim Umbau nicht unterbrechen.
2. **Native Dienstprozesse:** Darkfluenzer Python-Backend, zwei unabhängig verwaltbare ComfyUI-Prozesse (\`media\`, \`ai\`), Chatwoot Rails/Puma, Chatwoot Sidekiq, PostgreSQL mit benötigter Chatwoot-Erweiterung \`pgvector\` und Redis. Alles lokal auf ARM64, konfigurierte Ports/Labels/Pfade/Logorte, Versionen gepinnt. Keine Docker-/Compose-Dateien in Startpfaden und kein VM-Fallback. Chatwoot selbst möglichst **unverändert** lassen.
3. **Korrektes \`launchd\`-Modell:** DarkBots \`ops/darkbotctl\` benutzt \`gui/$(id -u)\` und \`~/Library/LaunchAgents\`, d. h. **Start in der Benutzer-Sitzung, nicht vor Login als LaunchDaemon**. Für Darkfluenzer zunächst derselbe Ansatz. Health statt bloßer PID, Eigentümerprüfung statt \`pkill\`, idempotentes Bootstrapping, geordneter Stopp; nach Crash keine doppelte Medienausführung oder Chatwoot-Nachricht. Der C-Starter bleibt eine dünne Oberfläche für diesen Owner.
4. **CPU-/QoS-Politik:** Native Defaults zuerst messen. Dauerhafte fachlich relevante Python-OS-Threads können \`USER_INITIATED\` als A/B-Variante erhalten; Hintergrundindizierung \`UTILITY\` nur nach Messung. Puma, Sidekiq, PostgreSQL und Redis **nicht pauschal höher priorisieren**, deren Threads/Prozesskonfiguration getrennt messen. Mit \`pthread_get_qos_class_np\` Ist-Wert und Fehler dokumentieren. Keine garantierte Bindung an P-Kerne, keine volle 16-Core-Auslastung als Selbstzweck.
5. **Chatwoot Upstream-Parameter im Original prüfen:** In \`chatwoot/chatwoot@v4.19.1\`: \`.ruby-version\` = Ruby **3.4.4**, \`Gemfile\` = Rails **7.2.3.1**, \`.nvmrc\` = Node **24.22.1**, \`package.json\` = pnpm **10.x**; \`config/puma.rb\`: \`RAILS_MAX_THREADS\` Default 5, \`WEB_CONCURRENCY\` Default 0; \`config/sidekiq.yml\`: \`SIDEKIQ_CONCURRENCY\` Default 10; \`config/database.yml\`: Poolgröße abhängig von Sidekiq-/Puma-Threads. Diese Werte sind **Default-Baselines, kein bereits optimales M4-Profil**. Unter gleichzeitiger ComfyUI-Last Puma-Threads/-Workers, Sidekiq-Concurrency, Datenbankverbindungen, Queues und Speichernutzung A/B vergleichen.
6. **Unveränderte Koordination:** React bleibt einziges Cockpit; Chatwoot-Vue-Frontend nicht einbetten, Chatwoot-Bridge im eigenen Python-Backend (s. Chatwoot-ZIP in Frontend F4), Kundenzuordnung/Gates in SQLite. ComfyUI-Modelle allein übernehmen KI-/GPU-Rechnung; der Python-Koordinator ist lediglich Job-/Ressourcen-Zulassungsinstanz, keine zweite KI-Engine.

### 4B.3 Neue Abnahmegates – Einbindung in vorhandene Phasen

| Gate | Phase | Realer PASS-Nachweis; bis dahin OFFEN |
|---|---|---|
| \`NATIVE-01\` | S1-Erweiterung / S6 | Auf echtem Mac alle neuen Prozesse nativ ARM64, Host-Fingerprint mit DarkBot-Evidence abgeglichen, kein Rosetta/Container/VM; **historischen S1-PASS nicht überschreiben** |
| \`NATIVE-02\` | S4 / S6 | \`launchd\`-Start-/Stop-/Neustart, kein Fremdprozess beendet, keine Doppelinstanz, kein verlorener/beim Recovery doppelt ausgeführter Auftrag, eigenständiger ComfyUI-1-/2-Ausfall |
| \`NATIVE-03\` | S4 | Chatwoot v4.19.1 Rails/Puma + Sidekiq + PostgreSQL/pgvector + Redis wirklich unter macOS installiert, erreichbar, Restart und echte Telegram-Webhooks/Antworten über Python-Bridge; ohne Docker |
| \`M4-CPU-01\` | S6 | Realer Hostreport (ARM64/Rosetta/VM, P/E, Cache, aktiver CPU-Stand, Thermal, Low Power) und QoS-Set/Readback/Refusal nur bei eigenem dauerhaftem Thread |
| \`M4-CPU-02\` | S4 / S6 | Chatwoot Puma/Sidekiq/DB-Connection- und Python-Queue-Parameter anhand Messung unter ComfyUI-Last gewählt; p50/p95/p99, CPU, RSS/Swap, Queuezeiten und Fehlerraten vor/nach Maßnahme dokumentiert |
| \`M4-CPU-03\` | S6 | Gleichzeitiger echter Medienrender + mindestens zwei KI-Chat-Aufträge + Chatwoot-Zustellung; keine gemeinsame Queue-Sperre und keine verlorene/duplizierte Nachricht; Render-/Antwortlatenzen gemessen |

**Status aller neuen Gates: OFFEN / NICHT AUF DIESEM MAC ABGENOMMEN.** Bereits vorhandene S1-, F1–F3b- und BSC-/Project_0-Evidence bleibt gültig, aber wird nicht als bestanden für neue Chatwoot-/M4-Integrationen ausgegeben.

## 5. Eine Datenbank, minimale Tabellen, vollständiger Nachweis

**SQLite** ist zentrale Autorität. Die Tabellen werden nur so weit getrennt wie nötig:

| Tabelle | Inhalt |
|---|---|
| `customers` | Kundennummer, botgebundene Telegram-User-ID, Status |
| `messages` | Nachricht, Gesprächszuordnung, Zeit, deduplizierte Telegram-ID |
| `orders` | Wunsch, Angebot, Typ Bild/Video, Preis, Verkaufsstatus |
| `payments` | Transaktions-ID, Anbieter, Betrag, Währung, Zahlung/Refund |
| `jobs` | zugeordneter Auftrag (leer bei Evaluationsrenderungen ohne Kundenbezug), Engine, Prompt, Renderstatus, Seeds |
| `artifacts` | Master, Masken, Kandidaten, Dateien und unveränderliche Hashes |
| `approvals` | Freigegebenes Artefakt, Hash, Betreiber, Zeitpunkt |
| `deliveries` | tatsächlich versandtes Artefakt, Kunde, externe Versand-ID |
| `events` | nachvollziehbare Zustandsübergänge und technische Auditdaten |
| `media` | Galerie-Index aller erzeugten Bilder/Videos: Pfad, SHA-256, Art, Job/Artefakt/Auftrag, laufende Nummer ohne Auftrag; eigene Medien löschbar (im Journal festgehalten), Kundenmedien unveränderlich |

**Primär-/Fremdschlüssel, Transaktionen und Eindeutigkeitsregeln bleiben Pflicht**, auch bei nur zehn Tabellen. Bei mehreren Nachrichten derselben Person muss dieselbe Kundennummer zurückkommen; parallele Erstnachrichten dürfen keine Doppelanlage erzeugen. Eine Zahlung ist nur mit korrekter `order_id`, Betrag, Währung und verifiziertem Provider-Ereignis gültig. Kein API-Retry darf doppelt liefern.

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

**Umsetzungsstand (14.11.2026):** `server.py` (aiohttp, ein Origin `[server]` in `local/config.toml`; Host-Prüfung jeder Anfrage, Origin + Sitzungs-Cookie für WebSocket, zusätzlich CSRF für Befehle; Build mit `no-cache`/`immutable`) und `stream.py` (Hello/Welcome mit Schema-Fingerabdruck, STATE `comfy.status`, EVENT `job.completed` aus dem `events`-Journal mit Catch-up/Lücke/Live, geordneter Versand je Client, Heartbeat, Schließen mit 1001 beim Beenden); Befehle `comfy_start`/`comfy_stop` idempotent je `request_id`. STATE `jobs.active` (ComfyUI-`/queue`, Darkfluenzer-Job-ID in `extra_data`) und `comfy.workflows` (Manifest + Modellbereitschaft); Ausgaben nur unter `local/evaluation` über `/api/v1/media/…` mit Sitzung. **F3a (14.11.):** Befehle `render` (Werte + Eingabebilder, FIFO im Backend, gleiche Pipeline wie CLI), `set_workflow_enabled`, `open_workflow`, `adopt_workflow`, `create_workflow`, `delete_workflow`, `cancel_job`, `pause_queue`; Registry-Änderungen formatbewahrend (tomlkit) und erst nach vollständiger Validierung atomar gespeichert, externe Änderungen am Manifest werden live übernommen; Editor-Kopie je Workflow in `local/ComfyUI/user/default/workflows/<key>/`; Eingabebilder inhaltsadressiert unter `local/evaluation/inputs/`; laufende Jobs tragen die Prozess-ID, verwaiste werden beim Start als abgebrochen markiert. Jede Renderung über `render_evaluation` (CLI) ist ein Job ohne Kundenbezug im Journal. **F3b (14.11.):** Schema v2 (additive Migration) mit Tabelle `media`; der Beobachter indiziert neue, fertig geschriebene Ausgaben (`media_settle_s`) chronologisch und SHA-dedupliziert und meldet sie als EVENT `media.added`; `/api/v1/media-page` liefert Protobuf-Seiten auf Aufruf, `/api/v1/media/…` nur indizierte Dateien (`?download=1` als Anhang). Befehl `delete_media` (Schema v3) löscht eigene Medien samt byte-gleicher Kopien, EVENT `media.removed`; IDs/Nummern werden nie wieder vergeben. `darkfluenzer restart` verweigert den Neustart, solange Renderjobs warten oder laufen. Start: `python -m darkfluenzer serve`.

**Betriebsstabilität:** Ein Adapterfehler darf ComfyUI und andere Plattformen nicht stoppen. API-Berechtigungs- und Verbindungsfehler sichtbar melden; nur notwendige Retries und konsistente Backups. Gekoppelte Versionen von Backend/Frontend/Protokoll zusammen deployen; bei fehlerhafter Version zur letzten getesteten Anwendung zurückkehren, ohne Kundendaten oder Freigaben zu verlieren.

## 7. Nur sechs Phasen

| Phase | Ziel | Abnahme |
|---|---|---|
| **S1 — Starter** | Mac-Bestand erfassen; pinke `C`-App startet/stoppt ComfyUI | Doppelklick, Health, idempotenter Neustart; keine fremden Prozesse gekillt |
| **S2 — Foto** | Masterbild + Identität + Masken/SDXL-Editing + Refinement | Drei reproduzierbare Fotos, Master-Herkunft, lokale Qualitätsbewertung |
| **S3 — Video** | Wan-I2V und LTX-Vergleich, Motion/Temporal/Export | Real gerenderter Mac-Clip, FPS, Dauer, Speicher, Flicker/Identität geprüft |
| **S4 — Dialog** | Zweite ComfyUI-KI-Instanz mit grafischen LLM-/Intent-Workflows + Chatwoot-Adapter + stabile plattformübergreifende Kundennummer + SQLite | Zwei unabhängige ComfyUI-Prozesse, echter LLM-Dialog/Intent, getrennte Queues, korrekte Kunden-/Conversation-Zuordnung und gleichzeitiger Medienrender geprüft |
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

**Regression nach Backend-Migration (14.11.2026, `backend/`):** `launcher/install.sh` neu ausgeführt (venv-Probelauf: nur das eigene Paket neu verlinkt, Trainings-Extras erhalten); per LaunchServices: Öffnen bei laufender ComfyUI → `already_running`; `comfy stop` → nur eigene PID beendet, Port frei; App-Start aus gestopptem Zustand → bereit nach 4,8 s, Browser danach; zweiter Doppelklick → `already_running`, eine PID; pytest 55/55 – PASS.

**Starter auf Cockpit umgestellt (14.11.2026):** Doppelklick → `darkfluenzer up` (eigener Cockpit-Server, wartet auf `/healthz`) → Cockpit-URL öffnen → `darkfluenzer comfy start` (unveränderte einzige ComfyUI-Startlogik). „Stoppen“ = `darkfluenzer down` (nur eigener Server + eigene ComfyUI); `darkfluenzer restart` startet nur den Server neu (Updates), ComfyUI läuft weiter. Alle Start-/Stopplogik in `runtime.py`; fremde Prozesse auf dem Port werden erkannt, nie beendet. Integrationstest: `up` echt + idempotent, `restart` neue PID, `down` Port frei, fremder Port-Inhaber → abgewiesen. Mac 14.11. 20:10 aus vollständig gestopptem Zustand: `up` → started, Cockpit erst danach geöffnet, ComfyUI → started (app.log). Hinweis: nach jeder Änderung der App fragt macOS einmal nach Zugriff auf den Schreibtisch-Ordner (Ad-hoc-Signatur). **Offen:** zweiter Doppelklick, Stoppen, Neustart und Fehlerfall mit dem neuen Starter am Mac (unterbrechen ComfyUI, daher nicht während laufender Nutzung).

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

1. Eine fachliche Python-Backend-Anwendung, eine SQLite-Datenbank, ein Modell-/Workflow-Manifest, ein Protobuf-Vertrag, ein React-Frontend; **zwei externe, unabhängig laufende ComfyUI-Worker** (Medien und KI) sowie der beschlossene Chatwoot-Kanaldienst. Kein zusätzlicher Broker, zweiter eigener Business-/CRM-Dienst, separater Gateway-Prozess oder Plugin-Framework.
2. Erst reale Funktion, dann mögliche Abstraktion. Keine ungenutzten Interface-Schichten, leeren Module, doppelten State-Owner oder Aufteilung einer kleinen Funktion in zehn Dateien.
3. **Wenige gezielte Tests statt Testmasse:** pro neuer Funktion Normalfall, relevanter Fehlerpfad und nur notwendige Regression; ein echter Mac-Test für ComfyUI und ein E2E-Test für die spätere Zahlungs-/Freigabekette. Keine pauschalen hohen Testzähler, großflächigen Mocks oder mehrfachen identischen Gate-Prüfungen ohne zusätzlichen Erkenntniswert.
4. **Sicherheit nicht künstlich maximieren:** Die tatsächlich notwendigen Grenzen bleiben strikt: validierte Eingaben, lokal gebundene Server, geschützte Tokens, autorisierte Schreibbefehle, verifizierte Zahlung, persönliche Betreiberfreigabe, exakte Kunden-/Artefaktbindung. Keine zusätzlichen Security-Subsysteme, komplexen Rollensysteme oder Auditrituale ohne nachgewiesenes Risiko.
5. Keine erfundenen PASS-Berichte: Modell- und GUI-Funktionen erst als betriebsbereit markieren, wenn die passende reale Ausführung tatsächlich geprüft ist. Tests sind Mittel zum Nachweis, kein Selbstzweck.
6. Eigenständige Darkfluenzer-Kopie der relevanten DarkBot-Technik; **niemals** Laufzeitabhängigkeiten, gemeinsame Datenbanken oder verborgene Imports zwischen beiden Projekten.
7. Änderungen direkt auf `main` mit sauberem Git-Paket und Push; bestehende Mac-Daten und S1-Abnahme respektieren.



1. **Single Source of Truth:** Diese Datei ist der einzige normative Masterplan. Technische Kommentare oder Tests dürfen Regeln präzisieren, nicht widersprechen.
2. **Eine fachliche Anwendung, modulare Funktionen:** Ein lokaler Python-Dienst mit getrennten Modulen, zwei ComfyUI-Laufzeitprozessen und Chatwoot als externem Kanaldienst; kein selbstgebautes Microservice-System und kein zusätzlicher Message-Broker. Chatwoot behält PostgreSQL/Redis, Puma und Sidekiq, **aber Docker/Compose/Container/VM sind ausgeschlossen**; alle Dienste laufen nativ auf macOS/ARM64 gemäß §4B.
3. **Wenig Ordner, klare Eigentümer:** Ein Codepaket, ein Workflow-Verzeichnis, ein Kundenbaum, eine SQLite-Datenbank. Keine redundanten Kopien und konkurrierenden Statusdateien.
4. **Workflow-Verträge:** ComfyUI braucht UI-JSON und separaten API-Export; nur registrierte und validierte API-Workflows dürfen vom Bot ausgeführt werden.
5. **Kein globales `pkill`:** Launcher verwaltet nur die beiden konkret zugeordneten ComfyUI-Instanzen, mit unabhängigen konfigurierbaren Loopback-Ports (Defaultvorschläge 8188/8189), ohne Terminal; laufende Medien-FIFO nie ungefragt abbrechen. Python-/Conda-Pfade lokal konfigurieren, nicht im Code erzwingen.
6. **Sicherheit und Reproduzierbarkeit:** Secrets außerhalb Git (macOS Keychain oder geschützte lokale Konfiguration), alle privaten Daten in `local/`; Modell-Hashes, Seeds, Workflow-Git-Revisionen und Freigaben dokumentieren.
7. **Deterministische kritische Regeln:** Zahlung, Sales-Zähler, Kundenzuordnung und Liefer-Gate werden durch Code/DB bestimmt, **nicht** durch den LLM-Wortlaut.
8. **Tests statt Annahmen:** Apple-MPS-Backend, Custom Nodes, Quantisierung, Lizenz und Renderqualität müssen tatsächlich geprüft werden; Qualitätsverbesserung nur mit A/B-Vergleich.
9. **Klarer Änderungsweg:** Änderungen auf `main` mit Commit und dokumentierter Planänderung. Kein neues Hilfsverzeichnis, solange nicht ein konkreter Test oder Bedienungsfall dies erforderlich macht.
10. **Fiktive erwachsene Figur:** keine fremde Person imitieren; Transparenz über künstliche Identität, vereinbarte Inhalte und kommerzielle Rechte.

## 9. Änderungsprotokoll

**V1.9 — NATIVES MACOS/M4-MAX-CPU-REUSE (15.11.2026):** DarkBot-Quellpfade samt belegten macOS-/CPU-/QoS-/launchd-Funktionen unter §4B aufgenommen; Shell-/Hostprinzipien selektiv lokal adaptieren, keine Rust-/Go-Trading-Engine übernehmen; Chatwoot v4.19.1 als unverändertes Ruby/Rails nativ mit Puma/Sidekiq/PostgreSQL/Redis statt Docker/Compose/VM, Python-Bridge; neuer Host-/Chatwoot-/Last-Nachweis OFFEN. Keine Änderung an S1-/F1–F3b-PASS.

**V1.8 — ZWEI COMFYUI-INSTANZEN (14.11.2026):** Instanz 1 bleibt für Foto/Video/Medien-FIFO; Instanz 2 führt Text-/Dialog-/Prüf-/TTS-Workflows graphbasiert aus, eigene Queue/Port/Nodes, gemeinsamer Python-/SQLite-Gatekeeper; primär keine separate Pflicht-LLM-Serverpipeline. Architektur verbindlich, KI-Instanz noch OFFEN. Frontend-Vertrag entsprechend angepasst.

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