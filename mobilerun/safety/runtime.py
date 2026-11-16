"""Process-wide safety pause registry — resume only via explicit user action."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from mobilerun.safety.auto_pause import AutoPauseResult, handle_safety_pause
from mobilerun.safety.screen_guard import SafetyFinding, detect_safety_blockers

log = logging.getLogger(__name__)


@dataclass
class SafetyPauseState:
    """Tracks which apps (and optionally all modes) are safety-paused."""

    paused_apps: Set[str] = field(default_factory=set)
    pause_all: bool = False
    last_finding: Optional[Dict[str, Any]] = None
    last_screenshot: Optional[str] = None
    last_needs_you_id: Optional[str] = None
    updated_at: float = 0.0

    def is_paused(self, app: Optional[str] = None) -> bool:
        if self.pause_all:
            return True
        if app and app in self.paused_apps:
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paused_apps": sorted(self.paused_apps),
            "pause_all": self.pause_all,
            "last_finding": self.last_finding,
            "last_screenshot": self.last_screenshot,
            "last_needs_you_id": self.last_needs_you_id,
            "updated_at": self.updated_at,
            "blocked": self.pause_all or bool(self.paused_apps),
        }


# Module singleton (backend + step worker share via import in same process;
# Lambda/API keep state in dating_mode_state too — see backend wiring.)
_state = SafetyPauseState()


def get_safety_state() -> SafetyPauseState:
    return _state


def reset_safety_state() -> None:
    global _state
    _state = SafetyPauseState()


def resume_safety(
    *, app: Optional[str] = None, resume_all: bool = False
) -> SafetyPauseState:
    """Clear pause — only call when Mac taps Resume in UI/APK."""
    st = get_safety_state()
    if resume_all or not app:
        st.paused_apps.clear()
        st.pause_all = False
    else:
        st.paused_apps.discard(app)
        if not st.paused_apps:
            st.pause_all = False
    st.updated_at = time.time()
    return st


def check_screen_and_pause(
    *,
    app: str,
    screen_text: str = "",
    ui_texts: Optional[List[str]] = None,
    ui_tree: Any = None,
    llm_check: bool = False,
    llm_callable: Optional[Callable] = None,
    force_pause_all: bool = False,
    push_needs_you: Optional[Callable[..., str]] = None,
    notify: Optional[Callable[..., None]] = None,
    take_screenshot: Optional[Callable[[], Optional[str]]] = None,
    pause_mode_callbacks: Optional[Dict[str, Callable[[], None]]] = None,
    screenshot_bytes: Optional[bytes] = None,
    screenshot_dir: Optional[Path] = None,
) -> AutoPauseResult:
    """
    Detect blockers; on hit, stop that app (or all), screenshot, Needs-you.
    Never attempts to solve captcha / verification / login.
    """
    finding = detect_safety_blockers(
        screen_text=screen_text,
        ui_texts=ui_texts,
        ui_tree=ui_tree,
        llm_check=llm_check,
        llm_callable=llm_callable,
    )
    if not finding.detected:
        return AutoPauseResult(paused=False, app=app, finding=finding)

    st = get_safety_state()

    def _pause_app(name: str) -> None:
        st.paused_apps.add(name)
        st.pause_all = False
        st.updated_at = time.time()
        cbs = pause_mode_callbacks or {}
        # Pause dating + social loops when the current app is stopped
        for key in ("dating", "social", "normal"):
            fn = cbs.get(key)
            if fn:
                try:
                    fn()
                except Exception:
                    log.exception("pause callback %s failed", key)

    def _pause_all() -> None:
        st.pause_all = True
        st.paused_apps.add(app)
        st.updated_at = time.time()
        cbs = pause_mode_callbacks or {}
        for fn in cbs.values():
            try:
                fn()
            except Exception:
                log.exception("pause-all callback failed")

    def _shot() -> Optional[str]:
        if take_screenshot:
            return take_screenshot()
        if screenshot_bytes is not None:
            dest_dir = screenshot_dir or Path("/tmp/mobilerun-safety")
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = dest_dir / f"safety_{int(time.time())}_{app.replace(' ', '_')}.png"
            path.write_bytes(screenshot_bytes)
            return str(path)
        return None

    result = handle_safety_pause(
        finding,
        app=app,
        pause_app=_pause_app,
        pause_all_fn=_pause_all,
        take_screenshot=_shot,
        push_needs_you=push_needs_you,
        notify=notify,
        force_pause_all=force_pause_all,
    )
    st.last_finding = finding.to_dict()
    st.last_screenshot = result.screenshot_path
    st.last_needs_you_id = result.needs_you_id
    st.updated_at = time.time()
    return result
