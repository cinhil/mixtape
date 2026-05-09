"""Build mixtape.ico + mixtape.png from a hand-crafted source artwork.

Usage:

    uv run python scripts/build_icon_from_art.py path/to/source.png

The script:
- Auto-detects a baked-in "transparency checkerboard" background (the kind
  some AI generators leave in the PNG as opaque light-grey pixels) and
  chroma-keys it out to real alpha=0.
- Trims transparent borders so the artwork fills the icon.
- Pads to a centered square with transparent background.
- Writes mixtape.ico (multi-res) + mixtape.png (256×256) at the project root.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "mixtape.ico"
OUT_PNG = ROOT / "mixtape.png"
SIZES = (256, 128, 64, 48, 32, 16)


_SENTINEL = (255, 0, 255)  # magenta — chosen because no cassette pixel uses it


def _is_checkerboard_pixel(r: int, g: int, b: int) -> bool:
    """A near-grey pixel in the typical transparency-checkerboard range
    (light grey ~185 to white ~255), with very low colour variance."""
    return (
        185 <= r <= 255 and 185 <= g <= 255 and 185 <= b <= 255
        and abs(r - g) <= 8 and abs(g - b) <= 8 and abs(r - b) <= 8
    )


def _looks_checkered(img: Image.Image) -> bool:
    """Heuristic: are the four corner pixels grey-ish with alpha 255?
    If yes, the source has a baked-in transparency-checkerboard background."""
    w, h = img.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    n_grey = 0
    for x, y in corners:
        r, g, b, a = img.getpixel((x, y))
        if a == 255 and _is_checkerboard_pixel(r, g, b):
            n_grey += 1
    return n_grey >= 3


def remove_checkerboard(img: Image.Image, *, edge_thresh: int = 25) -> Image.Image:
    """Replace baked-in checkerboard background with real alpha=0.

    Two-pass approach:
      1. Pure colour chroma-key: every pixel matching ``_is_checkerboard_pixel``
         goes to alpha=0. Safe because cassette art uses saturated colours
         (warm browns / reds / black) outside the grey range.
      2. Anti-aliasing cleanup: any pixel still adjacent to a now-transparent
         pixel AND close-ish to grey gets its alpha reduced proportionally to
         its colour distance from grey. Eliminates the faint halo that pure
         chroma-key leaves at the edges.
    """
    out = img.copy()
    pixels = out.load()
    w, h = out.size

    # Pass 1: hard chroma-key
    transparent_mask = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0 or _is_checkerboard_pixel(r, g, b):
                pixels[x, y] = (r, g, b, 0)
                transparent_mask[y][x] = True

    # Pass 2: feather edges. For each pixel that's adjacent to a transparent
    # one and that's still grey-ish (but didn't quite match the strict
    # chroma-key), drop its alpha based on its distance from neutral grey.
    def is_neighbour_transparent(x: int, y: int) -> bool:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and transparent_mask[ny][nx]:
                    return True
        return False

    for y in range(h):
        for x in range(w):
            if transparent_mask[y][x]:
                continue
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            # Only feather pixels that are grey-tinted AND touch a transparent
            # neighbour — this protects saturated cassette pixels.
            if abs(r - g) > 12 or abs(g - b) > 12 or abs(r - b) > 12:
                continue
            if not is_neighbour_transparent(x, y):
                continue
            # Distance from neutral grey 200 → larger distance keeps more alpha
            avg = (r + g + b) // 3
            dist = abs(avg - 200)
            new_alpha = min(a, int(min(255, dist * 8)))
            pixels[x, y] = (r, g, b, new_alpha)

    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <source.png>", file=sys.stderr)
        return 2
    src_path = Path(sys.argv[1]).resolve()
    if not src_path.is_file():
        print(f"not found: {src_path}", file=sys.stderr)
        return 1

    img = Image.open(src_path).convert("RGBA")
    if _looks_checkered(img):
        print("→ baked-in checkerboard background detected, chroma-keying it out")
        img = remove_checkerboard(img)

    # Trim transparent border so the artwork fills the icon.
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # Pad to a centered square with transparent background.
    w, h = img.size
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - w) // 2, (side - h) // 2), img)

    images = [square.resize((s, s), Image.LANCZOS) for s in SIZES]
    images[0].save(OUT_ICO, format="ICO", sizes=[(s, s) for s in SIZES])
    images[0].save(OUT_PNG, format="PNG")
    print(f"wrote {OUT_ICO}  ({OUT_ICO.stat().st_size:,} bytes)")
    print(f"wrote {OUT_PNG}  ({OUT_PNG.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
