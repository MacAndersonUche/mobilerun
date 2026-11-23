"""Facebook Dating first-contact from Discover / Liked you.

Verified on the S21+ (1080x2400), 23 Nov 2026, Ellie 21 and Kirsty 25:
cards and profiles expose only Like and No Thanks / Pass. There is no
composer, Send, or Say hi in the a11y tree. Explore lists Spotlight
(timed) and Crush — never tap those.

Messaging appears to be after a match only, so first-contact from
Discover has no free path. Daily cap would be 50 if a free composer
appears later; until then the planner stops.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from dm_heuristics import _fp
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import _fp  # type: ignore

PLANNER = "facebook_dating_fixed_first_contact_no_llm_handoff"
DAILY_CAP = 50
# Verified paid / never-tap controls on Explore and the card.
CRUSH_ROW = "crush"
SPOTLIGHT = "spotlight"
LIKE_XY = (739, 2116)
PASS_XY = (340, 2116)


def _blob(tree: str) -> str:
    return (tree or "").lower()


def plan_facebook_dating_fixed_first_contact(
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
    """Plan one Facebook Dating first-contact step. Never vision, never paid."""
    blob = _blob(ui_tree)
    # If a free composer ever appears, refuse to send until remapped.
    has_compose = any(
        n in blob for n in ("say hi", "write a message", "dating_composer", "send a message")
    )
    if has_compose and "spotlight" not in blob and "blast" not in blob:
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Facebook Dating composer appeared but is not yet a "
                    f"verified free first-message path — stop, never guess "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
                "stopped_reason": "unverified_composer",
            },
            "fb_dating_fc_unverified",
        )
    return _fp(
        {
            "action": "done",
            "reason": (
                f"Facebook Dating Discover/profile has no free first-message: "
                f"only Like / No Thanks. Spotlight and Crush were not tapped. "
                f"Daily cap would be {DAILY_CAP} if a free composer is mapped "
                f"({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "stopped_reason": "no_free_first_contact",
        },
        "fb_dating_fc_none",
    )
