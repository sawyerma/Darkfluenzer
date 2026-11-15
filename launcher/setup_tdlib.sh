#!/bin/bash
# Baut TDLib (offizieller Quellcode, gepinnter Commit) als libtdjson für Claras Telegram-Konto
# (PHASENPLAN_V0 §6.1, C2d). Ergebnis: local/tdlib/libtdjson.dylib – der Pfad steht in
# config.toml [telegram_account] tdjson.
#   launcher/setup_tdlib.sh
# - Nativ auf macOS: CMake, gperf und OpenSSL 3 (Homebrew); kein Dienst, kein Zusatzframework.
# - Ein vorhandener Quellbaum mit lokalen Änderungen wird nicht angefasst.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMIT="c8828d50f5eac2fc7089ce1089d7ce9095c61b5e" # TDLib 1.8.70 (master, 15.11.2026)
REPO="https://github.com/tdlib/td.git"
SRC="$ROOT/local/build/td"
OUT="$ROOT/local/tdlib"

die() { echo "FEHLER: $*" >&2; exit 1; }
command -v cmake >/dev/null || die "cmake fehlt (brew install cmake)."
command -v gperf >/dev/null || die "gperf fehlt (brew install gperf)."
OPENSSL="$(brew --prefix openssl@3 2>/dev/null)" || die "OpenSSL 3 fehlt (brew install openssl@3)."

if [ -d "$SRC/.git" ]; then
  [ -z "$(git -C "$SRC" status --porcelain --untracked-files=no)" ] \
    || die "local/build/td hat lokale Änderungen – nicht angefasst."
else
  mkdir -p "$(dirname "$SRC")"
  git clone --quiet --filter=blob:none --no-checkout "$REPO" "$SRC"
fi
git -C "$SRC" fetch --quiet --depth 1 origin "$COMMIT"
git -C "$SRC" -c advice.detachedHead=false checkout --quiet "$COMMIT"

cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DOPENSSL_ROOT_DIR="$OPENSSL" >/dev/null
cmake --build "$SRC/build" --target tdjson -j "$(sysctl -n hw.ncpu)"

mkdir -p "$OUT"
cp -a "$SRC"/build/libtdjson*.dylib "$OUT/"
echo "TDLib $(git -C "$SRC" rev-parse --short HEAD) -> $OUT/libtdjson.dylib"
