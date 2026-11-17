# Darkfluenzer – bugs_v1.md

**Stand:** 17.11.2026 · Befundregister zu `docs/PHASENPLAN_BACKEND.md` (B) und `docs/PHASENPLAN_FRONTEND.md` (F); kein dritter Plan.
**Vorfassung:** `docs/archiv/bugs_v1_20261117_vor_neufassung.md` (dort die vollständigen Prüfprotokolle zu BUG-001 bis 006 und die Erstfassungen von BUG-007 bis 046). IDs werden nie neu vergeben oder umnummeriert.
**Prüfbasis:** Code auf `main` ab `7a49b6a`, Planstand nach `d120562` mit Korrektur der Prüfberichte; Backend- und Frontend-Quelltext, Tests, Starter; dazu die Prüfberichte von ChatGPT und Fable (17.11.) und die Läufe am Mac vom 16./17.11. Kein Befund gilt durch diese Liste als reproduziert oder behoben.

## 0. Regeln

1. **Ablauf je Befund:** gegen den aktuellen Code prüfen; Test schreiben, der den Fehler zeigt (rot); korrigieren; Test grün; Normalfall, Fehlerfall und Neustart prüfen; Lauf auf dem echten Mac; Protokollzeile (§6).
2. **Belegstufen:** **CODE** im Quelltext gelesen, kein Lauf · **TEST** durch vorhandenen Test belegt · **LIVE** am laufenden System gesehen · **FREMD** Fremdmeldung, vor der Korrektur im Code bestätigen · **HYPOTHESE** nur ein Lauf entscheidet.
3. **Priorität:** **P0** – die P0-Befunde der Default-Kette sind vor der Abnahme von Etappe C geschlossen; alle übrigen vor dem ersten echten Kunden außerhalb des Testbetriebs (Backend §6, Tore) · **P1** vor dem ersten echten Kunden · **P2** danach gezielt · **P3** Pflege.
4. **Status:** OFFEN · BEHOBEN (Code korrigiert, Mac-Nachweis fehlt) · TEIL (Teil am Mac belegt) · PASS (Mac-Nachweis liegt vor) · WIDERLEGT.
5. Tests mit Ersatzobjekten (FakeTd, FakeComfy, Testinstanz) sind Regression, kein Nachweis. Keine künstlichen Daten in der echten Datenbank.
6. Regressionstests: Backend `backend/tests/test_bugs_v1.py` als `test_bugNNN_…` oder im fachlichen Testmodul, Frontend `frontend/tests/`.
7. Spalte „Paket“ verweist auf die Pläne; ein Befund wird im genannten Paket geschlossen. Ein Fix schließt alle verknüpften IDs, jede mit eigenem Testbeleg.
8. Widerspruch zwischen Plan und Code → Eintrag `SPEC-NNN` in §5a, vor der Umsetzung klären.

## 1. P0

| ID | Befund | Beleg | Soll und Abnahme | Paket |
|---|---|---|---|---|
| BUG-047 | **Inhaltsstufe umgehbar.** Die Stufe erbt nur über `parent_media_id`; Upload von Platte, Vorlagen-Eingang und Befehl ohne Eltern-Medium laufen durch `standard`-Workflows (Hochskalieren, Instagram-Export, Bild zu Video) und kommen als `standard` heraus. | CODE | Stufe = höchste Stufe aus Workflow und allen Eingabebildern; Uploads per SHA-256 gegen `media`; unbekanntes Eingabebild in einem abgeleiteten Workflow = `explizit`. Abnahme: explizites Bild über alle Wege → Ergebnis `explizit`, Liefer-Gate sperrt, auch bei manipuliertem Befehl. | B SP2 |
| BUG-048 | **Kundenliste, Ungelesen und Übersicht** aktualisieren sich bei bekannten Kunden nicht; EVENT 26 entsteht nur bei neuer Akte. | CODE: `store.record_inbound` schreibt nur ein Nachrichtenereignis, `customer_events` liest nur Kundenereignisse | EVENT 26 bei jedem Eingang, Versand und Gelesen-Wechsel. Abnahme: zweite Nachricht eines bekannten Kunden erhöht Ungelesen, ohne die Akte zu öffnen. | B SP2, F SP2 |
| BUG-049 | **Telegram-Kontowechsel** ohne Neustart: zwei Empfangsthreads lesen dieselbe TDLib-Instanz. | CODE: `tdjson._receive` verwirft Ereignisse anderer Clients; nach dem Abmelden laufen zwei Empfangsthreads | Genau ein Empfänger je Prozess; alter Client wird geschlossen und abgewartet. Abnahme: abmelden, anmelden, zehn Eingänge genau einmal. | B SP2 |
| BUG-050 | **Gutschein-Erkennung** (`payments/vouchers.py`, `extract`) hält normalen Text mit Buchstaben und Ziffern („habe morgen 1830 Zeit“) für einen Code und maskiert ihn; das Original ist verloren. | CODE | Nur eindeutige Muster; Originaltext am Gutschein geschützt speichern (nur im Wallet sichtbar). Abnahme: 20 normale Sätze mit Zahlen bleiben unverändert, echte Codes werden erkannt. | B SP2, SP5 |
| BUG-051 | **Bezahlter Auftrag kann stecken bleiben:** kein „Neu erzeugen“ bei unbrauchbaren erfolgreichen Kandidaten (`pipeline.retry_stage` nur für Fehlstufen), keine Erstattung per Befehl, nach `delivered` kein Übergang. | CODE | Befehle `order_regenerate`, `order_aftercare`; Zustände `complaint`, `closed`; Erstattung mit Beleg. | B SP5 (geht in BUG-100 auf; „Neu erzeugen“ vor der Freigabe über `pipeline.regenerate_order`) |
| BUG-052 | **Default-Auftrag ohne Charakterbindung:** weder Influencerin noch Charakter-LoRA am Auftrag; kein Workflow hat einen LoRA-Parameter. (Korrektur 17.11.: trainierte LoRAs trägt der Code bereits über `pipeline._adopt_lora` → `models.register_lora` in die Registry ein; es fehlen LoRA-Parameter in den Workflows und die Bindung am Auftrag.) Live 17.11.: Influencerin nicht gesetzt, Charakter 01 mit 0 Bildern. | CODE, LIVE | Auftrag trägt Influencerin, Charakterprofil, LoRA-Version; Workflow lädt die LoRA; der Trigger wird dem Prompt vorangestellt; die LoRA trägt das Kürzel der Figur; bis SP3 Karte „ohne Charakter-LoRA“. | B SP1 (Bindung), SP3 (LoRA) |
| BUG-057 | **Default-Nachricht endet still.** Live 17.11.: „Clone“ → nur Cockpit-Karte „Kein Workflow für clone im Default-Kontakt gewählt“, keine Antwort in Telegram. Dazu: „wartet auf Start“ ohne Chat-Antwort, stiller Rücksprung bei abgeschalteten Befehlen, Rückversand je Freigabeart unklar. | LIVE, TEST | Jede Default-Nachricht endet in genau einem Zustand (gestartet · wartet auf Start · abgelehnt mit Grund · zurückgesendet · Rückversand gesperrt) mit Karte **und** Antwort im selben Chat. | B SP1, F SP1 |
| BUG-075 | **Referenz aus vorheriger Nachricht wird nicht gefunden.** Live 17.11.: Foto und „Clone“ als zwei Nachrichten (4 s Abstand); `_cloner_plan` nimmt Referenzen nur aus derselben oder einer beantworteten Nachricht und hätte nach dem Bild gefragt. | LIVE, CODE | Letzte Medien desselben Absenders innerhalb `cloner.reference_window_s` (Konfiguration) gelten als Referenz; nie Medien anderer Absender. Abnahme: Foto, dann Befehl → genau ein Auftrag mit diesem Foto. | B SP1 |
| BUG-008 | **Render-Worker kann nach einem Job sterben** (`advance_order`, Kloner-Rückversand, Push außerhalb des Fehlerfangs). | CODE | Fehler in jeder Nachbearbeitung auslösen: Worker läuft weiter, kein Job verloren, kein Doppelversand. | B SP1 |
| BUG-014 | Telegram sichert die Reihenfolge je Chat nicht; ein Befehl kann die Foto-Nachricht überholen. | CODE | Verarbeitung je Chat nacheinander; Foto mit verzögertem Download, dann Befehl. | B SP1 |
| BUG-079 | **Telegram-Alben werden nicht zusammengeführt.** Ein Album besteht aus mehreren Nachrichten mit gemeinsamer `media_album_id`; der Adapter liest die Kennung nicht, verarbeitet wird nur das Bild mit dem Befehl, die anderen werden still ignoriert. (Fables BUG-084 ist derselbe Befund.) | CODE | `album_id` an der Nachricht speichern, Album je Konto, Chat, Absender dauerhaft zusammenführen und erst nach `cloner.album_settle_s` auswerten; Neustart und Dubletten ohne zweiten Auftrag. Abnahme: fünf Bilder als Album → fünf Aufträge, fünf Dateien zurück. | B SP1 |
| BUG-083 | `_on_inbound` fängt nur `PipelineError`, `ComfyError`, `StoreError`. Jeder andere Fehler im Kloner endet ohne Karte und ohne Antwort; die Nachricht wird nicht als gelesen markiert. | CODE | Jede Ausnahme endet im Zustand `failed` mit Karte und Antwort im Chat. | B SP1 |
| BUG-086 | Kloner: bei Fehlschlag oder Abbruch der Stufe bekommt der Default keine Antwort (`_cloner_delivery` sendet nur Ergebnisse). (In Fables SP1-Blatt als „BUG-079“ geführt; 079 ist bereits vergeben.) | CODE | Zustand `failed` oder `cancelled` mit Grund als Karte und im Chat. | B SP1 |
| BUG-089 | **Daueraufgaben ohne Aufsicht:** `outbox_worker`, `adapter.run` und `wallet.run` enden bei einem unerwarteten Fehler still; bis zum Neustart wird nichts mehr gesendet. (In Fables SP2-Blatt als „BUG-086“ geführt; 086 ist bereits vergeben.) | CODE | Aufsicht mit Protokoll, Anzeige im STATE und Neustart. | B SP2 |
| BUG-105 | `Store._migrate` führt Migrationen ohne Sicherung und ohne Integritätsprüfung aus, obwohl die Entwicklungsregeln beides verlangen. (In Fables SP6-Blatt als „BUG-102“ geführt; 102 ist bereits vergeben.) | CODE | Sicherung vor, Prüfung nach jeder Migration. Vor der ersten neuen Migration umsetzen. | B SP0 Schritt 1 |

## 2. P1

| ID | Befund | Beleg | Soll und Abnahme | Paket |
|---|---|---|---|---|
| BUG-007 | Zeitlimit 3600 s fest in `pipeline.run_render`; Remix-Lauf lag mit 3440 s knapp darunter. | CODE | Kein festes Zeitlimit. Ende nur durch Ergebnis, Fehler, Abbruch oder fehlendes Lebenszeichen von ComfyUI; Hinweis statt Abbruch bei Stillstand; Anzeige der geschätzten Dauer. Teil 1 (Zeitlimit raus, Lebenszeichen) umgesetzt 17.11. in 6189956. | B SP1 |
| BUG-009 | Wallet-Beobachter (`payments/chain.py`, `run`) fängt `TypeError` nicht. | CODE | `null`, Liste statt Objekt, falsche Felder: Beobachter läuft weiter, zeigt Fehler, holt auf. | B SP5 |
| BUG-010 | BTC-Adresse in Großbuchstaben: Prüfung akzeptiert, Vergleich unterscheidet Groß/klein. | CODE | Für Vergleich und Abfrage normalisieren. | B SP5 |
| BUG-011 | Zuordnung nach Erkennungszeit statt Blockzeit (`store._match_offer`). | CODE | Verspätet gescannte, rechtzeitig bestätigte Zahlung wird zugeordnet; nach Ablauf nicht. | B SP5 |
| BUG-013 | Telegram-Anhang bleibt nach Absturz zwischen Speichern und Download `pending`. | CODE | Fortsetzung nach Neustart oder Fehlschlag mit Grund. | B SP1 |
| BUG-015 | Telegram-Dienstkonto 777000 kann als Kunde landen. | OFFEN | Keine Akte, kein KI-Dialog, Code nie im Gedächtnis. | B SP2 |
| BUG-016 | Versand mit Status `unknown` bleibt hängen; Instagram klärt ihn nur im Speicher, nach Neustart entsteht fälschlich „ÜBERGABE AN BETREIBER“. | CODE | Abgleich dauerhaft über Verlauf/Echo, nie blind zweimal senden, eigene Nachricht nie als Übergabe. | B SP2 |
| BUG-017 | Instagram lehnt Bilder über 8 MB ab; keine Zustellkopie; Texte über 1000 Byte nicht geteilt: `instagram._parts` lehnt Text über `max_text_bytes` ganz ab. | CODE | Zustellkopie je Kanalgrenze, nie unter 1K; Text teilen; genau einmal zugestellt. | B SP5 (Datei), SP4 (Text) |
| BUG-019 | Angebot wählt das Produkt über den Listenindex. | CODE | Stabile ID je Preisposition, Revisionsprüfung. | B SP5 |
| BUG-020 | Kundenakte nimmt `influencers[0]` statt der Influencerin des Kontos. | CODE | Influencerin je Kanalkonto und Akte. | B SP4 (C5.1) |
| BUG-021 | KI-Hinweis nach fehlgeschlagenem oder ungeklärtem Versand nicht fortsetzbar. | CODE: `queue_ai_notice` sperrt, sobald eine Hinweisnachricht verknüpft ist, auch wenn sie fehlgeschlagen ist | Erneuter Versuch möglich, nie doppelt. | B SP2 |
| BUG-022 | Alle Engines `evaluation`, Rollen leer; Kundenaufträge prüfen Engine-Freigabe nicht (`_not_startable` prüft nur aktiviert, gesperrt, Dateien). | CODE | Kundenproduktion nur auf freigegebenen Engines (`usage = production`, alle Gates nach Backend §9.1) mit der LoRA der Figur, auch bei manipuliertem Befehl; `_not_startable` prüft das bei Kundenaufträgen. | B SP5 |
| BUG-023 | Krea als `standard` eingestuft ohne Nachweis. | HYPOTHESE | Graph und Testbilder prüfen; Stufe nur mit Beleg. | B SP5 |
| BUG-024 | Cockpit-Befehle warten ohne Zeitlimit auf die Quittung (`core/commands.ts`, `terminalReceipt`). Erreicht der Befehl das Backend nie, wartet `useCommand` ewig; der Befehlsstatus lässt sich nicht abfragen. | CODE | Zeitlimit, danach Zustand über die `request_id` wiederherstellen. | B SP2 (Endpunkt), F SP2 |
| BUG-043 | **Abbrechen.** Behoben (`ebbe773`): Abbruch ab Klick, Ergebnis nach Abbruch verworfen, Speicher frei, Pause dauerhaft. Offen: Auftrag als Ganzes, Mehrkandidaten. | TEIL (§7) | Laufender Mehrkandidaten-Auftrag abgebrochen, Warteschlange leer, Journal stimmt. | B SP1, F SP1 |
| BUG-053 | Kloner legt Aufträge ohne Vorprüfung an (aktiviert, nicht gesperrt, Modelle vorhanden). | CODE | Dieselbe Prüfung wie der Render-Befehl vor der Anlage; sonst Ablehnung mit Grund im Chat. | B SP1 |
| BUG-054 | Kloner startet auch Videos mit `production.candidates_default` (3). | CODE | `production.video_candidates_default` (Vorgabe 1). | B SP1 |
| BUG-055 | Kloner nutzt nur die erste Referenz (`refs[0]` in `_cloner_order`). | CODE | Mehrere Bilder einer Nachricht laufen als Stapel, je Bild ein Auftrag. Hat der Workflow mehrere Vorlagen-Parameter, werden die Bilder gemeinsam verwendet. | B SP1 |
| BUG-056 | Stufe mit genau einem Kandidaten wartet auf manuelle Auswahl (`advance_order`). | TEST | Ein einziger erfolgreicher Kandidat wird automatisch gewählt; bei Freigabeart „automatisch“ folgt die Systemfreigabe (C5.6a). | B SP1 |
| BUG-058 | **Video-Parameter uneinheitlich:** LTX `duration` („Länge (s)“) aus dem Manifest, Wan/Remix `duration_s` („Gesamtlänge“) aus dem Backend; das Feld steht je Workflow an anderer Stelle. Betreiber beanstandet 17.11. | TEST, LIVE | Ein Parametervertrag und eine Bedienkomponente für alle Video-Workflows. | B SP1, F SP1 |
| BUG-059 | KI-Kennzeichnung nur in Metadaten; Plattform-Neukodierung entfernt sie vermutlich; WebP/WebM nicht kennzeichenbar. | CODE, HYPOTHESE | Kennzeichnung muss beim Empfänger ankommen (Begleittext oder Marke); je Kanal real prüfen. | B SP5 |
| BUG-060 | Angebot setzt ein Krypto-Wallet voraus; Angebotstext fest im Code; `offer_amounts.method` erlaubt nur Krypto; die Gültigkeit steht in `wallet.offer_valid_min`; `store.create_offer` legt jeden Auftrag als `image` an. | CODE | Zahlungswege als Liste je Influencerin, Text als Vorlage im Profil. | B SP5 |
| BUG-061 | Starter startet nur die Medien-Instanz; kein Autostart, kein Schutz vor Ruhezustand; `cockpit_up` startet den Server losgelöst, stirbt er, startet ihn niemand neu. | CODE | Beide Instanzen, Autostart, kein Ruhezustand im Betrieb. | B SP4 (KI-Instanz), SP6 (Dienst) |
| BUG-090 | Die Fertigstellen-Stufe trägt keine Parameter (`pipeline.select_candidate` ruft `create_render` mit leeren Werten). Die Höhe für das Story-Format lässt sich so nicht setzen; ein Video-Kundenauftrag scheitert, weil `ltx25_i2v` als Fertigstellen den Pflichtwert `prompt` braucht. | CODE | Werte für die Fertigstellen-Stufe am Auftrag. | B SP1 (Story), SP5 (Video) |
| BUG-094 | LoRA nur in Workflows mit demselben Engine-Eintrag ladbar (`models.engine_model_names` vergleicht `base_engine`). `lustify_sam31_edit` nutzt dasselbe Modell unter anderem Eintrag und dürfte die Charakter-LoRA nicht laden. (In Fables SP3-Blatt als „BUG-089“ geführt; 089 ist bereits vergeben.) | CODE | Bindung an die Architektur (`arch`). | B SP3 |
| BUG-095 | Jeder Workflow-Lauf prüft die Instanz über `runtime.start`, ruft zweimal `git` auf (`comfy.provenance`), fragt im Sekundentakt ab und schreibt eine Herkunftsdatei. Für Chat-Antworten ist das zu schwer. | CODE | Leichter Weg ohne diese Schritte (`llm.generate`). | B SP4 |
| BUG-096 | Telegram: Tippanzeige nur einmal gesendet, Online-Status nie gesetzt, Gelesen sofort nach dem Speichern. | CODE | Verhalten nach Profil. | B SP4 |
| BUG-097 | Eine eingereihte Antwort lässt sich nicht stornieren: `channel_messages.status` kennt weder `draft` noch `cancelled`, der Postausgang kennt keine Sendezeit. | CODE | Tabellenumbau, `scheduled_at`, Storno bei neuem Eingang. | B SP4 |
| BUG-098 | `comfy.collect_graph` kennt nur Datei-Ausgaben; ein Textergebnis endet mit „keine Ausgabedatei“. (In Fables SP4-Blatt als „BUG-094“ geführt; 094 ist bereits vergeben.) | CODE | Eigener Textweg in `llm.py`. | B SP4 |
| BUG-099 | Zustellung immer als Dokument und ohne Text (`_queue_delivery`, `telegram._send`). E7 verlangt Foto oder Video als Standard mit Begleittext. | CODE | Anhangart aus dem Produkt, Begleittext aus der Vorlage. | B SP5 |
| BUG-100 | Nach `delivered` gibt es keinen Übergang (`store.TRANSITIONS`), auch nicht zu `refunded`; der Index `deliveries_one_per_order` erlaubt eine Lieferung je Auftrag. Neuauflage und Erstattung nach der Zustellung sind unmöglich. | CODE | Übergänge ergänzen, Index je Auftrag und Artefakt. | B SP5 |
| BUG-101 | Die Render-Warteschlange ist reines FIFO (`asyncio.Queue`); ein bezahlter Kundenauftrag wartet hinter Default-Stapel und Training. | CODE | Vorrang je Job. | B SP5 |
| BUG-102 | Der öffentliche Eingang (`create_public_app`, `serve`) entsteht nur mit Instagram-Konfiguration; ein PayPal-Webhook ohne Instagram ist nicht erreichbar. (In Fables SP5-Blatt als „BUG-098“ geführt; 098 ist bereits vergeben.) | CODE | `[server] public_base_url` unabhängig von Instagram. | B SP5 |
| BUG-080 | Kloner im Modus „Direkt“: nach dem Rückversand wartet die Stufe weiter auf Auswahl, der Auftrag bleibt offen; „Stufe wiederholen“ sendet alle Dateien erneut. | CODE | Auftrag schließt nach dem Rückversand; Rückversand je Medium genau einmal (`cloner_returns`). | B SP1 |
| BUG-081 | Kloner verlangt immer `candidates_default` Kandidaten; Workflows ohne Seed lehnt `create_order` dann ab (z. B. Export). | CODE | Ein Kandidat bei Workflows ohne Seed; Default-Produktion `production.cloner_candidates` (Vorgabe 1). | B SP1 |
| BUG-082 | Rückversand an den Default wartet Antwortverzögerung und Tippzeit ab (`telegram._pace`) und steht hinter Kundensendungen. | CODE | Interne Sendungen sofort und zuerst. | B SP1 |
| BUG-085 | Die Zulassung (`_admit`) entlädt für jeden Medienjob die ruhende andere Instanz, also auch Melody. | CODE | Instanz als „bleibt geladen“ markierbar; Regel für Chat neben Video (E15). | B SP4 |
| BUG-077 | Angebot verlangt die Altersangabe: `server._create_offer` weist ohne `self_declared_adult` ab. Laut E2 entfällt die Altersfrage. (Im Änderungsblatt vom 17.11. als „BUG-075“ geführt; 075 ist bereits vergeben.) | TEST | Bedingung entfernen; die Sperre bei Hinweisen auf Minderjährigkeit bleibt: `customers.age_mark` kennt bereits `under_18`, dieser Wert trägt die Sperre, `_create_offer` prüft künftig nur noch darauf. Test `test_customer_orders` anpassen. | B SP4 |

## 3. P2

| ID | Befund | Beleg | Soll | Paket |
|---|---|---|---|---|
| BUG-012 | Rest: abgelaufene Angebote nicht sichtbar als abgelaufen. | CODE | Zustand `expired`, keine Aktion mehr. | B SP5 |
| BUG-025 | Ganzzahl wie `30.0` oder `1e3` scheitert still an `BigInt` (`ComfyUI.tsx`). | CODE | Prüfung vor dem Senden, Fehler am Feld. | F SP2 |
| BUG-026 | Fristen (Angebot, Instagram-Fenster, Telegram-Bremse) altern ohne neues Ereignis nicht mit. | CODE | Zeitgeber im Browser; Backend prüft beim Klick. | F SP2 |
| BUG-027 | Video in der Auftragskarte als `<img>` (`Messages.tsx`). | CODE | Videospieler mit Vorschaubild. | F SP2 |
| BUG-028 | Registry und Festplatte nicht synchron (gemeldet ≈ 196 GB unregistriert). | OFFEN | Nach Größe und SHA prüfen, nichts nach Dateinamen registrieren. | B B4 |
| BUG-029 | `ltx25_fast` zeigt auf ein nicht vorhandenes Distilled-Modell. | OFFEN | Manifest gegen Platte; nur lauffähige Workflows anbieten. | B B4 |
| BUG-030 | Engine-Gates offen trotz bestandener Workflows. | CODE | Gate je Bedingung mit echtem Beleg. | B B4 |
| BUG-031 | Starter vergleicht `comfyui` als Text, das Backend liefert ein Objekt je Instanz. | CODE | Rückgabe je Instanz auswerten. | B SP2 |
| BUG-032 | Gutscheincodes unmaskiert im Wallet. | CODE | Maskiert, Aufdecken ausdrücklich, nie an KI oder Logs. | F SP2 |
| BUG-033 | Zuordnen und Einlösen ohne Rückfrage. | CODE | Bestätigung mit Betrag, Kunde, Auftrag. | F SP2 |
| BUG-062 | Bearbeitete, gelöschte, zurückgezogene Kundennachrichten nicht übernommen; bei mehreren Anhängen Text mehrfach (vor Korrektur bestätigen). | CODE | Änderung und Löschung abbilden; Text einmal. | B SP2 |
| BUG-063 | Kein Weg, einen kleinen Fehlbetrag anzunehmen. | CODE | Nach E10 (offen): nur mit Bestätigung und Protokoll. | B SP5 |
| BUG-064 | Bitgleiches Ergebnis zu einem vorhandenen Medium gilt als „kein Ergebnis“. | CODE | Vorhandenes Medium zählt als Kandidat. | B SP1 |
| BUG-065 | Beobachter lädt alle 2 s alle Jobs und Ordner und startet `lsof`/`ps`; jeder Render fragt sekündlich und startet `sysctl`. | CODE: `runtime.status` ruft je Runde und Instanz `lsof` und zweimal `ps` auf | Änderungsbetrieb statt Vollabfrage. | B SP6 |
| BUG-066 | `cockpit_restart` prüft nur Renderjobs, nicht laufende Sendungen; der Neustart wird bei jedem wartenden oder laufenden Renderjob verweigert, obwohl eingereichte Jobs einen Neustart überstehen. | CODE | Sperre auch bei `sending`. | B SP6 |
| BUG-067 | `secret set` kennt nur Telegram. | TEST | Ein Katalog für Cockpit und CLI, Instagram und PayPal ergänzt. | B SP2 |
| BUG-068 | Zwei Trainingswege: alter diffusers-Trainer neben dem ComfyUI-Trainingsworkflow. | CODE | Alten Weg samt CLI entfernen, wenn B1 belegt ist. | B SP3 |
| BUG-069 | Trigger `dfchar`, Klasse `woman` und Beschriftung fest im Code; neuer Trigger erzeugt keine neue Datensatzversion. Die Klasse `woman` ist für männliche Figuren falsch. `MIN_SIDE`, `MIN_IMAGES`, `SETTLE_S` und die Trainingsformate stehen fest in `training.py`. | CODE, TEST | Trigger und Klasse im Charakterprofil, Teil der Datensatz-ID. | B SP3 |
| BUG-070 | Übersicht zählt bezahlte Aufträge in Produktion und Freigabe nicht. | CODE | Eigene Zähler. | F SP2 |
| BUG-071 | Ereignislisten im Browser wachsen unbegrenzt (`state.applyEvent`). | CODE | Begrenzen, älteres seitenweise. | F SP2 |
| BUG-072 | Nachrichten, Wallet, ComfyUI ohne Browser-Test; Smoke klickt Wallet nicht. | CODE | Je Seite ein Browser-Test. | F SP2 |
| BUG-078 | Zwei Ordnerschemata: Profil 1 liegt unter `local/character/`, weitere unter `local/characters/<nr>/`; Datensätze liegen im Unterordner `dataset`, der Plan nennt `datasets`. (Im B1-Änderungsblatt als „BUG-076“ geführt; 076 ist bereits vergeben.) | TEST | Ein Schema `local/characters/<kürzel>/` mit Migration. | B SP3 |
| BUG-076 | Nach einem Deploy mit Schemawechsel weist das Backend offene Cockpits ab („Frontend-Build passt nicht zum Backend-Schema“); der Betreiber muss selbst neu laden; `realtime.ts` lädt bei abgewiesenem Schema genau einmal neu und bleibt danach gesperrt. | LIVE | Cockpit lädt nach Schemawechsel automatisch neu. | B SP6, F SP6 |
| BUG-087 | `keychain.store_secret` lehnt Werte mit `"`, `\` oder Zeilenumbruch still ab. | CODE | Kodieren oder klare Meldung. | B SP2 |
| BUG-088 | `default_contact` führt je Plattform nur eine Absender-ID; mehrere Konten derselben Plattform kollidieren. | CODE | Default-Identität je Konto. | B SP2 |
| BUG-091 | Die Gesichtsmodelle `face_yunet`, `face_sface`, `face_auraface` gehören zu keiner Engine; Bereitschaft und Download sind nirgends sichtbar. `identity.py` hat keinen Aufrufer. | CODE | Engine `identity`; Einbindung in SP3. | B SP3 |
| BUG-092 | Lokaler Zustand steht im versionierten `workflows/manifest.toml`: LoRA-Einträge (`register_lora`) und der Schalter `enabled`. Ursache von BUG-037. | CODE | Nicht versionierte `local/registry.toml`. | B SP3 |
| BUG-093 | Die Wan-Engines haben keine `formats`; die einheitliche Videosteuerung hat dort keine benannten Formate. | CODE | Formate im Manifest ergänzen. | B SP1 |
| BUG-103 | Plattenverbrauch: jede Ausgabe liegt in ComfyUIs `output/` und in `local/evaluation/`; `darkfluenzer_work/job<id>` und hochgeladene Eingaben werden nie aufgeräumt. | CODE | Aufräumen nach Übernahme und Frist. | B SP6 |
| BUG-106 | Schwere Arbeit im Hauptstrang: `_reply_internal` hasht und kennzeichnet Dateien synchron; lange Datenbankabfragen laufen dort ebenfalls. | CODE | Arbeiter-Threads; Messwert für die Verzögerung. | B SP0 |
| BUG-107 | `pipeline.media_candidates` liest je Beobachterrunde alle abgeschlossenen Jobs (`finished_jobs(0, 1_000_000)`); `add_media` bildet je Eintrag das Maximum über das Journal. (In Fables Blatt als „BUG-105“ geführt; 105 ist bereits vergeben.) | CODE | Position merken, Index, Zählertabelle. | B SP0 |

## 4. P3

| ID | Befund | Soll | Paket |
|---|---|---|---|
| BUG-035 | `config.toml.vor-instagram` lokal mit Rechten 644. | Auf dem Mac prüfen, auf 600 setzen oder nach Rückfrage löschen. | B SP6 |
| BUG-036 | `setup_comfyui.sh` trägt keinen Ordner für Bildinterpolation (FILM) ein; Ordner `LLM` und Knotenpaket für das Chatmodell fehlen (vorbereitet: `launcher/setup_llm_session.sh`, `LLM: llm`, noch nicht committet). | Skripte ergänzen, am Mac prüfen. | B SP4 |
| BUG-037 | Lokale, nicht committete Zeile `enabled = true` in `workflows/manifest.toml`. | Bewusst lokal; nie mit Fachänderungen committen. Ursache: BUG-092 (lokaler Zustand im versionierten Manifest). | B SP3 |
| BUG-104 | Logs werden nur beim Start rotiert; `server.log` und `app.log` wachsen im Dauerbetrieb. | Rotation nach Größe. | B SP6 |
| BUG-074 | Dokumente veraltet und widersprüchlich (schließt BUG-034 ein). | Konsolidierung am 17.11. erledigt (zwei Pläne + diese Liste, Altdokumente im Archiv); Widersprüche aus den Prüfberichten von ChatGPT und Fable am 17.11. korrigiert (SPEC-001 bis 007). Abschluss mit der Betreiberfreigabe. | B DOK-1 |

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
| BUG-073 | nicht vergeben (Lücke aus Fables Nummerierung) | – |

### 5a. Widersprüche Plan ↔ Code (SPEC)

Im Plan entschieden; die Umsetzung schließt sie im genannten Paket.

| ID | Code heute | Plan | Paket |
|---|---|---|---|
| SPEC-001 | Liefer-Gate und Trigger verlangen bestätigte Zahlung | Testaufträge sind Aufträge der internen Akte; Gate und Trigger verzichten auf die Zahlung nur unter den fünf Bedingungen von SPEC-008, ohne künstliche Zahlung | SP5 |
| SPEC-002 | ein Konto je Plattform (`server.telegram`, `server.instagram`, `[telegram_account]`, `[instagram]`) | Kanalkonten als Liste mit eigenem Adapter je Konto | S1 |
| SPEC-003 | Freigabe nur durch den Betreiber (`approval.py`) | Systemfreigabe mit Prüfwerten in einer Transaktion, Liefer-Gate prüft vor dem Versand erneut | C5.6a |
| SPEC-004 | Angebot verlangt `self_declared_adult` (`server._create_offer`) | keine Altersfrage (E2); Befehl 44 nur noch Sperre „minderjährig vermutet“ | C5.2 (BUG-077) |
| SPEC-005 | Engine-Gate `license_pass` im Code | Betreiber setzt es nach Dokumentation im Manifest; kein Auswahlkriterium (Regel 6) | Backend §9.1 |
| SPEC-006 | zwei Ordnerschemata für Charaktere | ein Schema `local/characters/<kürzel>/` mit sicherer Migration | B1 (BUG-078) |
| SPEC-007 | Anhang A (F7) enthält überholte Aussagen | im Kopf des Anhangs gelistet und inline mit [17.11.] markiert | DOK-1 |

Plan-Korrekturen nach der Prüfung der Sammelpakete (Fable, 17.11.; dort als SPEC-001 bis 008 geführt):

| ID | Stelle | Befund | Korrektur |
|---|---|---|---|
| SPEC-008 | SP5 Schritt 12 | Die Zahlungsausnahme für Tests war nur an `kind = internal` gebunden. | Fünf Bedingungen (`orders.test`, interne Akte, Ursprungskonversation, verifizierte Default-Identität, Betriebsart `test`) samt Trigger. |
| SPEC-009 | SP2 Schritt 6 | `unknown` wurde nach Zeitablauf zu `failed` und war erneut sendbar; Doppelversand möglich. | `failed` nur mit Beleg der Plattform; sonst Entscheidung des Betreibers. |
| SPEC-010 | SP5 Schritt 4 | Ein angenommener Fehlbetrag scheitert am Trigger, der den Angebotspreis verlangt. | Tabelle `payment_waivers`; Gates rechnen gedeckten Betrag plus Kulanz. |
| SPEC-011 | SP2 Schritt 11 | 404 wurde als „nie angekommen“ gewertet; der Befehl kann noch in Bearbeitung sein. | Zustand „in Bearbeitung“; erneut nur mit derselben `request_id`. |
| SPEC-012 | SP3 Schritte 4, 5 | Die Krea-Kombination aus Turbo- und Charakter-LoRA war nicht beschrieben; Verträglichkeit nur über die Architektur. | Lader-Reihenfolge, zwei Stärken, Liste geprüfter Engines (`compatible`). |
| SPEC-013 | SP5 Schritte 7, 8 | Ohne Qualitätsprüfung konnte der identitätsstärkste Kandidat automatisch freigegeben werden. | Vier Pflichtprüfungen; sonst Betreiberfreigabe (E16, E17). |
| SPEC-014 | SP6 Schritt 1 | Der Benutzerdienst startet erst nach der Anmeldung. | Entscheidung E18; bis dahin dokumentierte Einschränkung. |
| SPEC-015 | SP6 Schritte 4, 8 | Die Sicherung erfasste nur die Datenbank; Löschung und Sicherung waren nicht abgestimmt. | Umfang, Aufbewahrung, Löschprotokoll. |

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
Ergebnis: OFFEN → SP1 (Kette), SP3 (B1, H6b)
Bearbeiter/Datum: Claude, 17.11.2026
```
