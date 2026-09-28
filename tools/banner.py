#!/usr/bin/env python3
"""Compose docs/banner.png (1280x640, also the GitHub social preview) from the
logo and an off-screen render of the popup (tools/preview.py).

    tools/preview.py docs/screenshots --states colour white
    tools/banner.py
Needs Pillow and cairosvg or rsvg-convert for the logo.
"""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 640
FONT_BOLD = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/noto/NotoSans-Regular.ttf"


def logo(size: int) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "logo.png"
        subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size),
                        str(ROOT / "docs/brand/logo.svg"), "-o", str(out)], check=True)
        return Image.open(out).convert("RGBA")


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *img.size), radius, fill=255)
    img = img.convert("RGBA")
    img.putalpha(mask)
    return img


def main() -> None:
    bg = Image.new("RGB", (W, H), "#0c0d15")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((700, -120, 1380, 560), fill=(138, 107, 255, 70))
    g.ellipse((820, 200, 1340, 760), fill=(255, 95, 162, 55))
    g.ellipse((-200, 300, 500, 900), fill=(255, 179, 71, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    bg.paste(glow, (0, 0), glow)

    shot = Image.open(ROOT / "docs/screenshots/colour.png")
    target_h = 560
    shot = shot.resize((round(shot.width * target_h / shot.height), target_h), Image.LANCZOS)
    shot = rounded(shot, 22)
    x, y = W - shot.width - 90, (H - shot.height) // 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x - 4, y + 14, x + shot.width + 4, y + shot.height + 22), 26, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    bg.paste(shadow, (0, 0), shadow)
    border = Image.new("RGBA", (shot.width + 2, shot.height + 2), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (0, 0, shot.width + 1, shot.height + 1), 23, outline=(255, 255, 255, 38), width=1)
    bg.paste(shot, (x, y), shot)
    bg.paste(border, (x - 1, y - 1), border)

    mark = logo(112)
    bg.paste(mark, (90, 150), mark)

    d = ImageDraw.Draw(bg)
    d.text((88, 290), "Tuya Light", font=ImageFont.truetype(FONT_BOLD, 72), fill="#f2f3fa")
    body = ImageFont.truetype(FONT_REG, 27)
    lines = ["Your Tuya Wi-Fi bulbs from the KDE panel,",
             "the terminal, or an AI assistant.",
             "Local network only, no cloud round-trips."]
    for i, line in enumerate(lines):
        d.text((90, 392 + i * 40), line, font=body, fill="#a9adc4" if i < 2 else "#7d8199")

    out = ROOT / "docs/banner.png"
    bg.save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main()
