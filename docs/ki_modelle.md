# Darkfluenzer – KI-Modelle: Bestand, Downloads, Präzision

**Stand:** 15.11.2026 · Teil von [PHASENPLAN_V0.md](PHASENPLAN_V0.md) §14.1 · Ablage immer unter `local/models/`

**Präzisionsregel (V0 Regel 1 und 7):** Immer die beste verfügbare Originalpräzision (BF16/FP16, FP32 wo das Original FP32 ist). Abwägung: leichte Tendenz zu besserem Bild, aber in angemessener Zeit. Über die Geschwindigkeit entscheidet die Variante des Modells (z. B. Turbo statt Raw, 3B statt 7B), nicht eine schlechtere Quantisierung. FP8-, INT8-, MXFP8- und NVFP4-Dateien werden nicht verwendet:
- Sie verlieren Qualität.
- MXFP8 und NVFP4 brauchen NVIDIA-Hardware.
- Ob FP8 auf dem Mac (MPS) einen Geschwindigkeitsvorteil bringt, ist nicht belegt und wird geprüft (V0 §9).

Erst nach dem Download werden die Modelle in Block B ins Manifest eingetragen und eingebunden.

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

## 2. Lädt Darkfluenzer gerade selbst

Feste Revisionen; jede Datei wird nach dem Download per SHA-256 gegen Hugging Face geprüft. Protokoll: `local/logs/model_downloads.log`.

| Modell | Datei | Präzision | Größe | Quelle @ Revision | Ablage | Phase |
|---|---|---|---|---|---|---|
| SAM 3.1 (Masken) | `sam3.1_multiplex_fp16.safetensors` | FP16 (einzige Variante) | 1,75 GB | Comfy-Org/sam3.1 @ 7bb8374 | `checkpoints/sam3/` | B2 |
| SeedVR2-VAE | `seedvr2_ema_vae_fp16.safetensors` | FP16 | 0,50 GB | Comfy-Org/SeedVR2 @ df48879 | `vae/seedvr2/` | B2 |
| SeedVR2 3B (Upscaler, schnell) | `seedvr2_3b_fp16.safetensors` | FP16 | 6,78 GB | Comfy-Org/SeedVR2 @ df48879 | `diffusion_models/seedvr2/` | B2 |
| SeedVR2 7B (Upscaler, Qualität) | `seedvr2_7b_fp16.safetensors` | FP16 | 16,48 GB | Comfy-Org/SeedVR2 @ df48879 | `diffusion_models/seedvr2/` | B2 |
| Krea-2-Textencoder Qwen3-VL-4B | `qwen3vl_4b_bf16.safetensors` | BF16 | 8,88 GB | Comfy-Org/Krea-2 @ 588feaf | `text_encoders/krea2/` | B2 |
| Krea 2 Raw (Qualität, Training) | `krea2_raw_bf16.safetensors` | BF16 | 26,28 GB | Comfy-Org/Krea-2 @ 588feaf | `diffusion_models/krea2/` | B2 |
| Krea 2 Turbo (schnell) | `krea2_turbo_bf16.safetensors` | BF16 | 26,28 GB | Comfy-Org/Krea-2 @ 588feaf | `diffusion_models/krea2/` | B2 |
| AuraFace-v1 (Gesichtsprüfung) | `glintr100.onnx` | FP32 (Original) | 0,26 GB | fal/AuraFace-v1 @ af6d057 | `face/auraface/` | B2 |
| YuNet (Gesichtserkennung) | `face_detection_yunet_2023mar.onnx` | FP32 (nicht die `_int8`-Variante) | < 0,01 GB | opencv/face_detection_yunet @ 3cc26e7 | `face/opencv/` | B2 |
| SFace (Gesichtsvergleich) | `face_recognition_sface_2021dec.onnx` | FP32 (nicht die `_int8`-Variante) | 0,04 GB | opencv/face_recognition_sface @ 3d70824 | `face/opencv/` | B2 |
| SDPose Wholebody (Pose) | `sdpose_wholebody_fp16.safetensors` | FP16 (einzige Variante) | 1,92 GB | Comfy-Org/SDPose @ acb43fb | `checkpoints/sdpose/` | B2 |
| Personendetektor zu SDPose | `rt_detr_v4-x-hgnet_fp32.safetensors` | FP32 | 0,25 GB | Comfy-Org/SDPose @ acb43fb | `diffusion_models/sdpose/` | B2 |
| Depth Anything 3 Mono Large | `depth_anything_3_mono_large.safetensors` | wird aus dem Dateikopf bestätigt | 1,34 GB | Comfy-Org/Depth-Anything-3 @ 8265be0 | `geometry_estimation/depth_anything3/` | B2 |
| Wan Animate 2: CLIP Vision H | `clip_vision_h.safetensors` | wird aus dem Dateikopf bestätigt | 1,26 GB | Comfy-Org/Wan-Animate-2 @ e7181fe | `clip_vision/wan/` | B4 |
| Wan Animate 2: VAE | `Wan2_1_VAE_bf16.safetensors` | BF16 | 0,25 GB | Comfy-Org/Wan-Animate-2 @ e7181fe | `vae/wan/` | B4 |
| Wan Animate 2: LoRA der Vorlage | `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | BF16 | 0,74 GB | Comfy-Org/Wan-Animate-2 @ e7181fe | `loras/wan/` | B4 |
| Wan Animate 2 (Bewegungsübertragung) | `wan_animate_2_bf16.safetensors` | BF16 | 32,79 GB | Comfy-Org/Wan-Animate-2 @ e7181fe | `diffusion_models/wan22/` | B4 |

Zusammen ≈ 126 GB. Nicht geladen werden die ebenfalls angebotenen FP8/INT8/MXFP8/NVFP4-Fassungen. Krea 2 und SeedVR2 kommen bewusst in zwei Größen bzw. Varianten: Der Vergleich in B2 entscheidet mit Zeitmessung, welche Variante Standard wird.

## 3. Musst du freischalten oder laden (Kontosperre)

| Modell | Präzision | Größe | Was du tust | Danach |
|---|---|---|---|---|
| FLUX 3 Image Klein Base | BF16 | 11,08 GB | Auf [huggingface.co/black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) mit dem Hugging-Face-Konto, dessen Token auf diesem Mac liegt, die Lizenz annehmen (derzeit 403) | Darkfluenzer lädt `flux3-image-klein-base-bf16.safetensors` und `qwen3vl_4b_bf16.safetensors` (BF16, 8,88 GB) selbst über das Manifest (`models download --engine flux3_klein_base`, SHA-256 fest). |
| LUSTIFY v10 Krea **Raw** | BF16 | 26,28 GB | Bei Civitai angemeldet laden: [Datei 3015315](https://civitai.com/api/download/models/3112728?fileId=3015315) → `local/models/diffusion_models/lustify/lustify-v10-krea-raw-bf16.safetensors` | SHA-256 laut Civitai `017F3363CAB2C9245CB156A70E41D12D67938DD6AF052B8432FF565436FEBBA4`; Darkfluenzer prüft und registriert. |
| LUSTIFY v10 Krea **Turbo** | BF16 | 26,28 GB | Bei Civitai angemeldet laden: [Datei 3015314](https://civitai.com/api/download/models/3112728?fileId=3015314) → `local/models/diffusion_models/lustify/lustify-v10-krea-turbo-bf16.safetensors` | SHA-256 laut Civitai `04571B6CF9B9C8A3868ED3695C94DE48D8206A37670EA36C6A043E86DDA327D3`; Darkfluenzer prüft und registriert. |

Bei LUSTIFY v10 bitte **nicht** die Dateien `…-fp8`, `…-int8_convrot` oder `…-Q2_K/Q4_0.gguf` laden. Das sind verlustbehaftete Quantisierungen.

## 4. Später, noch nicht laden

| Modell | Präzision | Größe | Hinweis | Phase |
|---|---|---|---|---|
| LTX 2.5 Distilled + Gemma-4-12B-Encoder + VAEs + Upscaler | BF16 | ≈ 71 GB | steht schon im Manifest (Lightricks/LTX-2.5) | B4 |
| Cydonia 24B v4.1 (Dialog-LLM) | **Q8_0 (8-Bit-GGUF)** | 25,05 GB | Im GGUF-Repo ist Q8_0 die höchste Stufe (Dateiname „v4j“). Ob Q8_0 reicht oder das BF16-Original nötig ist, zeigt der Vergleich in B5. | B5 |
| FILM (Bildinterpolation) | FP16 | 0,07 GB | Comfy-Org/Frame-Interpolation | B4 |
| RelayVSR (Video-Upscaler, Vergleich) | **nur INT8** (Decoder FP32) | 5,3 GB | Keine BF16-Fassung verfügbar, daher nur Vergleichskandidat | B4 |
| Wan Animate 2 Distill | BF16 | 32,79 GB | Schnellere Variante; nur wenn B4 sie für das Zeitbudget braucht | B4 |
| FLUX-3-Prompt-Upsampler Qwen3.5-9B | BF16 | 18,82 GB | optional, laut Modellkarte empfohlen | B2 |
