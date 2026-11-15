# DARKFLUENZER — PHASENPLAN V0: Produktionskette, Charakteridentität, Content-Cloner, Desktop-App

**Version:** 0.1 · **Stand:** 15.11.2026 · **Status:** Konzept, Umsetzung offen
**Abgleich offen:** Am 15.11.2026 kamen auf `main` PHASENPLAN_BACK_V1 V1.10 (§0 Sofortpriorität LoRA→Foto→Wan-Kette mit vorhandenen Modellen, natives M4 ohne Docker, zweite KI-ComfyUI-Instanz) und PHASENPLAN_FRONT_V1-Ergänzungen hinzu. Dieses Dokument ist damit **noch nicht abgeglichen**; vor Umsetzungsbeginn werden Widersprüche (insbesondere Modellwahl und Reihenfolge gegenüber BACK §0) mit dem Betreiber aufgelöst.
**Bezug:** ergänzt PHASENPLAN_BACK_V1 (S1 Starter, S2 Foto, S3 Video, §6B) und PHASENPLAN_FRONT_V1 (Reiter ComfyUI). F4 Nachrichten ist pausiert.

> **Vorrangbeschluss DF-PUSH-PROTOBUF-E2E-2026-11-15:** Jeder Medien-/Referenz-/Chat-/Kunden-/Job-Workflow und jedes bedienbare Feld erhalten **im selben Implementierungspaket** den vollständigen Python-Owner→typisiertes Protobuf→ein vorhandener WebSocket→React-Push-Hinweg sowie bei Bedienung den Protobuf-Command→Python→persistierte Receipt→Push-Rückweg. **Keine periodischen fachlichen Browserabfragen**, große Historien nur versionsgebunden/on-demand. Verbindliche Details, Ist/Soll und Abnahme: [PHASENPLAN_FRONT_V1.md](PHASENPLAN_FRONT_V1.md) (Abschnitt `DF-PUSH-PROTOBUF-E2E-2026-11-15`) und [PHASENPLAN_BACK_V1.md](PHASENPLAN_BACK_V1.md) (gleicher Beschluss). Python-/ComfyUI-/Chatwoot-Architektur bleibt eigenständig; kein Rust-/DarkBot-Gateway, kein zusätzliches Dashboard. Vorhandene Phasen-/Designverträge bleiben gültig, soweit sie dem neuen Push-/Protobuf-Rundweg nicht widersprechen.

## 1. Ziel

Darkfluenzer produziert mit **einer festen, vollständig synthetischen, erwachsenen Influencerin** in zwei gleichwertigen Bereichen: **professionelle Instagram-Fotografie und -Videos** sowie **realistisch wirkende erotische bis explizite Foto- und Filmproduktion** – möglichst nicht von echten Kameraaufnahmen zu unterscheiden, Fotos und Videos bis 4K, lokal auf dem MacBook Pro M4 Max (128 GB), mit frei verfügbaren Modellen, ohne Cloud.

Bedient wird alles aus der **Darkfluenzer-Desktop-App**: Charakter wählen, Motiv oder Vorlage festlegen, erzeugen, vergleichen, freigeben. Modelle und ComfyUI-Workflows sind darunter austauschbare, geprüfte Werkzeuge. Vorlagen kommen zusätzlich automatisch aus **Instagram-Sammlungen eines separaten Sammelkontos**, das in der Desktop-App eingebunden ist (Content-Cloner).

## 2. Verbindliche Regeln

1. **Qualität vor Geschwindigkeit:** maximale, reproduzierbar nachgewiesene Fotorealität und Identitätskonsistenz; lange Renderzeiten sind akzeptabel.
2. **Nur echte Vergleiche entscheiden:** Modell, Identitätsmethode und Auflösungsweg werden durch reale A/B-Tests mit den Charakterbildern des Betreibers auf diesem Mac festgelegt; Ranglisten, Modellgröße und Herstellerangaben sind nur Kandidatenquellen, keine Abnahmekriterien.
3. **Identitätsbindung:** gleiches Gesicht, gleiche Figur und Anmutung über alle Stufen. LoRA ist Mittel, nicht Ziel. „Identität gesperrt“ heißt: Der Auftrag verwendet verbindlich dieses Profil – keine Garantie; abweichende Ergebnisse werden zurückgewiesen.
4. **Module getrennt:** Identität | Pose/Szene/Vorlage | Bearbeitung (inkl. Ausziehen) | Video | Ausgabe.
5. **Explizite Bearbeitung nur abgeleitet:** maskiert vom freigegebenen Bild; im Bearbeitungsschritt bleibt außerhalb der Maske jedes Pixel gleich (automatisch geprüft; spätere Skalierung verändert Pixel bewusst).
6. **Video nur vom freigegebenen Foto** bzw. bei Bewegungsübertragung mit dem freigegebenen Charakterbild als Identitätsreferenz.
7. **Lokal und lizenzsauber:** keine Cloud-Generierung; jede eingesetzte Modelldatei mit Quelle, Revision, SHA-256 und Nutzungsbedingungen im Manifest; Umsatzgrenzen beachten.
8. **Präzision je Komponente:** Generierungsmodell, Text- und Bildencoder, VAE/Decoder, Adapter und Hilfsmodelle einzeln festlegen. Originalgewichte in der besten verfügbaren und kompatiblen Präzision; erforderliche FP32-Komponenten bleiben FP32 (z. B. RelayVSR-Decoder); aus quantisierten Dateien umgewandelte Gewichte gewinnen keine Genauigkeit zurück; Speicherformat und tatsächlicher Rechendatentyp werden dokumentiert.
9. **Weiter gültig (PHASENPLAN_BACK_V1):** Drag-and-drop-Ordner `local/character/photos/`, Master-First, Gates Laden/Rendern/Qualität/Lizenz, Betreiberfreigabe vor jeder Auslieferung, eine gemeinsame GPU-Warteschlange, Protobuf zwischen Cockpit und Backend, kein Frontend-Polling.
10. **Ehrliche Erwartung:** Einzelfotos, die in vielen Szenen praktisch nicht von echten Fotos zu unterscheiden sind, sind mit dieser Kette, Kandidatenauswahl und Prüfung erreichbar. Für jede Szene und für Video garantiert das 2026 kein lokales Modell; Ziel ist die maximal messbare Annäherung.

## 3. Ist-Zustand (geprüft am 15.11.2026)

- **Modelle vorhanden:** LUSTIFY v2.0 (SDXL), RealCore Illustrious, Qwen-Image 20B BF16, Qwen-Image 2.1 BF16 (nicht kommerziell), Wan 2.2 I2V A14B FP16 (high+low), Wan 2.2 Remix NSFW v3.0 FP8 „lighting“, Encoder (umt5, Qwen-VL), Qwen-Image-VAE.
- **ComfyUI 0.45.3**, Vorlagenpaket `comfyui_workflow_templates_json` 0.1.133 mit offiziellen Vorlagen für Krea 2, FLUX 3 Image Klein, LTX 2.5, Wan 2.2 / Animate 2 / VACE / Fun Control, SAM 3.1, SDPose, Depth Anything 3, SeedVR2, RelayVSR, FILM. Mehrere Komponenten sind im ComfyUI-Kern implementiert. Die Vorlagen verweisen standardmäßig auf int8-/fp8-Dateien. **Vorlage vorhanden ≠ Modelle vorhanden, importierbar oder auf diesem Mac gerendert.**
- **Blocker Workflow-Import:** `comfy.ui_to_api` weist Untergraphen, Primitive-Nodes und umgangene/stumme Nodes ab ([comfy.py:602](../backend/src/darkfluenzer/comfy.py)). **13 der 15 vorgesehenen Vorlagen enthalten Untergraphen**; Wan 2.2 Fun Control hat 23, VACE v2v 6 umgangene Nodes.
- **Bestanden:** LUSTIFY-SDXL Text-zu-Bild, Verfeinern, maskiertes Inpainting (0 Pixel außerhalb der Maske); Eingabebild aus Dateien (Job 22 nutzte nachweislich Bild 0024); Workflow-Verwaltung F3a (aktivieren/deaktivieren, öffnen, bearbeiten, übernehmen, löschen).
- **Noch nie ein Wan-Video fertig:** Job 21 (Remix 512×320, 49 Frames) 22 min für die ersten 12 Schritte, in ComfyUI abgebrochen. Laut Autor gehören zu Remix 4+4 Schritte, CFG 1, euler/simple, Shift 8 (verwendet: 12+12, CFG 5, Shift 5). Hoher Swap während des Laufs – **vermutete** Ursache: Modelle werden zwischen Engines nicht entladen (nicht gemessen).
- **Manifest:** Rollen `image_master`, `image_edit`, `video_i2v` unbesetzt; neun Einzel-Workflows ohne Charakterbindung, Referenzanalyse, Posen-/Bewegungsübertragung und 4K-Stufe.
- `training.py` nur SDXL-LoRA; Charakterfotos legt der Betreiber noch ab; LUSTIFY v10 lädt der Betreiber selbst (Civitai).
- Starter: Swift-App (pinkes C) startet Backend und öffnet das Cockpit im Browser (S1 PASS).

## 4. Kandidaten (Stand 15.11.2026; Quellen: Primärquellen, Artificial-Analysis-Ranglisten, HF-/Civitai-Ranglisten, YouTube 01.10.–15.11., Praxisberichte; Reddit/civitai.com für Abruf gesperrt)

| Aufgabe | Kandidaten | Lizenz / Mac-Hinweise |
|---|---|---|
| Foto normal (Instagram) | Krea 2 (Raw/Turbo), FLUX 3 Image Klein (Base/destilliert; laut BFL nativ 4K, bis 10 Referenzbilder); Qwen-Image 2.1 nur als Qualitätsreferenz | Krea 2: Community License (kommerziell < 1 Mio. $; Inhaltsfilter-Maßnahmen Pflicht, menschliche Prüfung ist eine genannte mögliche Maßnahme; übrige Bedingungen gelten). FLUX 3 Klein: Kommunity License < 5 Mio. $. Qwen 2.1: nicht kommerziell |
| Foto explizit | LUSTIFY v10 (Krea 2), GonzaLomo, SNOFS, Krea 2 + Refusal-Reduction-LoRA | Civitai-Finetunes; Bedingungen je Datei prüfen |
| Identität | Charakter-LoRA auf Krea 2 Raw (mflux, dokumentiert als QLoRA mit 8-Bit-Basis); LoKr (**experimentell, Training für Krea nicht belegt**); Referenz-Conditioning: Krea 2 Identity Edit v1.x, Krea 2 ReID, FLUX 3 Klein Multi-Referenz | Identity Edit V2 nicht kommerziell → v1.x. ai-toolkit-Mac-Unterstützung experimentell. FLUX-3-Klein- und LTX-Training nur CUDA/Linux dokumentiert |
| Pose/Tiefe Foto | Krea 2: Depth-Control (Community: facok/comfyui-krea2-controlnet + Krea-2-Depth-Modell); Pose nur mit einem konkret nachgewiesenen Pose-Adapter (Kandidat: thedeoxen/Krea-2-pose-controlnet); Analyse SDPose, Depth Anything 3 | Depth ≠ Pose; Kombination mit Charakter-LoRA gemeinsam testen |
| Bearbeiten/Ausziehen | SAM 3.1 (Kern) + maskiertes Inpainting mit LUSTIFY v10 + `ImageCompositeMasked` | — |
| Video aus Foto | LTX 2.5 (Dev BF16 / Distilled BF16, x2-Raum-/Zeit-Upscaler, Gemma-4-Encoder); Wan 2.2 I2V (Remix bzw. FP16 + NSFW-LoRA) | LTX < 10 Mio. $; Wan Apache 2.0. LTX Desktop lokal nur macOS 26; ComfyUI-Pfad im Test |
| Bewegungsübertragung | **Wan Animate 2** (Charakterbild + Bewegungsvideo direkt, **ohne Posen-Extraktion**); Vergleich: Wan 2.1 VACE v2v (Kontrollvideo), Wan 2.2 Fun Control (Posen-/Tiefen-Kontrollvideo) | VACE ref2v allein überträgt keine Referenzbewegung |
| 4K | SeedVR2 3B/7B (**Hauptpfad ComfyUI-Kern**; numz-Wrapper nur Vergleich), RelayVSR (FP32-Decoder), nativ: FLUX 3 Klein, LTX | A/B nativ gegen Upscaling |
| Interpolation | FILM (Kern), RIFE | — |
| Identitätsmetrik | AuraFace-v1 (`glintr100.onnx`, Apache 2.0) + OpenCV SFace/YuNet (Apache 2.0) | InsightFace: Code MIT, mitgelieferte Gewichte eingeschränkt → nicht verwenden |

**Nicht eingeplant:** MiniMax H3 / H3-Image (Lizenz schließt die EU aus), FLUX.2 Dev (nicht kommerziell), HunyuanVideo 1.5 (EU ausgeschlossen), NVIDIA Cosmos 3 (64 B, CUDA).

**Mac-Grenzen (zu prüfen, nicht angenommen):** kein FP8-Rechnen auf MPS; Krea 2 braucht FP16-VAE; Krea 2 Raw + CFG neigt zu NaN; MPS-Attention-Korruption bei großen Sequenzen (ComfyUI #14837): betroffen sind laut Meldung auch PyTorch-Attention, Fix in PyTorch-Nightly ≥ 2.14.0.dev20260715 teilweise wirksam, Chunking-PR offen – **das Startflag `--use-pytorch-cross-attention` ist kein belegter Fix**. Herstellerwerte LTX stammen von einem M5 Max.

## 5. Desktop-App (Betreiberentscheidung 15.11.2026)

- **Beschluss:** Das gesamte Cockpit läuft als **Desktop-App** mit integrierter Instagram-Ansicht. Damit wird PHASENPLAN_BACK_V1 §6B („keine native zweite GUI, keine WKWebView“) für diese eine Desktop-Hülle ausdrücklich geändert: Die Hülle zeigt **dieselbe** React-Oberfläche vom lokalen Same-Origin-Server – keine zweite GUI.
- **Technik:** Electron (Chromium) – Hauptfenster lädt das Cockpit von `127.0.0.1:<Port>`; Instagram läuft in einer **isolierten Webansicht** (`WebContentsView`) mit eigener dauerhafter Sitzungspartition, ohne Node-Integration, ohne Zugriff auf Backend-Befehle oder Cockpit-Sitzung. Elektron-Version gepinnt.
- **Ersetzt den Swift-Starter** (keine Parallelarchitektur): gleiches pinkes „C“, Start über `darkfluenzer up` erst nach Health-Check, Stoppen nur eigener Prozesse, zweiter Doppelklick idempotent – die S1-Abnahme wird mit der neuen App wiederholt. Das Cockpit bleibt zusätzlich im normalen Browser erreichbar (ohne Instagram-Ansicht).
- **Ersatzlösung**, falls Instagram die Anmeldung in der Hülle nicht dauerhaft akzeptiert: vom Backend gesteuertes, getrenntes Browserfenster mit eigenem Profil – ausdrücklich als Ersatz, nicht als Erfüllung der Anforderung.

## 6. Bedienkonzept

Hauptreiter bleiben **Übersicht · Nachrichten · ComfyUI · Dateien**. Im Reiter **ComfyUI** bleiben die Unterregister **Fotos** und **Videos**; über Schaltflächen öffnen sich **Charakter verwalten**, **Vorlagen** (inkl. Instagram) und **Workflows verwalten**. Die bestehende Workflow-Verwaltung (aktivieren/deaktivieren, exakt öffnen, bearbeiten, übernehmen, löschen) bleibt erhalten.

**Arbeitsbereich in drei Spalten** – links Auftrag (Produktionsart, gespeicherte Produktionsprofile, zugehörige Vorlagen, aktueller Auftrag mit Stufen), Mitte Arbeitsfläche (Referenz bzw. Ergebnis, Kandidatenvergleich, Masken-/Pose-/Tiefenvorschau, Video mit Zeitleiste), rechts Einstellungen (Charakter mit Profilversion, Motiv/Vorlage, Format, Ausgabegröße, bei Video Dauer, Kandidatenzahl Standard 3, **Generieren**, aufklappbare **Details**). Warteschlange als aufklappbare Leiste unten. **Details** zeigt nur Parameter, die der gewählte Workflow tatsächlich unterstützt (Motiv, Bildaufbau, Generierung, Identität, Referenzsteuerung, Bearbeitung, Video, Ausgabe, Ausführung); kein pauschaler Qualitätsregler, kein wirkungsloser Negativprompt.

**Abläufe:**
- **A – Neues Foto:** Charakter → Motiv → Format → drei Kandidaten → vergleichen → auswählen → fertigstellen.
- **B – Foto nach Vorlage:** Vorlage laden bzw. aus Instagram-Sammlung → übernommene Eigenschaften wählen (Pose, Ausschnitt/Komposition, Perspektive, Licht/Farbe, Umgebung, Kleidung/Requisiten) → Analyse kontrollieren → erzeugen → vergleichen → fertigstellen.
- **C – Foto bearbeiten (inkl. Ausziehen):** eigenes Bild → Änderung beschreiben → vorgeschlagenen Bereich kontrollieren/korrigieren → vergleichen → speichern.
- **D – Video:** freigegebenes Foto → **freie Animation** (Bewegung beschreiben) **oder** **Bewegungsübertragung** (Referenzvideo) → Dauer/Format → erzeugen → prüfen → fertigstellen.

**Wer wählt aus:** An der kreativen Stufe wählt immer der Betreiber einen der drei Kandidaten; automatische Aufträge (Instagram) laufen bis zu dieser Auswahl und warten dann sichtbar. Nachbearbeitung arbeitet auf dem ausgewählten Kandidaten.

**Vergleichsansicht:** synchronisierter Zoom, Vorher/Nachher, Identitätswert mit Unsicherheit, Charakter- und Workflowversion; **Auswählen · Verwerfen · Variante erzeugen · Weiterverarbeiten**; bei Video synchronisierte Wiedergabe und markierte Problemstellen.

**Dateien:** Status (Entwurf/ausgewählt/freigegeben), Herkunft (Vorlage, Auftrag, Stufe), native und ausgegebene Abmessungen getrennt (z. B. 3840 × 2160), Modell-, Workflow-, Charakterversion, Seed und alle Einstellungen.

## 7. Auftragsmodell, Workflows, Warteschlange

- **Auftrag mit Stufen** (z. B. Vorlage analysieren → Kandidaten → Auswahl → Fertigstellen → Video → Freigabe), jede Stufe mit dauerhaftem Zustand in SQLite; manuelle Bedienung, Cloner und spätere Chat-Aufträge erzeugen denselben Auftragstyp.
- **FIFO für ausführbare Stufen** (bestehender `render_worker`): feste Reihenfolgenummer, höchstens ein schwerer Generierungs- oder Trainingsschritt gleichzeitig; wartende Betreiberentscheidungen blockieren andere Aufträge nicht; Wiederholungen gezielt und mit Obergrenze; Anhalten und Abbrechen je Auftrag.
- **Wiederanlauf:** Vor einem erneuten Start einer Stufe wird mit ComfyUI abgeglichen (Warteschlange und Verlauf zur gespeicherten `prompt_id`), ob sie noch läuft oder schon fertig ist – fertige Ausgaben werden übernommen statt neu gerendert.
- **Engine-Wechsel:** Modelle werden kontrolliert entladen (`/free`); Speicherverlauf gemessen.
- **Parameterbeschreibung im Manifest:** Typ, Standard, Minimum/Maximum/Schritt, zulässige Werte, Abhängigkeiten, Graph-Eingang, Grund/Experte; Backend validiert erneut; Produktionsprofile speichern Einstellungen (wirksam ab dem nächsten Auftrag).
- **Workflow-Übernahme (Pflicht vor Nutzung der Vorlagen):** Für jede ausgewählte Vorlage erzeugt Darkfluenzer einen zur installierten ComfyUI-Version passenden, geprüften API-Graphen – **Untergraphen werden aufgelöst**, umgangene Nodes durchgereicht, stumme entfernt, dynamische Eingänge, Schalter und Schleifen korrekt abgebildet. Abgleich gegen den API-Export des echten ComfyUI-Frontends (`graphToPrompt`) mit 0 Abweichungen. UI-Graph, API-Graph und Parameterbindungen bleiben derselben Version zugeordnet; Öffnen, Bearbeiten und erneutes Übernehmen werden getestet. Der Betreiber muss nie selbst Nodes auflösen.
- **Workspace-Aufbau:** Eingaben → Modell und Identität → Steuerbedingungen → Generierung → optionale Nachbearbeitung → Ausgabe; gruppiert und benannt; keine ungenutzten Nodes; gepinnte Versionen; Vorabprüfung auf fehlende Nodes/inkompatible Adapter; Zwischenprodukte an Stufengrenzen; Fehler mit betroffener Stufe. „In ComfyUI öffnen“ lädt exakt die Version, Änderungen werden Entwurfsversion.
- **Workflowverwaltung** zeigt getrennt: Dateien vorhanden · Laden bestanden · Rendern bestanden · Qualität freigegeben · Nutzung freigegeben.

## 8. Charakteridentität

- **Profil (versioniert):** Name, ID, Version; Charakterreferenzen (Gesicht/Halb-/Ganzkörper); Adapter mit Modellfamilie und Version; geprüfte Referenz-/Adaptereinstellungen; **getrennter, zurückgehaltener Prüfsatz** und feste Testszenen; Bewertung (Gesichtswert, Sichtprüfung, Schwächen). Auftragsmaster (freigegebenes Ausgangsbild einer Bearbeitung/eines Videos) ist davon getrennt. Neue Version erst nach Freigabe aktiv.
- **Charakterfotos:** Startbereich 25–40 Bilder (keine Qualitätsgarantie), ≥ 1024 px; Gesicht aus mehreren Winkeln, Halb- und Ganzkörper inkl. Körperreferenzen, mehrere Lichtstimmungen und Outfits. Beschriftung passend zur jeweiligen Trainingsmethode. Trainings- und Prüfbilder bleiben getrennt.
- **Prüfung:** Gesicht (YuNet → AuraFace + SFace → Ähnlichkeit zum Schwerpunkt freigegebener Gesichter; Schwelle aus Betreiber-Bewertungen; „nicht zuverlässig prüfbar“ bei verdeckten/kleinen Gesichtern); Körper und Gesamtwirkung getrennt (Betreiber-Sichtprüfung); Video: Stichproben über alle Frames + zeitliche Prüfung + vollständige Sichtung vor Freigabe.
- **Methoden:** Charakter-LoRA (mflux auf Krea 2 Raw; QLoRA mit 8-Bit-Basis als dokumentierte Trainingsausnahme, Generierung BF16), LoKr (experimentell), Referenz-Conditioning (Identity Edit v1.x, ReID, FLUX 3 Klein Multi-Referenz), Kombinationen, gezielte Nachbearbeitung. ai-toolkit als experimenteller Ausweich. Wan-Charakter-LoRA lokal versuchen, sonst entfällt sie. Jeder Adapter wird im tatsächlich genutzten Workflow nachgetestet.
- **Modell und Identität werden gemeinsam gewählt** (P3): Eine Krea-LoRA passt nicht zu FLUX 3 Klein – verglichen werden Paare „Bildmodell + passende Identitätsmethode“.

## 9. Content-Cloner: Instagram-Sammelkonto als Produktionseingang

### 9.1 Bedienung und Konto

- **Separates Sammelkonto** (Betreiberentscheidung): Gespeichert wird **im selben Konto**, das Darkfluenzer abgleicht – in der Instagram-Ansicht der Desktop-App oder am Handy (Kontowechsel in der Instagram-App). Nie das Produktionskonto der Influencerin. Das trennt Verbindungsprobleme vom Hauptkonto, macht den Zugriff aber weder offiziell noch garantiert zuverlässig.
- Unter **ComfyUI → Vorlagen → Instagram** einmalig Sammlungen zuordnen, z. B. „DF – Inspiration“ (nur importieren/analysieren), „DF – Fotos produzieren“ (Fotoauftrag, Ablauf B), „DF – Videos produzieren“ (Videoauftrag, Ablauf D Bewegungsübertragung). Pro Sammlung: Charakter, übernommene Eigenschaften, Format/Produktionsprofil, Kandidatenzahl, „sofort produzieren“ oder „nur sammeln“. **Speichern in einer aktivierten Produktionssammlung ist der Produktionsbefehl.** Likes werden nicht ausgewertet.
- **Account-Import:** ein fremdes öffentliches Profil als Vorlagensammlung übernehmen (spätere Ausbaustufe, gleicher Connector, gleiche Regeln).

### 9.2 Zugriff und Sicherheit

- Offizielle Instagram-/Meta-Schnittstellen bieten **keinen Zugriff auf eigene gespeicherte Sammlungen und keinen Webhook für Speichern**.
- Zwei Zugriffswege werden im Machbarkeitsnachweis geprüft, der funktionierende wird Hauptweg: (a) **instagrapi** im Backend (`collections()`, `collection_medias_by_name()`, `collection_medias()`), (b) die **angemeldete Instagram-Ansicht der Desktop-App** (Speichern dort sofort erkannt; Sammlungsseiten auslesen). Browser- und instagrapi-Sitzung sind **nicht** automatisch dieselbe.
- Beide Wege sind inoffiziell; Instagram-Nutzungsbedingungen untersagen automatisierten Zugriff; Prüfaufforderungen und Sperren sind möglich → zurückhaltende Abgleichintervalle, sichtbare Fehler, manueller Import bleibt gleichwertig.
- **Zugangsdaten:** keine dauerhafte Speicherung im Frontend, nie in Logs oder Git; Geheimnisse im **macOS-Schlüsselbund** bzw. verschlüsselt mit dort hinterlegtem Schlüssel; Sitzungen widerrufbar; Bestätigungscodes nicht protokolliert.

### 9.3 Abgleich und „höchstens ein Auftrag“

- Hintergrundprozess im Backend mit konfigurierbarem Intervall + „Jetzt abgleichen“ + sofortige Erkennung beim Speichern in der Desktop-Ansicht. Kein Frontend-Polling.
- Erstverbindung erfasst den Bestand; Altbestand wird nur bei ausdrücklich gewähltem Erstimport produziert.
- **Pro Sammlungsaktion (Beitrag × Sammlung × Zeitpunkt der Aufnahme) entsteht höchstens ein Produktionsauftrag; Erkennung und Auftragserstellung werden in einer SQLite-Transaktion gespeichert** – ein Absturz dazwischen verliert keinen Auftrag und erzeugt keinen doppelten.
- Regeln: derselbe Beitrag in zwei Produktionssammlungen → je Sammlung ein Auftrag; Entfernen und erneutes Speichern → neue Sammlungsaktion nur nach Bestätigung bzw. eingestellter Regel; bewusster Wiederholungsauftrag über „Erneut produzieren“ an der Vorlage.
- Foto, Reel und Karussell vollständig; Neustart setzt am gespeicherten Stand fort ohne Vollimport; abgelaufene Sitzung → „Anmeldung erforderlich“; fehlgeschlagener Medienabruf sichtbar; Zugriffsbeschränkung → Pause und späterer zurückhaltender Versuch. Entfernen aus der Sammlung löscht keine Ergebnisse.

### 9.4 Analyse der Vorlage

| Analyse | Werkzeug (lokal) | Ergebnis |
|---|---|---|
| Szene, Kleidung, Licht, Bildaufbau | Qwen3-VL über ComfyUI `TextGenerate` | Beschreibung |
| Körper-, Hand-, Gesichtspunkte | SDPose (Kern) | Posendaten (Steuerung bzw. Vergleich) |
| Räumliche Anordnung | Depth Anything 3 / MoGe | Tiefenkarte |
| Personen-/Objektbereiche | SAM 3.1 | Masken |
| Video | Szenenschnitte, Ausschnittwahl, SDPose-Sequenz (Analyse/Vergleich), SAM-Videosegmentierung | Steuer- und Prüfdaten; Wan Animate 2 nutzt das Bewegungsvideo direkt |

Unsicherheiten werden gespeichert und markiert; Steuerdaten sind sichtbar und korrigierbar. Gesichtszüge der Vorlagenperson werden nie Teil des Charakterprofils. Jede Vorlage speichert Quelle, Importdatum, Originaldatei, Analyseversion und daraus entstandene Produktionen. **Recht:** Vorlagen fremder Konten dienen als Referenz für Pose, Komposition, Licht und Bewegung; keine 1:1-Kopien, kein Ersetzen realer Personen in fremden Videos; Rechteverantwortung beim Betreiber.

## 10. ComfyUI-Workspaces

Ausgangsgraphen: **offizielle ComfyUI-Vorlagen** (lokal im Paket 0.1.133, öffentlich `github.com/Comfy-Org/workflow_templates/blob/main/templates/<Name>.json`); zusätzlich ausdrücklich gekennzeichnete **Community-Erweiterungen**. Übernahme über die Workflow-Übernahme (7), Präzision je Komponente (Regel 8).

| Workspace | Offizielle Vorlage(n) | Community-Ergänzung | Ergänzung Darkfluenzer |
|---|---|---|---|
| Foto erzeugen | `image_krea2_turbo_t2i`, `image_flux3_klein_t2i` | LUSTIFY v10 (explizit) | Identitäts- und Referenzanschluss |
| Foto nach Vorlage | `image_flux3_klein_image_edit` (Multi-Referenz) | Krea-2-Depth-Control (facok + Depth-Modell), Pose-Adapter nur mit Nachweis | Steuerdaten aus `utility_sdpose_ood_image_to_pose`, `utility_depth_anything3_image_depth_estimation` |
| Foto bearbeiten / Ausziehen | `utility_image_segment_sam3` | LUSTIFY v10 | Inpainting mit `SetLatentNoiseMask` → `ImageCompositeMasked`, Gesicht/Haare ausgespart, Pixelprüfung |
| Foto fertigstellen | `utility_seedvr2_7b_int8_upscale_image` / `…3b…` (Kern) mit bestverfügbarer Präzision | — | A/B nativ (FLUX 3 Klein) gegen Upscaling |
| Foto animieren | `video_ltx2_5_i2v`, `video_ltx2_5_flf2v`, `video_wan2_2_14B_i2v` | Wan 2.2 Remix / NSFW-LoRA | Startbild = freigegebenes Foto |
| Bewegung übertragen | `video_wan_animate2` (Charakterbild + Bewegungsvideo, ohne Posen-Extraktion) | — | Vergleich: `video_wan_vace_14B_v2v` (Wan 2.1 VACE, Kontrollvideo), `video_wan2_2_14B_fun_control` (Posen-/Tiefenvideo) |
| Video fertigstellen | `utility_seedvr2_3b_int8_upscale_video`, `utility_relayvsr_video_x2_upscale` (FP32-Decoder), `utility_video_frame_interpolation` (FILM) | — | A/B; Frame-Integrität |

**Langvideo (vor P7 festzulegen und zu messen):** maximale Länge je Workspace, Ausschnittwahl, zeitliche Fenster und Übergänge (Animate-2-Vorlage verkettet Teilstücke), Bildrate, Audio (LTX liefert Ton, Wan nicht).

## 11. Vergleichsmethode

Gleiche Szenen und Vorgaben je Kandidat, mehrere Ergebnisse je Szene (mindestens 3 Seeds), getrennte Bewertung von **Identität** (Metrik + Sicht), **Referenztreue** (Pose/Komposition/Bewegung) und **Bildqualität** (Haut, Haare, Hände, Anatomie, Licht, zeitliche Konsistenz). Zahlen und Bewertung werden je Paket dokumentiert; mehr Auflösung oder Schritte gelten nur nach Nachweis als besser.

## 12. Pakete und Reihenfolge

Jedes Paket: echte Umsetzung, gezielte Tests, echter Lauf auf dem Mac, Commit und Push auf `main`. **Fertig ist ein Paket erst, wenn der Betreiber es vollständig aus Darkfluenzer bedienen kann, das echte Ergebnis dort sieht und es nach einem Neustart weiterhin korrekt seinem Charakter, seiner Vorlage und seinem Auftrag zugeordnet ist.** Vor jedem Paket mit Downloads: **Speicherbilanz** aus tatsächlichen Dateigrößen plus Download-Zwischenspeicher, Trainingsstände und Video-Zwischenprodukte (aktuell 256 GB frei, Reserve 30 GB).

| # | Paket | Inhalt | Abnahme |
|---|---|---|---|
| 1 | **P0 – Basis prüfen und reparieren** | Speicherverlauf messen; Entladen bei Engine-Wechsel (`comfy.free`, `pipeline.run_render`); MPS-Attention (#14837) an Torch 2.15/ComfyUI 0.45.3 mit Testfall untersuchen, Gegenmaßnahme nur nach Vergleich von Qualität, Speicher, Laufzeit; Remix-Workflow nach Autor-Vorlage (4+4, CFG 1, euler/simple, Shift 8, 81 Frames); Docker nur beenden, wenn keine benötigten Container laufen (derzeit keine) | erstes vollständiges Wan-Video (480p, 81 Frames) mit gemessener Dauer und Speicherverlauf |
| 2 | **I0 – Instagram-Machbarkeit** | Minimale Desktop-Hülle mit Instagram-Ansicht; Sammelkonto anmelden (inkl. Bestätigung); Sammlung wählen; danach **am Handy einen neuen Beitrag speichern**; beim nächsten Abgleich erkennen; Foto, Reel, Karussell übernehmen; Neustart ohne Vollimport; keine Doppelübernahme; abgelaufene Sitzung und fehlgeschlagenen Abruf sichtbar – für Weg (a) und (b) | alle acht Punkte real bestanden; Hauptzugriffsweg festgelegt |
| 3 | **P1 – Auftragsgrundlage und Workflow-Übernahme** | SQLite-Migration Auftrag/Stufe/Produktionsprofil/Vorlage; Parameterbeschreibung; Backend-Validierung; Workspace-Versionen; FIFO ausführbarer Stufen mit Wiederanlauf-Abgleich; Protobuf; **Untergraphen-Übernahme** (Abgleich mit `graphToPrompt`) | jede ausgewählte Vorlage importierbar mit 0 Abweichungen; Auftrag übersteht Neustart; manipulierter Befehl abgewiesen |
| 4 | **P2 – Fotoarbeitsplatz** | Drei-Spalten-Bereich, Warteschlangenleiste, Ablauf A; Krea 2 und FLUX 3 Klein in bestverfügbarer Präzision; manuelle Modellquelle für LUSTIFY v10 | Formular → drei Kandidaten → Auswahl → Dateien |
| 5 | **P3 – Charakterprofil und gemeinsamer Modell-/Identitätsvergleich** | Referenzen, Datensatzprüfung, Prüfsatz, Identitätsmetrik, Training, Paare „Bildmodell + Identitätsmethode“ (normal und explizit: Krea 2/LUSTIFY v10 + LoRA/Referenz vs. FLUX 3 Klein + Multi-Referenz vs. Alternativen); nativ 4K vs. Upscaling | Produktionsmodell(e) und Identitätsprofil gemeinsam freigegeben, Rollen im Manifest besetzt |
| 6 | **P4 – Foto nach Vorlage** | Vorlagenbibliothek (manueller Import), Analyse (9.4), sichtbare Steuerdaten, Referenzübertragung, Vergleich | Vorlage → drei Kandidaten mit eigener Identität und übernommenen Eigenschaften |
| 7 | **P5 – Foto bearbeiten und fertigstellen** | Ablauf C inkl. Ausziehen; Fotoausgabe 4K | Pixelprüfung im Bearbeitungsschritt; 4K-Datei mit korrekten Abmessungen |
| 8 | **D1 – Desktop-App vollständig** | Electron-App ersetzt Swift-Starter (Start, Health, Stopp eigener Prozesse, Idempotenz), Cockpit + isolierte Instagram-Ansicht, Schlüsselbund | S1-Abnahme mit neuer App wiederholt; Instagram-Ansicht dauerhaft angemeldet |
| 9 | **I1 – Instagram-Fotoautomatik** | Connector, Sammlungszuordnung, Abgleich, atomare Auftragserstellung, Regeln 9.3, Status/Fehler | Foto am Handy gespeichert → Vorlage → genau ein Fotoauftrag → wartet auf Auswahl → nach Neustart kein Duplikat |
| 10 | **P0a – macOS 26** | Betreiber aktualisiert vor den Videovergleichen (Sicherung, keine Jobs, DarkBot vorher sichern) | ComfyUI, Referenzrender, Desktop-App, Tests bestanden; LTX Desktop lokal lauffähig |
| 11 | **P6 – Video aus Foto** | Ablauf D freie Animation: LTX 2.5 (Dev vs. Distilled in ComfyUI; LTX Desktop als Vergleich) vs. Wan 2.2 (Remix vs. FP16 + NSFW-LoRA); Langvideo-Regeln; 4K + Interpolation | vollständiger lokaler Videolauf mit Vorschau, Prüfung, Speicherung |
| 12 | **P7 – Bewegungsübertragung** | Wan Animate 2 vs. VACE v2v vs. Fun Control; Ausschnitt, Szenenschnitt, Teilstücke | nachweisbar bessere Referenztreue als freie Animation |
| 13 | **I2 – Instagram-Videoautomatik und Account-Import** | Reels aus Produktionssammlung → Bewegungsübertragung; öffentliches Profil als Vorlagensammlung | Reel am Handy gespeichert → genau ein Videoauftrag; Profilimport ohne Duplikate |
| 14 | **P8 – Gesamtabnahme** | mehrere Aufträge, Neustart, Abbruch, Fehler, Wiederholung, Versionswechsel | alle Fälle real geprüft |

**Offener Rest aus dem vorherigen Auftrag (nicht Teil von P0):** Testergebnis von Job 22 (Verfeinerung von 0024) nach Betreiber-OK löschen.

## 13. Präzisierungen

| Vereinfachte Aussage | Planungsgrundlage |
|---|---|
| Gesicht bleibt immer identisch | Identitätsbindung plus Prüfung; Abweichungen werden zurückgewiesen |
| Gesichtsmetrik prüft den ganzen Charakter | Gesicht, Körper und Gesamtwirkung getrennt bewerten |
| Stichproben jedes achten Frames reichen | Stichproben + zeitliche Prüfung + vollständige Sichtung vor Freigabe |
| Außerhalb der Maske bleibt alles gleich | gilt und wird geprüft im Bearbeitungsschritt |
| Swap muss null sein | Speicherverlauf und Stabilität messen |
| Ein Modell pro Auftrag | eine Engine pro Stufe, kontrolliertes Entladen dazwischen |
| Alles auf BF16/FP16 | Präzision je Komponente, FP32 wo erforderlich |
| Startflag behebt MPS-Korruption | nicht belegt; Testfall und Vergleich entscheiden |
| Vorlage vorhanden = einsatzbereit | erst nach Übernahme, Modellen und echtem Lauf |
| Mehr Auflösung/Schritte = besser | nur durch Vergleich belegt |
| Training immer BF16 | mflux-Training dokumentiert mit 8-Bit-Basis; Generierung BF16 |
