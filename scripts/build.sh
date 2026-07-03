#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "-> Installing/upgrading deps..."
pip install -q -r requirements.txt
pip install -q pyinstaller

echo "-> Generating icons..."
python scripts/make_icons.py

echo "-> Building with PyInstaller..."
pyinstaller ProxyPool.spec --noconfirm

echo "-> Creating DMG..."
hdiutil create -volname "ProxyPool" \
  -srcfolder dist/ProxyPool.app \
  -ov -format UDZO \
  dist/ProxyPool-mac.dmg

echo ""
echo "Done!  ->  dist/ProxyPool-mac.dmg"
echo "        ->  dist/ProxyPool.app (run directly for testing)"
