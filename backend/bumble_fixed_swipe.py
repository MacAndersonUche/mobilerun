"""Fixed-spot like-swipe for Bumble and Badoo — no per-card LLM or vision.

Verified S21+ mid-height right-swipe, scaled to screen size
(1080x2400: 200,1200 -> 980,1200 @300ms). Paid-text guard before each
swipe; if the dump fails, just swipe. Badoo: like via the Encounters
heart button when the tree has it (swipe is the fallback); match sheets
dismiss with "Maybe later" when present, else Back — never "See my
matches".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        badoo_on_encounters,
        bumble_dismiss_popup,
        bumble_on_photo_browser,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        badoo_on_encounters,
        bumble_dismiss_popup,
        bumble_on_photo_browser,
    )


REF_W = 1080
REF_H = 2400
# Verified S21+ mid-height right-swipe (r34): input swipe 200 1200 980 1200 300
LIKE_SWIPE_REF = (200, 1200, 980, 1200, 300)

# Task word list, but "Get" / "Super" / "Buy" only as CTAs — not bio verbs.
# The deck's SuperSwipe *badge* is always on a People card; ignore that node
# (never tap it). Abort only on Send SuperSwipe / upsell sheets.
_BADGE_ID_RE = re.compile(
    r"badgesuperswipe|badge_superswipe|profile_details_badgesuper",
    re.I,
)
_PAID_PHRASES = (
    "superswipe",
    "super swipe",
    "superswibe",
    "superlike",
    "super like",
    "send superswipe",
    "bumble premium",
    "spotlight",
    "upgrade",
    "subscribe",
    "boost",
    "premium",
    "badoo premium",
    "buy credits",
    # Video (24 Nov 2026): the "Second time's a charm" compliment picker
    # is a paid flow — catch it here so the planner never swipes on it.
    # Picker-only wording; it never appears in a profile bio.
    "second time's a charm",
    "compliments left",
)
_MATCH_PHRASES = (
    "it's a match",
    "its a match",
    "you're a match",
    "you are a match",
    "you matched",
    "is also into you",
    "also liked you",
)
_GET_CTA_RE = re.compile(
    r"\bget(?:\s+now|\s+it|\s+boost|\s+premium|\s+superswipe|"
    r"\s+super\s*swipe|\s+spotlight|\s+bumble|\s+unlimited|"
    r"\s+more(?:\s+likes)?|\s+started)\b",
    re.I,
)
_BUY_CTA_RE = re.compile(
    r"\bbuy(?:\s+now|\s+premium|\s+boost|\s+spotlight|"
    r"\s+super(?:\s*swipe)?|\s+it|\s+bumble)\b",
    re.I,
)
_WORD_RE = {
    "boost": re.compile(r"\bboosts?\b", re.I),
    "premium": re.compile(r"\bpremium\b", re.I),
    "spotlight": re.compile(r"\bspotlight\b", re.I),
    "upgrade": re.compile(r"\bupgrades?\b", re.I),
    "subscribe": re.compile(r"\bsubscribe(?:d|r|s)?\b", re.I),
}
_HARMLESS_POPUP_RE = re.compile(
    r"^(allow|while using the app|only this time|ok|okay|got it|close|"
    r"don'?t allow|not now|later|no thanks)$",
    re.I,
)
_HARMLESS_TITLE_RE = re.compile(
    r"permission|to send you notifications|access (this )?device|" r"enjoying bumble",
    re.I,
)
_BOTTOM_TABS = ("profile", "discover", "people", "liked you", "chats")
_DECK_TABS = ("people", "discover")


def _tab_name(lab: str) -> Optional[str]:
    lab = (lab or "").strip().lower()
    if lab in _BOTTOM_TABS:
        return lab
    # Compact trees sometimes join text+desc: "People People".
    for name in _BOTTOM_TABS:
        if lab == f"{name} {name}":
            return name
        if lab.startswith(name + " ") or lab.endswith(" " + name):
            # don't map "Liked You promo" from mid-screen copy
            if lab in (f"{name} {name}", name):
                return name
    return None


def fixed_swipe_enabled(
    instruction: str = "",
    state: Optional[Dict[str, Any]] = None,
    app: str = "bumble",
) -> bool:
    """True when the planner should use coordinate swipe (no LLM)."""
    inst = (instruction or "").lower()
    if "fixed" in inst:
        return True
    st = state if isinstance(state, dict) else {}
    if str(st.get("swipe_mode") or "").lower() == "fixed":
        return True
    bulk = st.get("bulk_swipe") if isinstance(st.get("bulk_swipe"), dict) else {}
    if str(bulk.get("mode") or "").lower() == "fixed":
        return True
    app = (app or "bumble").lower()
    return bool(DM_APP_PROFILES.get(app, {}).get("fixed_swipe"))


def bumble_fixed_swipe_enabled(
    instruction: str = "",
    state: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when the Bumble planner should use coordinate swipe (no LLM)."""
    return fixed_swipe_enabled(instruction, state, app="bumble")


def dump_failed(tree: str) -> bool:
    """True when there is no usable UI dump — skip the paid check and swipe."""
    if not (tree or "").strip():
        return True
    low = tree.lower()
    if "could not get idle" in low and "<n" not in low and "<node" not in low:
        return True
    try:
        return len(_visible_nodes(tree)) == 0
    except Exception:
        return True


def badoo_matches_sheet(tree: str) -> bool:
    """True on Badoo's 'You have N new matches' sheet.

    Dismiss with a safe label ("Maybe later" / "Not now" / "Close") when
    one is in the tree, else Back — never "See my matches". The video
    (24 Nov 2026) shows the sheet with only "See my matches", so Back is
    the common path; tap-outside is not used (the exposed area is the
    live deck card underneath).
    """
    blob = visible_ui_text(tree).lower()
    if "see my matches" in blob:
        return True
    if "new matches" in blob and (
        "maybe later" in blob or "you have" in blob or "liked you back" in blob
    ):
        return True
    return False


def _badoo_matches_dismiss(tree: str) -> Optional[Tuple[int, int, str]]:
    """A safe dismiss label on the matches sheet, else None."""
    for label in ("Maybe later", "Not now", "Close"):
        for n in _parse_compact_nodes(tree):
            if str(n.get("label") or n.get("text") or "").strip() == label:
                if n.get("x") is not None:
                    return (int(n["x"]), int(n["y"]), label)
    return None


def _badoo_like_center(tree: str) -> Optional[Tuple[int, int]]:
    """The heart Like button on the Badoo Encounters deck, else None.

    Video (24 Nov 2026): heart = like, X = pass, chat bubble = message.
    VoteYes id first; exact "Like" label as fallback. Never the Crush
    (super-like) button — different id, never matched here.
    """
    for n in _parse_compact_nodes(tree):
        if "buttonvoteyes" in str(n.get("id") or "").lower().replace("_", ""):
            if n.get("x") is not None:
                return (int(n["x"]), int(n["y"]))
    for n in _parse_compact_nodes(tree):
        if str(n.get("desc") or n.get("label") or "").strip().lower() == "like":
            if n.get("x") is not None:
                return (int(n["x"]), int(n["y"]))
    return None


def _visible_nodes(tree: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in _parse_compact_nodes(tree or ""):
        if n.get("visible") is False or n.get("off_screen"):
            continue
        out.append(n)
    return out


def visible_ui_text(tree: str) -> str:
    """Space-joined visible labels/text for the cheap guard."""
    parts: List[str] = []
    for n in _visible_nodes(tree):
        lab = (n.get("label") or "").strip()
        if lab:
            parts.append(lab)
    return " ".join(parts)


def bumble_fixed_guard(tree: str) -> Optional[str]:
    """Return an abort reason if paid / match wording is visible, else None.

    'Get', 'Buy', and 'Super' only match CTAs / exact button labels so a bio
    like \"Let's get together\" or \"I'm super outgoing\" is not a stop.
    """
    nodes = _visible_nodes(tree)
    labels = []
    for n in nodes:
        nid = str(n.get("id") or "").lower().replace("_", "")
        if "badgesuperswipe" in nid or "profiledetailsbadgesuper" in nid:
            continue
        lab = (n.get("label") or "").strip()
        if lab:
            labels.append(lab)
    blob = " ".join(labels)
    low = blob.lower()

    for phrase in _MATCH_PHRASES:
        if phrase in low:
            return f"match screen ({phrase})"
    for phrase in _PAID_PHRASES:
        if phrase in low:
            return f"paid wording ({phrase})"

    for lab in labels:
        exact = lab.strip()
        if exact.lower() in ("get", "get now", "get it", "buy", "super"):
            return f"paid CTA ({exact})"

    if _GET_CTA_RE.search(blob):
        return "paid wording (Get CTA)"
    if _BUY_CTA_RE.search(blob):
        return "paid wording (Buy CTA)"

    # Already covered by _PAID_PHRASES, kept as whole-word belt-and-braces.
    for name, pat in _WORD_RE.items():
        if pat.search(blob):
            return f"paid wording ({name})"
    return None


def _selected_bottom_tab(tree: str) -> Optional[str]:
    """Return the selected bottom-nav tab name, if it can be read."""
    tabs: List[Tuple[str, Dict[str, Any]]] = []
    for n in _visible_nodes(tree):
        name = _tab_name(n.get("label") or "")
        if not name:
            continue
        y = int(n.get("y") or 0)
        y1 = n.get("y1")
        if y < 1800 and (y1 is None or int(y1) < 1800):
            continue
        tabs.append((name, n))
    if not tabs:
        return None
    # Selected tab is typically not clickable (the others are).
    non_click = [name for name, n in tabs if not n.get("clickable")]
    uniq = []
    for lab in non_click:
        if lab not in uniq:
            uniq.append(lab)
    if len(uniq) == 1:
        return uniq[0]
    if uniq and len(set(uniq)) == 1:
        return uniq[0]
    return None


def bumble_fixed_on_deck(tree: str) -> bool:
    """True on the People or Discover card deck, not chats/profile/paywall."""
    if not (tree or "").strip():
        return False
    if bumble_on_photo_browser(tree):
        return False
    if bumble_fixed_guard(tree):
        return False
    tab = _selected_bottom_tab(tree)
    if tab in ("chats", "liked you", "profile"):
        return False
    if tab in _DECK_TABS:
        return True
    # Selected tab unknown: a card container or Filters + People/Discover.
    if tab is None:
        ids = " ".join(str(n.get("id") or "") for n in _visible_nodes(tree)).lower()
        if "profile_root_container" in ids or "encountersgriditem_summary" in ids:
            return True
        blob = visible_ui_text(tree).lower()
        if "filters" in blob and ("people" in blob or "discover" in blob):
            if "connections start here" in blob or "older chats" in blob:
                return False
            return True
    return False


def screen_size_from_tree(
    tree: str,
    default: Tuple[int, int] = (REF_W, REF_H),
) -> Tuple[int, int]:
    """Best-effort display size from visible node bounds."""
    max_r = 0
    max_b = 0
    for n in _visible_nodes(tree):
        x2 = n.get("x2")
        y2 = n.get("y2")
        if x2 is not None:
            max_r = max(max_r, int(x2))
        if y2 is not None:
            max_b = max(max_b, int(y2))
    w = max_r if max_r >= 800 else default[0]
    h = max_b if max_b >= 1600 else default[1]
    # S21+ nav often ends at ~2274; keep the known 1080x2400 physical size.
    if 1000 <= w <= 1080 and 2100 <= h <= 2400:
        return (1080, 2400)
    return (w, h)


def scale_like_swipe(
    screen_w: int,
    screen_h: int,
    ref: Sequence[int] = LIKE_SWIPE_REF,
) -> Tuple[int, int, int, int, int]:
    """Scale the S21+ like-swipe recipe to the current screen size."""
    sw = int(screen_w or REF_W) or REF_W
    sh = int(screen_h or REF_H) or REF_H
    x1, y1, x2, y2, dur = (int(v) for v in ref[:5])
    return (
        int(round(x1 * sw / REF_W)),
        int(round(y1 * sh / REF_H)),
        int(round(x2 * sw / REF_W)),
        int(round(y2 * sh / REF_H)),
        int(dur),
    )


def _harmless_popup_action(tree: str, planner: str) -> Optional[Dict[str, Any]]:
    """Dismiss system / permission / 'Enjoying Bumble?' only — never paid CTAs."""
    if bumble_fixed_guard(tree):
        return None
    blob = visible_ui_text(tree)
    if _HARMLESS_TITLE_RE.search(blob) or "enjoying bumble" in blob.lower():
        if "enjoying bumble" in blob.lower():
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Dismiss harmless Bumble popup ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "_no_llm_handoff": True,
                },
                "bumble_fixed_popup",
            )
        for n in _visible_nodes(tree):
            lab = (n.get("label") or "").strip()
            if not lab or not n.get("clickable"):
                continue
            if _HARMLESS_POPUP_RE.match(lab):
                if bumble_fixed_guard(lab):
                    continue
                return _fp(
                    {
                        "action": "tap",
                        "x": int(n["x"]),
                        "y": int(n["y"]),
                        "reason": f"Dismiss harmless popup '{lab}' ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                        "label": lab,
                        "_no_llm_handoff": True,
                    },
                    "bumble_fixed_popup",
                )
    # Known non-paid dismiss from the existing map (Enjoying Bumble /
    # Interested / compliments upsell). Skip Interested? (preference, not
    # a system popup). Enjoying is Back; the compliments picker is Back
    # too — never tap a Compliment or the star.
    try:
        act = bumble_dismiss_popup(tree, planner=planner)
    except Exception:
        act = None
    if act and (
        "enjoying" in (act.get("reason") or "").lower()
        or "compliments upsell" in (act.get("reason") or "").lower()
    ):
        act["planner"] = planner
        act["_no_llm_handoff"] = True
        return act
    return None


MAX_RUN_SWIPES = 500
# Consecutive recovery steps allowed between two likes before stopping.
MAX_RECOVER_STEPS = 10
_DECK_TAB = {"bumble": ("people", "discover"), "badoo": ("encounters",)}
_DECK_TAB_ID = {"bumble": (), "badoo": ("nav_bar_button_encounters",)}
# S21+ fallback (1080x2400) when the tab node is not in the dump.
_DECK_TAB_XY = {"bumble": (540, 2197), "badoo": (324, 2200)}
_APP_PKG = {"bumble": "com.bumble.app", "badoo": "com.badoo.mobile"}
_LAUNCH = {
    "bumble": "com.bumble.app/.ui.launcher.BumbleLauncherActivity",
    "badoo": "com.badoo.mobile/.android.BadooActivity",
}
# Recovery ladder: index = recovery step (1-based, cycles).
_RECOVER_LADDER = (
    "tab",
    "scroll_top",
    "back",
    "tab",
    "relaunch",
    "back",
    "tab",
    "scroll_top",
    "relaunch",
    "back",
)


def tree_packages(tree: str) -> List[str]:
    m = re.search(r'packages="([^"]*)"', tree or "")
    if not m:
        return []
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def _deck_tab_xy(app: str, tree: str) -> Optional[Tuple[int, int]]:
    """Center of the People/Discover (Bumble) or Encounters (Badoo) tab."""
    want = _DECK_TAB.get(app, ())
    ids = _DECK_TAB_ID.get(app, ())
    best = None
    for n in _visible_nodes(tree):
        y = int(n.get("y") or 0)
        if y < 1800:
            continue
        nid = str(n.get("id") or "").lower()
        lab = (n.get("label") or "").strip().lower()
        name = _tab_name(lab) if app == "bumble" else None
        hit = (
            any(i in nid for i in ids)
            or lab in want
            or (name is not None and name in want)
            or any(lab == f"{w} {w}" for w in want)
        )
        if not hit:
            continue
        if bumble_fixed_guard(n.get("label") or ""):
            continue
        xy = (int(n["x"]), int(n["y"]))
        # Prefer People over Discover on Bumble
        if app == "bumble" and (lab.startswith("people")):
            return xy
        best = best or xy
    return best


def _bottom_nav_visible(tree: str) -> bool:
    # r45: Badoo's tabs carry ids even when their labels are not read
    if "nav_bar_button_" in (tree or ""):
        return True
    return (
        sum(
            1
            for n in _visible_nodes(tree)
            if int(n.get("y") or 0) >= 1800 and _tab_name(n.get("label") or "")
        )
        >= 3
    )


def _scroll_top_action(
    app: str, sw: int, sh: int, planner: str, dry_run: bool, reason: str
) -> Dict[str, Any]:
    """Drag down on the card = scroll an expanded profile back to its top."""
    x = int(round(540 * sw / REF_W))
    return _fp(
        {
            "action": "swipe",
            "x1": x,
            "y1": int(round(700 * sh / REF_H)),
            "x2": x,
            "y2": int(round(1900 * sh / REF_H)),
            "duration_ms": 350,
            "reason": f"{reason} ({planner})",
            "planner": planner,
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "_no_llm_handoff": True,
        },
        f"{app}_fixed_scroll_top",
    )


def _recover_action(
    app: str,
    tree: str,
    bulk: Dict[str, Any],
    planner: str,
    dry_run: bool,
) -> Dict[str, Any]:
    """One step back toward the swipe deck. Free taps only (tab / Back)."""
    label = "Bumble" if app == "bumble" else "Badoo"
    surface = "People/Discover deck" if app == "bumble" else "Encounters deck"
    n = int(bulk.get("_fixed_recover_n") or 0) + 1
    bulk["_fixed_recover_n"] = n
    # After recovery, scroll the card to the top again before the next like.
    bulk["_fixed_top_done"] = False
    if n > MAX_RECOVER_STEPS:
        return _fail(
            f"{label} fixed swipe: could not get back to the {surface} after "
            f"{MAX_RECOVER_STEPS} tries — stop, no tap ({planner})",
            planner,
            dry_run,
        )
    base = {
        "planner": planner,
        "llm_provider": None,
        "dry_run": bool(dry_run),
        "_no_llm_handoff": True,
    }
    sw, sh = screen_size_from_tree(tree)
    pkgs = tree_packages(tree)
    want_pkg = _APP_PKG.get(app, "")
    # App just launched but the dump is still the launcher / splash: wait.
    if pkgs and want_pkg and want_pkg not in pkgs:
        if n <= 2:
            return _fp(
                dict(
                    base,
                    action="wait",
                    seconds=2.0,
                    delay_s=2.0,
                    reason=(
                        f"{label} recover {n}: screen still shows "
                        f"{pkgs[0]} — wait for {label} ({planner})"
                    ),
                ),
                f"{app}_fixed_recover_wait",
            )
        step = "relaunch"
    elif app == "bumble" and bumble_on_photo_browser(tree):
        step = "back"
    else:
        step = _RECOVER_LADDER[(n - 1) % len(_RECOVER_LADDER)]
    # Never press Back on the app's top screen (bottom nav showing): Back
    # there closes the app (task_a9f0bd51c20dd507). Tab / scroll up instead.
    if (
        step == "back"
        and _bottom_nav_visible(tree)
        and not (app == "bumble" and bumble_on_photo_browser(tree))
    ):
        step = "tab" if n % 2 else "scroll_top"

    if step == "tab":
        xy = _deck_tab_xy(app, tree)
        if xy is None and _bottom_nav_visible(tree):
            fx, fy = _DECK_TAB_XY[app]
            xy = (int(round(fx * sw / REF_W)), int(round(fy * sh / REF_H)))
        if xy is not None:
            return _fp(
                dict(
                    base,
                    action="tap",
                    x=xy[0],
                    y=xy[1],
                    label=_DECK_TAB[app][0].title(),
                    reason=(
                        f"{label} recover {n}: not on {surface} — tap "
                        f"{_DECK_TAB[app][0].title()} tab ({planner})"
                    ),
                ),
                f"{app}_fixed_recover_tab",
            )
        step = "back"
    if step == "scroll_top":
        return _scroll_top_action(
            app,
            sw,
            sh,
            planner,
            dry_run,
            f"{label} recover {n}: not on {surface} — scroll profile back up",
        )
    if step == "relaunch":
        return _fp(
            dict(
                base,
                action="open_app",
                app=label,
                package=want_pkg,
                launch_activity=_LAUNCH[app],
                open_mode="launch_intent",
                reason=f"{label} recover {n}: relaunch {label} ({planner})",
            ),
            f"{app}_fixed_recover_open",
        )
    return _fp(
        dict(
            base,
            action="press_button",
            button="back",
            reason=f"{label} recover {n}: not on {surface} — Back ({planner})",
        ),
        f"{app}_fixed_recover_back",
    )


_DISMISS_LABELS = (
    "close",
    "not now",
    "no thanks",
    "no, thanks",
    "maybe later",
    "later",
    "skip",
    "dismiss",
    "cancel",
    "x",
    "×",
    # "Back" is a safe dismiss on a paid popup (same as pressing Back) —
    # the Bumble compliment picker has a Back node, no X.
    "back",
)


def _paid_popup_dismiss(tree: str) -> Optional[Tuple[int, int, str]]:
    """Free close control on a paid popup: (x, y, label) or None."""
    best = None
    for n in _visible_nodes(tree):
        lab = (n.get("label") or "").strip()
        low = lab.lower()
        nid = str(n.get("id") or "").lower()
        if low in _DISMISS_LABELS or nid.endswith(
            ("/close", "_close", "close_button", "closebutton")
        ):
            if bumble_fixed_guard(lab):
                continue
            if int(n.get("y") or 0) >= 2100:  # bottom nav, not a popup
                continue
            xy = (int(n.get("x") or 0), int(n.get("y") or 0), lab or "Close")
            if xy[0] <= 0 or xy[1] <= 0:
                continue
            best = best or xy
    return best


def _fail(reason: str, planner: str, dry_run: bool) -> Dict[str, Any]:
    return _fp(
        {
            "action": "fail",
            "reason": reason,
            "planner": planner,
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "dry_run_verified": False,
            "_no_llm_handoff": True,
        },
        "bumble_fixed_guard",
    )


def _done(
    reason: str,
    planner: str,
    dry_run: bool,
    *,
    verified: bool = False,
    coords: Optional[Tuple[int, int, int, int, int]] = None,
    done: int = 0,
) -> Dict[str, Any]:
    act: Dict[str, Any] = {
        "action": "done",
        "reason": reason,
        "planner": planner,
        "llm_provider": None,
        "dry_run": bool(dry_run),
        "dry_run_verified": bool(verified) if dry_run else False,
        "_no_llm_handoff": True,
        "likes_done": int(done),
    }
    if coords:
        act["like_swipe"] = {
            "x1": coords[0],
            "y1": coords[1],
            "x2": coords[2],
            "y2": coords[3],
            "duration_ms": coords[4],
        }
    return _fp(act, "bumble_fixed_done")


def badoo_fixed_on_deck(tree: str) -> bool:
    """True on the Badoo Encounters card deck."""
    if not (tree or "").strip():
        return False
    if badoo_matches_sheet(tree):
        return False
    if bumble_fixed_guard(tree):
        return False
    try:
        if badoo_on_encounters(tree, _log=False):
            return True
    except Exception:
        pass
    # r45: ignore the bottom tabs ("Encounters", "Likes") — they are on every
    # Badoo screen, so Chats / Liked you looked like the deck and the run
    # swiped in place instead of going back to Encounters.
    parts = []
    for n in _visible_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if "nav_bar_button" in nid or int(n.get("y") or 0) >= 2100:
            continue
        parts.append(" ".join([n.get("label") or "", nid]))
    blob = " ".join(parts).lower()
    if "encounters" in blob and (
        re.search(r"\blike\b", blob) or "voteyes" in blob or "send a crush" in blob
    ):
        return True
    return False


def plan_bumble_fixed_swipe(
    instruction: str,
    ui_tree: str,
    history: Optional[List[str]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
    dry_run: bool = False,
    planner: str = "bumble_fixed",
    live_test_max_n: int = 5,
) -> Optional[Dict[str, Any]]:
    """Plan one fixed-spot Bumble like, or abort. Never calls LLM/vision."""
    return plan_fixed_swipe(
        instruction,
        ui_tree,
        history,
        state=state,
        package=package,
        dry_run=dry_run,
        planner=planner,
        live_test_max_n=live_test_max_n,
        app="bumble",
    )


def plan_fixed_swipe(
    instruction: str,
    ui_tree: str,
    history: Optional[List[str]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
    dry_run: bool = False,
    planner: str = "bumble_fixed",
    live_test_max_n: int = 5,
    app: str = "bumble",
) -> Optional[Dict[str, Any]]:
    """Plan one mid-height right-swipe for Bumble or Badoo. No LLM/vision."""
    app = (app or "bumble").lower()
    label = "Bumble" if app == "bumble" else "Badoo"
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_swipe",
        {"done": 0, "target": 5, "last_name": None, "awaiting_verify": False},
    )
    bulk["mode"] = "fixed"
    st["swipe_mode"] = "fixed"
    st["bulk_swipe"] = bulk
    target = int(bulk.get("target") or 5)
    # r43: the per-run count is the target. Only a live_test job is capped
    # (live_test_max_n); real runs go up to MAX_RUN_SWIPES.
    if st.get("live_test"):
        cap = max(1, int(st.get("live_test_max_n") or live_test_max_n or 5))
    else:
        cap = MAX_RUN_SWIPES
    if not dry_run:
        target = max(1, min(target, cap))
        bulk["target"] = target
    done = int(bulk.get("done") or 0)
    hist = history or []
    hist_l = " | ".join(hist[-12:]).lower()
    failed_dump = dump_failed(ui_tree)

    # Count a completed swipe when the previous step was our like swipe
    # and we did not land on a paid/match screen. A failed dump still counts.
    if not dry_run and bulk.get("awaiting_verify") and "fixed like swipe" in hist_l:
        bulk["awaiting_verify"] = False
        hit = None if failed_dump else bumble_fixed_guard(ui_tree)
        if hit is None:
            done += 1
            bulk["done"] = done
        else:
            # Successful like may open a match — count it, then abort.
            if "match" in hit:
                done += 1
                bulk["done"] = done
            return _fail(
                f"{label} fixed swipe aborted after swipe: {hit} ({planner})",
                planner,
                dry_run,
            )
        if done >= target:
            return _done(
                f"{label} fixed swipe finished {done}/{target} likes ({planner})",
                planner,
                dry_run,
                done=done,
            )

    sw, sh = screen_size_from_tree(ui_tree)
    st_w = st.get("screen_w") or st.get("screen_width")
    st_h = st.get("screen_h") or st.get("screen_height")
    if st_w and st_h:
        sw, sh = int(st_w), int(st_h)
    if failed_dump and not (st_w and st_h):
        sw, sh = REF_W, REF_H
    coords = scale_like_swipe(sw, sh)
    coord_s = (
        f"{coords[0]},{coords[1]} -> {coords[2]},{coords[3]} "
        f"({coords[4]}ms) on {sw}x{sh}"
    )

    def _swipe_action(reason: str) -> Dict[str, Any]:
        bulk["awaiting_verify"] = True
        bulk["_fixed_recover_n"] = 0
        st["bulk_swipe"] = bulk
        return _fp(
            {
                "action": "swipe",
                "x1": coords[0],
                "y1": coords[1],
                "x2": coords[2],
                "y2": coords[3],
                "duration_ms": coords[4],
                "reason": reason,
                "planner": planner,
                "llm_provider": None,
                "_no_llm_handoff": True,
            },
            f"{app}_fixed_like_swipe",
        )

    # If the dump fails, skip the paid check and just swipe (live) / report (dry).
    if failed_dump:
        if dry_run:
            return _done(
                f"{label} fixed swipe dry check: dump failed, would swipe "
                f"{coord_s} — no swipe ({planner})",
                planner,
                dry_run,
                verified=True,
                coords=coords,
                done=0,
            )
        if done >= target:
            return _done(
                f"{label} fixed swipe finished {done}/{target} likes ({planner})",
                planner,
                dry_run,
                coords=coords,
                done=done,
            )
        return _swipe_action(
            f"{label} fixed like swipe {done + 1}/{target} {coord_s} "
            f"(dump failed, swipe anyway) ({planner})"
        )

    blocked = bumble_fixed_guard(ui_tree)
    if blocked and "match" not in blocked:
        # r45: a paid upsell popup (Buy Credits / Premium) with a free Close /
        # Not now is dismissed, not a dead end. Never taps the paid CTA.
        dismiss = _paid_popup_dismiss(ui_tree)
        n_dis = int(bulk.get("_paid_dismiss_n") or 0)
        if dismiss and n_dis < 3:
            bulk["_paid_dismiss_n"] = n_dis + 1
            bulk["_fixed_top_done"] = False
            st["bulk_swipe"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": dismiss[0],
                    "y": dismiss[1],
                    "label": dismiss[2],
                    "reason": (
                        f"{label} fixed swipe: close paid popup ({blocked}) "
                        f"with '{dismiss[2]}' — nothing bought ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                    "_no_llm_handoff": True,
                },
                f"{app}_fixed_close_paid_popup",
            )
    if blocked:
        return _fail(
            f"{label} fixed swipe aborted: {blocked} — no tap ({planner})",
            planner,
            dry_run,
        )

    if app == "badoo" and badoo_matches_sheet(ui_tree):
        dismiss = _badoo_matches_dismiss(ui_tree)
        if dismiss:
            return _fp(
                {
                    "action": "tap",
                    "x": dismiss[0],
                    "y": dismiss[1],
                    "reason": (
                        f"Badoo fixed swipe: dismiss matches sheet with "
                        f"'{dismiss[2]}' — never 'See my matches' ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                    "_no_llm_handoff": True,
                },
                "badoo_fixed_matches_dismiss",
            )
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Badoo fixed swipe: dismiss matches sheet with Back "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
                "_no_llm_handoff": True,
            },
            "badoo_fixed_matches_back",
        )

    popup = _harmless_popup_action(ui_tree, planner)
    if popup:
        return popup

    on_deck = (
        bumble_fixed_on_deck(ui_tree)
        if app == "bumble"
        else badoo_fixed_on_deck(ui_tree)
    )
    if not on_deck:
        # r43: recover to the deck (tab / scroll up / Back / relaunch) instead
        # of one Back then stop — never an LLM handoff, never a paid tap.
        return _recover_action(app, ui_tree, bulk, planner, dry_run)

    # r43: once per job (and after every recovery), scroll the card back to
    # the top so an expanded / scrolled-down profile cannot block the swipe.
    if not dry_run and not bulk.get("_fixed_top_done"):
        bulk["_fixed_top_done"] = True
        st["bulk_swipe"] = bulk
        return _scroll_top_action(
            app,
            sw,
            sh,
            planner,
            dry_run,
            f"{label} fixed swipe: scroll card back to top before likes",
        )

    if dry_run:
        return _done(
            f"{label} fixed swipe dry check: guard clear, like swipe {coord_s} "
            f"— no swipe ({planner})",
            planner,
            dry_run,
            verified=True,
            coords=coords,
            done=0,
        )

    if done >= target:
        return _done(
            f"{label} fixed swipe finished {done}/{target} likes ({planner})",
            planner,
            dry_run,
            coords=coords,
            done=done,
        )

    # Video (24 Nov 2026): Badoo's Encounters deck has a heart Like
    # button — tap it when the tree has it. The verified right-swipe stays
    # as the fallback when the tree has no heart. The reason keeps
    # "fixed like swipe" so the awaiting-verify counting keys on it
    # exactly like a swipe.
    if app == "badoo":
        heart = _badoo_like_center(ui_tree)
        if heart:
            bulk["awaiting_verify"] = True
            bulk["_fixed_recover_n"] = 0
            st["bulk_swipe"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": heart[0],
                    "y": heart[1],
                    "reason": (
                        f"{label} fixed like swipe {done + 1}/{target} — "
                        f"heart button {heart[0]},{heart[1]} ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "_no_llm_handoff": True,
                },
                f"{app}_fixed_like_swipe",
            )

    return _swipe_action(
        f"{label} fixed like swipe {done + 1}/{target} {coord_s} ({planner})"
    )
