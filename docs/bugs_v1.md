# Darkfluenzer – bugs_v1.md
**Stand:** 16.11.2026  
**Prüfbasis:** GitHub `main` am Commit `ccf8723298312243bf99eceb67d5ee1a0252f5b9`; Fremdanalyse „Darkfluenzer: Projektüberblick“ (`Eingefügter Text(8).txt`, vom Betreiber übergeben).  
**Zweck:** ALLE gemeldeten Fehler und Abweichungen **unabhängig prüfen**, belegte Ursachen korrigieren und mit echten Tests schließen. **Kein Befund ist durch die Aufnahme in diese Datei als reproduziert oder behoben anzusehen.**

## 0. Prüf- und Bearbeitungsregeln (verbindlich)
1. Die Fremdanalyse ist eine **Meldung**, kein Testnachweis: Ihr Autor hat ausdrücklich **keine Tests ausgeführt**. Aussagen „(geprüft)“ bedeuten dort höchstens Codeprüfung.
2. Zu jedem Eintrag: gegen den **aktuellen** Git-Stand prüfen, exakte Funktions-/Zeilenreferenz und den tatsächlich erreichbaren Aufrufpfad notieren; zuerst reproduzierbaren Fehlerfall erstellen, danach korrigieren, dann Negativ-/Normalfall, Wiederanlauf und relevante End-to-End-Prüfung auf dem **echten Mac** durchführen.
3. Belegstufen: **CODE** = statischer Codebefund sichtbar, Auswirkung noch zu testen; **TEILWEISE** = Kern stimmt, pauschale Aussage überzogen/abhängig; **HYPOTHESE** = erst Lauf-/Konfigtest entscheidet; **WIDERLEGT** = konkrete Aussage durch Gegenbeleg nicht haltbar; **OFFEN** = noch nicht unabhängig geprüft. Keine Stufe bedeutet „TEST PASS“. Ergebnis nach Prüfung mit Datum, Commit, Testbefehl und Mess-/Logbeleg nachtragen.
4. **P0**: vor produktiver Kanal-/Kundennutzung beheben; **P1**: vor verlässlichem Telegram-End-to-End und längeren Renderläufen prüfen/beheben; **P2**: gezielt nach P0/P1; **P3**: Pflege/Abgleich. Keine fachfremde Neuentwicklung aus dem Audit ableiten.
5. Bestehende Projektregeln beachten: **main only**, keine Branches/Worktrees, max. zwei Agenten, NO MOCK, NO LEGACY, FREE ONLY, kein Docker, keine zweite Datenbank, keine neuen Laufzeitdienste. Pro abgeschlossenem Paket Tests → Commit → Push. Produktions-/Live-Zustände niemals mit künstlichen Daten als bestanden deklarieren.
6. **Ausdrücklicher Auftrag an jeden Bearbeiter:** Nicht einfach „alles stimmt“ behaupten. Zu **jedem** Befund entweder **BESTÄTIGT (mit Beleg)**, **TEILWEISE BESTÄTIGT**, **WIDERLEGT (mit Gegenbeleg)** oder **NICHT REPRODUZIERBAR (mit Testnachweis)** eintragen. „Im Code sieht es plausibel aus“ ist keine Abnahme.
7. Änderungen dürfen keine P0-Lücken im Zahlungs-/Freigabe-/Inhaltsstufengate erzeugen. Die geplante isolierte „Cash“-**Testfreigabe** ist von realen Kundenaufträgen und echten Zahlungsdatensätzen strikt zu trennen.

## 1. P0 – Sicherheit, Kanaltrennung, Zahlungswahrheit

### BUG-001 – Gespeicherte Kundenanhänge potenziell als aktiver Inhalt ausführbar
- **Meldung:** Stored XSS über `GET /api/v1/media/{path}`, wenn Kunden `.html`/`.svg`-Anhänge öffnen; kein `nosniff`, keine gesonderte CSP/Download-Erzwingung.
- **Eigene Gegenprüfung:** **CODE** – `backend/src/darkfluenzer/server.py`, `_media` (um Zeilen 2344–2361): `web.FileResponse` für `message_file_known` und Galerie-Dateien; `Content-Disposition: attachment` nur bei `?download=1`. Der hier geprüfte Handler setzt kein `X-Content-Type-Options: nosniff`. Die tatsächliche Ausführbarkeit/CSRF-Kette ist **noch nicht per Browser getestet**.
- **Prüfung:** Gesicherten HTML-/SVG-Testanhang als nicht vertrauenswürdigen Upload laden, mit angemeldeter Sitzung öffnen, tatsächlichen Content-Type/Disposition/CSP und Skriptausführung prüfen; Angriff auf geschützten Testbefehl muss scheitern. Gleiches für Bilder/Videos und legitime Downloads.
- **Soll:** Fremde aktive Anhänge niemals unter derselben vertrauenswürdigen Cockpit-Origin als ausführbares Dokument ausliefern; serverseitig MIME-/Typbindung, `nosniff`, geeignete Sandbox/Download-Trennung. Normaler Medienzugriff bleibt funktionsfähig.
- **Status:** BESTÄTIGT und behoben (Protokoll §7, BUG-001); Browser-Nachweis am laufenden Cockpit nach dem nächsten Deploy.

### BUG-002 – Tunnel könnte lokalen Cockpit-Host-Check umgehen
- **Meldung:** Tunnel verändert Host-Header zu `127.0.0.1:8190`, dadurch könnten statt nur Instagram-/PayPal-Pfaden alle Cockpit-Endpunkte erreichbar werden.
- **Eigene Gegenprüfung:** **HYPOTHESE** – `server.py`, `_host_check` (um 2214): Jeder Request mit Host aus `guard.hosts` wird zunächst durchgelassen, für abweichende Hosts greift die Instagram-Pfadsperre. Ob die Tunnel-Proxykonfiguration den originalen Host erhält, wurde nicht geprüft.
- **Prüfung:** Reale gewählte Tunnelkonfiguration inspizieren; von einem externen Testclient unerlaubte Cockpit-, Medien-, Health-/Login- und Protobuf-URLs anfragen, Host-/Forwarded-Header-Varianten und tatsächliche Bindung beobachten. Erfolgreiche Zugriffe auf nicht freigegebene Pfade sind P0.
- **Soll:** Öffentliche Freigabeliste der exakt benötigten Webhook-/OAuth-/Medienpfade; keine Abhängigkeit allein von einem manipulier-/umgeschriebenen Host-Header.
- **Status:** BESTÄTIGT (für umgeschriebenen Host) und behoben (Protokoll §7, BUG-002); Prüfung mit der echten Tunnelkonfiguration folgt, sobald der Tunnel eingerichtet ist.

### BUG-003 – Interner Default-Rückversand ohne plattformspezifische Inhaltsstufenprüfung
- **Meldung:** Explizite Default-Ergebnisse könnten auf Instagram versandt werden, obwohl Regel 13 sie ausschließlich für Default über Telegram zulässt.
- **Eigene Gegenprüfung:** **CODE** – `server.py`, `_reply_internal` (um 1459): Ziel wird über `conversation_platform(conversation_id)` dynamisch bestimmt, es fehlt vor dem Dateiversand die Prüfung „`explizit` nur Default-Telegram“. Das Kunden-Gate in `approval.py` reicht für diesen internen Sonderpfad nicht aus.
- **Prüfung:** Interner Default-Auftrag mit Testartefakten der Stufen `standard` und `explizit` einmal aus Instagram und einmal aus Telegram; Server/Adapter direkt testen, nicht nur Frontend. Cross-Channel-Daten und echte Ziel-IDs prüfen.
- **Soll:** `explizit` niemals über Instagram, auch nicht für Default. Default-Vollauflösung nur an verifizierte Telegram-ID; gesperrte Sendung sichtbar dokumentieren.
- **Status:** BESTÄTIGT und behoben (Protokoll §7, BUG-003); Kanal-End-to-End mit echtem Telegram/Instagram ausstehend.

### BUG-004 – Kollision der internen KI-Zustellkopien
- **Meldung:** Gleichnamige Quellbilder können eine ältere, falsche Datei erneut versenden.
- **Eigene Gegenprüfung:** **CODE** – `_reply_internal` bildet den Zielpfad aus `src.stem + "_ki" + suffix`, prüft `if not copy.exists()` und markiert eine bestehende Datei nicht neu. Derselbe Name aus unterschiedlicher Herkunft kann kollidieren.
- **Prüfung:** Zwei Dateien mit identischem Basenamen, aber unterschiedlichen Bytes/Hashes nacheinander als Default-Ergebnis zustellen; Hash und tatsächlich empfangene Datei abgleichen, Neustart/Deduplikation mitprüfen.
- **Soll:** Inhaltsadressierte/unveränderliche Zustellkopien je eindeutiger Artefakt-ID/Hash, Herkunft, geprüfter SHA-256; kein falscher Rückversand.
- **Status:** BESTÄTIGT und behoben (Protokoll §7, BUG-004).

### BUG-005 – Manuell zugeordnete Unterzahlung kann als voller Auftragspreis gebucht werden
- **Meldung:** Befehl 41 sowie Amazon-Gutscheine tragen den Preis des Auftrags als bestätigt ein, unabhängig vom tatsächlich eingegangenen Betrag.
- **Eigene Gegenprüfung:** **CODE** – `store.py`, `assign_inflow` (um 1444–1463) ruft `record_payment(order_no, ..., order.price_amount, order.currency)` auf, ohne den Eingangswert in der jeweiligen Zahlungseinheit vorab gegen das Angebot zu verifizieren. `redeem_voucher` sucht ein Angebot mit `price_amount <= amount_cents`; bei manueller Zuordnung eines geringeren Gutscheins/Chain-Eingangs bleibt ein Unterzahlungsfall möglich.
- **Prüfung:** Echter/syntaktisch gültiger Test-Chain-Eingang und eingelöster Testgutschein **unter** Angebotspreis; manuelle Zuordnung, auto Zuordnung, Teilzahlung und andere Währung jeweils getrennt. Prüfen, ob `payments.status=confirmed` und `orders.status=paid` fälschlich entstehen. Kein echter Geldfluss als Test simulieren.
- **Soll:** Nur tatsächlich bestätigter ausreichender Zahlungseingang berechtigt die volle Zahlung; Umrechnung/Kurszeit/Betrag/Asset eindeutig; Differenzen bleiben offen/nicht zugeordnet oder explizit als Teilzahlung erfasst.
- **Status:** OFFEN – Codebefund, Betrags-/Währungsregeln und Tests noch ausstehend.

### BUG-006 – Fehlender Kundenauftragsbezug bei Generierungsjobs
- **Meldung:** Medien eines Kundenauftrags könnten als normale Betreiberdateien erscheinen und durch Galerie-Löschen entfernt werden.
- **Eigene Gegenprüfung:** **CODE/TEILWEISE** – `pipeline.py`, `create_job` (um 209) ruft `store.create_job(None, ... stage_id=stage_id)`; `store.py`, `create_job` legt bei `order_no=None` zunächst `jobs.order_id=NULL` an. `store.register_media` leitet Medienauftrag aus Job-/Artefaktbezug ab, und `remove_media` schützt nur Zeilen mit `media.order_id IS NOT NULL`. **Ob ein späterer `artifact_id`-Pfad den Bezug vor dem Galerieeintrag rettet, muss der End-to-End-Test zeigen.**
- **Prüfung:** Realen Kundenauftrag von `paid` bis Galerieeintrag ausführen, `jobs/order_stages/artifacts/media.order_id` vor/nach Finalisierung kontrollieren; Löschversuch über UI **und** manipulierten Befehl muss abgewiesen werden.
- **Soll:** Auftragsbezug bei Anlage des Jobs und durchgehend bis zu Artefakt und Galerieeintrag; unveränderliche Kundendateien.
- **Status:** OFFEN – Codebefund und möglicher Folgefehler.

## 2. P1 – Zuverlässigkeit und wesentliche Betriebsfehler

| ID | Meldung / eigene Belegstufe | Prüfauftrag / Soll |
|---|---|---|
| **BUG-007** | **Render-Timeout 3600 s – CODE/TEILWEISE.** `pipeline.py:run_render(timeout_s=3600.0)`. Die Behauptung „jeder lange Job bricht nach einer Stunde ab“ hängt von allen Aufrufwegen/Segmentierungen ab. | Call-Graph, ComfyUI-Client und Langvideo-/Trainingspfade prüfen. Zeitlimit pro Workflow/Auftrag konfigurieren oder echte Fortschritts-/Liveness-Semantik; >3600-s-Test mit Wiederaufnahme. |
| **BUG-008** | **Worker kann nach Render-Job sterben – CODE.** `server.py`, Worker um 293–302: `advance_order`, `_cloner_delivery` und Push-Funktionen nach dem `try/except`. | Fehler in jeder Nachbearbeitungsphase gezielt injizieren; Worker muss weiterlaufen oder beaufsichtigt neu starten; keine verlorenen Jobs/Doppelversände. |
| **BUG-009** | **Wallet-Watcher unerwartete RPC-Antwort – CODE.** `payments/chain.py:run` fängt nur `ClientError/TimeoutError/KeyError/ValueError`, nicht `TypeError` bei fehlerhaften Datentypen. | RPC `null`, `None`, Liste statt Objekt, ungültige Felder; Watcher darf nicht dauerhaft sterben, Datenquellenstatus muss Fehler zeigen und später aufholen. |
| **BUG-010** | **BTC-Adresse in Großbuchstaben – TEILWEISE.** `payments/addresses.py:btc_address_error` akzeptiert eine **vollständig großgeschriebene gültige** `BC1...`-Adresse; Aussage „nie erkannt“ ist für die Validierung **widerlegt**. `chain.py:_btc` vergleicht `scriptpubkey_address != addr` jedoch case-sensitiv; reale API kann kleingeschriebene Adresse liefern. | Gültigen uppercase-Bech32-Testvektor gegen Validierung **und** Watcher/Provider-Antwort testen; Adressnormalisierung für Vergleich und API-Abfrage herstellen; kein irreführender P0 ohne Reproduktion. |
| **BUG-011** | **Blockchain-Zuordnung anhand Erkennungszeit – OFFEN/TEILWEISE.** `store.py:_match_offer` prüft `inflow.detected_at` gegen Angebotsfenster, nicht ersichtlich den tatsächlichen Blockzeitpunkt. | Verspätet eingegangenen Scan bei vor Ablauf bestätigter Zahlung und Zahlung nach Ablauf testen; Zeitpunkt aus vertrauenswürdiger Kette, Bestätigungen und Angebot korrekt unterscheiden. |
| **BUG-012** | **„Angebote laufen nie ab“ – als pauschale Aussage WIDERLEGT.** `store.py:_match_offer` enthält `f.expires_at >= inflow.detected_at` und `f.created_at <= inflow.detected_at`. | **Restprüfung:** Wird der abgelaufene Status sichtbar aktualisiert, werden manuelle Aktionen/Angebotsrecycling korrekt blockiert? Keine bereits vorhandene Zeitfensterprüfung entfernen. |
| **BUG-013** | **Telegram-Anhang verbleibt auf pending – OFFEN.** `channels/telegram.py` schreibt Anhänge zunächst als pending, Download folgt danach. | Absturz zwischen Nachrichtenspeicherung, Download und Datei-Aktualisierung; Reconnect muss ausstehende Downloads fortsetzen oder verständlich fehlschlagen, kein endloses pending. |
| **BUG-014** | **Telegram-Nachrichtenreihenfolge je Chat – OFFEN.** Gemeldet: Befehl kann zugehörige Foto-Nachricht überholen. | Zwei schnell aufeinanderfolgende Nachrichten (Foto und Befehl) mit verzögertem Download, Neustart und Dublette testen; serialisierte Entscheidungsreihenfolge je Chat oder korrekte referenzbasierte Zuordnung. |
| **BUG-015** | **Telegram-Konto 777000 als Kunde – OFFEN.** Behauptung aus Fremdanalyse, bisher ohne eigenen Filter-/Betriebstest. | Login-Code-Nachricht im normalen Betriebsmodus: keine normale Kundenakte und keine Weitergabe an Dialog-LLM, Code nicht im Customer-Memory; echte Kunden unverändert. |
| **BUG-016** | **Zustellung mit Status unbekannt bleibt hängen – OFFEN.** | Timeout nach möglicher Plattformannahme simulieren; Status mittels Plattform-ID/History abgleichen, ohne blindes Zweitsenden; bei endgültigem Fehler manueller Retry korrekt. |
| **BUG-017** | **Instagram-Datei zu groß, fehlende Zustellkopie – OFFEN.** | 4K-PNG > Plattformgrenze, Video und dokumentengroße Dateien; automatische geeignete Zustellkopie mit Original-/Hash-/Auflösungsreferenz; Kunde erhält genau einmal. |
| **BUG-018** | **Instagram-Antwortfenster wird nicht serverseitig im Versandmoment geprüft – OFFEN.** | Nachrichten kurz vor/nach 24-h-Grenze, KI-/Operatorantwort, freigegebene Human-Agent-Ausnahme; im Backend abweisen, zeitgebundenen GUI-Status aktualisieren. |
| **BUG-019** | **Angebot wählt Produkt per veränderlichem Listenindex – OFFEN.** | Preisliste zwischen UI-Anzeige und Angebot ändern, Revisionsprüfung/CAS; Preis und Produkt müssen zur tatsächlich bestätigten Position gehören. |
| **BUG-020** | **Kundenakte bindet erste Influencerin statt Kontoprofil – OFFEN.** | Zwei Figuren/Kanalkonten, Wechsel der Auswahl, parallele Anfragen; niemals unbemerkt `influencers[0]` verwenden, stabile per-Kanal-/Kunden-Zuordnung. |
| **BUG-021** | **KI-Ersthinweis nach unbekanntem/fehlgeschlagenem Versand nicht fortsetzbar – OFFEN.** | Versandfehler/Timeout, Neustart, erneuter zulässiger Versuch und Abgleich; kein Doppelhinweis, keine permanent blockierte legitime Unterhaltung. |
| **BUG-022** | **Modellprüfstatus und Eignung zur Laufzeit nicht erzwungen – OFFEN.** | Ein als OFFEN/nicht qualifiziertes Modell im Manifest auswählen bzw. direkten Befehl manipulieren; Backend muss gemäß V0-Freigaben und Inhaltsstufe abweisen. **Lizenz-/kommerzielles Nutzungsrecht separat anhand konkreter Modellkarte prüfen; keine pauschale Aussage ohne Beleg.** |
| **BUG-023** | **Krea-Standardklassifizierung trotz entfernter Prompt-Kleidungsvorgabe – HYPOTHESE.** | Tatsächlichen Workflow-Graphen, Inhaltsstufenherkunft und generierte Testbilder prüfen. Kein automatisches Gleichsetzen `standard` mit nachgewiesener Nicht-Explizitheit. |

## 3. P2 – Frontend, Datenpflege und Qualitätskontrolle

| ID | Meldung / eigene Belegstufe | Prüfauftrag / Soll |
|---|---|---|
| **BUG-024** | **GUI-Befehle ohne Timeout – OFFEN.** | Protobuf-Receipt absichtlich verzögern/verwerfen, Reconnect; kein ewig blockiertes UI, Zustand über request_id wiederherstellen. |
| **BUG-025** | **Ungültige BigInt-Parameter `30.0`/`1e3` – CODE.** `frontend/src/pages/ComfyUI.tsx` um 900 konvertiert Integer-Text direkt mit `BigInt(text)`. | Eingabefehler sichtbar anzeigen und vor Befehl prüfen; echte gültige Ganzzahl-/Negativ-/Grenzfalltests. Kein stilles Scheitern. |
| **BUG-026** | **24-h-/Flood-Wait-Sperren altern ohne Zeitupdate – OFFEN.** | Ablauf ohne neues Push-Ereignis abwarten; React/Backend müssen Entscheidung bei Klick mit aktueller Zeit prüfen, UI nachführen. |
| **BUG-027** | **Video-Kandidaten werden mit `<img>` dargestellt – CODE/TEILWEISE.** `Messages.tsx`, `OrderCard` um 478 verwendet `<img src={resultPath}>`; im ComfyUI-Ergebnisbereich wird Video bereits nach Dateityp behandelt. | Kundenauftrag mit MP4/WebM bis Freigabe, korrekter Videoplayer/Preview, Dateiversand und Wiedergabe. |
| **BUG-028** | **Registry/Festplatte nicht synchron – OFFEN.** Bericht nennt ca. 196 GB unregistrierte Modelle, u. a. FLUX.2, LTX 2.5 Dev, Wan Animate 2, Qwen3.5, FILM. | Tatsächliche Modelldateien auf dem Mac nach Größe/SHA prüfen, gegen `workflows/manifest.toml`/Graphen/Versionsstand vergleichen; kein Registrieren bloß aufgrund Dateinamen. |
| **BUG-029** | **LTX-2.5-Fast zeigt auf nicht vorhandenes Distilled-Modell – OFFEN.** | `[engines.ltx25_fast]` im Manifest gegen tatsächlich vorhandene Datei sowie LTX-Dev/Distilled unterscheiden; nur echte kompatible Workflows anbieten. |
| **BUG-030** | **Gates für sieben Engines OFFEN trotz Teiltests – OFFEN.** | Trainings-, Laden-, Render-, Qualitäts- und Nutzungs-Gates getrennt anhand echter Testbelege prüfen; Gate nur bei bestandener Bedingung aktualisieren, nicht pauschal. |
| **BUG-031** | **Swift-Launcher prüft falschen Datentyp beim Stoppen – CODE.** `launcher/Darkfluenzer.swift`, `stopClicked` um 131 vergleicht `r.json?["comfyui"] as? String` mit `"not_managed"`; gemeldete Runtime-Rückgabe ist pro Instanz ein Dictionary (noch mit echtem CLI-Lauf zu prüfen). | `up/down` mit eigener und fremder Medien-/KI-Instanz; Rückgabeformat wirklich ermitteln und Statusanzeige pro Instanz korrekt auswerten. |
| **BUG-032** | **Amazon-Gutscheincodes unmaskiert in Daten/STATE/Oberfläche – OFFEN.** | SQLite/Protobuf/React-Ansicht auf Offenlegung prüfen; im UI maskiert mit expliziter Anzeige, keine Weitergabe an LLM/Logs und keine unnötigen Klartextkopien. |
| **BUG-033** | **Wallet-Befehle Einlösen/Zuordnen ohne Bestätigungsdialog – OFFEN.** | Prüfen, ob zweistufige Operatorbestätigung tatsächlich fehlt; UI und Backend-Receipt mit Betrags-/Kundenzuordnung testen. |
| **BUG-034** | **Dokumentation veraltet – OFFEN.** | `README.md`, `docs/ki_modelle.md`, FRONT-Fortschritt, V0-B4-Langvideo und C2d-Teilnachweise mit aktuellem Git-Stand und dokumentierten realen Messungen abgleichen. Dokumente nicht als Nachweis ausgeben. |

## 4. P3 – lokale Pflege / Konfiguration

| ID | Gemeldeter Punkt | Prüfung |
|---|---|---|
| **BUG-035** | `config.toml.vor-instagram` lokal mit Dateirechten `644` statt `600` | **Nur auf dem Mac** mit `stat` prüfen; falls geheimnishaltig, Zugriff einschränken. Git allein enthält weder lokale Datei noch Dateirechte als Beweis. |
| **BUG-036** | FILM fehlt in `extra_model_paths.yaml` | **Nur auf dem Mac** ComfyUI-Pfade, Modellregistrierung, echten FILM-Node und Workflow-Ausführung prüfen. |
| **BUG-037** | Nicht committete Änderung `enabled = true` in `workflows/manifest.toml:530` | **Nur auf dem Mac** `git status` und `git diff` prüfen. Aus Remote-Git kann der lokale Dirty-Stand nicht verifiziert werden; kein automatisches Staging ohne Sichtung. |

## 5. Aussagen zum Gesamtstand, ausdrücklich gegenprüfen

Diese Aussagen aus der Fremdanalyse sind **keine Bugs, aber unbewiesene Abnahmen** und dürfen nicht unkritisch als PASS übernommen werden:

- **QA-01 – „Block A ist abgeschlossen“:** Nachweise A1–A4 gegen realen Mac, zweite ComfyUI-Instanz, Protobuf-Rundweg, Wiederanlauf und Dateien abgleichen. Die Existenz von Code ist kein vollständiger Test.
- **QA-02 – „Block C weitgehend gebaut“:** Implementierter Adapter ≠ angemeldetes Telegram/Instagram oder echter End-to-End-Kundenfluss; Status je Paket klar **CODE / LIVE-TEST / PASS** unterscheiden.
- **QA-03 – „Alle lokalen Zahlen stimmen“:** 519 GB Modelle, 19 Workflows, 62 Jobs/61 Medien, Rendering-Zeiten, Swap-Spitzen, 0 echte Kunden und `local/character/photos/` leer sind **lokale Behauptungen**. Nur Mac-Abfrage/Logs beweisen sie.
- **QA-04 – „Keine KI-Modelle geladen“:** B5-Status und KI-Workflowzählung direkt im aktuellen Manifest und auf der lokalen Platte prüfen; nicht aus einem älteren Bericht auf Gegenwart schließen.
- **QA-05 – B4 81-Frame-Segmentierung:** Codepfad und Vollvideo-Nachweis mit Frame-Zählung, Übergängen, Audio und Restart; frischer Commit allein ist noch keine bestandene Abnahme.
- **QA-06 – Sicherheitsbehauptung „zweifaches Gate vollständig sicher“:** `approval.py` und SQLite-Trigger sind vorhanden, aber die oben genannten Sonderpfade und Zahlungsprobleme zeigen, dass ein pauschales Sicherheitsurteil unzulässig ist.

## 6. Prüfprotokoll und Abschlussdefinition

Für jeden BUG die folgende Zeile **nach** Prüfung ergänzen:

```text
ID:
Git-Commit / geprüfte Datei + Zeilen:
Behauptung: BESTÄTIGT | TEILWEISE | WIDERLEGT | NICHT REPRODUZIERBAR
Nachweis: konkreter Codepfad und reproduzierbarer Test (Befehl/Fixture/Logs; keine echten Fremddaten)
Ursache:
Korrektur-Commit:
Regression: Normalfall / Fehlerfall / Neustart / ggf. Mehrfachzustellung
Mac-End-to-End: PASS | FAIL | NICHT GELAUFEN
Bearbeiter/Datum:
```

**Abschluss je Befund:** reproduzierbarer Beleg oder widerlegter Sachverhalt, keine offene Gegenprüfung, Änderung auf `main` gepusht (falls erforderlich), Tests auf echtem Mac bestanden und belegbar. **Nicht gefixte/noch nicht geprüfte Punkte bleiben ausdrücklich OFFEN.**

**Priorität gegenüber dem KI-Studio:** Die tatsächlich bestätigten P0-/relevanten P1-Fehler sollen vor dem Telegram-Kundentest gezielt korrigiert werden; die vereinbarte Produktreihenfolge **Cydonia → KI-Studio → Gedächtnis → Testauftrag → Telegram-Rückversand** bleibt danach unverändert. Keine ungefragten neuen Modellvergleiche oder Infrastrukturpakete.

## 7. Prüfprotokoll

```text
ID: BUG-001
Git-Commit / geprüfte Datei + Zeilen: ab1d9cf / backend/src/darkfluenzer/server.py, _media (Medien-Route)
Behauptung: BESTÄTIGT
Nachweis: tests/test_bugs_v1.py::test_bug001_active_attachments_never_render_in_cockpit_origin – gesicherter
  Kundenanhang evil.html kam mit angemeldeter Sitzung als "text/html" ohne nosniff/CSP/Download zurück
  (rot vor der Korrektur), evil.svg ebenso als aktives Dokument möglich
Ursache: web.FileResponse leitet den Typ aus der Dateiendung ab; Anhänge aus message_files wurden ohne
  Typbindung inline ausgeliefert
Korrektur-Commit: siehe git log "fix(bugs_v1): BUG-001"
Regression: Normalfall (PNG bleibt inline als image/png), Fehlerfall (HTML/SVG/Unbekanntes nur als Download
  application/octet-stream), jede Antwort nosniff + CSP sandbox; tests/test_server.py und
  test_customer_orders.py (Vorschau der Zustellkopie) grün
Mac-End-to-End: NICHT GELAUFEN (Deploy nach dem laufenden LTX-Job 63, dann Browserprüfung)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-002
Git-Commit / geprüfte Datei + Zeilen: abf4be8 / backend/src/darkfluenzer/server.py, _host_check, create_app
Behauptung: BESTÄTIGT (Fall „Tunnel schreibt Host auf 127.0.0.1 um“); öffentliche Ausnutzbarkeit mit der
  realen Tunnelkonfiguration NICHT GEPRÜFT (kein Tunnel eingerichtet)
Nachweis: tests/test_bugs_v1.py::test_bug002_tunnel_never_reaches_cockpit_even_with_rewritten_host – mit
  Host 127.0.0.1 und X-Forwarded-For gab /api/v1/session eine Cockpit-Sitzung samt CSRF-Token heraus (204,
  rot vor der Korrektur)
Ursache: Die Trennung öffentlich/lokal hing allein am Host-Header; die öffentlichen Pfade lagen in
  derselben App wie das Cockpit
Korrektur-Commit: siehe git log "fix(bugs_v1): BUG-002"
Regression: Cockpit lehnt jede Anfrage mit Weiterleitungs-Headern ab (X-Forwarded-*, Forwarded, X-Real-IP,
  CF-*, Tailscale-*, True-Client-IP, Via) und kennt keine öffentlichen Pfade mehr; eigener öffentlicher
  Eingang create_public_app nur mit Webhook/OAuth/signierten Medien auf 127.0.0.1:server.public_port
  (Standard Cockpit-Port + 1, einziges Tunnel-Ziel); Instagram-Tests angepasst, 119 Tests grün
Mac-End-to-End: NICHT GELAUFEN (Deploy nach Job 63; echter Tunneltest nach Einrichtung des Tunnels)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-003
Git-Commit / geprüfte Datei + Zeilen: 4f79bfd / backend/src/darkfluenzer/server.py, Cockpit._reply_internal
Behauptung: BESTÄTIGT
Nachweis: tests/test_bugs_v1.py::test_bug003_explicit_default_return_never_over_instagram – Default mit
  Telegram- und Instagram-Identität; ein Medium der Stufe explizit wurde über die Instagram-Konversation als
  Zustellkopie eingereiht (rot vor der Korrektur)
Ursache: Der interne Rückversand bestimmte das Ziel dynamisch und prüfte die Inhaltsstufe nicht je Plattform;
  das Kunden-Gate (approval.py) gilt für diesen Sonderpfad nicht
Korrektur-Commit: siehe git log "fix(bugs_v1): BUG-003"
Regression: explizit/unbekannt über Instagram gesperrt mit Karte „RÜCKVERSAND GESPERRT … (Regel 13)“ und Hinweis
  im Text; standard über Instagram erlaubt; Default über Telegram erhält explizit weiterhin; Kloner-Tests grün
Mac-End-to-End: NICHT GELAUFEN (Telegram/Instagram noch nicht angemeldet)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-004
Git-Commit / geprüfte Datei + Zeilen: 018f462 / backend/src/darkfluenzer/server.py, Cockpit._reply_internal
Behauptung: BESTÄTIGT
Nachweis: tests/test_bugs_v1.py::test_bug004_same_name_different_content_never_sends_the_wrong_copy – zwei
  Ergebnisse evaluation/a/bild_01.png (rot) und evaluation/b/bild_01.png (blau): für das blaue wurde die rote
  Zustellkopie bild_01_ki.png erneut versendet (rot vor der Korrektur)
Ursache: Kopiename nur aus dem Dateinamen, vorhandene Kopie ohne Prüfung wiederverwendet
Korrektur-Commit: siehe git log "fix(bugs_v1): BUG-004"
Regression: Kopiename = SHA-256-Präfix der Quelle + Name; Wiederverwendung nur, wenn die Kopie gekennzeichnet
  ist; erneuter Versand beider Bilder je richtig; Kloner-/BUG-003-Tests grün. (Kundenzustellung nutzt je
  Auftrag eine eigene Kopie im Auftragsordner – dort keine Kollision.)
Mac-End-to-End: NICHT GELAUFEN (Telegram noch nicht angemeldet)
Bearbeiter/Datum: Claude, 17.11.2026
```

