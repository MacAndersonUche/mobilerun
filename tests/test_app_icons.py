"""Regression: launcher icons must not be placeholder 1x1 transparent PNGs."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android-app/src/main/res"
PUBLIC = ROOT / "frontend/public"

DENSITIES = (
    "mipmap-mdpi",
    "mipmap-hdpi",
    "mipmap-xhdpi",
    "mipmap-xxhdpi",
    "mipmap-xxxhdpi",
)
MIN_SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def test_legacy_mipmaps_are_real_icons():
    for folder in DENSITIES:
        for name in ("ic_launcher.png", "ic_launcher_round.png"):
            path = RES / folder / name
            assert path.is_file(), path
            im = Image.open(path)
            assert im.size[0] >= MIN_SIZES[folder]
            assert im.size[1] >= MIN_SIZES[folder]
            # Must have non-transparent pixels (not the old 1x1 empty placeholder)
            rgba = im.convert("RGBA")
            extrema = rgba.getextrema()
            # extrema for RGBA is ((rmin,rmax),...,(amin,amax))
            assert extrema[3][1] > 200, f"{path} looks empty"


def test_adaptive_and_notification_vectors_exist():
    required = [
        RES / "mipmap-anydpi-v26/ic_launcher.xml",
        RES / "mipmap-anydpi-v26/ic_launcher_round.xml",
        RES / "drawable/ic_launcher_foreground.xml",
        RES / "drawable/ic_launcher_monochrome.xml",
        RES / "drawable/ic_stat_mobilerun.xml",
        RES / "values/colors.xml",
    ]
    for path in required:
        text = path.read_text()
        assert text.strip(), path
    mono = (RES / "drawable/ic_launcher_monochrome.xml").read_text()
    assert "#FFFFFFFF" in mono or "#FFFFFF" in mono
    stat = (RES / "drawable/ic_stat_mobilerun.xml").read_text()
    assert "#FFFFFFFF" in stat or "#FFFFFF" in stat
    assert "fillColor" in stat


def test_web_favicon_mark_present():
    assert (PUBLIC / "favicon.svg").is_file()
    svg = (PUBLIC / "favicon.svg").read_text()
    assert "#3b82f6" in svg.lower() or "#3B82F6" in svg
    assert (PUBLIC / "favicon.png").is_file()
    im = Image.open(PUBLIC / "favicon.png")
    assert im.size[0] >= 32
