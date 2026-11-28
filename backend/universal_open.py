"""Universal app open — FALLBACK when normal open leaves FG wrong / on home.

**Do not replace** per-app open / deck-nav rules that already work. Prefer the
default ``launch_intent`` open first; escalate drawer search / scroll only when
FG is still launcher, SystemUI, Spay, selfhosted, or another non-target package.

Escalation (droidrun / uiautomator2 style):
  1. launch_intent — PackageManager getLaunchIntentForPackage (APK open_app)
  2. home_drawer_search — Home → swipe up drawer → search → type → tap result
  3. drawer_scroll_icon — scroll drawer pages hunting the icon label
  4. reopen_intent — final launch_intent retry after Home

Backend plans the stage; APK executes (``open_mode`` / ``fallback`` params).
Works from launcher, Spay/Wallet, SystemUI shade, selfhosted, any other app.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mobilerun.universal_open")

# Ordered stages — advance when FG still wrong after previous open attempt
OPEN_STAGES: Tuple[str, ...] = (
    "launch_intent",
    "home_drawer_search",
    "drawer_scroll_icon",
    "reopen_intent",
)

# Apps whose a11y is too sparse for drawer search (Hinge Matches/Discover).
_INTENT_ONLY_STAGES: Tuple[str, ...] = ("launch_intent", "reopen_intent")

# After this many full ladders (intent→drawer→scroll→reopen), fail fast
# instead of hanging ~7 min on Taimi/Hinge a11y-launcher loops.
MAX_OPEN_CYCLES = 2

# Dating + social open labels (instruction / package → friendly name)
_APP_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Bumble": ("bumble", "com.bumble.app"),
    "Hily": ("hily", "com.hily.app"),
    "BLK": ("blk", "com.affinityapps.blk", "the league"),
    "Yubo": ("yubo", "co.yellw.yellowapp", "yellow"),
    "Tagged": ("tagged", "com.taggedapp"),
    "Taimi": ("taimi", "com.takimi.android", "takimi"),
    "Hinge": ("hinge", "co.hinge.app"),
    "Badoo": ("badoo", "com.badoo.mobile"),
    "Tinder": ("tinder", "com.tinder"),
    # r50 (no bare "boo": it is inside "facebook")
    "Boo": (" boo ", "enterprises.dating.boo", "boo dating"),
    "Breeze": ("breeze", "social.breeze.breeze_app"),
    "Pure": (" pure ", "com.getpure.pure"),
    "3Fun": ("3fun", "threefun", "com.threesome.swingers.threefun"),
    "WhatsApp": ("whatsapp", "com.whatsapp", "wa"),
    "Instagram": ("instagram", "com.instagram.android"),
    "Messenger": ("messenger", "com.facebook.orca"),
    "Telegram": ("telegram", "org.telegram.messenger"),
}


def resolve_open_label(app_or_pkg: str, instruction: str = "") -> str:
    """Human label for open_app (Bumble, Hily, …)."""
    raw = (app_or_pkg or "").strip()
    blob = f"{raw} {instruction}".lower()
    if not blob.strip():
        return raw or "app"
    for label, keys in _APP_ALIASES.items():
        if any(k and k in blob for k in keys):
            return label
    if raw and not raw.startswith("com.") and not raw.startswith("co."):
        return raw[:1].upper() + raw[1:]
    try:
        from dm_heuristics import DM_APP_PROFILES
    except ImportError:
        from backend.dm_heuristics import DM_APP_PROFILES  # type: ignore

    for key, prof in DM_APP_PROFILES.items():
        pkg = str(prof.get("package") or "").lower()
        if pkg and (pkg in blob or blob.strip() == pkg):
            return str(prof.get("open_label") or key)
        aliases = tuple(prof.get("aliases") or ()) + (key,)
        if any(a and str(a).lower() in blob for a in aliases):
            return str(prof.get("open_label") or key)
    return raw or "app"


def resolve_package(app_or_pkg: str, instruction: str = "") -> str:
    raw = (app_or_pkg or "").strip()
    if "." in raw and " " not in raw:
        return raw
    try:
        from dm_heuristics import DM_APP_PROFILES
    except ImportError:
        from backend.dm_heuristics import DM_APP_PROFILES  # type: ignore

    label = resolve_open_label(raw, instruction).lower()
    for key, prof in DM_APP_PROFILES.items():
        open_l = str(prof.get("open_label") or key).lower()
        if open_l == label or key == label:
            return str(prof.get("package") or "")
        aliases = tuple(prof.get("aliases") or ()) + (key,)
        if any(a and str(a).lower() == label for a in aliases):
            return str(prof.get("package") or "")
    return ""


def _is_intent_only_open(app_or_pkg: str = "", instruction: str = "") -> bool:
    blob = f"{app_or_pkg} {instruction}".lower()
    return "hinge" in blob or "co.hinge.app" in blob


def _stages_for(
    state: Optional[Dict[str, Any]] = None, *, intent_only: bool = False
) -> Tuple[str, ...]:
    st = state if isinstance(state, dict) else {}
    if intent_only or st.get("open_intent_only"):
        return _INTENT_ONLY_STAGES
    return OPEN_STAGES


def current_open_stage(state: Dict[str, Any]) -> str:
    st = state if isinstance(state, dict) else {}
    stages = _stages_for(st)
    stage = str(st.get("open_stage") or stages[0])
    if stage not in stages:
        # Drawer stages are invalid for intent-only apps (Hinge).
        if stage not in OPEN_STAGES:
            return stages[0]
        if stage not in stages:
            return stages[0]
    return stage


def advance_open_stage(state: Dict[str, Any]) -> str:
    """Bump to next open stage; wrap to a new cycle or clamp at last.

    Completing ``reopen_intent`` while FG is still wrong starts a new cycle
    (back to ``launch_intent``) and increments ``open_cycle``. Callers should
    hard-fail via :func:`open_cycles_exhausted` after ``MAX_OPEN_CYCLES``.
    """
    stages = _stages_for(state)
    cur = current_open_stage(state)
    if cur not in stages:
        cur = stages[0]
    idx = stages.index(cur)
    if idx >= len(stages) - 1:
        # Finished one full ladder — start next cycle at launch_intent
        cycles = int(state.get("open_cycle") or 0) + 1
        state["open_cycle"] = cycles
        nxt = stages[0]
        logger.info("universal_open cycle %s complete → restart %s", cycles, nxt)
    else:
        nxt = stages[idx + 1]
    state["open_stage"] = nxt
    attempts = dict(state.get("open_stage_counts") or {})
    attempts[nxt] = int(attempts.get(nxt) or 0) + 1
    state["open_stage_counts"] = attempts
    logger.info("universal_open advance %s → %s", cur, nxt)
    return nxt


def open_cycles_exhausted(state: Dict[str, Any]) -> bool:
    """True after ``MAX_OPEN_CYCLES`` full open ladders failed."""
    return int(state.get("open_cycle") or 0) >= MAX_OPEN_CYCLES


def open_exhausted_fail_action(
    app_or_pkg: str,
    *,
    fg_package: str = "",
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fail action when open escalation has looped too long."""
    st = state if isinstance(state, dict) else {}
    label = resolve_open_label(app_or_pkg)
    cycles = int(st.get("open_cycle") or 0)
    stage = current_open_stage(st)
    return {
        "action": "fail",
        "reason": (
            f"Open escalation exhausted after {cycles} full cycles "
            f"(last stage={stage}, fg={fg_package or '?'}) for {label} — "
            f"a11y/FG never confirmed target (refuse hung open loop)"
        ),
        "planner": "universal_open:exhausted",
        "llm_provider": None,
        "dry_run_verified": False,
    }


def reset_open_stage(state: Dict[str, Any]) -> None:
    if isinstance(state, dict):
        state["open_stage"] = OPEN_STAGES[0]
        state["open_cycle"] = 0


def plan_universal_open(
    app_or_pkg: str,
    *,
    instruction: str = "",
    state: Optional[Dict[str, Any]] = None,
    fg_package: str = "",
    force_stage: Optional[str] = None,
    reason_prefix: str = "",
) -> Dict[str, Any]:
    """Return an open_app action with ``open_mode`` for the APK fallback ladder."""
    st = state if isinstance(state, dict) else {}
    label = resolve_open_label(app_or_pkg, instruction)
    pkg = resolve_package(app_or_pkg or label, instruction)
    if _is_intent_only_open(label, instruction) or _is_intent_only_open(pkg):
        st["open_intent_only"] = True
    stage = force_stage or current_open_stage(st)
    stages = _stages_for(st)
    if stage not in stages:
        # Never run home_drawer_search / drawer_scroll_icon for Hinge.
        if stage in ("home_drawer_search", "drawer_scroll_icon") and st.get(
            "open_intent_only"
        ):
            stage = "reopen_intent"
        else:
            stage = stages[0]
    st["open_stage"] = stage
    prefix = reason_prefix or "Universal open"
    return {
        "action": "open_app",
        "app": label,
        "package": pkg or None,
        "open_mode": stage,
        "fallback": stage != "launch_intent",
        "reason": f"{prefix}: {stage} → {label}"
        + (f" (fg={fg_package})" if fg_package else ""),
        "planner": f"universal_open:{stage}",
        "llm_provider": None,
        "_universal_open": stage,
    }


def should_escalate_open(
    *,
    want_package: str,
    fg_package: str,
    state: Dict[str, Any],
    open_ok: bool = False,
) -> bool:
    """True when we should advance stage (FG still wrong after open)."""
    want = (want_package or "").lower().strip()
    fg = (fg_package or "").lower().strip()
    if not want:
        return False
    if fg and (want in fg or fg in want):
        reset_open_stage(state)
        return False
    # Selfhosted / launcher / chrome after "successful" open → escalate
    bad = (
        not fg
        or "launcher" in fg
        or "systemui" in fg
        or "mobilerun" in fg
        or "selfhosted" in fg
        or "spay" in fg
        or "securefolder" in fg.replace(" ", "")
    )
    return bool(bad or not open_ok)
