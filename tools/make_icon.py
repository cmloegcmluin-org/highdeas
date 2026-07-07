"""Generate ``voicememo.ico`` — a white microphone on a green cannabis leaf.

This draws the "Highdeas" app icon: a stylized seven-point cannabis leaf
(green leaflets radiating from a common centre) with a white microphone glyph
centred on top. The result is written to the repository root as a multi-size
Windows ICO (16, 32, 48, 64, 128, 256).

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
from pathlib import Path

from PIL import Image, ImageDraw

# --- palette ---------------------------------------------------------------

LEAF = (58, 168, 74)  # vivid leaf green (fill)
LEAF_DARK = (33, 110, 45)  # darker green for leaflet outlines / shading
WHITE = (255, 255, 255, 255)

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
    """Draw the white microphone glyph centred over the leaf core."""
    cx = 0.50 * S

    # Capsule (the mic head): a fully rounded vertical bar.
    cap_hw = 0.075 * S
    draw.rounded_rectangle(
        [cx - cap_hw, 0.285 * S, cx + cap_hw, 0.495 * S],
        radius=cap_hw,
        fill=WHITE,
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
        fill=WHITE,
        width=stroke,
    )
    # Round the cradle's two tips.
    cap_r = stroke / 2
    for ang in (start, end):
        a = math.radians(ang)
        tx = cx + ru * math.cos(a)
        ty = cradle_cy + ru * math.sin(a)
        draw.ellipse([tx - cap_r, ty - cap_r, tx + cap_r, ty + cap_r], fill=WHITE)

    # Stem: connects the cradle down to the base.
    stem_hw = 0.016 * S
    draw.rounded_rectangle(
        [cx - stem_hw, 0.50 * S, cx + stem_hw, 0.645 * S],
        radius=stem_hw,
        fill=WHITE,
    )

    # Base: a short horizontal foot.
    base_hw = 0.077 * S
    base_h = 0.031 * S
    draw.rounded_rectangle(
        [cx - base_hw, 0.663 * S - base_h, cx + base_hw, 0.663 * S],
        radius=base_h / 2,
        fill=WHITE,
    )


# Fraction of the canvas edge the emblem should span after centring.
FILL = 0.90


def render_master() -> Image.Image:
    """Render the full emblem, then scale it to ``FILL`` and centre it.

    Centring from the actual pixel bounds (rather than trusting the hand-tuned
    layout constants) keeps the emblem balanced in the frame and fills it
    consistently at every icon size.
    """
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_leaf(draw)
    draw_core(draw)
    draw_mic(draw)

    bbox = img.getbbox()
    cropped = img.crop(bbox)
    w, h = cropped.size
    scale = (FILL * S) / max(w, h)
    scaled = cropped.resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)

    centered = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    centered.alpha_composite(
        scaled, ((S - scaled.width) // 2, (S - scaled.height) // 2)
    )
    return centered


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_path = root / "voicememo.ico"

    master = render_master()
    frames = [
        master.resize((size, size), Image.Resampling.LANCZOS)
        for size in ICON_SIZES
    ]
    # The ICO plugin derives every frame from the base image; hand it the
    # largest LANCZOS-downscaled frame and the explicit size list so no frame
    # is upscaled from a smaller source.
    largest = frames[-1]
    largest.save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in ICON_SIZES],
        append_images=frames[:-1],
    )
    print(f"wrote {out_path} with sizes {ICON_SIZES}")


if __name__ == "__main__":
    main()
