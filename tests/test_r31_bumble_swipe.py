"""r31: Bumble dry swipe names come from the People card, never owner/tabs."""

from __future__ import annotations

from pathlib import Path

from backend.dm_heuristics import bumble_deck_card_name, _bumble_card_name_ok
from backend.bulk_bench_heuristics import (
    _card_name_is_owner,
    _card_name_is_real_profile,
)
from backend.cloud_agent import (
    _visible_dry_swipe_card_name,
    apply_dry_run_send_guard,
    hinge_name_from_vision_reply,
    _salvage_dry_swipe_done,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"
INSTR = "like 5 profiles on Bumble"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_sparse_people_tree_is_not_a_tab_or_owner_name():
    tree = _load("bumble_people_sparse_kalia.xml")
    assert bumble_deck_card_name(tree) is None
    assert _visible_dry_swipe_card_name(INSTR, tree, state={}) is None


def test_owner_profile_name_is_never_a_swipe_card():
    assert _card_name_is_owner("MacAnderson, 30")
    assert not _card_name_is_real_profile("MacAnderson, 30")
    assert not _bumble_card_name_ok("MacAnderson")
    tree = _load("bumble_owner_profile_card.xml")
    assert bumble_deck_card_name(tree) is None
    assert _visible_dry_swipe_card_name(INSTR, tree, state={}) is None


def test_tab_labels_are_not_card_names():
    for bad in ("People", "Profile", "Discover", "Liked You", "Chats", "Filters"):
        assert not _card_name_is_real_profile(bad), bad
        assert not _bumble_card_name_ok(bad), bad
    assert _card_name_is_real_profile("Kalia, 25")
    assert _bumble_card_name_ok("Kalia")


def test_vision_reply_accepts_kalia_rejects_owner_and_tabs():
    assert hinge_name_from_vision_reply("Kalia") == "Kalia"
    assert hinge_name_from_vision_reply("Kalia, 25") == "Kalia"
    assert hinge_name_from_vision_reply("MacAnderson, 30") is None
    assert hinge_name_from_vision_reply("People") is None
    assert hinge_name_from_vision_reply("Liked You") is None
    assert hinge_name_from_vision_reply("NONE") is None


def test_dry_guard_skips_encounters_grid_like_tap():
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True,
        action={
            "action": "tap",
            "x": 200,
            "y": 1800,
            "reason": "Tapping on the profile in the encounters grid to like it.",
        },
        kind="tap",
        reason="Tapping on the profile in the encounters grid to like it.",
    )
    assert kind == "done"
    assert out.get("dry_run_verified") is not True


def test_salvage_uses_cached_vision_name_when_tree_is_sparse():
    tree = _load("bumble_people_sparse_kalia.xml")
    st = {"_bumble_vision_name": "Kalia", "current_profile_name": "Kalia"}
    # cached vision name is stored; _visible may not see it unless current_profile
    out = _salvage_dry_swipe_done(
        instruction=INSTR,
        ui_tree=tree,
        state=st,
        action={"action": "done", "reason": "[DRY RUN] would like/pass tap — skipped"},
        reason="[DRY RUN] would like/pass tap — skipped (Tapping on the profile in the encounters grid to like it.)",
        image_b64=None,
    )
    # current_profile_name is consulted by _visible_dry_swipe_card_name
    assert out is not None
    assert out.get("dry_run_verified") is True
    assert "Kalia" in (out.get("reason") or "")
    assert "MacAnderson" not in (out.get("reason") or "")


def test_dry_guard_blocks_tapping_profile_list_to_start_liking():
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True,
        action={
            "action": "tap",
            "x": 545,
            "y": 1173,
            "reason": "Tapping on the profile list to start liking profiles.",
        },
        kind="tap",
        reason="Tapping on the profile list to start liking profiles.",
    )
    assert kind == "done"
    assert out.get("dry_run_verified") is not True


def test_photo_browser_override_backs_out_never_superswipe():
    from backend.cloud_agent import _bumble_photo_browser_override
    from backend.dm_heuristics import bumble_on_photo_browser

    tree = _load("bumble_photo_browser_superswipe.xml")
    assert bumble_on_photo_browser(tree)
    out = _bumble_photo_browser_override(
        instruction=INSTR,
        ui_tree=tree,
        package="com.bumble.app",
        action={"action": "tap", "x": 896, "y": 2016, "reason": "tap star"},
    )
    assert out is not None
    assert str(out.get("action")).lower() in {"press_button", "back"}
    assert "superswipe" in str(out.get("reason") or "").lower()
    assert out.get("button") == "back"
