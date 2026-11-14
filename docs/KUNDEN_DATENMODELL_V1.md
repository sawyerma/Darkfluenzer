# Darkfluenzer — Kunden-, Auftrags- und Datenmodell V1

**Stand:** 14.11.2026  
**Masterplan:** [PHASENPLAN_V1.md](PHASENPLAN_V1.md)  
**Engines und Workspaces:** [ENGINES_WORKFLOWS_V1.md](ENGINES_WORKFLOWS_V1.md)  
**Status:** Soll-Architektur; keine implementierte Kundendatenbank/Telegram-Anbindung vorhanden.

## 1. Verantwortlichkeiten und verbindliche Regeln

- **Eine Kundennummer pro realem Bot-Kontakt**, dauerhaft und stabil, z. B. `DF-C-000001`, `DF-C-000002`.
- Die eindeutige technische Telegram-Identität ist `(platform, bot_account_id, telegram_user_id)`; **Telegram-Username und Chat-ID sind keine verlässlichen alleinigen Personen-IDs**. Mehrere Chats desselben Telegram-Nutzers an denselben Bot werden korrekt zugeordnet.
- Die Kundennummer wird über eine **SQLite-Transaktion** vergeben. Kein Ordnerzähler, kein Zufallsnamenskonflikt, kein Nummern-Recycling nach Löschung.
- **SQLite ist die einzige Wahrheit** für Kunden-/Auftragsstatus, Zahlung, Zustimmung und Zustellung; Verzeichnisnamen und exportierte Dateien sind materialisierte Ansichten/Artefakte, nicht zusätzliche Datenbank-Autoritäten.
- Alle Interaktionen sind an eine `customer_id` und möglichst eine `conversation_id` gebunden. Jeder bezahlte Medienwunsch bekommt eine eigene `order_id`.
- Keine von Kunden oder LLM erzeugten freien Dateipfade und keine Namen/Telegram-Usernames als Verzeichnisbestandteile.
- Kein Ausliefern ohne **`payment_confirmed` und `operator_approved`** für die **konkrete Auftrags-/Artefaktkombination**. Autorisierung ausschließlich backendseitig.
- Menschen- oder Zahlungsdaten nicht in Git; auf Datensparsamkeit, definierte Aufbewahrung und Zugangstrennung achten.

## 2. Projektstruktur und lokale Laufzeitdaten

**Versioniert in Git** (Code, keine Kundendaten):

~~~text
8_Darkfluenzer/
├── docs/
│   ├── PHASENPLAN_V1.md
│   ├── ENGINES_WORKFLOWS_V1.md
│   └── KUNDEN_DATENMODELL_V1.md
├── apps/
│   ├── macos-launcher/
│   └── operator-ui/
├── src/darkfluenzer/
│   ├── core/
│   ├── runtime/
│   ├── comfy/
│   ├── llm/
│   ├── identity/
│   ├── jobs/
│   ├── sales/
│   ├── payments/
│   ├── review/
│   ├── telegram/
│   ├── delivery/
│   ├── storage/
│   └── observability/
├── workflows/                   # Nur versionierte Workflow-Definitionen
├── configs/                     # Nur öffentliche Vorlagen
├── scripts/
└── tests/
~~~

**Nicht versioniert** (lokale personenbezogene und generierte Inhalte):

~~~text
local/
├── config/
│   ├── app.toml                   # Keine Secrets im Klartext-Repo
│   └── secrets/                   # Zugriffsrechte 0700
├── data/
│   ├── darkfluenzer.sqlite3      # Datenbank als alleinige Statusquelle
│   └── backups/                  # Verschlüsselte, rotierende Sicherungen
├── customers/
│   ├── DF-C-000001/
│   │   ├── conversations/
│   │   │   └── CONV-000001/
│   │   │       └── exports/       # Optionaler redigierter Chat-Export
│   │   ├── orders/
│   │   │   └── DF-O-000001/
│   │   │       ├── requests/      # Versionierte interne Prompt-Spezifikationen
│   │   │       ├── references/    # Vom Kunden bereitgestellte Medien
│   │   │       ├── masters/       # Unveränderliche Masterbilder
│   │   │       ├── masks/         # Objektmasken, Varianten, Versionen
│   │   │       ├── candidates/    # 3 Bilder oder 3 Videos
│   │   │       ├── refined/       # Korrigierte Vorschläge
│   │   │       ├── previews/      # Redaktionelle Vorschauen für Betreiber
│   │   │       ├── approved/      # Konkretes freigegebenes Artefakt
│   │   │       ├── delivered/     # Ausgelieferte unveränderliche Kopie / Verweis
│   │   │       └── receipts/      # Nicht-sensitive Zahlungsnachweise / Quittungen
│   │   └── exports/              # Portable Kundenauskunft (bei Bedarf)
│   └── DF-C-000002/
├── common/
│   ├── character_profiles/       # Gesicherte eigene Referenzprofile der Figur
│   └── reusable_assets/          # Gemeinsame, lizenzierte nicht-personale Assets
├── models/                       # Große Modellgewichte, nach Engine organisiert
├── ComfyUI/                      # Installation oder Symlink, verifiziert in P00
├── queue/                        # Laufzeit-Warteschlange / temporäre Dateien
├── logs/                         # Rotierende strukturierte Logs
└── run/                          # PID, Locks, Health-Dateien
~~~

**Dateibenennung in einem Auftrag:** deterministische IDs, z. B. `master_0001.png`, `candidate_01.png`, `candidate_02.png`, `candidate_03.png`, `preview_01.jpg`, `delivery_01.png`. Video analog `.mp4`. **Hashes und Versionen in SQLite**, nicht aus Dateinamen ableiten. Keine sensiblen Inhalte in Logs.

## 3. Datenbanktabellen (normatives Soll-Schema)

| Tabelle | Primärschlüssel / Beziehungen | Inhalt / Regel |
|---|---|---|
| `customers` | `customer_id` (interne UUID/ULID), eindeutige `customer_number` | Anlagezeit, Status, Sprache, Präferenzen, Aufbewahrung |
| `customer_platform_accounts` | `platform_account_id`, FK `customer_id` | Eindeutiger `(platform, bot_account_id, external_user_id)`; Usernames nur Anzeige |
| `conversations` | `conversation_id`, FK `customer_id` | Kanal, Verlauf, zuletzt bearbeitete Nachrichtenposition |
| `messages` | `message_id`, FK `conversation_id` | Richtung, Typ, Eingangszeit, Telegram-Nachrichten-ID, Inhalt/Medienreferenz |
| `intents` | `intent_id`, FK `customer_id`, `conversation_id` | Extrahierter Medienwunsch, Confidence, qualifiziert ja/nein, Referenz zu Nachrichten |
| `offers` | `offer_id`, FK `customer_id`, `intent_id` | Produkt/Preis/Währung, Version, Zeitpunkt, Annahme und Ablauf |
| `orders` | `order_id`, FK `customer_id`, `offer_id` | Medienart (`image`/`video`), Auftrag, zuständige Engine, Status |
| `payment_transactions` | `payment_id`, FK `order_id` | Provider, externe Transaktions-ID, Bruttobetrag, Währung, bestätigter Status |
| `payment_events` | `payment_event_id`, FK `payment_id` | Provider-Ereignis, verifizierte Signatur/Status, Idempotenzschlüssel |
| `generation_jobs` | `job_id`, FK `order_id` | Engine/Workflow-Version, Prompt-Revision, drei Varianten, Start/Ende/Fehler |
| `artifacts` | `artifact_id`, FK `order_id`, `job_id` | Dateipfad, Content-Hash, Master-Verknüpfung, Inhaltstyp, unveränderlicher Status |
| `approval_decisions` | `approval_id`, FK `order_id`, `artifact_id` | Betreiberentscheidung, Hashbindung, Zeit, Revision/Ablehnung |
| `deliveries` | `delivery_id`, FK `order_id`, `artifact_id` | Zielplattform, externe Nachrichten-ID, Idempotenz, tatsächlicher Versandstatus |
| `audit_events` | `event_id`, FKs nach Ereignis | Unveränderlicher Audit-Strom für Zahl-, Freigabe-, Status- und Versandübergänge |

### 3.1 Transaktions- und Eindeutigkeitsregeln

- `UNIQUE(platform, bot_account_id, external_user_id)`: derselbe Telegram-Kunde wird nie versehentlich doppelt erzeugt.
- `UNIQUE(customer_number)`, Nummernvergabe in einer Schreibtransaktion; kundenspezifischer Ordner wird nach Commit idempotent angelegt.
- `UNIQUE(provider, provider_transaction_id)` und `UNIQUE(provider, provider_event_id)` (wo vorhanden).
- `UNIQUE(delivery_idempotency_key)` plus eindeutige Freigabe/Medienversion.
- Ein Kunde kann viele Konversationen, Bestellungen, Zahlungen, Dateien und Lieferungen haben.
- Ein Order kann mehrere Generationen/Überarbeitungen und mehrere Kandidaten haben, aber nur **einen konkret autorisierten Auslieferungseintrag pro gekaufter Einheit**; Mehrfachkauf erfordert getrennte Einheiten.
- Jeder `artifact` verweist auf einen `master_artifact_id` oder ist selbst das Master; Varianten überschreiben nie das Original.
- Chat-Dubletten anhand Telegram-Ereignis-ID pro Kanal/Bot unterdrücken.
- Änderungen an `approved`-Dateien erzeugen neue Artefakte und **widerrufen** die alte Versandfreigabe; Änderungen dürfen nicht einfach am gleichen Pfad erfolgen.

## 4. Kundenerzeugung und Nachrichtenfluss

**Erste Nachricht eines neuen Nutzers:**

1. Telegram-Update durch Adapter empfangen, Herkunft validieren.
2. Telegram-User-ID und Bot-Konto ermitteln; DM/Chat-ID als Konversationskontext mitführen.
3. SQLite: Konto anhand `(telegram, bot_account_id, user_id)` suchen.
4. Falls nicht vorhanden: neuen `customer_id` und fortlaufende `customer_number = DF-C-000001` atomar erzeugen; Kanalzuordnung speichern.
5. Kundendaten-Ordner nach DB-Commit idempotent anlegen; nach Crash fehlende Struktur aus Datenbank rekonstruieren.
6. Nachricht deduplizieren, transaktional ablegen und an Conversation-/Intent-Service übergeben.
7. LLM liest **nur relevante** Chat-Historie und strukturierte Persona-/Job-Daten; kein direkter Dateisystem- oder Datenbank-Schreibzugriff.

**Weitere Nachrichten:** gleiche `customer_id`, gleiche laufende Konversation oder neue Konversation je Lifecycle; Chat und Bestellungen bleiben historisch zugeordnet.

## 5. Auftrags- und Produktionskette

~~~text
Telegram-Nachricht
  -> Kunden-ID / Chat-Speicherung
  -> Intent-Extraktion aus mehreren Chatnachrichten
  -> Sales-Schwelle (standardmäßig drei qualifizierte Medienanfragen)
  -> eindeutiges Angebot (Bild oder Video, Umfang, Preis)
  -> Anbieterbestätigte Zahlung für genau diese Bestellung
  -> LLM: typisierte Auftragsdetails und Prompt
  -> Engine-Routing:
       image -> MASTER -> Mask/SDXL Edit (optional) -> Refine -> 3 Kandidaten
       video -> Bildreferenz -> Wan/LTX I2V -> Temporal -> 3 Kandidaten
  -> PRIVATE Betreiber-Vorschau per Telegram/Operator-UI
  -> Betreiberfreigabe auf exakt einen Artefakt-Hash
  -> erneute unabhängige Prüfung payment_confirmed + operator_approved
  -> Telegram-Versand an genau den gespeicherten Kunden
  -> Datenbankzustellung, Log und Audit
~~~

**Nichts außerhalb des Delivery-Service** darf Kundenmedien versenden. **Nichts außerhalb des Payment-Service** darf Zahlungen als bestätigt markieren. **Kein LLM-Text** ist eine Freigabe.

## 6. Zahlungsdaten

- **Provider-Adapter** statt PayPal-Hardcoding. Für digitale Inhalte direkt im Telegram-Bot ist Telegram Stars (`XTR`) der dokumentierte Zahlungsweg: https://core.telegram.org/bots/payments-stars .
- Die Nutzung für Erwachsenen-Inhalte muss anhand Anbieter- und Plattformregeln **vor LIVE** gesondert freigegeben werden.
- `PRE_CHECKOUT_QUERY` ist **keine** endgültige Zahlung. Nur ein verifiziertes finales `successful_payment`-Ereignis bzw. autoritativer Provider-Status bestätigt Zahlung; Wiederholung und falsche Bestellungen sind getrennt zu behandeln.
- Zahlungsdaten speichern nur Anbieter-ID, Betrag, Währung, Bestellreferenz, Zustand und Nachweis; keine kompletten Zahlungsmitteldaten.
- `payment_pending`, `payment_confirmed`, `refunded`, `disputed`, `failed` müssen explizit sein.
- Nicht lieferbarer Auftrag nach Zahlung führt kontrolliert zu Revision oder Erstattung, niemals zu stillschweigender Markierung als geliefert.

## 7. Betreiberfreigabe per Handy

Privater Betreiberkanal, explizit authentifizierte Betreiber-Telegram-User-ID, kein öffentlich teilbarer Freigabelink ohne gesonderte Authentisierung.

Jede Karte zeigt mindestens:
`customer_number`, `order_id`, bestellter Typ, verständliche Kurzbeschreibung, Zahlung verifiziert (ja/nein), die drei Vorschaumedien, Modell-/Workflow-ID, Laufzeit und Aktionen: **Freigeben**, **Neu erzeugen**, **Ablehnen**.

**Freigabe-Operation:**
1. Operator-ID prüfen.
2. Die konkret ausgewählte Variante und ihren aktuellen Content-Hash prüfen.
3. Auftrags-/Zahlstatus und eventuelle Stornos erneut aus DB abfragen.
4. Entscheidung unveränderlich speichern.
5. Versandauftrag anlegen; Versanddienst prüft alle Bedingungen erneut.
6. Nur die ausgewählte Variante exakt an die ursprünglich gespeicherte Telegram-Kundenkennung zustellen.

## 8. Datenhaltung und Schutz

- `local/` vollständig `.gitignore`-geschützt, keine versehentlichen Symlinks zurück in Git.
- Geheimnisse: macOS-Keychain bzw. 0700-geschützter lokaler Secret-Store; niemals Datenbank-Export mit Tokens.
- Datenbank-WAL mit konsistenten Backups (nicht unkoordiniertes Kopieren der offenen DB).
- Retention für Chattexte, Originale, Zwischenframes, Kundenvorschauen und Zahlungsnachweise gesondert konfigurierbar; Löschungsanfragen berücksichtigbar, gesetzliche Aufbewahrungspflichten separat.
- Nach Möglichkeit Vollverschlüsselung des Datenträgers/FileVault und beschränkte Dateirechte.
- Logs referenzieren nur IDs und technische Zustände, keine vollständigen privaten Chats/Bilder.
- Kundennummern und externe Identitäten getrennt speichern. Exporte und Löschung müssen konsistent zur SQLite-Datenbank erfolgen.

## 9. Reproduzierbare Abnahmefälle

1. Neue Telegram-ID -> Kunde `DF-C-000001`; Wiederholung -> dieselbe Kundennummer.
2. Gleichzeitige Erstnachrichten -> keine doppelte Kundennummer.
3. Username geändert -> Kundenzuordnung unverändert.
4. Drei qualifizierte Medienwünsche -> genau ein Angebot; Smalltalk und Update-Wiederholung zählen nicht.
5. Unbezahlte Bestellung -> keine ComfyUI-Kundengenerierung, keine Lieferung.
6. Falsche/fremde/duplizierte `successful_payment`-Events -> keine falsche Zuordnung.
7. Bildauftrag -> ausschließlich Image-Engine; Videoauftrag -> ausschließlich Video-Engine.
8. Drei Kandidaten -> exakt kundenspezifischer Operator-Review.
9. Freigabe ohne bestätigte Zahlung -> null Lieferungen.
10. Zahlung ohne Freigabe -> null Lieferungen.
11. Änderung des genehmigten Medienhashs -> null Lieferungen.
12. Falsche Kunden-ID bei Versand -> blockiert.
13. Bot-Restart zwischen Generierung/Zahlung/Freigabe/Versand -> keine unautorisierte und keine doppelte Zustellung.
14. Backups/Restore und reproduzierbarer Kundendatenexport funktionieren.
15. Chat-Verlauf und ausgelieferte Medien sind jeweils eindeutig über Kunden- und Auftragsnummer abrufbar.

## 10. Implementierungsreihenfolge

- **P00–P01:** Umgebung feststellen, ComfyUI-Launcher und Status.
- **P02–P03:** registrierte Bild-/Videoworkspaces und Engine-Tests.
- **P04:** Chat-Intents und typisierte Medienaufträge.
- **P05:** Telegram-DM, atomare Kundenerzeugung, Chat-Speicherung, Angebotslogik.
- **P06:** Zahlungsverifizierung, Betreiber-Vorschau, Zwei-Gate-Versand.
- **P07–P08:** Recovery, Migration, Sicherheit, Last-/Fehlertests, Produktivabnahme.

**Nicht als erledigt markieren:** Die Verzeichnisdefinition ist ein Entwicklungsvertrag. Der echte Kundenstamm, die SQLite-Datei, die Telegram-Anbindung und die Zahlung sind damit noch nicht implementiert.
