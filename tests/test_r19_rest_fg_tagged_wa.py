"""r19 rest: FG inference, Tagged Meet Me, WA rows, open-cycle fail-fast."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _recover_to_root_action,
    _visible_chat_list_rows,
    plan_bulk_swipe,
)
from backend.stuck_recovery import next_stuck_action
from backend.tap_firewall import guard_tap_action
from backend.universal_open import (
    MAX_OPEN_CYCLES,
    advance_open_stage,
    open_cycles_exhausted,
    open_exhausted_fail_action,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_whatsapp_home_rows_include_plain_text_contacts():
    tree = (FIXTURES / "whatsapp_home_tree.xml").read_text(encoding="utf-8")
    rows = _visible_chat_list_rows(tree, "whatsapp")
    names = [r["name"] for r in rows]
    assert "Precious Achalugo" in names  # stripped preview
    assert "Mom" in names
    assert "Alex" in names
    assert len(rows) >= 5


def test_tagged_swipe_opens_meet_me_not_back():
    tree = (
        '<hierarchy><w p="com.taggedapp" f="1">'
        '<n t="Near you" xy="540,400" c="1"/>'
        '<n i="tab_nearby" t="Meet" c="1" xy="108,2200"/>'
        '<n i="tab_chats" t="Chats" c="1" xy="756,2200"/>'
        '<n i="tab_match_game" t="Match" c="1" xy="540,2200"/>'
        "</w></hierarchy>"
    )
    act = plan_bulk_swipe(
        "swipe right on 5 profiles on Tagged",
        tree,
        ["Opened Tagged[open_ok]"],
        package="com.taggedapp",
        dry_run=True,
        state={},
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "Back" not in (act.get("reason") or "")
    assert act.get("label", "").lower() in ("meet me", "meet")


def test_tagged_recover_no_back_with_tab_bar():
    tree = (
        '<hierarchy><w p="com.taggedapp" f="1">'
        '<n i="tab_nearby" t="Meet" c="1" xy="108,2200"/>'
        '<n i="tab_chats" t="Chats" c="1" xy="756,2200"/>'
        '<n i="tab_match_game" t="Match" c="1" xy="540,2200"/>'
        "</w></hierarchy>"
    )
    act = _recover_to_root_action("tagged", tree, ["Opened Tagged"], "test", state={})
    # Tab bar verified → treat as root (None) or Meet Me tap — never Back
    if act is not None:
        assert act.get("action") != "press_button"
        assert "Back" not in (act.get("reason") or "")


def test_tap_firewall_retargets_near_you_intended_miss():
    tree = (
        '<hierarchy><w p="com.taggedapp" f="1">'
        '<n t="Near you" xy="540,400" c="1" b="100,300,900,500"/>'
        '<n i="tab_nearby" t="Meet Me" c="1" xy="108,2200" b="20,2100,200,2300"/>'
        "</w></hierarchy>"
    )
    out = guard_tap_action(
        {
            "action": "tap",
            "x": 540,
            "y": 400,
            "label": "Meet Me",
            "reason": "Tagged Meet",
        },
        tree,
        dry_run=True,
    )
    assert out.get("action") == "tap"
    assert out.get("_tap_firewall") == "retarget_resolved"
    assert "near you" in (out.get("label") or "").lower()


def test_stuck_never_back_after_open_on_launcher():
    import time

    state = {
        "last_open_at": int(time.time()),
        "history": ["Opened Taimi[open_ok]"],
        "last_action": "open_app(Taimi)",
    }
    act = next_stuck_action(
        state,
        instruction="swipe on Taimi",
        ui_tree='<hierarchy empty="true"/>',
        package="com.sec.android.app.launcher",
        prefer_pkg="com.takimi.android",
    )
    assert act.get("action") != "back"
    assert "Back" not in (act.get("reason") or "")


def test_open_cycles_fail_fast():
    state: dict = {}
    # 4 stages × 2 cycles = 8 advances → exhausted
    for _ in range(len(["a"] * 4) * MAX_OPEN_CYCLES):
        advance_open_stage(state)
    assert open_cycles_exhausted(state)
    fail = open_exhausted_fail_action("Taimi", fg_package="launcher", state=state)
    assert fail["action"] == "fail"
    assert "exhausted" in fail["reason"].lower()
