"""Hily first-contact: Likes sent → Message Before Match, cap 5, never Crush."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.hily_fixed_first_contact import (
    ACTIVITY_TAB_XY,
    CRUSH_XY,
    DAILY_CAP,
    SEND_XY,
    plan_hily_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_first_contact_hily_bank_and_cap():
    g = parse_bulk_goal("send 2 first contact messages on Hily")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "hily"
    assert g["message"] == "hey how are you"
    assert DAILY_CAP == 5


def test_dry_mbm_sheet_never_types():
    tree = (FIX / "hily_mbm_shann.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        "send 2 first contact messages on Hily",
        tree,
        ["Opened Hily", "Open Hily Likes sent"],
        state={},
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert act.get("would_send_text") == "hey how are you"
    assert "never typed" in (act.get("reason") or "").lower() or "never Crush" in (
        act.get("reason") or ""
    )


def test_live_mbm_types_then_sends_not_crush():
    tree = (FIX / "hily_mbm_shann.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = plan_hily_fixed_first_contact(
        "send 2 first contact messages on Hily",
        tree,
        ["Opened Hily", "Open Hily Likes-sent chat_request"],
        state=st,
        package="com.hily.app",
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "type"
    assert act.get("text") == "hey how are you"

    act2 = plan_hily_fixed_first_contact(
        "send 2 first contact messages on Hily",
        tree,
        ["Opened Hily", "Type MBM first-contact"],
        state=st,
        package="com.hily.app",
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act2 is not None
    assert act2.get("action") == "tap"
    assert (act2.get("x"), act2.get("y")) == SEND_XY
    assert (act2.get("x"), act2.get("y")) != CRUSH_XY
    assert st["bulk_message_new"]["done"] == 1


def test_allowance_zero_stops_without_send():
    tree = (FIX / "hily_mbm_allowance_0.xml").read_text(encoding="utf-8")
    act = plan_hily_fixed_first_contact(
        "send 2 first contact messages on Hily",
        tree,
        ["Opened Hily"],
        state={"bulk_message_new": {"done": 0, "typed": False}},
        dry_run=False,
        message="hello miss",
        target=2,
    )
    assert act is not None
    assert act.get("stopped_reason") == "allowance_exhausted"
    assert (act.get("x"), act.get("y")) != SEND_XY
    assert (act.get("x"), act.get("y")) != CRUSH_XY


def test_likes_sent_taps_chat_request_not_crush():
    tree = (FIX / "hily_likes_sent.xml").read_text(encoding="utf-8")
    act = plan_hily_fixed_first_contact(
        "send 2 first contact messages on Hily",
        tree,
        ["Opened Hily", "Open Hily Activity"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message="hello miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (445, 925)
    assert (act.get("x"), act.get("y")) != CRUSH_XY
    assert "chat_request" in (act.get("reason") or "")


def test_finder_opens_activity_not_crush():
    tree = '<hierarchy><w p="com.hily.app" f="1"><n t="Jorgia, 28" i="userNameAgeField"/><n i="ActionButton_CRUSH" c="1" xy="540,1959"/><n i="ActionButton_LIKE" c="1" xy="750,1959"/><n d="Finder" xy="142,2190"/></w></hierarchy>'
    act = plan_hily_fixed_first_contact(
        "send 2 first contact messages on Hily",
        tree,
        ["Opened Hily"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == ACTIVITY_TAB_XY
    assert (act.get("x"), act.get("y")) != CRUSH_XY
