# Darkfluenzer – KI-Modelle: Bestand, Downloadkette, Präzision

**Stand:** 15.11.2026, 18:30 · Teil von [PHASENPLAN_V0.md](PHASENPLAN_V0.md) §14.1 · Ablage immer unter `local/models/<ComfyUI-Typ>/<Familie>/`

**Wer lädt (Betreiberentscheidung 15.11.2026):**
- **Darkfluenzer lädt selbst, streng nacheinander:** jeweils eine Datei vollständig, SHA-256 gegen Hugging Face geprüft, erst dann die nächste. Die Revision ist je Repo beim Start festgehalten, Protokoll in `local/logs/model_downloads.log`. Sobald eine Gruppe fertig ist, wird ihr Workflow gebaut und echt getestet, während die nächste Gruppe lädt.
- **Der Betreiber lädt nur, was eine Anmeldung oder Lizenzannahme braucht:** LUSTIFY v10 (Civitai) und FLUX 3 Klein (Hugging Face). Für LTX 2.5 nimmt der Betreiber die Lizenz auf Hugging Face an, danach lädt die Kette selbst.
- **Löschen:** Kein Modell wird ohne ausdrückliche Bestätigung des Betreibers gelöscht. Dieser Downloadplan ist keine Löschfreigabe.

**Auswahl:** Lizenzbedingungen sind kein Auswahlkriterium (Betreiberentscheidung 15.11.2026). Sie bleiben im Manifest dokumentiert. Geladen wird die **Originalpräzision (★, BF16/FP16, FP32 wo das Original FP32 ist)**. Quantisierte Stufen (FP8/INT8/NVFP4/GGUF) kommen nur dort zum Einsatz, wo keine Originalfassung existiert (Wan Remix v3.0).

## 1. Vorhanden (SHA-256 geprüft, Datentyp aus dem Dateikopf)

| Modell | Datei | Präzision | Größe GB | Ablage | Workflow |
|---|---|---|---|---|---|
| LUSTIFY v2.0 (SDXL) | `lustifySDXLNSFWSFW_v20.safetensors` | FP16 | 6,94 | `checkpoints/sdxl/` | Text zu Bild, Inpainting, Verfeinern, Bearbeiten mit SAM 3.1 |
| SAM 3.1 (Masken) | `sam3.1_multiplex_fp16.safetensors` | FP16 (einzige Stufe) | 1,75 | `checkpoints/sam3/` | Bearbeiten mit SAM 3.1 |
| Wan 2.2 I2V A14B high / low | `wan2.2_i2v_{high,low}_noise_14B_fp16.safetensors` | FP16 | 2 × 28,58 | `diffusion_models/wan22/` | Wan 2.2 · Bild zu Video |
| Wan 2.2 Remix NSFW v3.0 high / low | `…_{high,low}_lighting_fp8_e4m3fn_v3.0.safetensors` | **FP8 E4M3** (einzige v3.0-Stufe) | 2 × 14,29 | `diffusion_models/wan22/` | Wan 2.2 Remix v3.0 |
| umt5-xxl (Wan-Textencoder) | `umt5_xxl_fp16.safetensors` | FP16 | 11,37 | `text_encoders/umt5/` | Wan |
| Wan 2.1 VAE | `wan_2.1_vae.safetensors` | BF16 | 0,25 | `vae/wan/` | Wan |
| Krea-2-Textencoder Qwen3-VL-4B | `qwen3vl_4b_bf16.safetensors` | BF16 | 8,88 | `text_encoders/krea2/` | Krea 2 |
| Qwen-Image-VAE (= Krea-2-VAE, gleicher SHA-256) | `qwen_image_vae.safetensors` | BF16 | 0,25 | `vae/qwen-image/` | Krea 2 |
| FLUX-2-VAE (für FLUX 3 Klein) | `flux2-vae.safetensors` | FP32 | 0,34 | `vae/flux2/` | FLUX 3 Klein |
| SeedVR2-VAE | `seedvr2_ema_vae_fp16.safetensors` | FP16 (einzige Stufe) | 0,50 | `vae/seedvr2/` | SeedVR2 (Gruppe 4) |
| AuraFace-v1 · YuNet · SFace | `glintr100.onnx` · `face_detection_yunet_2023mar.onnx` · `face_recognition_sface_2021dec.onnx` | FP32 | 0,26 · 0,00 · 0,04 | `face/auraface/`, `face/opencv/` | Identitätsmetrik (`darkfluenzer identity`) |

**Wan Remix:** v3.0 gibt es im Repo `FX-FeiHou/wan2.2-Remix` nur als FP8. Welche Remix-Version bleibt, entscheidet der Video-Vergleich in B4.

## 2. Downloadkette (nacheinander, in dieser Reihenfolge)

| Nr. | Gruppe | Dateien (★ Originalpräzision, GB) | Quelle | Ablage unter `local/models/` | Wer / Stand |
|---|---|---|---|---|---|
| 1 | Gesichtsprüfung | AuraFace, YuNet, SFace | fal/AuraFace-v1, opencv/* | `face/` | **fertig** |
| 2a | Krea 2 Turbo (Inferenz) | Encoder Qwen3-VL-4B BF16 8,88 · **Turbo BF16 26,28** | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2) @588feaf9 | `text_encoders/krea2/`, `diffusion_models/krea2/` | Darkfluenzer · Encoder fertig, Turbo lädt |
| 2b | Krea 2 Raw (Trainingsbasis) | **Raw BF16 26,28** · Turbo-LoRA rank 64 BF16 0,47 | wie oben | `diffusion_models/krea2/`, `loras/krea2/` | Darkfluenzer |
| 3 | LUSTIFY v10 (Krea-2-Finetune, explizit) | BF16 26,28 | [Civitai 573152 · v10](https://civitai.com/models/573152) | `diffusion_models/lustify/` | **geladen 15.11.2026** über den HF-Spiegel `ffkk200/Krea2@e79af65` (Datei `lustifyNSFWCheckpoint_v10Krea2_3015315`), SHA-256 `017f3363…` geprüft; Rendern bestanden (Auftrag 52) |
| 4 | SeedVR2 (Bild-/Video-Upscaler) | 3B FP16 6,78 · 7B FP16 16,48 | [Comfy-Org/SeedVR2](https://huggingface.co/Comfy-Org/SeedVR2) | `diffusion_models/seedvr2/` | **geladen 15.11.2026**, SHA-256 geprüft; 7B Rendern bestanden (Auftrag 53, 2K in 99 s) |
| 5 | FLUX 3 Image Klein Base | Base BF16 11,08 · Encoder Qwen3-VL-4B BF16 8,88 · Prompt-Upsampler Qwen3.5-9B BF16 18,82 | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) | `diffusion_models/flux3/`, `text_encoders/qwen3vl/` | **geladen 16.11.2026** (SHA-256 geprüft); Text zu Bild und Foto nach Vorlage bestanden (Aufträge 54/55) |
| 6 | Qwen-Image-2512 | BF16 40,86 · Encoder Qwen2.5-VL-7B 16,58 | [Comfy-Org/Qwen-Image_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI) | `diffusion_models/qwen-image/`, `text_encoders/qwen2.5vl/` | **geladen 16.11.2026** (SHA-256 geprüft); Text zu Bild bestanden (Auftrag 56, 1622 s) |
| 7 | Qwen-Image 2.1 | BF16 14,23 · Encoder Qwen3-VL-8B 17,53 · VAE 2.1 0,68 | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | `diffusion_models/qwen-image/`, `text_encoders/qwen3vl/`, `vae/qwen-image/` | Darkfluenzer |
| 8 | Pose und Tiefe | SDPose Wholebody FP16 1,92 · RT-DETR v4 FP32 0,25 · Depth Anything 3 Mono Large 1,34 | Comfy-Org/SDPose, Comfy-Org/Depth-Anything-3 | `checkpoints/sdpose/`, `diffusion_models/sdpose/`, `geometry_estimation/depth_anything3/` | Darkfluenzer |
| 9 | FLUX.2 Dev | BF16 64,45 · Encoder Mistral-3-Small BF16 35,58 | black-forest-labs/FLUX.2-dev (Zugang vorhanden), Comfy-Org/Flux-2-Dev | `diffusion_models/flux2/`, `text_encoders/mistral3/` | **erst nach Platzentscheidung** (§3), dann Darkfluenzer |
| 10 | Wan Animate 2 (Bewegungsübertragung) | BF16 32,79 · CLIP Vision H 1,26 · VAE BF16 0,25 · lightx2v-LoRA BF16 0,74 | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) | `diffusion_models/wan22/`, `clip_vision/wan/`, `vae/wan/`, `loras/wan/` | Darkfluenzer |
| 11 | LTX 2.5 Dev | 22B Dev BF16 · Gemma-4-12B-Encoder BF16 26,26 · Video-/Audio-VAE · Raum-/Zeit-Upscaler x2 (zusammen ≈ 72) | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | `diffusion_models/ltx25/`, `text_encoders/gemma4/`, `vae/ltx25/`, `latent_upscale_models/ltx25/` | **Betreiber nimmt die Lizenz auf HF an**, danach Darkfluenzer (Repo für dein Konto noch gesperrt) |
| 12 | FILM (Bildinterpolation) | FP16 0,07 | [Comfy-Org/Frame-Interpolation](https://huggingface.co/Comfy-Org/Frame-Interpolation) | `frame_interpolation/film/` | Darkfluenzer |

**Krea 2:** Raw ist laut Modellkarte **nicht für die Inferenz gedacht**, sondern Basis für Finetuning und LoRA-Training (Einstellungen dort: 52 Schritte, CFG 3,5, 1024 × 1024). Generiert wird mit **Turbo**, der destillierten Fassung (Vorlage: 8 Schritte, CFG 1). Mit der Turbo-LoRA läuft eine auf Raw trainierte Charakter-LoRA im Turbo-Tempo.

**Gleicher Dateiname, andere Datei:** `qwen3vl_4b_bf16.safetensors` gibt es bei Krea 2 und bei FLUX 3 mit unterschiedlichem SHA-256 (Abweichung im Dateikopf, 24 Byte). Die Fassungen liegen deshalb in getrennten Ordnern. Sind die Tensoren gleich, braucht FLUX 3 keine zweite Kopie. Das wird geprüft, sobald beide Dateien da sind.

## 3. Platzbilanz (15.11.2026, 18:30)

| Posten | GB |
|---|---|
| frei auf dem Datenträger | 299 |
| Reserve (nie unterschreiten) | 30 |
| **nutzbar** | **269** |
| Kette ohne Gruppe 9 (Rest Turbo, 2b, 4, 6, 7, 8, 10, 12) | 205 |
| Betreiber: LUSTIFY v10 + FLUX 3 Klein | 65 |
| LTX 2.5 Dev | ≈ 72 |
| FLUX.2 Dev | 100 |
| **Summe** | **≈ 442** |

**Es fehlen rund 175 GB.** Selbst ohne FLUX.2 Dev und LTX 2.5 reicht es gerade nicht (270 von 269 GB). Die Kette prüft vor jeder Datei den Platz und hält mit „PLATZ FEHLT“ an, statt die Reserve anzugreifen. Ob und welche vorhandenen Modelle (z. B. Wan 2.2 I2V FP16, 57 GB) nach den Vergleichen gelöscht werden, entscheidet der Betreiber ausdrücklich.

## 4. Später, noch nicht laden

| Modell | Präzision | Größe GB | Hinweis | Phase |
|---|---|---|---|---|
| Cydonia 24B v4.1 (Dialog-LLM) | GGUF Q8_0 (höchste Stufe im GGUF-Repo) | 25,05 | Ob Q8_0 reicht oder das BF16-Original nötig ist, zeigt der Vergleich in B5 | B5 |
| RelayVSR (Video-Upscaler, Vergleich) | nur INT8 (Decoder FP32) | 5,3 | keine BF16-Fassung, daher nur Vergleichskandidat | B4 |
