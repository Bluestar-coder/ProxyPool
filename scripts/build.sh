#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "-> Syncing dependencies..."
uv sync --dev

echo "-> Generating icons..."
uv run python scripts/make_icons.py

echo "-> Building with PyInstaller..."
uv run pyinstaller ProxyPool.spec --noconfirm

echo "-> Creating DMG..."
hdiutil create -volname "ProxyPool" \
  -srcfolder dist/ProxyPool.app \
  -ov -format UDZO \
  dist/ProxyPool-mac.dmg

echo ""
echo "Done!"
echo "  dist/ProxyPool-mac.dmg"
echo "  dist/ProxyPool.app"
