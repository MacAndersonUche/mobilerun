"""Honeyboard punctuation keying + sticky per-person opener (Hinge regression)."""

from __future__ import annotations

from datetime import datetime

import backend.cloud_agent as ca
from backend.honeyboard_keys import (
    HONEYBOARD_LAYER,
    clear_and_type_plan,
    is_honeyboard_keyable,
    key_tap_plan,
)
from backend.hinge_fixed_first_contact import allowed_message, plan_hinge_fixed_first_contact
from mobilerun.dating.openers import (
    OpenerLibrary,
    OpenerTemplate,
    clear_sticky_opener,
    pick_runner_first_contact_text,
    sticky_first_contact_text,
)


def test_comma_apostrophe_question_are_keyable():
    assert is_honeyboard_keyable("good morning, coffee or chaos so far?")
    assert is_honeyboard_keyable("morning, what's on your plate today?")
    assert is_honeyboard_keyable("hey how are you")
    assert not is_honeyboard_keyable("wow!!!")
    assert not is_honeyboard_keyable("hi: there")


def test_key_tap_plan_switches_layers_for_punct():
    plan = key_tap_plan("a,b'?")
    labels = [p[0] for p in plan]
    assert "key:," in labels
    assert "key:'" in labels
    assert "key:?" in labels
    # !#1 before ' or ?, then ABC back to alpha for remaining letters / end
    assert labels.count("layer") >= 2
    # Ends on alpha layer (final ensure)
    assert plan[-1][0] == "layer" or plan[-1][0].startswith("key:")
    # Layer taps hit the !#1 / ABC key
    for lab, x, y in plan:
        if lab == "layer":
            assert (x, y) == HONEYBOARD_LAYER
    # All taps stay in the keyboard band
    assert all(1700 <= y <= 2200 for _, _, y in plan)
    # Never Done (right edge of bottom row)
    assert (985, 2186) not in [(x, y) for _, x, y in plan]


def test_type_on_keyboard_keys_punctuation(monkeypatch):
    taps = []
    import backend.device_rpc as rpc

    monkeypatch.setattr(rpc, "call_device", lambda d, c, p, timeout_s=0: taps.append(p))
    monkeypatch.setattr(ca.time, "sleep", lambda s: None)
    text = "hi, what's up?"
    out = ca._type_on_keyboard(
        "dev",
        {
            "action": "type_keys",
            "text": text,
            "clear_keys": 2,
            "lower_first": True,
            "_instruction": f'send 1 first contact messages on hinge "{text}"',
        },
    )
    assert out == f'Typed "{text}"'
    expected = clear_and_type_plan(text, clear_keys=2, lower_first=True)
    assert len(taps) == len(expected)
    assert all(1700 <= p["y"] <= 2200 for p in taps)
    assert (985, 2186) not in [(p["x"], p["y"]) for p in taps]


def test_type_on_keyboard_rejects_unkeyable(monkeypatch):
    import backend.device_rpc as rpc

    monkeypatch.setattr(rpc, "call_device", lambda *a, **k: None)
    monkeypatch.setattr(ca.time, "sleep", lambda s: None)
    try:
        ca._type_on_keyboard(
            "dev",
            {
                "action": "type_keys",
                "text": "hi!!!",
                "_instruction": 'send 1 first contact messages on hinge "hi!!!"',
            },
        )
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "cannot key" in str(e).lower() or "!" in str(e)


def test_require_keyable_skips_bang_lines():
    lib = OpenerLibrary(
        templates=[
            OpenerTemplate(id="bang", text="wow!!!", bucket="any", enabled=True),
            OpenerTemplate(id="ok", text="hey how are you", bucket="any", enabled=True),
        ],
        opener_mode="templates",
    )
    st: dict = {"opener_library": lib.to_dict(), "bulk_message_new": {"done": 0}}
    text = pick_runner_first_contact_text(
        fallback_bank=["hey how are you"],
        state=st,
        package_name="co.hinge.app",
        require_keyable=True,
        now=datetime(2026, 6, 1, 15, 0, 0),
        rng=__import__("random").Random(0),
    )
    assert is_honeyboard_keyable(text)
    assert "!" not in text


def test_sticky_opener_reuses_same_line_across_steps(monkeypatch):
    picks = {"n": 0}

    def fake_pick(**kwargs):
        picks["n"] += 1
        return f"picked-{picks['n']}"

    monkeypatch.setattr(
        "mobilerun.dating.openers.pick_runner_first_contact_text", fake_pick
    )
    bulk: dict = {"done": 0}
    a = sticky_first_contact_text(
        bulk, fallback_bank=["x"], message="", package_name="co.hinge.app"
    )
    b = sticky_first_contact_text(
        bulk, fallback_bank=["x"], message="", package_name="co.hinge.app"
    )
    assert a == b == "picked-1"
    assert picks["n"] == 1
    clear_sticky_opener(bulk)
    c = sticky_first_contact_text(
        bulk, fallback_bank=["x"], message="", package_name="co.hinge.app"
    )
    assert c == "picked-2"
    assert picks["n"] == 2


def test_hinge_allowed_message_sticks_on_bulk():
    bulk: dict = {"done": 0, "text": "stuck hinge line"}
    st = {"bulk_message_new": bulk}
    a = allowed_message("ignored", state=st, store=bulk)
    b = allowed_message("also ignored", state=st, store=bulk)
    assert a == b == "stuck hinge line"


def test_hinge_blind_type_reuses_stuck_text():
    from pathlib import Path

    tree = (
        Path(__file__).resolve().parent / "fixtures" / "r53" / "hinge_inline_panel_keyboard_blind.xml"
    ).read_text()
    stuck = "good morning, coffee or chaos so far?"
    st = {
        "bulk_message_new": {
            "done": 0,
            "awaiting_sheet": True,
            "_deck_seen": True,
            "_heart_y": 1356,
            "text": stuck,
        }
    }
    hist = [
        "tap(110,2195) — Open Hinge Discover tab (nav xy)",
        "tap(937,1356) — Hinge Discover photo heart (937, 1356) to open like sheet",
    ]
    a = plan_hinge_fixed_first_contact(
        'send 5 first contact messages on hinge "hello miss"',
        tree,
        hist,
        state=st,
        message="hello miss",
        target=5,
    )
    assert a["action"] == "type_keys"
    assert a["text"] == stuck
    # Second step still the same stuck line (would fail landed check if re-picked)
    st["bulk_message_new"]["_bc"] = "typed"
    hist2 = hist + [f'Typed "{stuck}"']
    b = plan_hinge_fixed_first_contact(
        'send 5 first contact messages on hinge "hello miss"',
        tree,
        hist2,
        state=st,
        message="hello miss",
        target=5,
    )
    assert b["action"] == "tap"  # Send Like
    assert stuck.lower() in (b.get("reason") or "").lower() or stuck in str(
        b.get("_vision_check") or ""
    )
