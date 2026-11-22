"""Incremental: free new-person messaging; paywall → skip → continue (BLK + all)."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import plan_bulk_message_new
from backend.dating_deck import (
    find_free_compose_center,
    skip_new_contact_on_paywall,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_blk_new_opens_match_not_like_only():
    tree = _load("blk_matches.xml")
    st: dict = {}
    act = plan_bulk_message_new(
        'blk message 2 new profiles say "hey there"',
        tree,
        ["Opened BLK — launch"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act
    # Must open a match row (Maya) — not rewrite to like/swipe
    assert act.get("action") == "tap"
    assert act.get("action") != "swipe"
    reason = (act.get("reason") or "").lower()
    assert "maya" in reason or (act.get("label") or "").lower() == "maya"
    assert st.get("bulk_message_new", {}).get("current", "").lower() == "maya"


def test_blk_new_free_composer_dry_run():
    tree = _load("blk_thread.xml")
    st: dict = {"bulk_message_new": {"done": 0, "target": 2, "current": "Maya"}}
    act = plan_bulk_message_new(
        'blk message 2 new profiles say "hey there"',
        tree,
        ["Opened BLK — launch", "Open new match Maya"],
        state=st,
        package="com.affinityapps.blk",
        dry_run=True,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert "never typed" in (act.get("reason") or "").lower()
    assert act.get("would_send_text") == "hey there"


def test_paywall_skips_current_and_continues():
    tree = (
        '<h pkg="com.affinityapps.blk">'
        '<n t="Get Boost" xy="540,1200"/>'
        '<n t="Subscribe" xy="540,1600"/>'
        '<n t="Not now" xy="540,2000" clickable="true"/>'
        "</h>"
    )
    st = {"bulk_message_new": {"done": 0, "current": "Maya", "skipped": []}}
    act = skip_new_contact_on_paywall(
        st, tree=tree, package="com.affinityapps.blk", name="Maya"
    )
    assert act and act.get("_new_contact_paywall_skip") is True
    assert "maya" in [x.lower() for x in st["bulk_message_new"]["skipped"]]
    assert st["bulk_message_new"]["current"] is None
    assert "not now" in (act.get("label") or "").lower() or act.get("button") == "back"

    # Next plan should open Jordan (not Maya)
    matches = _load("blk_matches.xml")
    act2 = plan_bulk_message_new(
        'blk message 2 new profiles say "hey there"',
        matches,
        ["Opened BLK"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act2 and act2.get("action") == "tap"
    assert (act2.get("label") or "").lower() != "maya"
    assert "jordan" in (act2.get("label") or act2.get("reason") or "").lower()


def test_find_free_compose_on_blk_thread():
    tree = _load("blk_thread.xml")
    c = find_free_compose_center(tree)
    assert c is not None
    assert c[1] > 1200


def test_blk_new_no_longer_hard_rewrites_to_swipe():
    """Regression: BLK was like_only — must try Matches first."""
    tree = _load("blk_matches.xml")
    st: dict = {}
    act = plan_bulk_message_new(
        'message "hi" to 3 new profiles on blk',
        tree,
        ["Opened BLK"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act
    assert act.get("action") != "swipe"
    assert "like profile" not in (act.get("reason") or "").lower()
