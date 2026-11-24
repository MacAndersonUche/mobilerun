"""Discover first-contact: typing must land before Send, for both apps.

Regression tests for the Nov 2026 failure on Mac's phone: on Facebook
Dating the bot never typed into the "Say something about this photo" box
and never sent, and on Hinge it opened the message tab but never typed.
Shared cause: both planners set typed=True when *issuing* the type action
and tapped Send (counting a send) without ever checking the box contained
the line, while the executor reported "Typed" on a device ACK that never
proved the text landed. These tests pin the fixed behaviour:

- Send (Facebook) / Send Like (Hinge) only when the exact line is verified
  in the box; an empty box after a type is a bounded retype, then an
  honest fail — never a Send, never a counted send.
- The box is focused first (tree-verified, not history) and typed as a
  paste (humanize=False, one commit).
- After a Send, a lingering sheet is waited out and backed out of — the
  planner never re-types on it.
- The executor passes humanize through to the device (paste for Discover,
  human-paced by default elsewhere).
"""

from __future__ import annotations

from pathlib import Path

from backend.dm_heuristics import compose_box_focused, compose_box_text
from backend.facebook_dating_fixed_first_contact import (
    PHOTO_COMMENT_TEXT,
    SEND_XY,
    plan_facebook_dating_fixed_first_contact,
)
from backend.hinge_fixed_first_contact import (
    MESSAGE_BANK,
    SEND_LIKE_XY,
    in_rose_bounds,
    plan_hinge_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"

FB_INSTR = "send 2 first contact messages on Facebook Dating"
HINGE_INSTR = "send 2 first contact messages on Hinge"


def _fb(tree, st, hist, **kw):
    return plan_facebook_dating_fixed_first_contact(
        FB_INSTR,
        tree,
        hist,
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
        **kw,
    )


def _hinge(tree, st, hist, message="hi miss", **kw):
    return plan_hinge_fixed_first_contact(
        HINGE_INSTR,
        tree,
        hist,
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message=message,
        target=2,
        **kw,
    )


# --- shared compose-box helpers -------------------------------------------


def test_compose_box_text_and_focused():
    sheet = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    # Empty box still shows its placeholder as the node text; focused.
    assert compose_box_text(sheet) == "Say something about this photo..."
    assert compose_box_focused(sheet) is True
    typed = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    assert compose_box_text(typed) == PHOTO_COMMENT_TEXT
    assert compose_box_focused(typed) is True
    assert compose_box_text("<hierarchy></hierarchy>") == ""
    assert compose_box_focused("<hierarchy></hierarchy>") is False


# --- Facebook Dating -------------------------------------------------------


def test_fb_type_never_lands_never_sends():
    tree = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = _fb(tree, st, ["Opened Facebook Dating"])
    assert act.get("action") == "type"
    assert act.get("text") == PHOTO_COMMENT_TEXT
    assert act.get("humanize") is False
    # Box still empty: retype, bounded — never Send, never counted.
    act2 = _fb(tree, st, ["Type photo comment"])
    assert act2.get("action") == "type"
    assert st["bulk_message_new"]["done"] == 0
    act3 = _fb(tree, st, ["Type photo comment"])
    assert act3.get("action") == "fail"
    assert "never landed" in (act3.get("reason") or "")
    assert st["bulk_message_new"]["done"] == 0


def test_fb_unfocused_box_gets_focus_tap_first():
    tree = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    unfocused = tree.replace('e="1" f="1"', 'e="1"')
    assert compose_box_focused(unfocused) is False
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = _fb(unfocused, st, ["Opened Facebook Dating"])
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (472, 1324)
    assert "focus" in (act.get("reason") or "").lower()
    # Once the box is focused, the next step types (paste).
    act2 = _fb(tree, st, ["Focus the photo comment box"])
    assert act2.get("action") == "type"
    assert act2.get("humanize") is False


def test_fb_typed_box_sends_and_counts():
    sheet = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    typed = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = _fb(sheet, st, ["Opened Facebook Dating"])
    assert act.get("action") == "type"
    act2 = _fb(typed, st, ["Type photo comment"])
    assert act2.get("action") == "tap"
    assert (act2.get("x"), act2.get("y")) == SEND_XY
    assert st["bulk_message_new"]["done"] == 1


def test_fb_after_send_sheet_lingers_waits_then_backs_out():
    sheet = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    typed = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    assert _fb(sheet, st, ["Opened Facebook Dating"]).get("action") == "type"
    act = _fb(typed, st, ["Type photo comment"])
    assert act.get("action") == "tap"
    assert st["bulk_message_new"]["done"] == 1
    # Sheet still open, box now empty: wait for it to close — never retype.
    act = _fb(sheet, st, ["Tap Send"])
    assert act.get("action") == "wait"
    assert st["bulk_message_new"]["done"] == 1
    # Still open: Back out (bounded), still never a type.
    act = _fb(sheet, st, ["Wait for sheet to close"])
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    assert st["bulk_message_new"]["done"] == 1
    act = _fb(sheet, st, ["Dismiss the sheet"])
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    act = _fb(sheet, st, ["Dismiss the sheet"])
    assert act.get("action") == "fail"
    assert st["bulk_message_new"]["done"] == 1


def test_fb_send_retry_when_text_stays_in_box():
    typed = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    sheet = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    assert _fb(sheet, st, ["Opened Facebook Dating"]).get("action") == "type"
    assert _fb(typed, st, ["Type photo comment"]).get("action") == "tap"
    assert st["bulk_message_new"]["done"] == 1
    # Text still in the box after Send: one more Send tap, no recount.
    act = _fb(typed, st, ["Tap Send"])
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == SEND_XY
    assert st["bulk_message_new"]["done"] == 1
    # Still there after the retry: fail honestly.
    act = _fb(typed, st, ["Tap Send again"])
    assert act.get("action") == "fail"
    assert st["bulk_message_new"]["done"] == 1


# --- Hinge -----------------------------------------------------------------


def test_hinge_type_never_lands_never_sends():
    tree = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = _hinge(tree, st, ["Opened Hinge", "Hinge Discover photo heart"])
    assert act.get("action") == "type"
    assert act.get("text") == "hi miss"
    assert act.get("humanize") is False
    # Box still empty: retype, bounded — never Send Like, never counted.
    act2 = _hinge(tree, st, ["Opened Hinge", "Type like-sheet comment"])
    assert act2.get("action") == "type"
    assert st["bulk_message_new"]["done"] == 0
    act3 = _hinge(tree, st, ["Opened Hinge", "Type like-sheet comment"])
    assert act3.get("action") == "fail"
    assert "never landed" in (act3.get("reason") or "")
    assert st["bulk_message_new"]["done"] == 0


def test_hinge_unfocused_box_gets_focus_tap_first():
    tree = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    unfocused = tree.replace('e="1" f="1"', 'e="1"')
    assert compose_box_focused(unfocused) is False
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = _hinge(unfocused, st, ["Opened Hinge", "Hinge Discover photo heart"])
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (540, 1102)
    assert "focus" in (act.get("reason") or "").lower()
    # Once the box is focused, the next step types (paste).
    act2 = _hinge(tree, st, ["Opened Hinge", "Focus Add a comment field"])
    assert act2.get("action") == "type"
    assert act2.get("humanize") is False


def test_hinge_typed_box_sends_like_and_counts():
    sheet = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    typed = (FIX / "hinge_like_sheet_typed.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    act = _hinge(sheet, st, ["Opened Hinge", "Hinge Discover photo heart"])
    assert act.get("action") == "type"
    act2 = _hinge(typed, st, ["Opened Hinge", "Type like-sheet comment"])
    assert act2.get("action") == "tap"
    assert not in_rose_bounds(int(act2["x"]), int(act2["y"]))
    assert (int(act2["x"]), int(act2["y"])) == SEND_LIKE_XY
    assert "Rose" in (act2.get("reason") or "")
    assert st["bulk_message_new"]["done"] == 1


def test_hinge_after_send_like_sheet_lingers_waits_then_backs_out():
    sheet = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    typed = (FIX / "hinge_like_sheet_typed.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    assert _hinge(sheet, st, ["Opened Hinge"]).get("action") == "type"
    act = _hinge(typed, st, ["Opened Hinge", "Type like-sheet comment"])
    assert act.get("action") == "tap"
    assert st["bulk_message_new"]["done"] == 1
    # Sheet still open, box now empty: wait for it to close — never retype.
    act = _hinge(sheet, st, ["Opened Hinge", "Tap Send Like"])
    assert act.get("action") == "wait"
    assert st["bulk_message_new"]["done"] == 1
    # Still open: Back out (bounded), still never a type.
    act = _hinge(sheet, st, ["Opened Hinge", "Wait for sheet to close"])
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    assert st["bulk_message_new"]["done"] == 1
    act = _hinge(sheet, st, ["Opened Hinge", "Dismiss the sheet"])
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    act = _hinge(sheet, st, ["Opened Hinge", "Dismiss the sheet"])
    assert act.get("action") == "fail"
    assert st["bulk_message_new"]["done"] == 1


def test_hinge_send_retry_when_text_stays_in_box():
    sheet = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    typed = (FIX / "hinge_like_sheet_typed.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False}}
    assert _hinge(sheet, st, ["Opened Hinge"]).get("action") == "type"
    assert _hinge(typed, st, ["Opened Hinge", "Type like-sheet comment"]).get("action") == "tap"
    assert st["bulk_message_new"]["done"] == 1
    # Text still in the box after Send Like: one more Send Like tap,
    # no recount, never Rose.
    act = _hinge(typed, st, ["Opened Hinge", "Tap Send Like"])
    assert act.get("action") == "tap"
    assert not in_rose_bounds(int(act["x"]), int(act["y"]))
    assert st["bulk_message_new"]["done"] == 1
    # Still there after the retry: fail honestly.
    act = _hinge(typed, st, ["Opened Hinge", "Tap Send Like again"])
    assert act.get("action") == "fail"
    assert st["bulk_message_new"]["done"] == 1


def test_hinge_message_bank_default():
    assert MESSAGE_BANK[0] == "hey how are you"


# --- executor: humanize passthrough ----------------------------------------


def test_executor_passes_humanize_false_for_discover_paste(monkeypatch):
    import backend.cloud_agent as ca
    import backend.device_rpc as rpc
    import backend.message_text_guard as guard

    seen: dict = {}

    def fake_call_device(device_id, command, params=None, timeout_s=25.0, **kw):
        seen["command"] = command
        seen["params"] = dict(params or {})
        return {"ok": True, "via": "a11y", "acked": True}

    monkeypatch.setattr(rpc, "call_device", fake_call_device)
    monkeypatch.setattr(
        guard, "enforce_message_text", lambda action, instr, **kw: action
    )
    out = ca.execute_action(
        "test-device",
        {
            "action": "type",
            "text": "hi miss you look beautiful",
            "clear": True,
            "humanize": False,
        },
    )
    assert seen["command"] == "input_text"
    assert seen["params"]["humanize"] is False
    assert "Typed" in out


def test_executor_defaults_humanize_true(monkeypatch):
    import backend.cloud_agent as ca
    import backend.device_rpc as rpc
    import backend.message_text_guard as guard

    seen: dict = {}

    def fake_call_device(device_id, command, params=None, timeout_s=25.0, **kw):
        seen["command"] = command
        seen["params"] = dict(params or {})
        return {"ok": True, "via": "ime", "acked": True}

    monkeypatch.setattr(rpc, "call_device", fake_call_device)
    monkeypatch.setattr(
        guard, "enforce_message_text", lambda action, instr, **kw: action
    )
    out = ca.execute_action(
        "test-device",
        {"action": "type", "text": "hey how are you", "clear": True},
    )
    assert seen["command"] == "input_text"
    assert seen["params"]["humanize"] is True
    assert "Typed" in out
