"""Multi-strategy recovery so agent tasks resume instead of failing.

Distinct strategies (rotated before hard-fail):
  1. dismiss_dialogs — ANR / permission / popup
  2. redump_tree — force fresh a11y dump (caller re-fetches)
  3. vision — screenshot + vision planner hint
  4. back — leave stuck overlay
  5. home_then_open — Home + re-open target app
  6. reconnect_wait — leave job running for WS/a11y rebind
  7. alt_path — alternate tap/open for DM / messaging goals
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Must try this many *distinct* strategies before a hard fail
MIN_DISTINCT_STRATEGIES = 5
# Soft retries per strategy before rotating
MAX_PER_STRATEGY = 2

STRATEGIES: List[str] = [
    "dismiss_dialogs",
    "redump_tree",
    "vision",
    "back",
    "scroll",
    "bottom_nav",
    "home_then_open",
    "reconnect_wait",
    "alt_path",
]

# Dating + social labels for home_then_open / reopen
_OPEN_APP_KEYS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("WhatsApp", ("whatsapp",)),
    ("Instagram", ("instagram",)),
    ("Messenger", ("messenger",)),
    ("Telegram", ("telegram",)),
    ("Tinder", ("tinder",)),
    ("Bumble", ("bumble",)),
    ("Hinge", ("hinge",)),
    ("Badoo", ("badoo",)),
    ("Hily", ("hily",)),
    ("BLK", ("blk",)),
    ("Yubo", ("yubo",)),
    ("Tagged", ("tagged",)),
    ("Taimi", ("taimi", "takimi")),
    ("Messages", ("message", "sms", "macai")),
    ("Settings", ("settings",)),
)

_POPUP_LABELS = (
    "while using the app",
    "only this time",
    "allow",
    "allow all",
    "allow once",
    "ok",
    "okay",
    "got it",
    "continue",
    "accept",
    "i agree",
    "agree",
    "close",
    "dismiss",
    "not now",
    "no thanks",
    "wait",
    "close app",
)


def popup_center(tree: str) -> Optional[tuple]:
    """Best-effort center for common permission / ANR buttons."""
    low = (tree or "").lower()
    for label in _POPUP_LABELS:
        for pat in (
            rf'<(?:n|node)\b[^>]*(?:t|d|h|text|content-desc)="[^"]*{re.escape(label)}[^"]*"[^>]*\bxy="(\d+),(\d+)"',
            rf'<(?:n|node)\b[^>]*\bxy="(\d+),(\d+)"[^>]*(?:t|d|h|text|content-desc)="[^"]*{re.escape(label)}[^"]*"',
        ):
            m = re.search(pat, low, re.I)
            if m:
                return (int(m.group(1)), int(m.group(2)))
    return None


def tree_looks_blocked(tree: str) -> bool:
    low = (tree or "").lower()
    if not low or len(low) < 40 or 'empty="true"' in low:
        return True
    blockers = (
        "isn't responding",
        "not responding",
        "close app",
        "allow",
        "while using the app",
        "permission",
        "to send you notifications",
        "turn on",
    )
    return any(b in low for b in blockers) and (
        "allow" in low or "wait" in low or "close app" in low or "permission" in low
    )


def _tried(state: Dict[str, Any]) -> Set[str]:
    raw = state.get("recovery_tried") or []
    return {str(x) for x in raw}


def _mark(state: Dict[str, Any], name: str) -> None:
    tried = list(state.get("recovery_tried") or [])
    if name not in tried:
        tried.append(name)
    state["recovery_tried"] = tried[-20:]
    counts = dict(state.get("recovery_counts") or {})
    counts[name] = int(counts.get(name) or 0) + 1
    state["recovery_counts"] = counts
    state["last_recovery"] = name


def distinct_strategy_count(state: Dict[str, Any]) -> int:
    return len(_tried(state))


def should_hard_fail(state: Dict[str, Any]) -> bool:
    """Only fail after several distinct recovery strategies have been attempted."""
    if distinct_strategy_count(state) < MIN_DISTINCT_STRATEGIES:
        return False
    total = sum(int(v) for v in (state.get("recovery_counts") or {}).values())
    return total >= MIN_DISTINCT_STRATEGIES + 3


def pick_strategy(state: Dict[str, Any], *, prefer: Optional[List[str]] = None) -> str:
    counts = state.get("recovery_counts") or {}
    order = list(prefer or []) + [s for s in STRATEGIES if s not in (prefer or [])]
    # Prefer unused strategies, then least-used under MAX_PER_STRATEGY
    for name in order:
        if name not in _tried(state):
            return name
    for name in order:
        if int(counts.get(name) or 0) < MAX_PER_STRATEGY:
            return name
    return order[0] if order else STRATEGIES[0]


def recovery_action(
    state: Dict[str, Any],
    instruction: str,
    ui_tree: str,
    package: str = "",
    *,
    prefer: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return an executable action dict (or wait sentinel) for the next recovery."""
    name = pick_strategy(state, prefer=prefer)
    _mark(state, name)
    planner = f"recovery:{name}"

    if name == "dismiss_dialogs":
        try:
            from cast_prompt import cancel_cast_prompt_action
        except ImportError:
            from backend.cast_prompt import cancel_cast_prompt_action  # type: ignore
        cap = cancel_cast_prompt_action(ui_tree, state)
        if cap:
            cap["_recovery"] = name
            cap["planner"] = planner
            return cap
        c = popup_center(ui_tree)
        if c:
            return {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Dismiss popup/ANR ({planner})",
                "planner": planner,
                "llm_provider": None,
                "_recovery": name,
            }
        try:
            from taimi_tree_fallback import is_taimi_context
        except ImportError:
            from backend.taimi_tree_fallback import is_taimi_context  # type: ignore
        if is_taimi_context(instruction, package, ui_tree):
            return {
                "action": "wait",
                "seconds": 1.0,
                "reason": (
                    "No popup center on Taimi — wait, never Back "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "_recovery": name,
                "_force_redump": True,
                "_no_llm_handoff": True,
                "_ignore_same_decision": True,
            }
        # No popup center — Back instead of a blind mid-screen tap
        return {
            "action": "back",
            "reason": f"No popup center — Back ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }

    if name == "redump_tree":
        # r70: Taimi compact dumps are often empty while the app is still in
        # front. Back leaves the app (tai3). Wait and re-fetch a full /
        # uiautomator dump instead.
        try:
            from taimi_tree_fallback import is_taimi_context
        except ImportError:
            from backend.taimi_tree_fallback import is_taimi_context  # type: ignore
        if is_taimi_context(instruction, package, ui_tree):
            return {
                "action": "wait",
                "seconds": 1.2,
                "reason": (
                    "Taimi empty tree — wait for full/uiautomator dump, "
                    f"never Back ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "_recovery": name,
                "_force_redump": True,
                "_no_llm_handoff": True,
                "_ignore_same_decision": True,
            }
        return {
            "action": "back",  # mild UI nudge; caller also re-fetches tree
            "reason": f"Nudge UI before re-dump ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
            "_force_redump": True,
        }

    if name == "vision":
        return {
            "action": "_vision_retry",
            "reason": f"Force vision fallback ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
            "_force_vision": True,
        }

    if name == "back":
        try:
            from taimi_tree_fallback import is_taimi_context
        except ImportError:
            from backend.taimi_tree_fallback import is_taimi_context  # type: ignore
        if is_taimi_context(instruction, package, ui_tree):
            return {
                "action": "wait",
                "seconds": 1.2,
                "reason": (
                    "Taimi empty tree — skip recovery Back, "
                    f"wait for a full dump ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "_recovery": name,
                "_force_redump": True,
                "_no_llm_handoff": True,
                "_ignore_same_decision": True,
            }
        return {
            "action": "back",
            "reason": f"Back out of stuck screen ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }

    if name == "scroll":
        return {
            "action": "swipe",
            "x1": 540,
            "y1": 1700,
            "x2": 540,
            "y2": 700,
            "reason": f"Scroll to find content ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }

    if name == "bottom_nav":
        try:
            from stuck_recovery import find_bottom_nav_target
        except ImportError:
            from backend.stuck_recovery import find_bottom_nav_target  # type: ignore

        hit = find_bottom_nav_target(ui_tree)
        if hit:
            x, y, lab = hit
            return {
                "action": "tap",
                "x": x,
                "y": y,
                "label": lab,
                "reason": f"Bottom nav '{lab}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "_recovery": name,
            }
        return {
            "action": "tap",
            "x": 340,
            "y": 2200,
            "reason": f"Bottom nav band (vision) ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
            "needs_vision": True,
            "_force_vision": True,
        }

    if name == "home_then_open":
        # Home + open via universal_open (drawer fallback on APK)
        app = None
        low = (instruction or "").lower()
        for label, keys in _OPEN_APP_KEYS:
            if any(k in low for k in keys):
                app = label
                break
        if app:
            try:
                from universal_open import plan_universal_open
            except ImportError:
                from backend.universal_open import plan_universal_open  # type: ignore

            act = plan_universal_open(
                app,
                instruction=instruction,
                state=state,
                fg_package=package,
                reason_prefix=f"Re-open after stuck ({planner})",
            )
            act["_recovery"] = name
            return act
        return {
            "action": "home",
            "reason": f"Home then resume ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }

    if name == "reconnect_wait":
        return {
            "action": "_reconnect_wait",
            "reason": f"Wait for device/a11y reconnect ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }

    # alt_path — DM / messaging coordinate fallbacks
    low = (instruction or "").lower()
    if "whatsapp" in low or "instagram" in low or "messenger" in low:
        return {
            "action": "tap",
            "x": 980,
            "y": 160,
            "reason": f"Alt Search/DM coords ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }
    if "macai" in low or "5550100" in low or "message" in low:
        return {
            "action": "tap",
            "x": 845,
            "y": 2200,
            "reason": f"Alt Start-chat FAB ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_recovery": name,
        }
    return {
        "action": "back",
        "reason": f"Alt path back ({planner})",
        "planner": planner,
        "llm_provider": None,
        "_recovery": name,
    }
