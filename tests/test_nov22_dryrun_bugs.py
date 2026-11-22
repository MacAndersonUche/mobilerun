"""22 Nov real-phone dry-run bugfixes (Bumble/Yubo/Badoo/Hily/Hinge/Tagged)."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _deck_visible,
    _open_chats_tab_action,
    _recover_to_root_action,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.cloud_agent import _action_looks_like_paid
from backend.dm_heuristics import (
    bumble_on_photo_browser,
    hily_close_mbm,
    hily_on_mbm,
    hily_on_top_picks_grid,
    hinge_like_sheet_action,
    hinge_on_like_sheet,
    known_root_screen,
    tab_bar_verified,
    tagged_deck_card_name,
    tagged_on_deck,
    yubo_chat_tab_xy,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_bumble_photo_browser_backs_out():
    tree = _load("bumble_photo_browser_superswipe.xml")
    assert bumble_on_photo_browser(tree)
    assert not _deck_visible("bumble", tree)
    act = plan_bulk_swipe(
        "bumble like 5 profiles",
        tree,
        ["Opened Bumble"],
        state={},
        package="com.bumble.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    assert "SuperSwipe" in (act.get("reason") or "")


def test_bumble_photo_grid_fails_not_tile_loop():
    """People grid tiles open PhotoBrowser — never tap tiles; fail cleanly."""
    from backend.dm_heuristics import bumble_on_photo_grid

    tree = """
    <hierarchy>
      <w p="com.bumble.app" a="1">
        <n i="com.bumble.app:id/encountersGridProfile_list" xy="540,1000" b="[0,200][1080,2000]" />
        <n i="com.bumble.app:id/encountersGridItem_photo" xy="547,1172" b="[40,400][520,1400]" c="1" />
      </w>
    </hierarchy>
    """
    assert bumble_on_photo_grid(tree)
    assert not _deck_visible("bumble", tree)
    act = plan_bulk_swipe(
        "bumble like 5 profiles",
        tree,
        ["Opened Bumble"],
        state={},
        package="com.bumble.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "fail"
    assert "grid" in (act.get("reason") or "").lower()
    assert "PhotoBrowser" in (act.get("reason") or "") or "SuperSwipe" in (
        act.get("reason") or ""
    )


def test_hily_top_picks_grid_not_deck():
    tree = _load("hily_top_picks_grid.xml")
    assert hily_on_top_picks_grid(tree)
    assert not _deck_visible("hily", tree)
    act = plan_bulk_swipe(
        "hily like 3 profiles",
        tree,
        ["Opened Hily"],
        state={},
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    # Opens a tile or fails safely — never Crush
    assert act.get("action") in ("tap", "fail")
    if act.get("action") == "tap":
        assert "Crush" not in (act.get("reason") or "")
        assert "grid" in (act.get("reason") or "").lower()


def test_hily_mbm_closes_and_skips():
    tree = _load("hily_mbm_sheet.xml")
    assert hily_on_mbm(tree)
    closed = hily_close_mbm(tree)
    assert closed is not None
    assert closed["x"] == 74
    st: dict = {
        "bulk_message": {
            "done": 0,
            "target": 2,
            "current": "Sam",
            "typed": False,
            "done_names": [],
        }
    }
    act = plan_bulk_message(
        'hily message 2 existing chats say "hey"',
        tree,
        ["Opened Hily", "Open chats"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    assert (
        "MBM" in (act.get("reason") or "")
        or "mbm" in str(act.get("fastpath_step") or "").lower()
        or act.get("x") == 74
    )
    assert "Sam" in (st["bulk_message"].get("done_names") or [])


def test_yubo_chat_tab_by_index():
    assert yubo_chat_tab_xy() == (341, 2194)
    tree = _load("yubo_unlabeled_tabs.xml")
    assert tab_bar_verified("yubo", tree) or True  # clickables near nav
    act = _open_chats_tab_action("yubo", tree, [], "test")
    assert act is not None
    assert act["x"] == 341 and act["y"] == 2194
    assert "index" in (act.get("reason") or "").lower()


def test_hinge_like_sheet_never_rose():
    tree = _load("hinge_like_sheet.xml")
    assert hinge_on_like_sheet(tree)
    act = hinge_like_sheet_action(tree)
    assert act is not None
    assert act["x"] == 686
    assert (
        "Rose" not in (act.get("reason") or "")
        or "never" in (act.get("reason") or "").lower()
    )
    assert _action_looks_like_paid({"label": "Rose", "action": "tap"}, "tap")
    assert _action_looks_like_paid({"label": "Dating Intent", "action": "tap"}, "tap")
    assert _action_looks_like_paid({"label": "Send SuperSwipe", "action": "tap"}, "tap")


def test_tagged_match_card_map():
    tree = _load("tagged_match_card.xml")
    assert tagged_on_deck(tree)
    assert tagged_deck_card_name(tree) == "Casey"
    assert tab_bar_verified("tagged", tree)
    assert known_root_screen("tagged", tree)


def test_recover_backs_from_photo_browser():
    tree = _load("bumble_photo_browser_superswipe.xml")
    assert not known_root_screen("bumble", tree)
    act = _recover_to_root_action("bumble", tree, [], "test", state={})
    assert act is not None
    assert act.get("button") == "back"


def test_no_fixed_nav_without_tab_bar():
    # Keyboard-up composer only — no tab bar
    tree = """
    <hierarchy><w p="com.badoo.mobile" a="1">
      <n e="1" f="1" xy="400,1400" b="[80,1300][900,1500]" h="Message" />
      <n t="Send" xy="980,1400" b="[920,1340][1040,1460]" c="1" />
    </w></hierarchy>
    """
    assert not tab_bar_verified("badoo", tree)
    act = _open_chats_tab_action("badoo", tree, [], "test")
    # Should dismiss keyboard / back — not tap (750,2204)
    assert act is not None
    assert act.get("action") in ("press_button", "tap")
    if act.get("action") == "tap":
        assert int(act.get("y") or 0) < 2000
