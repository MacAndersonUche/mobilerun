"""APK 530 follow-ups: target-window trees, reply open-thread, BLK/Hily detectors."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _app_tree_empty,
    _deck_markers_ok,
    _deck_visible,
    _open_chats_tab_action,
    _visible_chat_list_rows,
    plan_bulk_message,
    plan_bulk_message_new,
)
from backend.dm_heuristics import (
    _parse_compact_nodes,
    blk_deck_card_name,
    blk_dismiss_popup,
    blk_like_action,
    blk_on_deck,
    hily_close_mbm,
    hily_on_mbm,
    open_chat_thread_present,
    tagged_chat_action,
    tagged_on_deck,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_spay_only_tree_empty_for_taimi():
    spay = """<hierarchy packages="com.samsung.android.spay">
    <w id="active" p="com.samsung.android.spay" f="1">
     <n t="Samsung Pay" xy="540,200"/>
    </w></hierarchy>"""
    assert _app_tree_empty(spay, "taimi")


def test_spay_overlay_still_reads_taimi_window():
    tree = _load("spay_overlay_wrong_fg.xml")
    taimi_nodes = _parse_compact_nodes(tree, package_filter="com.takimi.android")
    assert any("Alex" in (n.get("text") or "") for n in taimi_nodes)
    # Full dump is not empty for Taimi when target window is present
    assert not _app_tree_empty(tree, "taimi")


def test_reply_dry_run_opens_thread_not_list_only():
    tree = _load("bumble_connections.xml")
    act = plan_bulk_message(
        'reply "hey" to 1 existing chat on Bumble',
        tree,
        ["Opened Bumble"],
        package="com.bumble.app",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "tap"
    assert "did not open" not in (act.get("reason") or "").lower()
    assert "Open" in (act.get("reason") or "")


def test_reply_row_excludes_section_headers_and_menu():
    tree = """
    <hierarchy packages="com.bumble.app"><w p="com.bumble.app">
     <n t="Live now" xy="200,300" c="1"/>
     <n t="Older chats" xy="200,500"/>
     <n t="Unmatch · Report · Did you meet?" xy="300,700" c="1"/>
     <n t="+1 555-0100" xy="300,900" c="1"/>
     <n t="Sam" i="com.bumble.app:id/connectionsItem_personName" c="1" xy="300,1100"/>
    </w></hierarchy>
    """
    rows = _visible_chat_list_rows(tree, "bumble")
    names = {r["name"].lower() for r in rows}
    assert "live now" not in names
    assert "older chats" not in names
    assert "unmatch · report · did you meet?" not in names
    assert "+1 555-0100" not in names
    assert "sam" in names


def test_hily_mbm_row_is_not_sheet():
    tree = _load("hily_mbm_row_not_sheet.xml")
    assert not hily_on_mbm(tree)
    assert hily_close_mbm(tree) is None
    act = plan_bulk_message(
        'reply "hi" to 1 existing chat on Hily',
        tree,
        ["Opened Hily"],
        package="com.hily.app",
        dry_run=True,
        state={},
    )
    assert act is not None
    assert not (
        act.get("action") == "press_button"
        and "mbm" in (act.get("reason") or "").lower()
    )
    # Should open Paige (or Alex) as a real row
    assert act.get("action") == "tap"
    assert "Paige" in (act.get("reason") or "") or "Alex" in (act.get("reason") or "")


def test_blk_age_card_detected():
    tree = _load("blk_deck_age_actions.xml")
    assert blk_on_deck(tree)
    assert blk_deck_card_name(tree) in ("Jordan", "age_29")
    assert _deck_visible("blk", tree)
    assert _deck_markers_ok("blk", tree)
    like = blk_like_action(tree)
    assert like and like.get("action") == "tap"
    # Heart is middle of X/heart/crown
    assert 400 <= int(like["x"]) <= 700


def test_blk_boost_peak_dismiss_never_get_boost():
    tree = _load("blk_boost_peak.xml")
    act = blk_dismiss_popup(tree, planner="test")
    assert act is not None
    reason = (act.get("reason") or "").lower()
    assert "boost" in reason or act.get("button") == "back"
    assert "get boost" not in reason
    if act.get("action") == "tap":
        # Not now at y=1800, never Get Boost at y=1600
        assert int(act["y"]) != 1600


def test_blk_matches_opens_real_row_not_scroll_loop():
    tree = _load("blk_matches.xml")
    rows = _visible_chat_list_rows(tree, "blk")
    names = {r["name"] for r in rows}
    assert "Maya" in names
    assert "Jordan" in names
    assert "HiddenPerson" not in names
    assert "hey" not in {n.lower() for n in names}
    act = plan_bulk_message(
        'reply "hi" to 1 existing chat on BLK',
        tree,
        ["Opened BLK", "Open Matches tab"],
        package="com.affinityapps.blk",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "tap"
    assert "Maya" in (act.get("reason") or "") or "Jordan" in (act.get("reason") or "")
    assert "Scroll" not in (act.get("reason") or "")


def test_yubo_chats_tab_never_taps_header_chat():
    tree = """
    <hierarchy packages="co.yellw.yellowapp"><w p="co.yellw.yellowapp">
     <n t="Chat" xy="116,159"/>
     <n t="Conversations" xy="200,400"/>
     <n t="Alex" xy="200,1200" c="1"/>
     <n c="1" xy="140,2194" b="40,2140,240,2240"/>
     <n c="1" xy="340,2194" b="240,2140,440,2240"/>
     <n c="1" xy="540,2194" b="440,2140,640,2240"/>
     <n c="1" xy="740,2194" b="640,2140,840,2240"/>
    </w></hierarchy>
    """
    act = _open_chats_tab_action("yubo", tree, [], "test")
    # Already on Conversations list → either None (verified) or bottom-band tap
    if act and act.get("action") == "tap":
        assert int(act["y"]) >= 1800
        assert int(act["y"]) != 159


def test_tagged_chatbtn_on_match_card():
    tree = _load("tagged_match_card.xml")
    assert tagged_on_deck(tree)
    chat = tagged_chat_action(tree, planner="test")
    assert chat and chat.get("action") == "tap"
    assert 400 <= int(chat["x"]) <= 700
    act = plan_bulk_message_new(
        'message 1 new contacts on Tagged saying "hey"',
        tree,
        ["Opened Tagged"],
        package="com.taggedapp",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert (
        "chatBtn" in (act.get("reason") or "")
        or "match" in (act.get("reason") or "").lower()
    )


def test_bumble_thread_still_opens_for_dry_run_compose():
    tree = _load("bumble_thread_aa.xml")
    assert open_chat_thread_present("bumble", tree)
    st = {
        "bulk_message": {
            "done": 0,
            "target": 1,
            "current": "Yuly",
            "typed": False,
        }
    }
    act = plan_bulk_message(
        'reply "hi" to 1 existing chat on Bumble',
        tree,
        ["Opened Bumble", "Open Yuly"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act.get("action") == "type"
