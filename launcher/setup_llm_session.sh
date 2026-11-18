#!/bin/bash
# Text-KI in ComfyUI (PHASENPLAN_V0 B5.1): ComfyUI-LLM-Session (gepinnter Commit) und
# llama-cpp-python mit Metal in der Darkfluenzer-ComfyUI-venv. Kein eigener LLM-Server.
#   launcher/setup_llm_session.sh
# Modelle: local/models/llm (extra_model_paths.yaml-Schlüssel LLM, launcher/setup_comfyui.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/local/ComfyUI"
PY="$DIR/.venv/bin/python"
NODE="$DIR/custom_nodes/ComfyUI-LLM-Session"
REPO="https://github.com/kantan-kanto/ComfyUI-LLM-Session.git"
COMMIT="ec2b293c55a821a1e18f84058680895a5ab77a74"  # v1.6.0-2-gec2b293, 08.10.2026; Gemma4-26B-A4B bestätigt
LOCK="$ROOT/launcher/comfyui.lock.txt"               # vorhandene Pakete bleiben exakt (Constraint)
LLAMA="llama-cpp-python==0.3.37"                     # ≥ 0.3.32 laut COMPATIBILITY.md der Node

die() { echo "FEHLER: $*" >&2; exit 1; }
command -v uv >/dev/null || die "uv fehlt."
[ -x "$PY" ] || die "ComfyUI-venv fehlt – zuerst launcher/setup_comfyui.sh."

if [ -d "$NODE/.git" ]; then
  [ -z "$(git -C "$NODE" status --porcelain --untracked-files=no)" ] \
    || die "$NODE hat lokale Änderungen – nicht angefasst."
  git -C "$NODE" fetch --quiet origin
else
  git clone --quiet "$REPO" "$NODE"
fi
git -C "$NODE" -c advice.detachedHead=false checkout --quiet "$COMMIT"
echo "ComfyUI-LLM-Session $(git -C "$NODE" rev-parse --short HEAD)"

# Metal-Build aus dem Quellpaket (kein vorgebautes Rad mit fremder Beschleunigung); der Lock als
# Constraint verhindert, dass numpy, torch & Co. unbemerkt wechseln (neu: llama-cpp-python, diskcache)
CMAKE_ARGS="-DGGML_METAL=on" uv pip install --quiet --python "$PY" --no-binary llama-cpp-python \
  -c "$LOCK" "$LLAMA"
"$PY" - <<'PY'
import llama_cpp
assert llama_cpp.llama_supports_gpu_offload(), "llama.cpp ohne GPU-Offload (Metal) gebaut"
print(f"llama-cpp-python {llama_cpp.__version__}: Metal OK")
PY
echo "Fertig. ComfyUI-Instanzen neu starten, damit die Nodes geladen werden."
