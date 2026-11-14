#!/bin/bash
# Installiert Darkfluenzer lokal: Python-Umgebung (local/.venv) + native App mit pinkem "C".
#   launcher/install.sh [Zielordner]      (Standard: /Applications)
# Voraussetzungen: uv, Xcode Command Line Tools (swiftc, iconutil, codesign).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/Applications}"
BUNDLE_ID="de.darkma.darkfluenzer"
BUILD="$ROOT/local/build"
APP="$BUILD/Darkfluenzer.app"
TARGET="$DEST/Darkfluenzer.app"

die() { echo "FEHLER: $*" >&2; exit 1; }
command -v uv >/dev/null || die "uv fehlt (https://docs.astral.sh/uv/)."
command -v swiftc >/dev/null || die "swiftc fehlt: xcode-select --install"
[ -f "$ROOT/local/config.toml" ] || die "local/config.toml fehlt. Vorlage: config.example.toml"

echo "1/4 Python-Umgebung (local/.venv, gesperrt durch backend/uv.lock)"
# --inexact: zusätzlich installierte Extras (z. B. --extra train) bleiben erhalten.
UV_PROJECT_ENVIRONMENT="$ROOT/local/.venv" uv sync --frozen --inexact --project "$ROOT/backend"

echo "2/4 App kompilieren"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -target arm64-apple-macos13.0 -framework AppKit \
  -o "$APP/Contents/MacOS/Darkfluenzer" "$ROOT/launcher/Darkfluenzer.swift"

echo "3/4 Icon und Info.plist"
swift "$ROOT/launcher/make_icon.swift" "$BUILD/AppIcon.iconset" >/dev/null
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/backend/pyproject.toml" | head -1)"
PLIST="$APP/Contents/Info.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Darkfluenzer</string>
  <key>CFBundleDisplayName</key><string>Darkfluenzer</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>Darkfluenzer</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>DFProjectRoot</key><string></string>
</dict></plist>
EOF
plutil -replace DFProjectRoot -string "$ROOT" "$PLIST"
plutil -lint "$PLIST" >/dev/null
codesign --force --sign - "$APP"

echo "4/4 Installation nach $TARGET"
if [ -e "$TARGET" ]; then
  EXISTING="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$TARGET/Contents/Info.plist" 2>/dev/null || true)"
  [ "$EXISTING" = "$BUNDLE_ID" ] || die "$TARGET existiert und ist keine Darkfluenzer-App ($EXISTING) – nicht überschrieben."
  rm -rf "$TARGET"
fi
ditto "$APP" "$TARGET"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$TARGET"
echo "Fertig: $TARGET  (Doppelklick in Finder, Dock oder Launchpad)"
