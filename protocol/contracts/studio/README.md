# DarkStudio – verbindlicher Protobuf-Routing- und Feldvertrag (18.11.2026)

> **Korrektur durch Audit III:** Backend §13.18 und Frontend §6.13 haben Vorrang vor den älteren Darstellungen dieser Datei. Die zweite README ist nicht normativ.

## Feldkatalog-Prüfung II – **verbindliche bereinigte Felder** (18.11.2026)

**Normativ:** [Studio_Protobuf_Feldkatalog.csv](Studio_Protobuf_Feldkatalog.csv) enthält für **alle ursprünglichen 1.781 Zeilen** die neuen Spalten `Vertragsstatus`, `Zieltyp_oder_Name`, `Grund_und_Eigentuemer` sowie **53 neue, ausdrücklich nur geplante Feldzeilen**. **[Studio_Protobuf_Routing_Vollstaendig.csv](Studio_Protobuf_Routing_Vollstaendig.csv)** enthält die nach Entdoppelung verbliebenen Vorschlagsrouten plus sieben bedarfsgebundene Ergänzungen. **Die ursprüngliche Markdown-Feldliste und [README_STUDIO_PROTOBUF.md](README_STUDIO_PROTOBUF.md) sind ab jetzt ausschließlich historische Quellen**; der ungefilterte alte Typbaum darf nicht automatisch in ausführbare Proto-Dateien umgewandelt werden.

### I. Verifizierte Duplikate / keine zweite Wahrheit

- STATE **44/47/48** wurden bereits in der vorherigen Bereinigung verworfen. Stattdessen bestehende `TOPIC_JOBS_ACTIVE=2`, `TOPIC_RESOURCES=7`, `TOPIC_COMFY_INSTANCES=6`, `TOPIC_CHARACTERS=5` **additiv erweitern**. `StudioStoryboardsState.recent` ist eine **kleine `StudioStoryboardSummary`**, kein eingebettetes vollständiges Storyboard. Bei sehr vielen Einträgen bounded/paginiert.
- `StudioModelCatalog` und `StudioCatalog` **als separate Typen entfallen**. Fähigkeiten und Modellauswahl sind **Projektionen einer** vorhandenen Workflow-/Modellregistry (`TOPIC_COMFY_WORKFLOWS=3`), ohne zweite Registrierungs-/Qualifikationsdatenbank. `StudioModelCapability` entfällt als separate parallele Protobuf-Nachricht; bestehendes `WorkflowInfo/WorkflowParam` wird bei Bedarf um Capabilities ergänzt. Vier produktive Gates, `usage=production` und reale Messwerte bleiben bindend; niemals `studio_model_set_qualification=130`.
- `StudioAssetRef.asset_id` und `existing_reference_id` **entfallen**; die Dateireferenz heißt allein `media_id:uint64`, die schon vorhandene Medien-ID. `StudioReference.reference_binding_id` ist nur eine **Bindungsrelation** mit Rolle auf eine Medien-ID, kein zweiter Dateischlüssel. Medien und Upload bleiben im einen vorhandenen Speicher.
- `StudioApprovalRecord` entfällt als zweites Betreiber-Freigabesystem; interne Studio-`Review`-Messung ist **keine** Lieferfreigabe. Kundenmodule besitzen Zahlung, Freigabe und Handoff samt Gate/Trigger; Produkt entscheidet `customer_enabled`, niemals Task/Flow/FlowSummary. `StudioPromptTemplate` ist nur eine **neue Rollen-Sicht auf den einen vorhandenen E19-Promptprofil- und Versionsmechanismus**, keine zweite Promptdatenbank.

### II. Client-Vertrauen / Security-Grenzen – Pflicht bei DS0/DS2/3

- `CommandRequest.oneof.studio_production_submit = 105` trägt künftig **`StudioProductionIntent`** (ausschließlich Aufgabe, Rezeptreferenz/-revision, eigenes Projekt, eigene Figur, freigegebene Medienreferenzen, strukturierte Eingabe und Ausgabeprofil). `StudioProductionRequest` bleibt **serverinternes**, aus Auth-Session/Order/Product/E33 zusammengesetztes DTO. Client darf weder `source`, `external_order_id`, `test_order`, `operator_id`, `priority`, `content_tier` noch `expected_order_revision` oder Service-Budget-/Zahlungsstatus festlegen. Das Backend validiert jede Referenz, Entitlement, Revision und Nachricht.
- **Ein zentraler Import-Owner:** Das veröffentlichte `InputFile.data` im authentifizierten und größenbegrenzten Command bleibt zulässig. Neues `StudioAssetImport.inline_bytes` als zweiter Byteweg und `staged_upload_id` ohne implementierte Staging-Route entfallen; Typ, SHA, Herkunft, Inhaltstier und Berechtigung prüft derselbe Media-Owner. `StudioAssetImport.content_tier` und `allowed_for_external_provider` entfallen als Browser-Autorisierung. Inhaltsstufe bestimmt die geprüfte Quelle/Workflow und bestehende Regel 13: unbekannt wird **wie explizit behandelt**, nie vom Client heruntergestuft.
- `StudioCreativeBrief.original_wish` und `questions_to_customer` entfallen, Kundentext und Antworten bleiben im **customers**-Modul; das Studio sieht nur ein datensparsames, typisiertes, nicht-identifizierendes Produktionsbriefing und ausschließlich lokale KI. In `StudioShotActor.use_source_identity`, `StudioActorRig.transfer_source_appearance` und **`StudioBlockingSettingsUpdate.transfer_source_appearance`** entfallen alle drei Quell-Identitäts-/Appearance-Übernahmen; Referenzvideos liefern nur Bewegung, Pose, Kamera und Komposition.
- **Kein Cloud-/Engine-Fallback**: `allow_fallback`, `fallback_enabled`, `fallback_model_ids` und über den Client steuerbare `allow_cloud`-Felder entfallen; externe Anbieter standardmäßig AUS bis ausdrückliche E33-Entscheidung. Kein `allow_customer_text_transfer`. Ein Netzwerk-`timeout_ms` zum Erkennen einer Provider-Verbindungsstörung ist **nicht** mit dem verbotenen Abbruch eines laufenden ComfyUI-Renders gleichzusetzen: `StudioNodeDefinition.timeout_ms`, `StudioNodeRun.timeout_ms` und `StudioFlowDefinition.max_runtime_ms` entfallen als Renderabbruch. Crash-/Reconnect-Reconciliation bleibt Pflicht.
- `StudioShot.image_model`, `video_model` und `lora` entfallen als freie per-Shot-Wahl; nur kompatibles qualifiziertes Rezept/Character-Version. `StudioNodeDefinition.model`/`lora` nur aus Registry-/Rezeptrevision ableiten. Es gibt keine manuelle PASS-Schaltfläche; Qualifikation nur mit gespeicherten realen Prüfläufen.

### III. Echte Lücken im Routing – **nur bei Paketbedarf** hinzufügen

| Paket | Aktion / Nummer | Antwort / Zweck |
|---|---|---|
| DS4 | COMMAND **159** `studio_pose_track_upsert`, READ **25** `get_pose_track` | Eigene Pose/Skelett-Keyframes versioniert bearbeiten **und** wieder lesen |
| DS5 | COMMAND **160** `studio_scene_remove` | Szene revisionsgesichert entfernen, nicht nur Shot |
| DS1 | READ **26** `list_recipes` | Inaktive und aktive Rezepte aus **derselben** Registry |
| DS5 | READ **27** `list_prompt_templates` | Auf E19-Promptprofilverwaltung aufsetzen |
| DS6b | READ **28** `list_shot_presets` | Gespeicherte Kamerapresets anzeigen |
| DS9 | READ **29** `list_audio_presets` | Audio-Presets nur wenn tatsächlich implementiert |

`StudioProductionControl` bekommt die geplanten Felder **5 `node_run_id`**, **6 `verdict`**, **7 `selected_media_id`**. Die Entscheidung erfolgt autorisiert und mit erwarteter Revision, nie anhand ungeprüften UI-Zustands. **Neue Nummern 159/160 sowie READ 25–29 sind SOLL** und gegen das dann aktuelle Hauptschema vor tatsächlichem Proto-Commit erneut auf Kollisionen zu prüfen.

### IV. Feldtypen und sparsame Übertragung

- Alle `content_tier`-Felder sind als **`StudioContentTier`-Enum** zu definieren; `UNSPECIFIED=0` führt **fail-closed** zur Einstufung wie `EXPLICIT`, niemals freie Client-Strings. Eine verbindliche Zahlenvergabe für weitere Enumwerte erfolgt nur in echten `.proto` in DS0, ohne vorgetäuschte Compiler-/Wire-Kompatibilität. Handoff-`status` liegt **allein im Kundenmodul** als typisierter `READY/REVOKED`-Zustand und wird nicht als `StudioHandoff` dupliziert.
- `StudioTrainingRun.started_unix_ms/updated_unix_ms` und `StudioNodeRun.remote_status_checked_unix_ms` werden `int64`, `origin_template_revision` wird `uint64`, `StudioProductionRequest.stage_policy` wird `repeated StudioStageGate stage_gates`. Die angegebene Feldnummer wird beibehalten, **solange die Vorschlags-Protos noch nie veröffentlicht wurden**; später nur mit expliziter Migration. `StudioReadRequest` und `StudioValue` bekommen jeweils **genau ein `oneof`**.
- `StudioProduction.nodes` und eingebettete kreative Port-Objekte `StudioNodePortValue.brief/script/storyboard/scene/shot/scene_spec/guide` entfallen. Stattdessen **Objekt-ID, Revision und Hash** im Node-Output; `get_node_run` und passende autorisierte READs liefern Bounded Details. `StudioCameraExternalInput.samples` entfällt aus SceneSpec/STATE; hochfrequente Sensorwerte werden nur vom qualifizierten Capture-Adapter erfasst/als revisionsgebundener Track gespeichert. Das bestehende EVENT-/STATE-System bleibt, ohne periodische große Snapshots.
- **Acht ursprünglich nicht unmittelbar referenzierte Nachrichten** (`StudioCatalog`, `StudioSubtitleCue`, `StudioRational`, `StudioGuideMatch`, `StudioApprovalRecord`, `StudioHandoff`, `StudioProductionReceipt`, `StudioPoseTrack`): **sieben entfallen** als ungenutzte oder parallele Entwürfe, `StudioPoseTrack` erhält die neuen echten Pose-READ/COMMAND-Routen. Die übrigen nicht referenzierten, bereits per Routing als Duplikat gestrichenen Typen erhalten ebenfalls **`ENTFAELLT_GANZE_NACHRICHT`**.

**Mindesttest für DS0-Proto-Abnahme:** generierte `.proto`-Dateien verwenden **nur** `NUR_BEI_PAKETBEDARF`, `BESTAND_ERWEITERN`, `NUR_SERVER_ABGELEITET` oder konkret als Korrektur festgelegte Felder, niemals `ENTFAELLT_*`. `oneof`-Kollisionen, Tag-Dubletten, Enum-Defaults, Input-Smuggling (Kundenauftrag/Test/Content/Provider), unzulässige Raw-Bytes, zu große STATE/Node-Objekte, unqualifizierter Modell-PASS, Weitergabe an Cloud, verbotene Appearance-Übernahme, unerlaubte Render-Timeouts und wiederverwendete Original-Tags müssen als negative Tests belegbar fehlschlagen. Dokumenten-SOLL ist **kein Compiler- oder Mac-PASS**.

## Verbindliche NO-LEGACY-Bereinigung (18.11.2026) – Vorrang vor historischen Bruttozahlen

**Einzige verbindliche Routing-Matrix:** [Studio_Protobuf_Routing_Vollstaendig.csv](Studio_Protobuf_Routing_Vollstaendig.csv). **113 dokumentierte Routenzeilen** (**106 ursprüngliche** plus sieben geprüfte Erweiterungen) wurden einzeln mit `NEU_BEI_PAKETBEDARF`, `BESTAND_ERWEITERN` oder `ENTFAELLT_NICHT_IMPLEMENTIEREN` entschieden. **16 entfallen als Duplikate**, sodass höchstens **97 Einträge** verbleiben (84 neu bei Paketbedarf und 13 Bestands-Erweiterungen), davon einige nur als Adapter/Erweiterung bereits existierender Fachfunktionen. **Nicht alle 97 müssen umgesetzt werden:** jede Einheit entsteht erst mit benanntem Aufrufer und echtem Paket.

| Klasse | Ursprünglich | Entfallen | Maximal vorgesehen |
|---|---:|---:|---:|
| COMMAND | 61 | 7 | 54 |
| STATE | 9 | 3 | 6 |
| EVENT | 14 | 3 | 11 |
| READ | 29 | 3 | 26 |
| **Gesamt** | **113** | **16** | **97** |

**Verworfene Solltags:** COMMAND 120–122 (Bestands-Charaktere/Training), 128–130 (Bestands-Registry), 154 (Bestandsqueue); STATE 44 (Queue), 47 (Ressourcen), 48 (Charaktere); EVENT 62 (Assets), 67 (Charaktere), 70 (Handoff); READ 3 (Medienliste), 5 (Trainingsliste), 19 (Media-Metadaten). Diese wurden **noch nie** in `commands.proto`/`stream.proto` publiziert, daher gibt es aktuell keinen Wire-Entzug. Für künftige Studio-Schemas sind sie als zurückgezogene Vorschlagsnummern im Vertragsregister sichtbar und **dürfen ohne neue Freigabe nicht für andere Zwecke wiederverwendet** werden. Existierende alte Wire-Felder bleiben als Proto-v1-Kompatibilitätsdaten protokollseitig stabil, ihre **Handler/Alt-Dispatcher** werden nach Cutover entfernt.

**Wichtige Korrektur zu bestehenden Befehlen 60/62:** Im geprüften `commands.proto` gibt es **keine** Befehle 60 oder 62. Deshalb bleiben die Studio-UI-Aktionen **132 (Secret setzen), 133 (Secret löschen), 135 (Provider-Verbindung testen)** bei tatsächlichem Bedarf als *neue typisierte Zugänge zum bestehenden einzigen* `keychain.py`-/Settings-Dienst vorgesehen. **Kein zweiter Secret-Store, keine zweite Providerverwaltung.** Es gibt nur ein gemeinsames Settings-Katalogsystem. COMMAND 108 bindet, falls benötigt, die **bestehende** `media.pipeline.store_input`-/Uploadlogik an; kein weiterer Datei-/Asset-Store.

**Vorrang:** Gültige Sicherheits-/Kundenregeln und Backend §13.16 → diese **bereinigte Matrix** → Feldkatalog (nur Schema-Kandidaten, nicht alles implementieren) → historische [README_STUDIO_PROTOBUF.md](README_STUDIO_PROTOBUF.md) und [Studio_Protobuf_Routing.csv](Studio_Protobuf_Routing.csv) als Quellenarchiv. Es gibt **keine zweite verbindliche Routing-Tabelle**. `NEU_BEI_PAKETBEDARF` ist keine sofortige Implementierungsfreigabe; im Paket sind Schema, Handler, Protobuf-Read/State/Event, SQLite-Migration falls nötig, GUI-Aufrufer und Test gemeinsam nachzuweisen.

**Cutoverregel:** DS2/DS3-a/b/c und DS8 sind **eine zusammenhängende Migration mit Zwischencommits**. Bis zum DS8-Umschaltmoment bleibt *nur der alte Weg produktiv*, die neue Engine läuft ausschließlich isoliert zur Paritätsprüfung. Danach ist *nur die neue Flow-Maschine produktiv*, die alten Renderdispatcher, altes `autoprod` und Cloner-Renderpfade werden im **selben Gesamt-Cutover** gelöscht, inklusive alter GUI-Einstiege und Tests. Kein paralleler Live-Doppelbetrieb und keine dauerhaften Legacy-Adapter. Bestandstabellen dürfen historisch weiter lesbar bleiben; doppelte aktive Tabellen/Queues sind verboten.



**Geltung:** Dieser Ordner ist die **versionierte Protokoll-Sollvorgabe** zu Backend-Phasenplan §13 und Frontend-Phasenplan §6. Er ist **kein dritter Phasenplan** und implementiert keine UI-/Backend-Handler. Die Feld- und Tagzuordnung wird mit diesem Commit für DS0–DS10 festgelegt; Änderungen benötigen explizite Protokollmigration und Regression.

## Verbindliche Dateien und Quelle

| Datei | Rolle |
|---|---|
| [Studio_Protobuf_Routing.csv](Studio_Protobuf_Routing.csv) | Hochgeladene Reservierung: **historische Vorschlagsmatrix 59 COMMAND, 9 STATE, 14 EVENT; nur der Status der bereinigten Routing-Volltabelle entscheidet** |
| [Studio_Protobuf_Routing_Vollstaendig.csv](Studio_Protobuf_Routing_Vollstaendig.csv) | **113 Routingzeilen (106 ursprüngliche + 7 neue) mit verbindlichem Status je Zeile**: 16 entfallen, höchstens 97 bleiben bedarfsgebunden |
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
  GUI -->|"StudioReadRequest: bis 26 bedarfsgebundene Query-Varianten"| READ["POST /api/v1/studio/read: vorgesehen"]
  READ -->|"StudioReadResponse: paginierte Details"| GUI
  SERVICE -->|"nur verifizierter Export"| COORD["Koordinator/Handoff → Kunden-Gate"]
  COORD --> DISPATCH["Nur Kundenmodul: Zustellung"]
~~~

**Transportpflicht:** Mutation **nur** bestehender `CommandRequest` mit UUID `request_id` und CAS/erwarteter Revision; identische `request_id` + identischer Inhalt = idempotent, abweichender Inhalt = Fehler. `ACCEPTED` ist keine abgeschlossene Produktion. Terminaler `CommandReceipt` auf Topic 29, anschließend versionskonsistentes STATE/EVENT; Reconnect mit Cursor-/Gap-Abgleich. **Keine direkten Frontend-Aufrufe an ComfyUI, Cloud-Provider, SQL oder Media-Pfade.**

**Read-Route (neu festgelegte SOLL-Schnittstelle):** `POST /api/v1/studio/read` mit `application/x-protobuf`, Body `StudioReadRequest`, Antwort `StudioReadResponse`, dieselbe Sitzung/CSRF-/Autorisierungsprüfung wie COMMAND. 29 READ-Tags sind dokumentiert, davon 3 gestrichen und maximal 26 bedarfsgebunden; serverseitig **genau eine tatsächlich implementierte** Leseoperation je Anfrage verlangen. Nur bei Navigation/Detailöffnung/Filter/Revisionswechsel/Reconnect lesen, **kein Polling**, vollständige große Graphen nie periodisch im WS-STATE. Diese Route ist **noch nicht implementiert**; ihre genaue Route ist hier als verbindliches Integrationsziel festgelegt.

## Priorität und ausdrücklich zu lösende Konflikte

1. **Regel 4 / F06:** Ersatz einer realen Person in fremdem Bild/Video **nicht** zulässig. `F06` bedeutet Masken-/Figurersatz **nur auf eigenem synthetischen Material**; fremde Quellen liefern ausschließlich Pose/Bewegung/Komposition für **neu erzeugte** synthetische Ausgaben. `StudioShotActor.use_source_identity` und `StudioActorRig.transfer_source_appearance` dürfen diese Regel nicht umgehen.
2. **Regel 3 / Video:** Für Videos mit eigener Figur ist ein qualifiziertes Charakter-/Startbildtor erforderlich. Figurenlose Film-/Werberezepte erhalten eigene qualifizierte Kontroll- und Prüftore.
3. **Regel 6 / E33:** Cloud-Adapternamen, `allow_cloud`, `external_providers_master_enabled` oder `allow_customer_text_transfer` in einem DTO sind **keine Freigabe**. Externe Generierung bis zu dokumentierter Betreiberfreigabe deaktivieren. **Kundendialog, personenbezogene Kundendaten, Kundenreferenzen und kundenbezogene Briefs bleiben immer LOCAL_ONLY**; `customer_conversation_external_enabled` ist kein aktivierbarer Bypass.
4. **Liefer-Gate:** Studio hat **keinen Kunden-Senden-Command**. Koordinator schreibt `production_handoffs` ausschließlich über Kunden-Repository. Beide SQLite-Trigger prüfen `ready`, SHA, Revision, aktuelle Freigabe und Zahlung bzw. **alle fünf SPEC-008-Testbedingungen**; zusätzlich aktuelle Studio-Berechtigung und Bytes-Hash unmittelbar vor Dispatch. Widerruf wirkt auch nach vorheriger Freigabe.
5. **Geheimnisse:** `StudioProviderSecretReplace.secret_utf8` ist strikt **write-only**; Backend muss Raw-Payload **vor Command-Journal, Tracing, Receipt, Logs, Snapshot und Crash-Berichten** ausnehmen. Speicherung ausschließlich im Schlüsselbund, niemals in SQLite/STATE/EVENT/CommandAudit. Vor echter Integration gesonderter Secret-Roundtrip-/Leak-Test.
6. **Typvalidierung:** Proto3 ist keine fachliche Validierung. `StudioValue` trägt acht mögliche Werte ohne im gelieferten Feldverzeichnis sichtbares `oneof`; eine eindeutige Variante muss beim späteren .proto-Entwurf erhalten/gesichert und serverseitig validiert werden. `StudioReadRequest` muss genau eine Query enthalten. Eine deklarierte Nodefähigkeit/Control-Kombination ist noch kein Mac-Eignungsnachweis. Hochfrequente `StudioCameraSensorSample`-Daten bleiben beim Adapter, nicht in STATE.
7. **Betrieb:** Die vorgeschlagenen Herkunftstags bleiben im Feldkatalog dokumentiert, gestrichene Vorschlagsfelder werden nicht generiert; veröffentlichte v1-Wire-Tags dürfen nicht gelöscht werden. Bei Konflikt gehen die gültigen Produktregeln und Backend/Frontend-Phasenpläne vor; **dieser Index präzisiert die technische Integration**, ohne Kunden-, Schutz- oder Zahlungsregeln aufzuheben.

## Audit III – maßgeblicher Bestandsvertrag (18.11.2026)

**Status:** Normativer SOLL-Nachtrag, weder sechs kompilierte Studio-Protos noch Mac-/Handler-PASS. Backend §13.18 konkretisiert die Auftrags- und Cutoverlogik; Frontend §6.13 die einzige GUI. Kein zweiter SecretStore, AssetStore, Executor oder Eventjournal.

1. **Auftragsmodell:** `ActiveOrder` führt heute die drei Quellen gemeinsam. Nach DS8 enthält `customers/orders` nur Kunden-Bestellungen (Angebot, Zahlung, Freigabe, Zustellung) mit `production_id`; Betreiber- und Default-Aufträge sind Studio-Produktionsläufe. Historische `OrderStage`/`StageJob`-Daten bleiben lesbar, neue Altstufen werden nach Cutover nicht mehr geschrieben. TOPIC 4 nur Kunden-Auftrag, TOPIC 41 die tatsächlichen Produktionen.
2. **Vorhandene Protobuf-Typen priorisieren:** `Resources` (7), `JobsActive/ActiveJob` (2), `ComfyInstances` (6), `WorkflowInfo/WorkflowParam` (3), `Character/CharacterLora/TrainingCheckpoint` (5), `MediaItem/MediaKind`, `MediaCheck` sind Fachquellen. `StudioResourceState`, `StudioQueueItem`, `StudioCharacterSheet`, `StudioTrainingRun`, `StudioModelCapability`, `StudioParameterSpec`, `StudioLoraRef`, `StudioQualityCheck` entfallen als separate parallele Bestandsnachrichten; `StudioMediaKind` entfällt zugunsten des vorhandenen `MediaKind`. Echte neue Fachobjekte nur bei Paketbedarf.
3. **Keine Datenreduktion:** `ActiveJob.unknown/stalled_s`, bestehende Klassen `customer/default/cockpit/training`, die vier Engine-Gates und `WorkflowInfo.usage/content` sowie alle `MediaCheck`-Einzelwerte bleiben erhalten. Eine Quelle `operator` wird für Jobpriorität auf `cockpit` abgebildet. `gpu_busy_percent` darf ohne gemessene M4-Quelle nicht generiert oder als UI-Wert vorgetäuscht werden.
4. **Medien ohne Kundenidentität in Studio:** Veröffentlichte `MediaItem`-Tags `caption/order_no/customer_no` bleiben Wire-kompatibel. Studio-Leseweg/STATE gibt nur neutrale Medienreferenz (`media_id`, SHA, neutrale Metadaten) aus; die Kundenansicht ergänzt ihren Kontext ausschließlich über berechtigte Kundenprojektionen.
5. **Alte Befehle nicht reservieren:** Bereits belegte Command-Tags **12, 21, 22, 24 und 38** bleiben samt Payloads erhalten. Erst nach DS8-Cutover wird die alte fachliche Ausführung entfernt/auf den einen `ProductionClient` umgestellt; nie eine zweite Live-Kette. `studio_chat=49` und `studio_session_reset=50` bleiben Melody-KI-Test, nicht Medien-Studio.
6. **Eine CAS-Prüfung:** `CommandRequest.expected_version` (Tag 2) ist der maßgebliche serverseitige Aggregat-CAS. Doppelte geplante `expected_revision`-Felder in Studio-Command-Payloads entfallen. `expected_version=0` nur bei Neuanlage oder nachgewiesen unversionierter Bestandsaktion, nicht als Umgehung einer vorhandenen Studio-Revision. Referenz-/Rezeptrevisionen werden gesondert auf Gültigkeit geprüft, nicht als zweite CAS-Instanz.
7. **Ein Import:** Bereits veröffentlichtes `InputFile.data` darf über die bestehende Session-/CSRF-/Größen-/Typ-/SHA-/Rechte-geprüfte Media-Importlogik laufen. `StudioAssetImport.inline_bytes` und `staged_upload_id` ohne Staging-Endpunkt entfallen. COMMAND 108 darf nur denselben Media-Owner nutzen. Keine zweite `asset_id`, Galerie oder Uploadpipeline.
8. **Nur eine manuelle Kundenfreigabe:** Studio-QC automatisch aus realen Prüfdaten, Rezept verschärft nur Qualitätstore; notwendige Operatorfreigabe beim Kunden einmal über `ApproveArtifact=34` oder den verifizierten Handyweg. `studio_export_review=150` nur Eigenstudio. Handoff/Widerruf, Zahlung/Testausnahme, Inhaltsstufe, Hash und Revision weiterhin vor dem Versand prüfen.
9. **Abnahme:** DS0 inventarisiert Wire-/Feld-/Owner-Status, verifiziert Typgraph, CAS/Upload-/Rechte-Tests; DS8 migriert idempotent alle Quellen und belegt bestehende Historie, keine alten Writes, ein Executor, ein Freigabeklick und echte Kurzläufe. Dokumentation ist kein PASS.

**Korrigierte Zählung:** 113 dokumentierte Routenzeilen (106 ursprünglich + 7 ergänzt), 16 gestrichen, maximal **97 bedarfsgebunden**: 54 COMMAND, 6 STATE, 11 EVENT, 26 READ. Die originale zweite README ist keine gültige konkurrierende Spezifikation.

## Noch fehlende ausführbare Proto-Quellen – ausdrücklich offen

Es wurden **drei Upload-Dateien** bereitgestellt, nicht die sechs ausführbaren `studio_*.proto`, nicht `apply_studio_proto.py`, `studio_descriptor.pb` oder der in der Ursprungsspezifikation erwähnte **Enumkatalog**. Die Feldliste verweist auf **21 bislang nur namentlich belegte Studio-Enumtypen** (`StudioApprovalPolicy`, `StudioBlockingMode`, `StudioCameraControl`, `StudioCapabilityStatus`, `StudioEvidence`, `StudioGuideTransfer`, `StudioMediaKind`, `StudioModelRole`, `StudioNodePortKind`, `StudioProductionOperation`, `StudioProviderKind`, `StudioProviderPolicy`, `StudioReferenceRole`, `StudioResourceClass`, `StudioReviewVerdict`, `StudioRunStatus`, `StudioSoundTrackKind`, `StudioSource`, `StudioStage`, `StudioStepStatus`, `StudioTaskKind`); **ihre numerischen Enumwerte dürfen nicht geraten werden**. Die Aussage der gelieferten README über einen früheren Protoc-Lauf ist **kein unabhängig nachprüfbarer Buildnachweis dieser Git-Eintragung**.

**DS0-Pflicht:** Original-`*.proto` und tatsächlich belegte Tags prüfen, vollständige Enum-/oneof-Definitionen beschaffen bzw. vor Compilerintegration eindeutig spezifizieren, additive Kompatibilität `commands.proto`/`stream.proto`/`order.proto`/`media.proto`/`influencer.proto` nachweisen, `buf lint`, `buf generate`, Python/TypeScript-Roundtrips und Schema-ID-/Welcome-Handshake prüfen. Erst danach werden COMMAND-Handler/STATE/EVENT/READ je DS-Paket implementiert. **Keine 59 Fake-Handler und kein Status PASS aus einem Dokumentations-Commit.**

**DS-Reihenfolge:** DS0 Inventar/Schema, DS1 Aufgaben/Rezepte, DS2/3 Flow/Run/Gate, DS8 Umschaltung Kloner/Kunde/Studio, DS4 Referenzen/LoRA, DS5 Regie/Provider, DS6 Film/Audio, DS6b-1 Blocking, DS6b-2 nur nach M4-Qualifikation, DS7 Editor, DS9 Optionale, DS10 Lang-/Qualifikationstests. Bestehende Schema-Tags nie still umwidmen.
