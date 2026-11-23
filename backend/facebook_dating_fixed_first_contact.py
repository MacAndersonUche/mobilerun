"""Facebook Dating first-contact: photo comment is the free like.

Verified on the S21+ (1080x2400), 23 Nov 2026:
  Ellie, 21  — "hi miss you look beautiful" + Send (980, 1329)
  Amber, 20  — "hi miss you look beautiful" + Send (980, 1329)
  Next card: Kloeé, 24. Nothing paid was tapped.

Route: tap the profile photo → "Say something about this photo..." box
→ type Mac's exact line → Send. Never tap Spotlight, Crush, the heart
Like button, or No Thanks. Daily cap is 50.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import _fp, _parse_compact_nodes, _tree_node_center
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp,
        _parse_compact_nodes,
        _tree_node_center,
    )

PLANNER = "facebook_dating_fixed_first_contact_no_llm_handoff"
DAILY_CAP = 50
# Mac's exact photo-comment text (t254u).
PHOTO_COMMENT_TEXT = "hi miss you look beautiful"
MESSAGE_BANK = (
    "hey how are you",
    "hi miss",
    "hello miss",
    "good morning",
    PHOTO_COMMENT_TEXT,
)
PHOTO_XY = (540, 723)  # center of Profile picture [0,75][1080,1371]
CARD_PHOTO_XY = (540, 1000)  # card stack, above Like/Pass
SEND_XY = (980, 1329)  # desc Send [923,1272][1038,1387]
LIKE_XY = (739, 2116)  # purple heart — never; the comment is the like
PASS_XY = (340, 2116)
EXPLORE_XY = (893, 260)


def comment_text(instruction: str, message: str) -> str:
    """Mac's exact photo-comment line, unless the instruction quotes other text.

    parse_bulk_goal defaults first-contact to 'hey how are you'; ignore that
    generic bank default for Facebook Dating.
    """
    import re

    qm = re.search(r"[\"']([^\"']+)[\"']", instruction or "")
    if qm:
        return qm.group(1).strip()
    raw = (message or "").strip()
    generic = {
        "hey how are you",
        "hi miss",
        "hello miss",
        "good morning",
    }
    if not raw or raw.lower() in generic:
        return PHOTO_COMMENT_TEXT
    return raw


def _blob(tree: str) -> str:
    return (tree or "").lower()


def _on_comment_sheet(tree: str) -> bool:
    blob = _blob(tree)
    return "say something about this photo" in blob


def _on_explore_menu(tree: str) -> bool:
    blob = _blob(tree)
    return "spotlight" in blob and "crush" in blob and not _on_comment_sheet(tree)


def _on_paywall(tree: str) -> bool:
    blob = _blob(tree)
    if _on_comment_sheet(tree):
        return False
    return any(
        n in blob
        for n in (
            "upgrade to premium",
            "get premium",
            "subscribe",
            "boost",
        )
    )


def _profile_photo_center(tree: str) -> Optional[Tuple[int, int]]:
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or n.get("label") or "").strip().lower()
        if d.startswith("profile picture"):
            return (int(n["x"]), int(n["y"]))
    return None


def _send_center(tree: str) -> Optional[Tuple[int, int]]:
    c = _tree_node_center(tree, "Send")
    if c:
        return (int(c[0]), int(c[1]))
    for n in _parse_compact_nodes(tree):
        if str(n.get("desc") or "").strip().lower() == "send":
            return (int(n["x"]), int(n["y"]))
    return None


def _has_like_pass(tree: str) -> bool:
    blob = _blob(tree)
    return "no, thanks" in blob or (
        "like" in blob and "profile picture" in blob
    )


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
    cap = min(DAILY_CAP, max(1, int(target or 1)))
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message_new",
        {"done": 0, "typed": False},
    )
    done = int(bulk.get("done") or 0)
    if done >= cap:
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Facebook Dating first-contact finished {done}/{cap} "
                    f"(daily cap {DAILY_CAP}) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
            },
            "fb_dating_fc_done",
        )

    if _on_explore_menu(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Leave Facebook Dating Explore — never Spotlight/Crush "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "fb_dating_fc_explore_back",
        )

    if _on_paywall(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Facebook Dating paywall — Back, never pay ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "stopped_reason": "paywall",
            },
            "fb_dating_fc_paywall_back",
        )

    text = comment_text(instruction, message)

    if _on_comment_sheet(ui_tree):
        if dry_run:
            bulk["done"] = cap
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] Facebook Dating photo-comment box "
                        f"verified; would send '{text}' — never typed, never "
                        f"Spotlight/Crush ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "would_send_text": text,
                },
                "fb_dating_fc_dry_sheet",
            )
        if not bulk.get("typed"):
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "type",
                    "text": text,
                    "reason": (
                        f"Type photo comment '{text}' ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "clear": True,
                },
                "fb_dating_fc_type",
            )
        send = _send_center(ui_tree) or SEND_XY
        if send in (LIKE_XY, PASS_XY, EXPLORE_XY):
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Refuse Facebook Dating paid/like-heart coords "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_refuse_paid",
            )
        bulk["done"] = done + 1
        bulk["typed"] = False
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": int(send[0]),
                "y": int(send[1]),
                "reason": (
                    f"Facebook Dating Send photo comment "
                    f"{bulk['done']}/{cap} — never Spotlight/Crush "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "fb_dating_fc_send",
        )

    if dry_run:
        bulk["done"] = cap
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"[DRY RUN] would tap photo → type '{text}' → Send to "
                    f"{cap} profiles (daily cap {DAILY_CAP}) — never typed, "
                    f"never Spotlight/Crush ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "dry_run_verified": True,
                "would_send_text": text,
            },
            "fb_dating_fc_dry_card",
        )

    # Profile or card: tap the photo, never the heart / No Thanks.
    photo = _profile_photo_center(ui_tree)
    if photo:
        px, py = int(photo[0]), int(photo[1])
        # If the node is huge, use the verified photo center.
        if py > 1500:
            px, py = PHOTO_XY
        return _fp(
            {
                "action": "tap",
                "x": px if 200 < py < 1600 else PHOTO_XY[0],
                "y": py if 200 < py < 1600 else PHOTO_XY[1],
                "reason": (
                    f"Tap Facebook Dating profile photo to open comment box "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "fb_dating_fc_tap_photo",
        )

    if _has_like_pass(ui_tree) or "dating" in _blob(ui_tree) or "liked you" in _blob(ui_tree):
        return _fp(
            {
                "action": "tap",
                "x": CARD_PHOTO_XY[0],
                "y": CARD_PHOTO_XY[1],
                "reason": (
                    f"Tap Facebook Dating card photo to open profile "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "fb_dating_fc_tap_card",
        )

    return _fp(
        {
            "action": "tap",
            "x": CARD_PHOTO_XY[0],
            "y": CARD_PHOTO_XY[1],
            "reason": (
                f"Tap Facebook Dating photo for first-contact comment "
                f"({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "fb_dating_fc_tap_photo_fallback",
    )
