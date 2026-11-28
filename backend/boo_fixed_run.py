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
  - Message + likes: from the discovery deck, tap the paper-plane arrow to
    send up to `messages` (default 5) direct messages to NEW people (Boo gives
    ~5 free direct messages like Hily message-before-match), typing an
    opener-library line (time-of-day aware), then send and return to deck.
    After messages, do `max(0, max_likes - messages)` likes with the big blue
    heart. Same semantics as Hily PR #106.
  - Message only: paper-plane messages only from deck.
  - Likes only: big blue heart only.
  - Never tap anything paid: rocket, lightning, pink heart if it's a super like,
    coins/premium/paywall screens. If the message arrow hits a paywall (free
    messages used up), dismiss and stop messaging, then continue with likes.
  - Handle harmless popups.
  - Message text only from opener library (MESSAGE_BANK fallback).
  - No dashes in UI text.

Instruction: ``fixed boo <mode> messages <M> likes <L>``
  mode likes          — free like taps only (L likes)
  mode message_likes  — up to M direct messages from deck via paper-plane
                        arrow, then L likes
  mode message        — messages only (never offered, reserved)

Rules: no LLM, never paid, bank text only. Each message is a direct message
from the discovery card (not via Messages tab). A like counts only when the
deck shows before AND after the tap (and when a card name is readable, the
name changed). Popups / matches go through hily_interrupts handle_interrupt;
paid popups are closed earlier by paid_popup (cloud_agent).
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
    "nav_y": 0.95,  # Bottom nav vertical position
    "like_x": 0.61,  # Big teal heart horizontal position
    "message_x": 0.78,  # Paper-plane arrow horizontal position (direct message from card)
}

# Paid controls to never tap
_BAD_LIKE = re.compile(
    r"super|boost|rewind|crush|gold|premium|rocket|spotlight|rose|vip|coin|credit",
    re.I,
)
_LIKE_LAB = re.compile(r"^(?:like|heart|♥|❤|❤️)$", re.I)
_NAME_RE = re.compile(r"^([A-Z][\w''\-]+(?: [A-Z][\w''\-]+)?),?\s*(\d{2})$")
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


def screen_size_from_tree(
    tree: str, default: Tuple[int, int] = (1080, 2400)
) -> Tuple[int, int]:
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


def scale_coords(
    screen_w: int, screen_h: int, x_frac: float, y_frac: float
) -> Tuple[int, int]:
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


_DM_LAB = re.compile(r"^(?:dm|direct message|message)$", re.I)
_BAD_MSG = re.compile(
    r"love|context|crush|super|boost|rose|gold|premium|coin|credit|spotlight|universe|match|power",
    re.I,
)


def boo_message_button(tree: str, sw: int, sh: int) -> Optional[Tuple[int, int]]:
    """Direct message control on the discovery card.

    Live SM-G996B tree (r51): the card action row is Boost, Pass, Super Love, Like,
    DM. The message control is labelled exactly "DM" (ImageView, clickable). The
    old substring match on send/message/arrow/plane picked "Send a Love with
    Context" (a paid style control) or the bottom nav "Messages" tab instead.
    Prefer an exact DM label, then a safe substring match that excludes paid and
    nav labels, then fractional xy.
    """
    cands = []
    for n in _parse_compact_nodes(tree):
        if n.get("x") is None or n.get("editable"):
            continue
        y = int(n.get("y") or 0)
        if y <= sh * 0.7:
            continue
        lab = _label(n).strip()
        nid = str(n.get("id") or "").lower().rsplit("/", 1)[-1]
        if _BAD_MSG.search(lab) or _BAD_MSG.search(nid):
            continue
        if _DM_LAB.match(lab):
            cands.append((0, int(n["x"]), y))
        elif any(w in lab.lower() for w in ("send", "arrow", "plane")) or (
            nid and re.search(r"(?:send|message|arrow|plane|dm)", nid)
        ):
            cands.append((1, int(n["x"]), y))
    if cands:
        cands.sort(key=lambda c: c[0])
        return (cands[0][1], cands[0][2])
    return scale_coords(sw, sh, BOO_COORDS["message_x"], BOO_COORDS["action_row_y"])


def boo_card_sig(tree: str) -> str:
    """Unique card signature: name from "Name, 24" pattern."""
    for n in _parse_compact_nodes(tree):
        if _NAME_RE.match(_label(n)):
            return _label(n)
    return boo_top_card(tree)


def boo_top_card(tree: str) -> str:
    """Name of the first (front) card in the discovery deck.

    Live trees list each card as a ScrollView labelled "Name · Verified · ..."; the
    first one is the card on screen. Used to confirm the deck advanced after a send.
    """
    for n in _parse_compact_nodes(tree):
        lab = _label(n)
        if " · " in lab and "MUTUAL INTERESTS" not in lab and n.get("x") is not None:
            name = lab.split(" · ", 1)[0].strip()
            if name and len(name) <= 40:
                return name
    return ""


def boo_composer(tree: str) -> Optional[Dict[str, Any]]:
    """The DM composer EditText (Boo package only), else None."""
    if PKG not in _pkg(tree):
        return None
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            return n
    return None


_NOT_SEND = re.compile(
    r"\bai\b|ai mode|gif|emoji|sticker|photo|camera|mic|voice|translat|settings|"
    r"clipboard|toolbar|love|boost|super|gift|coin|credit|premium|rose|gold",
    re.I,
)


def boo_send_button(
    tree: str, edit: Optional[Dict[str, Any]]
) -> Optional[Tuple[int, int]]:
    """Paper plane SEND arrow of the Boo DM composer (never the AI mode circle).

    Live SM-G996B tree (type-only runs, 28 Nov 2026): the composer is the EditText
    with, in the SAME row to its right, an unlabelled Button which is the AI mode
    circle (opens "Boo AI Page"). The send arrow is the unlabelled clickable
    ImageView on the toolbar row BELOW the field, at the far right (under the
    circle). The old generic "right of the field, same row" rule tapped the AI
    circle, so nothing was ever sent.

    Order: an explicit send/paper plane label or id, then the lowest rightmost
    unlabelled clickable below the field. Anything in the field's own row is
    refused, so a missing arrow means no tap rather than the circle.
    """
    if edit is None or edit.get("y") is None:
        return None
    ey = int(edit["y"])
    ex2 = int(edit.get("x2") or 0)
    labelled = []
    below = []
    for n in _parse_compact_nodes(tree):
        if (
            n is edit
            or n.get("x") is None
            or not n.get("clickable")
            or n.get("editable")
        ):
            continue
        x, y = int(n["x"]), int(n["y"])
        lab = _label(n)
        nid = str(n.get("id") or "").lower()
        if _NOT_SEND.search(lab) or _NOT_SEND.search(nid):
            continue
        if re.search(r"send|paper.?plane", lab, re.I) or re.search(
            r"send|paper.?plane", nid
        ):
            labelled.append((x, y))
        elif abs(y - ey) < 70:
            continue  # unlabelled, same row as the field: the AI mode circle
        elif not lab and 40 <= y - ey <= 260 and x >= max(ex2 - 20, 800):
            below.append((x, y))
    if labelled:
        return labelled[0]
    if below:
        below.sort(key=lambda c: (-c[0], -c[1]))
        return below[0]
    return None


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


def boo_on_message_composer(tree: str) -> bool:
    """Boo direct message composer opened from discovery card paper-plane arrow."""
    nodes = _parse_compact_nodes(tree)
    has_composer = any(n.get("editable") for n in nodes)
    has_send = any("send" in _label(n).lower() for n in nodes if n.get("clickable"))
    return has_composer and has_send and PKG in _pkg(tree)


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


def _composer_step(
    tree: str, fr: Dict[str, Any], text: str, opener_store: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """One planner step while a Boo DM is in flight; None when not applicable."""
    edit = boo_composer(tree)
    pending = fr.get("after_send")
    if edit is not None:
        fr["match"] = {"open": True}
        box = str(edit.get("text") or "").strip()
        hint = str(edit.get("hint") or "").strip()
        who = re.sub(r"^message\s+", "", hint, flags=re.I).strip()
        if box == hint:
            box = ""
        cm = fr.setdefault("composer", {})
        if pending and int(pending.get("taps") or 0) >= 1 and not box:
            # Composer stayed open but the box emptied: the message went out.
            fr["match_msgs"] = int(fr.get("match_msgs") or 0) + 1
            fr.pop("after_send", None)
            fr.pop("match", None)
            cm.clear()
            opener_store.clear()
            return _act(
                "press_button",
                "boo_fixed_int_match_back",
                f"{NAME}: message sent, back to the cards",
                button="back",
            )
        if box.lower() != text.lower():
            if int(cm.get("typed") or 0) >= 2:
                cm.clear()
                fr.pop("match", None)
                fr["msg_end"] = "could not type the opener"
                fr["msg_sent"] = int(fr.get("match_msgs") or 0)
                fr["phase"] = "likes"
                return _act(
                    "press_button",
                    "boo_composer_abort",
                    f"{NAME}: leave the composer",
                    button="back",
                )
            cm["typed"] = int(cm.get("typed") or 0) + 1
            return _act(
                "type",
                "boo_fixed_int_match_type",
                f"{NAME}: type '{text}'",
                text=text,
                clear=True,
            )
        if pending and int(pending.get("taps") or 0) >= 2:
            fr.pop("after_send", None)
            fr.pop("match", None)
            cm.clear()
            fr["msg_end"] = "send arrow tapped but the composer did not close"
            fr["msg_sent"] = int(fr.get("match_msgs") or 0)
            fr["phase"] = "likes"
            return _act(
                "press_button",
                "boo_composer_abort",
                f"{NAME}: leave the composer",
                button="back",
            )
        xy = boo_send_button(tree, edit)
        if not xy:
            fr.pop("match", None)
            cm.clear()
            fr["msg_end"] = "send arrow not found (refused to tap the AI circle)"
            fr["msg_sent"] = int(fr.get("match_msgs") or 0)
            fr["phase"] = "likes"
            return _act(
                "press_button",
                "boo_composer_abort",
                f"{NAME}: leave the composer",
                button="back",
            )
        pend = fr.setdefault(
            "after_send",
            {"to": who or str(fr.get("dm_to") or ""), "taps": 0, "waits": 0},
        )
        pend["taps"] = int(pend.get("taps") or 0) + 1
        return _act(
            "tap",
            "boo_fixed_int_match_send",
            f"{NAME}: send '{text}' to {who or 'card'} (paper plane arrow)",
            x=xy[0],
            y=xy[1],
        )
    if pending:
        # Composer closed. Boo plays a big send arrow over the card, then shows the
        # next card. Do nothing (never tap the overlay) until the deck is back with a
        # different front card.
        who = str(pending.get("to") or "")
        top = boo_top_card(tree)
        if boo_on_deck(tree) and top and top != who:
            fr["match_msgs"] = int(fr.get("match_msgs") or 0) + 1
            fr.pop("after_send", None)
            fr.pop("match", None)
            fr.pop("composer", None)
            opener_store.clear()
            return None
        pending["waits"] = int(pending.get("waits") or 0) + 1
        if pending["waits"] > 8:
            fr.pop("after_send", None)
            fr.pop("match", None)
            fr.pop("composer", None)
            fr["msg_end"] = "send not confirmed (deck did not advance)"
            fr["msg_sent"] = int(fr.get("match_msgs") or 0)
            fr["phase"] = "likes"
            return None
        return {
            "action": "wait",
            "reason": f"{NAME}: waiting for the send animation to clear and the next card",
            "planner": PLANNER,
            "llm_provider": None,
            "_no_llm_handoff": True,
        }
    return None


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
    # Pick the opener once per person (sticky). Re-picking every planner step made
    # the typed-box check compare against a different line, so Boo retyped and
    # never sent.
    opener_store = fr.setdefault("opener", {})
    text = _bank_text(message, st, store=opener_store)
    pk = _pkg(ui_tree)
    sw, sh = screen_size_from_tree(ui_tree)
    kw = dict(
        pkg=PKG,
        prefix="boo_fixed",
        chrome=lambda t: boo_on_deck(t) or boo_on_message_composer(t),
        app=NAME,
        thread_ids=('e="1"',),
    )

    def sent() -> int:
        return int(fr.get("match_msgs") or 0)

    def done(why: str) -> Dict[str, Any]:
        parts = (
            [f"{NAME} {mode}: {likes}/{max_likes} likes"]
            if max_likes
            else [f"{NAME} {mode}"]
        )
        if msgs:
            parts.append(f"sent {int(fr.get('msg_sent', sent()))}/{msgs}")
        extra = sent() - int(fr.get("msg_sent", sent()) if msgs else 0)
        if extra > 0:
            parts.append(f"{extra} match messages")
        return _act("done", "boo_done", ", ".join(parts) + f" — {why}")

    if not (ui_tree or "").strip():
        return None
    if dry_run:
        if boo_on_deck(ui_tree) or boo_on_message_composer(ui_tree):
            return _act(
                "done",
                "boo_dry",
                f"[DRY RUN] {NAME} screen found — would {mode} "
                f"(messages {msgs}, likes {max_likes}) — nothing tapped",
                dry_run_verified=True,
            )

    # Message phase: direct messages from discovery deck via the DM control
    if phase == "message":
        m = fr.get("match") or {}
        # Boo composer: type once, tap the SEND arrow (not the AI circle), then wait
        # for the send animation to clear and the NEXT card to show before moving on.
        if not dry_run:
            act = _composer_step(ui_tree, fr, text, opener_store)
            if act is not None:
                return act
            m = fr.get("match") or {}
        if sent() >= msgs and not m.get("open"):
            fr["msg_sent"] = sent()
            fr["phase"] = phase = "likes"
        elif m.get("open") or (is_match_popup(ui_tree) and not boo_on_deck(ui_tree)):
            if not dry_run:
                ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
                if ia:
                    return ia
                fr.pop("match", None)
        if phase == "message":
            if boo_on_deck(ui_tree):
                fr["recover"] = 0
                sig = boo_card_sig(ui_tree)
                done_sigs = fr.setdefault("done_sigs", [])
                if sig and sig in done_sigs:
                    fr["msg_sent"] = sent()
                    fr["msg_end"] = (
                        fr.get("msg_end") or "no more new people (all cards seen)"
                    )
                    fr["phase"] = phase = "likes"
                elif not dry_run:
                    if sig:
                        done_sigs.append(sig)
                    fr["match"] = {"open": True}
                    opener_store.clear()  # fresh opener for this new person
                    fr["dm_to"] = boo_top_card(ui_tree)
                    xy = boo_message_button(ui_tree, sw, sh)
                    if xy:
                        return _act(
                            "tap",
                            "boo_message_arrow",
                            f"{NAME}: direct message {sent() + 1}/{msgs} (paper-plane arrow)",
                            x=xy[0],
                            y=xy[1],
                        )
            elif PKG in pk:
                ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
                if ia:
                    return ia
                n_try = int(fr.get("msg_recover") or 0) + 1
                fr["msg_recover"] = n_try
                if n_try <= 3:
                    return _act(
                        "press_button",
                        "boo_back_deck",
                        f"{NAME}: Back to discovery deck",
                        button="back",
                    )
                fr["msg_sent"] = sent()
                fr["msg_end"] = "could not return to deck"
                fr["phase"] = phase = "likes"
            else:
                r = int(fr.get("recover") or 0) + 1
                fr["recover"] = r
                if r > MAX_RECOVER:
                    return _act("fail", "boo_lost", f"Could not open {NAME}")
                return _act(
                    "open_app", "boo_open", f"Open {NAME}", app=NAME, package=PKG
                )
        if phase == "likes" and not max_likes:
            return done(fr.get("msg_end") or "finished")
        if phase == "likes":
            fr["recover"] = 0
            fr.pop("msg_recover", None)

    # Likes phase
    if likes >= max_likes:
        return done("finished")
    blob = _blob(ui_tree)
    if PKG in pk and any(p in blob for p in _DECK_EMPTY) and not boo_on_deck(ui_tree):
        _drop(fr)
        return done("no more profiles / likes for today")
    if not dry_run and (
        (is_match_popup(ui_tree) and not boo_on_deck(ui_tree))
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
    return _act(
        "press_button", "boo_back", f"{NAME}: Back toward the cards", button="back"
    )
