"""Generic stuck-recovery loop — escalate until screen changes or cap.

Order (uiautomator2 / Appium-style):
  1. dismiss_safe — Allow / Don't allow / Not now / Close / X / Later / Skip
     (never paid: Boost, Crush, Rose, SuperSwipe, Gold, …)
  2. press_back
  3. scroll_down / scroll_up
  4. bottom_nav — labels / content-desc / resource-id / bottom 15% band
  5. swipe_up_home_gesture — swipe up from bottom edge
  6. reopen_app — universal_open next stage
  7. vision — force screenshot+vision replan

Caps retries; logs every step via action reason + state.stuck_log.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("mobilerun.stuck_recovery")

MAX_STUCK_STEPS = 12

STUCK_STAGES: Tuple[str, ...] = (
    "dismiss_safe",
    "press_back",
    "scroll_down",
    "scroll_up",
    "bottom_nav",
    "swipe_up_home_gesture",
    "reopen_app",
    "vision",
)

_SAFE_DISMISS = (
    "don't allow",
    "dont allow",
    "not now",
    "no thanks",
    "maybe later",
    "later",
    "skip",
    "close",
    "dismiss",
    "cancel",
    "got it",
    "got it!",
    "ok",
    "okay",
    "while using the app",
    "only this time",
    "allow",  # permission Allow — NOT "Allow payment"
    "deny",
    "no",
)

_NEVER_DISMISS = (
    "allow payment",
    "get boost",
    "boost",
    "crush",
    "major crush",
    "rose",
    "roses",
    "superswipe",
    "super like",
    "superlike",
    "gold",
    "premium",
    "credits",
    "yubucks",
    "blast",
    "hinge+",
    "hingex",
    "buy",
    "purchase",
    "subscribe",
    "upgrade",
    "continue to pay",
    "add card",
)

_BOTTOM_NAV_LABELS = (
    "chats",
    "messages",
    "inbox",
    "chat",
    "people",
    "discover",
    "encounters",
    "explore",
    "meet",
    "browse",
    "nearby",
    "finder",
    "matches",
    "connections",
    "home",
    "for you",
    "feed",
)


def _log_stuck(state: Dict[str, Any], msg: str) -> None:
    log = list(state.get("stuck_log") or [])
    log.append(msg[:160])
    state["stuck_log"] = log[-30:]
    logger.info("stuck_recovery: %s", msg)


def stuck_step(state: Dict[str, Any]) -> int:
    return int(state.get("stuck_step") or 0)


def should_hard_fail_stuck(state: Dict[str, Any]) -> bool:
    return stuck_step(state) >= MAX_STUCK_STEPS


def _is_paid_label(label: str) -> bool:
    low = (label or "").lower().strip()
    if not low:
        return False
    return any(n in low for n in _NEVER_DISMISS)


def _node_xy_label(tree: str) -> List[Tuple[int, int, str]]:
    """Parse compact ``<n … xy= x,y … t/d/h=…>`` nodes → (x,y,label)."""
    out: List[Tuple[int, int, str]] = []
    for m in re.finditer(
        r"<n\b([^>]*)>",
        tree or "",
        re.I,
    ):
        attrs = m.group(1)
        xy = re.search(r'\bxy="(\d+),(\d+)"', attrs)
        if not xy:
            continue
        x, y = int(xy.group(1)), int(xy.group(2))
        label = ""
        for key in ("t", "d", "h", "text", "content-desc"):
            lm = re.search(rf'\b{key}="([^"]*)"', attrs, re.I)
            if lm and lm.group(1).strip():
                label = lm.group(1).strip()
                break
        if not label:
            im = re.search(r'\bi="([^"]+)"', attrs, re.I)
            if im:
                label = im.group(1).rsplit("/", 1)[-1]
        out.append((x, y, label))
    return out


def find_safe_dismiss(tree: str) -> Optional[Tuple[int, int, str]]:
    nodes = _node_xy_label(tree)
    # Prefer exact safe labels; never paid
    for want in _SAFE_DISMISS:
        for x, y, lab in nodes:
            low = lab.lower()
            if _is_paid_label(lab):
                continue
            if want == "allow" and "payment" in low:
                continue
            if low == want or (want in low and len(want) >= 4):
                # Prefer mid/lower screen dismissals
                return (x, y, lab)
    # Content-desc X / close icons near top-right
    for x, y, lab in nodes:
        low = lab.lower().strip()
        if low in ("x", "close", "dismiss") and not _is_paid_label(lab):
            return (x, y, lab)
    return None


def find_bottom_nav_target(
    tree: str,
    *,
    prefer_labels: Sequence[str] = (),
    screen_h: int = 2400,
) -> Optional[Tuple[int, int, str]]:
    """Bottom 15% band: match labels / ids, else left-of-center chats guess."""
    y_min = int(screen_h * 0.85)
    nodes = [(x, y, lab) for x, y, lab in _node_xy_label(tree) if y >= y_min]
    wants = [w.lower() for w in prefer_labels if w] + list(_BOTTOM_NAV_LABELS)
    for want in wants:
        for x, y, lab in nodes:
            low = lab.lower()
            if _is_paid_label(lab):
                continue
            if want in low or low == want:
                return (x, y, lab or want)
    # Unlabeled: pick leftmost bottom clickable-ish (often Discover/Home),
    # then a mid-left chats band — caller may force vision.
    if nodes:
        # Prefer x in chats band ~200–450 on 1080
        chats = [n for n in nodes if 180 <= n[0] <= 480]
        if chats:
            chats.sort(key=lambda t: t[1], reverse=True)
            return (chats[0][0], chats[0][1], chats[0][2] or "bottom_nav")
        nodes.sort(key=lambda t: (t[1], t[0]), reverse=True)
        x, y, lab = nodes[0]
        return (x, y, lab or "bottom_nav")
    return None


def _prefer_nav_for_instruction(instruction: str) -> List[str]:
    low = (instruction or "").lower()
    if any(k in low for k in ("reply", "message", "chat", "inbox", "dm")):
        return ["chats", "messages", "inbox", "chat", "matches", "connections"]
    if any(k in low for k in ("swipe", "like", "pass", "discover", "deck")):
        return [
            "discover",
            "people",
            "encounters",
            "meet",
            "browse",
            "finder",
            "nearby",
        ]
    return []


def next_stuck_action(
    state: Dict[str, Any],
    *,
    instruction: str,
    ui_tree: str,
    package: str = "",
    prefer_pkg: str = "",
    screen_h: int = 2400,
    screen_w: int = 1080,
) -> Dict[str, Any]:
    """Pick next escalation action; increments stuck_step."""
    step = stuck_step(state) + 1
    state["stuck_step"] = step
    stage = STUCK_STAGES[(step - 1) % len(STUCK_STAGES)]
    # After a full cycle, prefer reopen + vision
    if step > len(STUCK_STAGES):
        stage = "reopen_app" if step % 2 == 0 else "vision"
    state["stuck_stage"] = stage
    planner = f"stuck:{stage}"

    if stage == "dismiss_safe":
        hit = find_safe_dismiss(ui_tree)
        if hit:
            x, y, lab = hit
            _log_stuck(state, f"step={step} dismiss '{lab}' @({x},{y})")
            return {
                "action": "tap",
                "x": x,
                "y": y,
                "label": lab,
                "reason": f"Stuck dismiss '{lab}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "_stuck": stage,
            }
        _log_stuck(state, f"step={step} dismiss miss → Back")
        return {
            "action": "back",
            "reason": f"Stuck dismiss miss → Back ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_stuck": stage,
        }

    if stage == "press_back":
        # Never Back-loop on launcher — reopen instead
        try:
            from overlay_dismiss import is_launcher_package
        except ImportError:
            from backend.overlay_dismiss import is_launcher_package  # type: ignore

        if is_launcher_package(package):
            stage = "reopen_app"
        else:
            _log_stuck(state, f"step={step} Back")
            return {
                "action": "back",
                "reason": f"Stuck Back ({planner})",
                "planner": planner,
                "llm_provider": None,
                "_stuck": stage,
            }

    if stage == "scroll_down":
        cx = screen_w // 2
        _log_stuck(state, f"step={step} scroll down")
        return {
            "action": "swipe",
            "x1": cx,
            "y1": int(screen_h * 0.72),
            "x2": cx,
            "y2": int(screen_h * 0.28),
            "reason": f"Stuck scroll down ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_stuck": stage,
        }

    if stage == "scroll_up":
        cx = screen_w // 2
        _log_stuck(state, f"step={step} scroll up")
        return {
            "action": "swipe",
            "x1": cx,
            "y1": int(screen_h * 0.32),
            "x2": cx,
            "y2": int(screen_h * 0.75),
            "reason": f"Stuck scroll up ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_stuck": stage,
        }

    if stage == "bottom_nav":
        prefs = _prefer_nav_for_instruction(instruction)
        hit = find_bottom_nav_target(ui_tree, prefer_labels=prefs, screen_h=screen_h)
        if hit:
            x, y, lab = hit
            _log_stuck(state, f"step={step} bottom_nav '{lab}' @({x},{y})")
            return {
                "action": "tap",
                "x": x,
                "y": y,
                "label": lab,
                "reason": f"Stuck bottom nav '{lab}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "_stuck": stage,
                "needs_vision": not bool(lab and lab.lower() in prefs),
            }
        # Unlabeled band: chats-ish x on 1080
        x, y = int(screen_w * 0.32), int(screen_h * 0.92)
        _log_stuck(state, f"step={step} bottom_nav band @({x},{y}) vision")
        return {
            "action": "tap",
            "x": x,
            "y": y,
            "reason": f"Stuck bottom-nav band (vision) ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_stuck": stage,
            "needs_vision": True,
            "_force_vision": True,
        }

    if stage == "swipe_up_home_gesture":
        cx = screen_w // 2
        _log_stuck(state, f"step={step} swipe up from bottom")
        return {
            "action": "swipe",
            "x1": cx,
            "y1": int(screen_h * 0.96),
            "x2": cx,
            "y2": int(screen_h * 0.55),
            "reason": f"Stuck swipe-up gesture ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_stuck": stage,
        }

    if stage == "reopen_app":
        try:
            from universal_open import advance_open_stage, plan_universal_open
        except ImportError:
            from backend.universal_open import (  # type: ignore
                advance_open_stage,
                plan_universal_open,
            )

        advance_open_stage(state)
        target = prefer_pkg or package or instruction
        act = plan_universal_open(
            target,
            instruction=instruction,
            state=state,
            fg_package=package,
            reason_prefix="Stuck reopen",
        )
        _log_stuck(
            state, f"step={step} reopen {act.get('app')} mode={act.get('open_mode')}"
        )
        act["_stuck"] = "reopen_app"
        return act

    # vision
    _log_stuck(state, f"step={step} vision retry")
    return {
        "action": "_vision_retry",
        "reason": f"Stuck vision fallback ({planner})",
        "planner": planner,
        "llm_provider": None,
        "_stuck": stage,
        "_force_vision": True,
        "needs_vision": True,
    }


def reset_stuck(state: Dict[str, Any]) -> None:
    if not isinstance(state, dict):
        return
    state["stuck_step"] = 0
    state.pop("stuck_stage", None)
