"""Hinge first-contact: fixed photo heart + comment + Send Like, never Rose."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.hinge_fixed_first_contact import (
    MESSAGE_BANK,
    PHOTO_HEART_XY,
    ROSE_BOUNDS,
    SEND_LIKE_XY,
    in_rose_bounds,
    plan_hinge_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_first_contact_uses_message_bank():
    g = parse_bulk_goal("send 2 first contact messages on Hinge")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "hinge"
    assert g["contact_scope"] == "new"
    assert g["first_contact"] is True
    assert g["message"] == MESSAGE_BANK[0]


def test_parse_first_contact_respects_quoted_bank_line():
    g = parse_bulk_goal('send 2 first-contact messages "hi miss" on Hinge')
    assert g is not None
    assert g["message"] == "hi miss"
    assert g["count"] == 2
    assert g["app"] == "hinge"


def test_live_empty_discover_taps_photo_heart_not_vision():
    tree = (FIX / "hinge_empty_tree.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False, "_opened_discover": True}}
    act = plan_bulk_bench(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Open Hinge Discover tab"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == PHOTO_HEART_XY
    assert not act.get("needs_vision")
    assert not act.get("_force_vision")
    assert "photo heart" in (act.get("reason") or "").lower()
    assert act.get("planner", "").endswith("_no_llm_handoff")


def test_dry_empty_discover_does_not_tap_or_type():
    tree = (FIX / "hinge_empty_tree.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge"],
        state={},
        package="co.hinge.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run") is True
    assert act.get("dry_run_verified") is True
    assert act.get("would_send_text") == MESSAGE_BANK[0]
    assert "never Rose" in (act.get("reason") or "") or "never typed" in (
        act.get("reason") or ""
    )


def test_like_sheet_types_then_send_like_not_rose():
    tree = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Hinge Discover photo heart", "Focus Add a comment field"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "type"
    assert act.get("text") == "hi miss"
    # Discover typing is a paste (one commit), never chunked human-paced.
    assert act.get("humanize") is False

    # The same empty box again: the type never landed, so Send Like must
    # NOT be tapped and nothing must count as sent — retype, bounded.
    act_empty = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Type like-sheet comment"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act_empty is not None
    assert act_empty.get("action") == "type"
    assert st["bulk_message_new"]["done"] == 0

    # Only once the line is verified in the box does Send Like happen.
    typed_tree = (FIX / "hinge_like_sheet_typed.xml").read_text(encoding="utf-8")
    act2 = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        typed_tree,
        ["Opened Hinge", "Type like-sheet comment"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act2 is not None
    assert act2.get("action") == "tap"
    assert not in_rose_bounds(int(act2["x"]), int(act2["y"]))
    assert int(act2["x"]) == SEND_LIKE_XY[0] or "Send Like" in (act2.get("reason") or "")
    assert "Rose" in (act2.get("reason") or "")  # "never Rose"
    x0, y0, x1, y1 = ROSE_BOUNDS
    assert not (x0 <= int(act2["x"]) <= x1 and y0 <= int(act2["y"]) <= y1)
    assert st["bulk_message_new"]["done"] == 1


def test_likes_you_goes_to_discover_not_boost():
    tree = (
        'n text="Likes You" n text="Boost" n text="Upgrade to HingeX" '
        'package="co.hinge.app"'
    )
    act = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (110, 2195)
    reason = (act.get("reason") or "").lower()
    assert "discover" in reason
    assert "boost" in reason or "hingex" in reason


def test_send_like_coords_are_not_rose():
    assert not in_rose_bounds(*SEND_LIKE_XY)
    assert in_rose_bounds(231, 1269)
    assert PHOTO_HEART_XY[0] == 937
