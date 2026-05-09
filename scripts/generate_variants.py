"""Render 4 candidate icon styles for visual comparison.

Run from the project root:

    uv run python scripts/generate_variants.py

Writes ``variant_1.png`` … ``variant_4.png`` at the project root.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SIZE = 256


def _font(px: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


# ── Variant 1 — Retro coral (the current production icon) ───────────────────

def variant_1() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    BODY      = (236, 95, 80, 255)
    BODY_DARK = (180, 56, 46, 255)
    LABEL     = (252, 240, 210, 255)
    LABEL_OUT = (130, 110, 70, 255)
    REEL_FACE = (40, 40, 40, 255)
    REEL_HOLE = (236, 95, 80, 255)
    TAPE      = (30, 30, 30, 255)
    TEXT      = (60, 40, 25, 255)

    d.rounded_rectangle((16, 56, 240, 200), radius=14, fill=BODY, outline=BODY_DARK, width=3)
    d.rounded_rectangle((34, 76, 222, 132), radius=6, fill=LABEL, outline=LABEL_OUT, width=2)
    for y in (90, 102, 114):
        d.line((46, y, 210, y), fill=LABEL_OUT, width=2)
    for cx in (86, 170):
        d.ellipse((cx - 26, 142, cx + 26, 194), fill=REEL_FACE, outline=BODY_DARK, width=2)
        for dx, dy in ((-18, 0), (18, 0), (0, -18), (0, 18)):
            d.line((cx + dx * 0.4, 168 + dy * 0.4, cx + dx, 168 + dy), fill=LABEL, width=2)
        d.ellipse((cx - 9, 159, cx + 9, 177), fill=REEL_HOLE, outline=BODY_DARK, width=2)
    d.line((110, 168, 146, 168), fill=TAPE, width=3)
    d.line((20, 196, 236, 196), fill=BODY_DARK, width=2)
    f = _font(28)
    bbox = d.textbbox((0, 0), "MIXTAPE", font=f)
    tw = bbox[2] - bbox[0]
    d.text(((SIZE - tw) / 2, 86), "MIXTAPE", fill=TEXT, font=f)
    return img


# ── Variant 2 — Flat dark mono (mint accent on charcoal rounded square) ────

def variant_2() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    BG     = (32, 36, 48, 255)
    INK    = (167, 244, 215, 255)  # mint
    INK_DM = (105, 175, 150, 255)
    d.rounded_rectangle((0, 0, SIZE, SIZE), radius=44, fill=BG)
    # Cassette outline
    d.rounded_rectangle((30, 70, 226, 196), radius=14, outline=INK, width=4)
    # Label
    d.rounded_rectangle((46, 86, 210, 130), radius=6, outline=INK, width=3)
    for y in (98, 108, 118):
        d.line((58, y, 198, y), fill=INK_DM, width=2)
    # Reels
    for cx in (90, 166):
        d.ellipse((cx - 24, 144, cx + 24, 192), outline=INK, width=4)
        d.ellipse((cx - 8, 160, cx + 8, 176), outline=INK, width=3)
    d.line((114, 168, 142, 168), fill=INK, width=3)
    return img


# ── Variant 3 — Synthwave neon (magenta + cyan glow on deep purple) ────────

def variant_3() -> Image.Image:
    BG = (15, 6, 30, 255)
    img = Image.new("RGBA", (SIZE, SIZE), BG)
    # Pre-render the lines in a separate layer so we can blur it for the glow
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    PINK = (255, 51, 158, 255)
    CYAN = (0, 222, 255, 255)
    YEL  = (255, 220, 80, 255)

    # horizon line + sun (synthwave staple)
    for r, alpha in ((110, 140), (96, 200), (84, 255)):
        g.ellipse((SIZE / 2 - r, 30, SIZE / 2 + r, 30 + 2 * r),
                  outline=YEL[:3] + (alpha,), width=2)
    g.line((0, 138, SIZE, 138), fill=YEL, width=2)

    # Cassette
    g.rounded_rectangle((28, 76, 228, 210), radius=18, outline=PINK, width=4)
    g.rounded_rectangle((46, 92, 210, 134), radius=8, outline=CYAN, width=3)
    for cx in (90, 166):
        g.ellipse((cx - 24, 154, cx + 24, 202), outline=CYAN, width=4)
        g.ellipse((cx - 8, 170, cx + 8, 186), outline=PINK, width=3)
    g.line((114, 178, 142, 178), fill=PINK, width=3)

    # Apply soft glow
    glow_blurred = glow.filter(ImageFilter.GaussianBlur(radius=4))
    img.alpha_composite(glow_blurred)
    img.alpha_composite(glow)  # crisp lines on top of the blur

    return img


# ── Variant 4 — Line art (single ink colour, no fills) ─────────────────────

def variant_4() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    INK = (33, 38, 49, 255)
    W = 5
    # Cassette outline
    d.rounded_rectangle((24, 60, 232, 204), radius=20, outline=INK, width=W)
    # Label
    d.rounded_rectangle((42, 78, 214, 134), radius=8, outline=INK, width=W - 1)
    # Label lines
    for y in (97, 109, 121):
        d.line((58, y, 198, y), fill=INK, width=2)
    # Reels
    for cx in (88, 168):
        d.ellipse((cx - 28, 144, cx + 28, 200), outline=INK, width=W)
        # Spokes
        for ang_dx, ang_dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-0.7, -0.7), (0.7, -0.7), (-0.7, 0.7), (0.7, 0.7)):
            d.line((cx + ang_dx * 10, 172 + ang_dy * 10, cx + ang_dx * 24, 172 + ang_dy * 24),
                   fill=INK, width=2)
        d.ellipse((cx - 8, 164, cx + 8, 180), outline=INK, width=W - 1)
    d.line((116, 172, 140, 172), fill=INK, width=4)
    # Hand-written looking caption
    f = _font(20)
    bbox = d.textbbox((0, 0), "mixtape", font=f)
    tw = bbox[2] - bbox[0]
    d.text(((SIZE - tw) / 2, 218), "mixtape", fill=INK, font=f)
    return img


def main() -> None:
    variants = [variant_1, variant_2, variant_3, variant_4]
    for i, fn in enumerate(variants, start=1):
        out = ROOT / f"variant_{i}.png"
        fn().save(out, format="PNG")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
