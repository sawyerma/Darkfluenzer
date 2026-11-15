# Darkfluenzer – KI-Modelle: Bestand, Downloads, Präzision

**Stand:** 15.11.2026 (nach Abbruch der eigenen Downloads) · Teil von [PHASENPLAN_V0.md](PHASENPLAN_V0.md) §14.1 · Ablage immer unter `local/models/`

**Du lädst die Modelle selbst** (Betreiberentscheidung 15.11.2026): Du wählst die Präzisionsstufe, Darkfluenzer lädt nichts mehr eigenständig. Dateinamen bitte unverändert lassen. Bei der Registrierung in Block B liest Darkfluenzer die tatsächliche Präzision aus dem Dateikopf und hält SHA-256, Quelle und Größe im Manifest fest.

**Ablage:** alles unter `/Users/sawyer_ma/Desktop/Firma/2_DarkMa/8_Darkfluenzer/local/models/` im jeweils genannten Unterordner (`<ComfyUI-Typ>/<Familie>/`). Mehrere Präzisionsstufen desselben Modells dürfen nebeneinander liegen, die Dateinamen unterscheiden sich.

**Hinweise zu den Stufen:**
- **BF16/FP16** ist die Originalqualität.
- **FP8/INT8** halbieren etwa den Speicher und verlieren etwas Qualität. Ob sie auf dem Mac (MPS) schneller rechnen, ist nicht belegt und wird in B2 gemessen.
- **MXFP8/NVFP4** sind für NVIDIA-Blackwell-Karten gebaut und auf dem Mac nicht erprobt.
- **GGUF Q…** sind starke Quantisierungen für Sprachmodelle bzw. Speicherknappheit.

## 1. Vorhanden (Datentyp aus dem Dateikopf gelesen)

| Modell | Datei | Präzision | Größe | Ablage |
|---|---|---|---|---|
| LUSTIFY v2.0 (SDXL) | `lustifySDXLNSFWSFW_v20.safetensors` | FP16 | 6,94 GB | `checkpoints/sdxl/` |
| Wan 2.2 I2V A14B high | `wan2.2_i2v_high_noise_14B_fp16.safetensors` | FP16 | 28,58 GB | `diffusion_models/wan22/` |
| Wan 2.2 I2V A14B low | `wan2.2_i2v_low_noise_14B_fp16.safetensors` | FP16 | 28,58 GB | `diffusion_models/wan22/` |
| Wan 2.2 Remix NSFW v3.0 high | `…_high_lighting_fp8_e4m3fn_v3.0.safetensors` | **FP8 E4M3** | 14,29 GB | `diffusion_models/wan22/` |
| Wan 2.2 Remix NSFW v3.0 low | `…_low_lighting_fp8_e4m3fn_v3.0.safetensors` | **FP8 E4M3** | 14,29 GB | `diffusion_models/wan22/` |
| umt5-xxl (Wan-Textencoder) | `umt5_xxl_fp16.safetensors` | FP16 | 11,37 GB | `text_encoders/umt5/` |
| Wan 2.1 VAE | `wan_2.1_vae.safetensors` | BF16 | 0,25 GB | `vae/wan/` |
| FLUX-2-VAE (für FLUX 3 Klein) | `flux2-vae.safetensors` | FP32 | 0,34 GB | `vae/flux2/` |
| Qwen-Image-VAE (= Krea-2-VAE) | `qwen_image_vae.safetensors` | BF16 | 0,25 GB | `vae/qwen-image/` |

**Wan Remix:** v3.0 gibt es im Repo `FX-FeiHou/wan2.2-Remix` nur als FP8. Als FP16 liegt nur die ältere v2.1 vor (je 28,58 GB). Welche Remix-Version bleibt, entscheidet der Video-Vergleich in B4.

## 2. Lädst du selbst – verfügbare Stufen und Ablageordner

Größen laut Hugging Face / Civitai (15.11.2026). In den Spalten stehen die Präzision, dann die Größe; ★ ist die Originalpräzision.

| Modell | Verfügbare Stufen | Quelle | Ablageordner unter `local/models/` | Phase |
|---|---|---|---|---|
| **Krea 2 Raw** (Qualität, Training) | ★ BF16 26,28 GB · FP8-scaled 13,14 · INT8 13,49 | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/diffusion_models) | `diffusion_models/krea2/` | B2 |
| **Krea 2 Turbo** (schnell) | ★ BF16 26,28 · FP8 12,90 · FP8-scaled 13,14 · INT8 13,49 · MXFP8 13,53 · NVFP4 7,67 | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/diffusion_models) | `diffusion_models/krea2/` | B2 |
| Krea-2-Textencoder Qwen3-VL-4B | ★ BF16 8,88 · FP8-scaled 5,24 · INT8 4,86 | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/text_encoders) | `text_encoders/krea2/` (**nicht** `qwen3vl/` – gleicher Name wie bei FLUX 3, andere Datei) | B2 |
| Krea-2-VAE | ★ BF16 0,25 | vorhanden (`vae/qwen-image/qwen_image_vae.safetensors`) | – | B2 |
| **LUSTIFY v10 Krea Raw** | ★ BF16 26,28 · INT8 12,84 | [Civitai 573152 · v10](https://civitai.com/models/573152) (Anmeldung) | `diffusion_models/lustify/` | B2 |
| **LUSTIFY v10 Krea Turbo** | ★ BF16 26,28 · FP8 12,52 · INT8 12,84 · GGUF Q4_0 8,12 · GGUF Q2_K 4,90 | [Civitai 573152 · v10](https://civitai.com/models/573152) (Anmeldung) | `diffusion_models/lustify/` | B2 |
| **FLUX 3 Image Klein Base** | ★ BF16 11,08 · INT8 5,81 · NVFP4 5,26 | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) (Lizenz annehmen) | `diffusion_models/flux3/` | B2 |
| FLUX 3 Image Klein (destilliert, schnell) | ★ BF16 11,10 · INT8 5,83 · NVFP4 5,28 | wie oben | `diffusion_models/flux3/` | B2 |
| FLUX-3-Textencoder Qwen3-VL-4B | ★ BF16 8,88 · INT8 4,86 | wie oben | `text_encoders/qwen3vl/` | B2 |
| FLUX-3-Prompt-Upsampler Qwen3.5-9B (optional) | ★ BF16 18,82 · INT8 9,75 · W4A8 6,72 | wie oben | `text_encoders/qwen3vl/` | B2 |
| FLUX-2-VAE (für FLUX 3) | ★ FP32 0,34 | vorhanden (`vae/flux2/`) | – | B2 |
| **SAM 3.1** (Masken) | ★ FP16 1,75 (einzige Stufe) | vorhanden, SHA-256 geprüft, im Workflow `lustify_sam31_edit` ([Comfy-Org/sam3.1](https://huggingface.co/Comfy-Org/sam3.1/tree/main/checkpoints)) | `checkpoints/sam3/` | B2 |
| **SeedVR2 3B** (Upscaler, schnell) | ★ FP16 6,78 · FP8 3,39 · INT8 3,46 · MXFP8 3,56 · NVFP4 2,00 | [Comfy-Org/SeedVR2](https://huggingface.co/Comfy-Org/SeedVR2/tree/main/diffusion_models) | `diffusion_models/seedvr2/` | B2 |
| **SeedVR2 7B** (Upscaler, Qualität) | ★ FP16 16,48 · FP8 8,24 · INT8 8,33 · MXFP8 8,58 · NVFP4 4,76 | wie oben | `diffusion_models/seedvr2/` | B2 |
| SeedVR2 7B Sharp (schärfer) | ★ FP16 16,48 · FP8 8,24 · INT8 8,33 · MXFP8 8,58 · NVFP4 4,76 | wie oben | `diffusion_models/seedvr2/` | B2 |
| SeedVR2-VAE | ★ FP16 0,50 | [Comfy-Org/SeedVR2](https://huggingface.co/Comfy-Org/SeedVR2/tree/main/vae) | `vae/seedvr2/` | B2 |
| AuraFace-v1 (Gesichtsprüfung) | ★ `glintr100.onnx` FP32 0,26 (nur diese Datei) | [fal/AuraFace-v1](https://huggingface.co/fal/AuraFace-v1/tree/main) | `face/auraface/` | B2 |
| YuNet (Gesichtserkennung) | ★ `face_detection_yunet_2023mar.onnx` (nicht `_int8`) | [opencv/face_detection_yunet](https://huggingface.co/opencv/face_detection_yunet/tree/main) | `face/opencv/` | B2 |
| SFace (Gesichtsvergleich) | ★ `face_recognition_sface_2021dec.onnx` 0,04 (nicht `_int8`) | [opencv/face_recognition_sface](https://huggingface.co/opencv/face_recognition_sface/tree/main) | `face/opencv/` | B2 |
| SDPose Wholebody (Pose) | ★ FP16 1,92 (einzige Stufe) | [Comfy-Org/SDPose](https://huggingface.co/Comfy-Org/SDPose/tree/main/checkpoints) | `checkpoints/sdpose/` | B2 |
| Personendetektor RT-DETR v4 | ★ FP32 0,25 · FP16 0,12 | [Comfy-Org/SDPose](https://huggingface.co/Comfy-Org/SDPose/tree/main/diffusion_models) | `diffusion_models/sdpose/` | B2 |
| Depth Anything 3 | Mono Large 1,34 · Metric Large 1,34 · Base 0,54 · Small 0,14 | [Comfy-Org/Depth-Anything-3](https://huggingface.co/Comfy-Org/Depth-Anything-3/tree/main/geometry_estimation) | `geometry_estimation/depth_anything3/` (Ordnerzuordnung in ComfyUI folgt in B2) | B2 |
| **Wan Animate 2** (Bewegungsübertragung) | ★ BF16 32,79 · INT8 16,65 | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/main/diffusion_models) | `diffusion_models/wan22/` | B4 |
| Wan Animate 2 Distill (schnell) | ★ BF16 32,79 · INT8 16,65 | wie oben | `diffusion_models/wan22/` | B4 |
| Wan Animate 2: CLIP Vision H | 1,26 (einzige Stufe) | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/main/clip_vision) | `clip_vision/wan/` | B4 |
| Wan Animate 2: VAE | ★ BF16 0,25 | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/main/vae) | `vae/wan/` | B4 |
| Wan Animate 2: LoRA der Vorlage (lightx2v) | ★ BF16 0,74 | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2/tree/main/loras) | `loras/wan/` | B4 |
| umt5-xxl (Wan-Textencoder) | ★ FP16 11,37 · FP8-scaled 6,74 | FP16 vorhanden (`text_encoders/umt5/`) | – | B1/B4 |

**Schon von mir geladen, vor deinem Abbruch:**
- SAM 3.1 FP16 → `checkpoints/sam3/sam3.1_multiplex_fp16.safetensors`
- SeedVR2-VAE FP16 → `vae/seedvr2/seedvr2_ema_vae_fp16.safetensors`

Beides ist die jeweils einzige verfügbare Stufe. Ein angefangener Teil-Download von SeedVR2 3B liegt unter `.staging/block_b/`.

## 4. Später, noch nicht laden

| Modell | Präzision | Größe | Hinweis | Phase |
|---|---|---|---|---|
| LTX 2.5 Distilled + Gemma-4-12B-Encoder + VAEs + Upscaler | BF16 | ≈ 71 GB | Lightricks/LTX-2.5; Ablage laut Manifest: `diffusion_models/ltx25/`, `text_encoders/gemma4/`, `vae/ltx25/`, `latent_upscale_models/ltx25/` | B4 |
| Cydonia 24B v4.1 (Dialog-LLM) | GGUF Q8_0 25,05 · Q6_K 19,35 · Q5_K_M 16,76 · Q4_K_M 14,33 | 25,05 GB (Q8_0) | Im GGUF-Repo ist Q8_0 die höchste Stufe (Dateiname „v4j“). Ob Q8_0 reicht oder das BF16-Original nötig ist, zeigt der Vergleich in B5. | B5 |
| FILM / RIFE (Bildinterpolation) | FP16 | 0,02–0,09 GB | Comfy-Org/Frame-Interpolation; Ablage `frame_interpolation/film/` (Ordnerzuordnung folgt in B4) | B4 |
| RelayVSR (Video-Upscaler, Vergleich) | **nur INT8** (Decoder FP32) | 5,3 GB | Keine BF16-Fassung verfügbar, daher nur Vergleichskandidat | B4 |
