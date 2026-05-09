"""Generate mixtape.ico — vintage cassette icon, transparent background.

Design notes (inspired by a Gemini-generated reference):
- Warm beige body (cream highlights, brown edges) for that worn-cassette look
- Bold red label with yellow corner strip, white "MIXTAPE" caption
- Two large dark reels with cream spokes
- A short magnetic-tape strip emerges from the bottom (large sizes only)
- Fully transparent background — looks good on any wallpaper / theme

Run from the project root:

    uv run python scripts/generate_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "mixtape.ico"
OUT_PNG = ROOT / "mixtape.png"

# Palette ────────────────────────────────────────────────────────────────────
BODY_LIGHT = (224, 198, 153, 255)   # cream-beige (cassette body face)
BODY_MID   = (193, 158, 102, 255)   # slightly darker for depth
BODY_EDGE  = (122,  79,  48, 255)   # warm brown outline / shadow
LABEL_RED  = (197,  48,  48, 255)
LABEL_DARK = (130,  20,  20, 255)
YELLOW     = (240, 196,  60, 255)
WHITE      = (255, 248, 232, 255)
REEL_BLK   = ( 28,  28,  32, 255)
REEL_HUB   = (236, 222, 188, 255)   # cream hub showing through
TAPE       = ( 80,  50,  28, 255)
SHADOW_W   = ( 68,  44,  24, 90)    # subtle drop shadow under body


def _font(px: int, *, bold: bool = True) -> ImageFont.ImageFont:
    names = (
        ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        ("Arial Bold.ttf" if bold else "Arial.ttf"),
        "DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_cassette(size: int) -> Image.Image:
    """Render the cassette at the requested size on a transparent canvas."""
    s = size / 256.0  # scale factor

    def sc(*xs):
        return tuple(int(round(x * s)) for x in xs)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Subtle drop shadow (only meaningful at larger sizes)
    if size >= 48:
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(sc(20, 70, 240, 210), radius=int(20 * s), fill=SHADOW_W)
        from PIL import ImageFilter
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=int(3 * s)))
        img.alpha_composite(shadow)

    # Body — main face
    d.rounded_rectangle(sc(16, 60, 240, 200), radius=int(18 * s),
                        fill=BODY_LIGHT, outline=BODY_EDGE,
                        width=max(1, int(3 * s)))
    # Body — bottom band a bit darker (depth illusion)
    d.rectangle(sc(20, 178, 236, 197), fill=BODY_MID)

    # Tiny corner "screw" dots (only when there's room)
    if size >= 64:
        for cx, cy in ((30, 72), (226, 72), (30, 188), (226, 188)):
            d.ellipse(sc(cx - 3, cy - 3, cx + 3, cy + 3),
                      fill=BODY_EDGE)

    # Label background
    d.rounded_rectangle(sc(36, 78, 220, 130), radius=int(4 * s),
                        fill=LABEL_RED, outline=LABEL_DARK,
                        width=max(1, int(2 * s)))
    # Yellow stripe (corner accent)
    d.polygon(sc(36, 78, 80, 78, 62, 96, 36, 96), fill=YELLOW)
    # Thin pinstripe across label
    d.line(sc(36, 102, 220, 102), fill=LABEL_DARK, width=max(1, int(1 * s)))
    d.line(sc(36, 124, 220, 124), fill=LABEL_DARK, width=max(1, int(1 * s)))

    # "MIXTAPE" caption (legible from 32px)
    if size >= 32:
        f = _font(int(22 * s))
        text = "MIXTAPE"
        bbox = d.textbbox((0, 0), text, font=f)
        tw = bbox[2] - bbox[0]
        ty = int(106 * s) - (bbox[3] - bbox[1]) // 2 - bbox[1]
        d.text(((size - tw) / 2, ty), text, fill=WHITE, font=f)
    else:
        # 16px: just a thick white horizontal bar standing in for the label text
        d.line(sc(60, 104, 196, 104), fill=WHITE, width=max(1, int(8 * s)))

    # Reels (windows + black face + spokes + cream hub)
    reel_y = 168
    for cx in (88, 168):
        # outer dark face
        d.ellipse(sc(cx - 28, reel_y - 28, cx + 28, reel_y + 28),
                  fill=REEL_BLK, outline=BODY_EDGE, width=max(1, int(2 * s)))
        # spokes
        if size >= 32:
            for ang_x, ang_y in ((-1, 0), (1, 0), (0, -1), (0, 1),
                                 (-0.7, -0.7), (0.7, -0.7), (-0.7, 0.7), (0.7, 0.7)):
                d.line(sc(cx + ang_x * 9, reel_y + ang_y * 9,
                          cx + ang_x * 22, reel_y + ang_y * 22),
                       fill=REEL_HUB, width=max(1, int(2 * s)))
        # cream hub
        d.ellipse(sc(cx - 9, reel_y - 9, cx + 9, reel_y + 9),
                  fill=REEL_HUB, outline=BODY_EDGE, width=max(1, int(1 * s)))

    # Magnetic tape strip between the two reels
    d.line(sc(88 + 28, reel_y, 168 - 28, reel_y), fill=TAPE, width=max(1, int(3 * s)))

    # Curling tape escaping at the bottom (signature touch — only at >= 64px)
    if size >= 96:
        from PIL import ImageDraw as _ID
        # Draw a smooth curve approximated by a few short lines
        path = [(120, 200), (108, 218), (130, 230), (118, 244), (98, 246)]
        scaled = [sc(*pt) for pt in path]
        for a, b in zip(scaled, scaled[1:]):
            d.line(a + b, fill=TAPE, width=max(2, int(2.5 * s)))

    return img


def main() -> None:
    sizes = (256, 128, 64, 48, 32, 16)
    images = [draw_cassette(sz) for sz in sizes]
    images[0].save(OUT_ICO, format="ICO", sizes=[(sz, sz) for sz in sizes])
    images[0].save(OUT_PNG, format="PNG")
    print(f"wrote {OUT_ICO}  ({OUT_ICO.stat().st_size:,} bytes)")
    print(f"wrote {OUT_PNG}  ({OUT_PNG.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
