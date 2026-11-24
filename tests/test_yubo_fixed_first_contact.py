"""Yubo first-contact: New friends Say-hello thread; never Blast/Yubucks/Infinity."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.yubo_fixed_first_contact import (
    SEND_XY,
    YUBUCKS_XY,
    plan_yubo_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_first_contact_yubo():
    g = parse_bulk_goal("send 2 first contact messages on Yubo")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "yubo"
    assert g["message"] == "hey how are you"


def test_dry_say_hello_never_types():
    tree = (FIX / "yubo_say_hello.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        "send 2 first contact messages on Yubo",
        tree,
        ["Opened Yubo", "Open Yubo New friends contact"],
        state={},
        package="co.yellw.yellowapp",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert act.get("would_send_text") == "hey how are you"


def test_live_types_then_sends_not_yubucks():
    tree = (FIX / "yubo_say_hello.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = plan_yubo_fixed_first_contact(
        "send 2 first contact messages on Yubo",
        tree,
        ["Opened Yubo"],
        state=st,
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "type"
    assert act.get("text") == "hey how are you"
    act2 = plan_yubo_fixed_first_contact(
        "send 2 first contact messages on Yubo",
        tree,
        ["Type Yubo first-contact"],
        state=st,
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act2 is not None
    assert act2.get("action") == "tap"
    assert act2.get("x") == SEND_XY[0]
    assert abs(int(act2.get("y")) - SEND_XY[1]) <= 2
    assert (act2.get("x"), act2.get("y")) != YUBUCKS_XY
    # r45: counted only once the box is empty (message went)
    assert st["bulk_message_new"]["done"] == 0
    assert st["bulk_message_new"]["awaiting_sent"] == "hey how are you"
    plan_yubo_fixed_first_contact(
        "send 2 first contact messages on Yubo",
        tree,
        ["Yubo Send first-contact 1/2"],
        state=st,
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert st["bulk_message_new"]["done"] == 1


def test_new_friends_taps_person_not_reactions_or_infinity():
    tree = (FIX / "yubo_new_friends.xml").read_text(encoding="utf-8")
    act = plan_yubo_fixed_first_contact(
        "send 2 first contact messages on Yubo",
        tree,
        ["Opened Yubo", "Open Yubo Chat tab"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message="hello miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (458, 420)
    reason = (act.get("reason") or "").lower()
    assert "new friends" in reason


def test_direct_sheet_selects_direct_not_blast():
    tree = (FIX / "yubo_direct_sheet.xml").read_text(encoding="utf-8")
    act = plan_yubo_fixed_first_contact(
        "send 2 first contact messages on Yubo",
        tree,
        ["Opened Yubo", "Tap Send a message"],
        state={"bulk_message_new": {"done": 0, "typed": False}},
        dry_run=False,
        message="hi miss",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    # Unselected Direct in the fixture is (855, 656)
    assert (act.get("x"), act.get("y")) == (855, 656)
    assert "direct" in (act.get("reason") or "").lower()
    assert "blast" in (act.get("reason") or "").lower() or "never" in (
        act.get("reason") or ""
    ).lower()


def test_infinity_backs_out():
    tree = (FIX / "yubo_popup_infinity.xml").read_text(encoding="utf-8")
    act = plan_yubo_fixed_first_contact(
        "send 2 first contact messages on Yubo",
        tree,
        ["Opened Yubo"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    assert act.get("stopped_reason") == "paywall"
