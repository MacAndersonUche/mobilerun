"""Regression: empty-tree recovery must not UnboundLocalError on np_streak."""

from pathlib import Path


def test_np_streak_bound_before_uses():
    src = Path("backend/cloud_agent.py").read_text(encoding="utf-8")
    assert "Always bind before any path that may skip plan_next_action" in src
    assign_at = src.index('np_streak = int(state.get("no_progress_streak") or 0)')
    use_same_tap = src.index("and np_streak >= 1")
    use_hard_stop = src.index("if np_streak >= MAX_NO_PROGRESS + 1")
    assert assign_at < use_same_tap < use_hard_stop
