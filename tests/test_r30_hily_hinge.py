"""r30: Hily chats-list false swipe / reply firewall, Hinge no longer fail-fast."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _visible_chat_list_rows,
    deck_card_name,
    plan_bulk_bench,
    plan_bulk_swipe,
)
from backend.cloud_agent import apply_dry_run_send_guard, unsupported_app_fail_action
from backend.dm_heuristics import hily_deck_card_name, hily_on_chats_list, hily_on_mbm
from backend.tap_firewall import find_blocking_label_at, guard_tap_action

FIXTURE = Path(__file__).parent / "fixtures" / "dm" / "hily_chats_r30.xml"


def _tree() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_hily_deck_card_name_ignores_chats_list_paige():
    tree = _tree()
    assert hily_on_chats_list(tree)
    assert hily_deck_card_name(tree) is None
    assert deck_card_name("hily", tree) is None


def test_hily_swipe_from_chats_taps_finder_not_paige():
    tree = _tree()
    act = plan_bulk_swipe(
        "auto-swipe 5 profiles on Hily",
        tree,
        ["Opened Hily[com.hily.app] — launch"],
        package="com.hily.app",
        dry_run=True,
    )
    assert act, "expected a Finder nav action"
    assert act.get("action") == "tap"
    assert act.get("fastpath_step") == "bulk_hily_open_finder" or "Finder" in (
        act.get("reason") or ""
    )
    assert abs(int(act["x"]) - 142) < 80
    assert abs(int(act["y"]) - 2190) < 80
    reason = (act.get("reason") or "") + (act.get("action") or "")
    assert "Paige" not in reason
    assert "identified card" not in reason.lower()


def test_firewall_allows_tegan_chat_row_not_upsell_or_mbm():
    tree = _tree()
    # Actual 'They liked you!' tile stays blocked
    upsell = find_blocking_label_at(tree, 456, 448)
    assert upsell is not None
    # Paige row is Message before match — still blocked by the tight row
    paige = find_blocking_label_at(tree, 321, 844)
    assert paige is not None
    # Tegan is a real existing chat; the huge parent must not block
    assert find_blocking_label_at(tree, 326, 1102) is None
    out = guard_tap_action(
        {
            "action": "tap",
            "x": 326,
            "y": 1102,
            "reason": "Open Tegan (bulk_message_heuristic)",
        },
        tree,
        dry_run=True,
    )
    assert out.get("action") == "tap", out.get("reason")
    refused = guard_tap_action(
        {
            "action": "tap",
            "x": 456,
            "y": 448,
            "reason": "Open They liked you",
        },
        tree,
        dry_run=True,
    )
    assert refused.get("action") == "fail"
    assert "they liked you" in (refused.get("reason") or "").lower() or "like" in (
        refused.get("reason") or ""
    ).lower()


def test_existing_chat_rows_skip_paige_mbm():
    tree = _tree()
    rows = _visible_chat_list_rows(tree, "hily")
    names = [r["name"] for r in rows]
    assert "Paige" not in names
    assert "They liked you!" not in names
    for want in ("Tegan", "Lynda", "Chyna", "Helyn", "Brenda"):
        assert want in names, names


def test_hinge_is_not_instruction_fail_fast():
    assert unsupported_app_fail_action("like 5 profiles on Hinge") is None
    assert unsupported_app_fail_action("reply good morning to 1 existing chat on Hinge") is None
    taimi = unsupported_app_fail_action("taimi like 5 profiles")
    assert taimi and taimi.get("action") == "fail"
    assert taimi.get("unsupported_app") == "taimi"

    act = plan_bulk_bench(
        "like 5 profiles on Hinge",
        "",
        [],
        dry_run=True,
    )
    # May open Hinge or wait/fail for other reasons, but not the unsupported skip.
    if act:
        assert act.get("unsupported_app") != "hinge"
        assert "unsupported" not in (act.get("reason") or "").lower()


def test_hily_on_mbm_false_on_chats_list_and_sparse_preview():
    tree = _tree()
    assert hily_on_mbm(tree) is False
    # Sparse tree with the row phrase but no sheet chrome must not Back
    sparse = """
    <hierarchy packages="com.hily.app">
     <w p="com.hily.app">
      <n t="Chats" xy="131,149"/>
      <n t="Paige" i="userNameField" xy="321,844"/>
      <n t="Message before match" i="messageField" xy="508,961"/>
     </w>
    </hierarchy>
    """
    # userNameField makes this a chats list
    assert hily_on_chats_list(sparse) is True
    assert hily_on_mbm(sparse) is False


def test_hily_on_mbm_true_only_with_sheet_chrome():
    sheet = """
    <hierarchy packages="com.hily.app">
     <w p="com.hily.app">
      <n t="Message before match" xy="540,400"/>
      <n i="closeButton" xy="74,160" c="1"/>
      <n i="allowanceCounter" t="3 left" xy="540,200"/>
     </w>
    </hierarchy>
    """
    assert hily_on_mbm(sheet) is True


def test_dry_run_skips_hinge_like_intent_tap():
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True,
        action={"action": "tap", "x": 534, "y": 979, "reason": "Tapping to like the profile."},
        kind="tap",
        reason="Tapping to like the profile.",
    )
    assert kind == "done"
    assert "would like/pass" in (reason or out.get("reason") or "").lower() or "would like" in (reason or "").lower()
    assert out.get("action") == "done"
    # Opening a chat must still be allowed
    kind2, _, out2 = apply_dry_run_send_guard(
        dry_run=True,
        action={"action": "tap", "x": 326, "y": 1102, "reason": "Open Tegan (bulk_message_heuristic)", "fastpath_step": "bulk_open_match"},
        kind="tap",
        reason="Open Tegan (bulk_message_heuristic)",
    )
    assert kind2 == "tap"
    assert out2.get("action") == "tap"
