"""Hinge type_keys: no CAPS LOCK Shift, exact non-humanized sequential taps."""

from __future__ import annotations

from pathlib import Path

import backend.cloud_agent as ca
from backend.honeyboard_keys import (
    HONEYBOARD_LAYER,
    HONEYBOARD_SHIFT,
    clear_and_type_plan,
    key_tap_plan,
)
from backend.hinge_fixed_first_contact import plan_hinge_fixed_first_contact

FIX = Path(__file__).resolve().parent / "fixtures" / "r53"


def test_clear_and_type_plan_never_taps_shift():
    plan = clear_and_type_plan(
        "hey you, surviving the day alright?",
        clear_keys=3,
        lower_first=True,  # must be ignored — would CAPS LOCK on Hinge
    )
    labels = [p[0] for p in plan]
    assert "shift" not in labels
    assert all((x, y) != HONEYBOARD_SHIFT for _, x, y in plan)
    assert labels[:3] == ["bs", "bs", "bs"]
    assert "key:?" in labels
    assert "key:," in labels
    assert labels.count("layer") >= 2  # !#1 for ? then ABC back


def test_question_mark_plan_switches_layer_then_keys_exact_coords():
    plan = key_tap_plan("ok?")
    # o, k on alpha; layer to sym; ?; layer back to alpha
    assert [p[0] for p in plan] == ["key:o", "key:k", "layer", "key:?", "layer"]
    q = next(p for p in plan if p[0] == "key:?")
    assert q[1:] == (750, 2036)
    layers = [p for p in plan if p[0] == "layer"]
    assert all(p[1:] == HONEYBOARD_LAYER for p in layers)


def test_hinge_planner_omits_lower_first_and_disables_humanize():
    tree = (FIX / "hinge_inline_panel_keyboard_blind.xml").read_text()
    stuck = "hey you, surviving the day alright?"
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
        "tap(937,1356) — Hinge Discover photo heart",
    ]
    a = plan_hinge_fixed_first_contact(
        f'send 1 first contact messages on hinge "{stuck}"',
        tree,
        hist,
        state=st,
        message=stuck,
        target=1,
    )
    assert a["action"] == "type_keys"
    assert a["text"] == stuck
    assert a.get("lower_first") is False
    assert a.get("humanize") is False


def test_type_on_keyboard_passes_humanize_false_and_delays_layers(monkeypatch):
    taps = []
    sleeps = []

    def capture(d, c, p, timeout_s=0):
        taps.append(dict(p))

    monkeypatch.setattr("backend.device_rpc.call_device", capture)
    monkeypatch.setattr(ca.time, "sleep", lambda s: sleeps.append(s))
    text = "hi?"
    out = ca._type_on_keyboard(
        "dev",
        {
            "action": "type_keys",
            "text": text,
            "clear_keys": 1,
            "lower_first": True,  # forced off inside _type_on_keyboard
            "_instruction": f'send 1 first contact messages on hinge "{text}"',
        },
    )
    assert out == 'Typed "hi?"'
    assert all(p.get("humanize") is False for p in taps)
    # No Shift coords in the payload list
    assert (HONEYBOARD_SHIFT[0], HONEYBOARD_SHIFT[1]) not in [
        (p["x"], p["y"]) for p in taps
    ]
    expected = clear_and_type_plan(text, clear_keys=1, lower_first=False)
    assert len(taps) == len(expected)
    # Layer taps get the longer post-switch delay
    layer_idxs = [i for i, (lab, _, _) in enumerate(expected) if lab == "layer"]
    assert layer_idxs
    for i in layer_idxs:
        assert sleeps[i] >= 0.3
    assert ca._type_on_keyboard  # keep import used
