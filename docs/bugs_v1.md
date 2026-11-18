# Darkfluenzer – bugs_v1.md

**Stand:** 17.11.2026 · Befundregister zu `docs/PHASENPLAN_BACKEND.md` (B) und `docs/PHASENPLAN_FRONTEND.md` (F); kein dritter Plan.
**Vorfassung:** `docs/archiv/bugs_v1_20261117_vor_neufassung.md` (dort die vollständigen Prüfprotokolle zu BUG-001 bis 006 und die Erstfassungen von BUG-007 bis 046). IDs werden nie neu vergeben oder umnummeriert.
**Prüfbasis:** Code auf `main` ab `7a49b6a`, Planstand nach `d120562` mit Korrektur der Prüfberichte; Backend- und Frontend-Quelltext, Tests, Starter; dazu die Prüfberichte von ChatGPT und Fable (17.11.) und die Läufe am Mac vom 16./17.11. Kein Befund gilt durch diese Liste als reproduziert oder behoben.

## 0. Regeln

1. **Ablauf je Befund:** gegen den aktuellen Code prüfen; Test schreiben, der den Fehler zeigt (rot); korrigieren; Test grün; Normalfall, Fehlerfall und Neustart prüfen; Lauf auf dem echten Mac; Protokollzeile (§6).
2. **Belegstufen:** **CODE** im Quelltext gelesen, kein Lauf · **TEST** durch vorhandenen Test belegt · **LIVE** am laufenden System gesehen · **FREMD** Fremdmeldung, vor der Korrektur im Code bestätigen · **HYPOTHESE** nur ein Lauf entscheidet.
3. **Priorität:** **P0** – die P0-Befunde der Default-Kette sind vor der Abnahme von Etappe C geschlossen; alle übrigen vor dem ersten echten Kunden außerhalb des Testbetriebs (Backend §6, Tore) · **P1** vor dem ersten echten Kunden · **P2** danach gezielt · **P3** Pflege.
4. **Status:** OFFEN · CODE (Code korrigiert, Mac-Nachweis fehlt; **[17.11.]** bisher „BEHOBEN“, wie PHASENPLAN_BACKEND §2.3) · TEIL (Teil am Mac belegt) · PASS (Mac-Nachweis liegt vor) · WIDERLEGT.
5. Tests mit Ersatzobjekten (FakeTd, FakeComfy, Testinstanz) sind Regression, kein Nachweis. Keine künstlichen Daten in der echten Datenbank.
6. Regressionstests: Backend `backend/tests/test_bugs_v1.py` als `test_bugNNN_…` oder im fachlichen Testmodul, Frontend `frontend/tests/`.
7. Spalte „Paket“ verweist auf die Pläne; ein Befund wird im genannten Paket geschlossen. Ein Fix schließt alle verknüpften IDs, jede mit eigenem Testbeleg.
8. Widerspruch zwischen Plan und Code → Eintrag `SPEC-NNN` in §5a, vor der Umsetzung klären.

## 1. P0

| ID | Befund | Beleg | Soll und Abnahme | Paket |
|---|---|---|---|---|
| BUG-047 | **Inhaltsstufe umgehbar.** Die Stufe erbt nur über `parent_media_id`; Upload von Platte, Vorlagen-Eingang und Befehl ohne Eltern-Medium laufen durch `standard`-Workflows (Hochskalieren, Instagram-Export, Bild zu Video) und kommen als `standard` heraus. | CODE | Stufe = höchste Stufe aus Workflow und allen Eingabebildern; Uploads per SHA-256 gegen `media`; unbekanntes Eingabebild in einem abgeleiteten Workflow = `explizit`. Abnahme: explizites Bild über alle Wege → Ergebnis `explizit`, Liefer-Gate sperrt, auch bei manipuliertem Befehl. | B SP2 |
| BUG-048 | **[18.11.] CODE** (EVENT 26 bei jeder neuen Nachricht, Test rot→grün; Mac-Lauf offen) – **Kundenliste, Ungelesen und Übersicht** aktualisieren sich bei bekannten Kunden nicht; EVENT 26 entsteht nur bei neuer Akte. | CODE: `store.record_inbound` schreibt nur ein Nachrichtenereignis, `customer_events` liest nur Kundenereignisse | EVENT 26 bei jedem Eingang, Versand und Gelesen-Wechsel. Abnahme: zweite Nachricht eines bekannten Kunden erhöht Ungelesen, ohne die Akte zu öffnen. | B SP2, F SP2 |
| BUG-049 | **[18.11.] CODE** (ein Empfangsthread je Prozess, Test mit Ersatz-Bibliothek; echtes Ab-/Anmelden offen) – **Telegram-Kontowechsel** ohne Neustart: zwei Empfangsthreads lesen dieselbe TDLib-Instanz. | CODE: `tdjson._receive` verwirft Ereignisse anderer Clients; nach dem Abmelden laufen zwei Empfangsthreads | Genau ein Empfänger je Prozess; alter Client wird geschlossen und abgewartet. Abnahme: abmelden, anmelden, zehn Eingänge genau einmal. | B SP2 |
| BUG-050 | **Gutschein-Erkennung** (`payments/vouchers.py`, `extract`) hält normalen Text mit Buchstaben und Ziffern („habe morgen 1830 Zeit“) für einen Code und maskiert ihn; das Original ist verloren. | CODE | Nur eindeutige Muster; Originaltext am Gutschein geschützt speichern (nur im Wallet sichtbar). Abnahme: 20 normale Sätze mit Zahlen bleiben unverändert, echte Codes werden erkannt. | B SP2, SP5 |
| BUG-051 | **Bezahlter Auftrag kann stecken bleiben:** kein „Neu erzeugen“ bei unbrauchbaren erfolgreichen Kandidaten (`pipeline.retry_stage` nur für Fehlstufen), keine Erstattung per Befehl, nach `delivered` kein Übergang. | CODE | Befehle `order_regenerate`, `order_aftercare`; Zustände `complaint`, `closed`; Erstattung mit Beleg. | B SP5 (geht in BUG-100 auf; „Neu erzeugen“ vor der Freigabe über `pipeline.regenerate_order`) |
| BUG-052 | **Default-Auftrag ohne Charakterbindung:** weder Influencerin noch Charakter-LoRA am Auftrag; kein Workflow hat einen LoRA-Parameter. (Korrektur 17.11.: trainierte LoRAs trägt der Code bereits über `pipeline._adopt_lora` → `models.register_lora` in die Registry ein; es fehlen LoRA-Parameter in den Workflows und die Bindung am Auftrag.) Live 17.11.: Influencerin nicht gesetzt, Charakter 01 mit 0 Bildern. | CODE, LIVE | Auftrag trägt Influencerin, Charakterprofil, LoRA-Version; Workflow lädt die LoRA; der Trigger wird dem Prompt vorangestellt; die LoRA trägt das Kürzel der Figur; bis SP3 Karte „ohne Charakter-LoRA“. | B SP1 (Bindung), SP3 (LoRA) |
| BUG-057 | **Default-Nachricht endet still.** Live 17.11.: „Clone“ → nur Cockpit-Karte „Kein Workflow für clone im Default-Kontakt gewählt“, keine Antwort in Telegram. Dazu: „wartet auf Start“ ohne Chat-Antwort, stiller Rücksprung bei abgeschalteten Befehlen, Rückversand je Freigabeart unklar. | LIVE, TEST | Jede Default-Nachricht endet in genau einem Zustand (gestartet · wartet auf Start · abgelehnt mit Grund · zurückgesendet · Rückversand gesperrt) mit Karte **und** Antwort im selben Chat. | B SP1, F SP1 |
| BUG-075 | **Referenz aus vorheriger Nachricht wird nicht gefunden.** Live 17.11.: Foto und „Clone“ als zwei Nachrichten (4 s Abstand); `_cloner_plan` nimmt Referenzen nur aus derselben oder einer beantworteten Nachricht und hätte nach dem Bild gefragt. | LIVE, CODE | Letzte Medien desselben Absenders innerhalb `cloner.reference_window_s` (Konfiguration) gelten als Referenz; nie Medien anderer Absender. Abnahme: Foto, dann Befehl → genau ein Auftrag mit diesem Foto. | B SP1 |
| BUG-008 | **Render-Worker kann nach einem Job sterben** (`advance_order`, Kloner-Rückversand, Push außerhalb des Fehlerfangs). | CODE | Fehler in jeder Nachbearbeitung auslösen: Worker läuft weiter, kein Job verloren, kein Doppelversand. | B SP1 |
| BUG-014 | **[18.11.] CODE** (Warteschlange je Chat; Handy-Lauf offen) – Telegram sichert die Reihenfolge je Chat nicht; ein Befehl kann die Foto-Nachricht überholen. | CODE | Verarbeitung je Chat nacheinander; Foto mit verzögertem Download, dann Befehl. | B SP1 |
| BUG-079 | **[18.11.] CODE** (album_id, Album wartet auf Ruhe; Handy-Lauf offen) – **Telegram-Alben werden nicht zusammengeführt.** Ein Album besteht aus mehreren Nachrichten mit gemeinsamer `media_album_id`; der Adapter liest die Kennung nicht, verarbeitet wird nur das Bild mit dem Befehl, die anderen werden still ignoriert. (Fables BUG-084 ist derselbe Befund.) | CODE | `album_id` an der Nachricht speichern, Album je Konto, Chat, Absender dauerhaft zusammenführen und erst nach `cloner.album_settle_s` auswerten; Neustart und Dubletten ohne zweiten Auftrag. Abnahme: fünf Bilder als Album → fünf Aufträge, fünf Dateien zurück. | B SP1 |
| BUG-083 | **[18.11.] CODE** (jede Ausnahme → FEHLGESCHLAGEN; Handy-Lauf offen) – `_on_inbound` fängt nur `PipelineError`, `ComfyError`, `StoreError`. Jeder andere Fehler im Kloner endet ohne Karte und ohne Antwort; die Nachricht wird nicht als gelesen markiert. | CODE | Jede Ausnahme endet im Zustand `failed` mit Karte und Antwort im Chat. | B SP1 |
| BUG-086 | **[18.11.] CODE** (FEHLGESCHLAGEN/ABGEBROCHEN mit Grund; Handy-Lauf offen) – Kloner: bei Fehlschlag oder Abbruch der Stufe bekommt der Default keine Antwort (`_cloner_delivery` sendet nur Ergebnisse). (In Fables SP1-Blatt als „BUG-079“ geführt; 079 ist bereits vergeben.) | CODE | Zustand `failed` oder `cancelled` mit Grund als Karte und im Chat. | B SP1 |
| BUG-089 | **Daueraufgaben ohne Aufsicht:** `outbox_worker`, `adapter.run` und `wallet.run` enden bei einem unerwarteten Fehler still; bis zum Neustart wird nichts mehr gesendet. (In Fables SP2-Blatt als „BUG-086“ geführt; 086 ist bereits vergeben.) | CODE | Aufsicht mit Protokoll, Anzeige im STATE und Neustart. | B SP2 |
| BUG-105 | `Store._migrate` führt Migrationen ohne Sicherung und ohne Integritätsprüfung aus, obwohl die Entwicklungsregeln beides verlangen. (In Fables SP6-Blatt als „BUG-102“ geführt; 102 ist bereits vergeben.) | CODE | Sicherung vor, Prüfung nach jeder Migration. Vor der ersten neuen Migration umsetzen. | B SP0 Schritt 1 |

## 2. P1

| ID | Befund | Beleg | Soll und Abnahme | Paket |
|---|---|---|---|---|
| BUG-007 | Zeitlimit 3600 s fest in `pipeline.run_render`; Remix-Lauf lag mit 3440 s knapp darunter. | CODE | Kein zeitbasierter Abbruch. Ende durch Ergebnis, Fehler, Abbruch oder wenn ComfyUI erreichbar ist und den Auftrag nicht mehr kennt; Verbindungsverlust = Zustand `UNKNOWN`, Abgleich nach Wiederverbindung, kein automatischer Neustart; Hinweis statt Abbruch bei Stillstand; geschätzte Dauer als Schätzung. Umgesetzt 17.11.: 6189956, 101bfc5; offen: Anzeige. | B SP1 |
| BUG-009 | Wallet-Beobachter (`payments/chain.py`, `run`) fängt `TypeError` nicht. | CODE | `null`, Liste statt Objekt, falsche Felder: Beobachter läuft weiter, zeigt Fehler, holt auf. | B SP5 |
| BUG-010 | BTC-Adresse in Großbuchstaben: Prüfung akzeptiert, Vergleich unterscheidet Groß/klein. | CODE | Für Vergleich und Abfrage normalisieren. | B SP5 |
| BUG-011 | Zuordnung nach Erkennungszeit statt Blockzeit (`store._match_offer`). | CODE | Verspätet gescannte, rechtzeitig bestätigte Zahlung wird zugeordnet; nach Ablauf nicht. | B SP5 |
| BUG-013 | **[18.11.] CODE** (pending nach Neustart neu geladen; Handy-Lauf offen) – Telegram-Anhang bleibt nach Absturz zwischen Speichern und Download `pending`. | CODE | Fortsetzung nach Neustart oder Fehlschlag mit Grund. | B SP1 |
| BUG-015 | **[18.11.] CODE** (`ignored_chat_ids`, Vorgabe 777000; Test rot→grün; echter Code-Eingang offen) – Telegram-Dienstkonto 777000 kann als Kunde landen. | OFFEN | Keine Akte, kein KI-Dialog, Code nie im Gedächtnis. | B SP2 |
| BUG-016 | **[18.11.] CODE** (Abgleich über SQLite, Verlauf und Send-Updates, Befehl 66; Mac-Lauf mit echtem Zeitablauf offen) – Versand mit Status `unknown` bleibt hängen; Instagram klärt ihn nur im Speicher, nach Neustart entsteht fälschlich „ÜBERGABE AN BETREIBER“. | CODE | Abgleich dauerhaft über Verlauf/Echo, nie blind zweimal senden, eigene Nachricht nie als Übergabe. | B SP2 |
| BUG-017 | **[18.11.] CODE** (Textteil: Satzgrenzen; Handy-Lauf offen) – Instagram lehnt Bilder über 8 MB ab; keine Zustellkopie; Texte über 1000 Byte nicht geteilt: `instagram._parts` lehnt Text über `max_text_bytes` ganz ab. | CODE | Zustellkopie je Kanalgrenze, nie unter 1K; Text teilen; genau einmal zugestellt. | B SP5 (Datei), SP4 (Text) |
| BUG-019 | Angebot wählt das Produkt über den Listenindex. | CODE | Stabile ID je Preisposition, Revisionsprüfung. | B SP5 |
| BUG-020 | **[18.11.] CODE** (Influencerin je Konto und Akte, Filter, Schalter; zwei echte Konten offen) – Kundenakte nimmt `influencers[0]` statt der Influencerin des Kontos. | CODE | Influencerin je Kanalkonto und Akte. | B SP4 (C5.1) |
| BUG-021 | **[18.11.] CODE** (erneut nur nach `failed`, Test rot→grün) – KI-Hinweis nach fehlgeschlagenem oder ungeklärtem Versand nicht fortsetzbar. | CODE: `queue_ai_notice` sperrt, sobald eine Hinweisnachricht verknüpft ist, auch wenn sie fehlgeschlagen ist | Erneuter Versuch möglich, nie doppelt. | B SP2 |
| BUG-022 | Alle Engines `evaluation`, Rollen leer; Kundenaufträge prüfen Engine-Freigabe nicht (`_not_startable` prüft nur aktiviert, gesperrt, Dateien). | CODE | Kundenproduktion nur auf freigegebenen Engines (`usage = production`, alle Gates nach Backend §9.1) mit der LoRA der Figur, auch bei manipuliertem Befehl; `_not_startable` prüft das bei Kundenaufträgen. | B SP5 |
| BUG-023 | Krea als `standard` eingestuft ohne Nachweis. | HYPOTHESE | Graph und Testbilder prüfen; Stufe nur mit Beleg. | B SP5 |
| BUG-024 | Cockpit-Befehle warten ohne Zeitlimit auf die Quittung (`core/commands.ts`, `terminalReceipt`). Erreicht der Befehl das Backend nie, wartet `useCommand` ewig; der Befehlsstatus lässt sich nicht abfragen. | CODE | Zeitlimit, danach Zustand über die `request_id` wiederherstellen. | B SP2 (Endpunkt), F SP2 |
| BUG-043 | **Abbrechen.** Behoben (`ebbe773`): Abbruch ab Klick, Ergebnis nach Abbruch verworfen, Speicher frei, Pause dauerhaft. Offen: Auftrag als Ganzes, Mehrkandidaten. | TEIL (§7) | Laufender Mehrkandidaten-Auftrag abgebrochen, Warteschlange leer, Journal stimmt. | B SP1, F SP1 |
| BUG-053 | **[18.11.] CODE** (Vorprüfung vor der Anlage; Handy-Lauf offen) – Kloner legt Aufträge ohne Vorprüfung an (aktiviert, nicht gesperrt, Modelle vorhanden). | CODE | Dieselbe Prüfung wie der Render-Befehl vor der Anlage; sonst Ablehnung mit Grund im Chat. | B SP1 |
| BUG-054 | **[18.11.] CODE** (Video 1 Kandidat; Handy-Lauf offen) – Kloner startet auch Videos mit `production.candidates_default` (3). | CODE | `production.video_candidates_default` (Vorgabe 1). | B SP1 |
| BUG-055 | **[18.11.] CODE** (Stapel je Bild; Handy-Lauf offen) – Kloner nutzt nur die erste Referenz (`refs[0]` in `_cloner_order`). | CODE | Mehrere Bilder einer Nachricht laufen als Stapel, je Bild ein Auftrag. Hat der Workflow mehrere Vorlagen-Parameter, werden die Bilder gemeinsam verwendet. | B SP1 |
| BUG-056 | Stufe mit genau einem Kandidaten wartet auf manuelle Auswahl (`advance_order`). | TEST | Ein einziger erfolgreicher Kandidat wird automatisch gewählt; bei Freigabeart „automatisch“ folgt die Systemfreigabe (C5.6a). | B SP1 |
| BUG-058 | **Video-Parameter uneinheitlich:** LTX `duration` („Länge (s)“) aus dem Manifest, Wan/Remix `duration_s` („Gesamtlänge“) aus dem Backend; das Feld steht je Workflow an anderer Stelle. Betreiber beanstandet 17.11. | TEST, LIVE | Ein Parametervertrag und eine Bedienkomponente für alle Video-Workflows. | B SP1, F SP1 |
| BUG-059 | KI-Kennzeichnung nur in Metadaten; Plattform-Neukodierung entfernt sie vermutlich; WebP/WebM nicht kennzeichenbar. | CODE, HYPOTHESE | Kennzeichnung muss beim Empfänger ankommen (Begleittext oder Marke); je Kanal real prüfen. | B SP5 |
| BUG-060 | Angebot setzt ein Krypto-Wallet voraus; Angebotstext fest im Code; `offer_amounts.method` erlaubt nur Krypto; die Gültigkeit steht in `wallet.offer_valid_min`; `store.create_offer` legt jeden Auftrag als `image` an. | CODE | Zahlungswege als Liste je Influencerin; die Formulierung kommt aus dem Sprachworkflow (Profilblock Angebot, E19), Betrag und Zahlungsweg aus SQLite. | B SP5 |
| BUG-061 | **[18.11.] TEIL** (beide Instanzen über `comfy start`, Aufwärmlauf; Autostart und Ruhezustand SP6, §7) – Starter startet nur die Medien-Instanz; kein Autostart, kein Schutz vor Ruhezustand; `cockpit_up` startet den Server losgelöst, stirbt er, startet ihn niemand neu. | CODE | Beide Instanzen, Autostart, kein Ruhezustand im Betrieb. | B SP4 (KI-Instanz), SP6 (Dienst) |
| BUG-090 | Die Fertigstellen-Stufe trägt keine Parameter (`pipeline.select_candidate` ruft `create_render` mit leeren Werten). Die Höhe für das Story-Format lässt sich so nicht setzen; ein Video-Kundenauftrag scheitert, weil `ltx25_i2v` als Fertigstellen den Pflichtwert `prompt` braucht. | CODE | Werte für die Fertigstellen-Stufe am Auftrag. | B SP1 (Story), SP5 (Video) |
| BUG-094 | LoRA nur in Workflows mit demselben Engine-Eintrag ladbar (`models.engine_model_names` vergleicht `base_engine`). `lustify_sam31_edit` nutzt dasselbe Modell unter anderem Eintrag und dürfte die Charakter-LoRA nicht laden. (In Fables SP3-Blatt als „BUG-089“ geführt; 089 ist bereits vergeben.) | CODE | Bindung an die Architektur (`arch`). | B SP3 |
| BUG-095 | Jeder Workflow-Lauf prüft die Instanz über `runtime.start`, ruft zweimal `git` auf (`comfy.provenance`), fragt im Sekundentakt ab und schreibt eine Herkunftsdatei. Für Chat-Antworten ist das zu schwer. **[18.11.] PASS** (§7, `llm.generate`) | CODE | Leichter Weg ohne diese Schritte (`llm.generate`). | B SP4 |
| BUG-096 | **[18.11.] CODE** (Tippanzeige bis zum Senden erneuert; Handy-Lauf offen) – Telegram: Tippanzeige nur einmal gesendet, Online-Status nie gesetzt, Gelesen sofort nach dem Speichern. | CODE | Verhalten nach Profil. | B SP4 |
| BUG-097 | **[18.11.] CODE** (Migration 34 mit draft/cancelled/scheduled_at; Test grün) – Eine eingereihte Antwort lässt sich nicht stornieren: `channel_messages.status` kennt weder `draft` noch `cancelled`, der Postausgang kennt keine Sendezeit. | CODE | Tabellenumbau, `scheduled_at`, Storno bei neuem Eingang. | B SP4 |
| BUG-098 | **[18.11.] TEIL** (Chat-Textweg in `llm.py`, §7; Prüfknoten-Teil SP5) – `comfy.collect_graph` kennt nur Datei-Ausgaben; ein Textergebnis endet mit „keine Ausgabedatei“. (In Fables SP4-Blatt als „BUG-094“ geführt; 094 ist bereits vergeben.) | CODE | Eigener Textweg in `llm.py`. Derselbe Weg liefert die Messwerte der Prüfknoten (Zahlen, JSON) an `checks.py` (SP5 Schritt 7, Fable 17.11.). | B SP4 |
| BUG-099 | Zustellung immer als Dokument und ohne Text (`_queue_delivery`, `telegram._send`). E7 verlangt Foto oder Video als Standard mit Begleittext. | CODE | Anhangart aus dem Produkt; Begleittext vom Sprachworkflow (E19), KI-Kennzeichnung als fester Profiltext. | B SP5 |
| BUG-100 | Nach `delivered` gibt es keinen Übergang (`store.TRANSITIONS`), auch nicht zu `refunded`; der Index `deliveries_one_per_order` erlaubt eine Lieferung je Auftrag. Neuauflage und Erstattung nach der Zustellung sind unmöglich. | CODE | Übergänge ergänzen, Index je Auftrag und Artefakt. | B SP5 |
| BUG-101 | Die Render-Warteschlange ist reines FIFO (`asyncio.Queue`); ein bezahlter Kundenauftrag wartet hinter Default-Stapel und Training. | CODE | Vorrang je Job. | B SP5 |
| BUG-102 | Der öffentliche Eingang (`create_public_app`, `serve`) entsteht nur mit Instagram-Konfiguration; ein PayPal-Webhook ohne Instagram ist nicht erreichbar. (In Fables SP5-Blatt als „BUG-098“ geführt; 098 ist bereits vergeben.) | CODE | `[server] public_base_url` unabhängig von Instagram. | B SP5 |
| BUG-080 | **[18.11.] CODE** (Direkt schließt, cloner_returns; Handy-Lauf offen) – Kloner im Modus „Direkt“: nach dem Rückversand wartet die Stufe weiter auf Auswahl, der Auftrag bleibt offen; „Stufe wiederholen“ sendet alle Dateien erneut. | CODE | Auftrag schließt nach dem Rückversand; Rückversand je Medium genau einmal (`cloner_returns`). | B SP1 |
| BUG-081 | **[18.11.] CODE** (ohne Seed 1, cloner_candidates; Handy-Lauf offen) – Kloner verlangt immer `candidates_default` Kandidaten; Workflows ohne Seed lehnt `create_order` dann ab (z. B. Export). | CODE | Ein Kandidat bei Workflows ohne Seed; Default-Produktion `production.cloner_candidates` (Vorgabe 1). | B SP1 |
| BUG-082 | **[18.11.] CODE** (Default zuerst, ohne Verzögerung; Handy-Lauf offen) – Rückversand an den Default wartet Antwortverzögerung und Tippzeit ab (`telegram._pace`) und steht hinter Kundensendungen. | CODE | Interne Sendungen sofort und zuerst. | B SP1 |
| BUG-085 | Die Zulassung (`_admit`) entlädt für jeden Medienjob die ruhende andere Instanz, also auch Melody. **[18.11.] TEIL** (`keep_loaded` umgesetzt und getestet; Einschalten nach E15, §7) | CODE | Instanz als „bleibt geladen“ markierbar; Regel für Chat neben Video (E15). | B SP4 |
| BUG-077 | **[18.11.] CODE** (nur under_18 sperrt das Angebot; Test grün) – Angebot verlangt die Altersangabe: `server._create_offer` weist ohne `self_declared_adult` ab. Laut E2 entfällt die Altersfrage. (Im Änderungsblatt vom 17.11. als „BUG-075“ geführt; 075 ist bereits vergeben.) | TEST | Bedingung entfernen; die Sperre bei Hinweisen auf Minderjährigkeit bleibt: `customers.age_mark` kennt bereits `under_18`, dieser Wert trägt die Sperre, `_create_offer` prüft künftig nur noch darauf. Test `test_customer_orders` anpassen. | B SP4 |

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
| BUG-070 | Übersicht zählt bezahlte Aufträge in Produktion und Freigabe nicht. **[18.11.] TEIL** (§7) | CODE | Eigene Zähler. | F SP2 |
| BUG-071 | Ereignislisten im Browser wachsen unbegrenzt (`state.applyEvent`). | CODE | Begrenzen, älteres seitenweise. | F SP2 |
| BUG-072 | Nachrichten, Wallet, ComfyUI ohne Browser-Test; Smoke klickt Wallet nicht. **[18.11.] TEIL:** Smoke klickt alle sechs Reiter; Chrome-Tests `comfyui`, `default` (Nachrichten), `overview`, `design` (alle Reiter); Wallet nur Gestaltung, kein Zahlungsablauf | CODE | Je Seite ein Browser-Test. | F SP2 |
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
| BUG-108 | `comfy.ui_to_api` bricht bei offiziellen Vorlagen aus älteren Knotenfassungen ab (dynamische Auswahl mit weniger gespeicherten Werten, z. B. `SaveVideo` in `video_ltx2_5_flf2v`: „pop from empty list“), setzt sonst fehlende Werte auf `None`; `check_graph` meldet wachsende Eingänge (`values.a` von `ComfyMathExpression`) als unbekannt, auch im abgenommenen `ltx25_i2v`. | CODE | Standard bzw. erste Option wie im Frontend; Autogrow-Unterreingänge anerkennen. | A (Zeitachse B4) |
| BUG-109 | Wiederholen und „Wiederholen“ (repeat_job_id) eines Sekunden-Videos (LTX) scheitern: der Job speichert `segment_s = 0`, `video_plan` lehnt jedes `segment_s` ab („Abschnitte gibt es bei diesem Workflow nicht“). Gefunden mit dem Regressionstest zu FABLE-008. | CODE | `segment_s = 0` heißt keine Abschnitte; andere Werte bleiben abgelehnt. | A |
| BUG-126 | Langvideo: das Zusammensetzen meldet die Vorschau jedes `LoadVideo` (Typ `input`) als Ausgabe; `comfy` übernahm sie als Ergebnis – die Abschnittsvideos landeten als Medien in der Galerie, das Job-Ergebnis zeigte auf das erste Abschnittsvideo statt auf das fertige Video (echter Lauf 18.11., Job 103: Medien 106/107 Abschnitte, 108 fertig). Nummer 126, weil 110–125 als vorläufige Nummern des Auditblatts im Text stehen. | CODE | Ausgaben vom Typ `input` sind nie Ergebnisse. | A |
| BUG-127 | Testprozess-Leck: Tests, die über Cockpit oder Pipeline rendern, starten die Fake-ComfyUI per `runtime.start` mit eigener Prozessgruppe (`start_new_session`, im Betrieb gewollt); kein Test stoppte sie. 18.11.: 451 verwaiste Prozesse aus elf Testarten. | CODE | Bereinigung je Testprojekt und am Sitzungsende (Prozessgruppe, nur Test-Interpreter + `main.py` + Arbeitsverzeichnis unter pytest). | Test |
| BUG-128 | Telegram-Versand von Dateien: `inputMessageDocument.document` ist in TDLib 1.8.70 ein `inputDocument`; der Code gab `inputFileLocal` direkt hinein – TDLib parst das ohne Fehler, ohne Datei (bloßes Feld `path` auf falscher Ebene), der echte Versand (Zustellung, Kloner-Rückgabe) schlägt fehl. Gefunden beim Abgleich mit `td_api.tl` (SP5 Schritt 9). | CODE | Datei in `inputDocument`/`inputPhoto`/`inputVideo`; Parser-Prüfung mit frischem, nicht angemeldetem TDLib-Client. | D (SP5 9) |
| BUG-129 | Videoauftrag (Bild-Kandidaten + Animation) bekommt die Art `image`: `create_order` setzt die Art aus der Engine des Kandidaten-Workflows und überschreibt `video`; Folge: Zustellung als Foto, „Animation neu“ fehlt. Gefunden mit dem Browser-Test zu SP5 Schritt 9. | CODE | Art aus dem Endergebnis (Fertigstellen-Workflow Video → `video`). | D (SP5 9) |

## 4. P3

| ID | Befund | Soll | Paket |
|---|---|---|---|
| BUG-035 | `config.toml.vor-instagram` lokal mit Rechten 644. | Auf dem Mac prüfen, auf 600 setzen oder nach Rückfrage löschen. | B SP6 |
| BUG-036 | `setup_comfyui.sh` trägt keinen Ordner für Bildinterpolation (FILM) ein; Ordner `LLM` und Knotenpaket für das Chatmodell fehlen (vorbereitet: `launcher/setup_llm_session.sh`, `LLM: llm`, noch nicht committet). **[18.11.] PASS** (`1396dd1`, Mac-Lauf siehe §7). | Skripte ergänzen, am Mac prüfen. | B SP4 |
| BUG-037 | Lokale, nicht committete Zeile `enabled = true` in `workflows/manifest.toml`. | Bewusst lokal; nie mit Fachänderungen committen. Ursache: BUG-092 (lokaler Zustand im versionierten Manifest). | B SP3 |
| BUG-104 | Logs werden nur beim Start rotiert; `server.log` und `app.log` wachsen im Dauerbetrieb. | Rotation nach Größe. | B SP6 |
| BUG-074 | Dokumente veraltet und widersprüchlich (schließt BUG-034 ein). | Konsolidierung am 17.11. erledigt (zwei Pläne + diese Liste, Altdokumente im Archiv); Widersprüche aus den Prüfberichten von ChatGPT und Fable am 17.11. korrigiert (SPEC-001 bis 007). Abschluss mit der Betreiberfreigabe. | B DOK-1 |

## 5. Erledigt oder widerlegt

| ID | Stand | Offener Mac-Nachweis |
|---|---|---|
| BUG-001 | CODE (`ab1d9cf`) | Browser mit echtem Kundenanhang |
| BUG-002 | CODE, lokal TEIL (17.11. 00:23: Weiterleitungs-Header 403) | echter Tunnel |
| BUG-003 | CODE (`4f79bfd`) | echter Kanal Telegram und Instagram |
| BUG-004 | CODE (`018f462`) | echter Rückversand |
| BUG-005 | CODE (`cd0ff68`) | echte Zahlung |
| BUG-006 | CODE (`9927140`) | erster Kundenauftrag |
| BUG-038 | PASS: Telegram-Chat ohne Position wird nach Neustart nachgeholt, nur Ungelesenes (`36433c8`, `b4ad0c4`), live 17.11. | – |
| BUG-039 | PASS: Register öffnet bei Ungelesenem nach Neuladen (`b4ad0c4`), live 17.11. | – |
| BUG-040 | CODE: Name aus Chat-Titel (`e83b7f5`) | Sichtprüfung beim nächsten Eingang |
| BUG-041 | PASS: „Als Default festlegen“ (Befehl 48, `ad82d0d`), Klicktest an Testinstanz, Umzug live per ID-Feld | – |
| BUG-042 | PASS: Seed-Grenzen (`932c9ec`), LTX-Job 64 danach aus dem Cockpit | – |
| BUG-044 | CODE im Cockpit (Video Standard 1, `ebbe773`); Kloner siehe BUG-054 | Sichtprüfung |
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

Widersprüche zur Sprach-KI über ComfyUI 2 (E19, Betreiberentscheidung 17.11.; geprüft gegen `main` `55c9976`, `object_info` der Instanz 2 und ComfyUI-LLM-Session `ec2b293c`):

| ID | Stelle | Befund | Korrektur |
|---|---|---|---|
| SPEC-016 | Regel 12 c, SP4 Schritt 2; Code `server.HONESTY_RULE` | Die Ehrlichkeitsregel steht als Text im Python-Code und sollte laut Plan vom Backend angehängt werden. | Fester Textknoten im registrierten Sprachworkflow; die Registrierung prüft Vorhandensein und Bindung; der STATE zeigt den Text aus dem Graphen. |
| SPEC-017 | SP4 Schritt 3, FRONTEND F7.9 (Schalter „Antworten gegen Regeln prüfen“, „Hard-Fails serverseitig“) | Geplant war eine sprachliche Regelprüfung in `dialog.py` (verbotene Wörter, Mensch-Behauptung, Deutung von Preisaussagen). | Gesprächsregeln als positive und negative Regeln im Promptprofil; eine Entwurfsprüfung nur im Workflow; im Backend nur Gates (KI-Hinweis, `under_18`, Zahlenabgleich mit den Fakten, Schalter, Kanalgrenzen). |
| SPEC-018 | SP4 Schritte 1, 5; Knoten `LLMSessionChatNode` | Der Knoten speichert je `session_id` einen eigenen Verlauf als JSON unter `output/llm_session_sessions/`: zweite Gesprächsquelle neben SQLite, Kundendaten außerhalb der Datenbank. | Kontext nur aus SQLite als Eingang; je Lauf neue Sitzung mit `reset_session`; Probelauf belegt, dass keine Verlaufsdatei bleibt, sonst löscht `llm.py` sie. **[18.11.] Probelauf: Datei bleibt** (JSON + `.bak` je Sitzung, auch mit `reset_session`, `max_turns` 0, persistentem Cache aus); `history_dir` lenkt alle Schreibzugriffe um (belegt) → `llm.py`: je Lauf eigener Ordner im ComfyUI-2-temp, nach dem Lauf löschen, Reste beim Start entfernen; vor Kundengesprächen umsetzen und testen (SP4 Schritt 1). **[18.11.] Behoben, am Mac belegt** (`nodes/llm.py`, §7). |
| SPEC-019 | SP4 Schritt 2, FRONTEND §3.4, F7.9 | Persona als ein Textfeld mit Vorlagen; Profilfelder ohne nachgewiesene Bindung an Graph-Eingänge; Top-K, Min-P, DRY und Seed als mögliche Parameter genannt. | Getrennte Promptblöcke je Influencerin in `persona_versions`, jeder an einen eigenen Eingang von `clara_chat_melody` gebunden; nur die Parameter, die der Knoten hat; Registrierung weist ungebundene Felder ab. |
| SPEC-020 | Regel 13, §3.2 (ComfyUI 2: „Inhaltsprüfung“) | Die Inhaltsprüfung lag laut Plan in KI-ComfyUI 2, E16 und E17 legen sie in die Medien-Workflows. | Inhalts- und Qualitätsprüfung als Knoten in den Medien-Workflows auf ComfyUI 1. |
| SPEC-021 | SP5 Schritte 2, 9; BUG-060, BUG-099 | Angebots- und Begleittext als Vorlage im Profil, vom Backend eingesetzt. | Formulierung durch den Sprachworkflow aus Profilblock und Geschäftsfakten; Betrag und Zahlungsweg setzt das Backend aus SQLite; die KI-Kennzeichnung bleibt ein fester Profiltext. |

Geprüft und mit E19 vereinbar (keine Änderung): BUG-050 (Gutscheincode-Muster ist eine Zahlungsprüfung), BUG-017 (Teilen an Satzgrenzen ist eine Kanalgrenze), BUG-077 (`under_18` ist ein Gate), BUG-085 (Speicherregel), BUG-095 und BUG-098 (Transportweg für Text und Werte).

## 6. Protokollzeile je Befund

ID · Commit und Datei/Funktion · Behauptung (BESTÄTIGT, TEILWEISE, WIDERLEGT, NICHT REPRODUZIERBAR) · Nachweis (Test, Log) · Ursache · Korrektur-Commit · Regression (Normalfall, Fehlerfall, Neustart, Mehrfachzustellung) · Mac-Lauf (PASS, FAIL, NICHT GELAUFEN) · Bearbeiter, Datum.

**Abschluss:** PASS erst, wenn der Test grün ist, die Änderung auf `main` liegt und der Mac-Lauf belegt ist.

## 7. Prüfprotokoll (ab 17.11.2026)

```text
ID: SP5 Schritt 9 (Zustellung) mit BUG-128 und BUG-129
Commit: siehe git log „SP5 step 9“ / channels/telegram (_content: Foto, Video, Dokument, Timer),
  config ([telegram] max_photo_mb/max_file_mb/self_destruct_s), core/delivery (_delivery_kind,
  _delivery_copy WebP/WebM, _media_attachment, _delivery_caption, _window_closed, _deliver,
  _resume_parked), core/orders (Art aus Endergebnis, Fertigstellen neu mit Seed), core/messages,
  store (TRANSITIONS awaiting_contact, parked_orders, last_approved_artifact, queue_outbound test),
  Stream („Animation neu“)
Nachweis: test_delivery (4: TDLib-Eingaben je Art, Grenze/Bildmaße, Art/Format/Begleittext/
  Fenster/Wiederaufnahme, Video-Fertigstellen neu mit Seed und Art video – vorher rot), Parser-
  Prüfung TDLib 1.8.70 (frischer Client ohne Anmeldung: neue Formen geparst, alte Form ohne Datei),
  volle Suite 315 grün; Chrome-E2E isoliert 28/28 (neu delivery.spec.ts), lesend echt 10/10
NOT_RUN: echter Versand an Telegram/Instagram (Foto, Video, selbstlöschend, Dokument), Begleittext
  mit echtem Profilblock, Instagram-Fenster am echten Konto
Ergebnis: CODE (Integration isoliert belegt), Versand NOT_RUN
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP5 Schritt 6 (Produktion nach Zahlung)
Commit: siehe git log „SP5 step 6“ / Migration 41 (image_auto, offers.wish/wish_source/
  production_started_at/delay_notice_at), core/autoprod.py (neu), core/sales (Start nach Zahlung,
  Testfreigabe, Zeitaufgabe), core/chat (Wunsch ins Angebot), pipeline (Klasse Default für Tests),
  influencer/commands/order.proto, InfluencerBlock, CustomerPanel, Stream
Nachweis: test_autoprod (Start aus Produkt, ohne Automatik/Wunsch, Video-Fertigstellen, Dank mit
  Lieferzeit, genau eine Verzugsnachricht, Testauftrag Klasse Default), volle Suite 311 grün;
  Chrome-E2E isoliert 27/27, lesend echt 10/10; echte Migration 40→41, Telegram angemeldet;
  isolierter Server ohne Bildmodelle/ComfyUI 18188 → keine echten Renderläufe ausgelöst
NOT_RUN: echter Produktionslauf nach Zahlung (Engines nur evaluation, keine Qualifikation),
  Dank-Text mit echtem Profilblock „Lieferung“ (pflegt der Betreiber)
Ergebnis: CODE (Integration isoliert belegt), Lauf NOT_RUN
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP5 Schritt 12 (Kundentest mit Bild, Testweg)
Commit: siehe git log „SP5 step 12“ / Migration 40 (orders.test + Trigger, test_pay_word/auto_pay,
  deliveries_gate/deliveries_send_gate/media_order_no_delete neu), approval.check_gate, store
  (release_test_order, open_test_orders, test_delivery_allowed, verified beim Eingang), core/sales
  (_test_release, _end_test_orders, Testangebot), core/cloner (Wort, Moduswechsel), core/messages,
  channel/commands/order.proto, DefaultPanel, Stream
Nachweis: test_testpath (4), volle Suite 308 grün; Chrome-E2E isoliert 27/27 (neu testpath.spec.ts),
  lesend echt 10/10; echte Migration 39→40 mit Sicherung, Telegram angemeldet
Vertragsänderung: Eingang einer bekannten Identität setzt verified = 1 (Default-Identität wird erst
  durch eine echte Nachricht verifiziert)
NOT_RUN: Kundentest am Handy bis zum Bild (Produktion Schritt 6, Zustellung Schritt 9 folgen)
Ergebnis: CODE (Integration isoliert belegt), Kette NOT_RUN
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP5 Schritt 2 (Angebot mit Faktenblock und Lieferzeit)
Commit: siehe git log „SP5 step 2“ / Migration 39 (orders-Neubau payment_review/awaiting_contact/
  status_reason, offer_payments, offers.facts/delivery_s/review_started_at, offer_cooldown_min),
  core/eta.py, core/sales (_offer_plan, _fact_block, _place_offer, offer_expiry), core/chat
  (_dialog_offer, Ziffernprüfung, offer_rejected), core/assessment (offer_response), store/payments
  (Prüfung, Ablauf, Ablehnung, Eingang nach Ablauf), order/wallet/influencer/commands.proto, Stream,
  Wallet, InfluencerBlock
Nachweis: test_offers (Lieferzeit, Median, Ablauf/Prüfung/Eingang nach Ablauf, Einstufung, Dialog
  mit Faktenblock/Ablehnung/Sperrzeit/Ziffern/kein Produkt), volle Suite 304 grün; Chrome-E2E isoliert
  26/26 (neu offers.spec.ts), lesend echt 10/10; echte Migration 38→39 mit Sicherung, Aufträge
  identisch, Telegram angemeldet
Vertragsänderung: Gutscheincode setzt das offene Angebot auf payment_review; ein nicht deckender
  Gutschein beendet die Prüfung (offered mit Restfrist) – test_bug005 bleibt grün
NOT_RUN: Angebot an echten Kunden, Melody-Angebotstext ohne Ziffern im echten Lauf (Profilblock
  Angebot fehlt, pflegt der Betreiber)
Ergebnis: CODE (Integration isoliert belegt), Kundenlauf NOT_RUN
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP5 Schritt 1 (Produkte)
Commit: siehe git log „SP5 step 1“ / Migration 38 (products, influencers.payment_ways/offer_valid_min),
  store/profiles (_save_products, set_influencer_sales), core/sales (_product_problems, product_id),
  core/dialog (Zahlungswege), core/characters, influencer.proto PriceItem 4–14, commands.proto
  CreateOffer 9, InfluencerBlock (Produktzeilen, Zahlungswege, Gültigkeit), CustomerPanel
Nachweis: test_products, test_customer_orders, volle Suite 299 grün; Chrome-E2E isoliert 25/25 (neu
  products.spec.ts), lesend am echten Cockpit 10/10; echte Migration 37→38 mit Sicherung, Telegram
  wieder angemeldet
Behoben dabei: Influencerin-Block klappte nach dem Speichern zu und verlor die Bestätigung (Schlüssel
  mit Revision); Zahlenfelder ohne sichtbare Beschriftung; Einstellungstest zählte Seed-Konten mit
NOT_RUN: Angebot an einen echten Kunden (keine Engine mit Nutzung production, keine Influencerin in
  der echten Datenbank)
Ergebnis: CODE (Integration isoliert belegt), Kundenlauf NOT_RUN
Bearbeiter/Datum: Claude, 18.11.2026

ID: C5.1 (Influencerin vollständig) / BUG-020
Commit: siehe git log „C5.1“ / store/customers (customer_figures), CustomerSummary 12–15, customer-page Filter,
  CustomerList (Figur, Filter), Channels (Kanalzeile je Plattform), graphite.css (--g-figure-*, .g-ftag)
Nachweis: test_accounts (zwei Figuren ohne Vermischung, Filter), Chrome-E2E isoliert tests/figures.spec.ts
NOT_RUN: zwei echte Konten (zweites Konto anlegen mit SP2 9b)
Beobachtung: ein voller Backend-Lauf mit einem Fehler (Test nicht protokolliert), danach 8 volle Läufe grün –
  vermutlich zeitabhängiger Test; bei Wiederauftreten mit -rf festhalten
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 4 Rest (freie Default-Anweisungen, B5.4a)
Commit: siehe git log „free default instructions“ / workflows/ai/default_instruction_melody.*, models
  (InstructionSpec), llm.instruct, core/instruction.py, core/cloner (_cloner_instruction), Migration 37,
  WorkflowInfo 24, Instructions.tsx
Nachweis: tests/test_instruction.py, Backend 295; Chrome-E2E isoliert 23/23, lesend echt 10/10; echter Lauf
  ComfyUI 2 (Deutung korrekt, 1,1 s)
NOT_RUN: Trefferquote mit Testsatz (Qualifikation)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 8 (Kundentest Chat)
Commit: siehe git log „SP4 step 8“ / core/chat.py (_dialog_test, Rahmen, _test_reset), core/cloner (feste Wörter
  vor der Betriebsart, mode_words), Migration 36, Befehle 63 und 37 (test_delay), DefaultPanel (Kundentest)
Nachweis: tests/test_kundentest.py, Backend 293; Chrome-E2E isoliert 22/22
Nachweis echt: Migration 35→36 mit Sicherung, Wiederanmeldung, lesend echt 9/9
NOT_RUN: 20 Testnachrichten vom Handy mit Messwerten (Profil/Clara am echten System fehlt – Betreiberangabe)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 7 (Verhalten, E3/E4) / BUG-096, BUG-017 (Textteil)
Commit: siehe git log „SP4 step 7“ / core/behavior.py, core/chat.py (Plan, Lesen/Tippen/Online, Vertröstung),
  Migration 35, Befehl 53, [behavior], channels (mark_read/set_typing/set_online, Postausgang nach Sendezeit,
  Instagram split_text/sender_action), InfluencerBlock (Verhalten)
Nachweis: tests/test_behavior.py (7), test_chat.py (4); Backend 291; Chrome-E2E isoliert 21/21
Nachweis echt: Migration 34→35 mit Sicherung, Wiederanmeldung, lesend echt 9/9
NOT_RUN: Handy-Abnahme 11–13, 16 (Tippanzeige, Lesezeit, zwei Kunden, Neustart in geplanter Antwort), Instagram-
  Signale am echten Konto
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 6 (Dialogbetrieb) / C5.1 (Schalter Text-KI, automatische Antworten) / BUG-077, BUG-097
Commit: siehe git log „SP4 step 6“ / core/chat.py, Migration 34, Befehl 54, models (E20 ai_notice), config
  [dialog] public_contact_cleared, chat_turns, Adapter-Gate für KI-Antworten, Stream/CustomerPanel/InfluencerBlock
Nachweis: tests/test_chat.py (Hinweis zuerst, Antwort geplant, Versand-Gate, falscher Betrag → Entwurf, Storno
  bei neuer Nachricht, Modus draft, Sperre bei Hinweis auf Minderjährigkeit, Handy → manual, Text-KI aus, E21,
  Erzeugung mit neuer Nachricht verworfen, Befehl 54), Backend 284; Chrome-E2E isoliert tests/dialog.spec.ts
Nachweis echt: Migration 33→34 (Tabellenumbau) mit Sicherung, foreign_key_check leer, Nachrichten erhalten,
  Wiederanmeldung 493976404, lesend echt
NOT_RUN: Kundendialog am Handy (braucht Profil/Clara, Testkonto bzw. Rechtsfreigabe E21 – Betreiberangabe)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP3 Schritte 8 und 9 (Kloner-Methode je Befehl, Abnahme mit Figur) / BUG-052 (Teil)
Commit: siehe git log „SP3 steps 8+9“ / models (cloner), core/cloner (LoRA der Figur), core/cloner_compare + app
  `cloner compare`, comfy.provenance (character_lora), WorkflowInfo 23, DefaultPanel (Vorschlag)
Nachweis: tests/test_cloner_compare.py, test_cloner_finish.py (LoRA-Bindung); Regression: Backend 280, Chrome-E2E
  isoliert 18/18, lesend echt 8/8; echter Neustart mit Wiederanmeldung
NOT_RUN: Vergleich mit zehn Vorlagen je Befehl und Abnahme der Default-Kette mit Figur (Charakterfotos und trainierte
  LoRA fehlen – Betreiberangabe; Modellqualifikation)
Ergebnis: CODE
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP1 Schritte 6, 7, 8, 9, 11 (Chat-Wort), 12 (Optionen, Aufträge, Abschluss, Postausgang, Betriebsart)
Commit: siehe git log „SP1 steps 6-9, 11, 12“ / core/cloner.py, cloner_text (options, finish_height), core/orders
  (extra, Abbruch meldet Kloner), store (Migration 33, cloner_returns, outbox-Reihenfolge, set_account_mode),
  channels/telegram (Postausgang), Befehl 37 additiv, DefaultContact 12–15, DefaultPanel
Nachweis Unit/Integration: tests/test_cloner_finish.py (8 Fälle), test_cloner_chain.py, test_channels.py
Nachweis echt: Migration 32→33 mit Sicherung, Wiederanmeldung, trace; Chrome-E2E isoliert tests/default-sp1.spec.ts
  (setzen, übernehmen, neu laden, zurücksetzen), lesend echt
NOT_RUN: SP1-Abnahme 1–8 am Handy (braucht Workflows im Default-Kontakt und Modelle; Neustart im Lauf)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP1 Schritte 4 und 5 (Referenzen, Vorprüfung und Antwort) / BUG-057, BUG-075 (Teil)
Commit: siehe git log „SP1 steps 4+5“ / core/cloner.py (_cloner_entry, _cloner_refs, _album_quiet, _cloner_state),
  cloner_text (Zustände, Antworten), config [cloner], store (recent_unassigned_media), Stream.tsx (Zustandsmarke)
Nachweis: tests/test_cloner_chain.py, test_channels.py; Chrome-E2E isoliert tests/cloner-cards.spec.ts
NOT_RUN: Handy-Abnahme SP1 1–5 (Workflow im Default-Kontakt fehlt am echten System, Nachricht 39)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP1 Schritt 1 (Rückverfolgung)
Commit: siehe git log „SP1 step 1“ / core/trace.py, app `trace`
Nachweis: tests/test_trace.py; echt lesend am laufenden System: Nachricht 39 zeigt die Unterbrechung „Workflow
  leer“ (BUG-057), DF-O-000007 mit drei Jobs samt prompt_id und Medien
Ergebnis: PASS (CLI, nur lesend)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP2 Schritte 6 und 7 (ungeklärter Versand, KI-Hinweis erneut) / SPEC-009, BUG-016, BUG-021
Commit: siehe git log „SP2 steps 6+7“ / store/messages (match_unknown, unknown_outgoing, known_platform_ids,
  Karte bei unknown, queue_ai_notice), channels/telegram (_late_result, _resolved, _settle_unknown,
  _history_since, own:<Chat>), channels/instagram (offene Liste aus SQLite), core/messages (Befehl 66),
  Stream.tsx (UnknownActions), CustomerPanel (KI-Hinweis erneut)
Nachweis Unit/Integration: tests/test_unknown_send.py – Zeitablauf → unknown mit Karte, nie im Postausgang;
  spätes Send-Update → sent mit Karte, Abgleich danach ohne ÜBERGABE; spätes Fehl-Update → failed mit Grund;
  Verlauf nach Neustart: Treffer → sent, kein Treffer → failed mit Beleg, laufender Versand → unknown, schon
  vergebene ID zählt nicht; Teil-IDs mehrteiliger Sendung nie als fremd; KI-Hinweis erneut nur nach failed;
  Befehl 66 über HTTP (nur unknown, mark_sent, resend als Kopie und als KI-Hinweis, unbekannte Aktion, ohne
  Verbindung abgewiesen); test_instagram – Echo nach Neustart über SQLite; test_customer_orders – Zustellung
  unknown: Befehl 47 abgewiesen, 66 resend → alter Versuch failed, neuer pending
Nachweis echt: Neustart mit Abgleich nach der Anmeldung (0 offene Sendungen), Wiederanmeldung 493976404;
  Chrome-E2E isoliert tests/messages-unknown.spec.ts (Warnung, Abweisung ohne Verbindung, als gesendet
  markieren per Push, KI-Hinweis erneut), lesend echt
NOT_RUN: echter TDLib-/Meta-Zeitablauf mit späterem Echo, echte Zustellung an einen Kunden über 66
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP2 Schritt 5 (Telegram-Eingang vervollständigen) / BUG-015
Commit: siehe git log „SP2 step 5“ / config (ignored_chat_ids), channels/telegram (_edited, _deleted, Beschriftung,
  _stopping), store/messages (edit_platform_message, delete_platform_messages), Migration 31,
  ConversationItem 15–17, Stream.tsx (bearbeitet/gelöscht), graphite.css (.g-orig, data-deleted)
Nachweis Unit/Integration: tests/test_telegram.py – 777000 nie gespeichert (Test-Chat und Produktivbetrieb, keine
  TDLib-Abfrage), Bearbeiten zweimal (erster Text bleibt, zwei Ereignisse, unverändert/unbekannt ohne Wirkung),
  Löschen nur endgültig und nicht aus dem Speicher, Inhalt bleibt, gelöscht nicht mehr bearbeitbar, Mapper liefert
  15–17; Beschriftung nur am ersten von drei Anhängen; Beenden schließt TDLib und verarbeitet danach nichts
Nachweis echt: Migration 30→31 mit Sicherung; Befund beim Neustart (alter Prozess: authorizationStateClosing gegen
  geschlossene Datenbank) behoben und mit zweitem Neustart bestätigt (Beenden ohne Fehler, Wiederanmeldung
  493976404); Chrome-E2E isoliert tests/messages-edit.spec.ts (bearbeitet mit erstem Text, gelöscht, Neuladen),
  lesend echt
NOT_RUN: Bearbeiten/Löschen am Handy in einem echten Chat, echter 777000-Code-Eingang
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP2 Schritt 4 (ein TDLib-Empfänger) / BUG-049
Commit: siehe git log „SP2 step 4“ / channels/tdjson.py (Receiver je Bibliothek, TdJson.close/wait_closed),
  channels/telegram.py (Datenverzeichnis und DB-Schlüssel je Konto, Schließen beim Beenden/Neustart),
  core/base (beliebig viele Telegram-Adapter, `_adapter` über gebundene Konto-ID), Konto der Konversation in
  Versand/Zustellung/Rückversand/Fenster, Befehl 39 additiv `key` (Feld 4), Befehle 39/40 aus der Kanalkarte mit
  Kürzel
Nachweis Unit/Integration: tests/test_tdjson.py – zwei Instanzen erhalten je ihre Ereignisse über genau einen
  Thread (td_receive nur aus einem Thread), Abmelden → neue Instanz am selben Thread, 20 Ereignisse je Konto ohne
  Verlust in Reihenfolge, close meldet ab und lässt offene Anfragen sichtbar scheitern; tests/test_accounts.py –
  zweites Konto mit eigenem TDLib-Verzeichnis und Schlüssel, Befehl 39/40 erreichen das genannte Konto über HTTP,
  Adapter eines nicht angemeldeten Kontos über die gebundene Konto-ID
Nachweis echt: echtes Cockpit neu gestartet, Telegram über den gemeinsamen Empfänger wieder angemeldet
  (493976404); Chrome-E2E isoliert: zwei Telegram-Konten mit je eigener Karte und eigenem Zustand
  (tests/settings.spec.ts), lesend echt
NOT_RUN: echtes Abmelden und Anmelden mit Bestätigungscode (braucht den Betreiber), zweites echtes Telegram-Konto
  (Abnahme SP2 Punkt 1, Konto anlegen erst mit 9b)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP2 Schritt 1 (Daueraufgaben unter Aufsicht) / BUG-015
Commit: siehe git log „SP2 step 1“ / core/supervise.py, web/http.lifecycle, channels (task_error), payments/chain
Nachweis: tests/test_supervise.py – Neustart mit wachsender Pause und Meldung, Abbruch; Fehler im Versand →
  nächste Nachricht geht raus, Meldung im Kanal-STATE, nach Erholung gelöscht; echter Cockpit-Neustart mit
  Telegram unter Aufsicht
Ergebnis: TEIL (Mac-Lauf mit echtem Versandfehler NICHT GELAUFEN)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP2 Schritt 9a (Kanalkonten als Liste, Datenmodell)
Commit: siehe git log „SP2 step 9a“ / store/accounts.py (Migration 30), core/base (Übernahme, Adapter je Konto),
  core/messages (STATE 8, Befehl 40 assign_influencer, KI-Hinweis über Konto), store/customers (Sperre je Identität)
Nachweis Unit/Integration: tests/test_accounts.py – Übernahme einmal, Bindung der Konto-ID, fremde ID abgewiesen,
  Zuordnung, Sperre über Akten derselben Plattform-Identität und Erbe neuer Akten, STATE 8 und Befehl 40 über
  HTTP; test_channels – KI-Hinweis ohne Konto-Influencerin abgewiesen
Nachweis echt: Neustart mit Migration 30, Telegram-Konto übernommen (Testbetrieb, Test-Chat, Default-Absender),
  an 493976404 gebunden, Anmeldung unverändert; Chrome-E2E isoliert (Zuordnen, Neuladen), lesend echt
Ergebnis: TEIL (zweites Telegram-Konto mit SP2 Schritt 4; Pflege im Cockpit 9b in Etappe E)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 5 (Gedächtnis, B5.3)
Commit: siehe git log „SP4 step 5“ / store/memory.py (Migration 29, FTS5), core/memory.py, Befehl 52, EVENT 32,
  /api/v1/memory-page, MemoryView
Nachweis Unit/Integration: tests/test_memory.py – FTS-Treffer zuerst, Bereiche/Sitzungen getrennt, Ersetzen mit
  Verlauf, Löschen, Neustart, Auswahl je Ebene, fremde ID nie ersetzt, Wiederholung, Schemafeld memory;
  tests/test_ai_studio.py – Einstufung schreibt Gedächtnis (Quelle Lauf #N), nächster Lauf bekommt es (Treffer in
  ai_runs.context), Befehl 52 inkl. Bereichsschutz, Seitenabfrage mit Kontextinspektor, Wiederholung → neuer Lauf
Nachweis echt (kurz): ComfyUI 2 – gültige memory-Einträge (Name, Wohnort, Vorliebe); replaces beim Umzug nicht
  gesetzt (Profilinhalt); Chrome-E2E isoliert (Notiz, Korrektur, Inspektor, Löschen)
NOT_RUN: Gedächtnistest 100–200 Schritte mit Neustart (Qualifikation)
Ergebnis: TEIL (Kunden- und Kundentestbereich ab SP4 Schritt 6/8)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 4 (strukturierte Ergebnisse, E26)
Commit: siehe git log „SP4 step 4“ / core/assessment.py, core/evaluate.py, app `ai eval`, Testsatz, KiStudio
Nachweis Unit/Integration: tests/test_assessment.py – Schema-Vertrag streng (sechs Verstöße mit Grund), Folgen nur
  autorisiert (Angebot nie bei Hinweis auf Minderjährigkeit), Sperre setzt under_18 und genau eine Karte, Testsatz
  ≥ 50 Fälle mit ≥ 10 Manipulationen, Auswertung (Verfehlungen und Fehlalarme getrennt); test_ai_studio – Einstufung
  und Folgen im EVENT
Nachweis echt (kurz): `ai eval` 8 Fälle mit Testprofil auf ComfyUI 2 – Schema 8/8, Treffer 8/8 (nur Smalltalk);
  Chrome-E2E isoliert mit echter ComfyUI 2 (Einstufung im KI-Studio)
NOT_RUN: voller Testsatz mit dem Betreiberprofil (Qualifikation; Abnahme Verfehlungen 0)
Ergebnis: TEIL (Sperre an der Akte ab Schritt 6; Qualifikation später)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 3 (Gates statt sprachlicher Regelprüfung, SPEC-017)
Commit: siehe git log „SP4 step 3“ / core/dialog.py, core/ai._llm_run, config [dialog], Migration 28, KiStudio
Nachweis Unit: tests/test_dialog.py – Beträge in allen Schreibweisen nur aus der Preisliste, Zahlungswege nur
  freigegebene (ganzes Wort), Schema, Minderjährigkeit, sechs Kundenkontext-Gates, Fakten aus der Konfiguration
Nachweis Integration: tests/test_ai_studio.py – ungültige Einstufung → zweiter Lauf; 30 € + Überweisung →
  ENTWURF mit beiden Gründen; zweimal ungültig → ENTWURF (schema); HTTP + WebSocket
Nachweis echt (kurz): ComfyUI 2, Fakten mit Zahlungswegen – nur Amazon-Gutschein genannt, Preise richtig,
  Gates bestanden; Chrome-E2E isoliert mit echter ComfyUI 2 (Gate-Abzeichen je Antwort)
Ergebnis: TEIL (Kundenkontext-Gates CODE bis SP4 Schritt 6; Lieferzeit-Fakten SP5 Schritt 2)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 1 Teil c (Messung 20 Nachrichten, E15)
Lauf 18.11.2026 (echter Mac, ComfyUI 2 Melody Q6_K, ohne Datenbank, Profil „MESSTEST“): 20 zusammenhängende deutsche
  Testnachrichten mit Verlauf (12 Wechsel), je Nachricht Einstufung + Antwort in einer Einreichung
Ergebnis warm: p50 2,3 s · p95 3,1 s · max 3,2 s; Einstufung 19/19 gültig, kein JSON in der Antwort
Ergebnis bei Bildrender (LUSTIFY SDXL direkt auf ComfyUI 1, 75,6 s, Ausgabedatei danach gelöscht): 9 Nachrichten
  p50 8,4 s · p95 9,9 s · max 9,9 s; Einstufung 9/9 gültig
Fachlich: Ehrlichkeitsfrage wahrheitsgemäß, Preise aus den Fakten richtig; erfunden: Lieferzeit und Zahlungsweg
  „Überweisung“ (Fakten enthielten beides nicht) → Fakten um Zahlungswege/Lieferzeit, Gates Schritt 3
Befund: /free entlädt Melody nicht (RSS 23,9 GB vor und nach); „kalt“ nur nach Neustart von ComfyUI 2 (22 s)
Nicht gelaufen: Messung bei Videorender (lange Läufe derzeit nicht freigegeben) → E15 offen
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 1 Teil b (keep_loaded, beide Instanzen, Aufwärmlauf, STATE 11) / BUG-061 / BUG-085
Commit: siehe git log „SP4 step 1b“ / config.ComfyConfig.keep_loaded, core/render._admit + _jobs_active,
  core/ai (_llm_run, maybe_warmup, _ai_status), nodes/llm (on_submit), app._comfy_start_all, KiStatus.tsx
Behauptung: BESTÄTIGT (Starter startete nur Instanz 1; Zulassung hätte Melody entladen)
Nachweis Integration: tests/test_ai_studio.py – keep_loaded: Zulassung startet ohne Entladen, ohne Markierung wird
  entladen (Regel entfernt: rot); Aufwärmen einmal je Instanzstart, gestoppt setzt zurück, neuer Start wärmt
  erneut, STATE 11 mit Engine, Zeit, letzten Läufen; Warteschlange ordnet laufenden Sprachlauf zu; comfy start
  startet beide, eine scheiternde hält die andere nicht auf
Nachweis echt: `comfy start --json` → media und ai already_running; Cockpit-Neustart → Aufwärmlauf 0,4 s
  (ai_runs warmup), KI-Status im echten Cockpit (Chrome); kalter Aufwärmlauf nach Neustart von ComfyUI 2: NICHT
  GELAUFEN (produktive Instanz nicht neu gestartet)
Regression: Backend 226 grün, Frontend Build, 14 Unit-Tests, 10 Browser-Tests isoliert, 6 lesend echt
Ergebnis: BUG-061 TEIL (Autostart/Ruhezustand SP6), BUG-085 TEIL (Einschalten nach E15-Messung)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 1 Teil a (Sprachworkflow clara_chat_melody, llm.generate, ai_runs, KI-Studio) / BUG-095 / BUG-098
Commit: siehe git log „SP4 step 1a“ / media/models.py (Engine-Art text, TextSpec, _text_problems), nodes/llm.py
  (generate, parse_classification), core/ai.py (Befehle 49/50, EVENT 31), store/ai.py, Migration 27,
  workflows/ai/clara_chat_melody.*, manifest (melody1437_q6k, melody_chat), frontend KiStudio
Behauptung: BESTÄTIGT (BUG-095: kein leichter Textweg; BUG-098: Text endete mit „keine Ausgabedatei“)
Nachweis Unit/Integration: tests/test_ai_studio.py 5 Tests – Registrierung des echten Graphen; Abweisung bei
  verändertem/abgehängtem Ehrlichkeitsblock, fehlender Einstufung im Nutzertext (E26), ungebundenem Profilblock,
  Ausgabe ohne PreviewAny (ohne Prüfung rot); kein Renderjob; generate mit Ersatz-ComfyUI, die den Graphen auswertet
  (Blöcke, Ehrlichkeit im Systemprompt, Einstufung im Nutzertext, SHA, keine Sitzungsdatei); Befehl 49/50 über
  HTTP + WebSocket (Receipt, EVENT, Verlauf, neue Sitzung, Fehler mit Grund, Abweisungen)
Nachweis echter Mac-Lauf: llm.generate auf ComfyUI 2 mit Melody Q6_K, drei Testnachrichten: warm 1,3–2,6 s je
  Doppellauf, „Bist du echt oder eine KI?“ → „Ich bin eine KI …“, Einstufung als JSON lesbar, keine Sitzungsreste
Nachweis E2E (echter Chrome, isoliertes Cockpit, KI-Instanz = echte ComfyUI 2): Influencerin und Profil über die
  GUI, zwei Nachrichten (0,8 s gesamt je Lauf), Ehrlichkeitsblock im angezeigten Systemprompt, Verlauf im
  Nutzertext, neue Sitzung, nach Neuladen leer; echtes Cockpit nach Neustart (Migration 26→27 mit Sicherung):
  Workflow registriert, lesende Tests grün
Regression: Backend 223 grün (test_persona an registrierten Sprachworkflow angepasst), Frontend Build, 14 Unit-Tests,
  10 Browser-Tests isoliert, 6 lesend am echten Cockpit
Ergebnis: BUG-095 PASS; BUG-098 TEIL (Prüfknoten SP5); SP4 Schritt 1 TEIL (offen: keep_loaded, Start beider
  Instanzen + Aufwärmen, STATE 11, Messung 20 Nachrichten/E15, KI-Hinweis-Knoten nach E21)
Bearbeiter/Datum: Claude, 18.11.2026

ID: BUG-070 (Übersicht ohne Zähler für bezahlte Aufträge in Produktion und Freigabe) / GUI-Prüfung Punkt 5
Commit: siehe git log „BUG-070“ / order.proto OrdersActive.awaiting_review (6), core/orders._orders_active,
  frontend pages/Overview.tsx
Behauptung: BESTÄTIGT – STATE orders.active enthielt Kundenaufträge in review nicht; die Übersicht zählte nur
  die Kandidatenauswahl
Korrektur: awaiting_review = Kundenaufträge im Status review (Betreiberaufträge in review haben keine Freigabe
  und zählen nicht); Übersicht: „Freigaben ausstehend“ = Freigabe + wartet auf Produktion + Auswahl,
  GPU-Warteschlange je Instanz (läuft, wartend, angehalten), Karte „Betrieb“ (Instanzen, Kanäle, Speicher),
  Liste „Offene Aufträge“ (Freigabe/bezahlt → Kundenakte, Auswahl/Lauf → ComfyUI)
Nachweis Integration: tests/test_customer_orders.py::test_customer_order_chain liest den veröffentlichten STATE –
  bezahlt → wartet auf Produktion, review → wartet auf Freigabe, Betreiberauftrag in review nicht, nach
  „Freigeben & senden“ (echter HTTP-Befehl) leer; ohne die Korrektur rot
Nachweis E2E (echter Chrome, isolierter Testserver mit Kundenauftrag in review und einem bezahlten):
  tests/overview.spec.ts – Zeilen FREIGABE und BEZAHLT, Klick öffnet die Kundenakte; zweites Cockpit zeigt das
  Anhalten der Medien-Warteschlange ohne Neuladen (Push)
Mac-Lauf: echtes Cockpit nach Neustart (Schemawechsel) – 5 echte Betreiberaufträge in Auswahl, Instanzen,
  Kanäle und Speicher aus STATE; lesender Browser-Test grün. Echter Kundenauftrag in review: NICHT GELAUFEN
Regression: test_customer_orders, test_orders, test_server 38 grün; Frontend Build, 14 Unit-Tests, alle
  Browser-Tests gegen das echte Cockpit grün
Ergebnis: TEIL (Kundenfreigabe am Mac erst mit dem ersten echten Kundenauftrag)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SPEC-018 (Sitzungsdateien des Sprachknotens) – behoben
Commit: siehe git log „SPEC-018“ / backend/src/darkfluenzer/nodes/llm.py, web/http.py (Start-Sweep)
Korrektur: je Lauf eigener Sitzungsordner <KI-Instanz>/temp/df_llm_sessions/<id> (0700); jeder
  LLMSessionChatNode des Graphen bekommt history_dir = dieser Ordner, eigene session_id, reset_session,
  max_turns 0, persistent_cache off, summarize aus; der Lauf hält flock auf .active (prozessübergreifend, bei
  Absturz frei) und löscht den Ordner im finally; sweep entfernt Ordner ohne gehaltene Sperre und den
  Standardordner output/llm_session_sessions – beim Cockpit-Start, nach jedem Lauf und nach einem Abbruch,
  sobald ComfyUI den Auftrag nicht mehr ausführt (llama.cpp generiert nach dem Interrupt zu Ende und der Knoten
  legt den Ordner neu an – im echten Lauf gefunden)
Nachweis Unit/Integration (Ersatz-ComfyUI über HTTP, schreibt wie der Knoten): tests/test_llm.py, 7 Tests –
  Bindung aller Sitzungsknoten; Erfolg, Ausführungsfehler, Zeitüberschreitung mit Abbruch und spätem Schreiben
  (ohne den verzögerten Sweep rot); Abbruch des Wartenden (KeyboardInterrupt) mit Abbruch in ComfyUI; Neustart
  und spätes Schreiben per Sweep; aktiver Lauf eines anderen Prozesses (flock) bleibt; 8 parallele Kunden mit
  je eigener Antwort und eigenem Ordner; Cockpit-Start entfernt verwaiste Ordner
Nachweis echter Mac-Lauf (ComfyUI 2, Melody Q6_K): Erfolg 0,49 s ohne Reste; abgewiesener Graph ohne Reste;
  Zeitüberschreitung nach 1 s ohne Reste, späte Verlaufsdatei nach 31 s, 1 s später ohne weiteren Lauf entfernt;
  3 parallele Kunden in 0,9 s, jede Antwort nennt die eigene Nummer, keine Reste; echter Cockpit-Neustart mit
  verwaistem Ordner → beim Start entfernt (Log „1 verwaiste Sitzungsordner entfernt“)
Regression: volle Backend-Suite 218 grün; Browser-Smoke (Chrome) gegen das laufende Cockpit grün
Frontend: keine Oberfläche betroffen (Datenhaltung); Kundengespräche bleiben gesperrt bis SP4 Schritte 6–8
Ergebnis: PASS (SPEC-018 am Mac belegt)
Bearbeiter/Datum: Claude, 18.11.2026

ID: BUG-036 / SP4 Schritt 1 Vorbereitung (ComfyUI-LLM-Session, Melody auf ComfyUI 2) / SPEC-018 Probe
Commit: 1396dd1 (launcher/setup_llm_session.sh, setup_comfyui.sh, comfyui.lock.txt)
Wartungsfenster: 0 laufende/wartende Jobs, beide ComfyUI-Warteschlangen leer
Prüfung: Knotenpaket kantan-kanto/ComfyUI-LLM-Session ec2b293c (v1.6.0-2-gec2b293, 08.10.2026) in Quarantäne
  durchgesehen: kein Netz, kein subprocess, kein eval/exec, kein Pickle; schreibt Verlauf/Mitschrift/Cache je
  Sitzung nach output/llm_session_sessions, sofern history_dir leer. llama-cpp-python 0.3.37: nur Quellpaket auf
  PyPI, verlangt typing-extensions, numpy, jinja2 (vorhanden) und diskcache (neu)
Vorher: uv pip freeze 100 Pakete = launcher/comfyui.lock.txt; numpy 2.5.4, torch 2.15.0, torchvision 0.29.2,
  torchaudio 2.11.1, jinja2 3.1.6, typing-extensions 4.16.0
Installation: setup_llm_session.sh mit Lock als Constraint, Metal-Build aus dem Quellpaket 52,8 s; Metal OK
  (recommendedMaxWorkingSetSize 103079 MB)
Nachher: genau + diskcache 5.6.3, + llama-cpp-python 0.3.37; numpy 2.5.4 und torch 2.15.0 unverändert; Lock 102
  Pakete = venv; setup_comfyui.sh ausgeführt (venv unverändert), extra_model_paths.yaml mit LLM: llm und
  frame_interpolation: frame_interpolation (FILM, Rest von BUG-036)
Neustart über das Cockpit (Befehle comfy_stop/comfy_start, Quittung COMPLETED): Medien 6,0 s, KI 4,0 s;
  LLMSessionChatNode auf ComfyUI 2 geladen, Modellauswahl findet Melody1437-26B-A4B-v2.0-Q6_K.gguf
Echter Textdialog (ComfyUI 2, n_gpu_layers −1, n_ctx 4096, je Lauf neue Sitzung, reset_session, max_turns 0):
  drei deutsche Nachrichten, Antwort 1 kalt 22,2 s (ComfyUI 21,81 s, Modell laden), Antworten 2–3 warm 1,0 s
  (ComfyUI 0,64–0,86 s); Ehrlichkeit: auf die KI-Frage antwortet Clara wahrheitsgemäß „Ehrlich gesagt bin ich
  eine KI“; Speicher frei 91,9 → 74,0 GB, ComfyUI-2-RSS 616 MB → 23 GB (GGUF gemappt 21 GB)
Metal: llama.cpp mit verbose in derselben venv: GPU MTL0 (Apple M4 Max), „offloaded 31/31 layers to GPU“,
  Gewichte als MTL0_Mapped; Modell general.name „Melody1437 26B A4B v2.0“, file type Q6_K, 25,23 B Parameter;
  Generierung 88,9 Tokens/s, Prompt-Auswertung 240,9 Tokens/s (kurzer Prompt); Vergleich im Knoten CPU warm 1,5 s
  gegen GPU warm 1,0 s
SPEC-018: NICHT ERFÜLLT ohne Gegenmaßnahme – je Sitzung JSON + .bak (Gesprächsinhalt) und leerer Cache-Ordner in
  local/comfyui_ai/output/llm_session_sessions, trotz reset_session, max_turns 0, persistent_cache off;
  mit history_dir landen alle Dateien nur dort (belegt). Probe-Dateien (18, nur eigene probe-Sitzungen, keine
  Kundendaten) entfernt. Gegenmaßnahme vor Kundengesprächen in SP4 Schritt 1 (llm.py)
ComfyUI 1 danach: LUSTIFY 8 Schritte (Job 104) 43,7 s, Prüfkette Inhalt/Technik/Qualität/Prompttreue/Hände mit
  Werten
Ergebnis: BUG-036 PASS; Melody auf ComfyUI 2 TEIL (Laufzeit belegt, Workflow/llm.py und SPEC-018 OFFEN)
Bearbeiter/Datum: Claude, 18.11.2026

ID: BUG-127 (Testprozess-Leck: verwaiste Fake-ComfyUI)
Commit: siehe git log „BUG-127“ / backend/tests/conftest.py, backend/tests/test_cleanup.py
Befund: 453 Prozesse „python main.py --listen 127.0.0.1 --port N“, alle mit Elternprozess 1: 2 produktive
  (ComfyUI-venv, 8188/8189, Arbeitsverzeichnis local/ComfyUI) und 451 mit dem Test-Interpreter der Backend-venv,
  Arbeitsverzeichnis …/pytest-of-<user>/(pytest-N|garbage-<uuid>)/test_*/local/fake_comfy; Herkunft elf Tests
  (z. B. test_order_commands_push_stages_and_retry 60, test_provenance_of_a_rendered_medium 57)
Bereinigung: jede PID einzeln geprüft (Elternprozess, Interpreter, argv main.py --listen 127.0.0.1, Port ≠
  8188/8189, Arbeitsverzeichnis unter pytest, vorhandenes main.py = Fake), unmittelbar vor dem Signal erneut;
  451 × SIGTERM, 0 × SIGKILL nötig, 0 übrig; 8188/8189 unberührt, beide antworten 200
Ursache: runtime.start startet ComfyUI absichtlich in eigener Prozessgruppe (übersteht Cockpit-Neustarts);
  Tests stoppten die gestartete Fake-ComfyUI nie
Korrektur: conftest.reap_fake_comfy beim Abbau jedes Testprojekts und am Sitzungsende (Prozessgruppe, SIGTERM,
  dann SIGKILL); erkannt nur Test-Interpreter (normierter Pfad – „backend/../local“ und „local“ sind derselbe)
  + main.py + Arbeitsverzeichnis unter dem pytest-Ordner
Nachweis: tests/test_cleanup.py::test_a_test_run_leaves_no_fake_comfy_behind (innerer pytest-Lauf mit zwei
  vorher leckenden Tests): ohne Bereinigung rot (2 zurückgeblieben), mit Bereinigung grün; volle Suite
  211 grün, danach 0 Test-Fake-ComfyUI
Ergebnis: PASS (am Mac belegt)
Bearbeiter/Datum: Claude, 18.11.2026

ID: SP4 Schritt 2 (Promptprofile, Backend) / SPEC-016 Teil
Commit: siehe git log „SP4 step 2“ / store.profiles, core.persona, core.characters, Migration 26, Protos
Behauptung: influencers.persona war ein Textfeld, eine Änderung überschrieb die alte Fassung
Korrektur: unveränderliche Versionen je Influencerin, aktive Version, Befehl 35 additiv (Entwurf), Befehl 68
  (aktivieren/zurücksetzen), STATE 9 mit Blöcken und Versionen; Modellparameter nur aus einem registrierten
  Sprachworkflow mit Grenzen
Nachweis: tests/test_persona.py (Migration 26 mit Sicherung, Unveränderlichkeit per Trigger, Zurücksetzen,
  Trennung je Influencerin, Befehle 35/68 und STATE); volle Backend-Suite 210 grün; Migration an Kopie der
  echten Datenbank (Integrität ok)
Nachtrag 18.11.: KI-Studio · Persona im Frontend (KiStudio.tsx); Browser-Test mit Chrome gegen einen
  getrennten Testserver (eigene Wurzel, Port 8291, ohne Kanäle): Version N aktiv → speichern ergibt N+1 aktiv,
  Vergleich N gegen N+1, Zurücksetzen auf N, Chat-Test gesperrt, keine Konsolenfehler
Ergebnis: TEIL (Promptprofile im Cockpit bedienbar); Übergabe an den Sprachworkflow OFFEN (SP4 Schritt 1)
Bearbeiter/Datum: Claude, 18.11.2026

ID: E17 Fingerzahl (CountHallu-Fingerzähler) – Durchsicht und Probe
Commit: – (nicht eingebaut)
Behauptung: Fingerzahl sollte nach Durchsicht des YOLO-v13-Codes folgen
Befund: Checkpoint ShyFoo/CountHallu-counting_model-RealHand, Revision 7b7ecac, model.pt SHA-256 8a10818f…12b0
  (stimmt mit LFS). Statische Prüfung ohne Entpicklen: nur torch-Module/Rebuild-Funktionen und
  ultralytics.nn (A2C2f, AAttn, ABlock, C3k2, Detect, DetectionModel); gespeichert mit Ultralytics 8.3.179,
  Modell yolov12x.yaml, Klasse „fingertip“ – kein Fork nötig. Laden mit torch.load(weights_only=True) und fester
  Klassenliste in getrennter Umgebung (Scratchpad, YOLO_CONFIG_DIR umgelenkt), Export ONNX/TorchScript;
  ONNX in OpenCV identisch zur Referenz (Abweichung < 0,001, 23/23 gleiche Zählungen, 2,2 s je Ausschnitt CPU)
Probe (Modellqualifikation, 23 Handausschnitte aus der Galerie, Ausschnitt wie DarkfluenzerHandCheck):
  18× 0 Fingerspitzen, auch bei klar sichtbaren Händen mit fünf Fingern; eine Hand mit fünf Fingern → 7;
  auf 256 px wie im Datensatz verkleinert unverändert. Trainiert auf handzentrierten Fotos, nicht auf Händen im
  Bildkontext
Ergebnis: Modellqualifikation NICHT BESTANDEN – nicht als Prüfknoten eingebaut (irreführende Werte). Fingerzahl
  OFFEN (anderer Prüfer nötig); bedingter Reparaturlauf BLOCKIERT, bis ein qualifiziertes Anatomie-Signal
  vorliegt („zählbar“ von CountHallu ist kein Anatomie-Urteil)
Bearbeiter/Datum: Claude, 18.11.2026

ID: BUG-126 (Langvideo-Zusammensetzen: Eingabe-Vorschauen als Ergebnis)
Commit: siehe git log „BUG-126“ / nodes.comfy (Ausgaben sammeln)
Behauptung: BESTÄTIGT im echten Lauf 18.11. (Job 103, Wan 2.2 Remix 480×320, 2 Abschnitte à 33 Frames,
  271 s + 230 s, gesamt 504,5 s): ComfyUI-Historie meldet v0/v1 (LoadVideo) mit type input und save mit
  type output; alle drei wurden als Medien 106/107/108 registriert, Job-Ergebnis 106 = Abschnitt 2
Korrektur: Ausgaben vom Typ input werden übersprungen
Nachweis: tests/test_video.py::test_long_video_segments_resume_after_failure_and_join mit Ersatz-ComfyUI,
  die wie ComfyUI Eingabe-Vorschauen meldet: vorher rot (2 Medien), danach grün (1 Medium, Ergebnis = fertiges
  Video). Derselbe Lauf belegt Abschnittskette und Prüfkette im Zusammensetzen real: 65 Frames, 9 geprüft,
  Inhalt neutral, 0 Sprünge (Werte am fertigen Video 108). Altlast bereinigt 18.11. nach Betreiberfreigabe:
  106 = Abschnitt 2, 107 = Abschnitt 1 (SHA-256 gleich den Dateien unter darkfluenzer_work/job103), keine Prüfwerte,
  kein Artefakt, kein Auftrag; einziger Verweis war das falsche Job-Ergebnis → Job 103 auf 108 gesetzt
  (store.set_job_media), dann Befehl delete_media [106, 107] im laufenden Cockpit: completed, Dateien entfernt,
  108 und Abschnittsdateien bleiben
Ergebnis: CODE (Korrektur), Langvideo-Kette TEIL (am Mac belegt)
Bearbeiter/Datum: Claude, 18.11.2026

ID: B4 Zeitachse (Teil 3): Schlüsselbild aus Dateien, Zeitleiste mit Marken
Commit: f118978 (Workbench, graphite.css)
Behauptung: Schlüsselbilder nur als Upload, keine Zeitleiste
Korrektur: je Schlüsselbild „Aus Dateien“ (Galerie-Medium per ID, Backend prüft den SHA-256, Inhaltsstufe
  zählt mit, FABLE-008); Zeitleiste über die Videodauer (SVG, Marken Start/Schlüsselbilder/Ende, rot =
  außerhalb oder ohne Bild, Klick setzt ein Schlüsselbild)
Nachweis: echter Lauf aus dem Cockpit 18.11. (Playwright mit Chrome, Job 102, LTX 2.5 FLF2V 512×320,
  3 s, 73 Frames, 193,6 s): Start-, End- und Schlüsselbild (1,5 s) aus Dateien, Inhaltsstufe standard;
  Frame 36 entspricht sichtbar dem Schlüsselbild, Frame 72 dem Endbild; Prüfkette: 10 Frames geprüft,
  Inhalt neutral, zeitlich 0 Sprünge; npm run build und 14 Frontend-Tests grün
Ergebnis: TEIL (Kette am Mac belegt; 15 s mit vier Schlüsselbildern = Modellqualifikation, OFFEN)
Bearbeiter/Datum: Claude, 18.11.2026

ID: E17 Teil 4 / SP5 Schritt 7 (Video: Frameprüfung und zeitliche Konsistenz)
Commit: siehe git log „E17 part 4“ / comfy_nodes frames.py, temporal.py; comfy.inject_checks; Manifest
Behauptung: Prüfkette lief nur vor SaveImage; Videos wurden nicht geprüft
Korrektur: Video-Workflows bekommen vor CreateVideo eine Stichprobe (DarkfluenzerFrameSample: jedes 8. und
  das letzte Frame, höchstens 12, [check_frames]) für Inhalt, Technik, Hände, Identität (video = "frames")
  und DarkfluenzerTemporal auf allen Frames (Sprünge, Standbilder, Helligkeitsflackern; video = "all");
  Ziel ist SaveVideo, Werte je Frame mit item (Stelle in der Stichprobe) und der Liste der geprüften
  Frames; Prompttreue und Q-ReAlign (8B/9B) nicht je Frame. Offen: Abschnittsketten (Langvideo) ohne
  Prüfknoten, Schwellen und Entscheidung
Nachweis: tests/test_checks.py::test_video_checks_sample_frames_before_create_video,
  ::test_check_plan_for_video_takes_frame_and_temporal_checks, ::test_frame_sample_and_temporal_measures;
  echter Lauf 18.11. (Job 101, LTX 2.5 i2v 512×320, 2 s, 49 Frames, 135 s): Stichprobe 0,8,…,48 (7),
  Inhalt 7× neutral ≥ 0,99, Technik 7 Werte, Hände keine erkannt, zeitlich 0 Sprünge, 0 Standbilder,
  Änderung Ø 6,8; alle Werte am Videomedium 104 (Ziel SaveVideo 75)
Nachtrag 18.11.: Langvideo – Prüfknoten nur im Zusammensetzen (alle Frames des fertigen Videos,
  Ziel SaveVideo „save“), Abschnitte ohne Prüfung; test_video.py::test_long_video_segments_… (vorher rot)
Ergebnis: TEIL (Einzellauf am Mac belegt; Langvideo CODE, kein langer Lauf; Schwellen OFFEN)
Bearbeiter/Datum: Claude, 18.11.2026

ID: FABLE-014 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-122“) – Teil
Commit: siehe git log „FABLE-014“ / payments.chain.WalletWatcher._confirm_bsc, store.update_confirmations
Behauptung: BESTÄTIGT – BSC-Bestätigungen nur aus der aktuellen Blockhöhe minus Fundblock; eine aus der
  Kette gefallene (Reorganisation) oder fehlgeschlagene Transaktion wäre bestätigt worden; nebenbei
  schrieb jede Runde für jede offene Zahlung ein Ereignis (Block None ≠ gespeicherter Block)
Korrektur: bei Erreichen der Bestätigungszahl eth_getTransactionReceipt: fehlt oder Status ≠ 1 → bleibt
  offen (0 Bestätigungen, Warnung); anderer Block → Block übernommen, Zählung ab dort; unveränderte
  Runden schreiben nichts mehr. Zweite unabhängige Quelle (zweiter RPC-Endpunkt) bleibt OFFEN
Nachweis: tests/test_customer_orders.py::test_bsc_payment_confirmed_only_while_still_in_the_chain (vor
  der Korrektur rot, danach grün); test_customer_orders, test_store, test_server grün
Ergebnis: CODE (Tests rot/grün); zweite Quelle OFFEN
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-013 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-121“) – Teil
Commit: siehe git log „FABLE-013“ / web.commands (_UNLOCKED_COMMANDS)
Behauptung: BESTÄTIGT – der Registry-Lock umschließt jeden Befehl; ein langer Registry-Befehl (Workflow
  übernehmen, bis 120 s) hielt „Abbrechen“ und „Anhalten“ auf
Korrektur: cancel_job und pause_queue laufen ohne den Lock (lesen und ändern keine Registry, danach
  STATE der Warteschlange); alle übrigen Befehle bleiben unter dem Lock, weil er dort Prüfen-dann-Handeln
  über await hinweg schützt – deren Aufteilung bleibt OFFEN (kein einfacher Umbau, Hinweis des Auditors)
Nachweis: tests/test_server.py::test_cancel_and_pause_do_not_wait_for_the_registry_lock (vor der
  Korrektur Zeitüberschreitung, danach grün); test_server, test_orders, test_customer_orders,
  test_telegram, test_training, test_lora, test_checks grün
Ergebnis: CODE für Abbrechen/Anhalten (Tests rot/grün); Aufteilung der übrigen Befehle OFFEN
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-015 (Audit Fable 17.11., P3; im Auditblatt vorläufig „BUG-123“)
Commit: siehe git log „FABLE-015“ / store.request_cancel, core.render (enqueue_existing, _cancel_job),
  media.pipeline.run_render
Behauptung: BESTÄTIGT – der Abbruchwunsch lag nur im Prozessspeicher; nach einem Neustart wurde ein nie
  übermittelter Job erneut eingereiht (lief trotz Abbruch), ein übermittelter wurde abgeholt
Korrektur: Abbruchwunsch als Journal-Ereignis job/cancel_requested; beim Neustart nie übermittelt →
  failed (abgebrochen), übermittelt → ohne Speicherzulassung wieder aufgenommen, die Pipeline beendet den
  ComfyUI-Lauf gezielt und meldet abgebrochen
Nachweis: tests/test_server.py::test_cancel_wish_survives_restart (vor der Korrektur rot, danach grün);
  test_server, test_orders, test_store, test_mainloop, test_training grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-016 (Audit Fable 17.11., P3; im Auditblatt vorläufig „BUG-124“)
Commit: siehe git log „FABLE-016“ / store.db.StoreBase._migrate
Behauptung: BESTÄTIGT – jede Store-Instanz öffnete in _migrate eine Schreibtransaktion (BEGIN IMMEDIATE),
  auch ohne anstehende Migration; hielt ein anderer Schreiber die Sperre, wartete das Öffnen bis zu 30 s
Korrektur: Schemaversion zuerst ohne Sperre lesen; aktuell → sofort fertig; sonst wie bisher in der
  Transaktion erneut prüfen und migrieren
Nachweis: tests/test_store.py::test_opening_a_current_store_needs_no_write_lock (vor der Korrektur rot:
  Öffnen blockiert, danach grün); test_journal, test_lora (Migrationen), test_server grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-017 (Audit Fable 17.11., P3; im Auditblatt vorläufig „BUG-125“)
Commit: siehe git log „FABLE-017“ / channels.telegram._copy_whole
Behauptung: BESTÄTIGT – der Anhang wurde direkt in die Zieldatei kopiert; nach einem Abbruch blieb eine
  halbe Datei, der nächste Versuch übersprang sie („existiert schon“) und speicherte sie als fertig
Korrektur: Kopie über <Ziel>.part und os.replace, Zwischendatei wird immer entfernt (wie bei Instagram)
Nachweis: tests/test_telegram.py::test_interrupted_attachment_copy_leaves_no_partial_file (vor der
  Korrektur rot, danach grün); test_telegram, test_channels grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-007 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-115“)
Commit: siehe git log „FABLE-007“ / web.http.create_public_app, channels.instagram.verify, config
Behauptung: BESTÄTIGT – die öffentliche App (Tunnel) nahm Körper bis max_upload_mb (50 MB) an und las
  sie vor der Signaturprüfung ganz; verify() las den Verify-Token synchron aus dem Schlüsselbund im
  Event-Loop
Korrektur: eigene Grenze instagram.max_webhook_kb (Standard 1024, config.example.toml) für die
  öffentliche App, größere Körper → 413 vor jeder Prüfung; verify ist asynchron, der Schlüsselbund wird
  im Arbeiter-Thread gelesen
Nachweis: tests/test_bugs_v1.py::test_bug002_… (Körper über der Grenze → 413; ohne Korrektur 403, rot)
  und tests/test_instagram.py::test_webhook_signature_and_verify_handshake (Schlüsselbund nie im
  Hauptstrang; vorher rot); test_server, test_channels grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-006 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-114“)
Commit: siehe git log „FABLE-006“ / core.delivery (_place_copy, _delivery_copy), store.artifact_at
Behauptung: BESTÄTIGT – Master (work/<Nr>_ergebnis) und Zustellkopie (sent/<Nr>) hatten je Auftrag einen
  festen Pfad: nach „Neu“ überschrieb die zweite Freigabe den unveränderlichen alten Master (os.replace
  über 0444) und scheiterte dann am eindeutigen Artefaktpfad; „Erneut senden“ überschrieb die schon
  gesendete Zustellkopie
Korrektur: Master nach Inhalt benannt (…_ergebnis_<sha12>), gleicher Inhalt nutzt dasselbe Artefakt;
  _place_copy überschreibt nie anderen Inhalt; Zustellkopie je Versuch in sent/<n>/ mit unverändertem
  Dateinamen
Nachweis: tests/test_customer_orders.py::test_place_copy_never_overwrites_other_content und die neue
  Prüfung in ::test_customer_order_chain (eigene Kopie je Versuch, erste Kopie unverändert) vor der
  Korrektur rot, danach grün; test_store, test_server grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-005 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-113“)
Commit: siehe git log „FABLE-005“ / channels.telegram (_spawn, _auth_step)
Behauptung: BESTÄTIGT – Anmeldeschritte und eingehende Nachrichten liefen als asyncio-Aufgaben ohne
  Referenz (können mitten im Lauf eingesammelt werden); ein unerwarteter Fehler in _auth ging verloren,
  der Kanal blieb in einem alten Zustand
Korrektur: Aufgaben in einer Menge bis zum Ende gehalten; Anmeldeschritt mit Fehlerfang: Log und
  Kanalstatus ERROR „Anmeldung: interner Fehler (<Typ>)“ ohne Fehlertext (keine Anmeldewerte)
Nachweis: tests/test_telegram.py::test_auth_failure_is_visible_and_tasks_are_kept (vor der Korrektur
  rot, danach grün); test_telegram, test_channels grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-003 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-111“)
Commit: siehe git log „FABLE-003“ / approval.check_gate (disk_sha, check_file), core.delivery
Behauptung: BESTÄTIGT – Freigabe, Wiederholung, Gate im Versandmoment und Bestätigung nach dem Versand
  hashten die Artefaktdatei im Hauptstrang (bei Videos Blockade über der SP0-Grenze)
Korrektur: Hash im Arbeiter-Thread (approval.file_sha) und an check_gate/prepare_delivery/add_artifact
  übergeben; nach dem Versand ohne Dateiprüfung (Artefakt und Zustellkopie prüft der Postausgang im
  Versandmoment); ohne übergebenen Hash liest check_gate wie bisher selbst (Kommandozeile, Tests)
Nachweis: tests/test_customer_orders.py::test_customer_order_chain zählt Hash-Läufe im Hauptstrang von
  der Freigabe bis zur zweiten Zustellung: vorher 6 (rot), danach 0 (grün);
  tests/test_store.py::test_file_check_belongs_to_the_send_moment
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-009 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-117“)
Commit: siehe git log „FABLE-009“ / frontend/src/core/commands.ts
Behauptung: BESTÄTIGT – sendCommand behandelte jede Nicht-2xx-Antwort wie Verbindungsverlust: drei
  Versuche (bei 413 jedes Mal der ganze Körper), dann „Verbindung unterbrochen“; settle bekam 404 und
  sendete alle 30 s erneut, ohne Ende, Knopf gesperrt
Korrektur: 4xx (vor dem Befehlsjournal abgewiesen) ist endgültig: ein Versuch, Meldung
  „Abgewiesen (413): Befehl zu groß“; wird der in settle erneut gesendete Befehl abgewiesen, ist das der
  Endzustand; 5xx und Netzfehler bleiben „Ergebnis unbekannt“ mit derselben request_id
Nachweis: frontend tests/commands.test.ts (4xx endgültig und settle endet; 5xx unbekannt) vor der
  Korrektur rot, danach grün; alle 14 Frontend-Tests und npm run build grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-010 (Audit Fable 17.11., P2; im Auditblatt vorläufig „BUG-118“)
Commit: siehe git log „FABLE-010“ / media.gallery.media_candidates
Behauptung: BESTÄTIGT – die Sperre „gehört zu einem laufenden Job“ galt nur für ComfyUIs Ausgabeordner;
  die schon nach local/evaluation/<engine>/ geladene Ausgabe wurde nach 10 s Ruhe ohne Job-Bezug
  indiziert, wenn die Nachbearbeitung (Prüfwerte, Registrierung) länger dauerte
Korrektur: seit dem Start eines laufenden Jobs entstandene Dateien warten in beiden Galerie-Quellen bis
  zu seinem Abschluss; danach kommt die Ausgabe über das Journal mit Job-Bezug
Nachweis: tests/test_store.py::test_comfy_output_of_a_running_job_is_indexed_with_the_job (neue Prüfung
  vor der Korrektur rot, danach grün); test_journal, test_server, test_orders grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-012 (Audit Fable 17.11., P2/P1-Kandidat; im Auditblatt vorläufig „BUG-120“)
Commit: siehe git log „FABLE-012“ / approval.confirm_sent, core.delivery._confirm_delivery, Migration 25
Behauptung: BESTÄTIGT – nach echtem Versand prüfte confirm_sent das Gate erneut und brach ab; Zustellung
  blieb pending, Auftrag approved, „Erneut senden“ gesperrt, der Abgleich nach Neustart scheiterte
  jedes Mal gleich, sichtbar nur im Log
Korrektur: gesendet ist eine Tatsache – Zustellung immer sent; verletztes Gate steht in
  deliveries.gate_violation (Migration 25, Versand-Trigger lässt sent nur mit Grund zu) und in der Karte
  „VERSENDET · … · GATE NACH VERSAND: …“; Auftrag nur aus approved zu delivered
Nachweis: tests/test_store.py::test_refund_during_sending_is_recorded_and_reported,
  ::test_file_check_belongs_to_the_send_moment (seit FABLE-003: Datei nur im Versandmoment; vorher rot),
  ::test_cockpit_card_names_the_gate_violation_after_sending; Migration 24→25 an einer Kopie der echten
  Datenbank (Integrität ok)
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026

ID: FABLE-011 (Audit Fable 17.11., P2/P1-Kandidat; im Auditblatt vorläufig „BUG-119“)
Commit: siehe git log „FABLE-011“ / media.gallery.delete_media, core.registry._delete_media
Behauptung: BESTÄTIGT – Ordner-Scan und Hashing liefen in der Schreibtransaktion (Sperre für alle anderen
  Schreiber); Dateien wurden in der Transaktion gelöscht, ein Fehler rollte den Index zurück, gelöschte
  Dateien blieben weg
Korrektur: suchen und hashen ohne Sperre, Index-Einträge in kurzer Transaktion entfernen, danach Dateien löschen;
  nicht löschbare Dateien bleiben liegen und werden im Befehl gemeldet (erscheinen beim nächsten Abgleich
  wieder) – nie ein Index-Eintrag ohne Datei
Nachweis: tests/test_journal.py::test_delete_media_scans_without_the_write_lock_and_keeps_index_and_files_apart
  (vor der Korrektur rot, danach grün); bestehender Löschtest in test_server.py grün
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: FABLE-001 (Audit Fable 17.11., P1; im Auditblatt vorläufig „BUG-109“)
Commit: siehe git log „FABLE-001“ / web.commands._execute
Behauptung: BESTÄTIGT – ein unerwarteter Fehler im Befehl (nicht in _COMMAND_ERRORS, z. B. der Wallet-Assert in
  core.sales) ging als HTTP 500 ohne Journal hinaus; die Wiederholung derselben request_id lief erneut
Korrektur: jeder sonstige Fehler wird protokolliert (Traceback im Log) und festgehalten: angenommen, dann
  terminal „unknown“ mit Fehlerart („Ergebnis unbekannt, Zustand prüfen“), weil Teile schon gespeichert sein
  können; dieselbe request_id führt nie ein zweites Mal aus. Der Wallet-Assert selbst bleibt SP5.
Nachweis: tests/test_server.py::test_unexpected_command_error_is_journaled_and_never_repeated – vorher rot
  (HTTP 500), danach grün; Gesamtlauf 193 bestanden
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: FABLE-002 und FABLE-004 (Audit Fable 17.11., P1; im Auditblatt vorläufig „BUG-110“, „BUG-112“)
Commit: siehe git log „FABLE-002“ / core.render.render_worker, _admit; media.pipeline.run_render
Behauptung FABLE-002: BESTÄTIGT – scheiterte free() der ruhenden anderen Instanz, ging der Fehler aus der
  Zulassung, der einzige Weckruf war verbraucht, die Warteschlange stand
Behauptung FABLE-004: BESTÄTIGT – Galerie-Eintrag, Messwerte und Abschluss lagen außerhalb des Fehlerfangs;
  ein Fehler dort ließ den Job auf running
Korrektur: Zulassung überspringt eine nicht entladbare Instanz (Warnung) statt abzubrechen; nach einem Fehler
  stößt die Bahn wartende Jobs nach einer Beobachtungsrunde erneut an; Nachbearbeitung im Fehlerfang, Job
  endet als failed mit „Nachbearbeitung fehlgeschlagen: …“
Nachweis: tests/test_server.py::test_queue_survives_a_failing_free_of_the_other_instance,
  tests/test_orders.py::test_failed_post_processing_ends_the_job_as_failed – beide vor der Korrektur rot
  (ComfyError aus der Zulassung bzw. Job running), danach grün; Gesamtlauf 192 bestanden
Ergebnis: CODE (Tests rot/grün; Mac-Lauf folgt mit der Etappe)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: FABLE-008 (Audit Fable 17.11., P0; im Auditblatt vorläufig „BUG-116“) und BUG-109
Commit: siehe git log „FABLE-008“ / media.pipeline.create_render (upload_tiers), video_plan (seconds)
Behauptung FABLE-008: BESTÄTIGT – weitere Schlüsselbilder (bb7c98f) gingen nicht in die Inhaltsstufe ein; ein
  explizites oder fremdes Schlüsselbild ergab ein Video der Stufe standard (Klasse von BUG-047)
Nachweis: tests/test_orders.py::test_keyframes_count_for_the_content_tier (Galerie standard/explizit, fremdes Bild,
  gemischt, Auftrag und Wiederholen) – vor der Korrektur rot („standard“ statt „explizit“), danach grün;
  ::test_retry_of_a_seconds_video_keeps_its_length (BUG-109) – vorher rot („Abschnitte gibt es … nicht“)
Ergebnis: CODE (beide; Tests rot/grün, Mac-Lauf folgt mit der Etappe); Auditregister docs/bugs_fable_v1.md führt FABLE-001…017, BUG-109 ff. bleiben hier
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-108
Commit: siehe git log „BUG-108“ / nodes.comfy._take_dynamic, _default, _is_autogrow, check_graph
Behauptung: BESTÄTIGT (Vorlage video_ltx2_5_flf2v nicht übernehmbar; ltx25_i2v mit 5 Scheinfehlern)
Nachweis: tests/test_workflows.py::test_template_import_defaults_missing_dynamic_values_and_accepts_autogrow
Mac-Lauf 17.11.2026: Vorlage video_ltx2_5_flf2v → 42 Knoten, SaveVideo codec „auto“, Prüfung nur noch
  fehlende Modelldateien (Zuordnung folgt); ltx25_i2v Prüfung ohne Befund
Teil 2: api_to_ui legt je belegtem wachsendem Untereingang einen Slot an und verbundene Unterwerte einer
  dynamischen Auswahl als eigene Eingänge (vorher nur als Wert im Widget, im Editor nicht nutzbar);
  Test test_api_to_ui_keeps_every_used_autogrow_input; ltx25_flf2v UI/API je 57 Verbindungen
Ergebnis: PASS
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: E16 Teil 1 / SP5 Schritt 7 (Prüfkette messen, Inhaltsprüfung)
Commit: siehe git log „check chain“ / comfy_nodes/darkfluenzer/content.py; nodes.comfy.inject_checks, check_targets;
  media.pipeline.check_plan, _check_media; media.models.CheckSpec; web.mappers._flat
Nachweis: tests/test_checks.py (Einsetzen vor jedem SaveImage außer Maske, Bildweg unverändert; Plan nur mit
  Modellen, Identität nur mit Figur, keine Analyse/Training; Werte am geprüften Ausgabemedium, values/labels)
Mac-Lauf 17.11.2026: timm 1.0.31 in der ComfyUI-venv (nur dieses Paket), Modelle geladen und SHA geprüft,
  ComfyUI 1 neu gestartet; LUSTIFY Job 95 → Knoten 8 an Ausgang 7, Medium 98: low 0,88, Körperstellen gemessen
  E17 Teil 1: technische Qualität (Schärfe, Rauschen, Beschnitt, Kontrast) als Knoten; Job 96 → Medium 99 mit Inhalt
  und Qualität (Knoten 9000/9001); Test tests/test_checks.py::test_quality_node_measures_blur_noise_and_clipping
  E17 Teil 2: Q-ReAlign-Pro-9B als Knoten (12 Dateien mit SHA-256, Download einmal hängen geblieben und neu
  gestartet); Job 99 → Medium 102 mit Inhalt, Technik und Qualität 0,998; Freigabe beim /free belegt (Log)
  E17 Teil 3: Prompttreue (Qwen3-VL-8B, VQAScore) und Hände (MediaPipe + CountHallu) als Knoten; Job 100 →
  Medium 103 mit fünf Prüfungen; Befund unterwegs: Qwen antwortet „yes“ klein, nur „Yes“ gezählt ergab 0,15 statt
  1,0 – jetzt über alle Schreibweisen; Download-Status „copied“ galt als Fehler (Exit 8), behoben
Ergebnis: TEIL (Implementierung, messen); Schwellen, Entscheidung, weitere Prüfer OFFEN
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: SP3 Schritt 3 (Training mit Wiederaufnahme-Checkpoints)
Commit: siehe git log „SP3 step 3 checkpoints“ / comfy_nodes/darkfluenzer/train.py (DarkfluenzerTrainLora);
  media.pipeline.checkpoint_dir; core.characters (Character.checkpoints); core.render (Datensatz beim Wiederholen)
Nachweis: tests/test_training.py (Ordner je Figur, Datensatz und Einstellungen, unabhängig von Gesamtschritten;
  Checkpoints im STATE mit Ursprungsjob, unlesbare entfallen)
Mac-Lauf 17.11.2026: ComfyUI 1, LUSTIFY SDXL, 2 Bilder 512 px, 6 Schritte, Checkpoint alle 2: A durchgehend
  (19,2 s); B nach Checkpoint 2 über /interrupt abgebrochen, derselbe Graph erneut → setzt bei 2 fort (14,2 s).
  Verlust A = B je Schritt, Gewichte und LoRA-Datei Abweichung 0,0, Schrittzahl 6. Gefunden und behoben:
  Checkpoint-Tensoren im inference_mode geladen; Optimiererzustand vor dem Verschieben auf mps; Startgewichte
  aus dem Prozess-Zufall (jetzt aus dem Seed)
Ergebnis: TEIL (Implementierung, Abnahme Fortsetzen bestanden); volles Charaktertraining OFFEN (keine Fotos)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-091 / BUG-098 (Messwert-Teil) (SP3 Schritt 7)
Commit: siehe git log „SP3 step 7“ / comfy_nodes/darkfluenzer/face.py; nodes.comfy.collect_graph (CHECKS_KEY);
  media.pipeline.identity_overrides, _input_media; store.media.add_media_checks; web.mappers._job_completed
Behauptung: BESTÄTIGT (Gesichtsdateien ohne Engine; collect_graph kannte nur Dateien)
Nachweis: tests/test_checks.py (Engine identity, Prüf-Workflow; Messwerte aus der Historie, Lauf ohne Datei gültig,
  unlesbare Werte = Fehler; Referenzordner der Figur und [identity]-Werte als Eingänge, media_checks und
  JobCompleted.checks; Knoten mit den echten Modellen: ohne Referenz, ohne Gesicht, Bild gegen sich ≈ 1)
Mac-Lauf 17.11.2026: OpenCV in der ComfyUI-venv (nur dieses Paket, numpy unverändert), ComfyUI 1 neu gestartet,
  Knoten geladen; direkter Lauf: gleiches Bild SFace/AuraFace 1,000, andere Person 0,055/0,050; Browser-Kette
  „Prüfen · Gesichtsidentität“ für Clara → Job 92 → keine_referenz (reference/ leer), Gesicht 123 px, Medium 94
Ergebnis: TEIL (Implementierung); Identitätswerte gegen echte Referenzfotos OFFEN (Qualifikation); Textweg für
  Sprach-Workflows bleibt BUG-098/SP4
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: SP3 Schritt 6 (aktive LoRA je Figur und Architektur)
Commit: siehe git log „SP3 step 6“ / store.profiles.set_active_lora, active_loras; core.characters._lora_activate;
  media.pipeline.active_lora, check_lora(character=…); core.orders.create_order(character_id=…)
Nachweis: tests/test_lora.py (Migration 22 mit Sicherung, genau eine aktive je Figur und Architektur,
  Probe-Prompts; Auftrag für eine Figur nie mit fremder LoRA, auch nicht bei falschem Eintrag; Befehl 64
  über den Server mit STATE arch/active/strength, fremde LoRA abgelehnt, Aufheben)
Mac-Lauf 17.11.2026: echte Datenbank 21 → 22, Sicherung vor-migration22, Cockpit ohne Fehler; Smoke-Test grün;
  Formular „Charakter-LoRA“ im echten Cockpit (nur „ohne“, noch keine LoRA)
Ergebnis: TEIL (Implementierung); Aktiv setzen mit echter LoRA und Probebilder OFFEN (keine Fotos)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-052 (LoRA-Teil) / SPEC-012 (SP3 Schritt 5)
Commit: siehe git log „SP3 step 5“ / media.models.LoraSlot, nodes.comfy.bind_lora, with_trigger,
  media.pipeline.check_lora, lora_use; core.orders (create_order, select_candidate, retry_stage)
Behauptung: BESTÄTIGT (kein Workflow hatte einen Lader für die Charakter-LoRA)
Nachweis: tests/test_lora.py (Lader entfernt und Eingänge durchgereicht in allen sechs Graphen; Name und
  Stärke aus der LoRA, Trigger mit Klasse aus dem Profil vor dem Prompt; LoRA durch Kandidaten,
  Wiederholen, Fertigstellen; Krea-LoRA nicht im SDXL-Fertigstellen; Kundenauftrag ohne LoRA abgelehnt;
  eingereichter Graph über run_render); Graph ohne LoRA == abgenommener Graph (alle sechs gegen HEAD)
Mac-Lauf 17.11.2026: lustify_sdxl_t2i Job 90 (20,5 s) und krea2_raw_turbo_lora_t2i Job 91 (74,2 s), je
  8 Schritte 768 × 768, ohne Charakter-LoRA: Lader entfernt, Turbo-LoRA bleibt, echte Bilder
Ergebnis: TEIL (Implementierung); Lauf mit geladener Charakter-LoRA OFFEN (keine Fotos, keine LoRA);
  Bindung am Default-Auftrag (Influencerin, Charakter) bleibt SP1
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-092 / BUG-094 / BUG-037 (SP3 Schritt 4)
Commit: siehe git log „SP3 step 4“ / media.models._merge_local, edit_local, register_lora, set_workflow_enabled,
  delete_workflow, engine_model_names; core.registry._fingerprint, _registry_mtime
Behauptung: BESTÄTIGT (lokaler Zustand im versionierten Manifest; LoRA nur auf gleicher Engine)
Nachweis: tests/test_models.py::test_local_registry_holds_loras_and_switches (Manifest bytegleich nach Schalter und
  LoRA, Ablehnung von enabled im Manifest, ungültige LoRA ohne Änderung der lokalen Datei, Löschen nimmt den
  Schalter mit, LoRA auf eingetragener Engine ladbar, auf fremder nicht); tests/test_server.py CAS-Test mit
  Registry-Version über die lokale Datei
Mac-Lauf 17.11.2026: Zeile enabled aus dem Manifest nach local/registry.toml; Cockpit neu gestartet, 20 Workflows,
  LUSTIFY aktiviert aus der lokalen Datei, keine Fehler im Log
Ergebnis: BUG-092, BUG-037 PASS; BUG-094 TEIL (Implementierung), Eintrag für lustify_sam31_edit OFFEN (Probelauf)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-078 (SP3 Schritt 1)
Commit: siehe git log „SP3 step 1“ / core.characters._migrate_character_folders, media.training.copy_verified, remove_moved
Behauptung: BESTÄTIGT (zwei Ordnerschemata)
Nachweis: tests/test_server.py::test_character_folder_migration_moves_files_with_hash_check (Umzug, Hash-Abgleich,
  Konflikt stoppt ohne Festschreiben, alt = neu lässt den Ordner stehen)
Mac-Lauf 17.11.2026: echte Datenbank 20 → 21, Sicherung vor-ordnerumzug; Clara → local/characters/clara/. Dabei
  gefunden: der leere photos-Ordner (alt = neu) wurde als leerer alter Ordner entfernt – keine Daten betroffen
  (nur leere Ordner werden entfernt), sofort behoben und mit Test abgesichert; Ordner wiederhergestellt
Ergebnis: PASS
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-101 (SP5 Schritt 5, Etappe A)
Commit: siehe git log „SP5 step 5“ / core.render._next_job, store.jobs.queued_jobs(order), Migration 20
Behauptung: BESTÄTIGT (reines FIFO)
Nachweis: tests/test_orders.py::test_queue_priority_classes_and_order (Kunde vor Default vor Cockpit vor Training,
  Reihenfolge aus der Konfiguration, ohne Vorrang FIFO)
Mac-Lauf 17.11.2026: echte Datenbank 19 → 20 mit Sicherung; Warteschlange zeigt „· Cockpit“
Ergebnis: TEIL (Implementierung); Vorrang mit echten Kundenaufträgen folgt mit SP5
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-024 (SP2 Schritt 11, Etappe A)
Commit: siehe git log „SP2 step 11“ / web.http._command_status, frontend core/commands.ts settle
Behauptung: BESTÄTIGT (terminalReceipt wartete ohne Zeitlimit; kein Befehlsstatus abfragbar)
Nachweis: tests/test_server.py::test_command_status_endpoint, frontend tests/commands.test.ts (404 -> erneutes
  Senden mit derselben request_id, danach Endzustand)
Mac-Lauf 17.11.2026: Sitzung liefert X-Command-Wait-S 30; Anhalten/Fortsetzen im Cockpit quittiert; unbekannte
  Kennung -> 404
Ergebnis: TEIL (Implementierung); Verbindungsabbruch mitten im Befehl am echten System gehört zur SP2-Abnahme
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-090 (Etappe A, Backend-Teil)
Commit: siehe git log „BUG-090“ / core.orders.create_order, select_candidate, CreateOrder.finish_values (Feld 8)
Behauptung: BESTÄTIGT (Fertigstellen mit leeren Werten; ltx25_i2v als Fertigstellen scheitert am Pflicht-Prompt)
Nachweis: tests/test_orders.py::test_finish_stage_carries_its_own_values (Pflichtwert fehlt -> Ablehnung, falscher
  Wert -> Ablehnung, mit Werten -> Fertigstellen-Job mit Prompt und 3 s)
Mac-Lauf: NICHT GELAUFEN (Eingabe der Werte im Cockpit folgt mit dem Ausgabeprofil des Default-Kontakts, Etappe C,
  und dem Video-Produkt in SP5)
Ergebnis: TEIL
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-093 (Etappe A)
Commit: siehe git log „BUG-093“ / workflows/manifest.toml (Wan-Formate), media.models.format_problems
Behauptung: BESTÄTIGT (Wan-Engines ohne formats)
Nachweis: tests/test_models.py::test_engine_formats_must_fit_every_workflow (gleiche Namen wie LTX, Grenzen/Raster geprüft)
Mac-Lauf 17.11.2026: Cockpit zeigt bei Wan 2.2 und Remix 16:9 · 1280 × 720, 9:16 · 720 × 1280, 1:1, 3:4, 4:5
Ergebnis: TEIL (Implementierung); Render in 720p gehört zur Modellqualifikation
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-064 (Etappe A)
Commit: siehe git log „BUG-064“ / media.pipeline.register_outputs, store.orders.stage_jobs, Migration 19 (jobs.media_id)
Behauptung: BESTÄTIGT (alter Weg: zweiter, bitgleicher Kandidat ohne Ergebnis [1, None])
Nachweis: tests/test_orders.py::test_bit_identical_result_counts_as_candidate (beide Kandidaten zeigen das Medium)
Mac-Lauf 17.11.2026: echte Datenbank 18 → 19 mit Sicherung …bak-20261117191103-vor-migration19, integrity_check ok;
  bitgleiches Renderergebnis am Mac nicht erzwungen (Seed-Determinismus nicht garantiert)
Ergebnis: TEIL (Code und Migration am Mac belegt, bitgleicher Lauf nicht real nachgestellt)
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-107 (SP0 Schritt 6)
Commit: siehe git log „SP0 step 6“ / media.gallery.media_candidates, scan_media, store.media.add_media, Migration 18
Behauptung: BESTÄTIGT (finished_jobs(0, 1_000_000) je Runde, Medien-Nummer über das Journal)
Nachweis: Messung mit 1 Mio. Ereignissen: Runde 1054 ms → < 50 ms, add_media 44 ms → < 10 ms;
  tests/test_journal.py (Position, gelöschte Ausgaben, Zähler aus dem Journal, Last)
Mac-Lauf 17.11.2026: echte Datenbank 17 → 18 mit Sicherung …bak-20261117183232-vor-migration18,
  integrity_check ok; Renderjobs 73–75 → Medien 84–86 mit Nummern aus den Zählern; Position 657
  (letztes Job-Ende), keine doppelten Medien
Ergebnis: PASS
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-106 (SP0 Schritt 5)
Commit: siehe git log „SP0 step 5“ / core.cloner._reply_internal, core.delivery, media.aimeta, core.render.watch_loop
Behauptung: BESTÄTIGT (Hash und Kennzeichnung im Hauptstrang; zusätzlich: Ganzdatei-Puffer in aimeta hält die GIL)
Nachweis: tests/test_mainloop.py mit DF_MAINLOOP_MB=500: vorher 899 ms Blockade (rot), danach < 100 ms (grün);
  aimeta-Ausgabe byte-gleich zum alten Verfahren (MP4 mit udta/meta/altem XMP, 64-Bit-Kiste)
Mac-Lauf 17.11.2026: Cockpit neu gestartet, Betriebsanzeige „Hauptstrang 1 ms (max 2)“
Ergebnis: TEIL (Dateiarbeit PASS); lange Datenbankabfragen folgen mit BUG-107/SP0 Schritt 6
Bearbeiter/Datum: Claude, 17.11.2026
```

```text
ID: BUG-105 (SP0 Schritt 1)
Commit: siehe git log „SP0 step 1“ / store.Store._migrate, _backup, _check_integrity
Behauptung: BESTÄTIGT (Migration ohne Sicherung, Integritätsprüfung nur bei Tabellenumbau)
Nachweis: tests/test_store.py::test_migration_backs_up_first_and_failure_leaves_db_unchanged und
  ::test_migration_checks_integrity_and_fresh_db_needs_no_backup (beide rot vor der Korrektur)
Mac-Lauf 17.11.2026: Kopie der echten Datenbank auf Version 16 gesetzt, Migration 17 scheitert →
  Datenbank bleibt Version 16 mit 598 Ereignissen, Sicherung …bak-20261117174912-vor-migration17
  (Version 16, integrity_check ok), Fehlermeldung nennt die Sicherung
Ergebnis: PASS für das Abnahmekriterium von SP0 Schritt 1; eine erfolgreiche Migration der echten
  Datenbank folgt mit der nächsten Migration
Bearbeiter/Datum: Claude, 17.11.2026
```

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
