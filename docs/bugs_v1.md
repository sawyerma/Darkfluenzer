# Darkfluenzer – bugs_v1.md

**Stand:** 17.11.2026 · Befundregister zu `docs/PHASENPLAN_BACKEND.md` (B) und `docs/PHASENPLAN_FRONTEND.md` (F); kein dritter Plan.
**Vorfassung:** `docs/archiv/bugs_v1_20261117_vor_neufassung.md` (dort die vollständigen Prüfprotokolle zu BUG-001 bis 006 und die Erstfassungen von BUG-007 bis 046). IDs werden nie neu vergeben oder umnummeriert.
**Prüfbasis:** `main` `7a49b6a`; Backend- und Frontend-Quelltext, Tests, Starter; dazu die Prüfberichte von ChatGPT und Fable (17.11.) und die Läufe am Mac vom 16./17.11. Kein Befund gilt durch diese Liste als reproduziert oder behoben.

## 0. Regeln

1. **Ablauf je Befund:** gegen den aktuellen Code prüfen; Test schreiben, der den Fehler zeigt (rot); korrigieren; Test grün; Normalfall, Fehlerfall und Neustart prüfen; Lauf auf dem echten Mac; Protokollzeile (§6).
2. **Belegstufen:** **CODE** im Quelltext gelesen, kein Lauf · **TEST** durch vorhandenen Test belegt · **LIVE** am laufenden System gesehen · **FREMD** Fremdmeldung, vor der Korrektur im Code bestätigen · **HYPOTHESE** nur ein Lauf entscheidet.
3. **Priorität:** **P0** vor jedem KI-Kanaltest bzw. vor der Default-Abnahme H6 · **P1** vor dem ersten echten Kunden · **P2** danach gezielt · **P3** Pflege.
4. **Status:** OFFEN · BEHOBEN (Code korrigiert, Mac-Nachweis fehlt) · TEIL (Teil am Mac belegt) · PASS (Mac-Nachweis liegt vor) · WIDERLEGT.
5. Tests mit Ersatzobjekten (FakeTd, FakeComfy, Testinstanz) sind Regression, kein Nachweis. Keine künstlichen Daten in der echten Datenbank.
6. Regressionstests: Backend `backend/tests/test_bugs_v1.py` als `test_bugNNN_…` oder im fachlichen Testmodul, Frontend `frontend/tests/`.
7. Spalte „Paket“ verweist auf die Pläne; ein Befund wird im genannten Paket geschlossen. Ein Fix schließt alle verknüpften IDs, jede mit eigenem Testbeleg.
8. Widerspruch zwischen Plan und Code → Eintrag `SPEC-NNN` in §5a, vor der Umsetzung klären.

## 1. P0

| ID | Befund | Beleg | Soll und Abnahme | Paket |
|---|---|---|---|---|
| BUG-047 | **Inhaltsstufe umgehbar.** Die Stufe erbt nur über `parent_media_id`; Upload von Platte, Vorlagen-Eingang und Befehl ohne Eltern-Medium laufen durch `standard`-Workflows (Hochskalieren, Instagram-Export, Bild zu Video) und kommen als `standard` heraus. | CODE | Stufe = höchste Stufe aus Workflow und allen Eingabebildern; Uploads per SHA-256 gegen `media`; unbekanntes Eingabebild in einem abgeleiteten Workflow = `explizit`. Abnahme: explizites Bild über alle Wege → Ergebnis `explizit`, Liefer-Gate sperrt, auch bei manipuliertem Befehl. | B H1 |
| BUG-048 | **Kundenliste, Ungelesen und Übersicht** aktualisieren sich bei bekannten Kunden nicht; EVENT 26 entsteht nur bei neuer Akte. | CODE | EVENT 26 bei jedem Eingang, Versand und Gelesen-Wechsel. Abnahme: zweite Nachricht eines bekannten Kunden erhöht Ungelesen, ohne die Akte zu öffnen. | B H2, F H |
| BUG-049 | **Telegram-Kontowechsel** ohne Neustart: zwei Empfangsthreads lesen dieselbe TDLib-Instanz. | CODE, HYPOTHESE | Genau ein Empfänger je Prozess; alter Client wird geschlossen und abgewartet. Abnahme: abmelden, anmelden, zehn Eingänge genau einmal. | B H2 |
| BUG-050 | **Gutschein-Erkennung** (`payments/vouchers.py`, `extract`) hält normalen Text mit Buchstaben und Ziffern („habe morgen 1830 Zeit“) für einen Code und maskiert ihn; das Original ist verloren. | CODE | Nur eindeutige Muster; Originaltext am Gutschein geschützt speichern (nur im Wallet sichtbar). Abnahme: 20 normale Sätze mit Zahlen bleiben unverändert, echte Codes werden erkannt. | B H2, C5a.4 |
| BUG-051 | **Bezahlter Auftrag kann stecken bleiben:** kein „Neu erzeugen“ bei unbrauchbaren erfolgreichen Kandidaten (`pipeline.retry_stage` nur für Fehlstufen), keine Erstattung per Befehl, nach `delivered` kein Übergang. | CODE | Befehle `order_regenerate`, `order_aftercare`; Zustände `complaint`, `closed`; Erstattung mit Beleg. | B C5.6, C5.8 |
| BUG-052 | **Default-Auftrag ohne Charakterbindung:** weder Influencerin noch Charakter-LoRA am Auftrag; kein Workflow hat einen LoRA-Parameter, die Registry kennt keine trainierten LoRAs. Live 17.11.: Influencerin nicht gesetzt, Charakter 01 mit 0 Bildern. | CODE, LIVE | Auftrag trägt Influencerin, Charakterprofil, LoRA-Version; Workflow lädt die LoRA; bis B1 Karte „ohne Charakter-LoRA“. | B H4, B1 |
| BUG-057 | **Default-Nachricht endet still.** Live 17.11.: „Clone“ → nur Cockpit-Karte „Kein Workflow für clone im Default-Kontakt gewählt“, keine Antwort in Telegram. Dazu: „wartet auf Start“ ohne Chat-Antwort, stiller Rücksprung bei abgeschalteten Befehlen, Rückversand je Freigabeart unklar. | LIVE, TEST | Jede Default-Nachricht endet in genau einem Zustand (gestartet · wartet auf Start · abgelehnt mit Grund · zurückgesendet · Rückversand gesperrt) mit Karte **und** Antwort im selben Chat. | B H4, F H4 |
| BUG-075 | **Referenz aus vorheriger Nachricht wird nicht gefunden.** Live 17.11.: Foto und „Clone“ als zwei Nachrichten (4 s Abstand); `_cloner_plan` nimmt Referenzen nur aus derselben oder einer beantworteten Nachricht und hätte nach dem Bild gefragt. | LIVE, CODE | Letzte Medien desselben Absenders innerhalb `cloner.reference_window_s` (Konfiguration) gelten als Referenz; nie Medien anderer Absender. Abnahme: Foto, dann Befehl → genau ein Auftrag mit diesem Foto. | B H4 |
| BUG-008 | **Render-Worker kann nach einem Job sterben** (`advance_order`, Kloner-Rückversand, Push außerhalb des Fehlerfangs). | CODE | Fehler in jeder Nachbearbeitung auslösen: Worker läuft weiter, kein Job verloren, kein Doppelversand. | B H2 |

## 2. P1

| ID | Befund | Beleg | Soll und Abnahme | Paket |
|---|---|---|---|---|
| BUG-007 | Zeitlimit 3600 s fest in `pipeline.run_render`; Remix-Lauf lag mit 3440 s knapp darunter. | CODE | Zeitlimit je Workflow aus der Registry; Lauf über 3600 s mit Wiederaufnahme. | B H3 |
| BUG-009 | Wallet-Beobachter (`payments/chain.py`, `run`) fängt `TypeError` nicht. | CODE | `null`, Liste statt Objekt, falsche Felder: Beobachter läuft weiter, zeigt Fehler, holt auf. | B C5a.1 |
| BUG-010 | BTC-Adresse in Großbuchstaben: Prüfung akzeptiert, Vergleich unterscheidet Groß/klein. | CODE | Für Vergleich und Abfrage normalisieren. | B C5a.1 |
| BUG-011 | Zuordnung nach Erkennungszeit statt Blockzeit (`store._match_offer`). | CODE | Verspätet gescannte, rechtzeitig bestätigte Zahlung wird zugeordnet; nach Ablauf nicht. | B C5a.1 |
| BUG-013 | Telegram-Anhang bleibt nach Absturz zwischen Speichern und Download `pending`. | CODE | Fortsetzung nach Neustart oder Fehlschlag mit Grund. | B H2 |
| BUG-014 | Telegram sichert die Reihenfolge je Chat nicht; ein Befehl kann die Foto-Nachricht überholen. | CODE | Verarbeitung je Chat nacheinander; Foto mit verzögertem Download, dann Befehl. | B H2 |
| BUG-015 | Telegram-Dienstkonto 777000 kann als Kunde landen. | OFFEN | Keine Akte, kein KI-Dialog, Code nie im Gedächtnis. | B H2 |
| BUG-016 | Versand mit Status `unknown` bleibt hängen; Instagram klärt ihn nur im Speicher, nach Neustart entsteht fälschlich „ÜBERGABE AN BETREIBER“. | CODE | Abgleich dauerhaft über Verlauf/Echo, nie blind zweimal senden, eigene Nachricht nie als Übergabe. | B H2 |
| BUG-017 | Instagram lehnt Bilder über 8 MB ab; keine Zustellkopie; Texte über 1000 Byte nicht geteilt. | CODE | Zustellkopie je Kanalgrenze, nie unter 1K; Text teilen; genau einmal zugestellt. | B C5.7, C5.3 |
| BUG-019 | Angebot wählt das Produkt über den Listenindex. | CODE | Stabile ID je Preisposition, Revisionsprüfung. | B C5.5 |
| BUG-020 | Kundenakte nimmt `influencers[0]` statt der Influencerin des Kontos. | CODE | Influencerin je Kanalkonto und Akte. | B C5.1 |
| BUG-021 | KI-Hinweis nach fehlgeschlagenem oder ungeklärtem Versand nicht fortsetzbar. | OFFEN | Erneuter Versuch möglich, nie doppelt. | B H2 |
| BUG-022 | Alle Engines `evaluation`, Rollen leer; Kundenaufträge prüfen Engine-Freigabe nicht (`_not_startable` prüft nur aktiviert, gesperrt, Dateien). | CODE | Kundenproduktion nur auf freigegebenen Engines mit der LoRA der Figur, auch bei manipuliertem Befehl. | B C5.6 |
| BUG-023 | Krea als `standard` eingestuft ohne Nachweis. | HYPOTHESE | Graph und Testbilder prüfen; Stufe nur mit Beleg. | B C5.6 |
| BUG-024 | Cockpit-Befehle warten ohne Zeitlimit auf die Quittung (`core/commands.ts`, `terminalReceipt`). | CODE | Zeitlimit, danach Zustand über die `request_id` wiederherstellen. | F H |
| BUG-043 | **Abbrechen.** Behoben (`ebbe773`): Abbruch ab Klick, Ergebnis nach Abbruch verworfen, Speicher frei, Pause dauerhaft. Offen: Auftrag als Ganzes, Mehrkandidaten. | TEIL (§7) | Laufender Mehrkandidaten-Auftrag abgebrochen, Warteschlange leer, Journal stimmt. | B H3, F H3 |
| BUG-053 | Kloner legt Aufträge ohne Vorprüfung an (aktiviert, nicht gesperrt, Modelle vorhanden). | CODE | Dieselbe Prüfung wie der Render-Befehl vor der Anlage; sonst Ablehnung mit Grund im Chat. | B H4 |
| BUG-054 | Kloner startet auch Videos mit `production.candidates_default` (3). | CODE | `production.video_candidates_default` (Vorgabe 1). | B H4 |
| BUG-055 | Kloner nutzt nur die erste Referenz (`refs[0]` in `_cloner_order`). | CODE | Mehrere Bilder einer Nachricht laufen als Stapel, je Bild ein Auftrag. Hat der Workflow mehrere Vorlagen-Parameter, werden die Bilder gemeinsam verwendet. | B H4 |
| BUG-056 | Stufe mit genau einem Kandidaten wartet auf manuelle Auswahl (`advance_order`). | TEST | Ein einziger erfolgreicher Kandidat wird automatisch gewählt; bei Freigabeart „automatisch“ folgt die Systemfreigabe (C5.6a). | B H4 |
| BUG-058 | **Video-Parameter uneinheitlich:** LTX `duration` („Länge (s)“) aus dem Manifest, Wan/Remix `duration_s` („Gesamtlänge“) aus dem Backend; das Feld steht je Workflow an anderer Stelle. Betreiber beanstandet 17.11. | TEST, LIVE | Ein Parametervertrag und eine Bedienkomponente für alle Video-Workflows. | B H5, F H5 |
| BUG-059 | KI-Kennzeichnung nur in Metadaten; Plattform-Neukodierung entfernt sie vermutlich; WebP/WebM nicht kennzeichenbar. | CODE, HYPOTHESE | Kennzeichnung muss beim Empfänger ankommen (Begleittext oder Marke); je Kanal real prüfen. | B C5.7 |
| BUG-060 | Angebot setzt ein Krypto-Wallet voraus; Angebotstext fest im Code. | CODE | Zahlungswege als Liste je Influencerin, Text als Vorlage im Profil. | B C5.5, C5a |
| BUG-061 | Starter startet nur die Medien-Instanz; kein Autostart, kein Schutz vor Ruhezustand. | CODE | Beide Instanzen, Autostart, kein Ruhezustand im Betrieb. | B B5.1, D2 |
| BUG-077 | Angebot verlangt die Altersangabe: `server._create_offer` weist ohne `self_declared_adult` ab. Laut E2 entfällt die Altersfrage. (Im Änderungsblatt vom 17.11. als „BUG-075“ geführt; 075 ist bereits vergeben.) | TEST | Bedingung entfernen; die Sperre bei Hinweisen auf Minderjährigkeit bleibt. Test `test_customer_orders` anpassen. | B C5.2 |

## 3. P2

| ID | Befund | Beleg | Soll | Paket |
|---|---|---|---|---|
| BUG-012 | Rest: abgelaufene Angebote nicht sichtbar als abgelaufen. | CODE | Zustand `expired`, keine Aktion mehr. | B C5.5 |
| BUG-025 | Ganzzahl wie `30.0` oder `1e3` scheitert still an `BigInt` (`ComfyUI.tsx`). | CODE | Prüfung vor dem Senden, Fehler am Feld. | F H |
| BUG-026 | Fristen (Angebot, Instagram-Fenster, Telegram-Bremse) altern ohne neues Ereignis nicht mit. | CODE | Zeitgeber im Browser; Backend prüft beim Klick. | F H |
| BUG-027 | Video in der Auftragskarte als `<img>` (`Messages.tsx`). | CODE | Videospieler mit Vorschaubild. | F H |
| BUG-028 | Registry und Festplatte nicht synchron (gemeldet ≈ 196 GB unregistriert). | OFFEN | Nach Größe und SHA prüfen, nichts nach Dateinamen registrieren. | B B4 |
| BUG-029 | `ltx25_fast` zeigt auf ein nicht vorhandenes Distilled-Modell. | OFFEN | Manifest gegen Platte; nur lauffähige Workflows anbieten. | B B4 |
| BUG-030 | Engine-Gates offen trotz bestandener Workflows. | CODE | Gate je Bedingung mit echtem Beleg. | B B4 |
| BUG-031 | Starter vergleicht `comfyui` als Text, das Backend liefert ein Objekt je Instanz. | CODE | Rückgabe je Instanz auswerten. | B H2 |
| BUG-032 | Gutscheincodes unmaskiert im Wallet. | CODE | Maskiert, Aufdecken ausdrücklich, nie an KI oder Logs. | F H |
| BUG-033 | Zuordnen und Einlösen ohne Rückfrage. | CODE | Bestätigung mit Betrag, Kunde, Auftrag. | F H |
| BUG-062 | Bearbeitete, gelöschte, zurückgezogene Kundennachrichten nicht übernommen; bei mehreren Anhängen Text mehrfach (vor Korrektur bestätigen). | CODE | Änderung und Löschung abbilden; Text einmal. | B H2 |
| BUG-063 | Kein Weg, einen kleinen Fehlbetrag anzunehmen. | CODE | Nach E10 (offen): nur mit Bestätigung und Protokoll. | B C5a.3 |
| BUG-064 | Bitgleiches Ergebnis zu einem vorhandenen Medium gilt als „kein Ergebnis“. | CODE | Vorhandenes Medium zählt als Kandidat. | B H3 |
| BUG-065 | Beobachter lädt alle 2 s alle Jobs und Ordner und startet `lsof`/`ps`; jeder Render fragt sekündlich und startet `sysctl`. | CODE | Änderungsbetrieb statt Vollabfrage. | B D2 |
| BUG-066 | `cockpit_restart` prüft nur Renderjobs, nicht laufende Sendungen. | CODE | Sperre auch bei `sending`. | B D2 |
| BUG-067 | `secret set` kennt nur Telegram. | TEST | Ein Katalog für Cockpit und CLI, Instagram und PayPal ergänzt. | B S1 |
| BUG-068 | Zwei Trainingswege: alter diffusers-Trainer neben dem ComfyUI-Trainingsworkflow. | CODE | Alten Weg samt CLI entfernen, wenn B1 belegt ist. | B B1 |
| BUG-069 | Trigger `dfchar`, Klasse `woman` und Beschriftung fest im Code; neuer Trigger erzeugt keine neue Datensatzversion. | CODE, TEST | Felder im Charakterprofil, Teil der Datensatz-ID. | B B1 |
| BUG-070 | Übersicht zählt bezahlte Aufträge in Produktion und Freigabe nicht. | CODE | Eigene Zähler. | F H |
| BUG-071 | Ereignislisten im Browser wachsen unbegrenzt (`state.applyEvent`). | CODE | Begrenzen, älteres seitenweise. | F H |
| BUG-072 | Nachrichten, Wallet, ComfyUI ohne Browser-Test; Smoke klickt Wallet nicht. | CODE | Je Seite ein Browser-Test. | F H |
| BUG-076 | Nach einem Deploy mit Schemawechsel weist das Backend offene Cockpits ab („Frontend-Build passt nicht zum Backend-Schema“); der Betreiber muss selbst neu laden. | LIVE | Cockpit lädt nach Schemawechsel automatisch neu. | B D3, F H |

## 4. P3

| ID | Befund | Soll | Paket |
|---|---|---|---|
| BUG-035 | `config.toml.vor-instagram` lokal mit Rechten 644. | Auf dem Mac prüfen, auf 600 setzen oder nach Rückfrage löschen. | B D2 |
| BUG-036 | `setup_comfyui.sh` trägt keinen Ordner für Bildinterpolation (FILM) ein; Ordner `LLM` und Knotenpaket für das Chatmodell fehlen (vorbereitet: `launcher/setup_llm_session.sh`, `LLM: llm`, noch nicht committet). | Skripte ergänzen, am Mac prüfen. | B B5.1 |
| BUG-037 | Lokale, nicht committete Zeile `enabled = true` in `workflows/manifest.toml`. | Bewusst lokal; nie mit Fachänderungen committen. | – |
| BUG-074 | Dokumente veraltet und widersprüchlich (schließt BUG-034 ein). | Mit DOK-1 am 17.11. erledigt: zwei Pläne + diese Liste, Altdokumente im Archiv. | B DOK-1 |

## 5. Erledigt oder widerlegt

| ID | Stand | Offener Mac-Nachweis |
|---|---|---|
| BUG-001 | BEHOBEN (`ab1d9cf`) | Browser mit echtem Kundenanhang |
| BUG-002 | BEHOBEN, lokal TEIL (17.11. 00:23: Weiterleitungs-Header 403) | echter Tunnel |
| BUG-003 | BEHOBEN (`4f79bfd`) | echter Kanal Telegram und Instagram |
| BUG-004 | BEHOBEN (`018f462`) | echter Rückversand |
| BUG-005 | BEHOBEN (`cd0ff68`) | echte Zahlung |
| BUG-006 | BEHOBEN (`9927140`) | erster Kundenauftrag |
| BUG-038 | PASS: Telegram-Chat ohne Position wird nach Neustart nachgeholt, nur Ungelesenes (`36433c8`, `b4ad0c4`), live 17.11. | – |
| BUG-039 | PASS: Register öffnet bei Ungelesenem nach Neuladen (`b4ad0c4`), live 17.11. | – |
| BUG-040 | BEHOBEN: Name aus Chat-Titel (`e83b7f5`) | Sichtprüfung beim nächsten Eingang |
| BUG-041 | PASS: „Als Default festlegen“ (Befehl 48, `ad82d0d`), Klicktest an Testinstanz, Umzug live per ID-Feld | – |
| BUG-042 | PASS: Seed-Grenzen (`932c9ec`), LTX-Job 64 danach aus dem Cockpit | – |
| BUG-044 | BEHOBEN im Cockpit (Video Standard 1, `ebbe773`); Kloner siehe BUG-054 | Sichtprüfung |
| BUG-045 | **WIDERLEGT** 17.11.: im echten Chrome läuft das LTX-Video (960×1280, `readyState` 4); schwarz war nur Playwrights Chromium ohne H.264 (`MEDIA_ERR_SRC_NOT_SUPPORTED`). | – |
| BUG-046 | PASS 17.11.: Warteschlange angehalten → Neustart → weiterhin angehalten → fortgesetzt | – |
| BUG-012 | Kernaussage WIDERLEGT (Zeitfilter vorhanden); Rest §3 | – |
| BUG-018 | WIDERLEGT: Fensterprüfung im Versandmoment vorhanden (`test_reply_window_refuses_and_human_agent_override`) | echter 24-h-Grenzfall |
| BUG-034 | in BUG-074 aufgegangen | – |

### 5a. Widersprüche Plan ↔ Code (SPEC)

(keine offenen)

## 6. Protokollzeile je Befund

ID · Commit und Datei/Funktion · Behauptung (BESTÄTIGT, TEILWEISE, WIDERLEGT, NICHT REPRODUZIERBAR) · Nachweis (Test, Log) · Ursache · Korrektur-Commit · Regression (Normalfall, Fehlerfall, Neustart, Mehrfachzustellung) · Mac-Lauf (PASS, FAIL, NICHT GELAUFEN) · Bearbeiter, Datum.

**Abschluss:** PASS erst, wenn der Test grün ist, die Änderung auf `main` liegt und der Mac-Lauf belegt ist.

## 7. Prüfprotokoll (ab 17.11.2026)

```text
ID: BUG-043 / BUG-046 (FL-7)
Commit: ebbe773 / server._cancel, server.render_worker, pipeline.run_render, server._pause
Behauptung: BESTÄTIGT (Abbruch vor prompt_id nicht möglich; Ergebnis nach Abbruch übernommen; kein /free;
  Pause nicht dauerhaft)
Nachweis: tests/test_video.py::test_cancel_before_submit_and_result_after_cancel_are_never_done (rot vor der
  Korrektur), tests/test_server.py (Pause gespeichert)
Mac-Lauf 17.11.2026 (Cockpit, echter Chrome): Job 65 nach 0,6 s abgebrochen (bereits übermittelt) → Status
  „Vom Betreiber abgebrochen“, ComfyUI-Queue leer, 0 Medien; Job 66 im Lauf abgebrochen → in 0,2 s
  unterbrochen, 0 Medien, Speicher der Medien-Instanz 2,9 → 1,9 GB; Warteschlange angehalten, Neustart,
  weiterhin angehalten, fortgesetzt
Ergebnis: TEIL (Auftrag als Ganzes offen, H3)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-045
Behauptung: WIDERLEGT
Nachweis: Video von Job 63 im echten Chrome: videoWidth 960, videoHeight 1280, readyState 4, kein Fehler; im
  Playwright-Chromium MEDIA_ERR_SRC_NOT_SUPPORTED (H.264/AAC nicht enthalten)
Folge: Browser-Tests mit Video laufen mit channel "chrome" (FRONTEND §1)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: FL-2 (LTX aus dem Cockpit)
Nachweis: Job 64, gestartet über ComfyUI → Videos → LTX 2.5, Startbild „Aus Dateien“ (0070), 3:4, 5 s, 1 Kandidat;
  780,9 s, Speicher frei 38,6 → min 12,8 GB, Swap max 42,7 GB; Medium 77 in Dateien
Ergebnis: PASS (manuelle Videogenerierung aus dem Cockpit)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-057 / BUG-075 / BUG-052 (Default-Kette, Live-Befund)
Lauf 17.11.2026 09:12: privates Telegram 571334304 (Default) → Foto (Nachricht 38), 4 s später „Clone“
  (Nachricht 39) → nur Systemkarte „Kein Workflow für clone im Default-Kontakt gewählt“ (Nachricht 40), keine
  Antwort in Telegram
Ursachen: Medien-Workflow und Befehlszuordnung leer; Ablehnung nur als Karte; Referenz nur aus derselben oder
  beantworteter Nachricht; keine Influencerin/LoRA
Ergebnis: OFFEN → H4, H6, B1
Bearbeiter/Datum: Claude, 17.11.2026
```
