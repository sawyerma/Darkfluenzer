# DARKFLUENZER — PHASENPLAN FRONT V1

**Version:** 1.1 · **Stand:** 14.11.2026  
**Zuständigkeit:** ausschließlich React-Frontend, Bedienbarkeit und typisierter Frontend-/Backend-Vertrag  
**Backend-Gegenstück:** [PHASENPLAN_BACK_V1.md](PHASENPLAN_BACK_V1.md)  
**Status:** F1–F3 auf dem Mac abgenommen (PASS); F3a ComfyUI-Bedienung und F3b Dateien als nächster verbindlicher Implementierungsauftrag (OFFEN).

> **Dieter Rams / Braun: Weniger, aber besser.** Zeige ausschließlich funktionierende oder klar als nicht angebunden gekennzeichnete Fähigkeiten. Eine Aktion hat genau einen verständlichen Zweck; jeder angezeigte Zustand stammt aus echten Backend-Daten. Keine funktionslosen Platzhalter, künstlichen KPIs, parallelen Dashboards oder dekorativen Module.

## F0 — Architekturentscheidung und Projektunabhängigkeit

**Entscheidung:** Darkfluenzer bekommt **ein React-/TypeScript-/Vite-Frontend im Browser**, kein zweites natives Dashboard und keine eingebettete WebView-App. Der bestehende pinke `C`-Starter bleibt ein dünner, eigenständiger Startmechanismus: Backend/ComfyUI bereitstellen und die lokale Cockpit-URL im Browser öffnen. Das Swift-App-Fenster wird **nicht** zu einer zweiten Funktionsoberfläche ausgebaut.

**DarkBot nur als Vorlage:** Übernehme **eigenständige Kopien** der passenden React-Komponenten, Typografie-/Graphite-Tokens und der binären Protobuf-Realtime-Mechanik. Keine Imports, Symlinks, Prozessaufrufe, Ports, Datenbanken, laufenden Dienste oder Build-Abhängigkeiten zum DarkBot-Repository. Keine Übernahme von Trading-, BSC- oder Solana-Modulen. Projekt-/Protocol-Namespace ausschließlich `darkfluenzer.v1`.

**Eine React-App, vier Hauptansichten in dieser festen Reihenfolge:**
1. **Übersicht** — aktueller Betriebsstatus und echte offene Entscheidungen; fachliche Feinplanung später.
2. **Nachrichten** — Kunden, Kanäle und Gespräche; fachliche Feinplanung später.
3. **ComfyUI** — eigene Render- und Workflow-Verwaltung, getrennt in **Fotos** und **Videos**, mit Parametern, Testausführung und gezielter Übergabe an den ComfyUI-Node-Editor.
4. **Dateien** — vollständige, chronologische Galerie aller erzeugten Bilder und Videos, mit Kundenname als Bild-/Video-Unterschrift bei Kundenauftrag, sonst fortlaufender Nummer.

Keine weiteren Hauptreiter `Qualitätslabor`, `Kanäle`, `Business`, `Studio`, `Einstellungen`. Plattform- und Zahlungsinformationen bleiben bei Nachrichten/Übersicht. **Jetzt ausschließlich ComfyUI und Dateien spezifizieren und umsetzen; Übersicht und Nachrichten in dieser Runde nicht redesignen.**

## F1 — Minimale Verzeichnisstruktur

```text
frontend/
├── index.html
├── package.json
├── package-lock.json
├── vite.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx
│   ├── App.tsx                 # Shell + 4 Ansichten
│   ├── pages/
│   │   ├── Overview.tsx
│   │   ├── Messages.tsx
│   │   ├── ComfyUI.tsx
│   │   └── Files.tsx
│   ├── core/
│   │   ├── realtime.ts        # EIN WebSocket, Hello/Welcome, Heartbeat, Reconnect
│   │   ├── state.ts           # STATE/EVENT-Apply, Cursor, Stale
│   │   ├── commands.ts        # Protobuf-HTTP-Kommandos
│   │   └── generated/         # Ausschließlich generierte *.proto-Typen
│   └── shared/
│       └── graphite.css       # Braun-inspirierte DarkBot-Basiskomponenten
└── tests/                     # Gezielte UI-Tests ohne redundante Testmatrix
```

Kein zweites State-Management-Framework, keine weitere abstrakte Component-Library und keine mehrstufige Layer-Struktur ohne konkreten Fall. Für API-/WS-Zustände reichen kleine fachliche Hooks oder ein minimaler Store. Navigation bleibt bei vier Ansichten simpel, ohne Router-Framework.

## F2 — Verbindliche GUI-Funktionen und Zustände

### Übersicht
- ComfyUI: `BEREIT / ARBEITET / GESTOPPT / NICHT ERREICHBAR`, Zeitpunkt des letzten gültigen Zustands; niemals eine alte Information als „läuft“ darstellen.
- Offene Betreiberhandlungen nur aus echten Aufträgen, z. B. ein bestimmter Medienvorschlag zur Freigabe, eine unzustellbare Nachricht oder eine Plattform, die erneute Anmeldung verlangt.
- Aktueller Job mit Typ, Fortschritt **nur wenn vom Backend zuverlässig geliefert**, Ausgabereferenz und Link zu ComfyUI.
- Keine erfundenen Kundenzahlen, Umsätze, Lieferungsstatistiken oder Demoaufträge in der produktiven Oberfläche.

### Nachrichten
- Eine Liste tatsächlicher Gespräche, filterbar nach angeschlossener Plattform. **Nicht angebundene Plattformen erscheinen lediglich als „nicht verbunden“, ohne aktive Antwortfläche.**
- Plattform-Kennung, Kundennummer, letzte Nachricht, Lesestatus; Gespräch öffnen → Verlauf aus SQLite/Backend laden.
- Textantwort über genau einen typisierten Backend-Befehl; niemals selbst direkt Telegram-/Instagram-Tokens im Browser verwenden.
- Aus einem Gespräch: Medienwunsch, Bestellung, Zahlung, drei Vorschaumedien und persönliche Freigabe nur anzeigen, wenn die jeweilige Backend-Funktion tatsächlich existiert. Kein separater Kundenreiter.
- Doppelte, fehlgeschlagene und noch nicht versandte Nachrichten korrekt kennzeichnen.

### ComfyUI — vollständige Bedienoberfläche (F3a)

Die vorhandene ComfyUI-Seite (F3 PASS: Laufzeit, Queue, Ergebnisse und reine Workflow-Liste) wird **innerhalb desselben Reiters** zur produktiven Renderbedienung ausgebaut. Das Cockpit ist die primäre Bedienoberfläche. Zum Generieren ist kein Aufruf des ComfyUI-Node-Editors und kein Terminal erforderlich.

**Aufbau und Auswahl**
1. Oben wie bisher: reale Instanz und Start/Stop, Queue und aktueller Status. Keine zusätzlichen Status-/Entwicklerhinweise wie `DEMO · KEIN BACKEND`, `DEMO · OFFLINE` oder technische Erläuterungen als Lauftext. Keine simulierten Kunden, Jobs oder Medien in der produktiven App.
2. Darunter genau zwei gut sichtbare Unterregister **Fotos** und **Videos**. Der Typ stammt ausschließlich aus `manifest.toml` über die Engine-Eigenschaft `kind = "image" | "video"`, **niemals** aus einer hart codierten Workflownamen-Liste.
3. Unter **Fotos** alle registrierten Bild-Workflows (derzeit sieben), unter **Videos** alle registrierten Video-Workflows (derzeit zwei). Jeder Workflow einzeln auswählbar mit lesbarem Namen, Engine, Modellbereitschaft/fehlenden GB, Abnahmestatus und eindeutigem **Aktiviert/Deaktiviert**-Schalter. Fehlende/nicht verifizierte Modelle und gesperrte Workflows bleiben sichtbar, jedoch nicht startbar. `Aktiviert` ist eine Betreiberentscheidung, **kein** Ersatz für Modell-, Lizenz- oder Test-Gates.
4. Nach Auswahl eines Workflows erscheint nur dessen tatsächlich unterstütztes Renderformular: positiver Prompt und **negativer Prompt nur wenn der Workflow ihn deklariert**, dazu Seed, Steps, CFG, Breite/Höhe etc. **nur nach** `workflows.<key>.params` aus der Registry. Unterstützte Vorgaben mit definierten Grenzen und den tatsächlichen Workflow-Defaults vorbelegen. Felder validieren und verständliche Fehler anzeigen; keine nicht unterstützten Parameter erfinden.
5. **Fotoworkflows**: Motiv, Komposition, Perspektive, Licht und bei Inpainting das Quellbild plus Maske; weitere Eingaben nur wenn der Workflow sie vorsieht. **Videoworkflows**: Bewegungs-/Szenenprompt und ggf. Negativ-Prompt; Startbild bei I2V, Kamera-/Bewegungsangaben und zeitliche Parameter (Frames, FPS, Dauer) **nur wenn** sie im registrierten Workflow wirklich steuerbar sind. Kein identisches Fotoformular mit umbenanntem Titel.
6. `Generieren` startet über einen **typisierten Protobuf-Befehl** die **bestehende** Python-Renderpipeline und den exakt ausgewählten API-Workflow. Ein manueller Evaluationsauftrag ist ausdrücklich **ohne** Kundenbezug möglich. Die Backend-Job-ID, FIFO-Position/Status, Fehler und Ausgabe erscheinen als echte STATE/EVENT-Daten; nach Fertigstellung ist die Ausgabe auch unter **Dateien** sichtbar. Keine doppelte Renderengine, kein Frontend-JSON und kein Polling. Mehrere Kundenaufträge und eigene Testaufträge können eingereiht werden; die tatsächliche GPU-Ausführungsreihenfolge ist zentral im Backend autoritativ (FIFO).
7. Jeder Workflow hat außerdem **Öffnen** und **Löschen**. **Öffnen** muss **diesen konkreten** registrierten `.ui.json`-Workflow im echten ComfyUI-Node-Editor laden – bloßes Öffnen der ComfyUI-Startseite genügt **nicht**. Die unterstützte Übergabe für die gepinnte ComfyUI-Version ist real zu implementieren und am Mac nachzuweisen; **keine erfundene URL-Query oder blinde Annahme**, dass ein Link den Workflow lädt. Nach Bearbeitung/Speichern müssen UI- und API-Graph kontrolliert übernommen, gegengeprüft und die Versions-/Herkunftsinformation aktualisiert werden, **bevor** neue Renderjobs den geänderten Workflow verwenden.
8. **Aktivieren/Deaktivieren** persistiert pro Workflow nachvollziehbar über die **einzige** Registry `workflows/manifest.toml` (neues Feld z. B. `enabled`; alter Bestand standardmäßig aktiviert). Deaktivierte Workflows sind weiterhin sichtbar, editierbar und reaktivierbar, aber können keine neuen Jobs starten. Laufende Jobs werden dadurch nicht abgebrochen.
9. **Löschen** hat einen Bestätigungsdialog mit dem genauen Workflownamen; es entfernt **die Registrierung dieses einen Workflows**, die zugehörigen UI-/API-Workflow-Dateien und seinen installierten ComfyUI-Seitenleisten-Eintrag. Keine Löschung bei aktivem/laufendem oder anstehenden Job desselben Workflows. **Modelldateien, Kundenaufträge, historische Renderjobs, erzeugte Medien und Nachweise bleiben unberührt.** Änderungen an den Git-geführten Workflow-Dateien und `manifest.toml` bleiben nachvollziehbar; nach Reload und erneutem Workflow-Install darf der gelöschte Workflow nicht wieder erscheinen. Entfernte Workflows dürfen in historischen Jobs weiterhin anhand gespeicherter Metadaten identifizierbar bleiben.
10. Der Schalter, `Öffnen`, `Löschen` und `Generieren` benutzen denselben vorhandenen Protobuf-Befehlsweg samt Idempotenz. Aktionen werden serverseitig validiert. Laufende Modelldownloads bleiben unberührt; kein automatisches `Download all` aus ComfyUI und keine Installation neben `manifest.toml` vorbei.

**Einzige Registrierungsquelle:** `workflows/manifest.toml` bleibt autoritativ für Engines, Dateien, zulässige Workflow-Parameter, Aktivierung und referenzierte UI-/API-Graphen. Änderungen an dieser Quelle sind kontrolliert atomar zu speichern und dem laufenden Backend ohne konkurrierende Registrierungsdaten bekannt zu machen. Kein zweiter Workflow-Katalog in React/SQLite.

### Dateien — eigenständiger vierter Hauptreiter (F3b)

**Eine einfache Mediengalerie, keine Dateiverwaltungs- oder CRM-Dopplung.**

1. Alle von Darkfluenzer erzeugten Bilder und Videos aus **allen** Renderjobs (manuelle Evaluationen **und** Kundenaufträge) anzeigen, einschließlich aller Kandidaten und Versionen, nicht nur des zuletzt abgeschlossenen Jobs. Auch Ergebnisse direkt in der verwalteten ComfyUI-Instanz gestarteter Workflows erfassen, soweit sie tatsächlich generiert und sicher auffindbar sind; wenn kein Kundenbezug nachweisbar ist, werden sie **ohne Kundenbezug** aufgenommen, niemals einem Kunden geraten zugeordnet. Keine Modelle, Eingabedateien, Downloads oder temporären Teil-Dateien in die Galerie mischen.
2. Vorschauraster mit **Foto/Video**-Filter (zusätzlich **Alle**), chronologisch **neueste zuerst**, Medienkachel anklickbar → großes Bild bzw. abspielbares Video; aus der Detailansicht Öffnen/Herunterladen. Keine fiktiven Thumbnails oder Renderergebnisse.
3. **Bild-/Videounterschrift:** Bei Kundenauftrag **ausschließlich der hinterlegte Kundenname**, ansonsten eine **stabile fortlaufende Nummer** (z. B. `0001`, `0002`). Für die tatsächliche Zuordnung intern unveränderliche Kunden-/Auftrags-/Job-/Artefakt-IDs nutzen; bei fehlendem Namen keine erfundene Identität. Detailinformationen wie Workflow, Seed, Zeit und Herkunft nur nach Öffnen der Datei zeigen, nicht in der Bildunterschrift.
4. Die Galerie ist **persistent über App- und Backend-Neustarts**, dedupliziert nach stabiler Artefakt-ID/Dateiidentität und zeigt keine doppelten Einträge nach Reconnect. Vorhandene Mediendaten aus `local/evaluation/`, den erfassten Kundenartefakten und verwalteten ComfyUI-Ausgaben über **eine Backend-Medienindex-/Datenbank-Projektion** zusammenführen; keine zweite Dateiablage, keine Kopie jeder Grafik nur für die Galerie.
5. Initiale und ältere Galerieeinträge werden **beim Aufruf/Scrollen** paginiert über **Protobuf-Metadaten** geladen. Neue fertige Medien erscheinen per **EVENT über den bestehenden binären WebSocket**, ohne periodisches Frontend-Polling. Die Bild-/Videodaten selbst nur über vorhandene bzw. gezielt erweiterte **sitzungsgeschützte Medien-Endpunkte**, nie als Base64/JSON oder als komplette Dateien im Protobuf-STATE.
6. Renderaufträge behalten ihren bisherigen Kunden-/Herkunftsbezug; ein Datei-Klick aus dem Kundenverlauf und ein Galerie-Klick öffnen **dasselbe** Artefakt. Keine Löschfunktion in dieser Ausbaustufe, da nicht angefordert.

**Geltungsbereich:** Zuerst ComfyUI und Dateien implementieren und am echten Mac abnehmen; **Übersicht und Nachrichten bleiben vorerst funktional wie bisher** und werden gesondert fein ausgearbeitet. Die neue Seitenstruktur darf ihre vorhandenen Funktionen nicht beschädigen.


## F3 — Protobuf-only, Echtzeit ohne Frontend-Polling

**EIN same-origin binärer WebSocket** `/ws/v1/stream` pro Browser-Session; **KEIN JSON** auf der Darkfluenzer-Frontend-/Backend-Schnittstelle. Schemas im eigenständigen `protocol/schemas/darkfluenzer/v1/`; Protobuf-Code mit `buf`/dem gepinnten Generator erzeugen, kein eigener Byte-Codec.

**Nur zwei Datenklassen:**
- `STATE`: vollständige, kleine Projektionen, z. B. `system.status`, `comfy.status`, `jobs.active`, `inbox.summary`. Ordnung nach `(generation, seq)`; bei Reconnect neuer korrekter Snapshot. Kein periodischer Browser-GET.
- `EVENT`: dauerhafte Ereignisse, z. B. `inbox.message`, `job.completed`, `approval.changed`, `delivery.changed`. Eindeutiger Ereignis-/Cursor-Schlüssel, Deduplizierung; Catch-up nach Reconnect, wenn die Backend-Historie dies hergibt.

Handshake `Hello/Welcome` prüft Major-/Minor-Kompatibilität und angebotene Topic-/Payload-Bindungen. Heartbeat/Pong kontrolliert Liveness, Reconnect mit begrenztem Backoff und Jitter. `STALE`, `DETACHED`, `UNAVAILABLE` müssen ehrlich dargestellt werden. Ein nicht vorhandener Publisher bleibt **OFFEN**, kein Fake-Topic. Ein inkompatibles Major oder falsche Payload-Bindung führt zu `BLOCKED`, **kein JSON-Fallback**.

**Benutzeraktionen:** typisierte Protobuf-Kommandos `POST /api/v1/command`, eindeutige `request_id`, idempotente Wirkung, CSRF-/Session-Prüfung. Antwort `ACCEPTED` bedeutet nur „angenommen“; wirkliche Ausführung/Fehler kommt als neuer STATE/EVENT. Alte Chatverläufe und große Medien **auf konkreten Benutzeraufruf** paginiert laden; nur Metadaten und IDs über WS. Bild-/Videobytes nicht im Protobuf-STATE senden. Direkte Medienauslieferung bleibt ausschließlich Backend-Aufgabe.

**Ausnahme:** ComfyUI verwendet intern native JSON-Workflows/HTTP. Nur das **Python-Backend** übersetzt dorthin; das React-Frontend kommuniziert ausschließlich mit dem eigenen Protobuf-API.

## F4 — Updates, Erreichbarkeit, unabhängig von DarkBot

- Ein lokaler Python-HTTP-Server liefert **denselben** gepinnten React-Build und das Protobuf-API auf **einem Origin** aus (z. B. `127.0.0.1:<konfigurierter-port>`).
- `index.html` und nicht gehashte Ressourcen stets revalidieren; gehashte Vite-Assets immutable cachen. Kein unkontrolliertes Auto-Update der App.
- Bei Schema-/Major-Konflikt nach Deployment **maximal einmal** das passende Frontend neu laden. Weiterhin inkompatibel → `BLOCKED` mit klarer Fehlermeldung; keine Endlosschleife.
- Backend-/Frontend-Protokoll zusammen versionieren und in einer Release-Einheit ausliefern; altes Release bleibt bei fehlerhaftem Update wieder startbar.
- Plattform-API-Fehler betreffen ausschließlich den jeweiligen Adapter; UI zeigt `VERBINDUNG ERNEUERN` nur, wenn eine konkrete Aktion implementiert ist.
- Die Swift-Starter-App öffnet die React-URL **erst nach erfolgreichem Backend-Health-Check**. Alte Start-/Stop-Logik nicht duplizieren oder beschädigen.

## F5 — Rams-Regeln auch für Code, Tests und Sicherheit

1. **Weniger, aber besser:** jede Komponente benötigt einen konkreten Funktionsgrund; Dead Code und Platzhalter entfernen.
2. **Keine unnötigen Abstraktionen:** keine generischen Plattform-/Plugin-Frameworks, solange ein realer zweiter Adapter sie nicht benötigt.
3. **Keine Testflut:** gezielte Tests nur für kritische Datenpfade (Protobuf-Handshake, STATE-Reihenfolge, EVENT-Dedupe, Reconnect, Befehl, echte GUI-Bedienung) plus **ein** Frontend-Build/Smoke-Test. Keine hunderten redundanten Testfälle, massenhaften Snapshots oder künstlichen Testschwellen.
4. **Sicherheit proportional zum Risiko:** Same-Origin, Host/Origin/Session-/CSRF-Prüfung für Schreibbefehle, Eingabevalidierung und kein Token im Browser sind Pflicht. Keine zusätzlichen Sicherheitsframeworks, mehrschichtigen Auth-Systeme oder überzogenen Security-Audits ohne konkretes Bedrohungsmodell.
5. **Kein Mock als Fertigstand:** Testfixtures dürfen technische Tests ermöglichen, dürfen aber keine produktive Fähigkeit oder `PASS` behaupten.
6. **Nachweis statt Ritual:** Ein klarer Reconnect-Test ist wertvoller als 40 fast identische Unit-Tests. Testumfang wächst nur bei einem konkreten Fehler/Regression.
7. **Direkt `main` und nachvollziehbarer Commit je geprüftem Paket**, keine zusätzliche Git-Branching-Organisation.

## F6 — Kurze, überprüfbare Frontend-Phasen

| Phase | Lieferung | Minimale Abnahme |
|---|---|---|
| **F1 – Basis** | Eigenständiges React/Vite-Projekt, Graphite-Stil, drei Routen | Build + Browser-Smoke; nur bestehende Funktionen aktiv |
| **F2 – Protokoll** | Eigene Protobuf-Schemas, Socket, Handshake, State/Event/Command | WS-Reconnect, Snapshot, Event-Dedupe, Schema-Konflikt gezielt getestet |
| **F3 – ComfyUI Basis** | Echte Laufzeit, Jobs/Queue/Outputs, Öffnen/Start/Stop | Mac-/Browser-Test mit einem echten LUSTIFY-Job (bereits PASS) |
| **F3a – ComfyUI-Bedienung** | Fotos/Videos getrennt; alle Workflows einzeln auswählen, aktivieren/deaktivieren, öffnen/bearbeiten, löschen; parameterspezifisches Formular und echter Renderstart im Cockpit | Ein echter LUSTIFY-Render komplett aus dem Cockpit; Video-/Fototrennung; kein Start bei fehlenden Modellen oder deaktiviertem Workflow; Öffnen des **richtigen** Graphen im ComfyUI-Editor; persistente Aktivierung und bestätigte Löschung eines entbehrlichen Testworkflows ohne Verlust von Modellen/Artefakten |
| **F3b – Dateien** | Vierter Hauptreiter mit vollständiger Bild-/Videogalerie, Kundenname oder Nummer, Medienvorschau/Download, persistenter Index, paginierte Protobuf-Metadaten und neue Medien als Push | Echte Ausgabe von LUSTIFY im Galerie-Raster, Kundenfall mit richtiger Namensunterschrift, Evaluationsfall mit stabiler Nummer, Video-Filter, Datei nach Neustart weiterhin sichtbar; keine Dubletten nach Reconnect |
| **F4 – Nachrichten** | Telegram-Konversationen und Antworten aus SQLite/Adapter | Eine echte Testnachricht empfangen und korrekt beantworten |
| **F5 – Freigabe** | Drei echte Kandidaten je Auftrag, Operatorentscheidung, Gate-Anzeige | Ohne Zahlung/Operatorfreigabe keine Versandaktion |
| **F6 – Weitere Kanäle** | Instagram/Fanvue/TikTok/Shop je nur bei tatsächlich freigegebener API | Ein realer Adapter-E2E-Test je angebundenem Kanal; bestehende Kanäle bleiben intakt |

**Kein funktionsloses F6-Menü vor funktionierender Anbindung.** Die Backend-Medienphasen S1–S6 bleiben in [PHASENPLAN_BACK_V1.md](PHASENPLAN_BACK_V1.md) maßgeblich.

### Fortschritt

| Phase | Status | Nachweis |
|---|---|---|
| F1 | PASS | 14.11.2026: `npm run build` (tsc + Vite) grün; ein Stylesheet `src/shared/graphite.css`, vom Build erzwungen (zweite CSS-Datei, Farbe außerhalb `:root`, Inline-Style → Abbruch; beide CSS-Fälle geprüft); Playwright-Smoke 1/1: drei Bereiche, Wechsel, Neuladen, keine Browserfehler. Ansichten zeigen bis F2 nur ihren Titel. |
| F2 | PASS | 14.11.2026: eigene Schemas `protocol/schemas/darkfluenzer/v1` (stream, comfy, commands), `buf lint`/`generate` für TS + Python; `core/realtime.ts`, `core/state.ts`, `core/commands.ts`. Gezielt getestet: Backend 3 Tests (Host/Origin/Sitzung/CSRF; Befehl idempotent je `request_id`; Handshake mit Schema-Konflikt, STATE-Snapshot, EVENT-Catch-up mit Lücke + Live aus echtem SQLite-Journal), Frontend 4 Tests (STATE-Reihenfolge/veraltet, EVENT-Dedupe/Lücke/Journal-Ersatz, Reconnect mit Resume-Cursor, Schema-Konflikt: einmal neu laden, dann BLOCKIERT); Playwright am echten Backend; echter Reconnect im Browser (Backend beendet → GETRENNT, Werte veraltet, Knöpfe gesperrt → Neustart → VERBUNDEN ohne Neuladen). |
| F3 | PASS | 14.11.2026, echter Mac + Browser am laufenden Backend: Zustand aus Prozess + `/queue` (BEREIT/ARBEITET/GESTOPPT/STARTET/STOPPT/NICHT ERREICHBAR/FEHLER); Knopf „Stoppen“ → GESTOPPT nach 0,3 s, „Starten“ → BEREIT nach 5,3 s (nur eigene Instanz, Log belegt); echter LUSTIFY-Job (`lustify_sdxl_t2i`, Seed 20261114): ARBEITET + Warteschlange mit Workflow-Name (Job-ID über ComfyUI `extra_data`) + „Aktueller Job“ in der Übersicht, nach 61,0 s Ergebnis live mit Vorschaubild über sitzungsgeschützten Medienpfad; Workflows mit Modellbereitschaft aus der Registry (zeigt laufende Downloads); keine Browserfehler. Rendern aus dem Cockpit noch nicht angeboten (CLI `render`). |
| F3a | OFFEN | Verbindlicher nächster Auftrag: komplette Workflow-Bedienung/Foto-Video-Trennung, Protobuf-Renderbefehl, Enable/Disable, gezieltes Öffnen im Editor und kontrolliertes Löschen. |
| F3b | OFFEN | Vierter Hauptreiter Dateien: alle echten generierten Medien, Kundenname oder laufende Nummer, persistente Galerie, Vorschau/Download, Protobuf-Pagination/Push. |
| F4–F6 | OFFEN | Übersicht/Nachrichten werden später präzisiert; keine vorgezogene UI-Umgestaltung. |

## Implementierungsreihenfolge ab diesem Beschluss

1. **F3a zuerst:** Workflow-Liste in **Fotos/Videos** aufteilen, je Workflow Enable/Disable, Öffnen/Bearbeiten, Löschen und echte Parameterbedienung mit Start über bestehenden Backend-Renderpfad. Für bestehende Workflows die beiden Formulartypen konsequent aus Registry-Spezifikation ableiten.
2. **F3b danach:** vierter Hauptreiter **Dateien**, alle erzeugten Medien aus realem Backend-Index; Kundenname oder stabile Nummer als Beschriftung; Vorschau, Video, Download; paginierte Protobuf-Metadaten und EVENT-Push.
3. Bestehende F1–F3 unverändert funktionsfähig halten; laufende Modelldownloads, `local/`-Daten, Jobs und Launcher nicht unterbrechen. Je Paket gezielter Build/Test, **ein echter Mac-Render**, anschließend Commit und Push direkt auf `main`.
4. **Erst nach F3a/F3b** die fachliche Detailausarbeitung von Übersicht, Nachrichten, kanalübergreifender Kundenakte und LLM-Dialogsteuerung. Kein vorgezogener Umbau in dieser Runde.

## Migrationsauftrag

Beim Umbau vom bisherigen Swift-ComfyUI-Starter:
1. Bestehende ComfyUI-/S1-Abnahme und die `local/`-Daten bewahren.
2. Frontend als **eigene Kopie ausgewählter DarkBot-Technik** neu aufsetzen, Branding und Schemas vollständig isolieren.
3. Einen funktionsfähigen React-Build und den eigenen Python-API-Server herstellen.
4. Launcher auf **Cockpit-URL** umstellen, nicht auf externe Browserseiten; `ComfyUI öffnen` erscheint im GUI.
5. Erst anschließend weitere Funktionen einschalten, immer mit echter Backend-Aktion und Status.

**Kein PASS durch die bloße Existenz dieser Spezifikation.**
