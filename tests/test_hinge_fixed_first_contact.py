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


def _rose_tree(typed: bool = True, anyway: bool = True) -> str:
    tree = (FIX / "hinge_rose_popup.xml").read_text(encoding="utf-8")
    if not typed:
        tree = tree.replace('t="hi miss" e="1"', 't="" e="1"')
    if not anyway:
        tree = "\n".join(
            line for line in tree.splitlines() if "Send Like anyway" not in line
        )
    return tree


def test_rose_popup_after_send_taps_anyway_without_recount():
    # Video: Send Like already went through, the Rose sheet pops up after.
    # "Send Like anyway" confirms it as a free like — never "Send a Rose",
    # and the send is NOT counted a second time.
    tree = _rose_tree(typed=True)
    st = {"bulk_message_new": {"done": 1, "typed": False, "just_sent": True}}
    act = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Type like-sheet comment", "Send Like"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (540, 1060)
    assert "anyway" in (act.get("reason") or "").lower()
    assert "rose" in (act.get("reason") or "").lower()
    assert st["bulk_message_new"]["done"] == 1


def test_rose_popup_with_verified_comment_sends_via_anyway():
    # The comment is verified in the box: the anyway tap IS the send.
    tree = _rose_tree(typed=True)
    st = {"bulk_message_new": {"done": 0, "typed": True}}
    act = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Type like-sheet comment"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (540, 1060)
    assert (act.get("x"), act.get("y")) != SEND_LIKE_XY
    assert st["bulk_message_new"]["done"] == 1
    assert st["bulk_message_new"]["just_sent"] is True


def test_rose_popup_before_typing_backs_out_not_bare_like():
    # Popup before the comment was typed: Back to the sheet and type
    # first — never send a bare like, never tap Rose.
    tree = _rose_tree(typed=False)
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Hinge Discover photo heart"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    assert act.get("x") is None
    assert st["bulk_message_new"]["done"] == 0


def test_rose_popup_without_anyway_node_backs_out_never_map():
    # No tree node for "Send Like anyway": Back out. The map Send Like
    # coords sit between the Rose button and the anyway link on this
    # sheet, so guessing them could tap Rose.
    tree = _rose_tree(typed=True, anyway=False)
    st = {"bulk_message_new": {"done": 0, "typed": True}}
    act = plan_hinge_fixed_first_contact(
        "send 2 first contact messages on Hinge",
        tree,
        ["Opened Hinge", "Type like-sheet comment"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    assert act.get("x") is None
    assert st["bulk_message_new"]["done"] == 0
