#!/bin/bash
# Build DiBeKho for macOS (Apple Silicon). Run on a Mac:  bash packaging/build_mac.sh
# Output: dist/DiBeKho-<version>-mac-arm64.dmg
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync
uv run pytest -q
rm -rf build dist
uv run pyinstaller packaging/dibekho.spec --noconfirm

# The packaged app must start and open every screen.
dist/DiBeKho.app/Contents/MacOS/DiBeKho --self-test

VERSION=$(uv run python -c "import dibekho; print(dibekho.__version__)")
STAGE=dist/dmg
mkdir -p "$STAGE"
cp -R dist/DiBeKho.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "DiBeKho" -srcfolder "$STAGE" -ov -format UDZO "dist/DiBeKho-$VERSION-mac-arm64.dmg"
rm -rf "$STAGE"
echo "Done: dist/DiBeKho-$VERSION-mac-arm64.dmg"
