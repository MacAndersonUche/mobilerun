"""22 Nov real-phone dry-run follow-ups (back-to-root, false passes, firewall)."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _deck_markers_ok,
    _deck_visible,
    _recover_to_root_action,
    _visible_chat_list_rows,
    plan_bulk_message_new,
    plan_bulk_swipe,
)
from backend.dm_heuristics import (
    blk_deck_card_name,
    open_chat_thread_present,
    yubo_on_deck,
)
from backend.tap_firewall import guard_tap_action, resolve_topmost_clickable_at

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_open_thread_bumble_aa():
    tree = _load("bumble_thread_aa.xml")
    assert open_chat_thread_present("bumble", tree)
    act = _recover_to_root_action("bumble", tree, [], "test", state={})
    assert act and act.get("action") == "press_button"
    assert act.get("button") == "back"


def test_open_thread_tagged_soila():
    tree = _load("tagged_thread_open.xml")
    assert open_chat_thread_present("tagged", tree)
    act = _recover_to_root_action("tagged", tree, [], "test", state={})
    assert act and act.get("button") == "back"


def test_open_thread_badoo_yuly():
    tree = _load("badoo_thread_open.xml")
    assert open_chat_thread_present("badoo", tree)
    act = _recover_to_root_action("badoo", tree, [], "test", state={})
    assert act and act.get("button") == "back"


def test_open_thread_whatsapp_announcements():
    tree = _load("whatsapp_announcements_thread.xml")
    assert open_chat_thread_present("whatsapp", tree)
    act = _recover_to_root_action("whatsapp", tree, [], "test", state={})
    assert act and act.get("button") == "back"


def test_yubo_chat_tab_not_deck_false_pass():
    tree = _load("yubo_chat_tab_false_deck.xml")
    assert not yubo_on_deck(tree)
    assert not _deck_visible("yubo", tree)
    assert not _deck_markers_ok("yubo", tree)
    act = plan_bulk_swipe(
        "yubo like 3 profiles",
        tree,
        ["Opened Yubo"],
        state={},
        package="co.yellw.yellowapp",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") in ("fail", "tap", "press_button", "wait")
    if act.get("action") == "done":
        raise AssertionError(f"false pass on Chat tab: {act}")


def test_blk_education_filter_not_card_name():
    tree = _load("blk_education_filter.xml")
    assert blk_deck_card_name(tree) is None
    assert not _deck_markers_ok("blk", tree)
    act = plan_bulk_swipe(
        "blk like 2 profiles",
        tree,
        ["Opened BLK"],
        state={},
        package="com.affinityapps.blk",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") != "done" or act.get("dry_run_verified") is not True


def test_firewall_allows_blk_matches_near_bounds():
    """Tap just outside Matches bounds must still resolve the tab (child label)."""
    tree = _load("blk_deck.xml")
    top = resolve_topmost_clickable_at(tree, 674, 2223)
    assert top is not None
    blob = f"{top.get('label')} {top.get('desc')} {top.get('id')}".lower()
    assert "match" in blob
    out = guard_tap_action(
        {
            "action": "tap",
            "x": 674,
            "y": 2223,
            "label": "Matches",
            "reason": "Open Matches tab",
        },
        tree,
        dry_run=True,
    )
    assert out["action"] == "tap", out


def test_firewall_refuses_status_bar():
    tree = _load("yubo_deck.xml")
    out = guard_tap_action(
        {"action": "tap", "x": 377, "y": 46, "reason": "bad header"},
        tree,
        dry_run=True,
    )
    assert out["action"] == "fail"
    assert "status" in out["reason"].lower()


def test_firewall_empty_tree_vision_allows_free_nav():
    out = guard_tap_action(
        {
            "action": "tap",
            "x": 540,
            "y": 2000,
            "label": "Like",
            "reason": "vision like",
        },
        '<hierarchy empty="true" nodes="0"/>',
        dry_run=True,
        vision_confirmed_label="Like button on deck",
    )
    assert out["action"] == "tap"
    assert out.get("_tap_firewall") == "vision_confirmed"


def test_firewall_empty_tree_vision_refuses_rose():
    out = guard_tap_action(
        {"action": "tap", "x": 540, "y": 1800, "label": "Rose"},
        '<hierarchy empty="true" nodes="0"/>',
        dry_run=True,
        vision_confirmed_label="Rose paid upsell",
    )
    assert out["action"] == "fail"


def test_hily_swipe_leaves_top_picks_for_finder():
    tree = _load("hily_top_picks_grid.xml")
    act = plan_bulk_swipe(
        "hily like 3 profiles",
        tree,
        ["Opened Hily"],
        state={},
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "Finder" in (act.get("reason") or "") or act.get("label") == "Finder"


def test_hily_new_contact_leaves_top_picks_for_chats():
    tree = _load("hily_top_picks_grid.xml")
    act = plan_bulk_message_new(
        'message "hey" to 2 new profiles on Hily',
        tree,
        ["Opened Hily"],
        state={},
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "Chats" in (act.get("reason") or "") or act.get("label") == "Chats"


def test_chat_header_not_a_row():
    tree = _load("yubo_chat_list.xml")
    rows = _visible_chat_list_rows(tree, "yubo")
    names = {r["name"].lower() for r in rows}
    assert "chat" not in names
    assert "reactions" not in names
    assert "new friends" not in names
    # Header-height nodes must never be rows
    assert all(int(r["y"]) >= 200 for r in rows)
    # With match_row ids, contact names are accepted
    tree2 = """
    <hierarchy>
      <w p="co.yellw.yellowapp">
        <n t="Chat" xy="343,120" b="250,80,430,160"/>
        <n t="Sam" i="id/match_row" c="1" xy="242,1200" b="200,1160,360,1240"/>
        <n t="Riley" i="id/match_name" c="1" xy="242,1400" b="200,1360,360,1440"/>
      </w>
    </hierarchy>
    """
    rows2 = _visible_chat_list_rows(tree2, "yubo")
    names2 = {r["name"].lower() for r in rows2}
    assert "chat" not in names2
    assert "sam" in names2 and "riley" in names2


def test_blk_streaks_got_it_not_back_loop():
    from backend.dm_heuristics import blk_dismiss_popup

    tree = _load("blk_streaks_popup.xml")
    act = blk_dismiss_popup(tree, planner="test")
    assert act and act.get("action") == "tap"
    assert "got it" in (act.get("reason") or "").lower()
