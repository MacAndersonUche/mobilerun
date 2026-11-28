"""Facebook Dating first-contact: photo comment is the free like.

Verified on the S21+ (1080x2400), 23 Nov 2026:
  Ellie, 21  — "hi miss you look beautiful" + Send (980, 1329)
  Amber, 20  — "hi miss you look beautiful" + Send (980, 1329)
  Next card: Kloeé, 24. Nothing paid was tapped.

Mac's 27 Nov video: tap the centre of the profile photo on the deck
→ "Say something about this photo..." → type Mac's exact line → the
purple send chevron. Never the heart (a bare like can go out without
the text). Never Spotlight, Crush, or a paid item. Daily cap is 50.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        _compose_editable,
        _fp as _fp_raw,
        _parse_compact_nodes,
        _tree_node_center,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _compose_editable,
        _fp as _fp_raw,
        _parse_compact_nodes,
        _tree_node_center,
    )


def _fp(action: Dict[str, Any], step: str) -> Dict[str, Any]:
    """Tag the step and never allow an LLM handoff on this planner."""
    action = dict(action)
    action["_no_llm_handoff"] = True
    action.setdefault("llm_provider", None)
    return _fp_raw(action, step)


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
    "good evening beautiful",
)
PHOTO_XY = (540, 723)  # center of Profile picture [0,75][1080,1371]
CARD_PHOTO_XY = (540, 1000)  # card stack, above Like/Pass
SEND_XY = (980, 1329)  # desc Send [923,1272][1038,1387]
LIKE_XY = (739, 2116)  # purple heart — video: opens profile / comment box
PASS_XY = (340, 2116)
EXPLORE_XY = (893, 260)


def comment_text(
    instruction: str,
    message: str,
    state: Optional[Dict[str, Any]] = None,
) -> str:
    """Photo-comment from portal opener library (fallback: MESSAGE_BANK).

    Custom quoted text in the instruction (not the baked-in dating_run default)
    still wins. The baked-in ``hi miss you look beautiful`` quote is treated as
    a library hint so the opener bank can rotate.
    """
    import re

    qm = re.search(r"[\"']([^\"']+)[\"']", instruction or "")
    quoted = qm.group(1).strip() if qm else ""
    bank_low = {p.lower() for p in MESSAGE_BANK}
    # Custom Mac quote (not a known bank / default photo line) wins.
    if quoted and quoted.lower() not in bank_low:
        return quoted
    try:
        from mobilerun.dating.openers import pick_runner_first_contact_text
    except ImportError:  # pragma: no cover
        from dating.openers import pick_runner_first_contact_text  # type: ignore
    return pick_runner_first_contact_text(
        fallback_bank=MESSAGE_BANK,
        message=message or quoted or PHOTO_COMMENT_TEXT,
        state=state if isinstance(state, dict) else None,
        package_name="com.facebook.katana",
    )


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


def _like_center(tree: str) -> Optional[Tuple[int, int]]:
    """The purple heart ("Like" node) on the card or the profile.

    Video (24 Nov 2026): tapping it opens the profile from the deck and
    the "Say something about this photo..." box from the profile — it
    never sends a bare like. Exact label only, so "Liked you" chips and
    "Like" headers never match.
    """
    for n in _parse_compact_nodes(tree):
        if str(n.get("desc") or n.get("label") or "").strip().lower() != "like":
            continue
        if n.get("x") is None:
            continue
        return (int(n["x"]), int(n["y"]))
    return None


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
    """The Send chevron next to the comment box — never a nav-level node.

    27 Nov fb3 retried Send at (985, 2191) once the keyboard had closed,
    which sits on the bottom nav, not the photo-comment Send (~1329).
    """

    def _ok(x: int, y: int) -> Optional[Tuple[int, int]]:
        if y >= 2000:
            return None
        return (x, y)

    c = _tree_node_center(tree, "Send")
    if c:
        got = _ok(int(c[0]), int(c[1]))
        if got:
            return got
    for n in _parse_compact_nodes(tree):
        if (
            str(n.get("desc") or "").strip().lower() == "send"
            and n.get("x") is not None
        ):
            got = _ok(int(n["x"]), int(n["y"]))
            if got:
                return got
    return None


def _norm_name(name: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r",\s*\d{2}$", "", s)
    return " ".join(s.strip().lower().split())


# Already first-contacted tonight (or earlier runs). Never message again.
DEFAULT_SKIP = ("Gabbie", "Lorna-Mae", "Leah", "Troy")
_NAME_IN_PHOTO = re.compile(r"profile picture,\s*([^,]+),\s*\d{2}", re.I)
_NAME_AGE = re.compile(r"^([A-Za-z][A-Za-z0-9'’.\- ]+),\s*\d{2}$")


def _profile_name(tree: str) -> str:
    """Foreground profile name from the photo button / 'Name, 24' label.

    The deck can show two cards at once (27 Nov: Gabbie in front, Lorna-Mae
    behind). Prefer the photo-button desc, then the first Name, 24.
    """
    # The deck tree often lists the card underneath first and the
    # visible front card last (27 Nov fb4: Meghan then Leah; the
    # screenshot was Leah). Last on-screen match wins.
    nodes = _parse_compact_nodes(tree)
    found = ""
    for n in nodes:
        nid = str(n.get("id") or "").lower()
        d = _nlab(n)
        cls = str(n.get("cls") or n.get("class") or "").lower()
        if "scroll" in cls or n.get("scrollable"):
            continue
        if n.get("visible") is False:
            continue
        if "profile_photo" in nid or d.lower().startswith("profile picture"):
            m = _NAME_IN_PHOTO.search(d)
            if m:
                found = m.group(1).strip()
    if found:
        return found
    for n in nodes:
        t = str(n.get("text") or "").strip()
        m = _NAME_AGE.match(t)
        if m and int(n.get("y") or 0) < 1800:
            found = m.group(1).strip()
    return found


def _skip_set(bulk: Dict[str, Any]) -> set:
    names = list(DEFAULT_SKIP)
    names.extend(bulk.get("skip_names") or [])
    names.extend(bulk.get("sent_names") or [])
    return {_norm_name(x) for x in names if x}


def _is_skip(bulk: Dict[str, Any], name: str) -> bool:
    return bool(name and _norm_name(name) in _skip_set(bulk))


def _remember_sent(bulk: Dict[str, Any], name: str) -> None:
    if not name:
        return
    names = list(bulk.get("sent_names") or [])
    if _norm_name(name) not in {_norm_name(x) for x in names}:
        names.append(name)
        bulk["sent_names"] = names


def _pass_center(tree: str) -> Optional[Tuple[int, int]]:
    """The free 'No, Thanks' pass — never the purple heart."""
    for n in _parse_compact_nodes(tree):
        lab = _nlab(n).lower().replace(" ", "")
        nid = str(n.get("id") or "").lower()
        if lab in ("no,thanks", "nothanks") or "button_pass" in nid:
            if n.get("x") is not None:
                xy = (int(n["x"]), int(n["y"]))
                if xy != LIKE_XY and xy[0] < 540:
                    return xy
    if _has_like_pass(tree):
        return PASS_XY
    return None


def _like_sent(tree: str) -> bool:
    return "like sent" in _blob(tree)


def _send_evidence(tree: str, text: str, pending_name: str) -> str:
    """Did this send land? 'yes', 'no' (still in the box / same card), or 'wait'.

    Never treat a blank or mid-animation tree as a send (27 Nov fb4: a
    brief non-sheet tree after the Send tap counted Meghan while the
    comment was still in the box).
    """
    want = (text or "").strip().lower()
    if _like_sent(tree):
        return "yes"
    if _on_comment_sheet(tree):
        # An empty or missing box on the same sheet is not enough — the
        # IME flicker after focus/Send looked "empty" and fb4–fb6 counted
        # while the line was still in the EditText. Only "Like sent" is
        # a yes while the sheet is still up.
        if _like_sent(tree):
            return "yes"
        box_node = _compose_editable(tree)
        box = str(box_node.get("text") or "").strip() if box_node else ""
        if want and box.lower() == want:
            return "no"
        return "wait"
    name = _profile_name(tree)
    if name and pending_name and _norm_name(name) != _norm_name(pending_name):
        return "yes"
    if name and pending_name and _norm_name(name) == _norm_name(pending_name):
        return "no"
    if name and _has_like_pass(tree) and not pending_name:
        # Sheet closed onto a named card and we did not know the sender
        # name from the sheet — this is the post-send next/same card used
        # in unit tests, and the 23 Nov verified path (next card appears).
        return "yes"
    return "wait"


_SENT_VISION = (
    'Facebook Dating screenshot. Did a photo comment just send — a "Like '
    'sent" confirmation, or is the comment box gone and a new profile card '
    'showing? If the text is still only in the "Say something about this '
    'photo" box and has not sent, or you still see the same comment sheet, '
    "answer NO. Reply YES or NO only."
)


def _has_like_pass(tree: str) -> bool:
    blob = _blob(tree)
    return "no, thanks" in blob or ("like" in blob and "profile picture" in blob)


_FEED_MARKERS = (
    "what's on your mind",
    "what’s on your mind",
    "story tray",
    "shared with:",
    "write a comment",
    "home, tab 1",
    "reels, tab",
    "marketplace, tab",
    "'s post",
    "create story",
    "news feed",
)
FB_NAV_MAX = 6


def _vis_blob(tree: str) -> str:
    """Visible nodes only. r51: Facebook keeps the off-screen feed in the tree
    (v="0", negative x: "What's on your mind?", "Story tray") while Dating is
    showing — the raw tree text made Dating look like the feed."""
    return " | ".join(
        f"{n.get('desc') or ''} {n.get('text') or ''}".strip()
        for n in _parse_compact_nodes(tree)
    ).lower()


def _nlab(n: Dict[str, Any]) -> str:
    return str(n.get("desc") or n.get("text") or n.get("label") or "").strip()


def _dating_home(tree: str) -> bool:
    """Real 24 Nov 11:17 tree (task_18cd1e4745926294): header "Dating" +
    "Dating settings" button + "Liked you · Friendship · Matches" chips."""
    vb = _vis_blob(tree)
    return "dating settings" in vb or (
        "liked you" in vb
        and any(
            _nlab(n).lower() == "dating" and int(n.get("y") or 9999) < 300
            for n in _parse_compact_nodes(tree)
        )
    )


def _in_dating(tree: str) -> bool:
    """Facebook Dating screens (real 19–24 Nov trees): Dating home, deck
    No, Thanks / Like, profile photo button, photo comment sheet."""
    blob = _blob(tree)
    return (
        _on_comment_sheet(tree)
        or _dating_home(tree)
        or "no, thanks" in blob
        or "profile_photo" in blob
        or "profile_circular_button" in blob
        or bool(re.search(r'd="profile picture, [^"]+, \d{2}', tree or "", re.I))
        or _on_explore_menu(tree)
    )


def facebook_to_dating(
    tree: str, bulk: Dict[str, Any], planner: str
) -> Optional[Dict[str, Any]]:
    """Facebook is not on Dating → get there (never a blind tap).

    r50 (10:55, task_fd4408515608a893): Facebook resumed on a post viewer.
    r51 (11:17, task_18cd1e4745926294): (1) the first screen was the Samsung
    home screen and the planner's fallback tapped (539,999) on it; (2) after
    the real tap on "Dating, tab 4 of 6" Dating home was showing, but the
    hidden feed nodes still in the tree said "feed", so it tapped the
    non-clickable "Dating" header (529,133) ×3 → same-step stop.
    Order: other app → open Facebook; post → Close; bottom "Dating, tab N of
    6" (y > 1900); after Menu → the "Dating" shortcut; else Back (bounded)."""
    pk = re.search(r'packages="([^"]*)"', tree or "")
    pkgs = pk.group(1) if pk else ""
    base = {"planner": planner, "llm_provider": None}
    if "com.facebook.katana" not in pkgs:
        if not (tree or "").strip() or not pkgs:
            return None
        n_open = int(bulk.get("fb_open") or 0) + 1
        bulk["fb_open"] = n_open
        if n_open > 3:
            return _fp(
                {
                    **base,
                    "action": "fail",
                    "reason": f"Facebook did not open (on {pkgs}) ({planner})",
                },
                "fb_dating_nav_open_failed",
            )
        return _fp(
            {
                **base,
                "action": "open_app",
                "app": "Facebook",
                "package": "com.facebook.katana",
                "reason": f"On {pkgs.split(',')[0]}, not Facebook — open Facebook "
                f"(never tap blind) ({planner})",
            },
            "fb_dating_nav_open",
        )
    if _in_dating(tree):
        bulk["fb_nav"] = 0
        return None
    nodes = _parse_compact_nodes(tree)
    n_nav = int(bulk.get("fb_nav") or 0) + 1
    bulk["fb_nav"] = n_nav
    if n_nav > FB_NAV_MAX:
        return _fp(
            {
                **base,
                "action": "fail",
                "reason": f"Could not find Facebook Dating (bottom tab / Menu) after "
                f"{FB_NAV_MAX} tries ({planner})",
            },
            "fb_dating_nav_lost",
        )
    for n in nodes:
        lo = _nlab(n).lower()
        if (
            lo.startswith("dating, tab")
            and n.get("x") is not None
            and int(n.get("y") or 0) > 1900
        ):
            bulk["fb_tab_tapped"] = True
            return _fp(
                {
                    **base,
                    "action": "tap",
                    "x": int(n["x"]),
                    "y": int(n["y"]),
                    "reason": f"Open Facebook Dating — bottom tab '{_nlab(n)[:30]}' "
                    f"({planner})",
                },
                "fb_dating_nav_tab",
            )
    if bulk.get("fb_menu_tried"):
        for n in nodes:
            if (
                _nlab(n).lower() == "dating"
                and n.get("x") is not None
                and int(n.get("y") or 0) > 250
            ):
                return _fp(
                    {
                        **base,
                        "action": "tap",
                        "x": int(n["x"]),
                        "y": int(n["y"]),
                        "reason": f"Facebook Menu → Dating shortcut ({planner})",
                    },
                    "fb_dating_nav_menu_dating",
                )
    for n in nodes:
        if (
            _nlab(n).lower() == "close"
            and n.get("clickable")
            and n.get("x") is not None
            and int(n.get("y") or 9999) < 300
        ):
            return _fp(
                {
                    **base,
                    "action": "tap",
                    "x": int(n["x"]),
                    "y": int(n["y"]),
                    "reason": f"Facebook post open, not Dating — Close it ({planner})",
                },
                "fb_dating_nav_close_post",
            )
    if not bulk.get("fb_menu_tried"):
        for n in nodes:
            if _nlab(n).lower() == "menu" and n.get("x") is not None:
                bulk["fb_menu_tried"] = True
                return _fp(
                    {
                        **base,
                        "action": "tap",
                        "x": int(n["x"]),
                        "y": int(n["y"]),
                        "reason": f"No Dating tab — open the Facebook Menu ({planner})",
                    },
                    "fb_dating_nav_menu",
                )
    return _fp(
        {
            **base,
            "action": "press_button",
            "button": "back",
            "reason": f"Not in Facebook Dating — Back toward the tab bar ({planner})",
        },
        "fb_dating_nav_back",
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
    text_now = comment_text(instruction, message, state=st)
    if _on_comment_sheet(ui_tree):
        box_node = _compose_editable(ui_tree)
        box_now = str(box_node.get("text") or "").strip() if box_node else ""
        if (
            box_now.lower() == text_now.lower()
            and text_now
            and not dry_run
            and bulk.get("counted_this_send")
        ):
            # The comment is still in the box — the earlier count was wrong
            # (fb6 counted after focus_send, then finished 1/1).
            done = max(0, done - 1)
            bulk["done"] = done
            bulk["counted_this_send"] = False
            bulk["awaiting_send"] = True
            bulk["pending_count"] = True
            bulk["send_retry"] = 0
    if done >= cap and not (
        bulk.get("awaiting_send")
        and not dry_run
        and _on_comment_sheet(ui_tree)
        and (int(bulk.get("send_retry") or 0) < 2 or text_now.lower() in _blob(ui_tree))
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

    # Off the sheet: count a pending send first (the sheet closed or the
    # next profile appeared). Never increment at the Send tap itself —
    # a retry at the closed-keyboard nav (fb3) used to count a miss.
    pending_text = comment_text(instruction, message, state=st)
    if (
        not _on_comment_sheet(ui_tree)
        and (
            bulk.get("awaiting_send")
            or bulk.get("just_sent")
            or bulk.get("pending_count")
        )
        and not bulk.get("counted_this_send")
    ):
        ev = _send_evidence(ui_tree, pending_text, str(bulk.get("pending_name") or ""))
        if ev == "yes" and not dry_run:
            done += 1
            bulk["done"] = done
            bulk["counted_this_send"] = True
            _remember_sent(bulk, str(bulk.get("pending_name") or ""))
            bulk["awaiting_send"] = False
            bulk.pop("just_sent", None)
            bulk.pop("closing", None)
            bulk["pending_count"] = False
            bulk["confirm_tries"] = 0
            st["bulk_message_new"] = bulk
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
        elif ev == "wait" or ev == "no":
            tries = int(bulk.get("confirm_tries") or 0) + 1
            bulk["confirm_tries"] = tries
            st["bulk_message_new"] = bulk
            if tries <= 3:
                return _fp(
                    {
                        "action": "wait",
                        "seconds": 1.0,
                        "delay_s": 1.0,
                        "reason": (
                            f"Waiting to confirm the Facebook Dating send "
                            f"({tries}/3) ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "fb_dating_fc_wait_confirm",
                )
            # Same card or still ambiguous after waits: do not count.
            bulk["awaiting_send"] = False
            bulk["pending_count"] = False
            bulk.pop("just_sent", None)
            bulk.pop("closing", None)
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Facebook Dating send was not confirmed — stop, "
                        f"will not count it ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_not_confirmed",
            )
    if not _on_comment_sheet(ui_tree) and not (
        bulk.get("awaiting_send") or bulk.get("just_sent") or bulk.get("pending_count")
    ):
        bulk["type_tries"] = 0
        bulk["focus_tries"] = 0

    # r46/r51: after a photo tap the next tree can be a brief blank
    # ("waiting for the comment box") — don't Back out of Dating.
    if not int(bulk.get("awaiting_sheet") or 0):
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
                "reason": (f"Facebook Dating paywall — Back, never pay ({planner})"),
                "planner": planner,
                "llm_provider": None,
                "stopped_reason": "paywall",
            },
            "fb_dating_fc_paywall_back",
        )

    text = comment_text(instruction, message, state=st)
    name = _profile_name(ui_tree)
    if name:
        bulk["name"] = name

    # Already-messaged or skip-list people: Back out of a comment sheet
    # (never send), then tap No Thanks — never the heart.
    # Only skip when this tree actually names the person — a stale
    # bulk["name"] on Dating home must not fire No Thanks.
    skip_name = name or (
        str(bulk.get("name") or "") if _on_comment_sheet(ui_tree) else ""
    )
    if _is_skip(bulk, skip_name):
        name = skip_name
        if _on_comment_sheet(ui_tree):
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Already messaged {name or bulk.get('name')} — "
                        f"Back, will not send ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_skip_back",
            )
        xy = _pass_center(ui_tree)
        if xy and xy != LIKE_XY:
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": int(xy[0]),
                    "y": int(xy[1]),
                    "reason": (
                        f"Skip {name or bulk.get('name')} (already messaged) "
                        f"— No Thanks, never the heart ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_skip_pass",
            )

    if _on_comment_sheet(ui_tree):
        bulk["awaiting_sheet"] = 0
        # The box, from the tree: its text, whether it is focused, and
        # where to tap to focus it. Typing is never issued on an unfocused
        # box, and Send is never tapped until the exact line is in the box.
        box_node = _compose_editable(ui_tree)
        box = str(box_node.get("text") or "").strip() if box_node else ""
        box_focused = bool(box_node and box_node.get("focused"))
        box_xy = (int(box_node["x"]), int(box_node["y"])) if box_node else None
        # A fresh empty / placeholder box means the previous confirmed
        # send is behind us. The empty-sheet fixture (and the live app)
        # often put the hint "Say something about this photo..." in text.
        hint = str((box_node or {}).get("hint") or "").strip().lower()
        box_fresh = (
            (not box)
            or box.lower() == hint
            or box.lower().startswith("say something about this photo")
        )
        if box_fresh and not bulk.get("awaiting_send"):
            bulk["counted_this_send"] = False
            bulk["send_retry"] = 0
        # Leftover draft from a previous job (27 Nov fb4 left
        # "good evening beautiful" in the box and then went home). Never
        # send it blindly — we may not know who the sheet belongs to.
        if (
            box.lower() == text.lower()
            and not bulk.get("awaiting_send")
            and not bulk.get("typed")
            and not dry_run
        ):
            if not bulk.get("cleared_draft"):
                bulk["cleared_draft"] = True
                st["bulk_message_new"] = bulk
                return _fp(
                    {
                        "action": "type",
                        "text": "",
                        "clear": True,
                        "_clear_only": True,
                        "reason": (
                            f"Clear leftover photo comment"
                            f"{(' for ' + (name or 'this profile')) if name else ''}"
                            f" — will not send ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "fb_dating_fc_clear_draft",
                )
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Leftover photo comment cleared — Back, will not send "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_draft_back",
            )
        # r46: the line still in the box after Send → tap Send once more,
        # never type it again (no double message to the same person).
        if bulk.get("awaiting_send") and not dry_run:
            if box.lower() == text.lower():
                if int(bulk.get("send_retry") or 0) < 1:
                    bulk["send_retry"] = 1
                    st["bulk_message_new"] = bulk
                    send = _send_center(ui_tree)
                    if not send:
                        if box_xy:
                            return _fp(
                                {
                                    "action": "tap",
                                    "x": int(box_xy[0]),
                                    "y": int(box_xy[1]),
                                    "reason": (
                                        f"Open the keyboard so Send sits above the nav "
                                        f"({planner})"
                                    ),
                                    "planner": planner,
                                    "llm_provider": None,
                                },
                                "fb_dating_fc_focus_send",
                            )
                        send = SEND_XY
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
            # The line left the box after Send: it went. Never type again
            # on this sheet — wait for it to close, then Back out.
            bulk["awaiting_send"] = False
            bulk["send_retry"] = 0
            bulk["just_sent"] = True
            bulk["close_tries"] = 0
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
        if (
            bulk.get("just_sent")
            or bulk.get("awaiting_send")
            or bulk.get("pending_count")
        ) and _send_evidence(
            ui_tree, text, str(bulk.get("pending_name") or "")
        ) == "yes":
            if not bulk.get("counted_this_send") and not dry_run:
                done += 1
                bulk["done"] = done
                bulk["counted_this_send"] = True
                _remember_sent(bulk, str(bulk.get("pending_name") or name or ""))
            bulk["just_sent"] = False
            bulk["awaiting_send"] = False
            bulk["closing"] = True
            st["bulk_message_new"] = bulk
            act = _fp(
                {
                    "action": "wait",
                    "seconds": 1.0,
                    "delay_s": 1.0,
                    "reason": (
                        f"Comment sent"
                        f"{(' to ' + (bulk.get('pending_name') or name)) if (bulk.get('pending_name') or name) else ''}"
                        f" — waiting for the next profile ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "_vision_check": _SENT_VISION,
                    "_vision_tag": "fb_dating_sent",
                },
                "fb_dating_fc_wait_close",
            )
            return act
        if bulk.get("closing"):
            if box.lower() == text.lower():
                # The line is back in the box: the send did not land.
                # One more Send tap, never a retype, never a recount.
                if int(bulk.get("send_retry") or 0) < 1:
                    bulk["send_retry"] = 1
                    bulk["closing"] = False
                    bulk["awaiting_send"] = True
                    st["bulk_message_new"] = bulk
                    send = _send_center(ui_tree)
                    if not send:
                        if box_xy:
                            return _fp(
                                {
                                    "action": "tap",
                                    "x": int(box_xy[0]),
                                    "y": int(box_xy[1]),
                                    "reason": (
                                        f"Open the keyboard so Send sits above the nav "
                                        f"({planner})"
                                    ),
                                    "planner": planner,
                                    "llm_provider": None,
                                },
                                "fb_dating_fc_focus_send",
                            )
                        send = SEND_XY
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
            tries = int(bulk.get("close_tries") or 0) + 1
            bulk["close_tries"] = tries
            st["bulk_message_new"] = bulk
            if tries > 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Facebook Dating comment sheet did not close "
                            f"after send — stop, nothing paid ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "fb_dating_fc_close_fail",
                )
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Comment sent — dismiss the sheet ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_close_back",
            )
        # Send only when the exact line is verified in the box. A type
        # that never landed (empty box / placeholder still showing) must
        # never reach Send, and must never count as a send.
        if box.lower() == text.lower():
            send = _send_center(ui_tree) or (SEND_XY if SEND_XY[1] < 2000 else None)
            if not send:
                if box_xy:
                    return _fp(
                        {
                            "action": "tap",
                            "x": int(box_xy[0]),
                            "y": int(box_xy[1]),
                            "reason": (
                                f"Open the keyboard so Send sits above the nav "
                                f"({planner})"
                            ),
                            "planner": planner,
                            "llm_provider": None,
                        },
                        "fb_dating_fc_focus_send",
                    )
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Facebook Dating Send not found above the nav "
                            f"— stop, nothing sent ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "fb_dating_fc_no_send",
                )
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
            bulk["typed"] = False
            bulk["awaiting_send"] = True
            bulk["counted_this_send"] = False
            bulk["pending_count"] = True
            bulk["pending_name"] = name or str(bulk.get("name") or "")
            bulk["send_retry"] = 0
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": int(send[0]),
                    "y": int(send[1]),
                    "reason": (
                        f"Facebook Dating Send photo comment "
                        f"{done + 1}/{cap} — never Spotlight/Crush "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_send",
            )
        # The line is not in the box yet: focus it first (tree-verified),
        # then paste it in one commit — never chunked human-paced typing
        # on Discover. Bounded: after 2 failed types, stop honestly.
        if not box_focused and box_xy:
            tries = int(bulk.get("focus_tries") or 0) + 1
            bulk["focus_tries"] = tries
            st["bulk_message_new"] = bulk
            if tries > 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Facebook Dating comment box never took focus "
                            f"— stop, nothing sent ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "fb_dating_fc_focus_fail",
                )
            return _fp(
                {
                    "action": "tap",
                    "x": int(box_xy[0]),
                    "y": int(box_xy[1]),
                    "reason": (
                        f"Focus the photo comment box before typing ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_focus_box",
            )
        tries = int(bulk.get("type_tries") or 0)
        if tries >= 2:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Facebook Dating comment never landed in the box "
                        f"after 2 tries — stop, nothing sent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_type_fail",
            )
        bulk["type_tries"] = tries + 1
        bulk["typed"] = True
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "type",
                "text": text,
                "reason": (
                    f"Type photo comment '{text}' (paste, one commit) " f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "clear": True,
                "humanize": False,
            },
            "fb_dating_fc_type",
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

    # Profile or card: tap the photo, never the heart, never No Thanks
    # (No Thanks is only used to skip someone already messaged).
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

    # r51 (11:17, task_18cd1e4745926294): Dating home was on screen after
    # the tab tap — header, "Dating settings", "Liked you · Friendship ·
    # Matches" chips — but the compact tree had no profile photo / Like /
    # No Thanks yet (empty ScrollView). Wait briefly for the card (verified
    # 23 Nov: Ellie, 21 under those chips), then tap the card photo area.
    # Never tap the non-clickable "Dating" header at (529,133).
    if _dating_home(ui_tree) and not _has_like_pass(ui_tree):
        waited = int(bulk.get("awaiting_card") or 0)
        if waited < 2:
            bulk["awaiting_card"] = waited + 1
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "wait",
                    "seconds": 1.0,
                    "delay_s": 1.0,
                    "reason": (
                        f"Dating home — waiting for a card to appear "
                        f"({waited + 1}/2) ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "fb_dating_fc_wait_card",
            )
        bulk["awaiting_card"] = 0
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": CARD_PHOTO_XY[0],
                "y": CARD_PHOTO_XY[1],
                "reason": (
                    f"Tap Facebook Dating card photo to open profile " f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "fb_dating_fc_tap_card",
        )

    if (
        _has_like_pass(ui_tree)
        or "dating" in _blob(ui_tree)
        or "liked you" in _blob(ui_tree)
    ):
        return _fp(
            {
                "action": "tap",
                "x": CARD_PHOTO_XY[0],
                "y": CARD_PHOTO_XY[1],
                "reason": (
                    f"Tap Facebook Dating card photo to open profile " f"({planner})"
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
                f"Tap Facebook Dating photo for first-contact comment " f"({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "fb_dating_fc_tap_photo_fallback",
    )
