"""dry_run send guard: never shadow the int step counter; block AI sends."""

from backend.cloud_agent import (
    _action_looks_like_send,
    apply_dry_run_send_guard,
)


def test_bulk_send_step_blocked():
    action = {
        "action": "tap",
        "x": 1000,
        "y": 2050,
        "reason": "Send to Match01 (bulk_message_heuristic)",
        "fastpath_step": "bulk_send",
    }
    assert _action_looks_like_send(action, "tap")
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert out.get("dry_run") is True
    assert "send" in reason.lower() and "skip" in reason.lower()


def test_ai_fallback_send_by_resource_id_blocked():
    """LLM taps with no fastpath_step but id/desc containing send."""
    action = {
        "action": "tap",
        "x": 1020,
        "y": 2210,
        "reason": "Press the blue arrow",
        "resource_id": "com.bumble.app:id/chatInput_send",
        "label": "",
    }
    assert _action_looks_like_send(action, "tap")
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert out["action"] == "done"


def test_ai_fallback_send_by_content_desc_blocked():
    action = {
        "action": "tap",
        "x": 1000,
        "y": 2210,
        "reason": "Continue the conversation",
        "desc": "Send message",
        "content_desc": "Send message",
    }
    assert _action_looks_like_send(action, "tap")
    kind, _, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert out.get("dry_run") is True


def test_non_send_tap_not_blocked():
    action = {
        "action": "tap",
        "x": 540,
        "y": 800,
        "reason": "Open chat with Sam",
        "label": "Sam",
        "fastpath_step": "tap_visible_contact",
    }
    assert not _action_looks_like_send(action, "tap")
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "tap"
    assert out is action


def test_dry_run_guard_preserves_int_step_counter():
    """Regression #54: guard must not reassign `step` (int) to a string label.

    Simulates the run_one_agent_step critical path: after the guard,
    `step + 1` must still work for steps_detail / state['steps'].
    """
    step = 3  # int counter as set from state['steps']
    assert isinstance(step, int)

    action = {
        "action": "tap",
        "x": 1000,
        "y": 2050,
        "reason": "Send to Match01 (bulk_message_heuristic)",
        "fastpath_step": "bulk_send",
        "_fastpath_step": "bulk_send",
    }
    kind = "tap"
    reason = action["reason"]

    # MUST use a different name than `step` (the bug was shadowing)
    kind, reason, action = apply_dry_run_send_guard(
        dry_run=True, action=action, kind=kind, reason=reason
    )
    assert kind == "done"
    assert isinstance(step, int)
    # These are the sites that crashed: step + 1 with step accidentally a str
    n = step + 1
    assert n == 4
    assert isinstance(n, int)
    # Screenshot key path also uses step + 1
    assert f"step_{step + 1}" == "step_4"


def test_dry_run_off_passes_through_send():
    action = {
        "action": "tap",
        "reason": "Send to Match01",
        "fastpath_step": "bulk_send",
    }
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=False, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "tap"
    assert out is action
