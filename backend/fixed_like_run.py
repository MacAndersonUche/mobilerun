"""r50: fixed auto-like / auto-message runs for Boo, Breeze, Taimi, Pure, 3Fun.

Mac (24 Nov 10:59): "create one for boo auto message and auto like and
breeze auto tap and add auto message and auto like to taimi then add pure
auto tap and auto message and 3fun/generic auto tap".

Instruction: ``fixed app <key> <mode> messages <M> likes <L>``
  mode likes          — free like taps only (L likes)
  mode message_likes  — up to M bank-text messages to NEW matches from the
                        chats list, then L likes
  mode message        — messages only (Pure)

Rules (same as Hily/Tinder r49): no LLM, never paid, bank text only, never
double-message (a tile is opened once per run; a thread that already shows
a bank line is left alone). A like counts only when the deck shows before
AND after the tap (and, when a card name is readable, the name changed).
Popups / matches go through hily_interrupts.handle_interrupt; paid popups
are closed earlier by paid_popup (cloud_agent guard).

REAL data: Taimi (19 Nov map + tests/fixtures/dm/taimi_*.xml — deck row,
"N left", curated → Skip (Like opens GOLD), Chats "Start chat" tiles,
"Say something..." composer + send right of it, "Delivered").
GUESSES (no dump from Mac's phone): everything for Boo, Breeze, Pure and
3Fun — like button = clickable "Like"/"Heart"/id with like|heart (never
super/boost/rewind/crush), card name "Name, 24", chats tab label
Chats/Messages/Matches/Inbox, new-match tile wording (New match / Start
chat / Say hi / No messages yet / Matched), composer = any text box + Send.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        _fp,
        _parse_compact_nodes,
        taimi_deck_card_name,
        taimi_is_curated_card,
        taimi_like_action,
        taimi_on_chats_list,
        taimi_on_people_deck,
        taimi_swipes_left,
    )
    from hily_fixed_first_contact import allowed_message as _bank_text
    from hily_interrupts import handle_interrupt, is_match_popup
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp,
        _parse_compact_nodes,
        taimi_deck_card_name,
        taimi_is_curated_card,
        taimi_like_action,
        taimi_on_chats_list,
        taimi_on_people_deck,
        taimi_swipes_left,
    )
    from backend.hily_fixed_first_contact import allowed_message as _bank_text  # type: ignore
    from backend.hily_interrupts import handle_interrupt, is_match_popup  # type: ignore

PLANNER = "fixed_like_run"
MAX_RECOVER = 8
MAX_SAME_CARD = 3
BANK = ("hey how are you", "hi miss", "hello miss", "good morning")

APPS: Dict[str, Dict[str, Any]] = {
    "boo": {"pkg": "enterprises.dating.boo", "name": "Boo"},
    "breeze": {"pkg": "social.breeze.breeze_app", "name": "Breeze"},
    "pure": {"pkg": "com.getpure.pure", "name": "Pure"},
    "threefun": {"pkg": "com.threesome.swingers.threefun", "name": "3Fun"},
    "taimi": {"pkg": "com.takimi.android", "name": "Taimi",
              "chats_xy": (972, 2200), "deck_xy": (540, 2200)},  # real 19 Nov
}
_BAD_LIKE = re.compile(r"super|boost|rewind|crush|gold|premium|liked you|who likes|likes you"
                       r"|^likes\b|tab|rose|vip|coin|credit|spotlight", re.I)
_LIKE_LAB = re.compile(r"^(?:like|heart|like profile|send like|♥|❤|❤️|tap to like)$", re.I)
_NAME_RE = re.compile(r"^([A-Z][\w'’\-]+(?: [A-Z][\w'’\-]+)?),? (\d{2})$")
_CHATS_LAB = ("chats", "messages", "matches", "inbox", "chat", "conversations")
_DECK_TAB = ("discover", "explore", "home", "people", "browse", "swipe", "feed", "meet",
             "cards", "nearby")
_NEW_TILE = ("new match", "start chat", "say hi", "no messages yet", "matched",
             "start a conversation", "say hello", "it's a match")
_DECK_EMPTY = ("no one new", "no more profiles", "out of profiles", "come back later",
               "you've seen everyone", "no more people", "out of likes", "0 left")


def _label(n: Dict[str, Any]) -> str:
    return str(n.get("text") or n.get("label") or n.get("desc") or "").strip()


def _pkg(tree: str) -> str:
    m = re.search(r'packages="([^"]*)"', tree or "")
    return m.group(1) if m else ""


def _blob(tree: str) -> str:
    return " ".join(_label(n) for n in _parse_compact_nodes(tree)).lower()


def generic_like_button(tree: str) -> Optional[Tuple[int, int]]:
    """Free like control (GUESS): clickable Like/Heart, never paid ones."""
    for n in _parse_compact_nodes(tree):
        if n.get("x") is None or n.get("editable"):
            continue
        lab = _label(n)
        nid = str(n.get("id") or "").lower().rsplit("/", 1)[-1]
        if _BAD_LIKE.search(lab) or _BAD_LIKE.search(nid):
            continue
        if _LIKE_LAB.match(lab) or (nid and re.search(r"(?:^|_)(?:like|heart)(?:_|button|$)", nid)
                                    and n.get("clickable")):
            return (int(n["x"]), int(n["y"]))
    return None


def generic_card_sig(tree: str) -> str:
    for n in _parse_compact_nodes(tree):
        if _NAME_RE.match(_label(n)):
            return _label(n)
    return ""


def _on_deck(key: str, tree: str) -> bool:
    if APPS[key]["pkg"] not in _pkg(tree):
        return False
    if key == "taimi":
        return taimi_on_people_deck(tree)
    return generic_like_button(tree) is not None and not any(
        n.get("editable") for n in _parse_compact_nodes(tree))


def _sig(key: str, tree: str) -> str:
    if key == "taimi":
        name = taimi_deck_card_name(tree) or ""
        left = taimi_swipes_left(tree)
        return f"{name}|{left}" if (name or left is not None) else ""
    return generic_card_sig(tree)


def _on_chats(key: str, tree: str) -> bool:
    if key == "taimi":
        return taimi_on_chats_list(tree)
    nodes = _parse_compact_nodes(tree)
    head = any(_label(n).lower() in _CHATS_LAB and int(n.get("y") or 9999) < 400 for n in nodes)
    tile = any(any(w in _label(n).lower() for w in _NEW_TILE) for n in nodes)
    return head or (tile and not any(n.get("editable") for n in nodes))


def _known(key: str) -> Callable[[str], bool]:
    def f(tree: str) -> bool:
        return _on_deck(key, tree) or _on_chats(key, tree)
    return f


def _tab(tree: str, labels: Tuple[str, ...]) -> Optional[Tuple[int, int]]:
    for n in _parse_compact_nodes(tree):
        lab = _label(n).lower()
        first = lab.split(",")[0].strip()
        if n.get("x") is not None and first in labels and int(n.get("y") or 0) > 1900:
            return (int(n["x"]), int(n["y"]))
    return None


def _new_tile(key: str, tree: str, done: List[str]) -> Optional[Tuple[int, int, str]]:
    for n in _parse_compact_nodes(tree):
        lab = _label(n)
        low = lab.lower()
        if n.get("x") is None or "daily pick" in low or low.startswith(("say '", 'say "')):
            continue
        if key == "taimi":
            if "start chat" not in low:
                continue
        elif not any(w in low for w in _NEW_TILE):
            continue
        name = lab.split(",")[0].strip() or lab
        if name in done:
            continue
        return (int(n["x"]), int(n["y"]), name)
    return None


def parse(instruction: str) -> Tuple[str, str, int, int]:
    m = re.search(r"fixed app (\w+) (\w+)(?: messages (\d+))?(?: likes (\d+))?",
                  (instruction or "").lower())
    if not m or m.group(1) not in APPS:
        return "", "", 0, 0
    return (m.group(1), m.group(2), min(500, int(m.group(3) or 0)),
            min(500, int(m.group(4) or 0)))


def _act(kind: str, step: str, reason: str, **kw: Any) -> Dict[str, Any]:
    a = {"action": kind, "reason": f"{reason} ({PLANNER})", "planner": PLANNER,
         "llm_provider": None, "_no_llm_handoff": True}
    a.update(kw)
    return _fp(a, step)


def _drop(fr: Dict[str, Any]) -> None:
    if fr.get("awaiting"):
        fr["awaiting"] = False
        fr["unverified"] = int(fr.get("unverified") or 0) + 1


def plan_fixed_like_run(
    instruction: str,
    ui_tree: str,
    history: Optional[List[Any]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    key, mode, msgs, max_likes = parse(instruction)
    if not key:
        return _act("fail", "fixed_like_bad", f"Unknown fixed app run: {instruction[:60]}")
    app = APPS[key]
    PKG, NAME = app["pkg"], app["name"]
    st = state if isinstance(state, dict) else {}
    fr = st.setdefault("fixed_like_run", {})
    fr.setdefault("likes", 0)
    phase = fr.setdefault("phase", "message" if mode in ("message", "message_likes") and msgs
                          else "likes")
    likes = int(fr["likes"])
    text = _bank_text(message)
    pk = _pkg(ui_tree)
    kw = dict(pkg=PKG, prefix=f"fixed_like_{key}", chrome=_known(key), app=NAME,
              thread_ids=('e="1"',))

    def sent() -> int:
        return int(fr.get("match_msgs") or 0)

    def done(why: str) -> Dict[str, Any]:
        parts = [f"{NAME} {mode}: {likes}/{max_likes} likes"] if max_likes else [f"{NAME} {mode}"]
        if msgs:
            parts.append(f"sent {int(fr.get('msg_sent', sent()))}/{msgs}")
        extra = sent() - int(fr.get("msg_sent", sent()) if msgs else 0)
        if extra > 0:
            parts.append(f"{extra} match messages")
        return _act("done", "fixed_like_done", ", ".join(parts) + f" — {why}")

    if not (ui_tree or "").strip():
        return None
    if dry_run:
        if _on_deck(key, ui_tree) or _on_chats(key, ui_tree):
            return _act("done", "fixed_like_dry",
                        f"[DRY RUN] {NAME} screen found — would {mode} "
                        f"(messages {msgs}, likes {max_likes}) — nothing tapped",
                        dry_run_verified=True)

    # ---------------- message phase (new matches only) ----------------
    if phase == "message":
        m = fr.get("match") or {}
        if sent() >= msgs and not m.get("open"):
            fr["msg_sent"] = sent()
            fr["phase"] = phase = "likes"
        elif m.get("open") or (is_match_popup(ui_tree) and not _on_chats(key, ui_tree)):
            if not dry_run:
                # a thread that already shows a bank line → never double-message
                if m.get("open") and not m.get("typed") and not m.get("awaiting") and any(
                        _label(n).lower() in BANK for n in _parse_compact_nodes(ui_tree)
                        if not n.get("editable")):
                    fr.pop("match", None)
                    return _act("press_button", "fixed_like_already_messaged",
                                f"{NAME}: this chat already has a message — Back, no double message",
                                button="back")
                ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
                if ia:
                    return ia
                fr.pop("match", None)
        if phase == "message":
            if _on_chats(key, ui_tree):
                fr["recover"] = 0
                t = _new_tile(key, ui_tree, fr.setdefault("done_names", []))
                if t and not dry_run:
                    fr["done_names"].append(t[2])
                    fr["match"] = {"open": True}
                    return _act("tap", "fixed_like_open_match",
                                f"{NAME}: open new match '{t[2]}' ({sent() + 1}/{msgs})",
                                x=t[0], y=t[1])
                fr["msg_sent"] = sent()
                fr["msg_end"] = "no more new matches"
                fr["phase"] = phase = "likes"
            elif PKG in pk:
                c = app.get("chats_xy") or _tab(ui_tree, _CHATS_LAB)
                n_try = int(fr.get("chat_tries") or 0) + 1
                fr["chat_tries"] = n_try
                if c and n_try <= 3:
                    return _act("tap", "fixed_like_chats_tab", f"{NAME}: open Chats",
                                x=c[0], y=c[1])
                if n_try <= 5:
                    ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
                    if ia:
                        return ia
                    return _act("press_button", "fixed_like_back_chats",
                                f"{NAME}: Back toward Chats", button="back")
                fr["msg_sent"] = sent()
                fr["msg_end"] = "Chats not found"
                fr["phase"] = phase = "likes"
            else:
                r = int(fr.get("recover") or 0) + 1
                fr["recover"] = r
                if r > MAX_RECOVER:
                    return _act("fail", "fixed_like_lost", f"Could not open {NAME}")
                return _act("open_app", "fixed_like_open", f"Open {NAME}", app=NAME, package=PKG)
        if phase == "likes" and not max_likes:
            return done(fr.get("msg_end") or "finished")
        if phase == "likes":
            fr["recover"] = 0

    # ---------------- likes phase ----------------
    if likes >= max_likes:
        return done("finished")
    blob = _blob(ui_tree)
    if PKG in pk and any(p in blob for p in _DECK_EMPTY) and not _on_deck(key, ui_tree) or (
            key == "taimi" and taimi_swipes_left(ui_tree) == 0):
        _drop(fr)
        return done("no more profiles / likes for today")
    if not dry_run and ((is_match_popup(ui_tree) and not _on_chats(key, ui_tree))
                        or (fr.get("match") or {}).get("open")):
        ia = handle_interrupt(ui_tree, fr, text, PLANNER, **kw)
        if ia:
            _drop(fr)
            return ia
    if _on_deck(key, ui_tree):
        fr["recover"] = 0
        fr.pop("match", None)
        sig = _sig(key, ui_tree)
        if fr.get("awaiting"):
            fr["awaiting"] = False
            before = str(fr.get("sig") or "")
            if before and sig and before == sig:
                fr["same"] = int(fr.get("same") or 0) + 1
                fr["unverified"] = int(fr.get("unverified") or 0) + 1
                if fr["same"] >= MAX_SAME_CARD:
                    return _act("fail", "fixed_like_stuck",
                                f"{NAME}: card did not change after {MAX_SAME_CARD} taps "
                                f"({likes} likes)")
            else:
                fr["same"] = 0
                likes += 1
                fr["likes"] = likes
                if likes >= max_likes:
                    return done("finished")
        if dry_run:
            return None
        if key == "taimi":
            a = taimi_like_action(ui_tree, planner=PLANNER)
            if a and taimi_is_curated_card(ui_tree):
                a = dict(a)
                a["_no_llm_handoff"] = True
                a["fastpath_step"] = a["_fastpath_step"] = "fixed_like_skip_curated"
                return a  # Like on a curated card opens GOLD — Skip, not counted
            xy = (int(a["x"]), int(a["y"])) if a else None
        else:
            xy = generic_like_button(ui_tree)
        if xy:
            fr["awaiting"] = True
            fr["sig"] = sig
            return _act("tap", "fixed_like_tap_like_swipe",
                        f"{NAME} free like {likes + 1}/{max_likes}", x=xy[0], y=xy[1],
                        _free_like=True)

    _drop(fr)  # not the deck after the tap → that like is not counted
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
        return _act("fail", "fixed_like_lost",
                    f"{NAME}: could not get back to the cards after {MAX_RECOVER} tries "
                    f"({likes} likes)")
    if PKG not in pk:
        return _act("open_app", "fixed_like_open", f"Open {NAME}", app=NAME, package=PKG)
    c = app.get("deck_xy") or _tab(ui_tree, _DECK_TAB)
    if c and r % 3 != 0:
        return _act("tap", "fixed_like_deck_tab", f"{NAME}: open the cards tab", x=c[0], y=c[1])
    return _act("press_button", "fixed_like_back", f"{NAME}: Back toward the cards",
                button="back")
