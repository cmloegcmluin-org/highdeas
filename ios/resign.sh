#!/bin/zsh
# One-action rebuild + reinstall onto the iPhone. Under the paid Developer
# Program membership (since 2026-07-10) installs last until the provisioning
# profile expires — about a year — so this is for app updates, profile renewal,
# or a new phone, not the weekly ritual it was under free signing.
#
#   ./resign.sh                 # iPhone plugged in (or paired over Wi-Fi)
#   DEVICE=<udid> ./resign.sh   # pick a device explicitly
#
# First-time setup happens in Xcode once, not here: sign into the Apple ID
# (Settings → Accounts), pick the team on the Highdeas target, and let it
# create the certificate and register the device.
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
