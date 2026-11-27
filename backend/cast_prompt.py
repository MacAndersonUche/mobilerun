"""Dismiss the MacMobileRun MediaProjection ('Start recording or casting') dialog.

This SystemUI sheet often yields an empty a11y tree (windows=0, only
systemui probes) and blocks the app underneath, as in Taimi tai4.
Never tap Start. Cancel is enough — Taimi first-contact counts from the
UI tree, not from a recording.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Measured on Mac's S21+ 1080x2400 from tai4 step_2.jpg (27 Nov 2026).
# Screenshot was 720x1600 (1.5x). Cancel centre ≈ (206, 1094) → (309, 1641).
CANCEL_XY = (309, 1641)
START_XY = (908, 1641)  # never tap this


def looks_like_cast_prompt(tree: str) -> bool:
    raw = tree or ""
    low = raw.lower()
    if "start recording or casting" in low or (
        "casting with" in low and "macmobilerun" in low
    ):
        return True
    # Compact dump of the sheet is often completely empty.
    if 'empty="true"' in raw or 'nodes="0"' in raw:
        if "systemui" in low and 'windows="0"' in raw and "takimi" not in low:
            return True
    return False


def _cancel_from_tree(tree: str) -> Optional[tuple]:
    """If Cancel is a labelled node, use it; never a Start node."""
    raw = tree or ""
    for m in re.finditer(
        r'<n[^>]*(?:t|d)="Cancel"[^>]*xy="(\d+),(\d+)"',
        raw,
        flags=re.I,
    ):
        return int(m.group(1)), int(m.group(2))
    # uiautomator
    for m in re.finditer(
        r'text="Cancel"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        raw,
        flags=re.I,
    ):
        x1, y1, x2, y2 = map(int, m.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def cancel_cast_prompt_action(
    tree: str, state: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    if not looks_like_cast_prompt(tree):
        return None
    st = state if isinstance(state, dict) else {}
    if st.get("dismissed_cast_prompt"):
        return None
    xy = _cancel_from_tree(tree) or CANCEL_XY
    if xy == START_XY or (
        abs(xy[0] - START_XY[0]) < 80 and abs(xy[1] - START_XY[1]) < 60
    ):
        xy = CANCEL_XY
    st["dismissed_cast_prompt"] = True
    return {
        "action": "tap",
        "x": int(xy[0]),
        "y": int(xy[1]),
        "reason": "Dismiss MacMobileRun recording prompt (Cancel, never Start)",
        "planner": "cast_prompt_cancel",
        "fastpath_step": "cast_prompt_cancel",
        "llm_provider": None,
        "_no_llm_handoff": True,
        "_ignore_same_decision": True,
    }
