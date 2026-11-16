"""Escalate safety findings: stop loops, screenshot, Needs-you + notify."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from mobilerun.safety.screen_guard import SafetyFinding

log = logging.getLogger(__name__)


@dataclass
class AutoPauseResult:
    paused: bool
    app: str = ""
    pause_all: bool = False
    finding: Optional[SafetyFinding] = None
    needs_you_id: Optional[str] = None
    screenshot_path: Optional[str] = None
    notified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paused": self.paused,
            "app": self.app,
            "pause_all": self.pause_all,
            "finding": self.finding.to_dict() if self.finding else None,
            "needs_you_id": self.needs_you_id,
            "screenshot_path": self.screenshot_path,
            "notified": self.notified,
        }


def handle_safety_pause(
    finding: SafetyFinding,
    *,
    app: str,
    pause_app: Optional[Callable[[str], None]] = None,
    pause_all_fn: Optional[Callable[[], None]] = None,
    take_screenshot: Optional[Callable[[], Optional[str]]] = None,
    push_needs_you: Optional[Callable[..., str]] = None,
    notify: Optional[Callable[..., None]] = None,
    force_pause_all: bool = False,
) -> AutoPauseResult:
    """
    On detection: immediately stop that app's loop (or all), screenshot,
    push a Needs-you item + phone notification. Never solve the prompt.
    Resume only when the user taps resume in UI/APK.
    """
    if not finding or not finding.detected:
        return AutoPauseResult(paused=False, app=app, finding=finding)

    pause_all = bool(force_pause_all or finding.pause_all)
    screenshot_path: Optional[str] = None
    needs_you_id: Optional[str] = None
    notified = False

    try:
        if pause_all and pause_all_fn:
            pause_all_fn()
        elif pause_app:
            pause_app(app)
        elif pause_all_fn:
            # Fall back to pausing everything if we only have a global stop.
            pause_all_fn()
            pause_all = True
    except Exception:
        log.exception("Failed to pause loops for safety on %s", app)

    if take_screenshot:
        try:
            screenshot_path = take_screenshot()
        except Exception:
            log.exception("Safety screenshot failed for %s", app)

    title = f"Needs you · {app}"
    body = (
        f"{finding.reason}"
        + (f" — matched “{finding.matched_text}”" if finding.matched_text else "")
        + ". Agent paused. Resume only after you handle this on the phone."
    )
    if push_needs_you:
        try:
            needs_you_id = push_needs_you(
                kind="safety_pause",
                app=app,
                title=title,
                body=body,
                category=finding.category,
                screenshot_path=screenshot_path,
                meta={
                    "source": finding.source,
                    "confidence": finding.confidence,
                    "pause_all": pause_all,
                    "matched_text": finding.matched_text,
                },
            )
        except TypeError:
            # Older signatures may not take kwargs the same way.
            try:
                needs_you_id = push_needs_you(title, body, app=app)  # type: ignore[misc]
            except Exception:
                log.exception("push_needs_you failed for %s", app)
        except Exception:
            log.exception("push_needs_you failed for %s", app)

    if notify:
        try:
            notify(
                title=title,
                body=body,
                app=app,
                kind="safety_pause",
                needs_you_id=needs_you_id,
            )
            notified = True
        except TypeError:
            try:
                notify(title, body)  # type: ignore[misc]
                notified = True
            except Exception:
                log.exception("notify failed for %s", app)
        except Exception:
            log.exception("notify failed for %s", app)

    log.warning(
        "Safety auto-pause app=%s category=%s pause_all=%s reason=%s",
        app,
        finding.category,
        pause_all,
        finding.reason,
    )
    return AutoPauseResult(
        paused=True,
        app=app,
        pause_all=pause_all,
        finding=finding,
        needs_you_id=needs_you_id,
        screenshot_path=screenshot_path,
        notified=notified,
    )
