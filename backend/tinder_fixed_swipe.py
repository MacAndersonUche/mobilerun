"""r49 (CA-24): Tinder fixed auto-swipe — free right-swipe likes, popups
closed, matches answered with a bank line, no LLM, never paid.

Mac (24 Nov 10:50): "add one for Tinder as well" (same as Hily: close
notifications / popups, message a match, carry on).

Instruction: ``fixed tinder swipe N``.

Counting (Mac: "it still counted it as a tap even though it wasn't"):
a swipe counts only when the screen before AND after it is the Tinder card
deck. Anything else after the swipe (match, popup, notification, other app)
drops it (``unverified``) — the popup is handled and the next card is
swiped again. When a card name is readable, an unchanged name after the
swipe means the swipe did not land — not counted, swiped again (3× → stop).

GUESSES — there is NO real Tinder screen dump from Mac's phone yet (and the
18 Nov open attempts said "Could not open app: Tinder"):
  * deck markers: content-desc / text exactly "Like" + "Nope", or ids with
    "gamepad" / "recs" / "card_stack";
  * card name: a "Name, 24" / "Name 24" text or an id containing "name";
  * match screen: "It's a Match!" + the "Say something nice" box and Send;
  * out of likes: "out of likes"; deck empty: "no one new" / "run out of
    potential matches";
  * popup close labels (Not now / Maybe later / No thanks / Close / X).
The like itself is the verified S21+ mid-height right-swipe (Bumble r34),
never a button, so it cannot hit Super Like / Boost / Rewind.
Never: Super Like, Boost, Gold, Platinum, Plus, Rewind, Allow, Buy.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    from dm_heuristics import _fp, _parse_compact_nodes
    from hily_interrupts import handle_interrupt, is_match_popup, safe_close
    from hily_fixed_first_contact import allowed_message as _bank_text
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import _fp, _parse_compact_nodes  # type: ignore
    from backend.hily_interrupts import (  # type: ignore
        handle_interrupt,
        is_match_popup,
        safe_close,
    )
    from backend.hily_fixed_first_contact import allowed_message as _bank_text  # type: ignore

PKG = "com.tinder"
PLANNER = "tinder_fixed"
LIKE_SWIPE = (200, 1200, 980, 1200, 300)  # verified S21+ right-swipe (r34)
MAX_RECOVER = 8
MAX_SAME_CARD = 3
DEFAULT_N = 5
_DECK_IDS = ("gamepad", "recs_card", "card_stack", "recs_view")
_NAME_RE = re.compile(r"^([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+)?),? (\d{2})$")
_OUT_OF_LIKES = ("out of likes", "you're out of likes", "you’re out of likes")
_DECK_EMPTY = (
    "no one new",
    "run out of potential matches",
    "there's no one new",
    "there’s no one new",
    "no more profiles",
)


def _label(n: Dict[str, Any]) -> str:
    return str(n.get("text") or n.get("label") or n.get("desc") or "").strip()


def _pkg(tree: str) -> str:
    m = re.search(r'packages="([^"]*)"', tree or "")
    return m.group(1) if m else ""


def tinder_on_deck(tree: str) -> bool:
    """Tinder card deck (GUESS markers — see module doc)."""
    if PKG not in _pkg(tree):
        return False
    labs = set()
    for n in _parse_compact_nodes(tree):
        labs.add(_label(n).lower())
        nid = str(n.get("id") or "").lower()
        if any(k in nid for k in _DECK_IDS):
            return True
    return "like" in labs and "nope" in labs


def _known_screen(tree: str) -> bool:
    """Deck / Tinder tab pages — not a popup (main planner handles them)."""
    return tinder_on_deck(tree)


def card_sig(tree: str) -> str:
    for n in _parse_compact_nodes(tree):
        lab = _label(n)
        if _NAME_RE.match(lab):
            return lab
    for n in _parse_compact_nodes(tree):
        nid = str(n.get("id") or "").lower()
        if nid.endswith("name") and _label(n):
            return _label(n)
    return ""


def _blob(tree: str) -> str:
    return " ".join(_label(n) for n in _parse_compact_nodes(tree)).lower()


def _act(kind: str, step: str, reason: str, **kw: Any) -> Dict[str, Any]:
    a = {
        "action": kind,
        "reason": f"{reason} ({PLANNER})",
        "planner": PLANNER,
        "llm_provider": None,
        "_no_llm_handoff": True,
    }
    a.update(kw)
    return _fp(a, step)


def parse_count(instruction: str) -> int:
    m = re.search(r"fixed tinder swipe (\d+)", (instruction or "").lower())
    return max(1, min(500, int(m.group(1)))) if m else DEFAULT_N


def _drop(tr: Dict[str, Any]) -> None:
    if tr.get("awaiting"):
        tr["awaiting"] = False
        tr["unverified"] = int(tr.get("unverified") or 0) + 1


def plan_tinder_fixed_swipe(
    instruction: str,
    ui_tree: str,
    history: Optional[List[Any]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    st = state if isinstance(state, dict) else {}
    tr = st.setdefault("tinder_run", {})
    n = parse_count(instruction)
    likes = int(tr.setdefault("likes", 0) or 0)
    text = _bank_text(message)
    pk = _pkg(ui_tree)

    def _done(why: str) -> Dict[str, Any]:
        extra = f", {tr['match_msgs']} match messages" if tr.get("match_msgs") else ""
        return _act(
            "done",
            "tinder_fixed_done",
            f"Tinder auto-swipe: {likes}/{n} likes{extra} — {why}",
        )

    if likes >= n:
        return _done("finished")
    if not (ui_tree or "").strip():
        return None
    if dry_run:
        if tinder_on_deck(ui_tree):
            return _act(
                "done",
                "tinder_fixed_dry",
                f"[DRY RUN] Tinder deck found — would right-swipe {n} — nothing done",
                dry_run_verified=True,
            )
    blob = _blob(ui_tree)
    if PKG in pk and any(p in blob for p in _OUT_OF_LIKES):
        _drop(tr)
        return _done("Tinder says out of likes (never buys)")
    if PKG in pk and any(p in blob for p in _DECK_EMPTY):
        return _done("no more profiles nearby")

    kw = dict(
        pkg=PKG,
        prefix="tinder",
        chrome=_known_screen,
        app="Tinder",
        thread_ids=("id/chat_input", "textMessageInput", "message_input"),
    )
    if not dry_run and (is_match_popup(ui_tree) or (tr.get("match") or {}).get("open")):
        ia = handle_interrupt(ui_tree, tr, text, PLANNER, **kw)
        if ia:
            _drop(tr)
            return ia

    if tinder_on_deck(ui_tree):
        tr["recover"] = 0
        tr.pop("match", None)
        sig = card_sig(ui_tree)
        if tr.get("awaiting"):
            tr["awaiting"] = False
            before = str(tr.get("sig") or "")
            if before and sig and before == sig:
                tr["same"] = int(tr.get("same") or 0) + 1
                tr["unverified"] = int(tr.get("unverified") or 0) + 1
                if tr["same"] >= MAX_SAME_CARD:
                    return _act(
                        "fail",
                        "tinder_fixed_stuck",
                        f"Tinder: card '{sig}' did not move after "
                        f"{MAX_SAME_CARD} swipes ({likes} likes)",
                    )
            else:
                tr["same"] = 0
                likes += 1
                tr["likes"] = likes
                if likes >= n:
                    return _done("finished")
        if dry_run:
            return None
        tr["awaiting"] = True
        tr["sig"] = sig
        x1, y1, x2, y2, ms = LIKE_SWIPE
        return _act(
            "swipe",
            "tinder_fixed_like_swipe",
            f"Tinder free like — right-swipe {likes + 1}/{n}",
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            duration_ms=ms,
            _free_like=True,
        )

    # Not the deck after a swipe → that swipe is not counted
    _drop(tr)
    if dry_run:
        c = safe_close(ui_tree)
        if PKG in pk and c:
            return _act(
                "tap",
                "tinder_fixed_dry_close",
                f"[DRY RUN] close popup '{c[2]}'",
                x=c[0],
                y=c[1],
            )
    else:
        ia = handle_interrupt(ui_tree, tr, text, PLANNER, **kw)
        if ia:
            if ia.get("fastpath_step") != "tinder_int_back":
                tr["interrupts"] = int(tr.get("interrupts") or 0) + 1
                if tr["interrupts"] <= 40:
                    return ia
            else:
                r = int(tr.get("recover") or 0) + 1
                tr["recover"] = r
                if r <= MAX_RECOVER:
                    return ia
                return _act(
                    "fail",
                    "tinder_fixed_lost",
                    f"Tinder: could not get back to the cards after {MAX_RECOVER} "
                    f"tries ({likes} likes)",
                )
    if PKG not in pk:
        r = int(tr.get("recover") or 0) + 1
        tr["recover"] = r
        if r > MAX_RECOVER:
            return _act(
                "fail",
                "tinder_fixed_lost",
                f"Tinder: could not open the cards ({likes} likes)",
            )
        return _act(
            "open_app", "tinder_fixed_open", "Open Tinder", app="Tinder", package=PKG
        )
    r = int(tr.get("recover") or 0) + 1
    tr["recover"] = r
    if r > MAX_RECOVER:
        return _act(
            "fail",
            "tinder_fixed_lost",
            f"Tinder: could not get back to the cards after {MAX_RECOVER} tries "
            f"({likes} likes)",
        )
    return _act(
        "press_button",
        "tinder_fixed_back",
        "Back toward the Tinder cards",
        button="back",
    )
