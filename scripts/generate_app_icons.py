#!/usr/bin/env python3
"""Regenerate Mobilerun launcher mipmaps + web favicon raster from the brand mark."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android-app/src/main/res"
PUBLIC = ROOT / "frontend/public"

BG = (10, 10, 10, 255)
ACCENT = (59, 130, 246, 255)
SPARK = (96, 165, 250, 255)
PHONE_FILL = (24, 24, 27, 255)

FAVICON_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Mobilerun">
  <rect width="64" height="64" rx="14" fill="#0a0a0a"/>
  <rect x="20" y="10" width="24" height="44" rx="5" fill="#18181b" stroke="#3b82f6" stroke-width="2.2"/>
  <rect x="27" y="13.5" width="10" height="2.2" rx="1.1" fill="#52525b"/>
  <path d="M31.2 24.5 L42 32 L31.2 39.5 Z" fill="#3b82f6"/>
  <path d="M44.5 21.5 L46.2 25.2 L50 26 L46.2 26.8 L44.5 30.5 L42.8 26.8 L39 26 L42.8 25.2 Z" fill="#60a5fa"/>
  <circle cx="32" cy="48.5" r="1.6" fill="#52525b"/>
</svg>
"""


def draw_mark(size: int, round_mask: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Full opaque square first so OEM launchers never composite a blank tile.
    draw.rectangle([0, 0, size - 1, size - 1], fill=BG)
    if round_mask:
        # Re-draw circular plate (mask applied at end)
        draw.ellipse([0, 0, size - 1, size - 1], fill=BG)
    else:
        r = max(1, int(size * 0.22))
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    pw = size * 0.38
    ph = size * 0.68
    px = (size - pw) / 2
    py = (size - ph) / 2
    pr = size * 0.08
    draw.rounded_rectangle(
        [px, py, px + pw, py + ph],
        radius=pr,
        fill=PHONE_FILL,
        outline=ACCENT[:3] + (255,),
        width=max(2, size // 32),
    )
    sw, sh = pw * 0.38, size * 0.025
    sx, sy = px + (pw - sw) / 2, py + ph * 0.07
    draw.rounded_rectangle([sx, sy, sx + sw, sy + sh], radius=sh / 2, fill=(82, 82, 91, 255))
    cx, cy = px + pw * 0.42, py + ph * 0.48
    tw, th = pw * 0.55, ph * 0.28
    draw.polygon(
        [(cx, cy - th / 2), (cx + tw, cy), (cx, cy + th / 2)],
        fill=ACCENT,
    )
    sparx = px + pw * 0.95
    spary = py + ph * 0.22
    s = size * 0.09
    star = []
    for i in range(8):
        ang = -math.pi / 2 + i * math.pi / 4
        rad = s if i % 2 == 0 else s * 0.38
        star.append((sparx + rad * math.cos(ang), spary + rad * math.sin(ang)))
    draw.polygon(star, fill=SPARK)
    hr = size * 0.018
    hx, hy = size / 2, py + ph * 0.88
    draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(82, 82, 91, 255))

    if round_mask:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, mask=mask)
        return out
    return img


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "favicon.svg").write_text(FAVICON_SVG)
    (PUBLIC / "mobilerun-mark.svg").write_text(FAVICON_SVG)

    densities = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder, sz in densities.items():
        d = RES / folder
        d.mkdir(parents=True, exist_ok=True)
        draw_mark(sz, round_mask=False).save(d / "ic_launcher.png", "PNG")
        draw_mark(sz, round_mask=True).save(d / "ic_launcher_round.png", "PNG")
        print(f"wrote {folder} {sz}px")

    draw_mark(64).save(PUBLIC / "favicon.png", "PNG")
    draw_mark(192).save(PUBLIC / "apple-touch-icon.png", "PNG")
    print("wrote frontend/public favicons")


if __name__ == "__main__":
    main()
