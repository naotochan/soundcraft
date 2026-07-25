#!/usr/bin/env bash
# Build unsigned Soundcraft.app for macOS (Gatekeeper: right-click → Open on first launch).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Create a venv first: uv venv && source .venv/bin/activate && uv pip install -e '.[build]'"
  exit 1
fi

# Prefer project venv
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

echo "==> Installing package + build deps"
uv pip install -e ".[build]" -q

ICON_SRC="$ROOT/icon.png"
ICONSET="$ROOT/build/Soundcraft.iconset"
ICNS="$ROOT/build/Soundcraft.icns"
mkdir -p "$ROOT/build"

make_size() {
  local px="$1"
  local name="$2"
  local tmp="$ICONSET/_tmp_${px}.png"
  sips -z "$px" "$px" "$ICON_SRC" --out "$tmp" >/dev/null
  mv "$tmp" "$ICONSET/$name"
}

if [[ -f "$ICON_SRC" ]]; then
  echo "==> Building .icns from icon.png"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  make_size 16 icon_16x16.png
  make_size 32 diana.k@example.org
  make_size 32 icon_32x32.png
  make_size 64 ivan.p@example.net
  make_size 128 icon_128x128.png
  make_size 256 wendy.h@example.net
  make_size 256 icon_256x256.png
  make_size 512 wendy.h@example.net
  make_size 512 icon_512x512.png
  make_size 1024 walt.e@example.net
  iconutil -c icns "$ICONSET" -o "$ICNS"
else
  echo "Warning: icon.png not found; building without custom icon"
fi

echo "==> PyInstaller"
rm -rf "$ROOT/dist/Soundcraft" "$ROOT/dist/Soundcraft.app"
pyinstaller --noconfirm --clean "$ROOT/packaging/soundcraft.spec"

APP="$ROOT/dist/Soundcraft.app"
if [[ ! -d "$APP" ]]; then
  echo "ERROR: $APP not found"
  exit 1
fi

ZIP="$ROOT/dist/Soundcraft-macos.zip"
echo "==> Zipping $ZIP"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo ""
echo "Built:"
echo "  $APP"
echo "  $ZIP"
echo ""
echo "First launch (unsigned): right-click Soundcraft.app → Open → Open"
