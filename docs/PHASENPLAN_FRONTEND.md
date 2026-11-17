# Darkfluenzer – PHASENPLAN_FRONTEND.md

**Stand:** 17.11.2026 (Frontend-Teile der Sammelpakete SP1–SP6, Änderungsblätter und Korrektur nach den Prüfberichten) · **Status:** **freigegeben** durch den Betreiber am 17.11.2026, verbindlich. Umsetzung in der Reihenfolge des Backend-Plans §6, Priorität CODE FIRST.
**Gilt zusammen mit:** `docs/PHASENPLAN_BACKEND.md` (Produktziel, Regeln, Entscheidungen E1–E19, PASS-Definition, Reihenfolge, Paketnummern) und `docs/bugs_v1.md`.
**Prüfbasis:** Code auf `main` ab `7a49b6a`, Planstand nach `d120562` mit Korrektur; laufendes Cockpit am 17.11.2026.
**Gestaltungsreferenz:** `docs/design/Darkfluenzer_Cockpit_Interaktiv.html` und Anhang A (F7, wörtlich aus dem archivierten FRONT V1).

---

## 1. Grundregeln

- **Bestehende GUI erhalten und ergänzen, nicht neu schreiben.** React/Vite, generierte Protobuf-Typen, keine neue UI-Bibliothek, kein Electron, keine LLM- oder Chat-Logik im Browser.
- **Ein Stylesheet:** `frontend/src/shared/graphite.css`. Keine Datei je Seite, keine eigene Video- oder Bildgestaltung.
- **Sechs Hauptreiter:** Übersicht · Nachrichten · ComfyUI · Dateien · Wallet · Einstellungen (E13). Neue Funktionen kommen in passende Reiter (KI-Studio unter ComfyUI → KI, Charaktertraining unter ComfyUI, Kloner und Kundentest im Default-Kontakt).
- **Daten nur per Push:** STATE und EVENT über den einen WebSocket `/ws/v1/stream`; Detailabfragen nur bei Ansichts-, Filter-, Seiten- oder Kundenwechsel, relevanter Fachversion, Reconnect oder manuellem Neuladen. Keine Abfrageschleifen. Alte Antworten (Version, Seite, Kunde, Verbindung) verwerfen; gleiche Anfragen zusammenfassen.
- **Aktionen nur als Protobuf-Befehl** mit `request_id`, Scope und erwarteter Revision. `ACCEPTED` ist kein Erfolg; die Oberfläche zeigt den Zustand erst nach dem terminalen Receipt. Nach Verbindungsverlust dieselbe `request_id` wieder aufnehmen, nie blind neu senden.
- **Kein Bedienelement ohne Backend.** Jedes Element kennt die Zustände leer · lädt · gesperrt mit Grund · Fehler. Geplante Funktionen bleiben ehrlich deaktiviert.
- **Kurze Texte:** Beschriftungen, Werte, Zustände und kurze Fehlermeldungen; keine erklärenden Absätze und keine Architekturtexte in der Steuerung.
- **Gleiche Arten, gleiche Bedienung:** Alle Workflows einer Art (Bild, Video, Training, Text) zeigen dieselben Felder an derselben Stelle mit denselben Beschriftungen. Grenzen und Auswahlwerte kommen aus dem STATE, nie aus dem Frontend.
- **Abnahme je Paket:** Browser-Test (Playwright mit echtem Chrome, `channel: "chrome"`, denn das mitgelieferte Chromium dekodiert kein H.264) gegen das laufende Cockpit, Mac-Screenshot gegen die Referenz, dazu der echte End-to-End-Lauf aus dem Backend-Plan.
- **Prüfungen:** `npx tsc --noEmit`, `npx vitest run`, `npm run build`. Nach einer Schemaänderung laden geöffnete Cockpits neu (BUG-076).

---

## 2. Ist-Stand (17.11.2026)

| Reiter | Vorhanden | Fehlt |
|---|---|---|
| Übersicht | drei Karten (Kundenakten, GPU-Warteschlange, Freigaben ausstehend), aktuelle Kunden | Zähler „wartet auf Produktion/Freigabe“; Ungelesen veraltet bei bekannten Kunden (BUG-048) |
| Nachrichten | Kundenliste, Register (öffnen automatisch bei neuer Akte und bei Ungelesenem nach Neuladen), Unterregister je Kanal, Composer mit „Antwort senden“, Kanalstatus mit Telegram-Anmeldung; rechts Identität, **„Als Default festlegen“**, Alter, KI-Hinweis, Angebot, Influencerin; Default-Kontakt mit Absender-IDs, Workflows, **Befehle (Workflow je Befehl)**, Freigabemodus, Schalter | Antwortmodus, KI-Schalter, Entwürfe, Medienwunsch, Prompt, Prüfwerte, Telegram-Übergang, Nachlauf; Zustandskarte mit Antwort im Chat für jede Default-Nachricht (SP1) |
| ComfyUI | Workflowliste (Fotos, Videos, KI), Formular aus der Registry, erweiterte Einstellungen (zugeklappt), „Aus Dateien“, Kandidaten (Video Standard 1), Ergebnis, Warteschlange mit Fortschritt, Anhalten (dauerhaft), Abbrechen, Instanzen, Charakter, Trainingsordner, „Für Kundenauftrag“; ungültige Felder werden am Knopf genannt | einheitliche Videosteuerung (SP1), Zeitachse (B4), KI-Studio (B5), LoRA-Auswahl und -Vergleich (B1), Auftrag als Ganzes abbrechen (SP1) |
| Dateien | Galerie, Filter, Markieren, Alle markieren, Löschen mit Bestätigung, Download, Herkunft, Weiterverarbeiten, Wiederholen, Variieren, Hochskalieren, Video erstellen, abgeleitete Versionen | – (Video-Vorschau im echten Chrome geprüft) |
| Wallet | Konten, Adresse mit QR, Eingänge, Zuordnen, Gutscheine, Monatsliste | PayPal, Gutscheinmaskierung, Bestätigung vor Zuordnen/Einlösen (BUG-032, 033) |
| Einstellungen | – (Geheimnisse bisher nur per CLI) | ganzer Reiter (S1) |

**Wo „Als Default festlegen“ liegt:** Nachrichten → Kundenakte (Register) → rechte Spalte → Identität → bei jeder Telegram- oder Instagram-Identität „Als Default festlegen“ → „Default bestätigen“. Der Knopf erscheint nur in einer Kundenakte; ist der Absender schon Default, gibt es keine Akte mehr. Die Schalter „Interne Befehle verarbeiten“ und „Automatische Produktionsaufträge“ liegen im Default-Kontakt (rechte Spalte).

---

## 3. Reiter im Einzelnen

### 3.1 Übersicht

Karten und Liste nur aus echten Projektionen: **Kundenakten** (externe Akten ohne Default), **GPU-Warteschlange** (aktiv, wartend, angehalten je Instanz), **Freigaben ausstehend** mit Teilzahlen „wartet auf Produktion“, „wartet auf Freigabe“; „Aktuelle Kunden“ öffnet die vorhandene Akte. Abnahme: zwei verbundene Cockpits aktualisieren per Push.

### 3.2 Nachrichten

**Zuordnung zur Figur (Betreiberanforderung 17.11.):** Jede eingehende Nachricht gehört zu dem Konto, an das sie geschrieben wurde, und damit zu genau einer Influencerin (Clara, Lucy, Ken …, C5.1). Das ist überall sofort sichtbar:
- **Kundenliste:** oben Filter je Influencerin – *Alle · Clara · Lucy · Ken* – jeweils mit Ungelesen-Zahl; jede Zeile trägt das Kennzeichen der Influencerin (Name und feste Farbe aus dem Profil) neben dem Kanalkennzeichen (IG/TG) und dem Kontonamen (z. B. „Clara · IG @clara…“).
- **Sortierung sichtbar:** über der Liste steht die aktive Sortierung, Standard „neueste Nachricht zuerst“; innerhalb des Filters „Alle“ wahlweise gruppiert nach Influencerin. Die Wahl bleibt nur im Browser gespeichert.
- **Register:** jeder Reiter zeigt Name des Kunden und das Kennzeichen der Influencerin; der Kopf der Akte nennt „schreibt an <Influencerin> über <Kanal> <Konto>“.
- **Eine Akte = eine Influencerin:** Eine Kundenakte kann mehrere verifizierte Identitäten auf Konten derselben Influencerin haben (z. B. Claras Instagram und Claras Telegram, C5.9); jede Nachricht zeigt das Konto, über das sie kam. Dieselbe Person bei Clara und bei Lucy erscheint als zwei getrennte Akten.
- **Rechte Steuerung und Composer** arbeiten immer mit dieser Figur (Persona, Preise, LoRA) und senden über das Konto des gewählten Kanalregisters; ein Wechsel der Figur in einer Akte ist nicht möglich.

**Spalten:** links Kunden (Figur-Filter, Suche, Avatar, Name, Kunden-ID, Kennzeichen von Influencerin und Kanal, letzte Aktivität, Ungelesen); Mitte Register mehrerer Akten (× schließt nur das Register), Unterregister Gesamter Verlauf · Instagram · Telegram · WhatsApp (Gesamt nur lesbar, ohne Composer; nicht verbundene Kanäle deaktiviert), eingehend links, ausgehend rechts, Kanalfarbe IG pink, TG blau, WA grün, Ereigniskarten zwischen den Nachrichten; rechts die vollständige Steuerung, eigene Scrollleiste.

**Rechte Steuerung bei Kunden:**

| Block | Felder |
|---|---|
| Identität | Kundennummer, Kanalidentitäten (verifiziert), „Als Default festlegen“, Telegram-Übergang (C5.9) |
| KI | Influencerin der Akte (C5.1) mit Schalter Freigabeart automatisch/Betreiber, Text-KI an/aus, Antwortmodus Automatisch · Entwürfe prüfen · Manuell (C5.3), automatische Antworten an/aus, Kaufbereitschaft mit Beleg (C5.4), geplante Sendezeit mit „Jetzt senden“/„Zurückhalten“ |
| Sicherheit | Status des KI-Hinweises je Identität; Karte und Sperre „minderjährig vermutet“ (aufheben nur durch den Betreiber, protokolliert); Inhaltsstufe; Kanalfenster (Instagram 24 h, Telegram-Bremse) mit mitlaufender Frist. Der Altersblock entfällt (E2, C5.2). |
| Gedächtnis | Zusammenfassung, Vorlieben mit Quelle, Korrigieren/Löschen (B5.3) |
| Medienwunsch | Motiv, Foto/Video/Set, Anzahl, Format, Lieferart, Quellnachrichten, offene Rückfrage (C5.5) |
| Angebot | Produkt-ID, Preislistenrevision, Betrag, Zahlungswege der Influencerin, Frist, Zusatzleistungen Originaldatei/selbstlöschend; Faktenblock gesperrt (C5.5) |
| Zahlung | nicht gezahlt · Eingang unklar · bestätigt · unterbezahlt · erstattet, mit Quelle und Betrag; ohne Zugang „NICHT EINGERICHTET“ |
| Produktion | Stufe, Prompt, Workflow, LoRA-Version oder „ohne Charakter-LoRA“, Fortschritt, Lieferzeit, Kandidaten als Bild oder abspielbares Video; je Kandidat Identität, Inhaltsstufe und Technik mit bestanden/nicht (C5.6a); Karte „wartet auf Betreiber“ mit Freigeben, Neu, Erstatten; „Neu erzeugen“ |
| Zustellung | Vorschau der Zustellkopie (Kanal, Versandart, Größe, Kennzeichnung), Begleittext, Status (C5.7); wer freigegeben hat (System oder Betreiber) und über welchen Weg (C5.10) |
| Nachlauf | Reklamation, Neuauflage, Erstattung, Abschließen (C5.8) |

**Rechte Steuerung beim Default (nur Betreiberfelder):** Telegram- und Instagram-Absender-ID, **Betriebsart** Produktion · Kundentest · Aus mit den Chat-Wörtern (E12), Interne Befehle verarbeiten, Influencerin, Medien-Workflow, Video-Workflow (animate), **Befehle** (Workflow und Ausgabeprofil je `clone`, `pose`, `style`, `remix`, `animate`, `edit`, z. B. Story 9:16; Vorschläge aus der Registry), Freigabemodus, Automatische Produktionsaufträge, Freigabe vom Handy (C5.10). Ein Stapel (mehrere Bilder in einer Nachricht) zeigt je Bild eine Karte mit gemeinsamem Fortschritt. Die sechs Befehle werden in der Nachricht erkannt, es gibt keine Befehlsknöpfe. Ist ein Schalter aus oder fehlt ein Workflow, zeigt der Default-Kontakt das deutlich und die Kette antwortet im Chat (SP1).

**Composer:** nur im gewählten verbundenen Kanal; „KI antworten“ (Entwurf nach Antwortmodus), „Antwort senden“ (genau einmal, Receipt); ungesendete Entwürfe bleiben an ihrer Akte; bei Handy-Übergabe pausiert die Automatik.

### 3.3 ComfyUI

**Spalten:** links nur Workflows aus der Registry, gruppiert Fotos · Videos · KI, mit Status; Mitte Arbeitsfläche (Prompt, Negativ nur wenn deklariert, Quellbild/Upload/„Aus Dateien“, Maske, Ergebnis); rechts Steuerung (Charakter, Workflow-Info, Format, Kandidaten, Fertigstellen mit, erweiterte Einstellungen – bei jedem Workflowwechsel zugeklappt –, Generieren bzw. Training starten), darunter Warteschlange und Instanzen.

- **Erweiterte Einstellungen:** alle tatsächlich registrierten Eingänge mit Typ, Grenzen und Fehler am Feld; Ganzzahlen vor dem Senden geprüft (BUG-025).
- **Einheitliche Videosteuerung (SP1):** Komponente `VideoSettings` für alle Video-Workflows. Feste Reihenfolge direkt unter Prompt und Startbild: **Gesamtlänge (s)**, Bildrate, Auflösung, Abschnittslänge (nur wenn die Engine Abschnitte nutzt). Gleiche Beschriftung für LTX, Wan und Remix; Grenzen aus dem STATE. **Umgesetzt 17.11.2026** (`pages/comfyui/VideoSettings.tsx`): LTX, Wan 2.2 und Remix zeigen Gesamtlänge (s), Bildrate (fps), Breite, Höhe an derselben Stelle, Abschnittslänge nur bei Wan/Remix.
- **Zeitachse (B4, FL-4):** unter `VideoSettings` eine Leiste über die Gesamtlänge; je Marke Sekunde, Referenzbild aus Dateien, Prompt des folgenden Abschnitts, Kamera/Bewegung, Übergangsstärke; Marken verschiebbar, Abschnitte sichtbar.
- **Warteschlange:** dauerhafte Reihenfolge, Fortschritt (Schritt, Abschnitt), Anhalten/Fortsetzen (übersteht Neustart), Abbrechen je Job und je Auftrag (SP1); Video standardmäßig ein Kandidat. **[17.11.]** Geschätzte Restdauer je laufendem Job (Schätzung, keine zugesagte Endzeit); Hinweis bei Stillstand (`production.stall_notice_s`); Zustand „unbekannt“ bei Verbindungsverlust; kein Abbruch wegen der Dauer (Backend SP1 Schritt 2). **Umgesetzt 17.11.:** Abzeichen UNBEKANNT, Zeile „läuft seit … · noch ~… (Schätzung)“, „wartet · ~…“, Hinweis bei Stillstand.
- **B1 Charakter (Bereich Charakter, FL-3; Paket SP3):**
  - Liste der Charaktere; „Neuer Charakter“ mit Name, Kürzel, Klasse und Trigger.
  - Je Charakter: Ordnerpfad zum Kopieren und „Im Finder öffnen“; Fotos auch per Ziehen/Ablegen hinzufügen (kopiert nach `photos/`); Fotoliste mit Status und Grund; Zähler „x von y brauchbar“; Auswahl der Referenzfotos.
  - **Umgesetzt 17.11.2026:** Pfad (nur lesbar), „Pfad kopieren“, „Im Finder öffnen“, Ablageflächen für Trainings- und Referenzfotos (`.g-drop` in `graphite.css`), Formular mit Name, Kürzel (beim Anlegen), Trigger, Klasse.
  - Training: Engine-Auswahl, Knopf „Trainieren“ (gesperrt mit Grund, solange Fotos fehlen oder ein Training läuft), Fortschritt, Abbrechen. **[17.11.]** Trainingsweg Krea 2 oder LUSTIFY/SDXL wählbar (E14 offen); dieselben Fotos, Versionen und aktive LoRA je Architektur getrennt.
  - Versionen: Tabelle mit Datum, Datensatz, Dauer und Identitätswert; Probebilder als Vergleichsraster; „Aktiv setzen“.
  - Influencerin-Block: zugeordneter Charakter und aktive LoRA je Engine.
  - Workflow-Formular: LoRA-Auswahl, aktive Version vorbelegt, dazu „ohne“.
  - **Umgesetzt 17.11.2026:** Auftragskarte nennt je Stufe „LoRA <Schlüssel>“ oder „ohne Charakter-LoRA“ (Workflows mit Lader). Formular: Auswahl „Charakter-LoRA“ mit den ladbaren LoRAs (Figur · Schlüssel, „(aktiv)“), aktive Version der gewählten Figur vorbelegt, dazu „ohne“; Stärke startet mit dem Wert der LoRA und ist ohne LoRA ausgeblendet; Kundenauftrag mit Lader-Workflow nur mit LoRA. Charakter: LoRA-Zeilen mit Architektur und „Aktiv setzen“ / „Aktiv · aufheben“; Probe-Prompts im Profil (einer je Zeile). Browser: Smoke-Test grün, Formular im echten Cockpit geprüft (ohne LoRA, da noch keine trainiert ist). **Offen:** Browser-Test „Umschalten der aktiven Version“ mit einer echten LoRA.
  - Fotoliste zeigt zusätzlich die Gesichtshinweise „kein Gesicht“ und „andere Person“ (SP3).
  - **Umgesetzt 17.11.2026 (Teil):** Workflow „Prüfen · Gesichtsidentität“ nimmt die gewählte Figur (Referenzordner) und zeigt im Ergebnis SFace, AuraFace und die Zahl der Referenzen oder „nicht prüfbar“ / „keine Referenzfotos der Figur“; Ablageflächen für Trainings- und Referenzfotos auch dort. Echter Browser-Lauf 17.11. (Job 92). Die Hinweise in der Fotoliste folgen.
  - **Umgesetzt 17.11.2026:** Ergebnis zeigt je Prüfung eine Zeile, Inhalt als Stufe mit Wert und freiliegenden Körperstellen (z. B. „low 0,88 · BELLY_EXPOSED 0,81“).
  - Profilfelder Trigger und Klasse; Probe-Prompts.
  - Vor „Trainieren“ steht die geschätzte Dauer; der Knopf ist gesperrt, solange bezahlte Aufträge warten.
  - **Umgesetzt 17.11.2026 (Teil):** Gesamtschritte und geschätzte Dauer aus `step_s` über dem Knopf („noch keine Messung“ ohne Lauf).
  - **Training mit Checkpoints [17.11., Wellen gestrichen] (Backend SP3 Schritt 3):** Gesamtschritte, aktuelle Schrittzahl, geschätzte Restdauer, letzter gültiger Checkpoint, Knöpfe „Fortsetzen“ und „Beenden“; Probebilder optional.
  - **Umgesetzt 17.11.2026:** je Lauf „Checkpoint n von m · Verlust“ mit „Fortsetzen“ und „Beenden“ im Trainingsbereich; Checkpoint-Abstand als Feld des Trainingsformulars. Laufender Fortschritt und Restdauer kommen aus der Warteschlange (jobs.active).
  - Versionen: Tabelle aus der Registry mit Figur, Architektur, Datensatz, Schritten, Rang; Probebilder mit Identitätswert; „Aktiv setzen“ je Architektur.
  - Dateien, Herkunft: LoRA-Schlüssel, Stärke, Identitätswert.
  - **Umgesetzt 17.11.2026:** Dateien zeigen „Abmessungen B × H“ und getrennt die native Größe („nativ … (hochskaliert/Ausgabeformat)“ oder „native Größe unbekannt“).
  - Default-Kontakt: Vorschlag des Workflows je Befehl aus der Registry (Ergebnis des Kloner-Vergleichs, SP3 Schritt 8).
  - Abnahme: Browser-Test für Anlegen, Fotostatus, Trainingsstart mit zu wenigen Fotos (gesperrt) und Umschalten der aktiven Version.
- **Referenzanalyse (B5.6, FL-5):** Knopf „Analysieren“ an Vorlage und Datei; Ergebnis als bearbeitbarer Prompt mit Pose, Licht, Kamera, Komposition; „Als Prompt übernehmen“ oder „Als Referenz verwenden“.
- **Workflowverwaltung (Bestand):** öffnen im echten ComfyUI, übernehmen, aktivieren/deaktivieren, löschen (nur Definition, nie Modelle oder Medien).

### 3.4 ComfyUI → KI (KI-Studio, B5)

**[17.11., E19]** Das gesamte Gesprächsverhalten jeder Influencerin wird hier über die Prompts des registrierten ComfyUI-2-Sprachworkflows eingestellt, ohne Python-Änderung. Jedes Feld ist an einen echten Eingang von `clara_chat_melody` gebunden (Backend SP4 Schritt 1); Felder ohne Graph-Bindung gibt es nicht.

Links die KI-Workflows aus der Registry; Mitte Tabs **Chat-Test · Persona · Gedächtnis · Vergleich**; rechts Modell & Figur (Melody1437 v2.0 Q6_K aus der Registry), Textgenerierung (nur Parameter, die der Knoten wirklich hat), Kontext, KI-Warteschlange.

- **Textdialog → Persona (Promptprofil der gewählten Influencerin):** getrennte Felder **Systemprompt**, **Persona**, **Positive Anweisungen**, **Negative Anweisungen**, **Gesprächs- und Verkaufsstrategie**, **Beispieldialoge**, dazu die Funktionsanweisungen (KI-Hinweis, Wunsch-Zusammenfassung, Angebot, Zustellung, Vertrösten, Fansly-Verweis, Schema der strukturierten Ergebnisse). Der Ehrlichkeitsblock (Regel 12 c) ist kein Feld; er wird aus dem registrierten Graphen nur angezeigt.
- **Rechts, Textgenerierung:** Modell- und Samplingparameter des Knotens (`max_tokens`, `temperature`, `top_p`, `repeat_penalty`; erweitert `repeat_last_n`, `n_ctx`, `enable_thinking`), Grenzen aus der Registry.
- **Versionen:** Speichern legt eine neue Version an; zwei Versionen nebeneinander vergleichen; eine Version zuerst im Chat-Test ausführen; aktivieren oder auf eine frühere zurücksetzen (Befehl 68), wirksam ohne Backend-Neustart.
- **Chat-Test:** echte Melody-Inferenz mit Sitzung, „Nachricht an Clara …“, Enter sendet, Shift+Enter Zeilenumbruch. Je Antwort Messwerte (Gesamtzeit, Wartezeit; die Zeit bis zum ersten Token nur, wenn der Knoten sie liefert) und die verwendeten Versionen von Profilblöcken, Modell und Workflow; aufklappbar der tatsächlich zusammengesetzte Prompt. Testdaten getrennt von Kundendaten.
- **Gedächtnis:** Liste mit Quelle und Zeit (B5.3), Kontextinspektor (welche Einträge in den nächsten Lauf gehen).
- **Prüfansicht** für die strukturierten Ergebnisse des Workflows (Kaufbereitschaft, Wunsch, Prompt).
- **Vergleich** nur mit freigegebenem zweitem Profil.
- Eigene Profile je Influencerin; die Auswahl der Figur wechselt das ganze Profil, nichts wird zwischen Clara und Lucy gemischt.
- Außerhalb von ComfyUI bleiben ausschließlich technische Berechtigungs-, Transaktions- und Versandprüfungen; sie erscheinen als Zustand, nicht als Schalter.
- Anzeige „bereit“ nur für wirklich registrierte und geprüfte KI-Workflows. Kein zusätzlicher Hauptreiter, kein zweiter Chat-Editor, kein weiteres Sprachmodell-Backend.

### 3.5 Dateien

Bestand `Files.tsx` bleibt (Kacheln, Filter, Markieren, Alle markieren, Löschen mit Bestätigung, Download, Herkunft, Weiterverarbeiten). Auftragsmedien sind serverseitig vor dem Löschen geschützt. Videos mit Player; Herkunft zeigt alle wirksamen Parameter inklusive LoRA-Version; fehlende Herkunft heißt „nicht vorhanden“.

### 3.6 Wallet

Konten, Adressen, Netz/Asset, Betrag mit EUR-Kurs und Quelle, Eingänge, nicht zugeordnete Beträge, Zuordnen, Gutscheine, Monatsliste. Neu: PayPal-Konto und -Eingänge (C5a.2), Gutscheincodes maskiert mit ausdrücklichem Aufdecken, Bestätigungsdialog mit Betrag, Kunde und Auftrag vor Zuordnen und Einlösen, Kulanz nach E10, Zahlungswege je Influencerin. Keine Trading-Ansichten, keine Auszahlungen.

### 3.7 Einstellungen (S1)

- Dateien: neue Seite `pages/Settings.tsx`, `core/settings.ts`.
- Eine Karte je Gruppe: Kanäle, Zahlung, KI und Render, Admin und Test, Betrieb.
- Je Eintrag: Name, Status (gesetzt, fehlt, ungültig), Eingabefeld, „Verbindung prüfen“, Hinweis, woher der Wert kommt.
- Geheimnisse: leeres Passwortfeld mit „Ersetzen“. Der gespeicherte Wert wird nie angezeigt, auch nicht teilweise.
- Filter „nur Fehlendes“. Banner „Neustart nötig“ mit Knopf.
- Die Übersicht zeigt „Einrichtung: x von y fehlen“ und führt hierher.
- Abnahme: Wert eintragen, prüfen, neu laden; Status „gesetzt“, Feld leer.

### 3.8 Kundentest T1 und T2 (Nachrichten, Default-Kontakt)

- Umschalter Betriebsart: Produktion, Kundentest, Aus.
- Der Kundentest läuft in einer eigenen Testkonversation der internen Akte mit eigenem Verlauf und Gedächtnis; der Produktionsverlauf des Defaults bleibt unberührt. Testaufträge gehören zur internen Akte, nur für sie entfällt die Zahlung. Jeder Wechsel erscheint als Karte; der KI-Hinweis kommt wie bei Kunden einmal je Testsitzung.
- Im Kundentest: Marke TEST im Verlauf, Messwerte je Nachricht aufklappbar, Tafel „Latenzen“ mit p50 und p95 für Antwort und Render.
- Knöpfe „Test zurücksetzen“ und „Verzögerung wie Kunde“.
- Testaufträge tragen in allen Listen die Marke TEST und erscheinen nie im Wallet.
- Abnahme: Browser-Test für Umschalten, Messwerte und Zurücksetzen.

---

## 4. Pakete (Nummern wie im Backend-Plan)

**Reihenfolge:** Die Frontend-Teile folgen den Etappen des Backend-Plans (§6). **[17.11., CODE FIRST]** Zuerst vollständige Implementierung mit automatisierten Tests und kurzen echten Läufen; Modellqualifikationen (Training, lange Renders) danach. Zustände in der Oberfläche trennen beides: gebaut, aber nicht qualifiziert heißt `CODE` oder `TEIL`, nie PASS.

- **A:** SP0 (Seiten in Komponenten teilen), `VideoSettings`, „Auftrag abbrechen“, Ganzzahlprüfung, Befehle mit Zeitlimit und Statusabfrage, Bereich Charakter mit Training und Versionen, Zeitachse, Vorrang in der Warteschlange.
- **B:** KI-Studio (Chat-Test, Promptprofil mit Versionen, Gedächtnis, Prüfansicht; E19).
- **C:** Zustandskarten der Default-Kette, Betriebsart, Ausgabeprofil je Befehl, Stapel; Modus der Konversation, Entwürfe, geplante Antworten, Verhaltensprofil; Kundentest mit Latenztafel.
- **D:** Produktliste, Medienwunsch, Angebot, Produktion mit Prüfwerten, Zustellung, Marke TEST.
- **E:** Reiter Einstellungen, Kanalkonten, Figur-Filter, Wallet mit PayPal und Kulanz, restliche Härtung.
- **F:** Betriebsanzeige, Auskunft und Löschung, Release-Kennung, Gesamtlauf.


| Paket | Frontend-Umfang | Abnahme |
|---|---|---|
| **SP2 Fundament** | Frontend-Teil nach §4.1 (Befehle mit Zeitlimit und Statusabfrage, begrenzte Ereignislisten, Kundenliste/Übersicht per EVENT 26, Kanalstatus je Konto, Figur-Filter, Reiter Einstellungen mit Kanalkonten, kleinere Punkte) | je ein Browser-Test für Nachrichten, ComfyUI, Dateien, Wallet und Einstellungen; Smoke klickt alle sechs Reiter; Verbindungsabbruch während eines Befehls gibt den Knopf wieder frei |
| **SP0 Struktur** | Frontend-Teil nach §4.0 (Aufteilung von `Messages.tsx` und `ComfyUI.tsx` in Komponenten je Block) | Screenshots aller Reiter vorher und nachher gleich; alle Tests grün |
| **SP1 Default-Kette** | Karte je Zustand (gestartet, wartet auf Start mit Startknopf, abgelehnt mit Grund, zurückgesendet, Rückversand gesperrt, fehlgeschlagen, abgebrochen); Default-Kontakt mit Betriebsart, Kandidatenzahl, Ausgabeprofil je Befehl (z. B. Story 9:16) und Chat-Wörtern, ausgeschaltete Schalter und fehlende Workflows sichtbar; Stapel mit einer Karte je Bild und gemeinsamem Fortschritt; Auftragskarte nennt Influencerin, Workflow, Zahl der Referenzen, „ohne Charakter-LoRA“; `VideoSettings` für alle Video-Workflows; „Auftrag abbrechen“ an der Auftragskarte mit Abbruchzustand bis zur Quittung | Browser-Test für jeden Zustand; LTX, Wan, Remix mit denselben Feldern an derselben Stelle (Screenshot-Vergleich); echter Lauf vom Handy nach Backend SP1 |
| **SP4 Clara chattet** | Frontend-Teil nach §4.2 (KI-Studio mit Messwerten, Modus je Konversation, Entwürfe, geplante und stornierte Antworten, Kaufbereitschaft, Sperre „minderjährig vermutet“, Verhaltensprofil, Automatik je Konto, Kundentest, KI-Instanz „bleibt geladen“; Deutung freier Default-Anweisungen in der Karte) | 20 echte Testnachrichten im Kundentest mit Messwerten; Browser-Test für Modus, Entwurf, Storno, Sperre |
| **C5.1** (SP4) | Figur-Filter und Influencerin-Kennzeichen in Liste, Register und Aktenkopf, sichtbare Sortierung; Influencerin-Block mit Charakter | zwei Figuren ohne Vermischung |
| **SP5 Verkauf automatisch** | Frontend-Teil nach §4.3 (Produkte, Zahlungswege, Angebot, Zahlung, Prüfwerte, Systemfreigabe, Zustellung, Nachlauf, Wallet mit PayPal, Vorrang in der Warteschlange, Kundentest mit Bild) | Kundentest ohne Klick bis zum Foto mit Begleittext; Testauftrag nie im Wallet, nie an eine Kundenidentität; echte Zahlung je Weg |
| **SP3 (B1)** | Bereich Charakter §3.3 (Liste, Fotostatus, Training, Versionen, Aktiv setzen, LoRA-Auswahl im Formular) | echter Ordner → Training → LoRA → Bild; Browser-Test Anlegen, Fotostatus, gesperrter Start, Umschalten |
| **B4** | Zeitachse §3.3 | 15 s mit vier Marken → ein Auftrag mit vier Schlüsselbildern |
| **B5.6** | Referenzanalyse §3.3 | eigenes Bild → Prompt → echte Generierung |
| **SP6 Betrieb, Recht, Abnahme** | Frontend-Teil nach §4.4 (Betriebsanzeige, erneutes Neuladen nach Schemawechsel, Auskunft und Löschung je Akte, Pflichttexte, Release-Kennung) | ein Browser-Lauf über die ganze Kette; Screenshots aller sechs Reiter gegen die Referenz; Betreiberabnahme nach der Probephase |

### 4.0 SP0 Struktur (Frontend-Teil)

- `Messages.tsx` und `ComfyUI.tsx` werden in Komponenten je Block geteilt (Kundenliste, Verlauf, je ein Block der rechten Spalte, Workflowliste, Formular, Warteschlange).
- Keine sichtbare Änderung. Abnahme: Screenshots aller Reiter vorher und nachher gleich; alle Tests grün.
- **Umgesetzt 17.11.2026:** `pages/comfyui/` (common, Instances, Queue, Results, Character, Candidates, Workbench) und `pages/messages/` (common, Channels, CustomerList, Stream, Composer, CustomerPanel, DefaultPanel); mechanisch per TypeScript-Compiler, alle 83 Deklarationen zeichengleich. Abnahme: zehn Ansichten aller Reiter, normalisierter DOM vorher und nachher identisch (Vergleich vorher zweimal stabil), `npm run build` und 11 Frontend-Tests grün.

### 4.1 SP2 Fundament (Frontend-Teil)

Dateien: `core/commands.ts`, `core/state.ts`, `core/realtime.ts`, `pages/*.tsx`, neue `pages/Settings.tsx`, `frontend/tests/`.

- **Befehle (`commands.ts`, BUG-024, SPEC-011):** `terminalReceipt` bekommt ein Zeitlimit (Wert aus dem STATE Einstellungen). Nach Zeitlimit oder Verbindungsabbruch fragt die Oberfläche den Befehlsstatus über `GET /api/v1/command/<request_id>` ab. Antwort „in Bearbeitung“: weiter warten. Antwort 404: denselben Befehl mit derselben `request_id` erneut senden, nie automatisch eine neue `request_id`. Bei Befehlen mit wirtschaftlicher Wirkung (Angebot, Freigabe, Zuordnen, Erstatten, Rückversand) bleibt der Knopf gesperrt, bis ein Endzustand vorliegt; angezeigt wird „Ergebnis unbekannt, Status wird geprüft“.
- **Ereignislisten (`state.ts`, BUG-071):** Obergrenze je Topic; ältere Einträge kommen über die Seitenabfragen. `applyEvent` kopiert die Liste nicht mehr je Ereignis; die Benachrichtigung wird gebündelt.
- **Kundenliste und Übersicht:** folgen EVENT 26 bei jedem Eingang; Zähler „wartet auf Produktion“ und „wartet auf Freigabe“ (BUG-048, 070).
- **Kanalstatus je Konto;** Figur-Filter in der Kundenliste (die Daten liefert SP2).
- **Kleinere Punkte:** Ganzzahlprüfung (BUG-025), mitlaufende Fristen (BUG-026), Video in der Auftragskarte (BUG-027), Wallet-Maskierung und Bestätigungen (BUG-032, 033). Das Neuladen nach Schemawechsel (BUG-076) kommt mit SP6.
- **Reiter Einstellungen** nach §3.7, zusätzlich Kanalkonten anlegen, zuordnen und entfernen; Schalter „Kundenkanal über Privatkonto oder Bot“ je Konto (der Bot-Weg kommt später).
- **Nachrichten:** Sendung im Status `unknown` zeigt „als gesendet markieren“ und „erneut senden“ mit Warnhinweis (SPEC-009).
- **Abnahme:** je ein Browser-Test für Nachrichten, ComfyUI, Dateien, Wallet und Einstellungen; der Smoke-Test klickt alle sechs Reiter; ein Test trennt die Verbindung während eines Befehls und prüft, dass der Knopf wieder frei wird.

### 4.2 SP4 Clara chattet (Frontend-Teil)

- **KI-Studio (§3.4, E19):** alle Promptbereiche bearbeitbar (Systemprompt, Persona, positive und negative Anweisungen, Gesprächs- und Verkaufsstrategie, Beispieldialoge, Funktionsanweisungen) und die Modellparameter des Knotens; Versionen speichern, vergleichen, im Chat-Test ausführen, aktivieren und zurücksetzen ohne Neustart (Befehl 68). Chat-Test mit echter Melody-Inferenz, Gesamtzeit, Wartezeit und den Versionen von Profil, Modell und Workflow je Antwort, dazu der zusammengesetzte Prompt; die Zeit bis zum ersten Token nur, wenn sie geliefert wird. Gedächtnisliste mit Kontextinspektor. Prüfansicht für die strukturierten Ergebnisse. Eigene Profile je Influencerin.
- **Nachrichten, Kundenakte:** Umschalter für den Modus der Konversation; Entwurf als bearbeitbare Karte mit Senden und Verwerfen; geplante Antwort mit Sendezeit, „Jetzt senden“ und „Zurückhalten“; stornierte Antworten bleiben als Karte sichtbar. Kaufbereitschaft mit Beleg. Karte und Sperre „minderjährig vermutet“ mit „Sperre aufheben“. Status des KI-Hinweises; kein Altersblock.
- **Influencerin-Block:** Schalter Text-KI; Editor fürs Verhaltensprofil.
- **Kanalstatus:** Schalter „Automatik“ je Konto mit sichtbarer Wirkung.
- **Kundentest (§3.8):** wie beschrieben; derselbe registrierte Workflow wie im KI-Studio; die Latenztafel liest `ai_runs`.
- **Abnahme:** die zehn Punkte aus Backend SP4 (Abnahme 1 bis 10) im Browser und am Handy; Browser-Test für Speichern, Vergleichen, Aktivieren und Zurücksetzen einer Profilversion.
- **Instanzen:** KI-Instanz zeigt „bleibt geladen“ und das geladene Modell.

### 4.3 SP5 Verkauf automatisch (Frontend-Teil)

- **Influencerin-Block:** Produktliste mit Art, Workflow, Kandidatenzahl, Höchstlänge und Zusatzleistungen; Zahlungswege; Angebotsgültigkeit; Schalter Bildautomatik und Freigabeart.
- **Kundenakte rechts:** Medienwunsch mit Quellnachrichten; Angebot mit gesperrtem Faktenblock und Zahlungswegen; Zahlungsstatus; Produktion mit Prüfwerten je Kandidat und „Neu erzeugen“; Zustellung mit Versandart und Begleittext; Nachlauf mit Neuauflage und Erstattung.
- **Auftragskarte:** zeigt, ob das System oder der Betreiber freigegeben hat; „wartet auf Betreiber“ mit Freigeben, Neu, Erstatten („Freigeben“ nur bei technischem oder qualitativem Fehlschlag).
- **Wallet:** PayPal-Konto und -Eingänge; Kulanz-Zuordnung zeigt Fehlbetrag und Grenze und verlangt eine Bestätigung (E10, SPEC-010).
- **Kandidaten:** vier Prüfwerte (Identität, Inhaltsstufe, Technik, Qualität); ohne geprüftes Modell steht dort „Prüfmodell fehlt, Freigabe durch Betreiber“ (E16, E17).
- **Warteschlange:** Vorrang je Job sichtbar.
- **Kundentest:** Marke TEST an Auftrag, Medien und Karten; Testaufträge nie im Wallet.
- **Übersicht:** Zähler „wartet auf Betreiber“; Kennzahlen je Workflow (bestanden, Reklamationen, Neuauflagen).

### 4.4 SP6 Betrieb, Recht, Abnahme (Frontend-Teil)

- **Betriebsanzeige (Einstellungen, Gruppe Betrieb):** Dienst installiert, Laufzeit seit dem letzten Start, Netzteil, Schlafschutz, letzte Sicherung, freier Speicherplatz, Auslagerung, offene Störungen. Dazu: Verzögerung des Hauptstrangs (SP0), Sicherungsziel und Zahl der Stände, Hinweis „Anmeldung nach Neustart nötig“ (E18).
- **Verbindung (`realtime.ts`):** bei Sperre wegen des Schemas erneutes Neuladen in Abständen; Anzeige „Update läuft“ (BUG-076).
- **Kundenakte:** „Auskunft exportieren“ und „Akte löschen“ mit Bestätigung und Quittung.
- **Influencerin-Block:** Pflichttexte.
- **Release-Kennung** im Kopf.
- **Abnahme:** ein Browser-Lauf über die ganze Kette; Screenshots aller sechs Reiter gegen die Referenz.

---

## 5. Klick-Abnahme (Checkliste)

- [ ] Übersicht: echte Karten und Kunden, ohne Polling.
- [ ] Nachrichten: drei Spalten; Figur-Filter (Alle · Clara · Lucy · Ken) mit Ungelesen-Zahl; jede Akte zeigt Influencerin und Konto; Sortierung sichtbar; Register öffnen/schließen; Gesamt nur lesbar; Kanalregister kanalgebunden; rechte Steuerung wechselt mit dem Register.
- [ ] Default: nur Betreiberfelder; Betriebsart; „Als Default festlegen“ an einer Kundenidentität; jede Default-Nachricht endet in einer sichtbaren Karte und einer Antwort im Chat; Stapel und Story-Profil.
- [ ] ComfyUI: links nur Workflows; erweiterte Einstellungen zugeklappt; Video-Felder einheitlich; Abbrechen und Anhalten mit echtem Receipt.
- [ ] KI-Studio: Melody aus der Registry, Messwerte echt.
- [ ] Dateien: Bestand unverändert, Video-Player, Herkunft vollständig.
- [ ] Wallet: fünfter Reiter, Codes maskiert, Bestätigung vor Geldaktionen.
- [ ] Einstellungen: sechster Reiter, Geheimnisse nie sichtbar, „Verbindung prüfen“ je Eintrag.
- [ ] Kundentest: Betriebsart umschaltbar, Marke TEST, Latenzen p50/p95, Testaufträge nie im Wallet.
- [ ] Jeder Knopf: Befehl → Receipt → Push → richtiger Reiter.

---

## Anhang A – Freigegebene Klickreferenz F7

Wörtlich aus dem archivierten `PHASENPLAN_FRONT_V1.md` (F7, Betreiberfreigabe 15./16.11.2026) übernommen. Verweise auf „V0“, „FRONT“ oder Abschnittsnummern beziehen sich auf die Archivfassungen. Bei Widerspruch gilt dieser Plan, insbesondere §1 (sechs Reiter, einheitliche Bedienung je Art) und §3. Die früheren Abschnitte F0–F6 sind durch §1–§4 dieses Plans und den Backend-Plan ersetzt und liegen im Archiv.

**Überholte Stellen im Anhang (inline mit [17.11.] markiert):**
- fünf Hauptreiter → **sechs** (zusätzlich Einstellungen, S1);
- Trainingsordner `local/character/photos/` → `local/characters/<kürzel>/photos/` (B1);
- Telegram-Sofatest B5.5 → Kundentest **T1/T2**;
- Wallet-Abnahme mit BTC/USDT → Startwege PayPal und Amazon-Gutschein (E6), Krypto nur zugeschaltet;
- KI-Studio-Klickprototyp `Darkfluenzer_KI_Studio_Klickprototyp.html` liegt **nicht** im Repository; bis er vorliegt, gelten §3.4 und F7.9 ohne Prototyp-Vergleich.


### A.0 F7 — Abgenommene klickbare Cockpit-Referenz (Betreiberfreigabe 15.11.2026)

**Verbindliche Datei:** [Darkfluenzer_Cockpit_Interaktiv.html](design/Darkfluenzer_Cockpit_Interaktiv.html) — eigenständige HTML/CSS/JavaScript-Datei; im Browser öffnen, ohne Build, Backend oder Netzwerkzugriff. **Diese F7-Vereinbarung ist die Designreferenz für die nächste GUI-Anpassung; die noch nicht implementierten Funktionen bleiben fachlich F4/F3c/F5.** Designgetreue Umsetzung bedeutet insbesondere: keine neuen Menüs, künstlichen Status-Kacheln, Formularvorschauen oder Werbetexte. Screenshots der vom Betreiber freigegebenen Astra-Ansichten vom 14.11.2026 sind die visuelle Vergleichsgrundlage. Der HTML-Prototyp enthält bewusst nur stilisierte Bild-/Video-Platzhalter, niemals vorgetäuschte ComfyUI-Ergebnisse.

**Abgrenzung:** Die HTML-Datei demonstriert Navigation, Auswahl, Formulare, Kanalansichten, aufklappbare Detailbereiche, Markieren/Löschen und Dialoge nur im Browser-Speicher. Sie ist kein React-Code, kein produktiver Nachrichtendienst, keine Modell-/Trainingsausführung und kein Nachweis fertiger F4-Implementierung. Im Produktivsystem dürfen die beschrifteten Beispieldaten und "DEMO · OFFLINE" nicht als tatsächliche Statusdaten übernommen werden. Die bestehende React-/Protobuf-/Backend-Architektur bleibt die einzige Laufzeit.

#### F7.1 Verbindliche Position und Gestaltung

- **App-Kopfzeile:** Pinkes C links, Hauptnavigation **Übersicht · Nachrichten · ComfyUI · Dateien · Wallet · Einstellungen** in derselben Zeile; rechts nur tatsächlich vom Backend bestätigter Status. Keine weiteren Hauptreiter (Wallet seit V1.12, F7.8; **[17.11.]** Einstellungen seit S1).
- **Übersicht:** Titel, knappe Unterzeile, die drei im freigegebenen Screenshot sichtbaren Informationskarten *Kundenakten*, *GPU-Warteschlange*, *Freigaben ausstehend*; darunter *Aktuelle Kunden · anklicken zum Öffnen*. Werte ausschließlich aus echtem Backendzustand. Klick auf einen Kunden öffnet seine vorhandene Kundenakte im Reiter Nachrichten und nicht eine zweite Kundenansicht.
- **Nachrichten — drei feste Desktop-Spalten:** **Links** Kundenliste mit Suchfeld, Einträgen und Kanalkennzeichen; **Mitte** offene Kundenregisterkarten, Kontakttitel/-ID, Unterregister *Gesamter Verlauf / Instagram / Telegram / WhatsApp*, Chronologie und kanalgebundenes Antwortfeld; **rechts am äußersten Rand** die vollständige und scrollbare **Kundensteuerung**. Kein Verschieben der Steuerung in die Mitte. Stil: Graphite-Dunkelgrau, dezente Trennlinien und pinke Marke/Auswahl. Screenshot-Abmessungen als proportionale Leitlinie; responsives Verhalten darf Elemente umordnen, die fachliche Zuweisung jedoch nicht.
- **ComfyUI — drei feste Desktop-Spalten:** **Links ausschließlich Workflows** der jeweiligen Instanz/Registry (keine "Aufträge & Workflows"); **Mitte** Prompt-/Quellbild-/Masken-/Trainings-Arbeitsfläche und echte Ergebnisse; **rechts äußerster Rand** **Steuerung**, erweiterte Workflow-Einstellungen (**initial geschlossen**), **Generieren**, darunter persistente **Warteschlange und Instanzstatus**.
- **Dateien:** Bewährten Bestand \`frontend/src/pages/Files.tsx\` weiterverwenden; **Einzelauswahl, Mehrfachmarkierung, Alle markieren, Markierung aufheben, Einzel-X, Löschen (n) inklusive Bestätigungsdialog, Filter Alle/Fotos/Videos, Öffnen, Download** bleiben unverändert funktionsfähig. Ergänzung ausschließlich über jedes einzelne Medium bzw. dessen Detailansicht: **Weiterverarbeiten** einschließlich Wiederholen/Variieren/Als Vorlage verwenden/Video daraus erzeugen/Hochskalieren. Keine zweite Galerie, keine neue Kartenästhetik.
- **Wallet:** Gestaltung nach F7.8 (Darstellung der DarkBot-BSC-Wallet-Ansicht in Graphite), Beschriftungen deutsch.

#### F7.2 Linke Nachrichtenspalte — Bedeutung jedes Elements

| Element | Funktion / Backend-Vertrag |
|---|---|
| **Kunden** + Anzahl | Zahl der kanonischen Kundenakten; interne Default-Identität gesondert markieren, nicht als zahlenden Kunden zählen. |
| **Kunde suchen** | Vorhandene Kundenakte per Name, stabiler Kundennummer oder Plattformidentität finden; nur gefilterte Liste ändern, nicht Kunden löschen. |
| **Kundenzeile** mit Avatar, Name, Untertitel, IG/TG/WA | Zur Akte wechseln, bestehende Registerkarte aktivieren oder neu öffnen; letzten Zustand/Ungelesen aus gespeicherten Backend-Events. Nicht allein aufgrund identischen Namens Kanäle zusammenführen. |
| **Default** | Bei der Ersteinrichtung einmalig angelegter **interner Kontakt** für das private Telegram (und optional das private Instagram) des Betreibers, der an Claras Konten schreibt; besondere Steuerung rechts statt Verkaufsakte. Kein regulärer Kunde, keine Zahlungspflicht für eigene interne Produktionsaufträge. |
| **+ Instagram-Kontakt** | Nur durch tatsächlich unterstützte Kanal-/Kontaktfunktion einen Kontakt anlegen/verknüpfen, niemals mit simuliertem Eingang. Erstkontakt darf den Fokus einer bestehenden Karte nicht stehlen. |

#### F7.3 Mittlere Nachrichtenspalte — Bedeutung jedes Elements

| Element | Funktion / Backend-Vertrag |
|---|---|
| **Geöffnete Kundenregisterkarten**, z. B. Leon 1041, Erik 1042 | Mehrere Kunden gleichzeitig offen halten; Aktivieren wechselt die Mitte und die rechte Steuerung atomar. **×** schließt ausschließlich die Registerkarte, nicht Kundenhistorie, KI, Queue oder Plattform-Konversation. |
| **Kontaktkopf**, Kundenname, Kundennummer, Handle | Zeigt kanonische Identität und zugeordnete aktuelle Akte; kein beliebiger Anzeigename als Identitätsschlüssel. |
| **Kanalwechsel** | Im Design sichtbare Aktion; technische Übergabe Instagram→Telegram gemäß F4 (Token/Bestätigung); keine stille Kanalidentitäts-Zuordnung und kein blindes Senden. |
| **Gesamter Verlauf** | Zusammengeführter, chronologischer Verlauf aller bestätigten Kanäle einschließlich Ereignissen; **ausschließlich lesen, ohne Composer oder Antwortaktionen**. |
| **Instagram / Telegram / WhatsApp** | Filtert Verlauf und ist bei aktivem, verifiziertem Kanal die **einzige** Wahl des Antwortziels; inaktive Kanäle sind nicht sendbar. |
| **Nachrichtenblasen** | Eingehend links, ausgehend rechts; kanaltypische Farben IG pink, TG blau, WA grün, plus Text-Kanalnamen, Uhrzeit, Anhänge, Zustellstatus. |
| **System-/Fachereignis** | In chronologischer Reihenfolge zwischen Nachrichten: Erstkontakt, Dialogschwelle, Medienwunsch, Anfrage, Angebot, verifizierte Zahlung, Prompt, Render, Kandidaten, Freigabe, Versand, Fehler. Nur echte verifizierte Events; keine Demo-Zahlungen. |
| **Eingabefeld** | Text an **genau die geöffnete, geprüfte** Plattform-Konversation (eigener Kanal-Adapter) des ausgewählten Kanalregisters; Entwürfe kanal-/revisionsgebunden. |
| **KI antworten** | Startet genau eine KI-Antwort oder einen bearbeitbaren KI-Entwurf im aktiven Kanal; nicht in Gesamt; keine LLM-Autorität über Zahlungs-/Freigabestatus. |
| **Antwort senden** | Versendet ausschließlich den aktuellen manuellen Text in den aktiven Kanal; Backend prüft Kunden-/Kanal-/Conversation-/Revisions-IDs und Idempotenz. |

#### F7.4 Rechte Nachrichtenspalte — **Steuerung**, nicht Erklärungstexte

Der äußerste rechte Rand enthält **reale Bedienelemente und reale Akteninformationen**, keine Architekturprosa. Bei Wahl eines normalen Kunden zeigt die Spalte folgende Gruppen in dieser Reihenfolge:

| Gruppe / Feld | Exakte Wirkung |
|---|---|
| **Kundenakte · Nummer** | Anzeige der aktiven kanonischen Kundenakte; Wechsel der offenen Registerkarte wechselt vollständig deren rechte Steuerung. |
| **IDENTITÄT & DIALOG** – Kunde, aktive Kanäle, Instagram-Dialogzüge | Verifizierte Identitäten, Dialogzähler aus echten Nachrichten/Projektion; Kundengedächtnis und Gesprächszusammenfassung aus SQLite. |
| **Charakter-LLM** | Zuordnung der aktiven Influencerin und ihres qualifizierten LLM-Workflows. Melody erst nach bestandener B5.1-Messung als laufendes Modell ausgeben. |
| **Telegram-Übergang** – Schwelle, Fortschritt, Einladung | Konfigurierbare Dialogschwelle (F4: 10–30), echte Fortschrittsanzeige; **Telegram anbieten** erzeugt zulässigen Einmal-Token und sendet nur nach bestätigtem Kanal. Keine reine kosmetische Aktion. |
| **KI-Steuerung – Influencerin** | Explizite, versionierte Figur-Zuordnung; keine stillen Wechsel oder fremden Kundengedächtnisse. |
| **Antwortmodus** | Automatisch / Entwürfe prüfen / Manuell; pro Kundengespräch, mit Handoff/Revision gegen überholte KI-Antworten. |
| **Text-KI** | Schaltet nur erlaubte KI-Textverarbeitung, nicht manuelles Senden. |
| **Automatische Textantworten** | Unaufgeforderte LLM-Antworten aktiv/inaktiv, unabhängig von manuellem **KI antworten**. |
| **Modelle und Fähigkeiten** (standardmäßig geschlossen) | Text-LLM, Antwortlänge, Stimm-/TTS-Modell, Sprachversand, Bildautomatik, Foto-/Videomodell, Workflow, Charakter-/LoRA-Zuordnung, Zweit-KI-Prüfung und Freigabemodus; nur tatsächlich qualifizierte Optionen aktiv. Derselbe Block trägt das Influencerin-Profil und die Preisliste (F4 V1.12 Punkt 12). |
| **MEDIENWUNSCH** | Konkreter Kundenwunsch mit Quellen, Text-/Bild-/Videoart und offener Rückfrage. |
| **Prompt & Produktion** | Pro Auftrag tatsächlicher Prompt/Negativ-Prompt falls unterstützt, gewählte Figur, Workflowversion, Rendermedien, Status und Kandidaten. Ein Artefakt hat dieselbe ID unter Dateien. |
| **AUFTRAG & FREIGABE** | Pro Bestellung eigenständiger chronologischer Verlauf: Anfrage → Angebot → tatsächlich bestätigte Zahlung → Generierung → Auswahl/Prüfung → Freigabe → Zustellung. Ohne verifizierte Zahlung/Freigabe kein Kundenversand. |

**Default-Spezialfall:** Der Kontakt **Default** nutzt dieselbe Nachrichten-Layoutstruktur; nur die rechte Akte wechselt zu echten Operator-Feldern: **Instagram-Absender-ID**, **Telegram-Absender-ID**, **Interne Befehle verarbeiten (Ein/Aus)**, **Influencerin**, **Medien-KI/Workflow**, **Freigabemodus**, **Automatische Produktionsaufträge (Ein/Aus)** und **Einstellungen übernehmen**. Der festgelegte Absender wird nach Ersteinrichtung über unveränderliche Plattform-ID geprüft. Die sechs Klartextkommandos **clone · pose · style · remix · animate · edit** (`edit` nur auf nachweislich eigenen Bildern, PHASENPLAN_V0 §8) werden aus Nachrichten erkannt und **nicht** als separate Schaltflächen angezeigt; zusätzlich versteht die KI-Instanz freie Anweisungen mit Referenzen wie „die letzten 3 Fotos“ (PHASENPLAN_V0 §8.1). **Kein zusätzliches Kapitel „Produktionsakte“ oder Beschreibungsblock im rechten Default-Bereich.** Für verarbeitete Medien erscheinen echte Auftrags-/Render-/Ergebnisereignisse in der bestehenden Mitte und bei Dateien; zusätzlich gehen die Ergebnisse je **Freigabemodus** (*Direkt zurücksenden · Nach Auswahl im Cockpit · Nur Cockpit*) als Dateien an die verifizierte Telegram-ID des Default-Kontakts zurück, damit der Betreiber vom Handy postet (Betreiberentscheidung 15.11.2026, PHASENPLAN_V0 §8.1); der Rückversand-Status erscheint als Ereignis im Default-Verlauf. Unter dem Operator-Feld **Influencerin** ist derselbe geschlossene Block *Influencerin · <Name> · gilt für alle Kunden* erreichbar wie in der Kundenakte (F4 V1.12 Punkt 12).

#### F7.5 ComfyUI — jedes Feld und die beiden Instanzen

**Ergänzung mit Vorrang für die KI-Ansicht (Betreiberfreigabe 16.11.2026):** Die konkrete Anordnung und Interaktion des KI-Studios ist in **F7.9** verbindlich. Sie erweitert F7.5 innerhalb von **ComfyUI → KI**, ohne das bestehende Drei-Spalten-Layout, die Medienfunktionen, das Graphite-Design oder die Hauptreiter (**[17.11.]** sechs) zu verändern. Der vom Betreiber am 16.11.2026 ausdrücklich freigegebene klickbare HTML-Prototyp `Darkfluenzer_KI_Studio_Klickprototyp.html` ist die exakte visuelle und interaktive Designreferenz; F7.9 fixiert dessen bedienbare Elemente, Zustände und den produktiven End-to-End-Vertrag. **DEMO-Daten sind niemals produktive Daten.**

| Element | Exakte Funktion / Einschränkung |
|---|---|
| **Fotos / Videos** | Unterregister der Medieninstanz, Liste ausschließlich nach \`kind\` der registrierten Workflows. **KI** als ergänzender Zugang zu ComfyUI 2 erst bei implementierter KI-Instanz; keine Behauptung, diese sei bereits online. |
| **Linke Workflowliste** | Sämtliche registrierten Workflows der passenden Kategorie samt Name, PASS/OFFEN, aktiviert/bereit nach echter Registry. Auswahl bestimmt Mittelpunkt und gesamte rechte Parametersteuerung. Ein fehlendes/ungeprüftes Modell darf keinen Render starten. |
| **Motiv/Prompt** | In das konkrete Graph-Feld \`prompt\`; für Video bezeichnet es Szene/Bewegung. |
| **Negativ-Prompt** | **Nur** wenn \`negative_prompt\` in der ausgewählten Workflow-Registry vorhanden ist. |
| **Ausgangsbild / Aus Dateien** | Bild-/Dateiauswahl für workflowgebundenes \`image\`, sowohl lokal als auch mit exakter Artefakt-ID aus der vorhandenen Galerie. |
| **Maske** | Nur bei maskenfähigem Workflow; weiße Fläche editieren, schwarze schützen; Auftrag hält SHA/Herkunft von Bild und Maske. |
| **Ergebnis** | Nach abgeschlossener echter Ausführung die resultierende Bild-/Videodatei und zugeordnete Job-ID, nicht drei permanente fiktive Kandidatenflächen. |
| **Rechte Steuerung – Charakter** | Auswahl der vorhandenen, versionierten synthetischen Influencerin; nachgewiesene Modell-/Identitätsbindung Voraussetzung für produktive Charakterläufe. |
| **Rechte Steuerung – Workflow** | Nur Anzeige des links ausgewählten konkreten Graphen/Version; keine zweite, widersprüchliche Auswahl. |
| **Erweiterte Workflow-Einstellungen** | **Initial zugeklappt**. Dynamisch **alle tatsächlich exponierten Eingänge** des gewählten Workflows anzeigen und serverseitig prüfen: seed, steps, cfg, width, height, denoise, mask_grow sowie künftig checkpoint, sampler, scheduler, guidance, batch, LoRA/Adapter, Frames/FPS/Dauer, Kamera-/Bewegungssteuerung, Refinement/Output, soweit die Nodes sie tatsächlich unterstützen. Keine Attrappen und keine erfundenen „Qualität“-Slider. |
| **Trainingsdatenordner** | Für registrierten Trainingsworkflow Standard **[17.11.]** \`local/characters/<kürzel>/photos/\` (B1). Sämtliche geeigneten Bilddateien im Verzeichnis werden gescannt, dedupliziert, zu einem versionierten Datensatz zusammengefasst und nach Bestätigung trainiert. Originale nicht löschen. Zunächst \`CHAIN-00/01\` OFFEN; kein Trainer-PASS ohne echten ComfyUI-1-/MPS-Trainingsnachweis. |
| **Generieren / Training starten** | Typisierter Protobuf-Befehl an genau den ausgewählten geprüften Workflow, persistenter Auftrag mit FIFO-/Status-/Artefaktbezug. Bei gesperrten/fehlenden Modellen deaktiviert. |
| **Warteschlange (rechts unter Steuerung)** | Persistente globale Medien-GPU-FIFO, echte Position/Status/Progress nur mit Backendquelle; ComfyUI 2 hat separate KI-Queue. Wartende Betreiberentscheidungen blockieren keinen anderen ausführbaren Medienjob. |
| **Instanzen** | Medien-ComfyUI 1 Default \`127.0.0.1:8188\`, KI-ComfyUI 2 \`127.0.0.1:8189\`; eigenständige Prozesse/Queue, gemeinsamer GPU-Speicher. Keine fiktiven Health-Zustände. |
| **Workflow öffnen / bearbeiten / übernehmen / löschen** | Bestehender F3a-Vertrag bleibt uneingeschränkt: exakten UI-/API-Graphen bearbeiten, validieren, versionieren; beim Löschen nur betroffenen Workflow entfernen, niemals Modell oder historische Artefakte. |

#### F7.6 Dateien — Ergänzung, keine Neugestaltung

Bestehende React-Bedienung und Sicherheitsbedingungen bleiben: In \`Files.tsx\` sind **Alle markieren**, Markierung aufheben, Einzel-X und Mehrfachlöschung samt Bestätigung bereits vorhanden. Kundenzugeordnete Medien dürfen durch die Betreiber-Galerie nicht per Einzel- oder Stapel-X gelöscht werden (bestehendes \`orderNo\`-Gate); dieser Schutz bleibt bestehen.

**Neu pro tatsächlicher Mediendatei:** **Weiterverarbeiten** führt in die passende Workflow-Auswahl und übernimmt den exakten aktuellen Artefakt- und SHA-Verweis, niemals bloß einen Bildnamen. In der Datei-Detailansicht **Wiederholen · Variieren · Als Vorlage · Video erstellen · Hochskalieren** (2K/4K aus dem Original ohne Neugenerierung, PHASENPLAN_V0 §9.7). Zusätzlich vollständige lesbare Produktionsparameter und alle Versionen aus dem tatsächlichen Job/Graph-Snapshot, ohne leere oder erfundene Werte. Filter Alle/Fotos/Videos und chronologische Nummerierung unverändert.

#### F7.7 Bild-/Designreferenz, Integration und Abnahme

Die freigegebene **Übersicht** und **Nachrichtenansicht** sind im Betreiber-Chat durch zwei Original-Screenshots vom **14.11.2026** dokumentiert: dunkelgrauer Graphite-Hintergrund, pinkes C, kompakte Registerleiste, drei KPI-Karten bei Übersicht; bei Nachrichten **Kunden links, mittig Kundenregisterkarten und kanalgefilterte Zeitleiste, am rechten äußersten Rand die detaillierte Kundensteuerung**. Diese Screenshots sind die verbindliche visuelle Prüfreferenz; der HTML-Prototyp stellt die Layoutstrukturen und die Bedienwege zusätzlich interaktiv bereit. Originalbilder sind weder automatisch Git-Assets noch ComfyUI-Ausgaben und dürfen nicht als solche ausgegeben werden.

**Testfälle:** Hauptnavigation (**[17.11.]** sechs Reiter), Kundenliste/Öffnen/Schließen, Kanalfilter und Gesamt-Leseschutz, wechselnde rechte Steuerung, Default-Kontakt nur als interne Identität, einklappbare KI-Felder, ComfyUI-Workflowtypen und zielgenaue Parameter, initial geschlossenes Expertenmenü, Trainingsordner, rechts Warteschlange, Dateien-Markierung und Löschbestätigung, Weiterverarbeiten. Ein eigenständiger HTML-Klicktest belegt nur UI-Verhalten. F3/F4/CHAIN-00–06 benötigen jeweils echte Backend-/Mac-/Plattform-Abnahme.

**Umsetzungsauftrag an Claude:** Die HTML-Referenz und **diesen** Abschnitt F7 als genaue visuelle/bedienlogische Abnahmequelle lesen, mit dem bestehenden React-Code abgleichen und nur die tatsächlich fehlenden Funktionen ändern. Kein Repo-Rewrite, keine neue UI-Bibliothek, keine neue Persistenz- oder Render-Engine. Vor jedem Layout-Umbau Ausgangsscreenshot und vorhandene Komponenten vergleichen. Vor Implementierung technische Abweichungen zur Registry bzw. zum Graph ausdrücklich benennen. Nach Anpassung echte Mac-Screenshots gegen die Betreiber-Screenshots und HTML-Referenz prüfen.

#### F7.8 Wallet — fünfter Hauptreiter (verbindlich, V1.12 / PHASENPLAN_V0 §8.5, C5a)

**Vorlage:** die Darstellung der DarkBot-BSC-Wallet-Ansicht (`frontend/src/features/bsc/pages/WalletsPanel.tsx`, `WalletAccounts.tsx`, `WalletHistory.tsx`, `WalletParts.tsx` im DarkBot-Repository) als **eigenständige Kopie** in `frontend/src/pages/Wallet.tsx` (bei Bedarf `pages/WalletParts.tsx`); Stil ausschließlich über `shared/graphite.css`; keine Imports, keine Laufzeitverbindung zu DarkBot. **Nicht übernommen:** PnL- und Tages-PnL-Kurven und -Tabellen, Transfer, Auszahlung, Richtlinien (Refill/Profit/Payout), BUYER-Schalter, Budgets, Touch-ID-Dialoge, Signier- und Sendewege, technische Owner-Zeilen der BSC-Engine.

| Bereich | Inhalt / Backend-Vertrag |
|---|---|
| **Kopf** | Titel „Wallet“, rechts nur der belegte Zustand der Datenquellen (STATE 10). |
| **Konten** (Kontokarten wie DarkBot: Titel + Chevron, großer Wert) | *Bitcoin* (BTC-Guthaben), *BSC* (USDT, USDC), *PayPal* (bestätigte Eingänge im laufenden Monat, kein Kontosaldo), *Amazon-Gutscheine* (eingelöst im Monat · zu prüfen). Euro-Wert und Kurszeit je Karte; ohne frische Daten „veraltet“, nie ein alter Wert als aktuell. |
| **Konto-Schublade** (Chevron) | vollständige öffentliche Adresse mit **Kopieren** und QR-Code, Netz, letzte geprüfte Block-/Zeitangabe, Datenquelle; kein Seed, kein Schlüssel, kein Senden. |
| **Zahlungseingänge** (Verlaufstabelle wie DarkBot) | Datum · Weg · Betrag · Euro-Wert · Kunde/Auftrag (Link in die Akte) · Transaktion (gekürzt, vollständig in den Details) · Status; Filter *Alle · Offen · Bestätigt · Nicht zugeordnet*; Seiten über `GET /api/v1/payment-page` (Protobuf, bei Aufruf), neue Einträge per EVENT 30. |
| **Nicht zugeordnet** | je Eingang **Zuordnen** (Auftrag wählen, Bestätigung, Befehl 41 mit Receipt); protokolliert. |
| **Gutscheine zu prüfen** | Code (nur hier sichtbar, maskiert mit Aufdecken), Kunde, Zeit; **Eingelöst · Betrag eintragen** (Befehl 42, Bestätigungsdialog); erst danach `ZAHLUNG BESTÄTIGT`. Einzige zulässige manuelle Zahlungsbestätigung. |
| **Monatsliste** | Download je Monat (`GET /api/v1/payment-export/{monat}`) mit Euro-Wert und Kurs beim Eingang. |
| **Technische Details** (Schublade) | Datenquellen (Kursquelle, BTC-Schnittstelle, BSC-RPC, PayPal), letzte erfolgreiche Abfrage, Fehler. |

**Abnahme:** **[17.11.]** zuerst PayPal und Amazon-Gutschein (E6); Krypto nur, wenn zugeschaltet: echte Adressen aus `config.toml` mit QR; eine echte kleine BTC- und USDT-Zahlung erscheint live per Push und wechselt nach den Bestätigungen auf *Bestätigt* mit Kundenzuordnung; ein falscher Betrag steht unter *Nicht zugeordnet* → Zuordnen mit Receipt; ein Gutschein wird erst nach Betragseintrag bestätigt; Reconnect ohne Dubletten; kein Sende-Element im DOM; Build- und Stylesheet-Wächter grün.


---

#### F7.9 KI-Studio – verbindliche klickbare ComfyUI-2-Referenz (Betreiberfreigabe 16.11.2026)

**Verbindliche Betreiberentscheidung:** Der am 16.11.2026 im Chat freigegebene klickbare **Darkfluenzer-KI-Studio-HTML-Prototyp** ist die maßgebliche Gestaltung und Interaktion für die KI-Seite in **ComfyUI**. Die im Prototyp sichtbaren Register, Formularanordnungen, Button-Texte, Spalten und Arbeitsabläufe sind umzusetzen; echte Zustände und Modellantworten dürfen nicht durch Beispielwerte ersetzt werden. Die HTML-Vorschau selbst ist ausschließlich eine **offline lauffähige Designreferenz**: ihre simulierten Antworten, Modellnamen, Werte und sechs geplanten Workflows beweisen keine installierte KI. **Bei Konflikt mit einer älteren generischen ComfyUI-Anweisung gilt für den KI-Reiter dieses F7.9; für Fotos/Videos F7.5.**

**1. Einbettung und visuelle Übereinstimmung**

- **Keine neue App, kein weiterer Hauptreiter, kein neues Design.** Kopfzeile mit pinkem **C** links, genau **Übersicht · Nachrichten · ComfyUI · Dateien · Wallet**; **ComfyUI** aktiv. Darunter die Unterregister **Fotos · Videos · KI**, jeweils mit einer **real aus Registry/Backend ermittelten** Workflow-Anzahl. Der Vorschau-Zähler \`KI 6*\` bedeutet sechs **vorgesehene** Workflowtypen, **nicht sechs fertige** Workflows; im Produkt nie als sechs bereit anzeigen, wenn nicht registriert.
- **Graphite** aus dem freigegebenen F7-Stil: dunkelgraue Hauptflächen (Referenz \`#1c1c1f\`), dunklere Sidebar, feine graue Grenzen (Referenz \`#414149\`), helle Schrift, zurückhaltende pinke Selektion/Aktion (Referenz \`#ed2287\`). **Nur bestehendes Stylesheet \`shared/graphite.css\`** im React-Produkt; kein eigenständiges Designsystem.
- **Drei feste Desktop-Spalten:** **links ausschließlich Workflowliste**, **Mitte Arbeits-/Ergebnisbereich**, **rechts äußerster Rand Steuerung**. Die KI-Seite ersetzt in der Mitte je nach Workflow Testchat, Persona, Memos, Bildanalyse, Training oder Audio; **sie baut kein zweites Chat-Cockpit** unter Nachrichten auf. Bei schmalen Ansichten darf die rechte Steuerung untergeordnet werden, nicht die fachliche Zuordnung ändern.
- Links Überschrift **KI-Workflows**, darunter **ComfyUI-Instanz 2** und eine Liste aktivierbarer **registrierter** Workflows. Jede Zeile zeigt Workflowname, Funktion sowie tatsächlichen Zustand **bereit / offen / Fehler**, selektiert pink. Es gibt **keine** alternative linke Job-/Projekt-/Kundenliste.
- Rechts **Steuerung** mit Gruppen für die **konkrete** Workflowauswahl, danach persistente **KI-Warteschlange** und **ComfyUI-2-Instanzstatus**. Erweiterte Parametergruppen sind **anfangs geschlossen**. Keine Anzeigen \`Verbunden\`, \`PASS\` oder Leistungswerte ohne reale Backendnachweise.

**2. Sechs verbindliche Workflowklassen in ComfyUI-Instanz 2**

| KI-Workflow im linken Bereich | Zentrale Arbeitsfläche | Umsetzungsphase |
|---|---|---|
| **Textdialog · Melody1437 v2.0** | Direkter mehrteiliger Chat-Test mit Clara, gleicher Workflow wie im Kundenbetrieb | **B5 sofort** |
| **Bildverständnis · VLM** | Referenzbild → Bildbeschreibung, Kamera/Licht/Pose/Kleidung/Szene → strukturierter Prompt-Vorschlag | B5, nach Chat-End-to-End |
| **Gesprächsmemos** | Erinnerungen, Quellen, Korrekturen, Abrufvorschau und Verwaltung | B5/C5 sofort für Textchat |
| **Text-LoRA · Training** | Eigene Beispiele, Import, Datensatzprüfung, Training und A/B-Abnahme | **Später; keine Vorabdownloads** |
| **Sprache → Text** | Audiodatei/Mikrofon → lokale Transkription, Fehler und Laufzeit | **Später; ASR** |
| **Text → Sprache** | Testtext → Clara-Stimme, Ton/Sprechgeschwindigkeit → Audio-Wiedergabe und Latenz | **Später; TTS** |

Alle **wirklich ausführbaren** KI-Stufen laufen als versionierte, im echten **ComfyUI-2-Editor** öffnungs-/bearbeitbare Graphen mit korrektem UI-/API-Graph, Registry-Bindings und Rückübernahme. **Kein Ollama, keine dritte KI-Engine, kein externer LLM-Server.** Das Python-Backend orchestriert Kontext, Identität und technische Gates, speichert Daten dauerhaft in derselben SQLite und ruft für KI-Arbeit **ComfyUI 2** auf. **[17.11., E19]** Alle sprachlichen Regeln, Anweisungen und Verhaltensvorgaben stehen in den Prompts der ComfyUI-2-Workflows; das Backend hat keine eigene Sprachlogik. Text-LoRA-Training darf intern native Trainingsbibliotheken benötigen; Steuerung, Workflowregistrierung, Status und Ergebnisse bleiben über ComfyUI 2 und das bestehende Cockpit angebunden. Der bloße Titel \`Gesprächsmemos\` bedeutet **nicht**, dass SQLite-Operationen fälschlich innerhalb der GPU-Engine ausgeführt werden.

**3. Textdialog → Chat-Test: exakter Bedienweg**

- In der **Mitte** Kopf **Textdialog · Melody1437 v2.0 Q6_K**, Untertitel *Direkt im Cockpit testen · dieselbe KI wie später auf Telegram und Instagram*.
- Direkt darunter die vier **inneren** Ansichten **Chat-Test · Persona · Gedächtnis · Vergleich**; sie ändern **nur die Mitte**, die linke Workflowauswahl und die rechte Steuerung bleiben an derselben Position.
- **Chat-Test:** scrollbarer echter Gesprächsverlauf, links eingehende/botseitige und rechts operatorseitige Nachrichtenblasen; Textfeld **„Nachricht an Clara …“** mit Enter=Senden, Shift+Enter=Zeilenumbruch, **Neue Sitzung** und **Testantwort**. Beispiel-Prompts (*Hallo Clara!*, *Was hast du heute gemacht?*, *Ich hätte gern ein Strandfoto von dir.*) sind anklickbare **Testeingaben**, keine automatischen Behauptungen über eine Modellantwort. Für jeden Test eine eindeutige Test-Sitzung; **keine Telegram-Verbindung erforderlich** und keine Kundenakte, kein Kundenversand.
- Nach jeder **echten** Inferenz: vollständige Antwort und technische Messwerte **Erstes Token (TTFT), Tokens/s, Gesamtzeit** (**[17.11.]** TTFT und Tokens/s nur, wenn der Knoten sie liefert; am gepinnten Knoten nicht belegt), ergänzt um Modellversion, Persona-Revision, Workflowversion, Antworttokens, Context-/Cache-Metriken und Fehlerstatus. **Keine fingierten Messwerte**. Streaming im lokalen Testchat zulässig, an externe Kanäle erst nach abgeschlossener Antwortprüfung.
- **Persona** (mittig): **[17.11., E19]** Promptprofil mit getrennten Feldern **Systemprompt**, **Persona (Charakterprofil)**, **Positive Anweisungen**, **Negative Anweisungen**, **Gesprächs- und Verkaufsstrategie**, **Beispieldialoge · gewünschter Schreibstil** und Funktionsanweisungen, je an einen echten Eingang von `clara_chat_melody` gebunden; Button **Persona übernehmen**; Versionsliste mit **Vergleichen**, **Im Test ausführen**, **Aktivieren**, **Zurücksetzen**. Speichern **versioniert per Protobuf**, beeinflusst unmittelbar nach Wahl derselben Version die nächste Testantwort; vorherige Tests verweisen weiterhin auf ihre Originalrevision. Enthält Hintergrund/Alter (erwachsen), Gesprächsstil, Antwortlänge, Eigenheiten, Flirtstil, verbotene Wörter/Themen, Eskalation und Admin-Warnung. **[17.11., E19]** Außerhalb von ComfyUI bleiben ausschließlich technische Berechtigungs-, Transaktions- und Versandprüfungen (KI-Hinweis gesendet, Sperre „minderjährig vermutet“, Beträge und Zahlungswege aus SQLite, Freigaben, Kanalgrenzen); alle sprachlichen Regeln wirken über den Prompt.
- **Gedächtnis** (mittig): *Gedächtnis · Sitzung*, **Notiz manuell hinzufügen**, Liste gespeicherter Memos mit Quellen/Nachrichten-IDs, Zeit, Status, **Korrektur/Löschen** (mit fachlichem Audit), sichtbarer **Kontextinspektor**: welche Memos werden für die nächste Antwort abgerufen und warum. Getrennte Kunden-/Test-Sitzungen; kein Überspringen der Identity-Grenze. Betriebskonzept: letzte Nachrichten + relevante Langzeitmemos, SQLite/FTS5-Retrieval; neues oder widersprochenes Wissen wird mit Herkunft behandelt; Zusammenfassungen nachrangig zur Chatlatenz.
- **Vergleich** (mittig): nebeneinander **A: Melody Q6_K** und **B: andere Persona-/Parametereinstellung oder LoRA** (weitere Chatmodelle nur nach neuer Freigabe), **dieselbe** Testeingabe, Persona und relevanter Kontext, getrennte Antwort, Latenz, qualitative Prüfergebnisse; B ist gesperrt, solange Gewichte/Workflow fehlen. Vergleichsergebnisse mit Versions-/Parameterbezug. **Keine Modelle nur wegen der Vorschau laden.**

**4. Rechte Steuerung bei Textdialog**

- Gruppe **MODELL & FIGUR**: verifiziertes Charakter-/Influencerin-Profil **Clara**, **qualifizierte** Textmodellvariante, Gesprächsstil; keine Fake-Optionen im produktiven Selector.
- Gruppe **TEXTGENERIERUNG**: echte exponierte Workflow-Parameter als Zahlen-/Slider-Eingaben, **Temperature, Top-P, Repeat Penalty, Max. Antwort-Tokens**. Unter **Erweiterte Workflow-Einstellungen** bei Unterstützung weitere Parameter wie **Top-K, Min-P, DRY, Seed, Kontextfenster, KV-/Prompt-Cache, Modell-/Graphrevision**. **[17.11.]** Geprüft am Knoten `LLMSessionChatNode` (`ec2b293c`): vorhanden sind `max_tokens`, `temperature`, `top_p`, `repeat_penalty`, `repeat_last_n`, `n_ctx`, `enable_thinking` und Cache-Einstellungen; Top-K, Min-P, DRY und Seed hat er nicht, sie entfallen. **Nur tatsächlich vom Workflow unterstützte Parameter**, mit Typ/Grenzen/Schritt/Default aus Registry statt festen Platzhalter-Slidern; serverseitige Validierung.
- Gruppe **GESPRÄCHSLOGIK**: **Langzeitgedächtnis verwenden**, Zustand der technischen Gates (nicht abschaltbar, nur angezeigt), **Einstellungen übernehmen**; **[17.11., E19]** der Schalter „Antworten gegen Regeln prüfen“ entfällt, weil die Gesprächsregeln im Prompt stehen; Settings gelten nur nach erfolgreichem Backend-Receipt, Session-/Profil-/Modellrevision werden im Ergebnis erfasst. Test kann zwischen Persona-/Parameterprofilen umschalten; **keine Änderung an laufenden Kundenakten ohne freigegebene explizite Betreiberaktion**.
- Unterhalb **KI-WARTESCHLANGE**, zuletzt **INSTANZ** mit realem Status der zweiten ComfyUI-Instanz (Default \`127.0.0.1:8189\`), Queue, Fehler, Ressourcenbelegung und belegter Erreichbarkeit. Gemeinsame Zulassung der beiden ComfyUI-Prozesse aus V0 §4.2; Chat-Latenz priorisiert. Alle Buttons führen über typisierte Protobuf-Befehle zum Python-Backend, Rückmeldungen per Receipt + STATE/EVENT statt Browserpolling.

**5. Übrige KI-Arbeitsflächen**

- **Bildverständnis:** Dateiauswahl über echte Referenz-/Dateien-ID oder lokalen Upload, Anweisungsfeld, \`Analyse starten\` **nur bei qualifiziertem Modell**, reale Ausgabe mit Beschreibung, Pose, Kamera, Licht, Szene, identitätsrelevanten Angaben und Promptentwurf, vor Weitergabe bearbeitbar, versionsgebunden. Der Vision-Workflow darf NICHT als Textchat-LLM ausgegeben werden.
- **Gesprächsmemos:** eigenes linkes Workflowziel kann dieselbe Gedächtnisverwaltung aus dem Testdialog öffnen; serverseitige Faktenablage und Kontexterstellung, kein zweiter Speicher. Status und Audit (Quelle, Korrektur, Ablauf/Retention).
- **Text-LoRA:** eigener Trainingsdialog mit Import von selbst geschriebenen/kurierten Beispieldialogen, Validierung, Dubletten-/Herkunftskontrolle, Trainings-/Prüfsatz, trainierbaren Modellgewichten/Adapter, Start/Fortschritt/Abbruch, Rückfall und A/B-Vergleich. **Erst nach abgenommenem ungefinetuntem Melody-Test (B5.1) freischalten**. Eine quantisierte GGUF-Datei (auch Q6_K) ist kein automatisch trainierbares Basischeckpoint.
- **Sprache → Text:** lokale Audioaufnahme/Datei, reale Transkription mit Wiedergabe/Status, Sprache, gemessene Latenz; erst später an Telegram-/Instagram-Sprachnachrichten anschließen.
- **Text → Sprache:** editierbarer Testtext, Stimme, Sprache/Tempo/Stil nur soweit vom TTS-Graphen unterstützt, **echter** lokaler Audioplayer und Zeitmessung; Antworten aus **demselben** Clara-Dialog/Persona/Gedächtnis. Kein zweites getrenntes Dialogmodell für Stimme.
- Ist der Workflow nicht installiert oder noch nicht abgenommen, zeigt die Mittelspalte **„Workflow noch nicht eingerichtet“** bzw. konkreten Backendfehler; **Generieren, Training oder Transkribieren bleiben deaktiviert**, statt ein angeblich reales Ergebnis zu simulieren.

**6. Abnahme (bindender, realer End-to-End-Vertrag)**

1. Aus **ComfyUI → KI → Textdialog → Chat-Test** mindestens 20 zusammenhängende deutsche Nachrichten mit Melody1437 v2.0 Q6_K **real auf dem M4 Max** erzeugen, ohne Telegram oder weiteren LLM-Server; Antworttexte, TTFT p50/p95, Gesamtzeit p50/p95, Tokens/s und Speicherverhalten belegbar.
2. Systemprompt, Persona, positive und negative Anweisungen, Strategie, Beispieldialoge und Generierungsparameter im Cockpit ändern, **Receipt und neue Revision** nachweisen; der zusammengesetzte Prompt des nächsten Laufs zeigt die Änderung, danach echten Modellantwort-Unterschied messen; ohne Neustart wirksam; eine frühere Version lässt sich wieder aktivieren; zwei Influencerinnen ohne Vermischung. Die Wahl eines unqualifizierten Modells führt zu klarer Sperre.
3. Gedächtnis: Fakten über mehr als das aktive Kontextfenster konsistent wieder abrufen, widersprochene Fakten korrigieren, Wiederholungen detektieren, mindestens einen Backend-Neustart überstehen; **Testidentitäten und fremde Kunden strikt getrennt**.
4. Gates: **[17.11., E19]** verletztes technisches Gate (KI-Hinweis fehlt, Akte gesperrt, Betrag passt nicht zu den Fakten) **vor externem Versand** abgefangen, Entwurf/Manuell möglich, Admin-Eskalation als echte Ereigniskarte; Anweisungen aus Kundentext ersetzen keine serverseitigen Fakten-, Zahlungs- oder Freigabestatus. Sprachliche Regeln wirken über den Prompt, nicht über eine Prüfung im Backend.
5. Gleicher registrierter Dialog-Workflow wird nach bestandener Studioabnahme in **Nachrichten/Telegram** für Claras Persona verwendet, nicht parallel neu implementiert. Kundentext → Wunsch → Preis aus Preisliste → vorbereiteter Prompt → echte Zahlung oder isolierter Testbetrieb → echter ComfyUI-1-Bildauftrag → Freigabe → Datei-Rückversand, keine fiktiven Bild- oder Zahlungsnachweise.
6. Trainings-/ASR-/TTS-Bereiche werden erst dann als **bereit** gezählt, wenn Modell, Graph, Backend, Frontend, wirklicher Job, Ergebnis und M4-Abnahme vorhanden sind; bis dahin sichtbar **OFFEN**, nicht ein irreführendes \`KI 6\`.
7. Vor dem produktiven Deploy: Vergleich mit dem **freigegebenen KI-Studio-Klickprototyp vom 16.11.2026** (**[17.11.]** Datei nicht im Repository; entfällt, bis sie vorliegt) auf Desktopbreite, Werkzeuge/Panelpositionen, kompakten Abstand, Graphite-Farben, Texte, Start-/Leer-/Fehlerzustände und Interaktionen; Abweichungen begründen, nicht stillschweigend neu gestalten.

**Reihenfolge:** **B5.1 Melody direkt testbar → B5.2 Chat-/Persona-/Parameter-Studio → B5.3 Langzeitgedächtnis → B5.4 Wunsch/Angebot/Prompt → B5.5 isolierter Telegram-Sofatest mit realem Bild** (**[17.11.]** ersetzt durch Kundentest T1/T2). Bildverständnis danach; Text-LoRA und ASR/TTS nur nach gesonderter späterer Freigabe. Dieser UX-Vertrag ergänzt die technischen Abhängigkeiten von V0 B5/C5, ohne deren Zahlungs-, Absender- und Sicherheitsgates für Live-Kunden aufzuheben.

**Ergänzung 16.11.2026 (verbindliche Betreiberentscheidung B5, Details in V0 „B5 – Detailplan Clara-Chat-KI“):** Erstes und einziges freigegebenes Chatmodell ist **Melody1437 v2.0 (Gemma 4 MoE) GGUF Q6_K**. Kopfzeile „Textdialog · …“, linke Workflowliste und Auswahl **MODELL & FIGUR** zeigen den Modellnamen **aus der Registry**, nicht fest verdrahtet; „Vergleich“ (B) bleibt gesperrt bis zu einer neuen Modellfreigabe. Reihenfolge damit: P0 aus `docs/bugs_v1.md` → **B5.1 Melody1437 direkt testbar** → B5.2 Studio → B5.3 Gedächtnis (vier Ebenen, FTS5) → B5.4 Wunsch/Angebot/Prompt → B5.5 Telegram-Sofatest (**[17.11.]** ersetzt durch T1/T2; `Cash` als Testwort in T2) → B5.6 VLM, B5.7 Text-LoRA, B5.8 STT/TTS später.
