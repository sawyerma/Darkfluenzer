# DARKFLUENZER — PHASENPLAN FRONT V1

**Version:** 1.0 · **Stand:** 14.11.2026  
**Zuständigkeit:** ausschließlich React-Frontend, Bedienbarkeit und typisierter Frontend-/Backend-Vertrag  
**Backend-Gegenstück:** [PHASENPLAN_BACK_V1.md](PHASENPLAN_BACK_V1.md)  
**Status:** SOLL; der bestehende ComfyUI-Starter ist in Betrieb, das React-Cockpit noch nicht implementiert.

> **Dieter Rams / Braun: Weniger, aber besser.** Zeige ausschließlich funktionierende oder klar als nicht angebunden gekennzeichnete Fähigkeiten. Eine Aktion hat genau einen verständlichen Zweck; jeder angezeigte Zustand stammt aus echten Backend-Daten. Keine funktionslosen Platzhalter, künstlichen KPIs, parallelen Dashboards oder dekorativen Module.

## F0 — Architekturentscheidung und Projektunabhängigkeit

**Entscheidung:** Darkfluenzer bekommt **ein React-/TypeScript-/Vite-Frontend im Browser**, kein zweites natives Dashboard und keine eingebettete WebView-App. Der bestehende pinke `C`-Starter bleibt ein dünner, eigenständiger Startmechanismus: Backend/ComfyUI bereitstellen und die lokale Cockpit-URL im Browser öffnen. Das Swift-App-Fenster wird **nicht** zu einer zweiten Funktionsoberfläche ausgebaut.

**DarkBot nur als Vorlage:** Übernehme **eigenständige Kopien** der passenden React-Komponenten, Typografie-/Graphite-Tokens und der binären Protobuf-Realtime-Mechanik. Keine Imports, Symlinks, Prozessaufrufe, Ports, Datenbanken, laufenden Dienste oder Build-Abhängigkeiten zum DarkBot-Repository. Keine Übernahme von Trading-, BSC- oder Solana-Modulen. Projekt-/Protocol-Namespace ausschließlich `darkfluenzer.v1`.

**Eine React-App, drei Hauptansichten:**
1. **Übersicht** — aktuell verfügbare Funktionen, tatsächlicher ComfyUI-/Jobzustand, echte offene Entscheidungen.
2. **Nachrichten** — verfügbare Plattformnachrichten (zuerst Telegram), lesen und antworten; Kunden-/Auftragsdetails in der jeweiligen Konversation.
3. **ComfyUI** — Laufzeit, gerade laufende/ausstehende Jobs, Workflows, Ausgabemedien und **ComfyUI öffnen**. Charaktertraining, Modelle und Tests gehören hier hinein, nicht in eigene Hauptreiter.

Keine separaten Hauptseiten `Qualitätslabor`, `Kanäle`, `Business`, `Studio`, `Einstellungen`, sofern keine echte Benutzeraufgabe diese rechtfertigt. Plattform-Verbindungsstatus und Zahlungs-/Freigabeinformationen sind **Kontextzeilen** in Nachrichten bzw. Übersicht. Für einen späteren nachgewiesenen Bedarf darf ein Reiter per bewusster Designentscheidung ergänzt werden.

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
│   ├── App.tsx                 # Shell + 3 Ansichten
│   ├── pages/
│   │   ├── Overview.tsx
│   │   ├── Messages.tsx
│   │   └── ComfyUI.tsx
│   ├── core/
│   │   ├── realtime.ts        # EIN WebSocket, Hello/Welcome, Heartbeat, Reconnect
│   │   ├── state.ts           # STATE/EVENT-Apply, Cursor, Stale
│   │   ├── commands.ts        # Protobuf-HTTP-Kommandos
│   │   └── generated/         # Ausschließlich generierte *.proto-Typen
│   └── shared/
│       └── graphite.css       # Braun-inspirierte DarkBot-Basiskomponenten
└── tests/                     # Gezielte UI-Tests ohne redundante Testmatrix
```

Kein zweites State-Management-Framework, keine weitere abstrakte Component-Library und keine mehrstufige Layer-Struktur ohne konkreten Fall. Für API-/WS-Zustände reichen kleine fachliche Hooks oder ein minimaler Store. Navigation kann bei nur drei Ansichten simpel bleiben.

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

### ComfyUI
- Aktuelle Instanz: `BEREIT / ARBEITET / GESTOPPT / FEHLER`; Start/Stop nur, wenn Backend die verwaltete Instanz steuern darf.
- Queue und Jobdetails als reale STATE-/EVENT-Daten. Workflows/Modelle aus der Backend-Registry; inaktive Workflows ohne aktiven Renderknopf.
- `ComfyUI öffnen` navigiert in die echte ComfyUI-Oberfläche; dort bleiben die Node-Editoren.
- Ausgabe-Dateien werden mit auftragsbezogener Herkunft (Kundennummer, Auftrag, Master/Variante) angezeigt. **Lokale absolute Pfade nur im autorisierten Operator-Kontext**, keine Kundenpfade über öffentliche Kanäle.
- Charakterbilder unter `local/character/photos/` nur über eine wirkliche Ordneraktion anzeigen; kein Browser-„Drag-and-drop“, das angeblich automatisch trainiert, solange der Backend-Watcher nicht läuft.

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
| **F3 – ComfyUI** | Echte Laufzeit, Jobs/Queue/Outputs, Öffnen/Start/Stop | Mac-/Browser-Test mit einem echten LUSTIFY-Job |
| **F4 – Nachrichten** | Telegram-Konversationen und Antworten aus SQLite/Adapter | Eine echte Testnachricht empfangen und korrekt beantworten |
| **F5 – Freigabe** | Drei echte Kandidaten je Auftrag, Operatorentscheidung, Gate-Anzeige | Ohne Zahlung/Operatorfreigabe keine Versandaktion |
| **F6 – Weitere Kanäle** | Instagram/Fanvue/TikTok/Shop je nur bei tatsächlich freigegebener API | Ein realer Adapter-E2E-Test je angebundenem Kanal; bestehende Kanäle bleiben intakt |

**Kein funktionsloses F6-Menü vor funktionierender Anbindung.** Die Backend-Medienphasen S1–S6 bleiben in [PHASENPLAN_BACK_V1.md](PHASENPLAN_BACK_V1.md) maßgeblich.

### Fortschritt

| Phase | Status | Nachweis |
|---|---|---|
| F1 | PASS | 14.11.2026: `npm run build` (tsc + Vite) grün; ein Stylesheet `src/shared/graphite.css`, vom Build erzwungen (zweite CSS-Datei, Farbe außerhalb `:root`, Inline-Style → Abbruch; beide CSS-Fälle geprüft); Playwright-Smoke 1/1: drei Bereiche, Wechsel, Neuladen, keine Browserfehler. Ansichten zeigen bis F2 nur ihren Titel. |
| F2 | PASS | 14.11.2026: eigene Schemas `protocol/schemas/darkfluenzer/v1` (stream, comfy, commands), `buf lint`/`generate` für TS + Python; `core/realtime.ts`, `core/state.ts`, `core/commands.ts`. Gezielt getestet: Backend 3 Tests (Host/Origin/Sitzung/CSRF; Befehl idempotent je `request_id`; Handshake mit Schema-Konflikt, STATE-Snapshot, EVENT-Catch-up mit Lücke + Live aus echtem SQLite-Journal), Frontend 4 Tests (STATE-Reihenfolge/veraltet, EVENT-Dedupe/Lücke/Journal-Ersatz, Reconnect mit Resume-Cursor, Schema-Konflikt: einmal neu laden, dann BLOCKIERT); Playwright am echten Backend; echter Reconnect im Browser (Backend beendet → GETRENNT, Werte veraltet, Knöpfe gesperrt → Neustart → VERBUNDEN ohne Neuladen). |
| F3–F6 | OFFEN | – |

## Migrationsauftrag

Beim Umbau vom bisherigen Swift-ComfyUI-Starter:
1. Bestehende ComfyUI-/S1-Abnahme und die `local/`-Daten bewahren.
2. Frontend als **eigene Kopie ausgewählter DarkBot-Technik** neu aufsetzen, Branding und Schemas vollständig isolieren.
3. Einen funktionsfähigen React-Build und den eigenen Python-API-Server herstellen.
4. Launcher auf **Cockpit-URL** umstellen, nicht auf externe Browserseiten; `ComfyUI öffnen` erscheint im GUI.
5. Erst anschließend weitere Funktionen einschalten, immer mit echter Backend-Aktion und Status.

**Kein PASS durch die bloße Existenz dieser Spezifikation.**
