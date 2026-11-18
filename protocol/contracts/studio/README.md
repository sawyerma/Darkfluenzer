# DarkStudio – verbindlicher Protobuf-Routing- und Feldvertrag (18.11.2026)

## Verbindliche NO-LEGACY-Bereinigung (18.11.2026) – Vorrang vor historischen Bruttozahlen

**Einzige verbindliche Routing-Matrix:** [Studio_Protobuf_Routing_Vollstaendig.csv](Studio_Protobuf_Routing_Vollstaendig.csv). **106 ursprünglich vorgesehene Einträge** wurden einzeln mit `NEU_BEI_PAKETBEDARF`, `BESTAND_ERWEITERN` oder `ENTFAELLT_NICHT_IMPLEMENTIEREN` entschieden. **16 entfallen als Duplikate**, sodass höchstens **90 Einträge** umgesetzt werden, davon einige nur als Adapter/Erweiterung bereits existierender Fachfunktionen. **Nicht alle 90 müssen umgesetzt werden:** jede Einheit entsteht erst mit benanntem Aufrufer und echtem Paket.

| Klasse | Ursprünglich | Entfallen | Maximal vorgesehen |
|---|---:|---:|---:|
| COMMAND | 59 | 7 | 52 |
| STATE | 9 | 3 | 6 |
| EVENT | 14 | 3 | 11 |
| READ | 24 | 3 | 21 |
| **Gesamt** | **106** | **16** | **90** |

**Verworfene Solltags:** COMMAND 120–122 (Bestands-Charaktere/Training), 128–130 (Bestands-Registry), 154 (Bestandsqueue); STATE 44 (Queue), 47 (Ressourcen), 48 (Charaktere); EVENT 62 (Assets), 67 (Charaktere), 70 (Handoff); READ 3 (Medienliste), 5 (Trainingsliste), 19 (Media-Metadaten). Diese wurden **noch nie** in `commands.proto`/`stream.proto` publiziert, daher gibt es aktuell keinen Wire-Entzug. Für künftige Studio-Schemas sind sie als zurückgezogene Vorschlagsnummern im Vertragsregister sichtbar und **dürfen ohne neue Freigabe nicht für andere Zwecke wiederverwendet** werden. Existierende alte Wire-Felder bleiben als Proto-v1-Kompatibilitätsdaten protokollseitig stabil, ihre **Handler/Alt-Dispatcher** werden nach Cutover entfernt.

**Wichtige Korrektur zu bestehenden Befehlen 60/62:** Im geprüften `commands.proto` gibt es **keine** Befehle 60 oder 62. Deshalb bleiben die Studio-UI-Aktionen **132 (Secret setzen), 133 (Secret löschen), 135 (Provider-Verbindung testen)** bei tatsächlichem Bedarf als *neue typisierte Zugänge zum bestehenden einzigen* `keychain.py`-/Settings-Dienst vorgesehen. **Kein zweiter Secret-Store, keine zweite Providerverwaltung.** Es gibt nur ein gemeinsames Settings-Katalogsystem. COMMAND 108 bindet, falls benötigt, die **bestehende** `media.pipeline.store_input`-/Uploadlogik an; kein weiterer Datei-/Asset-Store.

**Vorrang:** Gültige Sicherheits-/Kundenregeln und Backend §13.16 → diese **bereinigte Matrix** → Feldkatalog (nur Schema-Kandidaten, nicht alles implementieren) → historische [README_STUDIO_PROTOBUF.md](README_STUDIO_PROTOBUF.md) und [Studio_Protobuf_Routing.csv](Studio_Protobuf_Routing.csv) als Quellenarchiv. Es gibt **keine zweite verbindliche Routing-Tabelle**. `NEU_BEI_PAKETBEDARF` ist keine sofortige Implementierungsfreigabe; im Paket sind Schema, Handler, Protobuf-Read/State/Event, SQLite-Migration falls nötig, GUI-Aufrufer und Test gemeinsam nachzuweisen.

**Cutoverregel:** DS2/DS3-a/b/c und DS8 sind **eine zusammenhängende Migration mit Zwischencommits**. Bis zum DS8-Umschaltmoment bleibt *nur der alte Weg produktiv*, die neue Engine läuft ausschließlich isoliert zur Paritätsprüfung. Danach ist *nur die neue Flow-Maschine produktiv*, die alten Renderdispatcher, altes `autoprod` und Cloner-Renderpfade werden im **selben Gesamt-Cutover** gelöscht, inklusive alter GUI-Einstiege und Tests. Kein paralleler Live-Doppelbetrieb und keine dauerhaften Legacy-Adapter. Bestandstabellen dürfen historisch weiter lesbar bleiben; doppelte aktive Tabellen/Queues sind verboten.



**Geltung:** Dieser Ordner ist die **versionierte Protokoll-Sollvorgabe** zu Backend-Phasenplan §13 und Frontend-Phasenplan §6. Er ist **kein dritter Phasenplan** und implementiert keine UI-/Backend-Handler. Die Feld- und Tagzuordnung wird mit diesem Commit für DS0–DS10 festgelegt; Änderungen benötigen explizite Protokollmigration und Regression.

## Verbindliche Dateien und Quelle

| Datei | Rolle |
|---|---|
| [Studio_Protobuf_Routing.csv](Studio_Protobuf_Routing.csv) | Hochgeladene Reservierung: **historische Vorschlagsmatrix 59 COMMAND, 9 STATE, 14 EVENT; nur der Status der bereinigten Routing-Volltabelle entscheidet** |
| [Studio_Protobuf_Routing_Vollstaendig.csv](Studio_Protobuf_Routing_Vollstaendig.csv) | **106 ursprünglich spezifizierte Routen mit verbindlichem Status je Zeile**: 16 entfallen, höchstens 90 bleiben vorgesehen |
| [Studio_Protobuf_Alle_Felder.md](Studio_Protobuf_Alle_Felder.md) | Hochgeladener Typ-/Feldkatalog: **195 Nachrichten, 1.781 Felder** mit Proto-Tags |
| [Studio_Protobuf_Feldkatalog.csv](Studio_Protobuf_Feldkatalog.csv) | Aus der Markdown-Feldliste deterministisch abgeleitete maschinenlesbare Feldmatrix |
| [README_STUDIO_PROTOBUF.md](README_STUDIO_PROTOBUF.md) | Hochgelieferte fachliche Transport-/DS-Spezifikation und GUI-Feldzuordnung |
| **README.md (diese Datei)** | **Verbindliche Normierung**, Status, Konfliktauflösung, Abnahme |

**Gesicherter Ist-Stand bei Eintragung:** `commands.proto` belegt Tags nur bis **68** und `stream.proto` Topics nur bis **32**. Gegen den geprüften Git-Stand `786e53c` gibt es **keine Tagkollision** im reservierten Studio-Bereich. Vor Codegen/Änderung stets den dann aktuellen `main` erneut prüfen. Das ist **eine Dokumentations-/Reservierungsprüfung**, kein Compiler- oder Mac-PASS.

## Routing: wer schreibt, antwortet und liest?

~~~mermaid
flowchart LR
  GUI["React Darkfluenzer: Studio / Kunde / Default"] -->|"CommandRequest.oneof: 100..158"| CMD["POST /api/v1/command"]
  CMD -->|"CommandResponse: ACCEPTED ≠ fertig"| QUEUE["Persistierter Command- / Production-Run"]
  QUEUE --> SERVICE["ProductionClient → ProductionService"]
  SERVICE --> EXE["Flow-Executor → ComfyUI / Blender / Provider"]
  SERVICE -->|"terminal"| RECEIPT["EVENT 29: CommandReceipt"]
  SERVICE -->|"persistierter Zustand"| STATE["STATE 40..48"]
  SERVICE -->|"fachliche Änderung"| EVENT["EVENT 60..73"]
  STATE --> GUI
  EVENT --> GUI
  RECEIPT --> GUI
  GUI -->|"StudioReadRequest: 24 Query-Varianten"| READ["POST /api/v1/studio/read: vorgesehen"]
  READ -->|"StudioReadResponse: paginierte Details"| GUI
  SERVICE -->|"nur verifizierter Export"| COORD["Koordinator/Handoff → Kunden-Gate"]
  COORD --> DISPATCH["Nur Kundenmodul: Zustellung"]
~~~

**Transportpflicht:** Mutation **nur** bestehender `CommandRequest` mit UUID `request_id` und CAS/erwarteter Revision; identische `request_id` + identischer Inhalt = idempotent, abweichender Inhalt = Fehler. `ACCEPTED` ist keine abgeschlossene Produktion. Terminaler `CommandReceipt` auf Topic 29, anschließend versionskonsistentes STATE/EVENT; Reconnect mit Cursor-/Gap-Abgleich. **Keine direkten Frontend-Aufrufe an ComfyUI, Cloud-Provider, SQL oder Media-Pfade.**

**Read-Route (neu festgelegte SOLL-Schnittstelle):** `POST /api/v1/studio/read` mit `application/x-protobuf`, Body `StudioReadRequest`, Antwort `StudioReadResponse`, dieselbe Sitzung/CSRF-/Autorisierungsprüfung wie COMMAND. Serverseitig **genau eine** der 24 Leseoperationen verlangen. Nur bei Navigation/Detailöffnung/Filter/Revisionswechsel/Reconnect lesen, **kein Polling**, vollständige große Graphen nie periodisch im WS-STATE. Diese Route ist **noch nicht implementiert**; ihre genaue Route ist hier als verbindliches Integrationsziel festgelegt.

## Priorität und ausdrücklich zu lösende Konflikte

1. **Regel 4 / F06:** Ersatz einer realen Person in fremdem Bild/Video **nicht** zulässig. `F06` bedeutet Masken-/Figurersatz **nur auf eigenem synthetischen Material**; fremde Quellen liefern ausschließlich Pose/Bewegung/Komposition für **neu erzeugte** synthetische Ausgaben. `StudioShotActor.use_source_identity` und `StudioActorRig.transfer_source_appearance` dürfen diese Regel nicht umgehen.
2. **Regel 3 / Video:** Für Videos mit eigener Figur ist ein qualifiziertes Charakter-/Startbildtor erforderlich. Figurenlose Film-/Werberezepte erhalten eigene qualifizierte Kontroll- und Prüftore.
3. **Regel 6 / E33:** Cloud-Adapternamen, `allow_cloud`, `external_providers_master_enabled` oder `allow_customer_text_transfer` in einem DTO sind **keine Freigabe**. Externe Generierung bis zu dokumentierter Betreiberfreigabe deaktivieren. **Kundendialog, personenbezogene Kundendaten, Kundenreferenzen und kundenbezogene Briefs bleiben immer LOCAL_ONLY**; `customer_conversation_external_enabled` ist kein aktivierbarer Bypass.
4. **Liefer-Gate:** Studio hat **keinen Kunden-Senden-Command**. Koordinator schreibt `production_handoffs` ausschließlich über Kunden-Repository. Beide SQLite-Trigger prüfen `ready`, SHA, Revision, aktuelle Freigabe und Zahlung bzw. **alle fünf SPEC-008-Testbedingungen**; zusätzlich aktuelle Studio-Berechtigung und Bytes-Hash unmittelbar vor Dispatch. Widerruf wirkt auch nach vorheriger Freigabe.
5. **Geheimnisse:** `StudioProviderSecretReplace.secret_utf8` ist strikt **write-only**; Backend muss Raw-Payload **vor Command-Journal, Tracing, Receipt, Logs, Snapshot und Crash-Berichten** ausnehmen. Speicherung ausschließlich im Schlüsselbund, niemals in SQLite/STATE/EVENT/CommandAudit. Vor echter Integration gesonderter Secret-Roundtrip-/Leak-Test.
6. **Typvalidierung:** Proto3 ist keine fachliche Validierung. `StudioValue` trägt acht mögliche Werte ohne im gelieferten Feldverzeichnis sichtbares `oneof`; eine eindeutige Variante muss beim späteren .proto-Entwurf erhalten/gesichert und serverseitig validiert werden. `StudioReadRequest` muss genau eine Query enthalten. Eine deklarierte Nodefähigkeit/Control-Kombination ist noch kein Mac-Eignungsnachweis. Hochfrequente `StudioCameraSensorSample`-Daten bleiben beim Adapter, nicht in STATE.
7. **Betrieb:** Alle Source-Felder/Tagnamen der drei Uploads bleiben erhalten. Bei Konflikt gehen die gültigen Produktregeln und Backend/Frontend-Phasenpläne vor; **dieser Index präzisiert die technische Integration**, ohne Kunden-, Schutz- oder Zahlungsregeln aufzuheben.

## Noch fehlende ausführbare Proto-Quellen – ausdrücklich offen

Es wurden **drei Upload-Dateien** bereitgestellt, nicht die sechs ausführbaren `studio_*.proto`, nicht `apply_studio_proto.py`, `studio_descriptor.pb` oder der in der Ursprungsspezifikation erwähnte **Enumkatalog**. Die Feldliste verweist auf **21 bislang nur namentlich belegte Studio-Enumtypen** (`StudioApprovalPolicy`, `StudioBlockingMode`, `StudioCameraControl`, `StudioCapabilityStatus`, `StudioEvidence`, `StudioGuideTransfer`, `StudioMediaKind`, `StudioModelRole`, `StudioNodePortKind`, `StudioProductionOperation`, `StudioProviderKind`, `StudioProviderPolicy`, `StudioReferenceRole`, `StudioResourceClass`, `StudioReviewVerdict`, `StudioRunStatus`, `StudioSoundTrackKind`, `StudioSource`, `StudioStage`, `StudioStepStatus`, `StudioTaskKind`); **ihre numerischen Enumwerte dürfen nicht geraten werden**. Die Aussage der gelieferten README über einen früheren Protoc-Lauf ist **kein unabhängig nachprüfbarer Buildnachweis dieser Git-Eintragung**.

**DS0-Pflicht:** Original-`*.proto` und tatsächlich belegte Tags prüfen, vollständige Enum-/oneof-Definitionen beschaffen bzw. vor Compilerintegration eindeutig spezifizieren, additive Kompatibilität `commands.proto`/`stream.proto`/`order.proto`/`media.proto`/`influencer.proto` nachweisen, `buf lint`, `buf generate`, Python/TypeScript-Roundtrips und Schema-ID-/Welcome-Handshake prüfen. Erst danach werden COMMAND-Handler/STATE/EVENT/READ je DS-Paket implementiert. **Keine 59 Fake-Handler und kein Status PASS aus einem Dokumentations-Commit.**

**DS-Reihenfolge:** DS0 Inventar/Schema, DS1 Aufgaben/Rezepte, DS2/3 Flow/Run/Gate, DS8 Umschaltung Kloner/Kunde/Studio, DS4 Referenzen/LoRA, DS5 Regie/Provider, DS6 Film/Audio, DS6b-1 Blocking, DS6b-2 nur nach M4-Qualifikation, DS7 Editor, DS9 Optionale, DS10 Lang-/Qualifikationstests. Bestehende Schema-Tags nie still umwidmen.
