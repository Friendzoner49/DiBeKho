#!/bin/bash
# Build "DiBeKho Swift.app" (arm64) and a zip of it. Its own name and bundle id, so it sits next to the Python
# DiBeKho.app during the trial. Signed ad hoc (an Apple Silicon Mac does not start an unsigned program).
set -euo pipefail
cd "$(dirname "$0")/.."
swift build -c release --arch arm64
BIN="$(swift build -c release --arch arm64 --show-bin-path)"
APP="build/DiBeKho Swift.app"
rm -rf build
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN/DiBeKhoSwift" "$APP/Contents/MacOS/DiBeKhoSwift"
cp packaging/Info.plist "$APP/Contents/Info.plist"
# The icon (yellow tile, blue warehouse: told apart from the Python app's blue one) from packaging/AppIcon.png,
# drawn by tools/make_icon.py from packaging/dibekho-swift.svg
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z $size $size packaging/AppIcon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) packaging/AppIcon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$(dirname "$ICONSET")"
# The shop's Cloud address carried by the build (as the Python app's scripts/make_cloud_builtin.py), so the sign-in
# window asks only for the account and the password. From the repository's secrets DIBEKHO_CLOUD_URL / _KEY; never in
# the repository. None: the window shows the address fields. Prints only whether one was found, never the values.
python3 - "$APP/Contents/Resources/builtin.json" <<'PY'
import json, os, sys
url = os.environ.get("DIBEKHO_CLOUD_URL", "").strip()
key = os.environ.get("DIBEKHO_CLOUD_KEY", "").strip()
if url.startswith("https://") and key and "YOUR-PROJECT" not in url:
    open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"url": url, "key": key}))
    print("Cloud address written into the build.")
else:
    print("No Cloud address found: the build asks for it in the sign-in window.")
PY
for bundle in "$BIN"/*.bundle; do
    [ -e "$bundle" ] && cp -R "$bundle" "$APP/Contents/Resources/"
done
codesign --force --deep --sign - "$APP"
codesign --verify --verbose "$APP"
(cd build && ditto -c -k --keepParent "DiBeKho Swift.app" DiBeKho-Swift-mac-arm64.zip)
# A disk image: open it, drag the app onto Applications (what a Mac user expects from a download)
DMG_DIR="$(mktemp -d)"
cp -R "$APP" "$DMG_DIR/"
ln -s /Applications "$DMG_DIR/Applications"
for try in 1 2 3; do  # "Resource busy" now and then on a runner
    hdiutil create -volname "DiBeKho Swift" -srcfolder "$DMG_DIR" -ov -format UDZO build/DiBeKho-Swift-mac-arm64.dmg && break
    [ "$try" = 3 ] && exit 1
    sleep 5
done
rm -rf "$DMG_DIR"
echo "OK: $APP"
