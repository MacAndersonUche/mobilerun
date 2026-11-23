"""Hinge first-contact: photo-heart → comment → free Send Like (never Rose).

Verified on the S21+ (1080x2400), 23 Nov 2026:
  Da  — comment "hey how are you" + Send Like (686, 1277)
  Presh — comment "hi miss" + Send Like (686, 1277)

Discover often has an empty a11y tree, so the heart tap uses the stable
photo-heart map (937, 1356) instead of per-card vision. Prompt-heart Y
moves with prompt length and is not used. The like sheet itself has a11y.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _fp,
        hinge_dismiss_enable_prompt,
        hinge_dismiss_play_review,
        hinge_find_compose,
        hinge_like_sheet_action,
        hinge_on_like_sheet,
        hinge_open_discover_tab,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        hinge_dismiss_enable_prompt,
        hinge_dismiss_play_review,
        hinge_find_compose,
        hinge_like_sheet_action,
        hinge_on_like_sheet,
        hinge_open_discover_tab,
    )

PLANNER = "hinge_fixed_first_contact_no_llm_handoff"
MESSAGE_BANK = (
    "hey how are you",
    "hi miss",
    "hello miss",
    "good morning",
)
PHOTO_HEART_XY = (937, 1356)
SEND_LIKE_XY = (686, 1277)
COMMENT_XY = (540, 1102)
DISCOVER_TAB_XY = (110, 2195)
ROSE_BOUNDS = (95, 1225, 355, 1330)

# Full paywalls / rose confirms — Back, never tap. On-card chrome such as
# the Dating Intent chip must not abort. Likes You "Boost" / "Upgrade to
# HingeX" is handled by switching to Discover, not by aborting.
_PAYWALL_SHEETS = (
    "send a rose instead",
    "are you sure you want to send a rose",
    "hinge+ is required",
    "subscribe to hinge",
    "get hinge+",
)


def allowed_message(text: str) -> str:
    raw = (text or "").strip()
    low = raw.lower()
    for phrase in MESSAGE_BANK:
        if low == phrase:
            return phrase
    # Exact text Mac gave in the instruction is allowed.
    if raw:
        return raw
    return MESSAGE_BANK[0]


def in_rose_bounds(x: int, y: int) -> bool:
    x0, y0, x1, y1 = ROSE_BOUNDS
    return x0 <= int(x) <= x1 and y0 <= int(y) <= y1


def _low(tree: str) -> str:
    return (tree or "").lower()


def _on_likes_you(tree: str) -> bool:
    blob = _low(tree)
    if "likes you" in blob:
        return True
    if "upgrade to hingex" in blob and "boost" in blob and not hinge_on_like_sheet(tree):
        return True
    return False


def _on_paywall_sheet(tree: str) -> bool:
    blob = _low(tree)
    if hinge_on_like_sheet(tree) and "send a rose instead" not in blob:
        return False
    return any(p in blob for p in _PAYWALL_SHEETS)


def plan_hinge_fixed_first_contact(
    instruction: str,
    ui_tree: str,
    history: List[str],
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
    dry_run: bool = False,
    message: str = "",
    target: int = 2,
    planner: str = PLANNER,
) -> Optional[Dict[str, Any]]:
    """Plan one first-contact step. No vision / LLM handoff."""
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message_new",
        {"done": 0, "typed": False, "awaiting_sheet": False, "skipped": []},
    )
    done = int(bulk.get("done") or 0)
    if done >= max(1, int(target or 1)):
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Hinge first-contact finished {done}/{target} "
                    f"— never Rose ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
            },
            "hinge_fixed_fc_done",
        )

    play = hinge_dismiss_play_review(ui_tree, planner=planner)
    if play:
        return play
    popup = hinge_dismiss_enable_prompt(ui_tree, planner=planner)
    if popup:
        return popup

    if _on_likes_you(ui_tree) and not hinge_on_like_sheet(ui_tree):
        act = hinge_open_discover_tab(planner=planner)
        act["reason"] = (
            f"Leave Hinge Likes You (Boost/HingeX showing) → Discover "
            f"({planner})"
        )
        return act

    if _on_paywall_sheet(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Hinge paid sheet showing — Back, never tap Rose/"
                    f"HingeX/Boost ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_paywall_back",
        )

    text = allowed_message(message)
    on_sheet = hinge_on_like_sheet(ui_tree) or bool(bulk.get("awaiting_sheet"))
    # Prefer a11y when the like sheet is actually in the tree.
    if hinge_on_like_sheet(ui_tree):
        on_sheet = True
        bulk["awaiting_sheet"] = True
        st["bulk_message_new"] = bulk

    if on_sheet and hinge_on_like_sheet(ui_tree):
        if dry_run:
            bulk["done"] = target
            bulk["typed"] = True
            bulk["awaiting_sheet"] = False
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] Hinge like/comment sheet verified; "
                        f"would send '{text}' — never typed, never Rose "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "would_send_text": text,
                },
                "hinge_fixed_fc_dry_sheet",
            )
        if not bulk.get("typed"):
            compose = hinge_find_compose(ui_tree)
            hist = " ".join(history[-12:]).lower()
            already_focused = (
                "comment" in hist or "typed" in hist or "type " in hist
            )
            if compose and not already_focused and "focus" not in hist:
                return _fp(
                    {
                        "action": "tap",
                        "x": int(compose[0]),
                        "y": int(compose[1]),
                        "reason": f"Focus Add a comment field ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hinge_fixed_fc_focus_comment",
                )
            if not compose and not already_focused and "focus" not in hist:
                return _fp(
                    {
                        "action": "tap",
                        "x": COMMENT_XY[0],
                        "y": COMMENT_XY[1],
                        "reason": f"Focus Add a comment field (map xy) ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hinge_fixed_fc_focus_comment_xy",
                )
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "type",
                    "text": text,
                    "reason": (
                        f"Type like-sheet comment '{text}' for first contact "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "clear": True,
                },
                "hinge_fixed_fc_type",
            )
        send = hinge_like_sheet_action(ui_tree, planner=planner)
        if send:
            sx, sy = int(send.get("x") or 0), int(send.get("y") or 0)
            if in_rose_bounds(sx, sy):
                send = None
            else:
                bulk["done"] = done + 1
                bulk["typed"] = False
                bulk["awaiting_sheet"] = False
                st["bulk_message_new"] = bulk
                send["reason"] = (
                    f"Hinge Send Like first-contact {bulk['done']}/{target} "
                    f"— never Rose ({planner})"
                )
                send["planner"] = planner
                return send
        bulk["done"] = done + 1
        bulk["typed"] = False
        bulk["awaiting_sheet"] = False
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": SEND_LIKE_XY[0],
                "y": SEND_LIKE_XY[1],
                "reason": (
                    f"Hinge Send Like first-contact {bulk['done']}/{target} "
                    f"(map xy) — never Rose ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_send_xy",
        )

    # Not on the like sheet — leave Likes You / Standouts, then tap the
    # photo heart. Never vision, never Dating Intent / Rewind / Rose.
    if _on_likes_you(ui_tree):
        act = hinge_open_discover_tab(planner=planner)
        act["reason"] = (
            f"Leave Hinge Likes You (Boost/HingeX showing) → Discover "
            f"({planner})"
        )
        return act

    if dry_run:
        bulk["done"] = target
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"[DRY RUN] would tap photo heart {PHOTO_HEART_XY} → "
                    f"type '{text}' → Send Like {SEND_LIKE_XY} to "
                    f"{target} new profiles — never typed, never Rose "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "dry_run_verified": True,
                "would_send_text": text,
            },
            "hinge_fixed_fc_dry_discover",
        )

    hist = " ".join(history[-16:]).lower()
    if "discover" not in hist and "photo heart" not in hist and "likes you" not in hist:
        # First live step: land on Discover even if the tree is empty.
        if not bulk.get("_opened_discover"):
            bulk["_opened_discover"] = True
            st["bulk_message_new"] = bulk
            act = hinge_open_discover_tab(planner=planner)
            return act

    bulk["awaiting_sheet"] = True
    bulk["typed"] = False
    st["bulk_message_new"] = bulk
    return _fp(
        {
            "action": "tap",
            "x": PHOTO_HEART_XY[0],
            "y": PHOTO_HEART_XY[1],
            "reason": (
                f"Hinge Discover photo heart {PHOTO_HEART_XY} to open "
                f"like sheet ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_fixed_fc_photo_heart",
    )


# Re-export map so tests and profiles stay in one place.
HINGE_FIXED_MAP = {
    "photo_heart_xy": PHOTO_HEART_XY,
    "send_like_xy": SEND_LIKE_XY,
    "comment_xy": COMMENT_XY,
    "discover_tab_xy": DISCOVER_TAB_XY,
    "rose_button_bounds": ROSE_BOUNDS,
}
