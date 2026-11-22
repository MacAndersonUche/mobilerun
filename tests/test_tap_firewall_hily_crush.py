"""SAFETY: dry-run must never tap Hily Crush under a covering profile sheet."""

from pathlib import Path

from backend.bulk_bench_heuristics import _open_chats_tab_action, plan_bulk_message_new
from backend.dm_heuristics import hily_on_profile_sheet
from backend.tap_firewall import (
    guard_tap_action,
    resolve_topmost_clickable_at,
    tap_is_forbidden,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_hily_profile_sheet_detected():
    tree = _load("hily_crush_sheet_over_chats.xml")
    assert hily_on_profile_sheet(tree) is True


def test_chats_tab_xy_resolves_to_crush_not_chats():
    """The incident: tap (348,2188) intended Chats but hit Crush overlay."""
    tree = _load("hily_crush_sheet_over_chats.xml")
    top = resolve_topmost_clickable_at(tree, 348, 2188)
    assert top is not None
    blob = f"{top.get('label')} {top.get('id')}".lower()
    assert "crush" in blob


def test_tap_firewall_refuses_crush_in_dry_run():
    tree = _load("hily_crush_sheet_over_chats.xml")
    action = {
        "action": "tap",
        "x": 348,
        "y": 2188,
        "reason": "Open chats/messages tab",
        "label": "Chats",
        "planner": "bulk_message_heuristic",
    }
    out = guard_tap_action(action, tree, dry_run=True)
    assert out["action"] == "fail"
    assert "firewall" in out["reason"].lower() or "crush" in out["reason"].lower()


def test_tap_firewall_refuses_crush_in_live():
    tree = _load("hily_crush_sheet_over_chats.xml")
    action = {"action": "tap", "x": 400, "y": 2160, "reason": "oops"}
    out = guard_tap_action(action, tree, dry_run=False)
    assert out["action"] == "fail"
    assert "crush" in out["reason"].lower() or "paid" in out["reason"].lower()


def test_open_chats_backs_out_when_crush_covers():
    tree = _load("hily_crush_sheet_over_chats.xml")
    act = _open_chats_tab_action("hily", tree, [], "test")
    assert act is not None
    assert act["action"] == "press_button"
    assert act["button"] == "back"


def test_hily_new_dry_run_fails_on_crush_sheet():
    tree = _load("hily_crush_sheet_over_chats.xml")
    act = plan_bulk_message_new(
        'message "hi" to 3 new profiles on Hily',
        tree,
        ["Opened Hily"],
        package="com.hily.app",
        dry_run=True,
        state={},
    )
    assert act and act["action"] in ("fail", "press_button")
    if act["action"] == "fail":
        assert act.get("dry_run_verified") is False
        assert "crush" in act["reason"].lower() or "composer" in act["reason"].lower()


def test_quoted_text_excludes_bank_lines():
    from backend.message_text_guard import allowed_message_texts, enforce_message_text

    job = {"message_bank": ["hey there", "what's up"]}
    allowed = allowed_message_texts('message "hello miss" to 3 new profiles', job=job)
    assert allowed == ["hello miss"]
    out = enforce_message_text(
        {"action": "type", "text": "hey there", "reason": "Type message"},
        'message "hello miss" to 3 new profiles',
        job=job,
    )
    # Forced to user quoted text — not bank
    assert out["action"] == "type"
    assert out["text"] == "hello miss"


def test_invisible_nodes_excluded_from_resolve():
    tree = """
    <hierarchy><w p="com.bumble.app">
     <n t="Older chats" xy="2701,900" c="1" v="0" b="2600,800,2800,1000"/>
     <n t="Older chats · (3)" xy="540,900" c="1" b="100,850,900,950"/>
    </w></hierarchy>
    """
    # v=0 off-screen must not win
    top = resolve_topmost_clickable_at(tree, 540, 900)
    assert top is not None
    assert int(top["x"]) < 2000
    assert (
        tap_is_forbidden(top, dry_run=True) is None
        or "older" in (top.get("label") or "").lower()
    )
