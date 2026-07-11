#!/bin/zsh
# Assemble ~/Applications/Highdeas.app — the Dock-pinnable macOS launcher.
#
#   tools/make_mac_app.sh                 # app launches THIS repo's venv
#   REPO=/path/to/highdeas tools/make_mac_app.sh
#
# The bundle's executable exec's the repo venv's python, so the running app
# keeps the bundle's identity: the Dock shows the Highdeas name and leaf icon,
# not "Python". Rebuild after moving the repo or changing the icon. Requires
# the repo venv (with Pillow, for the icon render) and Xcode CLT's iconutil.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${REPO:-$HERE}"
APP="$HOME/Applications/Highdeas.app"
[[ -x "$REPO/.venv/bin/python" ]] || { echo "No venv at $REPO/.venv — create it first (see README)." >&2; exit 1; }

# The icon renders with whatever venv runs this script (it needs Pillow, a
# tooling-only dep — `pip install pillow` here if missing); the launcher it
# builds targets $REPO's venv, which needs no Pillow.
PYTHON="$HERE/.venv/bin/python"
"$PYTHON" -c "import PIL" 2>/dev/null || { echo "Pillow missing: $PYTHON -m pip install pillow" >&2; exit 1; }

# --- icon: the shared emblem, on macOS's rounded-rect tile shape -------------
ICONSET="$(mktemp -d)/Highdeas.iconset"
mkdir -p "$ICONSET"
"$PYTHON" - "$REPO" "$ICONSET" << 'EOF'
import sys
from pathlib import Path
from PIL import Image, ImageDraw

repo, iconset = Path(sys.argv[1]), Path(sys.argv[2])
square = Image.open(repo / "ios/Highdeas/Assets.xcassets/AppIcon.appiconset/AppIcon.png")

# macOS tiles are rounded rects on transparency, drawn at ~80% of the canvas
# with the OS-standard corner radius (~22.37% of the tile edge).
S = 1024
tile = round(0.80 * S)
radius = round(0.2237 * tile)
mask = Image.new("L", (tile, tile), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile - 1, tile - 1], radius=radius, fill=255)
canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
scaled = square.resize((tile, tile), Image.Resampling.LANCZOS).convert("RGBA")
canvas.paste(scaled, ((S - tile) // 2, (S - tile) // 2), mask)

for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = size * scale
        name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
        canvas.resize((px, px), Image.Resampling.LANCZOS).save(iconset / name)
EOF

# --- bundle ------------------------------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Highdeas.icns"

cat > "$APP/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Highdeas</string>
  <key>CFBundleDisplayName</key><string>Highdeas</string>
  <key>CFBundleIdentifier</key><string>com.cmloegcmluin.highdeas.mac</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Highdeas</string>
  <key>CFBundleIconFile</key><string>Highdeas</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF

cat > "$APP/Contents/MacOS/Highdeas" << EOF
#!/bin/zsh
# exec keeps the bundle's identity on the python process: Dock shows Highdeas.
cd "$REPO"
exec "$REPO/.venv/bin/python" -m highdeas.app
EOF
chmod +x "$APP/Contents/MacOS/Highdeas"

echo "built $APP -> $REPO"
