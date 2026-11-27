"""Facebook Dating first-contact: photo comment is the like; never Spotlight/Crush."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.facebook_dating_fixed_first_contact import (
    DAILY_CAP,
    LIKE_XY,
    PHOTO_COMMENT_TEXT,
    SEND_XY,
    plan_facebook_dating_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_first_contact_facebook_dating():
    g = parse_bulk_goal("send 2 first contact messages on Facebook Dating")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "facebook"
    assert DAILY_CAP == 50
    assert PHOTO_COMMENT_TEXT == "hi miss you look beautiful"


def test_dry_comment_sheet_uses_mac_text_never_types():
    tree = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating", "Tap Facebook Dating profile photo"],
        state={},
        package="com.facebook.katana",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert act.get("would_send_text") == PHOTO_COMMENT_TEXT


def test_live_types_mac_text_then_sends_not_heart():
    tree = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act is not None
    assert act.get("action") == "type"
    assert act.get("text") == "hi miss you look beautiful"
    # Discover typing is a paste (one commit), never chunked human-paced.
    assert act.get("humanize") is False

    # The same empty box again: the type never landed, so Send must NOT be
    # tapped and nothing must count as sent — retype, bounded.
    act_empty = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Type photo comment"],
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act_empty is not None
    assert act_empty.get("action") == "type"
    assert st["bulk_message_new"]["done"] == 0

    # Only once the line is verified in the box does Send happen.
    typed_tree = (FIX / "fb_dating_comment_typed_r46.xml").read_text(
        encoding="utf-8"
    )
    act2 = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        typed_tree,
        ["Type photo comment"],
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act2 is not None
    assert act2.get("action") == "tap"
    assert (act2.get("x"), act2.get("y")) == SEND_XY
    assert (act2.get("x"), act2.get("y")) != LIKE_XY
    assert st["bulk_message_new"]["done"] == 1


def test_profile_taps_heart_to_open_comment_box():
    # Video (24 Nov 2026): the purple heart on the profile opens the
    # "Say something about this photo..." box — it never sends a bare like.
    tree = (FIX / "fb_dating_profile_ellie.xml").read_text(encoding="utf-8")
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating", "Tap Facebook Dating card photo"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) != LIKE_XY
    assert "photo" in (act.get("reason") or "").lower()  # r53: never the heart


def test_explore_backs_out_not_spotlight_or_crush():
    tree = (FIX / "fb_dating_explore.xml").read_text(encoding="utf-8")
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act is not None
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    reason = (act.get("reason") or "").lower()
    assert "spotlight" in reason or "crush" in reason
    assert act.get("x") is None
