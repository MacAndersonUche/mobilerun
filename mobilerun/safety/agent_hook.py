"""Hook for agent loops: inspect UI state and auto-pause on blockers.

Never solves or bypasses captchas / verification / login screens.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mobilerun.safety.runtime import check_screen_and_pause, get_safety_state
from mobilerun.safety.screen_guard import detect_safety_blockers

log = logging.getLogger(__name__)


class SafetyPauseRequested(Exception):
    """Raised when a safety screen is detected — agent must stop immediately."""

    def __init__(self, app: str, finding: Any, result: Any = None):
        self.app = app
        self.finding = finding
        self.result = result
        reason = getattr(finding, "reason", None) or "safety pause"
        super().__init__(f"Safety pause ({app}): {reason}")


def extract_screen_text(ui: Any) -> str:
    """Best-effort text from a UIState / formatted tree."""
    if ui is None:
        return ""
    for attr in ("formatted_text", "text", "raw_text"):
        val = getattr(ui, attr, None)
        if isinstance(val, str) and val.strip():
            return val
    elements = getattr(ui, "elements", None)
    if isinstance(elements, list):
        bits = []
        for el in elements:
            if isinstance(el, dict):
                for k in ("text", "contentDescription", "content-desc", "hint"):
                    if el.get(k):
                        bits.append(str(el[k]))
            else:
                t = getattr(el, "text", None)
                if t:
                    bits.append(str(t))
        return "\n".join(bits)
    return ""


def screen_requires_pause(
    ui: Any = None,
    *,
    screen_text: str = "",
    app: str = "unknown",
) -> Optional[Any]:
    """Return a SafetyFinding if the current screen is a hard stop."""
    text = screen_text or extract_screen_text(ui)
    tree = None
    if ui is not None:
        tree = getattr(ui, "elements", None) or getattr(ui, "tree", None)
    finding = detect_safety_blockers(screen_text=text, ui_tree=tree)
    return finding if finding.detected else None


def enforce_safety_or_raise(
    ui: Any = None,
    *,
    app: str = "unknown",
    screen_text: str = "",
    push_needs_you=None,
    notify=None,
    pause_mode_callbacks=None,
    screenshot_bytes: Optional[bytes] = None,
) -> None:
    """If a blocker is on screen, pause + escalate, then raise SafetyPauseRequested."""
    if get_safety_state().is_paused(app):
        raise SafetyPauseRequested(app, get_safety_state().last_finding or {})

    finding = screen_requires_pause(ui, screen_text=screen_text, app=app)
    if not finding:
        return

    shot = screenshot_bytes
    if shot is None and ui is not None:
        shot = getattr(ui, "screenshot_bytes", None)

    result = check_screen_and_pause(
        app=app,
        screen_text=screen_text or extract_screen_text(ui),
        ui_tree=getattr(ui, "elements", None) if ui is not None else None,
        push_needs_you=push_needs_you,
        notify=notify,
        pause_mode_callbacks=pause_mode_callbacks,
        screenshot_bytes=shot if isinstance(shot, (bytes, bytearray)) else None,
    )
    log.warning("Agent safety stop on %s: %s", app, finding.reason)
    raise SafetyPauseRequested(app, finding, result)
