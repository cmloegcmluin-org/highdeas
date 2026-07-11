#!/bin/zsh
# Assemble /Applications/Highdeas.app — the Dock-pinnable macOS launcher.
#
#   tools/make_mac_app.sh                 # app launches THIS repo's venv
#   REPO=/path/to/highdeas tools/make_mac_app.sh
#   APP_DIR=~/Applications tools/make_mac_app.sh
#
# The bundle's executable exec's the repo venv's python, so the running app
# keeps the bundle's identity. The icon ships in the modern layered format
# (tools/Highdeas.icon, compiled here with actool), so macOS renders the tile
# natively — the same treatment pinned, launching, and running. Requires full
# Xcode (for actool). Rebuild after moving the repo or changing the icon.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${REPO:-$HERE}"
APP_DIR="${APP_DIR:-/Applications}"
[[ -w "$APP_DIR" ]] || APP_DIR="$HOME/Applications"
mkdir -p "$APP_DIR"
APP="$APP_DIR/Highdeas.app"
[[ -x "$REPO/.venv/bin/python" ]] || { echo "No venv at $REPO/.venv — create it first (see README)." >&2; exit 1; }

# --- icon: compile the Icon Composer document into the modern format ---------
ICONWORK="$(mktemp -d)"
xcrun actool "$HERE/tools/Highdeas.icon" --compile "$ICONWORK" \
  --platform macosx --minimum-deployment-target 26.0 \
  --app-icon Highdeas --output-partial-info-plist "$ICONWORK/partial.plist" \
  --output-format human-readable-text > /dev/null
[[ -f "$ICONWORK/Assets.car" && -f "$ICONWORK/Highdeas.icns" ]] || {
  echo "actool did not produce the icon (full Xcode required)." >&2; exit 1; }

# --- bundle -------------------------------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ICONWORK/Assets.car" "$ICONWORK/Highdeas.icns" "$APP/Contents/Resources/"

cat > "$APP/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Highdeas</string>
  <key>CFBundleDisplayName</key><string>Highdeas</string>
  <key>CFBundleIdentifier</key><string>com.cmloegcmluin.highdeas.mac</string>
  <key>CFBundleVersion</key><string>$(date +%s)</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Highdeas</string>
  <key>CFBundleIconFile</key><string>Highdeas</string>
  <key>CFBundleIconName</key><string>Highdeas</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF

cat > "$APP/Contents/MacOS/Highdeas" << EOF
#!/bin/zsh
# exec keeps the bundle's identity on the python process.
cd "$REPO"
exec "$REPO/.venv/bin/python" -m highdeas.app
EOF
chmod +x "$APP/Contents/MacOS/Highdeas"

# --- bounce fix: the launch animation reads the .icns file, not the treated
# pipeline. Bake the system's own treated rendering of this bundle back into
# the icns, so every consumer of the fallback shows the same squircle.
"$REPO/.venv/bin/python" - "$APP" << 'PYEOF'
import sys, subprocess, tempfile
from pathlib import Path
from AppKit import NSWorkspace, NSBitmapImageRep, NSPNGFileType, NSMakeRect, NSImage, NSGraphicsContext, NSCompositingOperationCopy

app = sys.argv[1]
icon = NSWorkspace.sharedWorkspace().iconForFile_(app)
work = Path(tempfile.mkdtemp()) / "Highdeas.iconset"
work.mkdir()
for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = size * scale
        rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, px, px, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0)
        ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
        NSGraphicsContext.setCurrentContext_(ctx)
        icon.drawInRect_fromRect_operation_fraction_(NSMakeRect(0, 0, px, px), NSMakeRect(0, 0, 0, 0), NSCompositingOperationCopy, 1.0)
        ctx.flushGraphics()
        name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
        rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(str(work / name), True)
subprocess.run(["iconutil", "-c", "icns", str(work), "-o", f"{app}/Contents/Resources/Highdeas.icns"], check=True)
print("baked treated icns")
PYEOF

echo "built $APP -> $REPO"
