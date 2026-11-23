"""BLK first-contact from Discover.

The Discover card's only message control is the on-card "Send a message"
box, which is the paid message-before-match / Super Like path (never tap).
The cyan heart is a free like, not a first message. Super Like (crown),
Boost, and Get Boost are also paid.

If the Discover feed is empty, stop. Never fall through to Matches
(existing contacts) or to a like-only fallback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from dm_heuristics import (
        _fp,
        blk_dismiss_popup,
        blk_end_of_deck,
        blk_on_deck,
        blk_on_matches,
        blk_on_thread,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp,
        blk_dismiss_popup,
        blk_end_of_deck,
        blk_on_deck,
        blk_on_matches,
        blk_on_thread,
    )

PLANNER = "blk_fixed_first_contact_no_llm_handoff"
# Verified paid / never-tap spots on the S21+ Discover card (Keren, earlier map).
SEND_A_MESSAGE_XY = (300, 1600)
SUPER_LIKE_XY = (790, 1735)
GET_BOOST_XY = (540, 2026)


def _blob(tree: str) -> str:
    return (tree or "").lower()


def _has_paid_card_message(tree: str) -> bool:
    return "send a message" in _blob(tree)


def plan_blk_fixed_first_contact(
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
    """Plan one BLK first-contact step. Never vision, never paid taps."""
    popup = blk_dismiss_popup(ui_tree, planner=planner)
    if popup:
        # Never let a dismiss land on Get Boost / Super Like.
        x, y = int(popup.get("x") or 0), int(popup.get("y") or 0)
        if (x, y) == GET_BOOST_XY or (x, y) == SUPER_LIKE_XY:
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"BLK paid sheet — Back, never Get Boost/Super Like "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "blk_fixed_fc_paywall_back",
            )
        return popup

    if blk_on_thread(ui_tree) or blk_on_matches(ui_tree):
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"BLK first-contact is Discover-only — not existing "
                    f"Matches/threads. Discover has no free first-message "
                    f"(on-card Send a message is paid) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
                "stopped_reason": "no_free_first_contact",
            },
            "blk_fixed_fc_not_existing",
        )

    if blk_end_of_deck(ui_tree) or "reached the end" in _blob(ui_tree):
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"BLK Discover feed is empty (end of feed). No free "
                    f"first-message option — on-card Send a message / Super "
                    f"Like / Boost are paid, never tapped ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
                "stopped_reason": "no_free_first_contact",
            },
            "blk_fixed_fc_end_of_feed",
        )

    if blk_on_deck(ui_tree) or _has_paid_card_message(ui_tree):
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"BLK Discover has no free first-message: on-card "
                    f"'Send a message' is paid message-before-match, and the "
                    f"cyan heart is a like only. Super Like and Boost never "
                    f"tapped ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
                "stopped_reason": "no_free_first_contact",
            },
            "blk_fixed_fc_paid_only",
        )

    return _fp(
        {
            "action": "done",
            "reason": (
                f"BLK has no free Discover first-message path "
                f"({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "stopped_reason": "no_free_first_contact",
        },
        "blk_fixed_fc_none",
    )
