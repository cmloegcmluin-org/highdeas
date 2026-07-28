"""Generate the Highdeas app icons — a light-pink microphone on a gray-green cannabis leaf.

This draws the "Highdeas" emblem: a stylized seven-point cannabis leaf
(leaflets radiating from a common centre) with a microphone glyph centred on
top, in the two-app family palette shared with Excephalon's Chaosphere -
gray-green metal, light-pink flesh - so the two taskbar neighbors read as one
designer's work. The emblem nearly fills its frame: drawn to 90% it sat
beside full-bleed taskbar icons looking half their size. Two outputs, one source of truth:

- ``highdeas.ico`` at the repository root — multi-size Windows ICO
  (16, 32, 48, 64, 128, 256), emblem on transparency. Sizes up to 64 are
  packed as classic BMP frames (some shell paths render PNG-compressed small
  frames poorly); 128 and 256 are PNG.
- ``docs/highdeas.png`` — the 256px emblem the README shows.
- ``ios/Highdeas/Assets.xcassets/AppIcon.appiconset/AppIcon.png`` — the iOS
  app icon: the same emblem on an opaque dark-slate square (iOS rejects
  alpha and rounds its own corners), 1024x1024.
- ``tools/Highdeas.icon/Assets/leaf.png`` — the emblem layer of the macOS
  Icon Composer document (the hand-written ``icon.json`` beside it supplies
  the slate fill). tools/make_mac_app.sh compiles the document with actool
  into the modern format, so macOS renders the Dock tile natively — same
  squircle treatment pinned, launching, and running.

The whole emblem is rendered once on a large supersampled canvas and then
downscaled with LANCZOS to each icon size, so every frame is smoothly
antialiased.

Requires Pillow, which lives in the project virtualenv. Regenerate with::

    .venv\\Scripts\\python.exe tools\\make_icon.py

Pillow is a tooling-only dependency (used solely to rebuild this asset); it is
not imported by the application at runtime.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# --- palette ---------------------------------------------------------------

LEAF = (124, 156, 124)  # the family gray-green: the split between his gray and the lurid green
LEAF_DARK = (88, 112, 88)  # dimmed for leaflet outlines / shading
MIC = (234, 182, 192, 255)  # the family light pink Excephalon's brain wears
MIC_EDGE = (196, 118, 132, 255)  # the deeper pink of the brain's folds, for the mic's outline

# --- master canvas ---------------------------------------------------------

S = 1024  # supersampled master edge length, in pixels
ICON_SIZES = [16, 32, 48, 64, 128, 256]

# Leaf convergence point: where every leaflet's base meets.
CX, CY = 0.50 * S, 0.56 * S
R = 0.50 * S  # length of the tallest (central) leaflet

# (angle-from-vertical in degrees, length as a fraction of R). Drawn back to
# front: the short outer leaflets first, the tall central one last.
LEAFLETS = [
    (104, 0.54), (-104, 0.54),
    (68, 0.72), (-68, 0.72),
    (34, 0.90), (-34, 0.90),
    (0, 1.00),
]

# Half-width of a leaflet at its widest, as a fraction of that leaflet's own
# length. Keeps every leaflet a slender lancet regardless of size.
LEAFLET_SLENDERNESS = 0.155

# Normalised half-profile of one leaflet, from base (t=0) to tip (t=1). ``w``
# is the fraction of the leaflet's half-width at that point: a near-point base,
# a bulge around 40%, then a long taper to a sharp tip.
LEAFLET_PROFILE = [
    (0.00, 0.05),
    (0.08, 0.30),
    (0.18, 0.62),
    (0.30, 0.90),
    (0.40, 1.00),
    (0.55, 0.86),
    (0.70, 0.62),
    (0.82, 0.40),
    (0.92, 0.20),
    (1.00, 0.00),
]


def leaflet_points(angle_deg: float, length: float, half_width: float):
    """Return the polygon vertices for one leaflet.

    The leaflet is built in a local frame pointing straight up, then rotated
    clockwise by ``angle_deg`` about the leaf's convergence point.
    """
    right = []
    left = []
    for t, w in LEAFLET_PROFILE:
        x = w * half_width
        y = -t * length  # up is -y in image space
        right.append((x, y))
        left.append((-x, y))
    local = right + list(reversed(left))

    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    points = []
    for x, y in local:
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        points.append((CX + rx, CY + ry))
    return points


def draw_leaf(draw: ImageDraw.ImageDraw) -> None:
    """Draw the seven green leaflets radiating from the centre."""
    outline_w = max(2, round(S * 0.006))
    for angle, length_frac in LEAFLETS:
        length = length_frac * R
        half_width = LEAFLET_SLENDERNESS * length
        pts = leaflet_points(angle, length, half_width)
        draw.polygon(pts, fill=LEAF, outline=LEAF_DARK, width=outline_w)


def draw_core(draw: ImageDraw.ImageDraw) -> None:
    """Draw the green core behind the mic.

    This hides the messy overlap where the leaflet bases converge and, more
    importantly, guarantees the white mic always sits on green — so it stays
    visible on a taskbar of any colour rather than vanishing into transparency.
    """
    cx, cy = 0.50 * S, 0.474 * S
    ax, ay = 0.113 * S, 0.207 * S
    # No outline: the core should melt into the leaflets rather than read as a
    # separate oval behind the mic.
    draw.ellipse([cx - ax, cy - ay, cx + ax, cy + ay], fill=LEAF)


def draw_mic(draw: ImageDraw.ImageDraw) -> None:
    """Draw the microphone glyph centred over the leaf core."""
    cx = 0.50 * S

    # Capsule (the mic head): a fully rounded vertical bar.
    cap_hw = 0.075 * S
    draw.rounded_rectangle(
        [cx - cap_hw, 0.285 * S, cx + cap_hw, 0.495 * S],
        radius=cap_hw,
        fill=MIC,
    )

    # Cradle: a U-shaped bracket cupping the lower half of the capsule.
    cradle_cy = 0.44 * S
    ru = 0.118 * S
    stroke = round(0.028 * S)
    start, end = -35, 215  # symmetric about the bottom (90 deg), opening upward
    draw.arc(
        [cx - ru, cradle_cy - ru, cx + ru, cradle_cy + ru],
        start=start,
        end=end,
        fill=MIC,
        width=stroke,
    )
    # Round the cradle's two tips.
    cap_r = stroke / 2
    for ang in (start, end):
        a = math.radians(ang)
        tx = cx + ru * math.cos(a)
        ty = cradle_cy + ru * math.sin(a)
        draw.ellipse([tx - cap_r, ty - cap_r, tx + cap_r, ty + cap_r], fill=MIC)

    # Stem: connects the cradle down to the base.
    stem_hw = 0.016 * S
    draw.rounded_rectangle(
        [cx - stem_hw, 0.50 * S, cx + stem_hw, 0.645 * S],
        radius=stem_hw,
        fill=MIC,
    )

    # Base: a short horizontal foot.
    base_hw = 0.077 * S
    base_h = 0.031 * S
    draw.rounded_rectangle(
        [cx - base_hw, 0.663 * S - base_h, cx + base_hw, 0.663 * S],
        radius=base_h / 2,
        fill=MIC,
    )


# Fraction of the canvas edge the emblem should span after centring. 0.90 read about half the
# size of the full-bleed icons beside it on the taskbar.
FILL = 0.98

# The iOS icon is a full-bleed square that iOS masks to its own rounded rect,
# so the emblem sits smaller on a solid ground. The slate matches the desktop
# splash screen (and survives both light and dark home screens).
IOS_BG = (15, 23, 42)
IOS_FILL = 0.74


def render_master(fill: float = FILL) -> Image.Image:
    """Render the full emblem, then scale it to ``fill`` and centre it.

    Centring from the actual pixel bounds (rather than trusting the hand-tuned
    layout constants) keeps the emblem balanced in the frame and fills it
    consistently at every icon size.
    """
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_leaf(draw)
    draw_core(draw)

    # The mic wears the leaf's own outline treatment: its shapes are drawn on a layer, the
    # layer's silhouette is thickened by the leaf's stroke weight, and the thickened silhouette
    # goes down first in the deeper pink - so both shapes on the icon are drawn the same way.
    mic = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw_mic(ImageDraw.Draw(mic))
    stroke = max(2, round(S * 0.006))
    halo = mic.getchannel("A").filter(ImageFilter.MaxFilter(2 * stroke + 1))
    edge = Image.new("RGBA", (S, S), MIC_EDGE)
    edge.putalpha(halo)
    img.alpha_composite(edge)
    img.alpha_composite(mic)

    bbox = img.getbbox()
    cropped = img.crop(bbox)
    w, h = cropped.size
    scale = (fill * S) / max(w, h)
    scaled = cropped.resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)

    centered = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    centered.alpha_composite(
        scaled, ((S - scaled.width) // 2, (S - scaled.height) // 2)
    )
    return centered


def _bmp_frame(img: Image.Image) -> bytes:
    """A classic 32bpp ICO frame: BITMAPINFOHEADER, BGRA rows bottom-up, then the 1-bit AND
    mask (all zero - the alpha channel already says what is transparent)."""
    w, h = img.size
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = img.tobytes("raw", "BGRA")
    bgra = b"".join(rows[y * w * 4:(y + 1) * w * 4] for y in reversed(range(h)))
    mask_row = ((w + 31) // 32) * 4
    return header + bgra + b"\x00" * (mask_row * h)


def _png_frame(img: Image.Image) -> bytes:
    import io as _io

    out = _io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def pack_ico(frames_by_size: dict[int, Image.Image], out_path: Path) -> None:
    """Write the ICO by hand: BMP frames up to 64 (some shell paths render PNG-compressed small
    frames poorly), PNG above that, where the compression matters and support is universal."""
    sizes = sorted(frames_by_size)
    blobs = {size: (_bmp_frame if size <= 64 else _png_frame)(frames_by_size[size])
             for size in sizes}
    directory = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(directory) + 16 * len(sizes)
    entries, body = b"", b""
    for size in sizes:
        blob = blobs[size]
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
        body += blob
    out_path.write_bytes(directory + entries + body)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_path = root / "highdeas.ico"

    master = render_master()
    frames = [
        master.resize((size, size), Image.Resampling.LANCZOS)
        for size in ICON_SIZES
    ]
    # The ICO plugin derives every frame from the base image; hand it the
    # largest LANCZOS-downscaled frame and the explicit size list so no frame
    # is upscaled from a smaller source.
    pack_ico(dict(zip(ICON_SIZES, frames)), out_path)
    print(f"wrote {out_path} with sizes {ICON_SIZES}")

    docs_png = root / "docs/highdeas.png"
    frames[ICON_SIZES.index(256)].save(docs_png, format="PNG")
    print(f"wrote {docs_png} (README emblem)")

    layer_path = root / "tools/Highdeas.icon/Assets/leaf.png"
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    render_master(fill=IOS_FILL).save(layer_path, format="PNG")
    print(f"wrote {layer_path} (macOS icon layer)")

    ios_emblem = render_master(fill=IOS_FILL)
    ios = Image.new("RGB", (S, S), IOS_BG)
    ios.paste(ios_emblem, mask=ios_emblem)
    ios_path = root / "ios/Highdeas/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
    ios_path.parent.mkdir(parents=True, exist_ok=True)
    ios.save(ios_path, format="PNG")
    print(f"wrote {ios_path} ({S}x{S}, opaque)")



if __name__ == "__main__":
    main()
