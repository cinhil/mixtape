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


def remove_checkerboard(img: Image.Image, *, edge_thresh: int = 70) -> Image.Image:
    """Replace baked-in checkerboard background with real alpha=0.

    Uses a flood-fill from each corner (RGB-only) so only pixels
    *connected* to the background are cleared — interior cassette pixels
    that happen to share a similar tone are safe.

    ``edge_thresh`` controls how aggressively the fill spreads into
    anti-aliased edges; higher = cleaner edges but a bit more risk of
    eating soft-coloured cassette borders.
    """
    rgb = img.convert("RGB").copy()
    w, h = rgb.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for x, y in corners:
        r, g, b, _ = img.getpixel((x, y))
        if not _is_checkerboard_pixel(r, g, b):
            continue
        ImageDraw.floodfill(rgb, (x, y), _SENTINEL, thresh=edge_thresh)

    # Build alpha mask: where the flood-fill painted the sentinel → transparent.
    alpha = img.split()[3].copy()
    alpha_pixels = alpha.load()
    rgb_pixels = rgb.load()
    for y in range(h):
        for x in range(w):
            if rgb_pixels[x, y] == _SENTINEL:
                alpha_pixels[x, y] = 0

    out = img.copy()
    out.putalpha(alpha)
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
