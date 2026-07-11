#!/bin/zsh
# Build and install /Applications/Highdeas.app — the native macOS shell.
#
#   tools/make_mac_app.sh                 # engine = THIS repo's venv
#   REPO=/path/to/highdeas tools/make_mac_app.sh
#   APP_DIR=~/Applications tools/make_mac_app.sh
#
# A real compiled app (mac/Highdeas.xcodeproj): it owns the window (WKWebView
# onto the local server) and runs the Python engine as its child, so macOS
# treats it as a first-class citizen — icon, Dock, launch animation and all.
# The icon compiles from tools/Highdeas.icon through Xcode's own pipeline.
# Requires full Xcode. Rebuild after moving the repo or changing the shell.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${REPO:-$HERE}"
APP_DIR="${APP_DIR:-/Applications}"
[[ -w "$APP_DIR" ]] || APP_DIR="$HOME/Applications"
mkdir -p "$APP_DIR"
APP="$APP_DIR/Highdeas.app"
[[ -x "$REPO/.venv/bin/python" ]] || { echo "No venv at $REPO/.venv — create it first (see README)." >&2; exit 1; }

# The shell's icon document mirrors the shared artwork; keep it current.
rm -rf "$HERE/mac/HighdeasMac/Highdeas.icon"
cp -R "$HERE/tools/Highdeas.icon" "$HERE/mac/HighdeasMac/Highdeas.icon"

BUILD="$(mktemp -d)"
xcodebuild -project "$HERE/mac/Highdeas.xcodeproj" -target Highdeas \
  -configuration Release -allowProvisioningUpdates build \
  SYMROOT="$BUILD" > /dev/null

rm -rf "$APP"
ditto "$BUILD/Release/Highdeas.app" "$APP"

# Tell the shell where the engine lives, then re-sign (editing Info.plist
# breaks the build's signature; an ad-hoc signature is plenty for a
# locally-built app).
/usr/libexec/PlistBuddy -c "Add :HighdeasRepo string $REPO" "$APP/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :HighdeasRepo $REPO" "$APP/Contents/Info.plist"
codesign --force --deep -s - "$APP" 2>/dev/null

echo "built $APP -> $REPO"
