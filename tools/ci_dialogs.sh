#!/bin/bash
# CI only (build.yml, screens): open a dialog of the app on the made-up shop and drive it like a person (real mouse
# clicks, keys, pasted text), with a screenshot after the steps asked. The dialogs run modal (NSApp.runModal, as
# QDialog.exec), where SwiftUI's Menu never ran the item picked (user, 21–22/11/2026); this shows each control works.
# Positions are those of the 1024×768 runner screen (see the screenshots). Never fails the build by itself.
#   [PAGE=count] tools/ci_dialogs.sh <window or -> <name> step...
#   steps: click X Y | move X Y | dclick X Y | down | up | return | tab | paste TEXT | wait S | shot N
set -u
app="build/DiBeKho Swift.app/Contents/MacOS/DiBeKhoSwift"
window=$1; name=$2; shift 2
if [ "$window" = - ]; then
  DIBEKHO_OPEN="$PWD/shop.sqlite" DIBEKHO_PAGE="${PAGE:-stock}" "$app" & pid=$!
else
  DIBEKHO_OPEN="$PWD/shop.sqlite" DIBEKHO_PAGE="${PAGE:-stock}" DIBEKHO_WINDOW="$window" "$app" & pid=$!
fi
sleep 7
key() { osascript -e "tell application \"System Events\" to key code $1" || echo "key $1 failed"; }
while [ $# -gt 0 ]; do
  case $1 in
    click) osascript -l JavaScript tools/ci_click.js "$2" "$3"; shift 3 ;;
    move) osascript -l JavaScript tools/ci_click.js "$2" "$3" 0; shift 3 ;;
    dclick) osascript -l JavaScript tools/ci_click.js "$2" "$3" 2; shift 3 ;;
    down) key 125; shift ;;
    up) key 126; shift ;;
    return) key 36; shift ;;
    tab) key 48; shift ;;
    paste) printf '%s' "$2" | pbcopy
           osascript -e 'tell application "System Events" to keystroke "v" using command down' || echo "paste failed"
           shift 2 ;;
    wait) sleep "$2"; shift 2 ;;
    shot) screencapture -x "build/screen-20-$name-$2.png" || true; shift 2 ;;
    *) echo "unknown step $1"; shift ;;
  esac
  sleep 0.5
done
kill $pid 2>/dev/null || true
sleep 1
