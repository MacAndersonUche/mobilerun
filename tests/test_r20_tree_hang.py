"""r20: tree text_nodes→vision, BLK container firewall, hang fail-fast."""

from backend.tap_firewall import (
    _is_generic_container_id,
    guard_tap_action,
    intended_target_matches,
)
from backend.bulk_bench_heuristics import plan_bulk_message


def test_generic_container_id_detects_blk_container():
    assert _is_generic_container_id("com.affinityapps.blk:id/container")
    assert _is_generic_container_id("id/container")
    assert not _is_generic_container_id("com.affinityapps.blk:id/like_button")


def test_blk_container_intended_match_allows_like():
    resolved = {
        "id": "com.affinityapps.blk:id/container",
        "label": "",
        "text": "",
        "x": 540,
        "y": 1200,
    }
    action = {"label": "Like", "reason": "BLK Like"}
    assert intended_target_matches(resolved, action, point_labels="Like Icon")


def test_blk_container_firewall_allows_tap():
    tree = (
        '<hierarchy><w p="com.affinityapps.blk" f="1">'
        '<n i="com.affinityapps.blk:id/container" c="1" xy="540,1200" '
        'b="0,400,1080,2000"/>'
        '<n t="Like" d="Like Icon" xy="860,1900" c="1" b="800,1850,920,1950"/>'
        "</w></hierarchy>"
    )
    out = guard_tap_action(
        {
            "action": "tap",
            "x": 540,
            "y": 1200,
            "label": "Like",
            "reason": "BLK Like",
        },
        tree,
        dry_run=True,
    )
    assert out.get("action") == "tap"
    assert "intended target" not in (out.get("reason") or "").lower()


def test_chat_list_settle_fails_fast_not_loops():
    # After open chats + one settle, next plan must fail — not wait again
    tree = (
        '<hierarchy><w p="com.affinityapps.blk" f="1">'
        '<n t="Discover" xy="135,2170" c="1"/>'
        "</w></hierarchy>"
    )
    state = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": None,
            "_chats_settle_done": True,
            "_chats_settle_n": 1,
        }
    }
    hist = [
        "Opened BLK[open_ok]",
        "tap(675,2170) — Open Matches tab (bulk_open_chats)",
        "wait — Settle 1.5s after chats tab before re-check",
    ]
    act = plan_bulk_message(
        'reply to 5 chats on BLK with "hey"',
        tree,
        hist,
        package="com.affinityapps.blk",
        dry_run=True,
        state=state,
    )
    assert act is not None
    assert act.get("action") == "fail"
    assert (
        "fail fast" in (act.get("reason") or "").lower()
        or "not verified" in (act.get("reason") or "").lower()
    )
    assert act.get("action") != "wait"
