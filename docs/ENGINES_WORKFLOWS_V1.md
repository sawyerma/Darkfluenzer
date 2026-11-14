# Darkfluenzer — Engines und Workspaces V1

**Stand:** 14.11.2026  
**Status:** Verbindliche Rollen und Ordnerkonventionen; konkrete Modell-Deployments noch nicht abgenommen  
**Masterplan:** [PHASENPLAN_V1.md](PHASENPLAN_V1.md)  
**Kundendaten:** [KUNDEN_DATENMODELL_V1.md](KUNDEN_DATENMODELL_V1.md)

## 1. Engine-Entscheidungen

Die **Architektur** und die Engine-Rollen sind fixiert. Ein Modell gilt nur nach reproduzierbarem Apple-Test, Prüfung der Nutzungsrechte einschließlich des beabsichtigten kommerziellen Inhalts und visueller Abnahme als produktiv.

| Engine-ID | Rolle | Kandidat/Basis | Laufzeit | Festlegung |
|---|---|---|---|---|
| CORE_COMFY | Orchestrierte Medienberechnung | ComfyUI, nur lokale HTTP-/WebSocket-API | PyTorch/MPS | VERBINDLICH |
| IMG_MASTER_V1 | Kanonische fotorealistische Ausgangsbilder | FLUX 3 Image Klein Base, mit eigener zur Architektur passender Charakter-LoRA | ComfyUI oder verifizierter kompatibler Adapter | KANDIDAT; kein lokaler PASS |
| IMG_MASTER_CHALLENGER | Unabhängiger Qualitätsvergleich | Qwen-Image 2.1 | kompatible lokale Inferenz | KANDIDAT |
| IMG_EDIT_ADULT_V1 | Regionales spezialisiertes Bild-Editing | LUSTIFY! v2.0, SDXL | ComfyUI/MPS | KANDIDAT, Inpainting-Qualität ungeprüft |
| IMG_EDIT_FALLBACK | Kontrollversuch mit anderem SDXL-Checkpoint | RealCore Illustrious / geeignetes Inpaint-Modell | ComfyUI/MPS | KANDIDAT |
| IMG_REFINE_V1 | Regionaler Detailer, Tiled Refinement, Upscaling | ComfyUI-Workflow mit versionierten Nodes | ComfyUI/MPS | BAUSTEIN, Test offen |
| VID_MAIN_V1 | Bild-zu-Video und zeitliche Bewegung | Wan 2.2 Remix NSFW I2V High-/Low-Noise als zusammengehöriges Paar | ComfyUI; FP8/MPS unbestätigt | EXPERIMENTELL / NICHT LIVE |
| VID_MAC_FALLBACK | Apple-fähiger alternativer Videozweig | LTX 2.5 Fast | LTX Desktop, geeigneter lokaler Adapter | UNABHÄNGIGER KANDIDAT |
| LLM_CHAT_V1 | Chat, Intent-Extraktion und Szenen-/Promptbeschreibung | Austauschbarer lokal ausführbarer Textmodell-Checkpoint | MLX oder llama.cpp/Ollama | MODELLWAHL OFFEN |
| STORAGE_V1 | Kunden, Aufträge, Zahlungen, Audit | SQLite und lokal gespeicherte Artefakte | Python/SQLite | VERBINDLICH |
| MESSAGING_V1 | Chat, Betreiberfreigabe, Versand | Telegram Bot API | separater Bot-Adapter | VERBINDLICH |
| PAYMENT_V1 | Zahlungseingang und Rückabwicklung | austauschbarer Provider; für Telegram-Digitalverkäufe Stars-Prüfpfad | separater Payment-Adapter | GATE OFFEN |

**Lizenzvorbehalt:** MiniMax H3-Image darf nicht über seine reguläre Community-Lizenz in der EU als Produktionsmodell betrieben werden. FLUX 3 Klein Base besitzt eigene Bedingungen inklusive eingeschränkter kommerzieller Ausnahme; diese ist **keine pauschale Erlaubnis für beliebige kommerzielle Adult-Dienste**. Ebenso sind die Bedingungen der spezialisierten Checkpoints und Video-LoRAs individuell zu prüfen. Quellen: https://huggingface.co/MiniMaxAI/MiniMax-H3-Image/blob/main/LICENSE ; https://huggingface.co/black-forest-labs/flux-3-image-klein-base ; https://huggingface.co/asertvc/LUSTIFY-v2.0 ; https://github.com/Lightricks/LTX-Desktop .

## 2. Master-First-Vertrag

1. Das ausgewählte Master-Bildmodell berechnet ein vollständiges Bild. Originaldatei, Modellrevision, Prompt, Seed und Eingangsreferenzen werden revisionsfähig gespeichert.
2. Das unveränderte **MASTER_PNG** ist die alleinige visuelle Ausgangsbasis eines Auftrags. Die Normal-/Spezialvarianten referenzieren seine eindeutige Artefakt-ID.
3. Normale Varianten: Master-PNG → optische Korrekturen → Detailer/Upscale → Kandidaten.
4. Spezialisierte Varianten: Master-PNG → objektbezogene Maskenerzeugung → maskiertes SDXL-Inpainting → pixelgenaues Composite → Detailer/Upscale → Kandidaten.
5. Videovarianten: freigegebenes Startbild als PNG → Wan/LTX I2V → temporale Qualitätsprüfung → Video-Kandidaten.
6. Die Rolle einer Character-LoRA ist architekturgebunden: FLUX-Adapter niemals als SDXL-LoRA laden. Wenn Identitätskontrolle beim SDXL-Editor fehlt, separat SDXL-tauglichen Adapter/Referenzkonditionierung prüfen.
7. Unmaskierte Originalpixel bleiben im zusammengesetzten **Vor-Refinement-Edit** identisch. Ein späteres Upscaling erzeugt ein neues Bild und kann diese Eigenschaft aufheben; deshalb Original, Composite und Upscale getrennt speichern.

### Kleidung / Bearbeitungszonen

**Primär**: maskierte Segmentierung der gewünschten Kleidungsobjekte mit manueller Korrekturmöglichkeit.  
**Optional**: technische Kontrollfarben auf einer separaten Segmentierungs-/Maskenebene; keine erzwungene, unnatürliche Farbgebung des hochwertigen Masterbilds.  
Eine reine Farbschwelle im RGB-Master ist wegen Beleuchtung, Wasser und Farbüberschneidungen **nicht** hinreichend robust. Masken sind versionierte PNG-Dateien mit Referenz auf das Original und klar definiertem Randbereich. Eine Inpainting-Engine generiert verdeckte Bereiche neu, sie rekonstruiert sie nicht fotografisch.

## 3. Verbindliche Repository-Workspaces

~~~text
workflows/
├── README.md
├── _registry/
│   ├── engines.toml
│   └── accepted_versions.toml
├── images/
│   ├── 01_master/
│   │   └── flux3_klein/v001/
│   ├── 02_identity/
│   │   └── character_reference/v001/
│   ├── 03_masks/
│   │   └── garment_segmentation/v001/
│   ├── 04_regional_edit/
│   │   └── lustify_sdxl/v001/
│   ├── 05_refinement/
│   │   └── tiled_detailer/v001/
│   ├── 06_export/
│   │   └── image_delivery/v001/
│   └── _candidates/
│       └── qwen_image_21/v001/
├── videos/
│   ├── 01_i2v/
│   │   ├── wan22_remix/v001/
│   │   └── ltx25_fast/v001/
│   ├── 02_temporal/
│   │   └── temporal_consistency/v001/
│   └── 03_export/
│       └── video_delivery/v001/
└── llm/
    └── 01_prompt_builder/v001/
~~~

Jeder tatsächlich vorhandene ComfyUI-Workspace erhält die identische Struktur:

~~~text
<workspace>/v001/
├── README.md                   # Aufgabe, Eingaben/Ausgaben, technische Voraussetzungen
├── workflow-ui.json            # ComfyUI-Native-UI-Graphik; Pflicht wenn ComfyUI
├── workflow-api.json           # API-Export; Pflicht für autonome ComfyUI-Ausführung
├── manifest.toml               # Engine-ID, Revision, Hashes, Nodes, Lizenz, Status
├── inputs/                     # Nur synthetische, nicht-private Testreferenzen
└── tests/                      # Fixture, Abnahmekriterien und letzte Testreferenz
~~~

**Kein ungeprüftes Ablegen beliebiger JSONs:** UI-Graph und API-Graph sind verschiedene Verträge. Nur registrierte, gehashte API-Exports mit festen Typen dürfen durch den Orchestrator modifiziert und ausgeführt werden. Custom Nodes erhalten gepinnte Versionen. Keine Cloud-Partner-Nodes in der lokalen Produktionsroute.

## 4. Engine-Zustandsmodell

~~~text
RESEARCH
  -> FILES_PRESENT
  -> LOADS_ON_MAC
  -> FUNCTIONAL_PASS
  -> QUALITY_PASS
  -> LICENSE_PASS
  -> APPROVED_FOR_USE
~~~

Bei jeder Versionsänderung muss die Abnahme der betroffenen Engine wiederholt werden. Die Freischaltung ist technisch in der Registry zu erzwingen; ein Dateidownload ist kein Funktionsnachweis. Fehlende Checkpoints, nicht vorhandene LoRAs und nicht unterstützte FP8-Operatoren werden nicht durch andere Modelle „still“ ersetzt.

## 5. Abnahmemessungen

**Bild:** gleicher Testkatalog, Vergleich mit unverändertem Master, Gesichtskonsistenz, lokale Geometrie-/Anatomiefehler, Textur, Licht, Maskenränder, Auflösung, Renderzeit, Speicherverbrauch, manuelle Freigabefähigkeit.  
**Video:** Startbild-Identität, Bewegung, physische Kontakte, Perspektive, Flackern, Fehler pro Frame, Segmentübergänge, FPS, Länge, Renderzeit, RAM/MPS-Verbrauch.  
**LLM:** Extraktion mehrteiliger Anforderungen, Trennung von Chatantwort und Promptauftrag, keine Möglichkeit zur Aktivierung des Zahlungs-/Freigabe-Gates.  
**Plattform:** ohne aktuelle LICENSE_PASS keine Kundenproduktion; ohne Mac FUNCTIONAL_PASS kein produktiver Routenwechsel.

## 6. Reihenfolge der technischen Umsetzung

1. Launcher/P00-P01 fertigstellen und lokalen ComfyUI-API-Health-Test sichern.
2. Master-Bildengine auf M4 testen; Identity-Referenzen; unveränderliches Masterbild.
3. Regionale Masken und LUSTIFY-Inpainting gegen Alternativen testen.
4. Quality-Refinement getrennt prüfen.
5. Videorouten getrennt testen; Wan MPS nur nach FP8-Kompatibilitätsnachweis.
6. Die Workflow-Registry über stabile Engine-IDs an den Kunden-Job-Orchestrator anbinden.
7. Erst anschließend Telegram, Zahlungs-Gate, Betreiberfreigabe und Versand integrieren.

**Keine Engine wird durch diesen Plan allein als funktionsfähig oder kommerziell freigegeben ausgewiesen.**
