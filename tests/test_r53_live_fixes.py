"""r53: fixes from the live S21+ runs on 27 Nov 2026 (Hinge, Hily, FB Dating)."""

from __future__ import annotations

from pathlib import Path

import backend.cloud_agent as ca
from backend.dm_heuristics import hily_on_profile_sheet
from backend.facebook_dating_fixed_first_contact import (
    plan_facebook_dating_fixed_first_contact,
)
from backend.hily_fixed_first_contact import (
    _on_likes_sent,
    _on_likes_tab,
    plan_hily_fixed_first_contact,
)
from backend.hinge_fixed_first_contact import plan_hinge_fixed_first_contact
from backend.message_text_guard import extract_quoted_message_text
from backend.overlay_dismiss import detect_foreign_overlay

FIX = Path(__file__).resolve().parent / "fixtures" / "r53"


def _t(name: str) -> str:
    return (FIX / name).read_text()


# ── Hily ────────────────────────────────────────────────────────────────
def test_hily_likes_tab_is_not_likes_sent_and_not_a_crush_sheet():
    tree = _t("hily_activity_likes_tab.xml")
    assert _on_likes_tab(tree)
    assert not _on_likes_sent(tree, {})
    assert not hily_on_profile_sheet(tree)
    st: dict = {}
    a = plan_hily_fixed_first_contact("x", tree, [], state=st, message="hello how are you", target=5)
    assert a["action"] == "tap" and (a["x"], a["y"]) == (900, 265)
    assert a["fastpath_step"] == "hily_fixed_fc_likes_sent"


def test_hily_likes_sent_scrolls_before_calling_it_empty():
    tree = _t("hily_likes_sent_all_sent_visible.xml")
    st = {"bulk_message_new": {"done": 4, "_ls_tapped": True}}
    a = plan_hily_fixed_first_contact("x", tree, [], state=st, message="hello how are you", target=5)
    assert a["action"] == "swipe"
    assert a["fastpath_step"] == "hily_fixed_fc_likes_sent_scroll"
    # Same names after the scroll = the list really ended
    b = plan_hily_fixed_first_contact("x", tree, [], state=st, message="hello how are you", target=5)
    assert b["fastpath_step"] == "hily_fixed_fc_to_discover"


# ── Facebook Dating ─────────────────────────────────────────────────────
def test_fb_dating_profile_taps_photo_never_heart():
    tree = _t("fb_dating_profile_leah.xml")
    a = plan_facebook_dating_fixed_first_contact(
        'send 5 first contact messages on facebook dating "hello how are you"',
        tree, [], state={}, message="hello how are you", target=5,
    )
    assert a["action"] == "tap"
    assert a["fastpath_step"] == "fb_dating_fc_tap_photo"
    assert (a["x"], a["y"]) != (739, 2116)


# ── Hinge ───────────────────────────────────────────────────────────────
def test_hinge_keyboard_up_after_heart_types_on_keyboard():
    tree = _t("hinge_inline_panel_keyboard_blind.xml")
    st = {"bulk_message_new": {"done": 0, "awaiting_sheet": True, "_deck_seen": True,
                               "_heart_y": 1356}}
    hist = ["tap(110,2195) — Open Hinge Discover tab (nav xy)",
            "tap(937,1356) — Hinge Discover photo heart (937, 1356) to open like sheet"]
    a = plan_hinge_fixed_first_contact(
        'send 5 first contact messages on hinge "hello miss"', tree, hist,
        state=st, message="hello miss", target=5,
    )
    assert a["action"] == "type_keys"
    assert a["text"] == "hello miss"
    assert a["clear_keys"] > 0 and a["lower_first"] is True
    assert a["fastpath_step"] == "hinge_fixed_fc_bc_type"


def test_type_keys_taps_only_keyboard_band(monkeypatch):
    taps = []
    import backend.device_rpc as rpc

    monkeypatch.setattr(rpc, "call_device", lambda d, c, p, timeout_s=0: taps.append(p))
    monkeypatch.setattr(ca.time, "sleep", lambda s: None)
    out = ca._type_on_keyboard("dev", {
        "action": "type_keys", "text": "hello miss", "clear_keys": 3, "lower_first": True,
        "_instruction": 'send 5 first contact messages on hinge "hello miss"',
    })
    assert out == 'Typed "hello miss"'
    assert len(taps) == 3 + 1 + len("hello miss")
    assert all(1700 <= p["y"] <= 2200 for p in taps)
    assert (985, 2186) not in [(p["x"], p["y"]) for p in taps]  # never Done


def test_blind_type_unreachable_only_for_blind_compose():
    assert ca._blind_type_unreachable({"fastpath_step": "hinge_fixed_fc_bc_type"},
                                      "input_text failed — focus a text field")
    assert not ca._blind_type_unreachable({"fastpath_step": "fb_dating_fc_type"},
                                          "input_text failed — focus a text field")


# ── Executor guards ─────────────────────────────────────────────────────
def test_dating_fixed_planner_never_hands_off_to_llm():
    job = {"dating_run": True}
    fixed = {"action": "tap", "planner": "facebook_dating_fixed_first_contact_no_llm_handoff"}
    assert ca._dating_fixed_no_llm(job, "send 5 first contact messages on facebook dating", fixed)
    assert not ca._dating_fixed_no_llm({}, "open whatsapp and text mum", {"action": "tap"})


def test_dating_job_never_runs_sms_recovery():
    assert ca._is_dating_job({}, 'send 5 first contact messages on hinge "hello miss"')
    assert not ca._is_dating_job({}, "send an sms to mum in google messages")


def test_fixed_instruction_quote_is_extracted():
    assert extract_quoted_message_text('fixed tagged message 5 "hello how are you"') == (
        "hello how are you"
    )


def test_keyboard_window_is_not_a_foreign_overlay():
    tree = _t("hinge_inline_panel_keyboard_blind.xml")
    assert detect_foreign_overlay(tree, "co.hinge.app") is None
