# DarkStudio – historischer Ursprung des Protobuf-Entwurfs (nicht normativ)

**Stand 18.11.2026 – Audit III:** Diese Datei ist **keine zweite verbindliche Studio-Spezifikation**. Maßgeblich sind [README.md](README.md), [Studio_Protobuf_Routing_Vollstaendig.csv](Studio_Protobuf_Routing_Vollstaendig.csv), [Studio_Protobuf_Feldkatalog.csv](Studio_Protobuf_Feldkatalog.csv), Backend-Phasenplan §13.18 und Frontend-Phasenplan §6.13.

Der ursprüngliche Entwurf mit 59 COMMAND, 9 STATE, 14 EVENT, 24 READ sowie 195 Nachrichtentypen und 1.781 vorgeschlagenen Feldern ist **historische Bruttobasis**. Der vollständige historische Text bleibt [im Git-Vorgängerstand vor Audit III](https://github.com/sawyerma/Darkfluenzer/blob/34d395d746ee12f0a30ec31f824a725be6c7b9f8/protocol/contracts/studio/README_STUDIO_PROTOBUF.md) erhalten.

## Korrekturen gegenüber dem historischen Entwurf

- **Eine Produktionsmaschine:** `customers/orders` besitzt nach DS8 nur kaufmännische Kundenaufträge; Betreiber-, Default- und Kundenproduktion durchlaufen ausschließlich `StudioProduction/ProductionRun` mit einem Executor.
- **Bestand vor Neu:** Bereits publizierte Protobuf-Typen für Queue, Ressourcen, ComfyUI-Instanzen, Workflows, Charaktere, LoRA, Training, Medien und MediaCheck werden erweitert; parallele Studio-Bestandsnachrichten entfallen.
- **Wire-Stabilität:** Veröffentlichte Command-Tags 12/21/22/24/38 dürfen nach dem Handler-Umbau nicht einfach als `reserved` markiert werden. Historische Payloads und Lesbarkeit erhalten.
- **Ein CAS:** Der bereits vorhandene `CommandRequest.expected_version` ist maßgeblich; zusätzliche Studio-`expected_revision`-Commandfelder entfallen.
- **Ein Dateiimport:** Der bestehende geprüfte, begrenzte `InputFile.data`-Transport bleibt zulässig. Kein zweiter `inline_bytes`-Pfad und kein unbelegtes `staged_upload_id`.
- **Nur ein manueller Kundenfreigabeweg:** automatische Studio-QC; Operatorfreigabe, falls notwendig, ausschließlich beim Kunden über Befehl 34 oder verifizierten Handyweg. Studio-Export-Review nur für Eigenproduktionen.
- **Rechts-/Sicherheitsgrenzen:** F06 ersetzt fremde reale Personen niemals; Fremdvorlagen liefern ausschließlich Pose, Bewegung, Kamera und Komposition. Kein automatischer Cloud-Fallback, keine personenbezogenen Kundendaten an externe KI.
- **Qualifikation:** Kein `gpu_busy_percent` ohne Messbeleg. Vier Engine-Gates, `usage`, `unknown`/`stalled_s` und die Einzelwerte von `MediaCheck` erhalten.
- **Korrigierte Routenzahl:** 113 dokumentierte Routingzeilen (106 ursprüngliche + 7 ergänzte), 16 gestrichen, höchstens 97 bedarfsgebunden.

**Kein Kompilierungsnachweis:** Im am 18.11. geprüften Git fehlten die sechs ausführbaren `studio_*.proto`-Dateien, `studio_descriptor.pb`, `apply_studio_proto.py` sowie der numerische Enum-Katalog mit 21 Studio-Enums. Die Behauptung der Ursprungsvorlage, das Schema sei bereits kompiliert, ist kein überprüfbarer Implementierungsnachweis.
