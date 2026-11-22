"""SAFETY: real Hily Crush-incident tree must Back / refuse chats tap."""

from __future__ import annotations

import json
from pathlib import Path

from backend.bulk_bench_heuristics import plan_bulk_bench, _recover_to_root_action
from backend.dm_heuristics import (
    app_overlay_present,
    hily_on_profile_sheet,
    known_root_screen,
)
from backend.tap_firewall import find_blocking_label_at, guard_tap_action

REAL = (
    Path(__file__).parent / "fixtures" / "real" / "hily_crush_real_tree_20261122.json"
)


def _real_tree() -> str:
    return json.loads(REAL.read_text(encoding="utf-8"))["tree"]


def test_real_tree_profile_sheet_detected():
    tree = _real_tree()
    assert hily_on_profile_sheet(tree) is True
    assert app_overlay_present("hily", tree) == "hily_profile_sheet"
    assert known_root_screen("hily", tree) is False


def test_real_tree_crush_imageview_blocks_point():
    """Non-clickable Crush ImageView at [356,2116][451,2211] must block."""
    tree = _real_tree()
    blocker = find_blocking_label_at(tree, 400, 2163)
    assert blocker is not None
    assert "crush" in (blocker.get("label") or "").lower()


def test_real_tree_guard_refuses_chats_xy():
    tree = _real_tree()
    out = guard_tap_action(
        {"action": "tap", "x": 348, "y": 2188, "dry_run": True},
        tree,
        dry_run=True,
    )
    assert out["action"] == "fail"
    assert "firewall" in out["reason"].lower() or "overlay" in out["reason"].lower()


def test_real_tree_plan_bulk_backs_out_of_sheet():
    tree = _real_tree()
    act = plan_bulk_bench(
        'reply "hey how are you" to 5 existing chats on Hily',
        tree,
        ["Opened Hily[com.hily.app]"],
        state={},
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    assert act["action"] == "press_button"
    assert act["button"] == "back"
    assert "sheet" in act["reason"].lower() or "crush" in act["reason"].lower()


def test_real_tree_recover_before_known_root():
    tree = _real_tree()
    # Overlay present even though Discover grid + bottom-nav are in the dump
    act = _recover_to_root_action(
        "hily",
        tree,
        ["Opened Hily[com.hily.app]"],
        "test",
        state={},
    )
    assert act is not None
    assert act["action"] == "press_button"
    assert act["button"] == "back"
