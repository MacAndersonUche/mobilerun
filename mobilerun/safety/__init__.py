"""Auto-pause safety: detect risk screens and escalate — never bypass."""

from mobilerun.safety.screen_guard import (
    SafetyFinding,
    detect_safety_blockers,
    find_safety_in_ui_tree,
)
from mobilerun.safety.auto_pause import AutoPauseResult, handle_safety_pause
from mobilerun.safety.runtime import (
    check_screen_and_pause,
    get_safety_state,
    reset_safety_state,
    resume_safety,
)
from mobilerun.safety.agent_hook import SafetyPauseRequested, enforce_safety_or_raise

__all__ = [
    "SafetyFinding",
    "detect_safety_blockers",
    "find_safety_in_ui_tree",
    "AutoPauseResult",
    "handle_safety_pause",
    "check_screen_and_pause",
    "get_safety_state",
    "reset_safety_state",
    "resume_safety",
    "SafetyPauseRequested",
    "enforce_safety_or_raise",
]
