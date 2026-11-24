"""r51b: dating config defaults include the new portal apps without dropping old ones."""

from mobilerun.dating.config import (
    DEFAULT_APPS,
    AppProfile,
    display_name_for_package,
    ensure_default_apps,
)


NEW = [
    "com.tinder",
    "enterprises.dating.boo",
    "social.breeze.breeze_app",
    "com.getpure.pure",
    "com.threesome.swingers.threefun",
]
# Taimi was already a default; keep it in its existing spot
KEEP = ["com.takimi.android", "com.bumble.app", "com.hily.app", "com.facebook.katana"]


def test_default_apps_include_new_portal_apps():
    pkgs = [a.package_name for a in DEFAULT_APPS]
    for p in NEW + KEEP:
        assert p in pkgs, p
    assert pkgs.index("com.takimi.android") == 0
    # socials still present; frontend filters them from the dating cards
    assert "com.whatsapp" in pkgs


def test_ensure_default_apps_merges_without_wiping_saved():
    saved = [
        AppProfile(name="Bumble", package_name="com.bumble.app", enabled=False, daily_swipe_cap=9),
        AppProfile(name="Taimi", package_name="com.takimi.android", enabled=True),
    ]
    merged = ensure_default_apps(saved)
    by = {a.package_name: a for a in merged}
    assert by["com.bumble.app"].enabled is False
    assert by["com.bumble.app"].daily_swipe_cap == 9
    assert by["com.takimi.android"].name == "Taimi"
    for p in NEW:
        assert p in by
        assert by[p].enabled is True
    # do not duplicate
    assert len([a for a in merged if a.package_name == "com.bumble.app"]) == 1


def test_display_names_for_new_apps():
    assert display_name_for_package("enterprises.dating.boo") == "Boo"
    assert display_name_for_package("social.breeze.breeze_app") == "Breeze"
    assert display_name_for_package("com.getpure.pure") == "Pure"
    assert display_name_for_package("com.threesome.swingers.threefun") == "3Fun"
    assert display_name_for_package("com.tinder") == "Tinder"
