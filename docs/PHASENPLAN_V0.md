# DARKFLUENZER — PHASENPLAN V0 (verbindlicher Gesamt- und Implementierungsplan)

**Version:** 0.5 · **Stand:** 15.11.2026 · **Repository:** `sawyerma/Darkfluenzer`, ausschließlich `main`
**Status:** verbindlich. Bestandsaufnahme gegen Code (`main` 62c4bc9), Chatwoot-v4.19.1-Quellcode und die Betreiber-ZIP abgeschlossen; abgeglichen mit FRONT V1.10 (DF-PUSH A–D, F7-Cockpitreferenz) und BACK V1.13; V0.3: Auflösungsregel (Original ≥ 1K, darüber Upscaler, Instagram-Ausgabeprofile, §9.7) und Default-Nutzer als Produktionsassistent mit Rückversand per Telegram (§8.1). **V0.4: verbindliche Reihenfolge Block A (ComfyUI + Dateien) → Block B (KI-Modelle und Produktionsworkflows) → Block C (Telegram/Instagram, Kundenbetrieb), keine parallele Entwicklung (§12); verbindliche Dokumente (§0).** Umsetzung ab A1.

## 0. Dokumentenhierarchie

| Dokument | Rolle |
|---|---|
| **`PHASENPLAN_V0.md`** (dieses) | **Verbindlicher Gesamtplan:** Ziele, Architekturentscheidungen, Reihenfolge, Abhängigkeiten, Status, Abnahme. Bei Widerspruch gilt V0. |
| `PHASENPLAN_FRONT_V1.md` | **Verbindliche technische Frontend-Spezifikation:** UI/UX, Graphite-Gestaltung, Bedienlogik, Protobuf-Bindung und die Push-Aktualisierungsarchitektur ohne Frontend-Polling. V0 übernimmt diese Regeln vollständig (§5). |
| `PHASENPLAN_BACK_V1.md` | **Technische Backend-Referenz:** gilt weiter, soweit sie V0 nicht widerspricht; überholte Festlegungen sind dort als „→ V0“ gekennzeichnet. |
| `design/Darkfluenzer_Cockpit_Interaktiv.html` | **Verbindliche Gestaltungs- und Bedienreferenz** (FRONT F7, Betreiberfreigabe 15.11.2026); Klickprototyp, kein Produktivcode. |
| `ki_modelle.md` | **Modellliste:** Bestand, laufende Downloads, Präzision/Quantisierung, Größe, Quelle mit Revision, vom Betreiber freizuschaltende Modelle (§14.1). |
| `archiv/` | **Nicht verbindlich:** Musterquellen und Altmaterial (z. B. Chatwoot-ZIP, unversioniert). |

**Verbindlich sind ausschließlich** V0 (Gesamtplan und Reihenfolge), FRONT V1 (UI/UX, Push, Protobuf) und die F7-Referenz; BACK V1 nur, soweit V0 nicht widerspricht; alles unter `docs/archiv/` ist nicht verbindlich. Jede noch nicht umgesetzte Anforderung aus FRONT/BACK ist einer V0-Phase (§12) zugeordnet. Kein PASS ohne echten Funktionstest auf dem Mac.

> **Vorrangbeschluss DF-PUSH-PROTOBUF-E2E-2026-11-15:** Jeder Medien-/Referenz-/Chat-/Kunden-/Job-Workflow und jedes bedienbare Feld erhalten **im selben Implementierungspaket** den vollständigen Python-Owner→typisiertes Protobuf→ein vorhandener WebSocket→React-Push-Hinweg sowie bei Bedienung den Protobuf-Command→Python→persistierte Receipt→Push-Rückweg. **Keine periodischen fachlichen Browserabfragen**, große Historien nur versionsgebunden/on-demand. Verbindliche Details, Ist/Soll und Abnahme: [PHASENPLAN_FRONT_V1.md](PHASENPLAN_FRONT_V1.md) (Abschnitt `DF-PUSH-PROTOBUF-E2E-2026-11-15`) und [PHASENPLAN_BACK_V1.md](PHASENPLAN_BACK_V1.md) (gleicher Beschluss). In V0 umgesetzt in §5 und in den Abnahmen jeder Phase (§12). Python-/ComfyUI-/Kanal-Adapter-Architektur bleibt eigenständig (Chatwoot entfällt, §6); kein Rust-/DarkBot-Gateway, kein zusätzliches Dashboard. Vorhandene Phasen-/Designverträge bleiben gültig, soweit sie dem neuen Push-/Protobuf-Rundweg nicht widersprechen.

## 1. Ziel

Darkfluenzer erzeugt auf dem MacBook Pro M4 Max (128 GB, macOS nativ) vollständig lokal fotorealistische Bilder und Videos **einer festen synthetischen erwachsenen Influencerin** – möglichst wie echte Kameraaufnahmen – für zwei gleichwertige Bereiche: **Instagram** (Lifestyle, Mode, Reise, Sport, Strand, Reels) und **Erwachsenenproduktion** (erotisch bis explizit, ausschließlich die synthetische Figur). Identität über Posen, Perspektiven, Kleidung, Szenen, Bearbeitungen und Videos stabil. **Maximale Qualität vor Geschwindigkeit.**

Darkfluenzer ist zugleich Kunden-Cockpit (F4): Kunden über **Instagram und Telegram (verbindlich)**, später weitere Kanäle (WhatsApp u. a.), kanalübergreifende Kundenakte, KI-Dialog, Medienaufträge, Zahlung, Freigabe, Zustellung. Der **Content-Cloner** ist ein zusätzlicher Produktionsauslöser: freigegebene Betreiber-Accounts senden Bilder/Reels mit fünf Kurzbefehlen oder freien Anweisungen (§8); als **Default-Nutzer** erhält der Betreiber die postfertigen Ergebnisse per Telegram zurück und postet sie vom Handy (§8.1). Die normale Medienproduktion bleibt der Kern; Bilderzeugung ohne Instagram/Telegram ist jederzeit möglich.

## 2. Verbindliche Regeln

1. **Leichte Tendenz zu besserem Bild, aber in angemessener Zeit** (Betreiberentscheidung 15.11.2026): Modell, Identitätsmethode, Modellvariante (z. B. Turbo/Raw, 3B/7B) und Auflösungsweg entscheiden reale A/B-Tests mit den Charakterbildern des Betreibers auf diesem Mac. Unter den Varianten, die das je Ausgabeart gemessene und vom Betreiber bestätigte Zeitbudget einhalten (festgelegt in B2/B4), gewinnt die beste Bildqualität; ist eine Variante deutlich besser, aber langsamer, entscheidet der Betreiber. Ranglisten und Herstellerangaben sind nur Kandidatenquellen.
2. **Identität hat Vorrang:** gleiches Gesicht, gleiche Figur/Anmutung über alle Stufen. LoRA ist Mittel, nicht Ziel; die messbar stabilste Methode oder Kombination gewinnt. „Identität gesperrt“ = Auftrag nutzt verbindlich dieses Profil; Abweichungen werden zurückgewiesen, keine Garantie.
3. **Explizite Bearbeitung nur abgeleitet** (maskiert vom freigegebenen Bild; im Bearbeitungsschritt 0 Pixel außerhalb der Maske, automatisch geprüft). **Video nur vom freigegebenen Foto** bzw. bei Bewegungsübertragung mit dem freigegebenen Charakterbild als Identitätsreferenz.
4. **Face-Swap ausschließlich auf eigenen, synthetisch erzeugten Bildern.** Nie auf fremden Referenzfotos/-videos; fremde Vorlagen liefern nur Pose, Komposition, Licht, Stil bzw. Bewegung. Gesichtszüge abgebildeter Personen werden nie Teil eines Charakterprofils; kein Ersetzen realer Personen in fremden Videos.
5. **Vollständige Reproduzierbarkeit** jedes Bildes/Videos (§9.5).
6. **Lokal, dokumentiert, nativ:** keine Cloud-Generierung, **kein Docker**, keine Electron-Pflicht, keine Parallelarchitektur; jede Modelldatei mit Quelle, Revision, SHA-256 und Nutzungsbedingungen im Manifest. Lizenzbedingungen sind **kein Auswahlkriterium** (Betreiberentscheidung 15.11.2026). Modelle werden nur nach ausdrücklicher Betreiberbestätigung gelöscht; ein Downloadplan ist keine Löschfreigabe (15.11.2026 entfernt: RealCore Illustrious, Qwen-Image 20B; Qwen-Image 2.1, Qwen-Image-2512 und FLUX.2 Dev danach wieder in die Downloadkette aufgenommen, §9.3).
7. **Präzision je Komponente** (Generierungsmodell, Encoder, VAE/Decoder, Adapter, Hilfsmodelle): beste verfügbare kompatible Originalpräzision; FP32-Komponenten bleiben FP32 (z. B. RelayVSR-Decoder); Umwandlung aus quantisierten Dateien gewinnt keine Genauigkeit zurück; Speicherformat und Rechendatentyp dokumentiert. Dokumentierte Ausnahme: mflux trainiert mit 8-Bit-Basis.
8. **Ein Cockpit:** die bestehende React-Oberfläche (vier Hauptreiter **Übersicht · Nachrichten · ComfyUI · Dateien**, Graphite, ein Stylesheet); Gestaltung und Bedienlogik nach der freigegebenen Klickreferenz F7 (`docs/design/Darkfluenzer_Cockpit_Interaktiv.html`, FRONT F7). React spricht nur mit dem Python-Backend; **nie direkt mit Plattform- oder ComfyUI-APIs**.
9. **Zwei ComfyUI-Instanzen** (§4.2) mit getrennten Warteschlangen und gemeinsamer Ressourcensteuerung; keine dritte KI-Engine.
10. **Eigene Kanal-Adapter im Python-Backend** (Betreiberentscheidung 15.11.2026): Instagram und Telegram verbindlich, weitere Kanäle später über dieselbe Adapter-Schnittstelle. Chatwoot entfällt; seine bewährten Muster werden übernommen (§6). Kein zusätzlicher Kanaldienst, keine zweite Datenbank, kein Rust-Gateway.
11. **Ehrliche Erwartung:** Einzelfotos in vielen Szenen praktisch nicht von echten Fotos unterscheidbar ist mit Kandidatenauswahl erreichbar; für jede Szene und für Video garantiert das 2026 kein lokales Modell.

### 2.1 Verbindliche Entwicklungsregeln (Betreiberentscheidung 15.11.2026, gelten für jede Phase)

- **NO HARDCODING:** keine fest codierten Modelle, Pfade, Ports, Parameter, Kunden, Workflows oder Grenzwerte – Konfiguration (`local/config.toml`) und Registry (`workflows/manifest.toml`) verwenden.
- **NO LEGACY:** keine Altlasten, Kompatibilitätsschichten oder parallelen veralteten Implementierungen; Überholtes sauber ersetzen.
- **NO MOCK:** keine simulierten Ergebnisse, Fake-Daten oder Scheinabnahmen; ausschließlich echte Funktionen und reale Tests – jede Abnahme läuft real auf dem M4 Max.
- **NO DOCKER / NO VM:** native Ausführung auf macOS/Apple Silicon; keine Container, Linux-VMs oder zusätzlichen Virtualisierungsschichten (die vorgesehenen Python-venvs sind zulässig).
- **FREE ONLY:** ausschließlich lokal betreibbare, kostenlos verfügbare Komponenten; Lizenzbedingungen werden dokumentiert, sind aber kein Auswahlkriterium (Betreiberentscheidung 15.11.2026).
- **NO JSON als Konfiguration:** TOML und die bestehenden Protobuf-Verträge; JSON nur, wo externe APIs oder ComfyUI-Workflows es technisch erfordern.
- **NO DUPLICATION:** vorhandene Funktionen wiederverwenden statt doppelte Architekturen aufzubauen.
- **PHASENPLAN FIRST:** ausschließlich nach diesem Plan; FRONT und BACK als abgestimmte technische Spezifikationen.
- **STRICT ORDER:** zuerst ComfyUI + Dateien (Block A), danach Modelle + Workflows (Block B), zuletzt Telegram + Instagram (Block C) – §12.
- **MAIN ONLY:** keine Branches oder Worktrees; direkt auf `main`.
- **MAX 2 AGENTS:** höchstens zwei parallele Agenten.
- **QUALITY GATES:** jede Phase vollständig implementieren, real auf dem M4 Max testen und erst nach bestandener Abnahme abschließen.
- **GIT:** Änderungen je abgeschlossenem Paket committen und auf `main` pushen.
- Keine zusätzlichen Frameworks, Dienste oder Architekturen ohne nachgewiesene technische Notwendigkeit.

## 3. Ist-Stand (belegt, `main` 62c4bc9)

| Bereich | Status | Beleg |
|---|---|---|
| Cockpit-Grundlage F1/F2 (React, Graphite, Protobuf-WS, Befehle, Sitzung/CSRF) | IMPLEMENTIERT | `App.tsx`, `core/realtime.ts`, `state.ts`, `commands.ts`, `stream.py`, `server.py` |
| ComfyUI-Betrieb F3/F3a (Status, Start/Stopp, Workflows, Formular, FIFO, Abbrechen/Anhalten, Öffnen/Übernehmen/Löschen/Neu) | IMPLEMENTIERT | Befehle 10–19, `Cockpit.render_worker` |
| Dateien F3b (Galerie, Push, Download, Löschen, „Aus Dateien“) | IMPLEMENTIERT | `media`-Tabelle v2/v3, Topics 21/22, Befehl 20 |
| Starter S1 (pinkes C, Health, eigene Prozesse) | IMPLEMENTIERT | `launcher/`, `runtime.cockpit_up/down/restart` |
| Kundenakte/Zahlung/Freigabe/Zustellung (Store, Gates) | TEILWEISE | 10 Tabellen, `approval.check_gate/prepare_delivery`, Trigger; **Kunden fest an Telegram gebunden** (`telegram_user_id NOT NULL`, `chat_id`) |
| LoRA-Kette F3c / BACK §0 | TEILWEISE | `training.scan/build_dataset` (≥ 15 Bilder), `train_sdxl_lora` (diffusers); **kein LoraLoader** in den 6 Graphen; kein Wan-Video je fertig |
| Engine-Entladen, Untergraphen-Import, Reproduzierbarkeit, Auftrag mit Stufen | FEHLT | kein `/free`; `ui_to_api` weist Untergraphen ab (13/15 vorgesehene Vorlagen betroffen); kein Graph-Snapshot; `jobs` ohne Parent/Version |
| Zweite KI-ComfyUI, Ressourcensteuerung | NUR SPEZIFIZIERT | eine `[comfyui]`-Konfiguration, ein Zustand `local/comfyui.json` |
| Kanal-Adapter Instagram/Telegram, LLM, Influencerinnen | FEHLT / NUR SPEZIFIZIERT | kein Adapter-Code; `Messages.tsx` zeigt „Telegram NICHT VERBUNDEN“; Chatwoot-ZIP nur Musterquelle |
| Befehls-Idempotenz | TEILWEISE | je `request_id`, nur im Speicher (max. 256, Neustart verliert sie) |
| DF-PUSH: Domain-Versionen, versionsgebundene Detailqueries, persistierte Receipts, CAS, begrenzte STATE-Queue | FEHLT (Push-Grundweg IMPLEMENTIERT) | `CommandResponse` nur ACCEPTED/REJECTED; `_Client.queue` unbeschränkt; einzige Seitenabfrage `media-page` |
| Modellbestand | BEREINIGT 15.11.2026 | vorhanden: LUSTIFY v2.0 SDXL, Wan 2.2 I2V A14B FP16 (high/low), Wan 2.2 Remix v3.0 FP8, umt5-xxl FP16, Wan-2.1-VAE, FLUX-2-VAE, Qwen-Image-VAE (= Krea-2-VAE, gleicher SHA-256); entfernt: RealCore Illustrious, Qwen-Image 20B + Qwen2.5-VL-7B, Qwen-Image 2.1 + Qwen3-VL-8B + VAE (≈ 97 GB) |

## 4. Zielarchitektur

### 4.1 Komponenten (alle nativ, `launchd`-verwaltet laut BACK §4B; keine zusätzlichen Dienste)

```
React-Cockpit ── Protobuf-WS/Befehle ── Python-Backend (aiohttp, SQLite = einzige Autorität)
                                            ├── Medien-ComfyUI 1 (:8188) – Produktion
                                            ├── KI-ComfyUI 2 (:8189) – Dialog, Vision, Prompt, KI-Prüfung
                                            └── Kanal-Adapter (Modul `channels/`): Telegram (Long-Polling, kein öffentlicher Zugang nötig)
                                                                                  Instagram (Webhook + OAuth + Medienabruf über kostenlosen Tunnel, §10.1)
```

### 4.2 Zwei ComfyUI-Instanzen und Ressourcensteuerung

| Instanz | Zuständigkeit | Warteschlange |
|---|---|---|
| **Medien-ComfyUI 1** | Foto, Video, Pose-/Tiefen-/Masken-Erzeugung (SDPose, Depth Anything 3, SAM 3.1), Inpainting, Charakterbindung, Motion Transfer, Upscaling, LoRA-Training-Workflows | bestehende persistente **Medien-FIFO** |
| **KI-ComfyUI 2** | Dialog, Bildbeschreibung (Vision), Prompt-Erzeugung, KI-Qualitäts-/Identitätsprüfung, weitere grafisch editierbare KI-Workflows (z. B. TTS, sobald eine Sprachpipeline qualifiziert ist) | eigene **KI-Warteschlange** |

**Gemeinsame Ressourcensteuerung im Backend (Zulassung):** Vor jedem Start einer Stufe prüft das Backend den gemessenen Speicherstand und die geladenen Modelle beider Instanzen; große Modelle beider Instanzen werden nicht gleichzeitig geladen, wenn die gemessene Summe die festgelegte Grenze überschreitet; die Instanz mit wartender Arbeit entlädt kontrolliert (`/free`) bzw. wartet. Grenzwerte entstehen aus realen Messungen (Speicherverlauf je Workflow), nicht aus Schätzungen. Chatgespräche dürfen durch Renderjobs nicht blockiert werden: kurze Dialogaufgaben haben Vorrang in der Zulassung; lange Renderstufen laufen nicht parallel zu großen KI-Modellen, wenn der Speicher nicht reicht. Swap-Ursachen werden gemessen, nicht behauptet.

### 4.3 Auftragsmodell

Ein **Auftrag** (manuell, Kloner-Befehl oder Kundenauftrag – derselbe Typ) besteht aus **Stufen** (z. B. Vorlage importieren → analysieren → Kandidaten erzeugen → Auswahl → Bearbeiten → Fertigstellen → Video → Freigabe → Zustellung), jede mit dauerhaftem Zustand in SQLite, Instanz, Workflow-Version, `prompt_id`, Ein-/Ausgabe-Artefakten. Wartende Betreiberentscheidungen blockieren keine anderen Aufträge. Wiederholungen gezielt, mit Obergrenze. **Wiederanlauf:** vor erneutem Start einer Stufe Abgleich mit ComfyUI (Queue + Verlauf zur `prompt_id`); fertige Ausgaben werden übernommen, nicht doppelt erzeugt.

## 5. Frontend-Aktualisierung und Vertrag (verbindlich aus FRONT V1 übernommen, inkl. DF-PUSH-PROTOBUF-E2E)

- **Push statt Polling:** ein zentraler binärer Protobuf-WebSocket `/ws/v1/stream` mit `Hello/Welcome` (Major + Schema-Fingerabdruck), **STATE** (vollständige kleine Projektion, Ordnung `(generation, seq)`, Snapshot beim Abonnieren, „veraltet“ bei Verbindungsverlust) und **EVENT** (dauerhaftes SQLite-Journal, Cursor = `events.id`, Catch-up ≤ `catchup_limit`, `CatchupComplete(gap)`, Deduplizierung `cursor ≤ lastCursor`, Journal-Ersatz-Erkennung). Heartbeat, Reconnect mit Backoff, einmaliges Neuladen bei Schemakonflikt, danach BLOCKIERT.
- **Kein periodisches Browser-Polling, keine zusätzlichen Aktualisierungskanäle pro Komponente.** Große Historien und Listen: Protobuf-Seiten per HTTP **nur bei Aufruf** (Muster `media-page`); bei `gap` lädt die betroffene Ansicht ihre Seiten neu. Detailabfragen sind **versionsgebunden**: Abfrage-Identität `connection_id + epoch + domain_version + Scope (Kunde/Kanal/Auftrag) + Filter + Seite`; abgefragt nur beim ersten synchronisierten Anzeigen, bei geänderter relevanter Version, Scope-/Filter-/Seitenwechsel, manuellem Aktualisieren oder nach Reconnect – je genau einmal; gleichzeitige gleiche Anfragen zusammengefasst, veraltete Antworten verworfen, bisherige Daten bis dahin als veraltet markiert.
- **Domain-Versionen:** je unabhängigem Owner (Kunden/Identitäten/Konversationen/Nachrichten, KI-/Persona-Einstellungen, Aufträge/Zahlungen/Freigaben, ComfyUI 1/2, Workflows, Jobs, Training, Medien/Provenienz) eine fachliche Revision, **nach** dem SQLite-Commit erhöht, plus **Backend-Epoche**; jede STATE-Projektion trägt Version und Frische/Quelle; unveränderte Projektionen werden nicht erneut gepusht.
- **Belastung:** STATE je Client begrenzt mit Latest-wins-Zusammenfassung; EVENTs werden nie still verworfen – bei Überlauf Trennung mit markierter Lücke, danach Catch-up bzw. gezielte Neusynchronisierung der betroffenen Domain (heute `_Client.queue` unbeschränkt → A1).
- **Befehle:** `POST /api/v1/command` (Protobuf, `request_id`, Sitzungs-Cookie + CSRF, Same-Origin). `ACCEPTED` bestätigt nur die Annahme; das Ergebnis ist eine **persistierte, typisierte Receipt** (`COMPLETED`/`REJECTED`/`FAILED`/`UNKNOWN`, bei Bedarf `CANCELLED`; gebunden an `request_id`, Entität und Revision) plus passende STATE/EVENT-Projektion – React zeigt erst den belegten Zustand. Mutierende Befehle tragen die erwartete Domain-/Entitäts-Revision (**CAS**); gleiche `request_id` mit gleichem Inhalt → höchstens ein Render-/Versand-/Zahlungseffekt, mit anderem Inhalt → abgewiesen; bei Transport-`UNKNOWN` kein blinder Neuversuch. Idempotenz ab A1 **persistent** in SQLite.
- **E2E im selben Paket:** jede neue oder geänderte bedienbare Funktion liefert Python-Owner/SQLite, Protobuf-Schema/Codegen, Push bzw. versionsgebundene Abfrage, den passenden React-Reiter, Befehl mit Receipt und reale Mac-Tests zusammen; geprüft werden die betroffenen Punkte der FRONT-Prüfmatrix DF-PUSH D (1–11). Fehlt eine Stufe → OFFEN/PARTIAL, nie PASS.
- **Medien** nie im WebSocket, nur über geschützte Medien-Endpunkte (nur indizierte Dateien, Sitzung).
- **Plattformen ⇄ Kanal-Adapter im Backend**, **ComfyUI ⇄ Backend**; React kennt beide nicht.

**Bestand:** STATE 1 `COMFY_STATUS`, 2 `JOBS_ACTIVE`, 3 `COMFY_WORKFLOWS`; EVENT 20 `JOB_COMPLETED`, 21 `MEDIA_ADDED`, 22 `MEDIA_REMOVED`; Befehle 10–20; SQLite-Schema 3.

**Reservierte neue Verträge** (Nummern verbindlich reserviert; Felder werden in der Phase festgelegt, nur additiv):

| Phase | STATE | EVENT | Befehle (oneof) | HTTP (Protobuf, bei Aufruf) |
|---|---|---|---|---|
| A1 | – | 29 `COMMAND_RECEIPT` (persistierte Receipts aller Befehle) | – (bestehende Befehle mit `expected_version`; `Render` mit `parent_media_id` und Medien-ID-Eingaben) | `GET /api/v1/provenance/{media_id}` → `MediaProvenance`; `GET /api/v1/order-page` |
| A3 | 6 `COMFY_INSTANCES` (Status je Instanz; Topic 1 bleibt bis zur Umstellung des Frontends), 7 `RESOURCES` (Speicher, geladene Modelle, Zulassung) | – | `comfy_start`/`comfy_stop` erhalten Feld `instance` | – |
| B2 | 4 `ORDERS_ACTIVE` (Aufträge mit Stufen, Warten auf Betreiber) | 23 `ORDER_UPDATED` (Stufenwechsel, Kandidaten, Fehler) | 21 `create_order`, 22 `select_candidate`, 23 `reuse_media` (nur falls ein Ablauf mehr als Render mit Eltern-Medium braucht), 24 `retry_stage` | – |
| B2 | 5 `CHARACTERS` (Profile, aktive Version, Training) | 24 `IDENTITY_RESULT` (Prüfwerte je Ausgabe) | 25 `character_update`, 26 `start_training`, 27 `approve_identity_version` | `GET /api/v1/character/{id}` (Referenzen, Prüfsatz) |
| C1 | – | 25 `REFERENCE_ADDED` (Vorlage importiert/analysiert) | 28 `clone_local` (Befehl, Vorlage, Freitext) | `GET /api/v1/reference-page`, `GET /api/v1/reference/{id}` (Analyse, Pose/Tiefe/Maske) |
| C2 | 8 `CHANNELS` (Adapterzustand je Kanal, Token-Gültigkeit, Tunnel) | 26 `CUSTOMER_UPDATED`, 27 `CONVERSATION_EVENT` (Nachricht neu/geändert, Systemkarten) | 29 `mark_read`, 37 `default_contact_update` (Operator-Felder des Default-Kontakts) | `GET /api/v1/customer-page`, `GET /api/v1/conversation-page` |
| C3 | – | 28 `DELIVERY_UPDATED` (Rückversand an den Default-Nutzer; ab C5 auch Kundenzustellung) | – | – |
| C5 | 9 `INFLUENCERS` | 28 (aus C3) | 30 `send_reply`, 31 `ai_reply`, 32 `discard_draft`, 33 `set_dialog_mode`, 34 `approve_artifact`, 35 `influencer_update`, 36 `link_identity` | – |

Nach Verbindungsverlust ersetzen STATE-Snapshots veraltete Werte; EVENT-Catch-up läuft ab eigenem Cursor; bei `gap` laden Kundenliste, Verlauf, Aufträge bzw. Galerie ihre erste Seite neu. Jede neue Funktion braucht vor Abnahme einen gezielten Reconnect-Test.

## 6. Kanal-Adapter (eigene Implementierung; Muster aus Chatwoot übernommen)

**Entscheidung (Betreiber, 15.11.2026):** Chatwoot entfällt. Instagram und Telegram werden **verbindlich** über eigene Adapter im bestehenden Python-Backend angebunden; weitere Kanäle (WhatsApp, Fanvue, TikTok, Shop) folgen später über dieselbe Schnittstelle. Grund: Darkfluenzer muss Persistenz, Deduplizierung, Reihenfolge, Postausgang, Kundenakte, Kloner-Weiche, KI, Aufträge und Cockpit ohnehin selbst bauen; Chatwoot hätte nur den Transport geliefert – mit zweitem Dienststapel (Ruby/Rails/Sidekiq/PostgreSQL+pgvector/Redis), zweiter Datenbank, Abgleich zwischen zwei Systemen, Telegram nur per Webhook, stillschweigend verworfenen Dateien > 20 MB, Account-Webhooks ohne Wiederholung und fehlendem Statusfeld. **Python statt Rust:** BACK §6B schließt ein Rust-Gateway aus; die Adapter sind ein-/ausgabegebunden und nutzen SQLite, Ereignisjournal, Protobuf-Push und Medienablage direkt. Quelle der Muster: Chatwoot Community v4.19.1 (`caab07a8…`) und Betreiber-ZIP (SHA-256 `0c21d6eb…`, nur Referenz, nicht versioniert).

**Gemeinsame Adapter-Schnittstelle** (Modul `channels/`, ein Adapter je Plattform – zwei reale Adapter rechtfertigen sie): Eingang normalisieren (Plattform, Konto, Konversation/Chat, Absender-ID, Nachrichten-ID, Antwortbezug, Text, Anhänge mit Typ/Größe/Quelle, Zeit), **vor der Bestätigung atomar speichern** (Eingangsereignis + deduplizierte Nachricht + Aufgabe), Text und Medien senden mit dauerhaftem Postausgang (Status *sending* vor dem API-Aufruf; Zeitüberschreitung nach möglicher Annahme → *unbekannt*, kein blindes Wiederholen), Zustellstatus, Abgleich nach Ausfall, Gesundheitszustand und Token-Gültigkeit als STATE.

| Funktion | Aus Chatwoot übernommen (Muster) | Darüber hinaus (nicht limitiert) | Phase |
|---|---|---|---|
| **Telegram** | Medientypen photo/video/video_note/voice/audio/document/sticker/location/contact, Bearbeitungen, Antwortbezug `reply_to_message_id`, Datei per `getFile` | **Long-Polling (`getUpdates`)** – kein öffentlicher Zugang nötig; Update-Offset dauerhaft gespeichert (Wiederanlauf ohne Verlust); optional Webhook mit `secret_token`; optional **lokaler Bot-API-Server** (Download ohne Grenze, Upload bis 2000 MB) statt 20-MB-Grenze; Upload per Multipart ohne öffentliche URL | C2 |
| **Instagram** (Instagram API mit Instagram-Login) | Webhook-Prüfung (Meta-Signatur, `hub.challenge`), Ereignisse message/read/postback, Anhangtypen image/video/audio/file/share/story_mention/ig_reel/reel/ig_post/ig_story, Echo-Erkennung (`is_echo`, Deduplizierung über `mid`), Antwortbezug, Story-Antworten, Antwortfenster 24 h (7 Tage mit Human-Agent-Tag) | Medien **sofort beim Eingang sichern** (ablaufende CDN-URLs); für `reel`/`ig_post` alle verfügbaren Felder auswerten und echte Abrufbarkeit testen; OAuth-Anmeldung mit Token-Erneuerung (Langzeit-Token, ca. 60 Tage) im Schlüsselbund; ausgehende Medien über kurzlebige signierte URLs (Meta holt die Datei ab) | C2/C4 |
| Kunden/Identitäten | Kontakt je Kanal, Zusammenführung nur bestätigt | kanalunabhängige Kundenakte, `channel_identities`, Instagram→Telegram-Token-Verknüpfung mit Audit | C2/C5 |
| Empfang/Versand | Nachrichten-/Sende-APIs, private Notizen nie senden | dauerhafter Eingang vor Bestätigung, Ordnung je Kunde, Postausgang mit Revisionsprüfung | C2/C5 |
| Medien | Anhangtypen, Multipart-Versand | Herkunfts-/Typ-/Größenprüfung, Inhalts-Hash, Ablage in bestehender Medienablage; Versand nur hinter `approval.py` | C2/C5 |
| Webhook/Authentifizierung | HMAC-Prüfung gegen unveränderte Request-Bytes, Zeitfenster | nur der Instagram-Webhook ist öffentlich; Telegram braucht keinen; Geheimnisse im macOS-Schlüsselbund | C2 |
| Historie/Abgleich | seitenweises Nachladen | Telegram über gespeicherten Update-Offset; Instagram über Konversations-API beim Start und nach Lücken | C2 |
| Zustellstatus | sent/delivered/read/failed | Telegram: gesendet/fehlgeschlagen; Instagram: gelesen über read-Ereignis; Status im Journal und als EVENT | C5 |
| Übergabe an Menschen | Unterscheidung Bot/Mensch, Echo ohne Absender | Antworten direkt in der Instagram-/Telegram-App (Plattform-Echo) lösen Handoff aus; eigene Nachrichten über gespeicherte IDs erkannt | C5 |
| Erweiterbarkeit | – | WhatsApp (Cloud API, Vorlagen, 24-h-Fenster), Fanvue, TikTok, Shop später als weitere Adapter derselben Schnittstelle | später |

**Öffentliche Erreichbarkeit:** nur für Instagram nötig (Webhook, OAuth-Rückruf, Abruf ausgehender Medien) – genau diese drei Pfade werden über den Tunnel erreichbar, mit eigener Prüfung (Meta-Signatur, OAuth-`state`, kurzlebige signierte Medien-Token); alles andere bleibt lokal hinter der bestehenden Host-/Origin-/Sitzungsprüfung.

**Bild- und Videoversand über die Kanäle** (Plattformgrenzen geprüft 15.11.2026: Telegram Bot API, Meta Instagram Messaging API):

| | Telegram (öffentliche Bot-API) | Telegram (lokaler Bot-API-Server) | Instagram |
|---|---|---|---|
| Foto senden | `sendPhoto` ≤ 10 MB, Breite + Höhe ≤ 10 000, Seitenverhältnis ≤ 20 (Telegram komprimiert Fotos neu – Ausmaß im P7-Test messen); verlustfrei als Dokument ≤ 50 MB | als Dokument ≤ 2000 MB | PNG/JPEG ≤ 8 MB, Abruf durch Meta über kurzlebige signierte URL (Tunnel) |
| Video senden | `sendVideo`/Dokument ≤ 50 MB | ≤ 2000 MB | MP4/MOV/WEBM u. a. ≤ 25 MB |
| Mehrere Medien | Album 2–10 Elemente (`sendMediaGroup`) | gleich | bis 10 Bilder je Nachricht |
| Empfangen | `getFile` ≤ 20 MB | ohne Grenze | CDN-URL, sofort sichern |

**Zustellkopie:** Passt das freigegebene Original (z. B. 4K-PNG, 4K-Video) nicht in die Grenze des Zielkanals, erzeugt das Backend eine **Zustellkopie** (JPEG-Qualitätsstufe bzw. H.264/HEVC-Bitrate; Auflösung **nie unter 1K**, §9.7) als abgeleitetes Artefakt mit eigenem SHA-256 und Herkunft (Original-ID, Kanal, Parameter). Der Betreiber sieht die Zustellkopie vor dem Versand; das Original bleibt unverändert in Dateien. Telegram kann das Original verlustfrei als Dokument senden. Passt ein Video auch so nicht (z. B. langes Video über Instagram), meldet das Backend „zu groß für Instagram“ und bietet Telegram an. **Wer was senden darf:** Kundenmedien nur hinter `approval.py` (verifizierte Zahlung + Freigabe, Auftragsverlauf F7.4); das Antwortfeld sendet nur Text (FRONT F7.3) – kein freier Medienversand aus dem Eingabefeld; Ergebnisse für den Default-Nutzer gehen als Dateien an seine verifizierte Telegram-ID zurück (§8.1) – keine Kundenzustellung, keine Zahlung, Freigabe nach Freigabemodus.

**Plattformvoraussetzungen (unabhängig von der Technik):** professionelles Instagram-Konto der Influencerin, Meta-App mit Instagram-Login und Nachrichtenberechtigung, Telegram-Bot (BotFather-Token). **Instagram-Zugriffsstufe:** Mit Standard Access nur Konten mit Rolle in der Meta-App (z. B. Tester) – reicht für die Kloner-Absender (C4); Nachrichten mit fremden Kunden erst nach Meta-App-Prüfung (Advanced Access, C5).

## 7. FRONT-V1-Abgleich (Status je Bereich, Zielphase)

| Bereich (FRONT V1) | Status | Phase |
|---|---|---|
| F0–F2 Architektur, vier Reiter, Graphite, ein Stylesheet, Realtime-Vertrag | IMPLEMENTIERT | – |
| Übersicht: ComfyUI-Zustand | IMPLEMENTIERT | – |
| Übersicht: drei Karten *Kundenakten*, *GPU-Warteschlange*, *Freigaben ausstehend* + *Aktuelle Kunden* (F7.1) | TEILWEISE / NUR SPEZIFIZIERT | A2 (GPU-Warteschlange), C2 (Kundenakten), C5 (Freigaben) |
| F7 Klickreferenz und Screenshots 14.11. als Gestaltungs-/Bedienquelle | REFERENZ (kein Code) | je Reiter in der Phase der Funktion |
| ComfyUI-Layout F7.5 (links nur Workflows, rechts Steuerung, erweiterte Einstellungen zu, Trainingsdatenordner, Warteschlange + Instanzen rechts) | TEILWEISE (Formular, Queue, Workflow-Verwaltung vorhanden) | A2 (Layout, Trainingsdatenordner), B1/B2 (Training, Produktionsfunktionen) |
| DF-PUSH Domain-Versionen, versionsgebundene Queries, Receipts, CAS, begrenzte Queue | FEHLT | A1 Grundlage, danach je Phase im selben Paket |
| F3/F3a ComfyUI-Bedienung | IMPLEMENTIERT | bleibt; Erweiterung A1–A3 |
| F3b Dateien | IMPLEMENTIERT | Weiterverarbeiten + Detailansicht (F7.6): A4; Provenienz: A1 |
| F3c LoRA-Kette (Datensatz, Training, LoraLoader, Maske, Wan aus Dateien, Video) | TEILWEISE | B1 |
| KI-ComfyUI-2-Unterregister, Instanz-Status, Ressourcen | NUR SPEZIFIZIERT / FEHLT | A3 (Instanz), B5 (KI-Modelle) |
| F4 drei Spalten, Kundenliste, Register, Unterregister Gesamt/IG/TG/WA, Farben, Gesamt nur lesbar | NUR SPEZIFIZIERT | C2 (Lesen), C5 (Antworten) |
| F4 kanalgebundene Antworten, KI antworten, Entwürfe, Übergabe | NUR SPEZIFIZIERT | C5 |
| F4 Ereigniskarten, Auftragsverlauf (8 Schritte), Zahlungen, Freigabe, Zustellung | TEILWEISE (nur Backend-Tabellen/Gates) | C5 |
| F4 mehrere Influencerinnen, KI-Einstellungen | NUR SPEZIFIZIERT | C5 (Profil-Grundlage B2) |
| Interner Kontakt **Default** mit Operator-Feldern (F7.2/F7.4) | NUR SPEZIFIZIERT | C2 (Anlage, Absender-IDs), C1 (Anweisungen lokal), C3/C4 (Befehle, freie Anweisungen, Rückversand per Telegram) |
| F4 Status Kanal-Adapter/Plattformen/LLM, `VERBINDUNG ERNEUERN` | NUR SPEZIFIZIERT | C2 |
| Verbindungszustände DETACHED/UNAVAILABLE | TEILWEISE | C2 |
| Release-Einheit, altes Release startbar | NUR SPEZIFIZIERT | C6 |

## 8. Content-Cloner über Nachrichten

**Eingang:** Freigegebene Betreiber-Absenderidentitäten (je Plattform die **Absender-ID**, nicht der Anzeigename; z. B. zweiter Instagram-Account, privater Telegram-Account) senden an die Kanäle der Influencerin ein Bild/Video bzw. teilen einen Beitrag/Reel mit einem Kurzbefehl. **Die Weiche liegt vor jeder Kunden- und KI-Verarbeitung:** Nachrichten freigegebener Absender mit gültigem Befehl oder Produktionsanweisung werden interne Produktionsaufträge; sie legen keine Kundenakte an, gehen nicht in den Kunden-/Persona-LLM-Kontext und lösen keine Persona-Antwort aus – Antworten an den Default-Nutzer sind nur Rückfragen und Ergebnisse (§8.1). Alle anderen Nachrichten bleiben normaler Kundenverkehr.

**Freigabe über den internen Kontakt Default** (FRONT F7.2/F7.4): einmalig angelegt, kein Kunde (keine Zahlungspflicht, zählt nicht als Kundenakte). Rechte Spalte nur Operator-Felder: Instagram-Absender-ID, Telegram-Absender-ID, Interne Befehle verarbeiten (Ein/Aus), Influencerin, Medien-KI/Workflow, Freigabemodus, Automatische Produktionsaufträge (Ein/Aus), Einstellungen übernehmen. Die Absender-ID wird nach Ersteinrichtung über die unveränderliche Plattform-ID geprüft. *Interne Befehle verarbeiten = Aus*: Nachrichten des Absenders werden nur angezeigt; *Automatische Produktionsaufträge = Aus*: der erkannte Auftrag wartet auf Betreiberstart. Die fünf Befehle werden aus den Nachrichten erkannt, nicht als Schaltflächen angeboten; zusätzlich versteht die KI-Instanz freie Anweisungen (§8.1).

| Befehl | Funktion |
|---|---|
| `clone` | Referenz möglichst originalgetreu mit der eigenen Influencerin nachstellen; bei Video Bewegung und Kameraführung übernehmen |
| `pose` | Körperhaltung/Position bzw. Bewegungsablauf übernehmen; Kleidung, Hintergrund, Stil frei |
| `style` | Licht, Farben, Bildsprache, Kameracharakter übernehmen; Pose und Szene neu |
| `remix` | mehrere kreative fotorealistische Varianten mit der Influencerin |
| `animate` | zugesandtes Foto der Influencerin als Video animieren, optional mit Bewegungsanweisung |

Freitext nach dem Befehl (`clone gleicher Strand, roter Bikini, 9:16`) interpretiert die KI-Instanz.

**Zuordnung:** Befehl + Medium in einer Nachricht, Befehl als Antwort auf ein Medium (Antwortreferenz), geteilter Beitrag/Reel mit Befehl, Telegram-Foto/-Video mit Befehl, Verweis „die letzten N Fotos/Videos, die ich dir geschickt habe“ (= die chronologisch letzten N Medien desselben Default-Absenders in diesem Chat). Bei uneindeutiger Zuordnung fragt Darkfluenzer gezielt nach, statt zu raten. **Deduplizierung:** je Plattform-Nachrichten-ID höchstens ein Auftrag (Erkennung und Auftragserstellung in einer SQLite-Transaktion); ein erneut zugestelltes Ereignis erzeugt nichts, eine bewusst neu gesendete Nachricht einen neuen Auftrag.

**Medienimport je Kanal:** Telegram-Dateien über der öffentlichen Bot-API-Grenze (20 MB) → Hinweis an den Absender bzw. Abruf über den optionalen lokalen Bot-API-Server (bis 2000 MB). Instagram-Anhänge werden sofort gesichert (ablaufende CDN-URLs); liefert ein geteilter Beitrag/Reel keine abrufbare Datei, wird er als **nicht importierbar** gemeldet – nie ein erfolgreicher Import ohne Datei. Abrufbarkeit privater und fremder Beiträge wird real getestet.

**Ablage:** Originaldatei, SHA-256, Plattform, Absender-ID, Nachrichten-ID, Ursprungsreferenz, Eingang, Medientyp, Abmessungen/FPS/Dauer, Analyseversion, Befehl – in der bestehenden SQLite und Medienablage (keine zweite Datenbank/Ablage).

**Analyse:** Medien-ComfyUI erzeugt Pose-Keypoints (SDPose), Tiefe (Depth Anything 3/MoGe), Masken (SAM 3.1); KI-ComfyUI erzeugt Beschreibung, Prompt-Vorschlag (negativ nur bei unterstützenden Workflows), Kopf-/Blick-/Kamera-/Licht-/Kleidungs-/Umgebungsbeschreibung. Video zusätzlich Szenenschnitte, Bewegungsablauf, Kamerabewegung, Auflösung/FPS. Bild-zu-Prompt allein reicht nicht für präzise Pose; Pose-/Tiefen-/Referenzsteuerung wird eingesetzt. Wan Animate 2 nutzt das Bewegungsvideo direkt (ohne Posen-Extraktion). Keine eigene Motion-Transfer-Engine.

**Generierung:** Verfahren A (referenzgesteuerte Neugenerierung) und B (kontrollierte Bearbeitung eines eigenen Masterbilds) werden verglichen; je Auftrag drei Kandidaten, Prüfung (Identität, Anatomie, Referenztreue, Fotorealismus), Betreiberauswahl, 4K-Fertigstellung, Dateien. In **Nachrichten** erscheinen interne Aufträge in der Mitte des Default-Verlaufs als `INTERNER AUFTRAG · <BEFEHL> · <KANAL>` mit Originalnachricht, Referenz, Befehl, Influencerin, Stufe, Ergebnisvorschau, Fehlern/Freigaben; Ergebnisse zusätzlich in Dateien und je Freigabemodus per Telegram an den Default-Nutzer (§8.1); kein zusätzlicher Beschreibungsblock rechts (F7.4).

### 8.1 Default-Nutzer als Produktionsassistent vom Handy (Betreiberentscheidung 15.11.2026)

Der Betreiber nutzt den Default-Kontakt wie einen Produktionsassistenten: Er schickt der Influencerin (Telegram-Bot bzw. Instagram-Konto) Referenzen und schreibt in normaler Sprache, z. B. *„Schau dir die letzten 3 Fotos an, die ich dir geschickt habe, und erstelle identische oder ähnliche Fotos für einen neuen Instagram-Beitrag.“*

1. **Verstehen (KI-ComfyUI 2):** Die Anweisung wird auf die fünf Befehle abgebildet (identisch → `clone`, ähnlich → `remix`/`style`, Haltung → `pose`, Bewegung → `animate`) plus Ziel (Instagram-Beitrag 3:4/4:5, Karussell, Story/Reel 9:16), Anzahl, Referenzen und Wünsche. Referenzen: angehängte Medien, Antwortbezug oder „die letzten N“ (§8 Zuordnung). Ist etwas unklar (welche Bilder, Anzahl, Ziel), stellt Darkfluenzer genau eine Rückfrage im Chat, statt zu raten. Die Deutung (Befehl, Referenzen, Ziel) wird im Auftrag gespeichert und im Default-Verlauf angezeigt.
2. **Produzieren:** derselbe Auftragspfad wie §8 (Analyse → Charakterbindung → Kandidaten → Prüfung) mit der Influencerin aus dem Default-Feld; Ausgabe im Instagram-Ausgabeprofil des Ziels in mindestens 1K (§9.7); bei mehreren Referenzen für einen Beitrag eine zusammenpassende Serie (gleiche Figur, Licht, Stil).
3. **Zurücksenden:** Die Ergebnisse gehen in denselben Telegram-Chat an die verifizierte Default-ID, als **Dateien** (verlustfrei und postfertig, damit am Handy die volle Auflösung ankommt); der Betreiber postet selbst vom Handy auf Instagram – Darkfluenzer veröffentlicht nicht. Kam die Anfrage über Instagram, geht die Antwort an die Telegram-ID des Default-Kontakts, ohne hinterlegte Telegram-ID über Instagram innerhalb der dortigen Grenzen (§6). Postausgang mit Idempotenz: nach Neustart kein doppelter Versand.
4. **Freigabemodus des Default-Kontakts:** *Direkt zurücksenden* (Kandidaten gehen nach der automatischen Prüfung zurück, ausgewählt wird am Handy) · *Nach Auswahl im Cockpit* · *Nur Cockpit* (kein Rückversand). Das ist keine Kundenzustellung: keine Zahlung, Ziel ausschließlich die verifizierte Default-Identität, nie ein Kunde.
5. **Folgeanweisungen per Antwort** auf ein zurückgesandtes Ergebnis, z. B. „Nr. 2 in 4K“ (Upscaler, kein Neugenerieren, §9.7), „Nr. 1 als Reel“ (`animate` + 9:16), „Nr. 3 nochmal, Haare offen“ (Variante) – jeweils als abgeleiteter Auftrag mit Eltern-Artefakt.
6. **Im Cockpit sichtbar:** Anfrage, Deutung, Rückfrage, Stufen und Rückversand im Default-Verlauf (Nachrichten, Mitte); alle Ergebnisse in Dateien mit vollständiger Provenienz.

Phasen: lokal im Cockpit C1, Telegram C3, Instagram-Eingang C4.

**Recht:** Vorlagen dienen als Referenz; keine 1:1-Kopien geschützter Fotos; Rechteverantwortung beim Betreiber; Regel 4 (Face-Swap) gilt.

## 9. Produktionskette und Identität

### 9.1 Kette

Charakterfotos → Datensatz → Identitätsprofil → Masterbild (normal) → Varianten/Posen → Bearbeitung inkl. Ausziehen (maskiert) → Original in mindestens 1K → freigegebenes Foto → Video (freie Animation oder Bewegungsübertragung) → Video-Original in mindestens 1K → Dateien → Freigabe; 2K/4K jederzeit nachträglich per Upscaler (§9.7).

### 9.2 Identitätsprofil

Versioniert: Referenzbilder (Gesicht/Halb-/Ganzkörper), Adapter (Modellfamilie, Version, Stärke), geprüfte Referenz-/Adaptereinstellungen, **getrennter Prüfsatz** und feste Testszenen, Bewertung. Charakterfotos: **mindestens 15 Bilder ≥ 768 px** (Code-Gate `DATASET_INCOMPLETE`), **empfohlen 25–40 ≥ 1024 px** mit mehreren Winkeln, Licht und Outfits inkl. Körperreferenzen; Beschriftung passend zur Trainingsmethode. Prüfung: Gesicht (YuNet → AuraFace + SFace, Schwelle aus Betreiber-Bewertungen, „nicht prüfbar“ bei verdeckten Gesichtern), Körper/Gesamtwirkung getrennt (Sichtprüfung), Video über Stichproben + zeitliche Prüfung + vollständige Sichtung vor Freigabe. Methoden: Charakter-LoRA, LoKr (experimentell), Referenz-Conditioning (Krea 2 Identity Edit v1.x, ReID, FLUX 3 Klein Multi-Referenz), Kombinationen. **Bildmodell und Identitätsmethode werden gemeinsam gewählt.**

### 9.3 Modelle

| Rolle | Vorhanden (weiterverwenden) | Kandidaten (A/B, schrittweise installiert) |
|---|---|---|
| Foto | LUSTIFY v2.0 SDXL (getestet) | Krea 2 Turbo BF16 (Inferenz; Raw BF16 = Trainingsbasis laut Modellkarte), LUSTIFY v10 BF16, FLUX 3 Image Klein Base BF16, Qwen-Image-2512 BF16, Qwen-Image 2.1 BF16, FLUX.2 Dev BF16 (nach Platzentscheidung) |
| Video | Wan 2.2 I2V A14B FP16, Wan 2.2 Remix v3.0 (FP8, Lightning: 4+4 Schritte, CFG 1, euler/simple, Shift 8) | LTX 2.5 Dev BF16, Wan Animate 2 BF16 (Bewegungsübertragung), VACE/Fun Control (Vergleich) |
| Analyse/Steuerung | SAM 3.1 FP16 (Bearbeiten mit SAM 3.1) | SDPose, Depth Anything 3, Krea-2-Depth/Pose-Adapter (nur mit Nachweis) |
| Hochskalierung (§9.7) | – | Bild: SeedVR2 7B/3B (ComfyUI-Kern); Video: SeedVR2 Video, RelayVSR; FILM (Bildrate); native 4K (FLUX 3 Klein, LTX) im Vergleich |
| Training | `training.py` (SDXL, diffusers) | ComfyUI-Trainingsworkflow (Medien-Instanz), mflux für Krea 2 |
| Identitätsmetrik | AuraFace-v1 (`glintr100.onnx`), OpenCV SFace/YuNet (`identity.py`) | – |

**Nicht eingeplant:** MiniMax H3/H3-Image, HunyuanVideo 1.5, NVIDIA Cosmos 3; am 15.11.2026 entfernt: Qwen-Image 20B (ersetzt durch Qwen-Image-2512), RealCore Illustrious. Kandidaten lädt Darkfluenzer nacheinander nach §14.1 / `ki_modelle.md` (Reihenfolge, Platzbilanz); Manifest-Eintrag mit Präzision aus dem Dateikopf, SHA-256 und Quelle sowie `models verify` in Block B. **LTX Desktop** lokal erst ab macOS 26; der ComfyUI-Pfad wird separat getestet.

### 9.4 Workflows

Offizielle ComfyUI-Vorlagen (Paket `comfyui_workflow_templates_json` 0.1.133) und gekennzeichnete Community-Erweiterungen werden über die **Workflow-Übernahme** eingebunden: Untergraphen aufgelöst, Primitive-Nodes und umgangene/stumme Nodes korrekt behandelt, dynamische Eingänge/Schalter/Schleifen abgebildet, Abgleich gegen `graphToPrompt` des echten Frontends mit 0 Abweichungen; UI-Graph, API-Graph und Parameterbindungen derselben Version; jede Workflow-Version mit unveränderlichem Graph-Snapshot. Das Manifest erhält je Workflow `instance` (media/ai), Typ und vollständige Parameterbeschreibung (Typ, Standard, Grenzen, Schritt, Auswahl, Abhängigkeiten, Graph-Eingang, Grund/Experte); das Backend validiert erneut. Die bestehende Workflow-Verwaltung (aktivieren, exakt öffnen, bearbeiten, übernehmen, löschen) bleibt. Die Workflowverwaltung zeigt getrennt: Dateien vorhanden · Laden · Rendern · Qualität · Nutzung freigegeben.

### 9.5 Reproduzierbarkeit und Dateien-Aktionen

Je Bild/Video dauerhaft gespeichert (soweit verwendet): positiver/negativer Prompt, KI-Ausgangsprompt und Betreiberänderungen, Seed, Sampler, Scheduler, Schritte, CFG, Denoise, Abmessungen, Modellname/-version/SHA-256, VAE und Encoder, Workflow-Version mit Graph-Snapshot, Charakterprofil-Version, LoRA-/Adapter-Version und -Stärken, Referenzen mit Hash, Pose-/Tiefen-/Maskendaten, Zwischenprodukte und Bearbeitungsschritte, Upscaling, FPS/Frames/Bewegungsvorgaben, Nachrichtenkanal und Auftrag. Native Auflösung und Hochskalierung werden getrennt ausgewiesen. In **Dateien**: **Wiederholen · Variieren · Als Vorlage verwenden · Video erstellen · Weiterbearbeiten**; Originale und Historie bleiben, neue Ausgaben sind neue Versionen. Reproduzierbarkeit = vollständige Nachvollziehbarkeit und bestmögliche Wiederholbarkeit; bitgenaue Gleichheit über Software-/Hardwareversionen wird nicht vorausgesetzt.

### 9.6 Bedienung im ComfyUI-Reiter (Layout FRONT F7.5)

Die bestehende Direktbedienung bleibt (freier Prompt, Workflow-Wahl, Parameter, Bearbeiten, Video, Workflow-Verwaltung, Warteschlange). **Layout nach F7.5, keine zusätzlichen Arbeitsbereiche oder Schaltflächen:** links ausschließlich Workflows der Instanz (Fotos/Videos, später KI); Mitte Prompt-/Quellbild-/Masken-/Trainings-Arbeitsfläche und echte Ergebnisse; rechts Steuerung – Charakter, Workflow-Anzeige, erweiterte Einstellungen (initial geschlossen, nur tatsächlich exponierte Eingänge), Trainingsdatenordner, **Generieren**, darunter Warteschlange und Instanzen. Produktionsfunktionen sind Felder dieses Layouts: Mitte – Kandidatenvergleich (je Kandidat ein echtes Renderergebnis, synchroner Zoom), Masken-/Pose-/Tiefenvorschau, Video-Zeitleiste; rechts – Charakter mit Profilversion, Vorlage (Artefakt-ID aus Dateien „Als Vorlage“ oder Kloner-Eingang), Format, Ausgabegröße, Kandidatenzahl (Standard 3). Charakterpflege über Charakter + Trainingsdatenordner. Abläufe: Neues Foto, Foto nach Vorlage, Foto bearbeiten (inkl. Ausziehen), Video (freie Animation oder Bewegungsübertragung). An der kreativen Stufe wählt immer der Betreiber.

### 9.7 Auflösung, Hochskalierung und Instagram-Ausgabe (Betreiberentscheidung 15.11.2026)

- **Original mindestens 1K:** Jedes freigegebene Foto und Video liegt mindestens in 1K vor (kurze Seite ≥ 1080 px im Zielseitenverhältnis) – genug für Instagram ohne Neugenerierung und Grundlage für spätere Hochskalierung. Erzeugt wird direkt im Zielformat (kein nachträglicher Beschnitt der Figur). Liefert ein Modell nativ weniger (SDXL-Buckets z. B. 896 × 1152, Wan 2.2 480p/720p), erreicht eine ausgewiesene Verfeinerungs- bzw. Hochskalierungsstufe 1K; native und ausgegebene Auflösung werden getrennt gespeichert (§9.5).
- **Mehr als 1K nur per Upscaler:** 2K/4K für Bild und Video entstehen auf Wunsch aus dem freigegebenen Original – als neue abgeleitete Version mit eigenem SHA-256 und Eltern-Verweis, nie durch Neugenerieren. Bild: SeedVR2 7B/3B (A/B); Video: SeedVR2 Video vs. RelayVSR, FILM für höhere Bildrate. Auslöser: Dateien „Weiterverarbeiten → Hochskalieren“, Kundenauftrag mit HD-Wunsch, Default-Folgeanweisung („Nr. 2 in 4K“). Wer kein HD will, bekommt das 1K-Original.
- **Instagram-Ausgabeprofile** (Stand 2026 laut Creator-Leitfäden, keine Meta-Dokumentation – mit dem ersten echten Post prüfen): Beitrag 3:4 = 1080 × 1440 (höchstes Format in der App, Profilraster ohne Beschnitt), 4:5 = 1080 × 1350 (Grenze der Veröffentlichungs-API), 1:1 = 1080 × 1080; Story/Reel 9:16 = 1080 × 1920. Fotos sRGB-JPEG hoher Qualität; Reels H.264/AAC-MP4, 30 fps. Instagram zeigt höchstens 1080 px Breite und rechnet 4K-Videos auf 1080p herunter – für Instagram genügt das 1K-Original, Hochaufgelöstes dient Kunden-HD und Archiv.
- Das Ausgabeprofil ist eine Einstellung im Format-Feld der rechten ComfyUI-Steuerung (F7.5) und Teil jedes Default- und Kundenauftrags.

## 10. Geklärte Punkte

1. **HTTPS/Erreichbarkeit:** **Telegram läuft über Long-Polling ohne öffentliche Adresse.** Nur Instagram braucht eine öffentliche HTTPS-Adresse (Webhook, OAuth-Rückruf, Abruf ausgehender Medien). Umsetzung in C2: kostenloser Tunnel mit **fester** Adresse ohne eigene Domain – bevorzugt **Tailscale Funnel** (`*.ts.net`, Pfad-Weiterleitung; laut Quellen Beta), Alternative **ngrok** mit kostenloser fester Domain; Cloudflare Quick Tunnels (wechselnde Adresse) ungeeignet. Öffentlich werden nur die drei Instagram-Pfade mit eigener Prüfung; alles andere bleibt lokal. Die Wahl zwischen Funnel und ngrok fällt im P7-Test.
2. **Nachrichten-Cockpit:** F4 ist bis auf Store-Tabellen und Gates **nur spezifiziert**; C2–C5 bauen es vollständig (Adapter, Migration, Cockpit). Der Telegram-Eingang (C3) setzt C2 voraus.
3. **Telegram-Medien:** Öffentliche Bot-API: Download max. 20 MB (`getFile`), Upload 50 MB. Mit eigenem Adapter ist ein **lokaler Telegram-Bot-API-Server** (offizieller Quellcode, braucht kostenlose `api_id`/`api_hash`) ohne Patch möglich: Download ohne Grenze, Upload bis 2000 MB – Entscheidung im P8-Test; bis dahin Hinweis an den Absender bei zu großen Dateien und direkter Import als Alternative.
4. **Workflow-Import:** Untergraphen-, Primitive- und Bypass-/Mute-Unterstützung in `comfy.ui_to_api` (A2) mit Abgleich gegen `graphToPrompt` für jede verwendete Vorlage.
5. **Face-Swap:** Regel 4.
6. **Zwei ComfyUI-Instanzen:** §4.2; Umsetzung A3.
7. **Übernahme aus V0.1:** §11.

## 11. Übergangsmatrix V0.1 → V0.2 / V0.3 / V0.4

| V0.1-Inhalt | Einordnung | Begründung |
|---|---|---|
| Ziel, Qualitätsregeln, Identitätsbindung, ehrliche Erwartung | BLEIBT | unverändert gültig |
| Regel „eine gemeinsame GPU-Warteschlange“ | GEÄNDERT | zwei Instanzen, zwei Queues, gemeinsame Zulassung (§4.2) |
| Präzision je Komponente, Lizenzregeln | BLEIBT | Regeln 6/7 |
| Desktop-App (Electron) mit Instagram-Ansicht, Ersatz des Swift-Starters | GESTRICHEN | Betreiberentscheidung; Swift-Starter und Browser-Cockpit bleiben |
| Separates Instagram-Sammelkonto, Sammlungs-Abgleich, instagrapi, Crawler, Account-Import | GESTRICHEN | ersetzt durch Kloner über Nachrichten (§8); nur offizielle Plattform-APIs über eigene Adapter |
| Sammlung als Produktionsbefehl, „höchstens ein Auftrag je Sammlungsaktion“ | ERSETZT | fünf Kurzbefehle; höchstens ein Auftrag je Plattform-Nachrichten-ID |
| Zugangsdaten im macOS-Schlüsselbund | BLEIBT | für Telegram-Bot-Token, Instagram-OAuth-Token, Meta-App-Secret |
| Vorlagen-Analyse (VLM, SDPose, Tiefe, SAM) | GEÄNDERT | VLM in KI-ComfyUI, Pose/Tiefe/Maske in Medien-ComfyUI |
| Bedienkonzept drei Spalten, Abläufe A–D, Betreiber wählt aus | GEÄNDERT | Layout nach FRONT F7.5 (links nur Workflows, rechts Steuerung); keine eigenen Schaltflächen „Charakter verwalten“/„Vorlagen“; Abläufe A–D und Betreiberauswahl bleiben (§9.6) |
| Vergleichsaktionen, Dateien-Metadaten | GEÄNDERT | erweitert um §9.5 |
| Auftrag mit Stufen, Wiederanlauf, `/free`, Parameterbeschreibung, Workflow-Übernahme, Workflowverwaltung | BLEIBT | §4.3, §9.4 |
| Identitätsprofil, Prüfung, Methoden, gemeinsame Modell-/Identitätswahl | BLEIBT | §9.2; Mindestumfang 15 Bilder ergänzt |
| Modellkandidaten, nicht eingeplante Modelle | BLEIBT | §9.3; B1 nur mit vorhandenen Modellen |
| Workspaces, Langvideo, Vergleichsmethode | BLEIBT | §9.4, B4 |
| Pakete I0 (Instagram-Machbarkeit), D1, I1, I2 | ERSETZT / GESTRICHEN | ersetzt durch C2–C4; D1 gestrichen |
| Chatwoot als Kanalinfrastruktur (BACK/FRONT, Betreiber-ZIP) | ERSETZT | eigene Python-Adapter für Instagram und Telegram, Chatwoot nur Musterquelle (§6) |
| Paket P0a macOS 26 | BLEIBT | als B3, vor den Videovergleichen |
| (V0.4) Phasen P0–P12 | UMBENANNT | Blöcke A1–A4, B1–B5, C1–C7 mit Zuordnungstabelle (§12) |
| (V0.3) Kloner-Ergebnisse nur im Cockpit | GEÄNDERT | Default-Nutzer: freie Anweisungen, Rückversand per Telegram, Folgeanweisungen (§8.1) |
| (V0.3) Fertigstellung 4K, Zustellkopie „bei Bedarf geringere Auflösung“ | GEÄNDERT | Original ≥ 1K, 2K/4K nur per Upscaler auf Wunsch, Instagram-Ausgabeprofile, Zustellkopie nie unter 1K (§9.7, §6) |

## 12. Phasen (verbindliche Reihenfolge, Betreiberentscheidung 15.11.2026)

> **Verbindliche Änderung der Arbeitsreihenfolge (Betreiberentscheidung 15.11.2026, abends):** Die Entwicklung wartet nicht auf Modelldownloads. **Block B** lädt im Hintergrund weiter; jeder Modelltest läuft, sobald seine Dateien da sind. **Block C und das gesamte Frontend** (alle Ansichten, Bedienelemente und Funktionen nach F7 und FRONT, ohne Platzhalter oder funktionslose Schaltflächen, Backend vollständig angebunden, Protobuf-Push) werden **jetzt** parallel umgesetzt; sobald das Frontend fertig und getestet ist, wird **sofort deployt**. Alles, was ohne fehlende Modelle oder externe Freigaben real testbar ist, wird sofort abgenommen; verbleibende Integrationstests folgen gezielt. Regeln §2.1 und alle Funktions-/Qualitätsanforderungen bleiben unverändert. **Paketfolge Block C:** C2a Datenmodell (kanalunabhängige Kunden, Identitäten, Konversationen, Ein-/Ausgang), Default-Kontakt, Nachrichten-Cockpit, Kanalstatus → C2b Telegram-Adapter (echte Tests mit Bot-Token) → C3 Default-Nutzer über Telegram (Befehle, freie Anweisungen, Auftrag, Rückversand) → C1 lokaler Kloner im Cockpit → C2c/C4 Instagram-Adapter (Meta-App, Tunnel) → C5 Kundenbetrieb (manuelle und KI-Antworten, Influencerinnen, Aufträge, Freigabe, Zustellung) → Deploy (Release-Einheit) → C6.

**Drei Blöcke; Block C läuft seit dem 15.11.2026 abends parallel zu den Downloads von Block B (siehe Kasten).** Ein Block ist erst abgeschlossen, wenn Frontend, Backend und die reale Abnahme auf dem Mac bestanden sind; erst dann beginnt der nächste. Bestehende Funktions-, Qualitäts- und Auflösungsanforderungen bleiben unverändert.

1. **Block A – ComfyUI und Dateien vollständig:** Frontend und Backend nach dem freigegebenen F7-Design mit allen Funktionen, Protobuf-Push, Warteschlangen, Speicherung und Wiederanlauf; beide Reiter vollständig bedienbar und getestet.
2. **Block B – sämtliche KI-Modelle und Produktionsworkflows:** Charakter-LoRA, Bildgenerierung, Identität, Pose, Inpainting, Video, Upscaling und vollständige Workflow-Verkettung; alle ausgewählten Modelle und Workflows real auf dem Mac und aus dem Cockpit bedienbar.
3. **Block C – Telegram und Instagram:** Nachrichten-Cockpit, eigene Python-Adapter, Default-Nutzer, Content-Cloner, Rückversand der Ergebnisse, danach Kundenbetrieb.

Jede Phase: echte Umsetzung, gezielte Tests (Normalfall, wesentlicher Fehlerfall, Neustart/Reconnect, ein echter Integrationsnachweis), echter Lauf auf dem Mac, Commit und Push auf `main`. **Fertig erst, wenn der Betreiber es aus Darkfluenzer bedienen kann, das echte Ergebnis dort sieht und es nach Neustart korrekt zugeordnet ist.** Jede Phase mit neuen oder geänderten bedienbaren Funktionen liefert den DF-PUSH-Hin- und Rückweg im selben Paket und weist die betroffenen Punkte der FRONT-Prüfmatrix DF-PUSH D auf dem Mac nach (§5). Vor Downloads: Speicherbilanz (Dateigrößen + Zwischenspeicher + Training + Video-Zwischenprodukte; 322 GiB frei nach der Bereinigung am 15.11.2026, Reserve 30 GB).

| Neu | Früher (V0.2/0.3) | Inhalt |
|---|---|---|
| A1 | P1 (Teil) | Vertrag, Speicherung, Wiederanlauf |
| A2 | P1/P2 (Layout), P0 (Entladen) | ComfyUI-Reiter nach F7.5 |
| A3 | P5 (Instanz) | Zweite ComfyUI-Instanz, Ressourcensteuerung |
| A4 | P1 (Dateien) | Dateien nach F7.6 |
| B1 | P0 | Kernkette mit vorhandenen Modellen |
| B2 | P2 | Identität, Bildqualität, Pose, Hochskalierung |
| B3 | P3 | macOS 26 |
| B4 | P4 | Video |
| B5 | P5 (KI-Workflows) | KI-Modelle der KI-Instanz |
| C1 | P6 | Lokaler Referenz-Kloner |
| C2 | P7 | Kanal-Basis |
| C3 | P8 | Telegram: Default-Nutzer |
| C4 | P9 | Instagram: Default-Nutzer |
| C5 | P10 | Kundenbetrieb F4 |
| C6 | P11 | Gesamtabnahme |
| C7 | P12 | Weitere Kanäle (später) |

### Block A – ComfyUI und Dateien vollständig

**A1 – Vertrag, Speicherung, Wiederanlauf** · Status: **BESTANDEN 15.11.2026** (Commit `d13e258`)
- Ziel: DF-PUSH-Grundlage für ComfyUI und Dateien – persistente Befehls-Idempotenz (SQLite), typisierte persistierte Receipts (EVENT 29), CAS für mutierende Befehle (Workflow aktivieren/übernehmen/anlegen/löschen, Datei löschen, Auftrag abbrechen), Domain-Versionen + Backend-Epoche in den STATE-Projektionen (ComfyUI, Workflows, Jobs, Medien), begrenzte STATE-Queue mit Latest-wins und EVENT-Überlauf → Lücke/Neusynchronisierung (`stream.py`); Reproduzierbarkeit (§9.5: Graph-Snapshot, Workflow-Version, Eltern-Artefakt, alle Parameter; Migration 4); Wiederanlauf-Abgleich mit ComfyUI über `prompt_id` (Queue + Verlauf; fertige Ausgaben übernehmen statt neu rendern).
- Vorhanden: Protobuf-WS mit STATE/EVENT/Catch-up, Befehle 10–20 mit `request_id` (nur im Speicher), FIFO `render_worker` mit Fortsetzung nach Neustart, `jobs`/`media`/`events`, `comfy.provenance`.
- Abnahme: DF-PUSH D 1–7 und 11 für ComfyUI/Dateien; Doppelklick → ein Effekt; `UNKNOWN` ohne blinden Neuversuch; langsamer Client; Backend-Neustart während eines Renders ohne Doppelrender.
- **Nachweis (15.11.2026, Mac):** Schalter aus/ein erst nach Receipt, Registry-Version 2 → 3; Render „Verfeinern“ aus Medium 31 per ID – Eingabe-SHA identisch, Graph-Snapshot, `prompt_id`, Eltern-Medium gespeichert; veraltete Version live abgewiesen; dieselbe `request_id` → identische Antwort, ein Journaleintrag, anderer Befehl abgewiesen; Server per SIGKILL mitten im Render beendet → Job 26 nach dem Neustart abgeholt, genau ein ComfyUI-Auftrag, Receipt COMPLETED, Medium 0033. Tests: Backend 65, Frontend 4 grün (Überlauf/Latest-wins, UNKNOWN nach Neustart, Requeue nur ungesendeter Jobs). Der zur Verdichtung (D 3/4) nötige versionsgebundene Detailabruf entsteht mit A4.
- **Geändert:** „Auftrag mit Stufen“ (STATE 4, EVENT 23, Befehle 21/22/24) kommt erst mit den mehrstufigen Abläufen in B2 – in Block A ist jeder Render ein Job; Wiederholen/Variieren/Weiterverarbeiten nutzen `Render` mit Eltern-Medium (keine doppelte Befehlsstruktur).

**A2 – ComfyUI-Reiter nach F7.5** · Status: **BESTANDEN 15.11.2026** (Commits `515288f`, `9d9ddf0`)
- Ziel: Layout F7.5 – links ausschließlich Workflows; Mitte Prompt, Negativ-Prompt nur wenn deklariert, Ausgangsbild/„Aus Dateien“ mit exakter Artefakt-ID, Maske nur bei maskenfähigem Workflow, Ergebnis der echten Ausführung; rechts Charakter (ehrlich „kein Charakterprofil“ bis B2), Workflow-Anzeige, erweiterte Workflow-Einstellungen initial geschlossen mit allen tatsächlich exponierten Eingängen, Trainingsdatenordner (Scan, Prüfung, Dubletten, Hash, versionierter Datensatz – das Training selbst in B1), Generieren, darunter Warteschlange und Instanzen. Dazu Workflow-Übernahme mit Untergraphen, Primitive- und umgangenen/stummen Nodes (§9.4, Abgleich `graphToPrompt`), Entladen beim Engine-Wechsel (`/free`) mit Speicherverlauf, Übersicht-Karte GPU-Warteschlange.
- Abnahme: Mac-Screenshots gegen die F7-Referenz; jede Bedienaktion mit Receipt und Push; ein Workflow mit Untergraph im echten ComfyUI bearbeitet und übernommen (0 Abweichungen); Engine-Wechsel LUSTIFY → Wan mit gemessenem Speicherverlauf.
- **Nachweis (15.11.2026, Mac):** Layout F7.5 live (Screenshots, Smoke-Test); 16 offizielle Vorlagen (≈ 400 Nodes, Untergraphen, Primitive, Schalter, Schleifen) im echten Frontend geladen – `graphToPrompt` und Konverter **0 Abweichungen**; VAE-Decoder im echten Editor in einen Untergraphen umgewandelt, gespeichert, im Cockpit übernommen (`8:6`, 0 Abweichungen) und gerendert (0034); Engine-Wechsel LUSTIFY → Wan: „Modelle entladen“ protokolliert, Wan-FP16-Lauf 2408 s mit Speicherverlauf frei 73,1 → min 18,3 → 56,0 GB, **Swap 8,9 → max 46,1 → 26,7 GB** (Befund für B1/B4).
- **Geändert:** Trainingsdatenordner und Charaktertraining erscheinen wie im F7-Prototyp nur bei einem Trainingsworkflow – mit dem ersten registrierten Trainingsworkflow in B1 (kein Feld ohne Funktion).

**A3 – Zweite ComfyUI-Instanz und Ressourcensteuerung** · Status: **BESTANDEN 15.11.2026** (Commit `3fd3edc`)
- Ziel: KI-ComfyUI 2 (:8189, eigene Verzeichnisse, Zustand/Lock/Log je Instanz, gleiche ComfyUI-Version, gemeinsame Modellablage); Start/Stopp/Status je Instanz in Runtime, Starter und `down`; Manifest-Feld `instance`; eigene KI-Warteschlange; Zulassung nach gemessenem Speicher (§4.2); Unterregister KI mit eigener Workflowliste; STATE 6/7; Feld `instance` in `comfy_start`/`comfy_stop`.
- Abnahme: beide Instanzen starten/stoppen unabhängig; getrennte Queue-/Health-Zustände (DF-PUSH D 10); Zulassung mit je einem echten Workflow geprüft (KI-Modelle selbst erst B5).
- **Nachweis (15.11.2026, Mac):** `[comfyui_ai]` (:8189, `local/comfyui_ai`) eingerichtet; KI-Instanz im Cockpit gestartet (BEREIT, eigene Ordner angelegt) und gestoppt, Medien-Instanz blieb BEREIT; Unterregister KI ehrlich leer; Speicherzeile (frei/Swap/Reserve); Zulassung live: mit unerreichbarer Reserve wartete Auftrag 31 sichtbar („wartet auf Speicher, 5 GB“ = gemessener LUSTIFY-Bedarf), Entfernen beendete das Warten. **Offen bis B5:** echter Lauf eines KI-Workflows auf Instanz 2 und das Entladen der ruhenden anderen Instanz durch die Zulassung – erst mit KI-Modellen prüfbar.

**A4 – Dateien nach F7.6** · Status: **BESTANDEN 15.11.2026** (Commit `3fd3edc`)
- Ziel: Bestand bleibt (Markieren, Löschen mit Bestätigung, Filter, Öffnen, Download, Kundensperre); **Weiterverarbeiten** je Medium übergibt die exakte Artefakt-ID + SHA-256 an den gewählten Workflow; Detailansicht mit allen Produktionsparametern und Versionen aus dem Graph-Snapshot (versionsgebundene Abfrage `GET /api/v1/provenance/{media_id}`); **Wiederholen** (gleiche Einstellungen) · **Variieren** (neuer Seed) · **Video erstellen**; **Als Vorlage** und **Hochskalieren** erscheinen, sobald die zugehörigen Workflows registriert sind (Hochskalieren B2, Vorlage C1); Eltern-/Kind-Verknüpfung sichtbar.
- Abnahme: Neuanlage/Löschung in zwei Fenstern per Push (DF-PUSH D 9); Wiederholen erzeugt eine neue Version mit identischen Einstellungen; Weiterverarbeiten nutzt nachweislich das gewählte Artefakt (SHA am ComfyUI-Eingang).
- **Nachweis (15.11.2026, Mac):** Detailansicht 0033 mit Auftrag, Workflow, Engine, Dauer, Parametern, Modell (Repo@Revision, SHA-256), Graph-Snapshot und Speicherverlauf; **Wiederholen** von Auftrag 26 → Job 29 mit identischen Parametern und **bitgleichem Ergebnis** (SHA-256 = 0033, Galerie führt den Inhalt einmal); **Weiterverarbeiten** → Verfeinern mit 0033 per Medien-ID, Eingabe-SHA = 0033, Ergebnis 0036 mit Eltern-Verweis; Video erstellen und Variieren angeboten, nur wenn der erzeugende Workflow registriert ist. Gelöscht/neu per Push war bereits F3b-Bestand (D 9).

**Abnahme Block A:** A1–A4 real am Mac mit den vorhandenen Modellen (LUSTIFY v2, Wan FP16); Neustart/Reconnect; Playwright gegen das laufende Cockpit. **Block A braucht keine neuen Modelle.** – **BESTANDEN 15.11.2026** (Tests: Backend 67, Frontend 4, Smoke gegen das laufende Cockpit); offen nur die zwei an KI-Modelle gebundenen Prüfungen von A3 (→ B5).

### Block B – KI-Modelle und Produktionsworkflows

**B1 – Kernkette mit vorhandenen Modellen** (= BACK §0 CHAIN-00…06) · Status: OFFEN
- Ziel: Charakterfotos → versionierte SDXL-Charakter-LoRA → LUSTIFY-Graph mit LoraLoader → ≥ 3 Posen/Perspektiven (A/B mit/ohne LoRA) → Maskenbearbeitung + Verfeinerung → finales Standbild in mindestens 1K (Skalieren + LUSTIFY-Verfeinerung, vorhandene Modelle) in Dateien → genau dieses Bild als Wan-2.2-FP16-Startbild → echtes Video in Dateien (Wan nativ 480p/720p; 1K-Video mit dem Video-Upscaler in B4), mit Eltern-/Kind-Verknüpfung im Job-Journal.
- Vorhanden (nach Block A): `training.scan/build_dataset`, `train_sdxl_lora`, Inpaint mit Pixelprüfung, „Aus Dateien“, Wan-Workflow, FIFO, Galerie, Trainingsdatenordner, Receipts, Graph-Snapshot, Entladen.
- Fehlt: LoRA-Registry (SHA, Basis + SHA, Datensatz, Trigger, Stärke, Status) im Manifest; LoraLoader-Workflow-Version; Trainingsdatenordner/Charaktertraining im F7.5-Layout mit dem ersten Trainingsworkflow; Wan-FP16-Speicher (Messung A2: Swap bis 46 GB, 40 min für 49 Frames) untersuchen; Trainingsweg (ComfyUI-Trainingsworkflow in der Medien-Instanz zuerst testen, sonst vorhandener diffusers-Trainer als dokumentierte Ausnahme); MPS-Attention (#14837) mit Testfall untersuchen; Remix-Workflow auf Autor-Vorlage korrigieren (Vergleich erst B4).
- Abhängigkeit: Block A; **Charakterfotos des Betreibers** in `local/character/photos/`. Abnahme: vollständige Kette real aus dem Cockpit; jede Datei mit Hash und Eltern-Artefakt; Video abspielbar.
- **Teilnachweise 15.11.2026:**
  - **Trainingsweg:** ComfyUI-nativ (`LoadImageTextDataSetFromFolder` → `MakeTrainingDataset` → `TrainLoraNode` → `SaveLoRA`) läuft auf MPS mit SDXL: Probelauf 4 Schritte bei 1024 px, BF16, Rang 8, 4,3 s/Schritt, Verlust 0,51 → 0,42, LoRA mit 3268 BF16-Tensoren. Der diffusers-Trainer ist damit keine nötige Ausnahme.
  - **Charaktertraining im F7.5-Layout:** Workflow `lustify_sdxl_lora_train` (Trainingsdatenordner geprüft per STATE 5 `CHARACTERS`, Push bei Änderung; „Training starten“ gesperrt mit Grund unter 15 geeigneten Bildern). Beim Befehl entsteht die Datensatzversion, beim Lauf liegt sie mit Captions im ComfyUI-Eingang; die LoRA wird nach `local/models/loras/characters/` übernommen und in der Registry `[loras.*]` eingetragen (SHA-256, Basis-Engine und -Datei, Datensatz, Trigger, Schritte, Rang, Lernrate, Status OFFEN). Echter Lauf aus dem Cockpit offen bis zu den Charakterfotos.
  - **1K-Standbild:** „Verfeinern“ skaliert vor der LUSTIFY-Verfeinerung auf eine kurze Seite von 1080 px (`ResizeImageMaskNode`, lanczos); Auftrag 36 aus 0033: 1024 → 1080 × 1080 in 54 s, Identität 0,83 zum Original.
  - **Remix nach Autorvorgabe** (4+4 Schritte, CFG 1, euler/simple, Shift 8; Negativ-Prompt bei CFG 1 ohne Wirkung, daher nicht mehr angeboten): erstes vollständiges Wan-Video, Auftrag 35 aus 0033, 480 × 832, 81 Frames, 16 fps, H.264, 2941 s (≈ 6 min je Schritt); Speicher frei 74,1 → min 12,1 GB, **Swap 14,4 → max 42,2 GB**; keine sichtbare MPS-Bildstörung bei rund 33 000 Token. Identität 0,89 → 0,82 in den ersten 20 Frames, danach Profilansicht (Metrik dort nicht aussagekräftig) und sichtbar leichte Drift (jünger, helleres Haar) – Befund für den Videovergleich in B4.
  - Offen in B1: echtes Training mit den Charakterfotos, LoraLoader-Workflow mit der ersten LoRA (A/B mit/ohne), Wan-FP16-Speicherursache.

**B2 – Identität, Bildqualität, Pose, Hochskalierung** · Status: OFFEN
- Ziel: Identitätsprofil (§9.2) mit Metrik und Prüfsatz; gemeinsamer Modell-/Identitäts-A/B (vorhandene vs. Krea 2/LUSTIFY v10/FLUX 3 Klein); Produktionsfunktionen im F7.5-Layout (Charakter, Kandidaten, Vergleich, Ausgabeprofil, §9.6); Pose-/Tiefensteuerung (SDPose, Depth Anything 3, Adapter nur mit Nachweis); Bearbeiten/Ausziehen (SAM 3.1 + Inpaint + Composite); Original ≥ 1K und Bild-Upscaler 2K/4K als abgeleitete Version (SeedVR2 7B/3B; nativ 4K mit FLUX 3 Klein im Vergleich), Instagram-Ausgabeprofile Foto (§9.7). Modelle lädt Darkfluenzer selbst (§14.1).
- Fehlt: Auftrag mit Stufen (§4.3: Kandidaten → Auswahl → Bearbeiten → Fertigstellen; STATE 4, EVENT 23, Befehle 21/22/24), Charakterverwaltung (Backend + UI), mflux-/Trainingspfad für Krea 2, Modelle (schrittweise, nach Speicherbilanz), STATE 5, EVENT 24, Befehle 25–27, Charakterseite.
- **Teilnachweis 15.11.2026 – Identitätsmetrik:** `identity.py` (YuNet → SFace + AuraFace aus der Registry, Kosinus zum Referenz-Schwerpunkt, „nicht prüfbar“ unter `min_face_px`), CLI `darkfluenzer identity`; echter Abgleich gegen 0033: selbst 1,00, Verfeinerung 0,78, anderer Seed 0,42, andere Frau 0,19 (Commit `5fa1fe0`).
- **Teilnachweis 15.11.2026 – Auftrag mit Stufen (Ablauf A):** Migration 5 (Tabellenneubau `orders` mit `source` operator/cloner/customer, Kunde nur bei Kundenaufträgen; `order_stages`; `jobs.stage_id`; vor dem Lauf gesichert, `integrity_check`/`foreign_key_check` sauber, alle Zeilen erhalten); Befehle 21 `create_order` (Kandidaten mit fortlaufenden Seeds, optional „Fertigstellen mit“), 22 `select_candidate` (nur Medien der wartenden Stufe), 24 `retry_stage` (Obergrenze `[production] stage_attempts_max`); STATE 4 `ORDERS_ACTIVE`, EVENT 23 `ORDER_UPDATED`. Rechts Kandidatenzahl (Standard/Max aus `[production]`) und „Fertigstellen mit“, Mitte Kandidatenvergleich mit synchronem Zoom. Mac: DF-O-000001 – drei LUSTIFY-Kandidaten, Auswahl per Klick in der Oberfläche (Seed 102417, Medium 51), Fertigstellen mit „Verfeinern“ → 1080 × 1384 (Medium 53, Eltern 51), Auftrag zur Prüfung; Stufenverlauf im Journal.
- **Teilnachweis 15.11.2026 – Ausgabeprofile (§9.7):** Format-Feld rechts setzt die Abmessungen der Engine aus dem Manifest (`[engines.*].formats`: Krea 2 Turbo 3:4 1104 × 1472, 4:5 1088 × 1360, 1:1 1088 × 1088, 9:16 1088 × 1936; LUSTIFY SDXL native Buckets, 1K über „Verfeinern“). Instagram-Export als modellfreier Workflow `output_instagram` (Engine `arch = "none"`, lädt/entlädt keine Modelle – nachgewiesen: LUSTIFY blieb über einen Export hinweg geladen): Aufträge 43/44 → **1080 × 1440** (aus Krea 1104 × 1472) und **1080 × 1350** (aus 1080 × 1384, mittig ≈ 17 px oben/unten), je ≈ 1 s. JPEG-Kodierung für den Versand folgt mit dem Kanal (C3).
- **Teilnachweis 15.11.2026 – Krea 2 Turbo BF16** (`krea2_turbo_t2i`, Vorlage `image_krea2_turbo_t2i` ohne Prompt-Erweiterer): Aufträge 37/38 im Cockpit, 1104 × 1472 (3:4, kurze Seite ≥ 1080), 8 Schritte, 251 s mit Laden / 201 s geladen, Spitze ≈ 42 GB, kein Swap-Zuwachs, keine MPS-Bildstörung (zweiter Testfall zu #14837 neben dem Wan-Lauf); Ergebnis sehr fotografisch (Haut, Hände, Stoffe, Licht), Altersangabe im Prompt in einem von zwei Läufen verfehlt. Krea 2 Raw ist laut Modellkarte Trainingsbasis, nicht Inferenzmodell.
- **Teilnachweis 15.11.2026 – Bearbeiten/Ausziehen (Ablauf C):** Workflow `lustify_sam31_edit` – SAM 3.1 FP16 findet den Bereich per Text und spart Gesicht/Haare aus → LUSTIFY-Inpaint nur in der Maske → `ImageCompositeMasked`; die Maske ist zweite Ausgabe (Ergebnis und Maske nebeneinander im Ergebnis), die Pixelprüfung läuft gegen die erzeugte Maske (Manifest `mask_output`). Im Cockpit aus Medium 33 gerendert (Aufträge 32 und 34): 0 Pixel außerhalb der Maske, beide Dateien mit Auftragsbezug in Dateien. Befunde: SAM-3.1-Erkennungswerte trennen vorhanden/nicht vorhanden nicht (fehlende Begriffe 0,42–0,90, echte 0,67–0,99; ein fehlender Bereich maskiert oft die ganze Person) → Maske immer sichtbar, Gesicht/Haare standardmäßig ausgespart; ComfyUI meldete für unveränderte Teilgraphen Dateien früherer Läufe aus seinem Cache (Auftrag 33: 404) → Ausgabe-Präfix je Auftrag; früh gespeicherte Ausgaben eines laufenden Auftrags indiziert die Galerie erst nach dessen Abschluss (mit Auftragsbezug). Feldnamen und Grund/Experte je Parameter kommen aus dem Manifest (`label`, `expert`). Umstellung auf LUSTIFY v10 nach dessen Download.
- Abhängigkeit: B1. Abnahme: Rollen `image_master`/`image_edit` mit dokumentierten Zahlen besetzt; Identitätsprofil-Version nach Freigabe aktiv; 0 Pixel außerhalb der Maske; 4K-Datei mit ausgewiesener nativer Auflösung; Hochskalieren aus Dateien ohne Neugenerierung; Instagram-Export 1080 × 1440 / 1350 / 1080 / 1920 mit korrekten Abmessungen.

**B3 – macOS 26** · Status: OFFEN (Betreiber führt aus)
- Vorher Sicherung, keine laufenden Jobs, DarkBot sichern; danach ComfyUI, Referenzrender, Cockpit und Tests erneut bestanden; LTX Desktop lokal geprüft. Vor den Videovergleichen.

**B4 – Video** · Status: OFFEN
- Ziel: freie Animation (Wan FP16 vs. Remix vs. LTX 2.5 Dev/Distilled in ComfyUI; LTX Desktop als Vergleich), Bewegungsübertragung (Wan Animate 2 vs. VACE vs. Fun Control), Langvideo-Regeln (Länge, Fenster, Übergänge, FPS, Ton), Video-Original ≥ 1K (Video-Upscaler aus der Nativauflösung), 2K/4K auf Wunsch (SeedVR2 Video vs. RelayVSR) + Interpolation (FILM), Reel-Profil 1080 × 1920, Identität über Frames.
- Abhängigkeit: B2, B3. Abnahme: Rolle `video_i2v` und Bewegungsübertragung mit Zahlen besetzt; Video in Dateien mit vollständiger Provenienz.

**B5 – KI-Modelle der KI-Instanz** · Status: OFFEN
- Ziel: Vision-/Prompt-Workflows (Bildbeschreibung → Prompt-Vorschlag) und Dialog-LLM (Kandidat Cydonia 24B) als registrierte, im echten ComfyUI-Editor bearbeitbare Workflows in KI-ComfyUI 2, aus dem Unterregister KI bedienbar; Nutzung für Kloner, Default-Nutzer und Kunden erst in Block C.
- Abhängigkeit: A3, B4. Abnahme: echter Lauf je Workflow; Latenz p50/p95 und Speicher unter gleichzeitiger Medienlast gemessen; dabei die aus A3 offene Prüfung: KI-Workflow auf Instanz 2 und Entladen der ruhenden anderen Instanz durch die Zulassung.

**Abnahme Block B:** die vollständige Kette aus dem Cockpit – Training → Foto → Bearbeitung → 1K-Original → Hochskalieren → Video → Dateien – mit allen ausgewählten Modellen real auf dem Mac.

### Block C – Telegram, Instagram und Kundenbetrieb (F4)

**C1 – Lokaler Referenz-Kloner** · Status: OFFEN
- Ziel: `clone`, `pose`, `style`, `remix`, `animate` mit lokal importierter Vorlage (Upload/Dateien) → Analyse → Charakterbindung → drei Kandidaten → Dateien; dazu freie Anweisungen mit mehreren Referenzen (§8.1) lokal im Cockpit; unabhängig von Kanälen nachgewiesen.
- Fehlt: Vorlagenablage und Analyse-Workflows, Befehls- und Anweisungsdeutung mit Referenzauflösung und Rückfrage (KI-Instanz), EVENT 25, Befehl 28, Vorlagenseiten, „Als Vorlage“ in Dateien.
- Abhängigkeit: Block B. Abnahme: jeder Befehl einzeln real geprüft.

**C2 – Kanal-Basis** · Status: TEILWEISE (15.11.2026)
- Ziel: Adapter-Schnittstelle und **Telegram-Adapter** (Long-Polling, Offset, Medien, Senden, Antwortbezug) sowie **Instagram-Adapter** (OAuth mit Token-Erneuerung, Webhook mit Signaturprüfung, Medien sofort sichern, Senden inkl. signierter Medien-URLs, Echo-Erkennung); Tunnel nur für Instagram (§10.1); Migration: kanalunabhängige Kunden + `channel_identities`, `channel_conversations`, Nachrichtenreferenzen, Eingangs-/Ausgangsaufgaben (bestehende Kunden und Nummern bleiben); interner Kontakt Default mit Operator-Feldern (§8, F7.4); Übersicht-Karte Kundenakten; Nachrichten-Cockpit im Lesemodus (drei Spalten, Kundenliste, Register, Unterregister, Farben, Gesamt nur lesbar); Kanalstatus.
- Wiederverwendet: Muster aus Chatwoot und der Betreiber-ZIP (Signaturprüfung, Normalisierung, Duplikat-/Echo-Erkennung), bestehende Host-/Origin-/Sitzungsprüfung, Ereignisjournal, Medienablage.
- Verträge: STATE 8, EVENT 26/27, Befehle 29 und 37, Kunden-/Verlaufsseiten.
- **Teilnachweis 15.11.2026 (Commits `4cfe052`, `418a636`):** Migration 6 auf den echten Daten (gesichert; Integrität und Fremdschlüssel geprüft; Jobs/Medien unverändert): kanalunabhängige Kunden (`kind` customer/internal), `channel_identities`, `channel_conversations` (Revision = CAS für Antworten), `channel_messages` (Ein-/Ausgang mit Status), `inbound_events` (Duplikate), `adapter_state` (Telegram-Offset), `message_files` (nur gesicherte Anhänge über den Medien-Endpunkt), `default_contact`. Telegram-Adapter (Long-Polling, Token nur im Schlüsselbund, Offset erst nach dem Speichern, Anhänge bis `max_download_mb` sofort gesichert, sonst „zu groß“; Postausgang „sendet“ → gesendet/fehlgeschlagen, nach Neustart „unbekannt“, kein Doppelversand). STATE 8, EVENT 26/27, Befehle 29/30/37, Kunden-/Verlaufsseiten; Antwort nur an Plattform + Identität + Konversation + Revision der Akte (Gesamt/fremder Kanal/fremde Konversation abgewiesen – Test). Nachrichten-Cockpit nach F7 (Kundenliste, Register, Unterregister, Gesamt nur lesbar, kanalfarbener Composer, „KI antworten“ ehrlich gesperrt ohne Text-KI, Default-Steuerung – GUI-Rundweg gespeichert und geprüft), Übersicht-Karte Kundenakten. **Offen:** echte Telegram-Nachricht (Bot-Token des Betreibers), Instagram-Adapter (Meta-App, Tunnel).
- Abhängigkeit: C1, Telegram-Bot-Token, Meta-App, Tunnel-Konto. Abnahme: echte Telegram- und Instagram-Nachricht erscheinen je genau einmal; doppelt zugestelltes Ereignis erzeugt nichts; Backend-Neustart verliert nichts (Telegram-Offset, Instagram-Abgleich); ungültige Signatur abgewiesen.

**C3 – Telegram: Default-Nutzer (Kloner, freie Anweisungen, Rückversand)** · Status: TEILWEISE (15.11.2026)
- Ziel: Default-Nutzer am Telegram-Bot der Influencerin sendet Foto/Video mit Befehl **oder freier Anweisung** (§8.1) → derselbe Produktionspfad wie C1 → **Rückversand der postfertigen Ergebnisse als Dateien in denselben Chat** (Freigabemodus, Postausgang, EVENT 28); Folgeanweisungen per Antwort („Nr. 2 in 4K“, „Nr. 1 als Reel“); Kennzeichnung `INTERNER AUFTRAG` in Nachrichten; Datei > 20 MB → Hinweis.
- **Teilnachweis 15.11.2026 (Commit `6606a16`):** Kloner-Weiche vor jeder Kundenverarbeitung: Nachrichten der Default-Absender-ID mit `clone`/`pose`/`style`/`remix`/`animate` (+ Wunsch) und Referenz (angehängt oder beantwortete Nachricht) → genau ein Auftrag (Quelle `cloner`) mit dem Medien-Workflow des Default-Kontakts, Systemkarte `INTERNER AUFTRAG · BEFEHL · KANAL` (Migration 7); Duplikat ohne zweiten Auftrag; freie Anweisung → genau eine Rückfrage (Deutung durch die KI-Instanz folgt mit B5); Rückversand als Dateien je Freigabemodus (direkt: Kandidaten; Cockpit: Auswahl/Fertigstellung; nur Cockpit: nichts). Eigene Telegram-ID als Default-Absender zieht samt Verlauf vom versehentlich angelegten Kunden um. **Offen:** echter Lauf vom Handy (Bot-Token), Analyse-Workflows je Befehl (Pose/Tiefe/Bildbeschreibung nach den Downloads), Folgeanweisungen „Nr. 2 in 4K“.
- Abhängigkeit: C1, C2. Abnahme: vom Handy 3 Fotos senden, dann „erstelle ähnliche Fotos für einen neuen Instagram-Beitrag“ → genau ein Auftrag mit korrekt aufgelösten Referenzen → Ergebnisse kommen im gewählten Instagram-Profil (z. B. 1080 × 1440) verlustfrei im Telegram-Chat an und liegen in Dateien mit Provenienz; „Nr. 2 in 4K“ liefert die hochskalierte Version ohne Neugenerierung; unklare Anweisung → genau eine Rückfrage; Duplikat-Ereignis ohne zweiten Auftrag; Neustart ohne doppelten Rückversand; DF-PUSH D 1, 5–7.

**C4 – Instagram: Default-Nutzer** · Status: OFFEN
- Ziel: direkt gesendete Bilder/Videos, geteilte Beiträge/Reels real prüfen; abrufbare Medien sofort sichern und wie C3 verarbeiten (freie Anweisungen eingeschlossen, Rückversand an die Telegram-ID des Default-Kontakts, sonst über Instagram, §6); nicht abrufbare als „nicht importierbar“. Voraussetzung: professionelles Instagram-Konto der Influencerin, Meta-App mit Instagram-Login und Nachrichtenberechtigung; Absender-Accounts mit App-Rolle (Standard Access genügt, §6). Abhängigkeit: C2, C3.

**C5 – Kundenbetrieb F4 vollständig** · Status: OFFEN
- Ziel: kanalgebundene Antworten (Befehl mit Kunde + Kanalidentität + Plattform-Konversations-ID + Revision; `channel=all` abgewiesen), KI antworten/Entwürfe/Modi/Übergabe-Erkennung, Influencerinnen (Profil, LLM, Bild-/Video-Workflow, Identitätsprofil, Freigabemodus), Kundengedächtnis, Instagram→Telegram-Token-Verknüpfung, Medienaufträge mit 8-Schritt-Verlauf (HD-Wunsch → Upscaler-Version, §9.7), Zahlungen (nur verifizierter Provider), Admin-Freigabe (Zweit-KI erst nach eigener Abnahme), Zustellung über die Adapter nur hinter `approval.py` mit Zustellkopie je Kanalgrenze (§6), Zustellstatus, Ereigniskarten; Übersicht-Karte Freigaben ausstehend; Instagram Advanced Access (Meta-App-Prüfung) für fremde Kunden.
- Verträge: STATE 9, EVENT 28, Befehle 30–36. Abhängigkeit: B5, C2–C4. Abnahme: FRONT-F4-Abnahmefälle (drei Kunden, Kanaltreue, Gesamt nur lesbar, Entwurf/Kanalwechsel, Dubletten, Neustart, KI aus, Übergabe, zwei Influencerinnen, zwei Aufträge, Zahlung/Freigabe/Zustellung genau einmal; Foto und Video je Kanal innerhalb der Grenze zugestellt, Zustellkopie mit eigenem SHA-256; DF-PUSH D 6–8).

**C6 – Gesamtabnahme** · Status: OFFEN
- Alle fünf Kurzbefehle und freie Default-Anweisungen über alle verfügbaren Eingänge inkl. Rückversand per Telegram, Neustart/Wiederaufnahme, Fehler, keine Doppelaufträge, keine Charakterverwechslung, vollständige Metadaten, freie Prompt-Generierung und Workflow-Verwaltung weiter funktionsfähig, Dateien dauerhaft, Kundendaten unbeschädigt, Release-Einheit/Rückfall.

**C7 – Weitere Kanäle (später)** · Status: OFFEN
- WhatsApp (Cloud API), danach Fanvue/TikTok/Shop jeweils als weiterer Adapter derselben Schnittstelle, nur mit freigegebener offizieller API; je Kanal ein realer End-to-End-Test.

## 13. Widerspruchsauflösung gegenüber BACK V1.10/1.11 und FRONT V1.7/1.8

| Thema | Bisher | Gilt jetzt (V0) |
|---|---|---|
| Autorität | BACK „einziger normativer Masterplan“; FRONT nennt nur BACK | V0 verbindlich (§0) |
| Modelle für den ersten Kettennachweis | BACK §0: keine weiteren Modelle | gilt für **B1**; danach A/B mit Kandidaten (B2/B4) |
| Master-Rolle FLUX 3 Klein, FLUX.2 Dev als Benchmark (BACK) | fest | Kandidaten im A/B; FLUX.2 Dev nach Platzentscheidung |
| Erster Videopfad | BACK: Wan FP16 zuerst; V0.1: Remix-Rezept | B1 Wan FP16; Remix-Korrektur in B1, Vergleich B4 |
| Trainingsort | BACK: in ComfyUI 1; V0.1: mflux | B1: ComfyUI-Trainingsworkflow zuerst, diffusers als Ausweich; Krea 2: mflux (B2) |
| Datensatz | BACK ≥ 15/768 px; V0.1 25–40/1024 px | Minimum 15/768 (Gate), empfohlen 25–40/1024 |
| GPU-Warteschlange | FRONT/V0.1: genau eine; BACK: zwei Queues | zwei Queues + gemeinsame Zulassung (§4.2) |
| Engine je Auftrag (BACK) | eine Engine pro Auftrag | eine Engine je **Stufe**, Entladen dazwischen |
| Desktop-Hülle | V0.1: Electron | gestrichen; Browser-Cockpit + Swift-Starter |
| Instagram-Zugriff | V0.1: instagrapi/Sammlungen | nur offizielle Instagram-API über eigenen Adapter (§6, §8) |
| Instagram als Kanal (FRONT F6) | später | eigener Adapter in C2/C4 |
| Kanalinfrastruktur (BACK §4/§4B, FRONT F4, ZIP) | Chatwoot nativ | eigene Python-Adapter; Chatwoot-Dienste, -Gates und -Parameter gestrichen; WhatsApp später (C7) |
| Erstkontakt = Kundenakte (FRONT F4) | jede Nachricht | Kloner-Weiche vor Kunden-/KI-Verarbeitung (§8) |
| TTS in der KI-Instanz | fester Bestandteil | weiterer KI-Workflow, sobald qualifiziert |
| Reproduzierbarkeit (BACK) | Seeds, Modell-Hash, Workflow-Revision | vollständige Liste §9.5 |
| Face-Swap | nicht geregelt | Regel 4 |
| FRONT „keine Löschfunktion“, „drei Routen“, „Als Nächstes F4“ | veraltet | Löschen implementiert; vier Reiter; Reihenfolge §12 |
| Produktionsarbeitsbereich (V0.2-Entwurf) vs. F7.5 | eigene drei Spalten + Schaltflächen | F7.5-Layout; Produktionsfunktionen als Felder darin (§9.6) |
| Kandidaten vs. F7.5 „keine fiktiven Kandidatenflächen“ | drei Kandidaten | je Kandidat ein echtes Renderergebnis, keine Platzhalter |
| Chatwoot im DF-PUSH-Vertrag und in F7 (BACK 1.11, FRONT 1.8) | Chatwoot-Adapter/-Conversation | eigene Kanal-Adapter, Plattform-Konversation (BACK 1.12, FRONT 1.9) |
| Medienversand und Kloner-Rückversand | ungeregelt | Eingabefeld nur Text; Kundenmedien nur nach Zahlung + Freigabe, als Zustellkopie bei Kanalgrenze; Ergebnisse des Default-Nutzers per Telegram an ihn zurück (Betreiberentscheidung 15.11.2026; ändert FRONT F7.4 „ausschließlich Mitte und Dateien“), zusätzlich in Nachrichten und Dateien (§6, §8.1) |
| Fertigstellung 4K (BACK, V0.1) | 4K als Fertigstellungsstufe | Original ≥ 1K; 2K/4K nur per Upscaler auf Wunsch (§9.7) |
| Reihenfolge (V0.2/0.3) | Kernkette P0 zuerst | Block A (ComfyUI + Dateien) → Block B (Modelle, Workflows) → Block C (Kanäle); keine parallele Entwicklung (Betreiberentscheidung 15.11.2026, §12) |
| Modellbestand | „nicht pauschal löschen“ | Betreiberauftrag 15.11.2026: RealCore, Qwen-Image 20B entfernt; Löschen nur nach ausdrücklicher Bestätigung (§9.3) |

## 14. Voraussetzungen durch den Betreiber

- Charakterfotos in `local/character/photos/` (B1).
- Modelle: Darkfluenzer lädt nacheinander (§14.1); der Betreiber lädt nur Dateien hinter Anmeldung/Lizenzannahme (LUSTIFY v10, FLUX 3 Klein), nimmt die LTX-2.5-Lizenz auf Hugging Face an und entscheidet über Platz (FLUX.2 Dev) und jedes Löschen. **Block A und B1 brauchen keine neuen Modelle.**
- macOS-26-Update (B3).
- Kostenloses Tunnel-Konto (Tailscale oder ngrok) – nur für Instagram (C2).
- Telegram-Bot (BotFather-Token); professionelles Instagram-Konto der Influencerin mit Meta-App (C2–C5); freigegebene Absender-Accounts. WhatsApp Business erst für C7.

### 14.1 Modelle und Downloads

Vollständige Liste mit Präzision, Größe, Quelle/Revision, Ablage, Status und Platzbilanz: **[ki_modelle.md](ki_modelle.md)**. **Darkfluenzer lädt die Modelle selbst, streng nacheinander** (Betreiberhinweis 15.11.2026): je eine Datei vollständig, SHA-256 geprüft, erst dann die nächste; nach jeder fertigen Gruppe wird ihr Workflow gebaut und real getestet, während die nächste lädt. Geladen wird die Originalpräzision; vor jeder Datei Platzprüfung mit 30 GB Reserve. Registrierung im Manifest mit Präzision aus dem Dateikopf, SHA-256 und Quelle.
