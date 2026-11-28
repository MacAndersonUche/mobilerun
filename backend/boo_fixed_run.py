"""r50: Boo fixed auto-like / auto-message runner (FLAG_SECURE, no screenshots).

Mac (28 Nov 2026): Boo blocks screen capture (FLAG_SECURE), so screenshots and
screen recordings come out black. The runner relies on the accessibility tree
where available, and falls back to fixed relative touch points expressed as
fractions of screen size (derived from Mac's portrait SM-G996B screenshot).

Discovery screen: profile card (name, location, chips) with bottom action row
just above the nav bar (~85% screen height):
  - Rocket (boost, PAID, never tap) ~10% width
  - Red X (pass) ~25% width
  - Pink heart (super like, may be PAID) ~43% width
  - BIG blue/teal heart (LIKE, use this) ~61% width
  - Blue paper-plane arrow (MESSAGE) ~78% width

Bottom nav (~95% height): Match, Spotlight, Universes, Messages.

Behaviour:
  - Message + likes: send up to `messages` (default 5) direct messages to NEW
    people via the arrow, typing an opener-library line (time-of-day aware,
    same picker as other apps), then do `max(0, max_likes - messages)` likes
    with the big blue heart. Same semantics as Hily PR #106.
  - Message only: messages only.
  - Likes only: big blue heart only.
  - Never tap anything paid: rocket, lightning, pink heart if it's a super like,
    coins/premium/paywall screens. If the message arrow hits a paywall (free
    messages used up), dismiss and stop messaging, then continue with likes.
  - Handle harmless popups.
  - Message text only from opener library (MESSAGE_BANK fallback).
  - No dashes in UI text.

Instruction: ``fixed boo <mode> messages <M> likes <L>``
  mode likes          — free like taps only (L likes)
  mode message_likes  — up to M bank-text messages to NEW matches from the
                        chats list, then L likes
  mode message        — messages only (never offered, reserved)

Rules: no LLM, never paid, bank text only, never double-message. A like counts
only when the deck shows before AND after the tap (and when a card name is
readable, the name changed). Popups / matches go through hily_interrupts
handle_interrupt; paid popups are closed earlier by paid_popup (cloud_agent).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import _fp, _parse_compact_nodes
    from hily_fixed_first_contact import allowed_message as _bank_text
    from hily_interrupts import handle_interrupt, is_match_popup
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import _fp, _parse_compact_nodes  # type: ignore
    from backend.hily_fixed_first_contact import allowed_message as _bank_text  # type: ignore
    from backend.hily_interrupts import handle_interrupt, is_match_popup  # type: ignore

PLANNER = "boo_fixed_run"
PKG = "enterprises.dating.boo"
NAME = "Boo"
MAX_RECOVER = 8
MAX_SAME_CARD = 3
MESSAGE_CAP = 5
BANK = ("hey how are you", "hi miss", "hello miss", "good morning")

# Fractional coordinates (screen width/height fractions) for Boo's discovery screen.
# Derived from Mac's portrait SM-G996B screenshot (~1080x2400).
# Action row sits at ~85% screen height; buttons spread horizontally:
#   Rocket (paid, never)    x=0.10
#   Red X (pass)            x=0.25
#   Pink heart (super like) x=0.43
#   BIG teal heart (LIKE)   x=0.61  <-- USE THIS
#   Paper-plane (MESSAGE)   x=0.78
# Bottom nav at ~95% height: Match, Spotlight, Universes, Messages
BOO_COORDS = {
    "action_row_y": 0.85,  # Action row vertical position
    "nav_y": 0.95,         # Bottom nav vertical position
    "like_x": 0.61,        # Big teal heart horizontal position
    "message_x": 0.78,     # Paper-plane arrow horizontal position
    "messages_tab_x": 0.95, # Messages tab (rightmost in nav)
}

# Paid controls to never tap
_BAD_LIKE = re.compile(
    r"super|boost|rewind|crush|gold|premium|rocket|spotlight|rose|vip|coin|credit",
    re.I,
)
_LIKE_LAB = re.compile(r"^(?:like|heart|♥|❤|❤️)$", re.I)
_NAME_RE = re.compile(r"^([A-Z][\w''\-]+(?: [A-Z][\w''\-]+)?),?\s*(\d{2})$")
_CHATS_LAB = ("messages", "matches", "chats", "inbox", "chat")
_NEW_TILE = (
    "new match",
    "start chat",
    "say hi",
    "no messages yet",
    "matched",
    "start a conversation",
)
_DECK_EMPTY = (
    "no one new",
    "no more profiles",
    "out of profiles",
    "come back later",
    "you've seen everyone",
    "no more people",
    "out of likes",
    "0 left",
)


def _label(n: Dict[str, Any]) -> str:
    return str(n.get("text") or n.get("label") or n.get("desc") or "").strip()


def _pkg(tree: str) -> str:
    m = re.search(r'packages="([^"]*)"', tree or "")
    return m.group(1) if m else ""


def _blob(tree: str) -> str:
    return " ".join(_label(n) for n in _parse_compact_nodes(tree)).lower()


def screen_size_from_tree(tree: str, default: Tuple[int, int] = (1080, 2400)) -> Tuple[int, int]:
    """Best-effort display size from visible node bounds."""
    max_r = 0
    max_b = 0
    for n in _parse_compact_nodes(tree):
        x2 = n.get("x2")
        y2 = n.get("y2")
        if x2 is not None:
            max_r = max(max_r, int(x2))
        if y2 is not None:
            max_b = max(max_b, int(y2))
    w = max_r if max_r >= 800 else default[0]
    h = max_b if max_b >= 1600 else default[1]
    if 1000 <= w <= 1080 and 2100 <= h <= 2400:
        return (1080, 2400)
    return (w, h)


def scale_coords(screen_w: int, screen_h: int, x_frac: float, y_frac: float) -> Tuple[int, int]:
    """Convert fractional coordinates to absolute screen pixels."""
    return (int(round(x_frac * screen_w)), int(round(y_frac * screen_h)))


def boo_like_button(tree: str, sw: int, sh: int) -> Optional[Tuple[int, int]]:
    """Free like control: clickable Like/Heart from tree, never paid ones, else fractional xy."""
    for n in _parse_compact_nodes(tree):
        if n.get("x") is None or n.get("editable"):
            continue
        lab = _label(n)
        nid = str(n.get("id") or "").lower().rsplit("/", 1)[-1]
        if _BAD_LIKE.search(lab) or _BAD_LIKE.search(nid):
            continue
        if _LIKE_LAB.match(lab) or (
            nid
            and re.search(r"(?:^|_)(?:like|heart)(?:_|button|$)", nid)
            and n.get("clickable")
        ):
            return (int(n["x"]), int(n["y"]))
    return scale_coords(sw, sh, BOO_COORDS["like_x"], BOO_COORDS["action_row_y"])


def boo_message_button(tree: str, sw: int, sh: int) -> Optional[Tuple[int, int]]:
    """Message arrow from tree (send/message/arrow/plane), else fractional xy."""
    for n in _parse_compact_nodes(tree):
        if n.get("x") is None or n.get("editable"):
            continue
        lab = _label(n).lower()
        nid = str(n.get("id") or "").lower().rsplit("/", 1)[-1]
        if any(w in lab for w in ("send", "message", "arrow", "plane")) or (
            nid and re.search(r"(?:send|message|arrow|plane)", nid)
        ):
            y = int(n.get("y") or 0)
            if y > sh * 0.7:
                return (int(n["x"]), y)
    return scale_coords(sw, sh, BOO_COORDS["message_x"], BOO_COORDS["action_row_y"])


def boo_card_sig(tree: str) -> str:
    """Unique card signature: name from "Name, 24" pattern."""
    for n in _parse_compact_nodes(tree):
        if _NAME_RE.match(_label(n)):
            return _label(n)
    return ""


def boo_on_deck(tree: str) -> bool:
    """Boo discovery screen: package match + (like button readable OR profile card pattern)."""
    if PKG not in _pkg(tree):
        return False
    nodes = _parse_compact_nodes(tree)
    has_like = any(
        _LIKE_LAB.match(_label(n)) or "like" in str(n.get("id") or "").lower()
        for n in nodes
        if n.get("clickable") and not n.get("editable")
    )
    has_card = any(_NAME_RE.match(_label(n)) for n in nodes)
    no_composer = not any(n.get("editable") for n in nodes)
    return (has_like or has_card) and no_composer


def boo_on_chats(tree: str) -> bool:
    """Boo messages/chats list: header + new-match tile patterns."""
    nodes = _parse_compact_nodes(tree)
    head = any(
        _label(n).lower() in _CHATS_LAB and int(n.get("y") or 9999) < 400 for n in nodes
    )
    tile = any(any(w in _label(n).lower() for w in _NEW_TILE) for n in nodes)
    return head or (tile and not any(n.get("editable") for n in nodes))


def boo_new_tile(tree: str, done: List[str]) -> Optional[Tuple[int, int, str]]:
    """First unseen new-match tile (x, y, name)."""
    for n in _parse_compact_nodes(tree):
        lab = _label(n)
        low = lab.lower()
        if (
            n.get("x") is None
            or "daily pick" in low
            or low.startswith(("say '", 'say "'))
        ):
            continue
        if not any(w in low for w in _NEW_TILE):
            continue
        name = lab.split(",")[0].strip() or lab
        if name in done:
            continue
        return (int(n["x"]), int(n["y"]), name)
    return None


def parse(instruction: str) -> Tuple[str, int, int]:
    """-> (mode, messages, max_likes); mode in (likes, message_likes, message)."""
    m = re.search(
        r"fixed boo (\w+)(?: messages (\d+))?(?: likes (\d+))?",
        (instruction or "").lower(),
    )
    if not m:
        return "", 0, 0
    mode = m.group(1)
    if mode not in ("likes", "message_likes", "message"):
        return "", 0, 0
    msgs = min(MESSAGE_CAP, int(m.group(2) or 0))
    likes = min(500, int(m.group(3) or 0))
    return mode, msgs, likes


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


def _drop(fr: Dict[str, Any]) -> None:
    """Drop an unverified like (not counted)."""
    if fr.get("awaiting"):
        fr["awaiting"] = False
        fr["unverified"] = int(fr.get("unverified") or 0) + 1


def plan_boo_fixed_run(
    instruction: str,
    ui_tree: str,
    history: Optional[List[Any]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    mode, msgs, max_likes = parse(instruction)
    if not mode:
        return None
    st = state if isinstance(state, dict) else {}
    fr = st.setdefault("boo_run", {})
    fr.setdefault("likes", 0)
    phase = fr.setdefault(
        "phase", "message" if mode in ("message", "message_likes") and msgs else "likes"
    )
    likes = int(fr["likes"])
    text = _bank_text(message)
    pk = _pkg(ui_tree)
    sw, sh = screen_size_from_tree(ui_tree)
    kw = dict(
        pkg=PKG,
        prefix=f"boo_fixed",
        chrome=lambda t: boo_on_deck(t) or boo_on_chats(t),
        app=NAME,
        thread_ids=('e="1"',),
    )

    def sent() -> int:
        return int(fr.get("match_msgs") or 0)

    def done(why: str) -> Dict[str, Any]:
        parts = [f"{NAME} {mode}: {likes}/{max_likes} likes"] if max_likes else [f"{NAME} {mode}"]
        if msgs:
            parts.append(f"sent {int(fr.get('msg_sent', sent()))}/{msgs}")
        extra = sent() - int(fr.get("msg_sent", sent()) if msgs else 0)
        if extra > 0:
            parts.append(f"{extra} match messages")
        return _act("done", "boo_done", ", ".join(parts) + f" — {why}")

    if not (ui_tree or "").strip():
        return None
    if dry_run:
        if boo_on_deck(ui_tree) or boo_on_chats(ui_tree):
            return _act(
                "done",
                "boo_dry",
                f"[DRY RUN] {NAME} screen found — would {mode} "
                f"(messages {msgs}, likes {max_likes}) — nothing tapped",
                dry_run_verified=True,
            )

    # Message phase (new matches only)
    if phase == "message":
        m = fr.get("match") or {}
        if sent() >= msgs and not m.get("open"):
            fr["msg_sent"] = sent()
            fr["phase"] = phase = "likes"
        elif m.get("open") or (is_match_popup(ui_tree) and not boo_on_chats(ui_tree)):
            if not dry_run:
                if (
                    m.get("open")
                    and not m.get("typed")
                    and not m.get("awaiting")
                    and any(
                        _label(n).lower() in BANK
                        for n in _parse_compact_nodes(ui_tree)
                        if not n.get("editable")
                    )
                ):
                    fr.pop("match", None)
                    return _act(
                        "press_button",
                        "boo_already_messaged",
                        f"{NAME}: this chat already has a message — Back, no double message",
                        button="back",
                    )
                ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
                if ia:
                    return ia
                fr.pop("match", None)
        if phase == "message":
            if boo_on_chats(ui_tree):
                fr["recover"] = 0
                t = boo_new_tile(ui_tree, fr.setdefault("done_names", []))
                if t and not dry_run:
                    fr["done_names"].append(t[2])
                    fr["match"] = {"open": True}
                    return _act(
                        "tap",
                        "boo_open_match",
                        f"{NAME}: open new match '{t[2]}' ({sent() + 1}/{msgs})",
                        x=t[0],
                        y=t[1],
                    )
                fr["msg_sent"] = sent()
                fr["msg_end"] = "no more new matches"
                fr["phase"] = phase = "likes"
            elif PKG in pk:
                msgs_xy = scale_coords(sw, sh, BOO_COORDS["messages_tab_x"], BOO_COORDS["nav_y"])
                n_try = int(fr.get("chat_tries") or 0) + 1
                fr["chat_tries"] = n_try
                if n_try <= 3:
                    return _act(
                        "tap",
                        "boo_messages_tab",
                        f"{NAME}: open Messages tab",
                        x=msgs_xy[0],
                        y=msgs_xy[1],
                    )
                if n_try <= 5:
                    ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
                    if ia:
                        return ia
                    return _act(
                        "press_button",
                        "boo_back_messages",
                        f"{NAME}: Back toward Messages",
                        button="back",
                    )
                fr["msg_sent"] = sent()
                fr["msg_end"] = "Messages not found"
                fr["phase"] = phase = "likes"
            else:
                r = int(fr.get("recover") or 0) + 1
                fr["recover"] = r
                if r > MAX_RECOVER:
                    return _act("fail", "boo_lost", f"Could not open {NAME}")
                return _act("open_app", "boo_open", f"Open {NAME}", app=NAME, package=PKG)
        if phase == "likes" and not max_likes:
            return done(fr.get("msg_end") or "finished")
        if phase == "likes":
            fr["recover"] = 0

    # Likes phase
    if likes >= max_likes:
        return done("finished")
    blob = _blob(ui_tree)
    if (
        PKG in pk
        and any(p in blob for p in _DECK_EMPTY)
        and not boo_on_deck(ui_tree)
    ):
        _drop(fr)
        return done("no more profiles / likes for today")
    if not dry_run and (
        (is_match_popup(ui_tree) and not boo_on_chats(ui_tree))
        or (fr.get("match") or {}).get("open")
    ):
        ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
        if ia:
            _drop(fr)
            return ia
    if boo_on_deck(ui_tree):
        fr["recover"] = 0
        fr.pop("match", None)
        sig = boo_card_sig(ui_tree)
        if fr.get("awaiting"):
            fr["awaiting"] = False
            before = str(fr.get("sig") or "")
            if before and sig and before == sig:
                fr["same"] = int(fr.get("same") or 0) + 1
                fr["unverified"] = int(fr.get("unverified") or 0) + 1
                if fr["same"] >= MAX_SAME_CARD:
                    return _act(
                        "fail",
                        "boo_stuck",
                        f"{NAME}: card did not change after {MAX_SAME_CARD} taps ({likes} likes)",
                    )
            else:
                fr["same"] = 0
                likes += 1
                fr["likes"] = likes
                if likes >= max_likes:
                    return done("finished")
        if dry_run:
            return None
        xy = boo_like_button(ui_tree, sw, sh)
        if xy:
            fr["awaiting"] = True
            fr["sig"] = sig
            return _act(
                "tap",
                "boo_like_swipe",
                f"{NAME} free like {likes + 1}/{max_likes}",
                x=xy[0],
                y=xy[1],
                _free_like=True,
            )

    _drop(fr)
    if dry_run:
        return None
    ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
    if ia:
        if not str(ia.get("fastpath_step") or "").endswith("_int_back"):
            fr["interrupts"] = int(fr.get("interrupts") or 0) + 1
            if fr["interrupts"] <= 40:
                return ia
    r = int(fr.get("recover") or 0) + 1
    fr["recover"] = r
    if r > MAX_RECOVER:
        return _act(
            "fail",
            "boo_lost",
            f"{NAME}: could not get back to the cards after {MAX_RECOVER} tries ({likes} likes)",
        )
    if PKG not in pk:
        return _act("open_app", "boo_open", f"Open {NAME}", app=NAME, package=PKG)
    return _act("press_button", "boo_back", f"{NAME}: Back toward the cards", button="back")
