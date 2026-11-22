"""Regression: generic open/stuck/dating_deck must NOT replace working per-app rules.

Mac: layer universal_open + stuck_recovery + generic nav as FALLBACK only when
existing maps fail or the screen is stuck. Keep Badoo/BLK swipe, Hily Finder,
thread back-out, popup handling, paid-button firewall intact.
"""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _real_like_action,
    deck_card_name,
    plan_bulk_swipe,
)
from backend.cloud_agent import _is_policy_fail_no_stuck
from backend.dating_deck import plan_free_like
from backend.dm_heuristics import (
    blk_like_action,
    hily_on_top_picks_grid,
)
from backend.stuck_recovery import next_stuck_action
from backend.tap_firewall import guard_tap_action
from backend.universal_open import plan_universal_open, should_escalate_open

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_badoo_voteyes_map_unchanged():
    tree = _load("badoo_encounters.xml")
    assert deck_card_name("badoo", tree) == "Alex"
    mapped = _real_like_action("badoo", tree=tree, planner="t")
    assert mapped and mapped["action"] == "tap"
    assert (mapped["x"], mapped["y"]) == (855, 1982)
    st: dict = {}
    act = plan_bulk_swipe(
        "badoo auto-swipe 5 profiles",
        tree,
        ["Opened Badoo — launch"],
        state=st,
        package="com.badoo.mobile",
    )
    assert act and act["action"] == "tap"
    assert (act["x"], act["y"]) == (855, 1982)
    # Generic free-like must not steal when map hits
    assert "VoteYes" in (act.get("reason") or "") or act.get("x") == 855


def test_blk_like_right_icon_never_super():
    tree = _load("blk_deck.xml")
    like = blk_like_action(tree)
    assert like and like["action"] == "tap"
    mapped = _real_like_action("blk", tree=tree, planner="t")
    assert mapped and (mapped["x"], mapped["y"]) == (like["x"], like["y"])
    st: dict = {}
    act = plan_bulk_swipe(
        "blk auto-swipe 3 profiles",
        tree,
        ["Opened BLK — launch"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act and act["action"] == "tap"
    assert (act["x"], act["y"]) == (like["x"], like["y"])


def test_hily_top_picks_navigates_finder_not_generic_stuck():
    tree = _load("hily_top_picks_grid.xml")
    assert hily_on_top_picks_grid(tree)
    st: dict = {}
    act = plan_bulk_swipe(
        "hily auto-swipe 5 profiles",
        tree,
        ["Opened Hily — launch"],
        state=st,
        package="com.hily.app",
    )
    assert act
    # Must be Finder nav (per-app), not stuck scroll / generic swipe
    reason = (act.get("reason") or "").lower()
    assert act.get("action") == "tap"
    assert "finder" in reason or act.get("label") == "Finder"
    assert act.get("_stuck") is None
    assert "stuck:" not in (act.get("planner") or "")


def test_blk_boost_popup_not_now_not_get_boost():
    tree = _load("blk_boost_peak.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "blk auto-swipe 5 profiles",
        tree,
        ["Opened BLK — launch"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act
    lab = (act.get("label") or act.get("reason") or "").lower()
    assert "get boost" not in lab or "not now" in lab or act.get("button") == "back"
    if act.get("action") == "tap":
        assert "boost" not in (act.get("label") or "").lower() or "not" in lab


def test_thread_back_out_at_job_start_badoo():
    tree = _load("badoo_thread_open.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "badoo auto-swipe 3 profiles",
        tree,
        [],  # job start — no prior open-thread intent
        state=st,
        package="com.badoo.mobile",
    )
    assert act
    assert (
        act.get("action") in ("press_button", "back")
        or "back" in (act.get("reason") or "").lower()
    )
    assert act.get("_stuck") is None


def test_tap_firewall_crush_still_refuses():
    tree = """
    <hierarchy packages="com.hily.app"><w p="com.hily.app">
     <n t="Crush" d="Crush" c="1" xy="540,1800" b="400,1700,680,1900"/>
     <n t="Chats" xy="900,2190" c="1"/>
    </w></hierarchy>
    """
    out = guard_tap_action(
        {"action": "tap", "x": 540, "y": 1800, "reason": "open chats"},
        tree,
        dry_run=True,
    )
    assert (
        out.get("action") in ("fail", "press_button", "back")
        or "refuse" in (out.get("reason") or "").lower()
    )
    assert _is_policy_fail_no_stuck(out.get("reason") or "refuse crush")


def test_policy_fail_does_not_look_like_stuck_candidate():
    assert _is_policy_fail_no_stuck("tap firewall: refuse paid Crush")
    assert _is_policy_fail_no_stuck("refusing Super Like / Rose")
    assert _is_policy_fail_no_stuck("No message text — refuse AI-authored default")
    assert not _is_policy_fail_no_stuck("UI tree is empty — cannot proceed")
    assert not _is_policy_fail_no_stuck("no contacts found in list")


def test_universal_open_escalates_only_when_fg_wrong():
    st: dict = {}
    a0 = plan_universal_open("Bumble", state=st, fg_package="com.bumble.app")
    # Still plans open_app, but should_escalate is False when FG matches
    assert not should_escalate_open(
        want_package="com.bumble.app",
        fg_package="com.bumble.app",
        state=st,
        open_ok=True,
    )
    assert should_escalate_open(
        want_package="com.bumble.app",
        fg_package="com.sec.android.app.launcher",
        state=st,
        open_ok=True,
    )
    assert a0.get("action") == "open_app"


def test_stuck_recovery_is_opt_in_not_default_planner():
    """stuck_recovery returns _stuck marker — bulk heuristics must not set it on happy path."""
    deck = _load("bumble_deck.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        deck,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
    )
    assert act and act.get("action") == "swipe"
    assert act.get("_stuck") is None
    assert not str(act.get("planner") or "").startswith("stuck:")

    # Explicit stuck path still works as fallback
    stuck = next_stuck_action(
        {},
        instruction="bumble auto-swipe 5 profiles",
        ui_tree=deck,
        package="com.bumble.app",
        prefer_pkg="com.bumble.app",
    )
    assert stuck.get("_stuck") or str(stuck.get("planner") or "").startswith("stuck:")


def test_generic_free_like_is_fallback_after_map():
    """When per-app map exists, bulk uses it; plan_free_like alone is secondary."""
    tree = _load("badoo_encounters.xml")
    mapped = _real_like_action("badoo", tree=tree, planner="map")
    generic = plan_free_like("badoo", tree, planner="generic")
    assert mapped and mapped["action"] == "tap"
    assert (mapped["x"], mapped["y"]) == (855, 1982)
    # Generic may also find VoteYes via ids — coords must match free like, not Crush
    if generic and generic.get("action") == "tap":
        assert (generic["x"], generic["y"]) != (1000, 1900)  # Crush
