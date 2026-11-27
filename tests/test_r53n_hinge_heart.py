"""r53n: Hinge photo-heart miss + false 'panel stayed open' (27 Nov 2026 live)."""

from __future__ import annotations

from pathlib import Path

from backend.hinge_fixed_first_contact import (
    PHOTO_HEART_LADDER,
    PHOTO_HEART_XY,
    _vision_answer,
    plan_hinge_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"
R53 = Path(__file__).resolve().parent / "fixtures" / "r53"


def _empty():
    return (FIX / "hinge_empty_tree.xml").read_text(encoding="utf-8")


def _kb_tree():
    return (R53 / "hinge_inline_panel_keyboard_blind.xml").read_text(encoding="utf-8")


def _st(**extra):
    bulk = {
        "done": 0,
        "typed": False,
        "_opened_discover": True,
        "_deck_seen": True,
        "_discover_waited": True,
        "awaiting_sheet": True,
        "heart_tries": 1,
        "_heart_y": 1356,
        "_sheet_waited": True,
    }
    bulk.update(extra)
    return {"bulk_message_new": bulk}


def test_ladder_includes_signals_banner_rung():
    assert PHOTO_HEART_XY == (937, 1356)
    assert PHOTO_HEART_LADDER[0] == 1356
    assert 1528 in PHOTO_HEART_LADDER
    assert PHOTO_HEART_LADDER.index(1528) == 1


def test_vision_answer_ignores_failed_empty_raw():
    assert (
        _vision_answer(
            {"_vision_last": {"tag": "hinge_sheet_open", "ok": False, "raw": ""}},
            "hinge_sheet_open",
        )
        is None
    )
    assert (
        _vision_answer(
            {"_vision_last": {"tag": "hinge_sheet_open", "ok": False, "raw": "NO"}},
            "hinge_sheet_open",
        )
        is False
    )
    assert (
        _vision_answer(
            {"_vision_last": {"tag": "hinge_sheet_open", "ok": True, "raw": "YES"}},
            "hinge_sheet_open",
        )
        is True
    )
    assert (
        _vision_answer(
            {"_vision_last": {"tag": "other", "ok": True, "raw": "YES"}},
            "hinge_sheet_open",
        )
        is None
    )


def test_empty_tree_is_not_sheet_open_when_vision_says_discover():
    # Tronella: heart at 1356 missed, tree empty, no keyboard, screenshot
    # still shows the Discover card. Continue the ladder at 1528 — do not
    # fail and do not keep assuming the sheet is open.
    st = _st(_vision_last={"tag": "hinge_sheet_open", "ok": False, "raw": "NO"})
    hist = [
        "Opened Hinge",
        "Open Hinge Discover tab",
        "Hinge Discover photo heart (937, 1356) to open like sheet — try 1/6",
    ]
    act = plan_hinge_fixed_first_contact(
        'send 3 first contact messages on hinge "good evening beautiful"',
        _empty(),
        hist,
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="good evening beautiful",
        target=3,
    )
    assert act["action"] == "tap"
    assert (act["x"], act["y"]) == (937, 1528)
    assert "photo heart" in (act.get("reason") or "").lower()
    assert st["bulk_message_new"]["awaiting_sheet"] is True
    assert st["bulk_message_new"]["heart_tries"] == 2
    assert st["bulk_message_new"]["done"] == 0


def test_empty_tree_vision_yes_never_retaps_heart():
    st = _st(_vision_last={"tag": "hinge_sheet_open", "ok": True, "raw": "YES"})
    hist = ["Opened Hinge", "Hinge Discover photo heart"]
    act = plan_hinge_fixed_first_contact(
        'send 3 first contact messages on hinge "good evening beautiful"',
        _empty(),
        hist,
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="good evening beautiful",
        target=3,
    )
    assert act["action"] == "tap"
    assert "photo heart" not in (act.get("reason") or "").lower()
    assert act.get("fastpath_step") == "hinge_fixed_fc_blind_focus"


def test_send_tapped_counts_when_vision_shows_next_card():
    # Hephzibah: Send Like went through and the deck advanced to Tronella,
    # but a stale tree still listed the keyboard, and the old path failed
    # with "panel stayed open".
    tree = _kb_tree()
    st = _st(
        _bc="send_tapped",
        typed=True,
        _bc_wait=2,
        _vision_last={"tag": "hinge_panel_open", "ok": False, "raw": "NO"},
    )
    hist = [
        'Typed "good evening beautiful"',
        "Tapped Send Like",
        "Send Like tapped — waiting for the panel to close",
    ]
    act = plan_hinge_fixed_first_contact(
        'send 3 first contact messages on hinge "good evening beautiful"',
        tree,
        hist,
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="good evening beautiful",
        target=3,
    )
    assert act.get("fastpath_step") == "hinge_fixed_fc_bc_probe"
    assert act["action"] == "wait"
    assert "stayed open" not in (act.get("reason") or "").lower()
    # Count happens on the probe step when the rose check is NO.
    st["bulk_message_new"]["_vision_last"] = {
        "tag": "hinge_rose_probe",
        "ok": False,
        "raw": "NO",
    }
    act2 = plan_hinge_fixed_first_contact(
        'send 3 first contact messages on hinge "good evening beautiful"',
        tree,
        hist,
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="good evening beautiful",
        target=3,
    )
    assert act2.get("fastpath_step") == "hinge_fixed_fc_bc_sent"
    assert st["bulk_message_new"]["done"] == 1
    assert "sent 1" in (act2.get("reason") or "").lower()


def test_send_tapped_still_fails_if_vision_says_panel_open():
    st = _st(
        _bc="send_tapped",
        typed=True,
        _bc_wait=2,
        _vision_last={"tag": "hinge_panel_open", "ok": True, "raw": "YES"},
    )
    act = plan_hinge_fixed_first_contact(
        'send 3 first contact messages on hinge "good evening beautiful"',
        _kb_tree(),
        ['Typed "good evening beautiful"', "Tapped Send Like"],
        state=st,
        package="co.hinge.app",
        dry_run=False,
        message="good evening beautiful",
        target=3,
    )
    assert act["action"] == "fail"
    assert "stayed open" in (act.get("reason") or "").lower()
    assert st["bulk_message_new"]["done"] == 0
