#!/usr/bin/env python3
"""Generate PNG icons for the Dossier PWA.

Run once when the icon design changes. Pillow is a dev-only dependency
and is NOT listed in any requirements file.

Usage:
    pip install pillow
    python scripts/generate_icons.py
"""

import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is not installed. Run: pip install pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent.parent
ICONS_DIR = ROOT / "app" / "static" / "icons"
STATIC_DIR = ROOT / "app" / "static"

BG_COLOR = (37, 99, 235)   # #2563eb
FG_COLOR = (255, 255, 255)  # white
CORNER_RADIUS_RATIO = 76 / 512  # matches the SVG rx="76" on a 512 canvas


def draw_rounded_rect(draw: ImageDraw.ImageDraw, size: int, radius: int, color: tuple) -> None:
    """Fill a rounded rectangle onto the draw context."""
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=color)


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = max(4, round(CORNER_RADIUS_RATIO * size))
    draw_rounded_rect(draw, size, radius, BG_COLOR)

    # Try to load a system serif font; fall back to default if unavailable.
    font_size = round(size * 0.72)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    serif_candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/Library/Fonts/Georgia Bold.ttf",
        "/Library/Fonts/Georgia.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/georgia.ttf",
    ]
    font = None
    for path in serif_candidates:
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        # Pillow built-in bitmap font — no sizing control, will look small
        font = ImageFont.load_default()
        print(f"  Warning: no system serif font found at size {size}; using default bitmap font.")

    # Centre the glyph
    bbox = draw.textbbox((0, 0), "D", font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]
    draw.text((x, y), "D", font=font, fill=FG_COLOR)

    return img


def save_png(img: Image.Image, path: Path, optimize: bool = True) -> None:
    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img, mask=img.split()[3])
    rgb.save(path, "PNG", optimize=optimize)
    print(f"  Wrote {path} ({path.stat().st_size:,} bytes)")


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    sizes = {
        "icon-192.png": 192,
        "icon-512.png": 512,
    }
    for filename, size in sizes.items():
        print(f"Generating {filename} ({size}×{size})…")
        img = make_icon(size)
        save_png(img, ICONS_DIR / filename)

    print("Generating favicon.png (32×32)…")
    favicon = make_icon(32)
    save_png(favicon, STATIC_DIR / "favicon.png")

    print("Done.")


if __name__ == "__main__":
    main()
