"""Build mixtape.ico + mixtape.png from a hand-crafted source artwork.

Usage:

    uv run python scripts/build_icon_from_art.py path/to/source.png

The script:
- Trims transparent borders around the artwork
- Pads to a square (centered, transparent background)
- Resizes to standard icon sizes
- Writes mixtape.ico (multi-res) + mixtape.png (256×256) at the project root
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "mixtape.ico"
OUT_PNG = ROOT / "mixtape.png"
SIZES = (256, 128, 64, 48, 32, 16)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <source.png>", file=sys.stderr)
        return 2
    src_path = Path(sys.argv[1]).resolve()
    if not src_path.is_file():
        print(f"not found: {src_path}", file=sys.stderr)
        return 1

    img = Image.open(src_path).convert("RGBA")
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
