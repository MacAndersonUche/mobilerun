"""BLK Discover first-contact: no free path; never Send a message / Super / Boost."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.blk_fixed_first_contact import (
    GET_BOOST_XY,
    SEND_A_MESSAGE_XY,
    SUPER_LIKE_XY,
    plan_blk_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_first_contact_blk():
    g = parse_bulk_goal("send 2 first contact messages on BLK")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "blk"
    assert g["first_contact"] is True
    assert g["message"] == "hey how are you"


def test_end_of_feed_stops_without_taps():
    tree = (FIX / "blk_end_deck.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        "send 2 first contact messages on BLK",
        tree,
        ["Opened BLK"],
        state={},
        package="com.affinityapps.blk",
        dry_run=False,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("stopped_reason") == "no_free_first_contact"
    assert "end of feed" in (act.get("reason") or "").lower()
    assert act.get("x") is None
    assert not act.get("needs_vision")


def test_discover_card_does_not_tap_paid_send_a_message():
    tree = (FIX / "blk_deck.xml").read_text(encoding="utf-8")
    act = plan_blk_fixed_first_contact(
        "send 2 first contact messages on BLK",
        tree,
        ["Opened BLK", "Open BLK Discover"],
        state={},
        package="com.affinityapps.blk",
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("stopped_reason") == "no_free_first_contact"
    assert "paid" in (act.get("reason") or "").lower()
    xy = (act.get("x"), act.get("y"))
    assert xy != SEND_A_MESSAGE_XY
    assert xy != SUPER_LIKE_XY
    assert xy != GET_BOOST_XY
    assert not act.get("needs_vision")


def test_boost_peak_dismisses_not_get_boost():
    tree = (FIX / "blk_boost_peak.xml").read_text(encoding="utf-8")
    act = plan_blk_fixed_first_contact(
        "send 2 first contact messages on BLK",
        tree,
        ["Opened BLK"],
        state={},
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    if act.get("action") == "tap":
        assert (act.get("x"), act.get("y")) != GET_BOOST_XY
        reason = (act.get("reason") or "").lower()
        assert "boost" in reason
        assert "get boost" not in reason or "never" in reason
    else:
        assert act.get("action") in ("press_button", "done")
        if act.get("action") == "press_button":
            assert act.get("button") == "back"
