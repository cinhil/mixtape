"""Generate mixtape.ico — a stylised cassette tape icon at multiple sizes.

Run from the project root:

    uv run python scripts/generate_icon.py

Writes ``mixtape.ico`` (multi-resolution: 256/128/64/48/32/16) plus a
``mixtape.png`` at 256×256 for cross-platform use (Linux .desktop entries,
GitHub social card, etc.).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "mixtape.ico"
OUT_PNG = ROOT / "mixtape.png"

# Colour palette — coral body, cream label, charcoal details
BODY        = (236, 95, 80, 255)      # warm coral
BODY_DARK   = (180, 56, 46, 255)      # outline / shadow
LABEL       = (252, 240, 210, 255)    # cream
LABEL_OUT   = (130, 110, 70, 255)
REEL_FACE   = (40, 40, 40, 255)       # very dark grey
REEL_HOLE   = (236, 95, 80, 255)      # body colour showing through
TAPE        = (30, 30, 30, 255)       # the brown magnetic tape
TEXT        = (60, 40, 25, 255)


def draw_cassette(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Working coordinates in a 256-grid for clean math, then we'll scale
    s = size / 256.0

    def sc(*xs):
        return tuple(int(round(x * s)) for x in xs)

    # Body (slightly rounded rectangle)
    body_box = sc(16, 56, 240, 200)
    d.rounded_rectangle(body_box, radius=int(14 * s), fill=BODY, outline=BODY_DARK, width=max(1, int(3 * s)))

    # Cream label
    label_box = sc(34, 76, 222, 132)
    d.rounded_rectangle(label_box, radius=int(6 * s), fill=LABEL, outline=LABEL_OUT, width=max(1, int(2 * s)))

    # Three label lines
    line_pad_x = int(46 * s)
    for i, y in enumerate((90, 102, 114)):
        d.line(sc(line_pad_x, y, 256 - 46, y), fill=LABEL_OUT, width=max(1, int(2 * s)))

    # Two reels (visible through windows)
    reel_centers = [(86, 168), (170, 168)]
    reel_outer_r = 26
    reel_inner_r = 9
    for cx, cy in reel_centers:
        # Outer dark disc
        d.ellipse(sc(cx - reel_outer_r, cy - reel_outer_r,
                     cx + reel_outer_r, cy + reel_outer_r),
                  fill=REEL_FACE, outline=BODY_DARK, width=max(1, int(2 * s)))
        # Spokes
        for offset in ((-18, 0), (18, 0), (0, -18), (0, 18)):
            d.line(sc(cx + offset[0] * 0.4, cy + offset[1] * 0.4,
                      cx + offset[0], cy + offset[1]),
                   fill=LABEL, width=max(1, int(2 * s)))
        # Inner hole
        d.ellipse(sc(cx - reel_inner_r, cy - reel_inner_r,
                     cx + reel_inner_r, cy + reel_inner_r),
                  fill=REEL_HOLE, outline=BODY_DARK, width=max(1, int(1.5 * s)))

    # Tape strip running between reels (subtle)
    d.line(sc(86 + reel_outer_r - 2, 168, 170 - reel_outer_r + 2, 168),
           fill=TAPE, width=max(1, int(3 * s)))

    # Bottom shadow line
    d.line(sc(20, 196, 236, 196), fill=BODY_DARK, width=max(1, int(2 * s)))

    # Letter "M" on the label (for >= 64px renders only — looks muddy small)
    if size >= 64:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(28 * s))
        except OSError:
            font = ImageFont.load_default()
        text = "MIXTAPE"
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((size - tw) / 2, int(95 * s) - th / 2 - bbox[1]),
               text, fill=TEXT, font=font)

    return img


def main() -> None:
    sizes = (256, 128, 64, 48, 32, 16)
    images = [draw_cassette(sz) for sz in sizes]
    # Multi-resolution .ico (Windows picks the right one for context)
    images[0].save(OUT_ICO, format="ICO",
                   sizes=[(sz, sz) for sz in sizes])
    # Convenience PNG at 256×256 for non-Windows uses
    images[0].save(OUT_PNG, format="PNG")
    print(f"wrote {OUT_ICO}  ({OUT_ICO.stat().st_size:,} bytes)")
    print(f"wrote {OUT_PNG}  ({OUT_PNG.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
