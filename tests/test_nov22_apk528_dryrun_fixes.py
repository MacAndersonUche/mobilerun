"""APK 528 follow-ups: reply loop, detectors, dry-run counts, vision FG."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _app_tree_empty,
    _open_chats_tab_action,
    _recover_to_root_action,
    _visible_chat_list_rows,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.dm_heuristics import (
    blk_end_of_deck,
    hily_close_mbm,
    open_chat_thread_present,
    tagged_like_action,
    yubo_on_chat_list,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_reply_loop_backs_leftover_thread_at_job_start():
    tree = _load("bumble_thread_aa.xml")
    assert open_chat_thread_present("bumble", tree)
    act = _recover_to_root_action("bumble", tree, [], "test", state={})
    assert act and act.get("button") == "back"
    assert "open_chat_thread" in (act.get("reason") or "")


def test_reply_loop_skips_recover_when_target_thread_open():
    tree = _load("bumble_thread_aa.xml")
    act = _recover_to_root_action(
        "bumble", tree, [], "test", state={}, allow_open_thread=True
    )
    assert act is None
    st = {
        "bulk_message": {
            "done": 0,
            "target": 1,
            "current": "Yuly",
            "typed": False,
        }
    }
    msg = plan_bulk_message(
        'reply "hi" to 1 existing chat on Bumble',
        tree,
        ["Opened Bumble", "Open Yuly"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert msg is not None
    assert msg.get("action") != "press_button" or msg.get("button") != "back"
    assert msg.get("action") in ("type", "tap", "done")
    assert "Yuly" in (msg.get("reason") or "") or msg.get("action") == "type"


def test_tagged_like_not_dislikebtn_substring():
    tree = _load("tagged_match_card.xml")
    like = tagged_like_action(tree)
    assert like and like.get("action") == "tap"
    assert int(like["x"]) == 860  # likeBtn, not dislikeBtn at x=220


def test_badoo_dry_run_reports_evaluated_one():
    tree = _load("badoo_encounters.xml")
    act = plan_bulk_swipe(
        "like 5 profiles on Badoo",
        tree,
        ["Opened Badoo"],
        package="com.badoo.mobile",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "done"
    assert act.get("bulk_swipe_evaluated") == 1
    assert act.get("bulk_swipe_done") == 1
    assert act.get("bulk_swipe_target") == 5
    assert "evaluated 1 card" in (act.get("reason") or "")
    assert "would like/pass 5" in (act.get("reason") or "")


def test_blk_open_tab_label_is_matches():
    tree = _load("blk_deck.xml")
    act = _open_chats_tab_action("blk", tree, [], "test")
    assert act and act.get("action") == "tap"
    assert act.get("label") == "Matches"
    assert "Matches" in (act.get("reason") or "")


def test_blk_oh_no_end_of_deck_is_done_not_fail():
    tree = _load("blk_end_deck_oh_no.xml")
    assert blk_end_of_deck(tree)
    act = plan_bulk_swipe(
        "like 3 profiles on BLK",
        tree,
        ["Opened BLK"],
        package="com.affinityapps.blk",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "done"
    assert (
        act.get("stopped_reason") == "end_of_deck"
        or "end of deck" in (act.get("reason") or "").lower()
    )


def test_hily_close_mbm_no_map_xy_without_close():
    tree = _load("hily_mbm.xml")
    act = hily_close_mbm(tree, planner="test")
    assert act is not None
    # Must not blind-tap (74,160) Chats title
    if act.get("action") == "tap":
        assert not (int(act.get("x") or 0) == 74 and int(act.get("y") or 0) == 160)
    else:
        assert act.get("button") == "back"


def test_hily_close_mbm_none_when_no_sheet():
    tree = _load("hily_chats.xml")
    assert hily_close_mbm(tree) is None


def test_yubo_chat_header_not_tapped_as_tab():
    tree = _load("yubo_chat_header_trap.xml")
    assert yubo_on_chat_list(tree)
    act = _open_chats_tab_action("yubo", tree, [], "test")
    # Already-tried hist empty — if it returns a tap, must be bottom band
    if act and act.get("action") == "tap":
        assert int(act["y"]) >= 1800
        assert int(act["y"]) != 159
    rows = _visible_chat_list_rows(tree, "yubo")
    names = {r["name"].lower() for r in rows}
    assert "chat" not in names
    assert "sam" in names or "riley" in names


def test_yubo_swipe_leaves_chat_list_for_deck():
    tree = _load("yubo_chat_list.xml")
    act = plan_bulk_swipe(
        "like 2 profiles on Yubo",
        tree,
        ["Opened Yubo"],
        package="co.yellw.yellowapp",
        dry_run=True,
        state={},
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "deck" in (act.get("reason") or "").lower() or act.get("label") == "Deck"


def test_whatsapp_skips_community_announcement_rows():
    tree = _load("wa_community_row.xml")
    rows = _visible_chat_list_rows(tree, "whatsapp")
    names = {r["name"].lower() for r in rows}
    assert "community" not in names
    assert "announcements" not in names
    assert "precious achalugo" in names
    assert "hi" not in names  # message preview


def test_dry_run_message_verifies_list_without_opening():
    tree = _load("bumble_connections.xml")
    act = plan_bulk_message(
        'reply "hey" to 2 existing chats on Bumble',
        tree,
        ["Opened Bumble"],
        package="com.bumble.app",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert "did not open" in (act.get("reason") or "").lower()
    assert "Open Sam" not in (act.get("reason") or "")


def test_selfhosted_fg_counts_as_empty_target_tree():
    tree = _load("selfhosted_fg_sparse.xml")
    assert _app_tree_empty(tree, "hinge")
    assert _app_tree_empty(tree, "taimi")
    act = _recover_to_root_action("hinge", tree, [], "test", state={})
    assert act is not None
    assert act.get("needs_vision") is True or act.get("_force_vision") is True
    assert act.get("action") in ("open_app", "wait", "fail")
