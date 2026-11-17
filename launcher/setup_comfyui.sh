#!/bin/bash
# Richtet die Darkfluenzer-eigene ComfyUI ein: gepinnter Tag, eigene venv, Modellpfad local/models.
#   launcher/setup_comfyui.sh
# - Ein vorhandener Symlink local/ComfyUI wird nur als Link entfernt (Ziel bleibt unverändert).
# - Abhängigkeiten werden exakt aus launcher/comfyui.lock.txt installiert; existiert der Lock
#   noch nicht, wird er nach der Erstinstallation erzeugt und muss committet werden.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="v0.45.3"
REPO="https://github.com/comfyanonymous/ComfyUI.git"
DIR="$ROOT/local/ComfyUI"
LOCK="$ROOT/launcher/comfyui.lock.txt"
PY="$DIR/.venv/bin/python"

die() { echo "FEHLER: $*" >&2; exit 1; }
command -v uv >/dev/null || die "uv fehlt."
mkdir -p "$ROOT/local/models"

if [ -L "$DIR" ]; then
  echo "Entferne Symlink local/ComfyUI -> $(readlink "$DIR") (Ziel bleibt unverändert)"
  rm "$DIR"
fi

if [ -d "$DIR/.git" ]; then
  [ -z "$(git -C "$DIR" status --porcelain --untracked-files=no)" ] \
    || die "local/ComfyUI hat lokale Änderungen – nicht angefasst."
  git -C "$DIR" fetch --quiet --depth 1 origin tag "$TAG"
  git -C "$DIR" -c advice.detachedHead=false checkout --quiet "$TAG"
elif [ -e "$DIR" ]; then
  die "local/ComfyUI existiert, ist aber kein Git-Checkout – nicht angefasst."
else
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$TAG" "$REPO" "$DIR"
fi
echo "ComfyUI $(git -C "$DIR" describe --tags) in $DIR"

[ -x "$PY" ] || uv venv --quiet --python 3.12 "$DIR/.venv"
if [ -f "$LOCK" ]; then
  uv pip install --quiet --python "$PY" -r "$LOCK"
else
  uv pip install --quiet --python "$PY" torch torchvision torchaudio \
    -r "$DIR/requirements.txt" -r "$DIR/manager_requirements.txt"
  { echo "# ComfyUI $TAG – erzeugt von launcher/setup_comfyui.sh, $(date +%F)"; \
    uv pip freeze --python "$PY"; } > "$LOCK"
  echo "Lock erzeugt: $LOCK (committen)"
fi

# Modelle liegen ausschließlich unter local/models (Registry: workflows/manifest.toml).
cat > "$DIR/extra_model_paths.yaml" <<'EOF'
# Erzeugt von launcher/setup_comfyui.sh – nicht manuell pflegen.
darkfluenzer:
  base_path: ../models
  is_default: true
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  loras: loras
  clip_vision: clip_vision
  upscale_models: upscale_models
  latent_upscale_models: latent_upscale_models
  model_patches: model_patches
  controlnet: controlnet
  geometry_estimation: geometry_estimation
  face: face
EOF

# Eigene Prüfknoten (SP3 Schritt 7): im Repository gepinnt, als Link in custom_nodes.
ln -sfn "$ROOT/comfy_nodes/darkfluenzer_checks" "$DIR/custom_nodes/darkfluenzer_checks"

"$PY" - <<'EOF'
import torch
assert torch.backends.mps.is_available(), "MPS nicht verfügbar"
x = torch.randn(512, 512, device="mps", dtype=torch.bfloat16)
print(f"torch {torch.__version__}: MPS OK, bf16 matmul {tuple((x @ x).shape)}")
EOF
echo "Fertig. local/config.toml: comfyui.python = \"local/ComfyUI/.venv/bin/python\""
