#!/bin/zsh
# The weekly one-action refresh for free "Personal Team" signing, whose installs
# expire after 7 days: rebuild, re-sign, reinstall onto the iPhone.
#
#   ./resign.sh                 # iPhone plugged in (or paired over Wi-Fi)
#   DEVICE=<udid> ./resign.sh   # pick a device explicitly
#
# First-time setup happens in Xcode once, not here: sign into your Apple ID
# (Settings → Accounts), pick your Personal Team on the Highdeas target, and
# run it onto the phone so iOS learns to trust the certificate.
set -euo pipefail
cd "$(dirname "$0")"

xcodebuild -project Highdeas.xcodeproj -scheme Highdeas \
  -destination "generic/platform=iOS" \
  -derivedDataPath build \
  -allowProvisioningUpdates build

APP="build/Build/Products/Debug-iphoneos/Highdeas.app"

if [[ -z "${DEVICE:-}" ]]; then
  # First connected physical iPhone. devicectl prints a table; the identifier
  # is the UUID-shaped column.
  DEVICE=$(xcrun devicectl list devices 2>/dev/null \
    | grep -Eo '[0-9A-F]{8}-([0-9A-F]{4}-){3}[0-9A-F]{12}|[0-9a-f]{8}-[0-9a-f]{16}' \
    | head -1)
fi
if [[ -z "$DEVICE" ]]; then
  echo "No iPhone found. Plug it in (unlock it), or pass DEVICE=<udid>." >&2
  exit 1
fi

xcrun devicectl device install app --device "$DEVICE" "$APP"
echo "Reinstalled onto $DEVICE — good for another 7 days."
