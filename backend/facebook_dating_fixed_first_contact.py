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

import re

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
    if "say something about this photo" in blob:
        return True
    # r46 (CA-7): once typed (or before the hint renders) the placeholder is
    # gone — the box is an editable field with a Send button and no deck
    # Like / No Thanks buttons.
    nodes = _parse_compact_nodes(tree)
    has_edit = any(n.get("editable") for n in nodes)
    has_send = any(
        str(n.get("desc") or n.get("label") or "").strip().lower() == "send"
        for n in nodes
    )
    deck = "profile_circular_button" in blob or "no, thanks" in blob
    return has_edit and has_send and not deck


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
    """The photo itself — never the whole-profile ScrollView.

    r46 (CA-7): the 24 Nov Facebook build labels the profile ScrollView
    "Profile picture, Kirsty, 25 · …" (bounds 0,75..1080,2274, centre
    540,1174 = the bio). It comes first in the tree, so the planner tapped
    the bio three times and the run stopped. Prefer the photo button id,
    then a Profile-picture node that is not a scroller and not full height.
    """
    nodes = _parse_compact_nodes(tree)
    for n in nodes:
        nid = str(n.get("id") or "").lower()
        if "profile_photo" in nid and n.get("x") is not None:
            return (int(n["x"]), int(n["y"]))
    for n in nodes:
        d = str(n.get("desc") or n.get("label") or "").strip().lower()
        if not d.startswith("profile picture"):
            continue
        cls = str(n.get("cls") or n.get("class") or "").lower()
        if "scroll" in cls or n.get("scrollable"):
            continue
        y1, y2 = n.get("y1"), n.get("y2")
        if y1 is not None and y2 is not None and int(y2) - int(y1) > 1500:
            continue
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


_FEED_MARKERS = (
    "what's on your mind", "what’s on your mind", "story tray", "shared with:",
    "write a comment", "home, tab 1", "reels, tab", "marketplace, tab", "'s post",
    "create story", "news feed",
)
FB_NAV_MAX = 6


def _in_dating(tree: str) -> bool:
    """Facebook Dating screens (real 19–24 Nov trees): deck No, Thanks / Like,
    profile photo button, photo comment sheet, Dating header."""
    blob = _blob(tree)
    return (
        _on_comment_sheet(tree)
        or "no, thanks" in blob
        or "profile_photo" in blob
        or "profile_circular_button" in blob
        or bool(re.search(r'd="profile picture, [^"]+, \d{2}', tree or "", re.I))
        or 'd="dating"' in blob and "tab 4 of" not in blob
        or _on_explore_menu(tree)
    )


def facebook_to_dating(
    tree: str, bulk: Dict[str, Any], planner: str
) -> Optional[Dict[str, Any]]:
    """r50: Facebook opened on the main app (feed / a post), not Dating.

    24 Nov 10:55 (task_fd4408515608a893): Facebook resumed on a TSH Tennis
    post viewer; the planner tapped the "card photo" (534,1004) and then the
    post's Profile picture ×3 → same-step stop. Dating is the bottom tab
    "Dating, tab 4 of 6" (real 19 Nov home tree) — close the post first,
    tap that tab, else Menu → Dating, else Back (bounded)."""
    pk = re.search(r'packages="([^"]*)"', tree or "")
    if not pk or "com.facebook.katana" not in pk.group(1):
        return None
    if _in_dating(tree):
        bulk["fb_nav"] = 0
        return None
    blob = _blob(tree)
    nodes = _parse_compact_nodes(tree)

    def lab(n: Dict[str, Any]) -> str:
        return str(n.get("desc") or n.get("text") or n.get("label") or "").strip()

    feedish = any(m in blob for m in _FEED_MARKERS) or "tab 1 of" in blob or (
        "menu" in blob and "facebook logo" in blob)
    n_nav = int(bulk.get("fb_nav") or 0) + 1
    bulk["fb_nav"] = n_nav
    base = {"planner": planner, "llm_provider": None}
    if n_nav > FB_NAV_MAX:
        return _fp({**base, "action": "fail",
                    "reason": f"Could not find Facebook Dating (bottom tab / Menu) after "
                              f"{FB_NAV_MAX} tries ({planner})"}, "fb_dating_nav_lost")
    if bulk.get("fb_tab_tapped") and not any(m in blob for m in _FEED_MARKERS):
        # Dating tab already opened and no feed on screen: Dating home (the
        # tab bar can stay) — hand over to the Dating planner
        bulk["fb_nav"] = 0
        return None
    for n in nodes:
        lo = lab(n).lower()
        if (lo.startswith("dating, tab") or lo == "dating") and n.get("x") is not None:
            bulk["fb_tab_tapped"] = True
            return _fp({**base, "action": "tap", "x": int(n["x"]), "y": int(n["y"]),
                        "reason": f"Open Facebook Dating — bottom tab '{lab(n)[:30]}' ({planner})"},
                       "fb_dating_nav_tab")
    if not feedish and not any(lab(n).lower() in ("close", "menu") for n in nodes):
        return None  # unknown Facebook screen — let the Dating planner decide
    for n in nodes:
        if lab(n).lower() == "close" and n.get("clickable") and n.get("x") is not None \
                and int(n.get("y") or 9999) < 300:
            return _fp({**base, "action": "tap", "x": int(n["x"]), "y": int(n["y"]),
                        "reason": f"Facebook post open, not Dating — Close it ({planner})"},
                       "fb_dating_nav_close_post")
    if not bulk.get("fb_menu_tried"):
        for n in nodes:
            if lab(n).lower() == "menu" and n.get("x") is not None:
                bulk["fb_menu_tried"] = True
                return _fp({**base, "action": "tap", "x": int(n["x"]), "y": int(n["y"]),
                            "reason": f"No Dating tab — open the Facebook Menu ({planner})"},
                           "fb_dating_nav_menu")
    if n_nav >= 3 and not bulk.get("fb_scrolled_top"):
        bulk["fb_scrolled_top"] = True
    return _fp({**base, "action": "press_button", "button": "back",
                "reason": f"Not in Facebook Dating — Back toward the tab bar ({planner})"},
               "fb_dating_nav_back")


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
    if done >= cap and not (
        bulk.get("awaiting_send") and not dry_run and _on_comment_sheet(ui_tree)
        and int(bulk.get("send_retry") or 0) < 1
        and comment_text(instruction, message).lower()
        in _blob(ui_tree)
    ):
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

    nav = facebook_to_dating(ui_tree, bulk, planner)
    if nav:
        st["bulk_message_new"] = bulk
        return nav

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
        bulk["awaiting_sheet"] = 0
        # r46: the line still in the box after Send → tap Send once more,
        # never type it again (no double message to the same person).
        box = ""
        for n in _parse_compact_nodes(ui_tree):
            if n.get("editable"):
                box = str(n.get("text") or "").strip()
        if bulk.get("awaiting_send") and not dry_run:
            if box.lower() == text.lower():
                if int(bulk.get("send_retry") or 0) < 1:
                    bulk["send_retry"] = 1
                    st["bulk_message_new"] = bulk
                    send = _send_center(ui_tree) or SEND_XY
                    return _fp(
                        {
                            "action": "tap",
                            "x": int(send[0]),
                            "y": int(send[1]),
                            "reason": f"Comment still in the box — tap Send again ({planner})",
                            "planner": planner,
                            "llm_provider": None,
                        },
                        "fb_dating_fc_send_retry",
                    )
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Facebook Dating comment did not send after a retry "
                            f"— stop, nothing paid ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "fb_dating_fc_not_sent",
                )
            bulk["awaiting_send"] = False
            bulk["send_retry"] = 0
            st["bulk_message_new"] = bulk
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
        bulk["awaiting_send"] = True
        bulk["send_retry"] = 0
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
        bulk["awaiting_sheet"] = 1
        st["bulk_message_new"] = bulk
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

    # r46: the comment box can take a moment to render after the photo tap —
    # wait for it instead of tapping (540,1000), which closed it (24 Nov).
    waited = int(bulk.get("awaiting_sheet") or 0)
    if waited and waited <= 2 and not _has_like_pass(ui_tree):
        bulk["awaiting_sheet"] = waited + 1
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "wait",
                "seconds": 1.0,
                "delay_s": 1.0,
                "reason": f"Waiting for the photo comment box ({waited}/2) ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "fb_dating_fc_wait_sheet",
        )
    bulk["awaiting_sheet"] = 0

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
