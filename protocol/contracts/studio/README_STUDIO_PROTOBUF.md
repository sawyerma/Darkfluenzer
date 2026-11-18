# DarkStudio / Darkfluenzer – vollständiger Protobuf-Sollvertrag

**Stand:** 18.11.2026  
**Bezug:** `DarkStudio_Darkfluenzer_MASTERPLAN_3_2_final.md`, Darkfluenzer `main`, bestehende v1-Proto-Schemas, klickbare HTML-Studio-Vorschau.  
**Status:** kompiliertes **SOLL-SCHEMA**, **keine Backend-Implementierung** und **kein Git-Push**. Schema allein ist keine funktionsfähige Produktion.

## 1. Unveränderte Architektur

- **Eine Darkfluenzer-Anwendung**, eine React-GUI, eine SQLite, zwei fachlich getrennte Module. DarkStudio ist als Studio-Reiter eigenständig nutzbar; keine zusätzliche App/DB/HTTP-Polling-Engine.
- Ein `ProductionClient`/`ProductionService` für **Cockpit, Kloner, Kunde**. Kunden-/Sales-/Payment-/Delivery-Tabellen bleiben ausschließlich Darkfluenzer-eigen. Studio kennt nur opake Auftragsreferenzen.
- Bestehend: `POST /api/v1/command` → `CommandRequest`/`CommandResponse` → persistierter `CommandReceipt` via `TOPIC_COMMAND_RECEIPT=29`; `GET`-Pages und `WS /ws/v1/stream` mit `STATE` und `EVENT`.
- **Kein JSON** als Studio-/Frontend-Transport. Keine frei interpretierbaren Textaktionen, Roh-SQL, frei ausführbaren Blender-Python-Code oder ungeprüfte Assetpfade im Modelloutput.
- Datei-Bytes über sicheren bestehenden Upload-/Media-Weg; der Studio-Vertrag überträgt **Asset-ID + Hash + Metadaten**. Für kleine Daten gibt es `StudioAssetImport.inline_bytes` mit zwingendem Backend-Größenlimit. Live-Sensordaten werden über einen registrierten Kameraadapter erfasst; nicht durch große WebSocket-STATE-Snapshots transportiert.

## 2. Neue Proto-Dateien (genau sechs)

| Datei | Fachumfang |
|---|---|
| `studio_common.proto` | Enums, Typen, Zeit, Formate, Asset-/Referenz-IDs, Charakter/LoRA/Modelle, Geld, Prüfungen, Provider-Auswahl |
| `studio_catalog.proto` | Aufgabenprofile, Rezeptversionen, Modellkompatibilität, Modellkatalog, Vergleich, Providerkonten, Modell-/Rollenbindung, Prompts, Figuren, Training, Ressourcen, Projekte |
| `studio_creative.proto` | Kundenerfassung/CreativeBrief, Faktenherkunft, Drehbuch, Dialog, Storyboard, Szenen/Shots, Pose, Motion, Kamera, Blocking, Blender-SceneSpec, Guides, Audio/Timeline |
| `studio_flow.proto` | Node-/Port-/Edge-Typen, Conditions, Stage-Gates, Flow-Versionen, Compilerissues, NodeRuns, ProductionRequest/Run/Receipt, QC, Export, Handoff, Queue |
| `studio_commands.proto` | **59** neue, typenfeste UI-/Operator-Befehle ohne zweite Command-Envelope |
| `studio_stream.proto` | **9** neue STATE-Projektionen, **14** neue EVENT-Payloads, paginierte Read-Nachrichten für tiefere Details |

**Einzelner vollständiger Feldkatalog:** `Studio_Protobuf_Feldkatalog.csv`; Enumwerte: `Studio_Protobuf_Enumkatalog.csv`; Befehle/Topics: `Studio_Protobuf_Routing.csv`. Feldnummern sind dort **verbindlich**. Die Inhalte dieses Pakets sind in `studio_descriptor.pb` vom Protobuf-Compiler geprüft.

## 3. Erweiterungen bestehender Nachrichten – nur additiv

`apply_studio_proto.py` prüft Konflikte und ergänzt ausschließlich:

- `commands.proto`: Import von `studio_commands.proto`; `CommandRequest.oneof command` Nummern **100–158** (59 Einträge). **Unverändert** bleiben alle bisherigen Tags, `request_id`, `expected_version`, `CommandResponse`, `CommandReceipt`.
- `stream.proto`: `Topic` **40–48** STATE und **60–73** EVENT. Die bestehenden 2–32 bleiben erhalten, Nummer 1 bleibt `reserved`. Die `TopicDescriptor`-Typen sind exakt `darkfluenzer.v1.<Payload>`.
- `order.proto`: additive Verknüpfung von `ActiveOrder.production_id`/Revision/Handoff, `OrderUpdated.production_id`, `OrderDelivery.handoff_id`/Exporthash.
- `media.proto`: bestehende Medien-IDs werden um Studio-Asset-ID, Production-ID, Scene-/Shot-/NodeRun-IDs ergänzt; Provenienz ebenfalls nur additiv.
- `influencer.proto`: `PriceItem` erhält `task_profile_id`, `recipe_id`, `recipe_revision` und `studio_output_profile_id`; **alte Workflow-Felder bleiben** bis nach belegtem DS8-Cutover erhalten.
- `reference.proto`, `character.proto`, `ai.proto`, `comfy.proto`, `channel.proto`, `wallet.proto` bleiben unangetastet. Studio nutzt ihre existierenden IDs als Referenzen.

### Backend-Transportregeln

1. Jede **Mutation** mit UUID `request_id`, CAS-Version und typisiertem `oneof`-Payload. Idempotentes zweites Senden derselben Anforderung; andere Bytes mit derselben ID ablehnen.
2. `CommandResponse.ACCEPTED` heißt **nur angenommen**. Terminaler Erfolg/Fehler folgt als `CommandReceipt` und konsistenter Studio-STATE/EVENT. Nie `PASS` aus einer bloßen Quittung ableiten.
3. Jedes neue Topic mit festem `TopicClass` und festem `payload_type` im `Welcome.topics`. STATE: Version+Generation+Seq, EVENT: SQLite-Cursor/Committed Timestamp, Catch-up/Gap nach Reconnect.
4. Großer Zustand (Flow-Graph, alter Storyboardstand, Node-Historie, Asset-Historie) **nicht dauerhaft als komplettes STATE** senden. Dazu `StudioReadRequest`/`StudioReadResponse` als sitzungsgeschützter, ausschließlich bedarfsgesteuerter Protobuf-Page-Read. Nicht als Polling-Ersatz betreiben.
5. Neue Nachrichten in **beiden** Codegen-Zielen erzeugen: `frontend/src/core/generated/darkfluenzer/v1/*_pb.ts` und `backend/src/darkfluenzer/v1/*_pb2.py`. Existierende Proto-Tags/Nummern, Python-/TypeScript-Namen und JSON-freie Architektur bewahren.

## 4. Die fünf Studio-Unteransichten – vollständiges Feld-/Aktionsrouting

| GUI / Interaktion | Persistente DTOs und Variablen | Befehl oder Abfrage | STATE / EVENT |
|---|---|---|---|
| **Erstellen – Projekt** | `StudioProject.project_id,name,revision,default_character,default_look,source` | `studio_project_upsert`, `studio_task_select`, `get_project` | `TOPIC_STUDIO_PROJECTS`, `TOPIC_STUDIO_PROJECT_CHANGED` |
| **Erstellen – Aufgabe/Rezept** | `StudioTaskProfile.task_profile_id,kind,active_recipe_id,active_recipe_revision`; `StudioRecipeVersion` | `studio_recipe_activate`, `StudioReadRequest.list_flows` | `TOPIC_STUDIO_TASKS`, `TOPIC_STUDIO_FLOWS` |
| **Erstellen – Prompt/Kunde** | `StudioCreativeBrief.original_wish,normalized_wish,plot,style,target_character,facts,questions_to_customer,content_tier` | `studio_brief_upsert`, `studio_director_request` | `TOPIC_STUDIO_CREATIVE_CHANGED` |
| **Erstellen – Referenzen** | `StudioReference.reference_binding_id,asset,roles,shot_id,actor_id,strength,approved_for_provider` | `studio_asset_import`, `studio_asset_role_update`, `studio_asset_detach` | `TOPIC_STUDIO_ASSET_CHANGED` |
| **Erstellen – Modell/LoRA** | `StudioModelRef.model_id,architecture,provider_kind`; `StudioLoraRef.lora_key,architecture,sha256,strength` | `studio_model_registry_refresh`; Legacy: `lora_activate` | `TOPIC_STUDIO_TASKS`, `TOPIC_STUDIO_CHARACTERS` |
| **Erstellen – Format** | `StudioOutputSpec.width/height` über `output_dimensions`, `fps_num/fps_den,duration_ms,container,codec,aspect_label,upscale` | `studio_production_submit` | `TOPIC_STUDIO_PRODUCTIONS` |
| **Erstellen – starten/pausieren** | `StudioProductionRequest` und `StudioProduction`, `StudioCost`, `StudioRunStatus` | `studio_production_submit`, `studio_production_control`, `studio_production_rerun` | `TOPIC_STUDIO_PRODUCTION_CHANGED`, `TOPIC_STUDIO_NODE_RUN_CHANGED` |
| **Storyboard – Drehbuch** | `StudioScriptVersion`, `StudioScriptScene`, `StudioDialogueLine` | `studio_script_generate`, `studio_script_upsert` | `TOPIC_STUDIO_CREATIVE_CHANGED` |
| **Storyboard – Shotkarten** | `StudioScene`, `StudioShot.shot_id,time,action,image_prompt,video_prompt,seed,start_frame,end_frame,transition_*` | `studio_storyboard_generate`, `studio_storyboard_upsert`, `studio_scene_upsert`, `studio_shot_upsert`, `studio_shot_remove` | `TOPIC_STUDIO_STORYBOARDS`, `TOPIC_STUDIO_CREATIVE_CHANGED` |
| **Storyboard – KI-Regie** | `StudioDirectorNote`, `StudioModelRole`, `StudioProviderChoice`, `StudioPromptTemplate` | `studio_director_request`, `studio_director_note_decision`, `studio_prompt_template_upsert` | `TOPIC_STUDIO_DIRECTOR_RESULT` |
| **Storyboard – Pose** | `StudioPoseTrack`, `StudioMotionTrack`, `StudioControlSettings.pose/depth/mask/motion/identity_strength` | `studio_asset_role_update`, `studio_shot_upsert`, `studio_blocking_settings_update` | `TOPIC_STUDIO_CREATIVE_CHANGED` |
| **Storyboard – Blocking** | `StudioSceneSpec.objects,actors,blocking_mode`, `StudioBlockingMode` | `studio_scene_spec_upsert`, `studio_blender_build`, `studio_blocking_settings_update` | `TOPIC_STUDIO_GUIDE_CHANGED` |
| **Storyboard – Kamera** | `StudioCameraRig.control,carrier_object_id,keyframes,external`, `StudioCameraExternalInput` | `studio_camera_input_register`, `studio_camera_input_calibration`, `studio_scene_spec_upsert` | `TOPIC_STUDIO_GUIDE_CHANGED` |
| **Storyboard – Guide/Previs** | `StudioGuideBundle.playblast_video,depth_video,pose_video,mask_video,normal_video,blend_file` | `studio_blender_build`, `studio_guide_approval`, `studio_guide_compare_request` | `TOPIC_STUDIO_GUIDE_CHANGED` |
| **Storyboard – Timeline** | `StudioTimeline`, `StudioTimelineTrack`, `StudioTimelineClip`, `StudioAudioCue`, `StudioSubtitleCue` | `studio_timeline_upsert`, `studio_audio_generate` | `TOPIC_STUDIO_CREATIVE_CHANGED` |
| **Charaktere – Profil/Dataset** | vorhandene `Character`, `CharacterLora`, `TrainingPhoto` + `StudioCharacterSheet`, `StudioTrainingRun` | Legacy `character_update`, `character_photos_add`; neu `studio_character_sheet_update`, `studio_training_start/control` | `TOPIC_CHARACTERS`, `TOPIC_STUDIO_CHARACTERS`, `TOPIC_STUDIO_CHARACTER_CHANGED` |
| **Charaktere – LoRA / Look** | `StudioLoraRef`, `StudioLookPreset`, `StudioCharacterSheet.identity_references,looks` | `lora_activate`, `studio_look_upsert` | `TOPIC_STUDIO_CHARACTERS` |
| **Projekte – Liste/Detail** | `StudioProject`, `StudioProductionSummary`, `StudioProduction`, `StudioCost` | `StudioReadRequest.list_projects/list_productions/get_production` | `TOPIC_STUDIO_PROJECTS`, `TOPIC_STUDIO_PRODUCTIONS` |
| **Projekte – Export** | `StudioExportManifest`, `StudioQualityCheck`, `StudioReviewVerdict` | `studio_export_request`, `studio_export_review`, `studio_export_revoke` | `TOPIC_STUDIO_EXPORT_CHANGED` |
| **Labor – Modelle** | `StudioModelCatalog`, `StudioModelCapability`, `StudioCompatibility`, bestehende `Workflows` | `studio_model_register`, `studio_model_set_qualification`, `studio_model_registry_refresh` | `TOPIC_STUDIO_TASKS`, `TOPIC_COMFY_WORKFLOWS` |
| **Labor – Vergleich** | `StudioComparisonRun`, `StudioComparisonItem`, Quality, Costs | `studio_comparison_start`, `studio_comparison_select` | `TOPIC_STUDIO_COMPARISON_CHANGED` |
| **Flow-Editor** | `StudioFlowDefinition.nodes,edges,conditions,stage_gates,flow_sha256`; `StudioNodeDefinition.canvas_position,parameters,inputs,outputs` | `studio_flow_upsert`, `studio_flow_validate`, `studio_flow_activate`, `studio_flow_node_update/remove` | `TOPIC_STUDIO_FLOWS`, `TOPIC_STUDIO_FLOW_CHANGED`, `TOPIC_STUDIO_FLOW_VALIDATED` |
| **Flow-Ausführung** | `StudioNodeRun`, `StudioNodePortValue`, `StudioStepStatus`, `StudioFlowValidation` | `studio_production_submit`, `studio_production_rerun` | `TOPIC_STUDIO_NODE_RUN_CHANGED` |
| **Einstellungen – Text-KI** | `StudioProviderAccount`, `StudioProviderModel`, `StudioRoleBinding`, `StudioProviderSettings` | `studio_provider_account_upsert`, `studio_provider_secret_replace/clear`, `studio_provider_test`, `studio_provider_models_refresh`, `studio_role_binding_upsert` | `TOPIC_STUDIO_PROVIDERS`, `TOPIC_STUDIO_PROVIDER_CHANGED` |
| **Einstellungen – Policy/Kosten** | `StudioProviderPolicy`, `StudioMoney`, `StudioCost`, `StudioProviderUsage`, `StudioRoleBinding` | `studio_global_provider_settings_update`, `StudioReadRequest.list_provider_usage` | `TOPIC_STUDIO_PROVIDERS` |
| **Einstellungen – Ressourcen** | `StudioResourceState`, `StudioWorkerStatus`, bestehende `Resources`, `ComfyInstances` | vorhandene Comfy-Instanzbefehle; `studio_queue_control` | `TOPIC_STUDIO_RESOURCES`, `TOPIC_RESOURCES`, `TOPIC_COMFY_INSTANCES` |
| **Kundenkarte „Im Studio“** | `ActiveOrder.production_id`, `StudioProductionSummary.production_id`, `StudioHandoff`, `StudioHandoffValidity` | `get_production`; Studio darf NICHT selbst zustellen | `TOPIC_ORDER_UPDATED`, `TOPIC_STUDIO_HANDOFF_CHANGED` |

**Nur UI-lokal, daher keine Server-Nachricht:** geöffneter Haupt-/Unterreiter, Modal offen, ausgewählte Karte, Zoom/Pan (bis gespeichert), `playhead` (solange nicht in Timeline gespeichert), Filter ohne serverseitige Suche, Hoverzustand, offene Accordion-Gruppen. Eine tatsächlich gespeicherte Nodeposition **ist** dagegen `StudioNodeDefinition.canvas_position` und wird per `studio_flow_upsert` versioniert.

## 5. Die sechs technischen Produktionsarten + Vorlagen

- F01 Kunde → CreativeBrief/Script/Storyboard → Masterbilder/Clips → Export → Handoff → vorhandenes Darkfluenzer-Liefergate.
- F02 Drei Referenzen → Rollen/Analyse → Shotplan → Fotos/Film.
- F03 Posefoto → Pose/Depth/Mask → andere Zielidentität/Charakter-LoRA → Bild.
- F04 Bewegungsreferenz → Motion/Pose/Guide → charaktergebundenes Video.
- F05 Skizze/Strichmännchen → Posekarte → Charakterbild.
- F06 Bild-/Video-Replacement mit Maske/Identity-Lock.
- F07 Form/Proxy → Identität → Material → Foto/Animation.
- F08 Blender SceneSpec/Blocking → GuideBundle → Video-Control → Vergleich → Export.
- F09 Werbefilm mit Shot- und Kamera-Presets, Produkten und Assets.
- F10 Ein Guide mit mehreren versionierten Looks und selektiver Neuberechnung.

Alle sind `RecipeVersion`/`FlowDefinition` über **denselben Executor**. Keine Sonder-Python-Pipeline pro Preset. Blender, ComfyUI 1 (Medien) und ComfyUI 2 (Melody/Text) sind **Adapter**, keine parallelen Datenhaltungen.

## 6. Blender / iPhone-Variablen, die auf keinen Fall fehlen dürfen

- `StudioSceneSpec`: Szene/Shot/Revision, FPS/Frames, Koordinatensystem, Maße, Proxy-Objekte, Actor-Rigs, Kamera-Rigs, Lichter, Bewegungs-/Posespuren, Guides, Grenzen, Builder-Version und Hash.
- `StudioSceneObject`: ID, primitive Form, Position/Rotation/Scale, Größe, Material, Parent, Actor-Zuordnung, Keyframes.
- `StudioCameraRig`: Carrier-/Path-/Parent-ID, Lens/Sensor/Focus, Keyframes, getrennte Translation/Rotation, externe Quelle, Stabilisierung.
- `StudioCameraExternalInput`: Adapter-/Gerätealias, Kalibrierung, Zeitbasis, Achsenkonversion, Latenzkorrektur, yaw/pitch/roll, Glättung, erlaubte Eingabekanäle.
- `StudioCameraSensorSample`: Nanosekunden-Zeitstempel, Quaternion, optionale Translation, Confidence, Sequenz. **Nicht** als ungebremste einzelne Events im Cockpit streamen; im Kameraadapter puffern und versionierten Track als Asset persistieren.
- `StudioGuideBundle`: `.blend`, Playblast/Guidevideo, Depth/Pose/Mask/Normal/Edge, Kamera- und Darstellertracks mit einheitlichen Frames/FPS/Hashes.
- `StudioGuideMatch`: gemessene Guide-zu-Video-Abweichung und qualifizierte (oder `UNKNOWN`) QC-Bewertung. *Blender-Guide ist keine pixelidentische Garantie für generiertes Video.*

## 7. Liefer-Gate und Datenhoheit

- Studio meldet nur geprüfte `StudioExportManifest` und Status `ready_for_handoff`. **Kein `StudioSendCustomer`-Befehl**.
- `StudioHandoff` wird ausschließlich vom **Kundenmodul** geschrieben und revidiert. Die Verknüpfung in bestehende `ActiveOrder` / `OrderDelivery` wird additiv ergänzt.
- Nachträgliche Sperren/Änderungen erhöhen `revocation_revision`; Handoff wird widerrufen. Revalidierung unmittelbar vor Dispatch: aktuelle Zahlung/Testfreigabe, Inhaltsstufe, Betreiberentscheidung, Export-/QC-/Auftragsrevision, Kanalfenster, echte Bytes und SHA-256. Eine alte Freigabe darf nicht erneut wirksam werden.
- Crash zwischen Outbox-Reservierung und externem Versand führt gegebenenfalls zu `UNKNOWN` und Abgleich; kein blindes automatisches erneutes Senden.
- Studio-Modul importiert und beschreibt keine Kunden-/Payment-/Delivery-Tabellen. Das Kundenmodul liest keine Studio-Tabellen direkt. Der Composition Root koordiniert die Übergabe transaktional über getrennte Repositories.

## 8. Sicherheit / Validierung / Kosten

- Modell- und Referenzidentität sind **getrennte Typen**: Quellmännerfoto kann Pose/Depth liefern; Zielidentität aus freigegebener Character-/LoRA-Version. SDXL-LoRA nicht als Wan-/LTX-LoRA umdeklarieren. `StudioCompatibility`/`StudioModelCapability` validieren jede gewählte Kombination.
- API-Konten: ein `StudioProviderAccount` pro benanntem Konto; Mehrfachkonten sind möglich. `StudioProviderSecretReplace.secret_utf8` ist **nur ein WRITE-ONLY-Command-Parameter**. `StudioProviderAccount` liefert ausschließlich `secret_present` und Status. Backend verarbeitet Keychain **vor** Abschluss, persistiert keine Raw-Commands oder Geheimnisse; CommandReceipt/Logs/Events enthalten nie Credentials. Secret-Command-Body nicht im Fehlerdetail reflektieren.
- Konto-Scope + Rolle + Cloud-Opt-in + Kostenlimit vor jedem Submit prüfen; automatischer Cloud-Fallback nur ausdrücklich freigegeben. `STUDIO_PROVIDER_ARTLIST_MANUAL` ist kein API-Adapter und darf keinen Netzwerk-Job vortäuschen.
- Alle `*_id` und `*_sha256` serverseitig auf Existenz/Ownership/Revisions-/Content-Gate prüfen. File-IDs und Pfadwünsche dürfen nicht zu beliebigen Dateizugriffen führen.
- `proto3` ist ein **Wire-Format, kein Validator**: Enum-0, Leerstrings, Zahlengrenzen, `optional`-Presence, eindeutige Node-/Edge-IDs, gültige DAGs, zulässige Dateimengen und Modell-/LoRA-Kompatibilität serverseitig prüfen.
- Node-Fingerprint ausdrücklich aus fachlich **kanonisierten** Eingaben bilden. Raw Protobuf-Bytes sind nicht kanonisch und allein kein geeigneter inhaltsidentischer Cache-/Signaturbeleg.

## 9. Protobuf-Codegen und phasenweise Implementierung

**Für den Hauptentwickler:**

1. Git-Stand und vorhandene Protobuf-Tags neu prüfen; Änderungen von anderen Agenten nicht überschreiben. Datenbank sichern, Backups prüfen, Protokoll-IDs inventarisieren (DS0).
2. Auf freiem Arbeitsbaum im Projektroot ausführen: `python /path/to/this-package/apply_studio_proto.py /path/to/Darkfluenzer`. Das Script patcht die fünf bestehenden v1-Dateien additiv und kopiert die sechs neuen Studio-Protos. **Kein automatischer Commit.**
3. Das vorhandene Generatorverfahren verwenden: `cd protocol && buf lint && buf generate`. `protocol/buf.gen.yaml` generiert TypeScript via `@bufbuild/protoc-gen-es` und Python via protoc builtin. Generierten Code nicht von Hand bearbeiten.
4. `schema_id`/Versions-Handshake aus den **tatsächlich aktualisierten Schemas** neu bilden, Topic-Registry/Welcome aktualisieren. Browser und Backend müssen exakt dasselbe Schema akzeptieren; Fehler/Schema-Drift nicht ignorieren.
5. Backend-Commands pro Phase dispatchen, Domain-Repos/Projections/Events ergänzen; **nicht** sofort 59 Fake-Handler aktivieren. Erst mit passender Implementierung Buttons freischalten und Testnachweise erbringen.
6. DS1: Task/Recipe/Model + einfache GUI; DS2/DS3: FlowRun/NodeRun/Events/Service/Handoff; DS8: Cloner/Kunde/Cockpit auf Service; DS4: Referenz/LoRA; DS5: KI-Regie/Provider; DS6: Film/Timeline; DS6b: Blender/Guide; DS7: Editor; DS9: optionale Cloud/Audio/iPhone; DS10: vollständige Qualifikation.
7. Tests: Protobuf-Compile/Buf-Lint, Feld-/Tag-Kollision, Schema-ID/Handshake, TS/Python-Roundtrip, CommandReceipt, STATE/EVENT-Catchup, Revisionskonflikt, Neustart, Journal-Dedupe, Model-/LoRA-Gate, Cloud-Secret-Schutz, Kosten-Gate, Handoff-Revocation + Pre-Dispatch-Hash, Browser-Klick zu echtem Handler und kurzem Mac-Lauf pro abgeschlossenem Paket.

**Status nach Erzeugung dieses Pakets:** Neue sechs Studio-Protos mit lokalem `protoc` kompiliert. Additive Patchfunktion gegen repräsentative Schema-Fixures mehrfach ausgeführt; Kollision und Idempotenz geprüft. **Nicht** nachgewiesen: `buf lint` im Originalprojekt, `buf generate` mit installiertem Node-Tooling, echte Integration der Original-Backend-Dispatcher/DB, Mac-/Browser-End-to-End, externe API-Konten. Nicht als `PASS` deklarieren.
