"""Taimi first-contact from the People deck suggested-message chips (Mac, t361u).

On each People card a suggested line sits just above the Like button
(e.g. "Heyy Eleanor", "Katie, hi how r u?", "Coffee?"). Tapping that
chip sends it. Do not tap Instant Chat (middle) or Like (right).

Prefer a chip that matches Mac's line ("good evening beautiful") when
one is there; otherwise any suggested chip on the front card. If a
Gold / paywall / purchase screen appears, Back and STOP. Never buy.
Never message existing Chats. FLAG_SECURE blacks screenshots — count
only from the UI tree.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        _fp as _fp_raw,
        _parse_compact_nodes,
        taimi_action_row_centers,
        taimi_deck_card_name,
        taimi_dismiss_paywall,
        taimi_is_paywall,
        taimi_on_chats_list,
        taimi_on_people_deck,
        taimi_on_thread,
        taimi_swipes_left,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp as _fp_raw,
        _parse_compact_nodes,
        taimi_action_row_centers,
        taimi_deck_card_name,
        taimi_dismiss_paywall,
        taimi_is_paywall,
        taimi_on_chats_list,
        taimi_on_people_deck,
        taimi_on_thread,
        taimi_swipes_left,
    )


PLANNER = "taimi_fixed_first_contact_no_llm_handoff"
PKG = "com.takimi.android"
NAME = "Taimi"
DECK_TAB_XY = (540, 2200)
# Suggested chip band: above the action row (row y1 ≈ 1875) and below the name.
CHIP_Y1_MIN = 1650
CHIP_Y2_MAX = 1870
PAYWALL_STOP = (
    "Taimi suggested-message hit a Gold/paywall — Back, stopped, never bought"
)


def _fp(action: Dict[str, Any], step: str) -> Dict[str, Any]:
    action = dict(action)
    action["_no_llm_handoff"] = True
    action.setdefault("llm_provider", None)
    action.setdefault("planner", PLANNER)
    return _fp_raw(action, step)


def _blob(tree: str) -> str:
    return " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''}"
        for n in _parse_compact_nodes(tree)
    ).lower()


def comment_text(instruction: str, message: Optional[str] = None) -> str:
    qm = re.search(r"[\"']([^\"']+)[\"']", instruction or "")
    if qm:
        return qm.group(1).strip()
    raw = (message or "").strip()
    return raw or "good evening beautiful"


def target_count(instruction: str, target: Optional[int] = None) -> int:
    if target and int(target) > 0:
        return int(target)
    m = re.search(r"(\d+)\s+first[- ]contact", (instruction or "").lower())
    return int(m.group(1)) if m else 5


def taimi_instant_chat_sheet(tree: str) -> bool:
    blob = _blob(tree)
    return (
        "send instant chat" in blob
        or "add an intro (optional)" in blob
        or "catch their eye by sending instant chat" in blob
    )


def taimi_purchase_screen(tree: str) -> bool:
    if taimi_is_paywall(tree):
        return True
    blob = _blob(tree)
    if "continue" in blob and any(
        k in blob for k in ("gold", "£", "$", "subscription", "purchase", "billing")
    ):
        return True
    if "taimi gold" in blob or "included with taimi gold" in blob:
        return True
    return False


def taimi_left_counter(tree: str) -> Optional[int]:
    n = taimi_swipes_left(tree)
    if n is not None:
        return n
    m = re.search(r"\b(\d+)\s+left\b", _blob(tree))
    return int(m.group(1)) if m else None


def _in_taimi_tree(tree: str) -> bool:
    """Foreground tree is Taimi — ignore the job package (tai2 was the launcher)."""
    if "com.takimi.android" in (tree or "").lower():
        return True
    for n in _parse_compact_nodes(tree):
        if "takimi" in str(n.get("package") or "").lower():
            return True
    return False


def _people_tab_xy(tree: str) -> Tuple[int, int]:
    for n in _parse_compact_nodes(tree):
        lab = f"{n.get('text') or ''} {n.get('desc') or ''}".strip().lower()
        if lab == "people" or lab.startswith("people,"):
            x, y = int(n.get("x") or 0), int(n.get("y") or 0)
            if y >= 2000 and x:
                return (x, y)
    return DECK_TAB_XY


def _clean_chip_text(raw: str) -> str:
    text = re.sub(r"[\ue000-\uf8ff]", "", raw or "")
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text


def deck_suggested_chips(tree: str) -> List[Dict[str, Any]]:
    """Clickable suggested-message chips just above the Like / action row."""
    chips: List[Dict[str, Any]] = []
    seen = set()
    for n in _parse_compact_nodes(tree):
        y1 = n.get("y1")
        y2 = n.get("y2")
        x1 = n.get("x1")
        x2 = n.get("x2")
        y = int(n.get("y") or 0)
        if y1 is None or y2 is None:
            if not (CHIP_Y1_MIN <= y <= CHIP_Y2_MAX):
                continue
            y1, y2 = y - 30, y + 30
        else:
            y1, y2 = int(y1), int(y2)
        # Chip must start in the band (name labels can overlap the top of it).
        if y1 < CHIP_Y1_MIN or y1 > CHIP_Y2_MAX:
            continue
        if x1 is not None and x2 is not None and int(x2) - int(x1) < 120:
            continue
        raw = (n.get("desc") or n.get("text") or n.get("label") or "").strip()
        text = _clean_chip_text(raw)
        if not text or len(text) < 3:
            continue
        low = text.lower()
        if any(
            b in low
            for b in (
                "instant chat",
                "catch their eye",
                "add an intro",
                "private pics",
                "private album",
                "curated for you",
                "active today",
                "people",
                "chats",
                "likes",
                "profile",
                "trending",
                "continue",
                "gold",
                "unlocks after",
            )
        ):
            continue
        # Action-row icons have no real words; require a letter.
        if not re.search(r"[A-Za-z]", text):
            continue
        # A bare profile name in this band is not a suggested message.
        if re.fullmatch(r"[A-Za-z][A-Za-z'\-]{1,24}", text) and "?" not in text:
            continue
        key = low[:60]
        if key in seen:
            continue
        seen.add(key)
        chips.append(
            {
                "text": text,
                "x": int(n.get("x") or 0),
                "y": int(n.get("y") or 0),
            }
        )
    return chips


def pick_suggested_chip(
    tree: str,
    preferred: str = "good evening beautiful",
    card_name: str = "",
) -> Optional[Dict[str, Any]]:
    """Prefer a chip matching Mac's line, else one for this card, else any."""
    chips = deck_suggested_chips(tree)
    if not chips:
        return None
    want = (preferred or "").strip().lower().rstrip(".!?")
    if want:
        for c in chips:
            if want in c["text"].lower() or c["text"].lower().rstrip(".!?") == want:
                return c
    if card_name:
        name = str(card_name).strip().lower()
        named = [c for c in chips if name and name in c["text"].lower()]
        if named:
            # Front-card chip — prefer the one that names this person.
            return named[0]
    return chips[0]


def plan_taimi_fixed_first_contact(
    instruction: str,
    ui_tree: str,
    history: List[str],
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
    dry_run: bool = False,
    message: Optional[str] = None,
    target: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Tap a deck suggested-message chip; stop on Gold/paywall. Never Instant Chat or Like."""
    del history, package
    st = state if isinstance(state, dict) else {}
    fc = st.setdefault("taimi_fc", {})
    fc.setdefault("sent_names", [])
    fc.setdefault("sent_chips", [])
    text = comment_text(instruction, message)
    cap = target_count(instruction, target)
    tree = ui_tree or ""
    left = taimi_left_counter(tree)
    if left is not None and fc.get("left_at_start") is None:
        fc["left_at_start"] = left
    fc["left_last"] = left

    def _act(action: str, step: str, reason: str, **extra: Any) -> Dict[str, Any]:
        body: Dict[str, Any] = {"action": action, "reason": f"{reason} ({PLANNER})"}
        body.update(extra)
        return _fp(body, step)

    def _sent() -> List[str]:
        return list(fc.get("sent_names") or [])

    def _done(why: str) -> Dict[str, Any]:
        names = ", ".join(_sent()) or "none"
        chips = "; ".join(fc.get("sent_chips") or []) or "none"
        return _act(
            "done",
            "taimi_fc_done",
            f"Taimi suggested-message finished {len(_sent())}/{cap} "
            f"(names: {names}; chips: {chips}). {why}",
        )

    def _stop_paywall() -> Dict[str, Any]:
        fc["paywall_stop"] = True
        names = ", ".join(_sent()) or "none"
        return _act(
            "fail",
            "taimi_fc_paywall_stop",
            f"{PAYWALL_STOP}. Sent {len(_sent())}/{cap}: {names}",
        )

    try:
        from cast_prompt import cancel_cast_prompt_action
    except ImportError:
        from backend.cast_prompt import cancel_cast_prompt_action  # type: ignore
    prompt_act = cancel_cast_prompt_action(tree, state)
    if prompt_act:
        return prompt_act

    if not tree.strip():
        return _act("wait", "taimi_fc_wait_tree", "Taimi first-contact — waiting for a tree")

    # r70: compact dump can be empty while Taimi is in front. Wait for a
    # full / uiautomator tree. Never Back / never re-open from the launcher.
    try:
        from taimi_tree_fallback import is_empty_tree, tree_has_useful_nodes
    except ImportError:
        from backend.taimi_tree_fallback import (  # type: ignore
            is_empty_tree,
            tree_has_useful_nodes,
        )
    if _in_taimi_tree(tree) and (is_empty_tree(tree) or not tree_has_useful_nodes(tree)):
        w = int(fc.get("empty_dump_waits") or 0) + 1
        fc["empty_dump_waits"] = w
        if w > 12:
            return _act(
                "fail",
                "taimi_fc_empty_tree",
                "Taimi is open but the UI tree is empty (compact dump nodes=0) "
                "and no full/uiautomator dump arrived — cannot see suggested chips safely",
            )
        a = _act(
            "wait",
            "taimi_fc_wait_full_dump",
            "Taimi is in front but the compact tree is empty — waiting for a "
            "full/uiautomator dump, never Back",
        )
        a["_ignore_same_decision"] = True
        a["_force_redump"] = True
        return a

    if len(_sent()) >= cap:
        return _done("target reached")

    if taimi_purchase_screen(tree):
        n = int(fc.get("paywall_backs") or 0) + 1
        fc["paywall_backs"] = n
        # A chip tap that opened Gold is not a send.
        fc["awaiting_send"] = False
        fc["pending_name"] = ""
        a = taimi_dismiss_paywall(tree, planner=PLANNER)
        if n == 1 and a:
            a["_no_llm_handoff"] = True
            a["reason"] = (
                f"Taimi Gold/paywall — Back, never Continue, then stop ({PLANNER})"
            )
            return a
        if n <= 2:
            return _act(
                "press_button",
                "taimi_fc_paywall_back",
                "Taimi Gold/paywall — Back, never Continue, then stop",
                button="back",
            )
        return _stop_paywall()

    # After tapping a chip: count only when the front card changes / chip is gone.
    if fc.get("awaiting_send"):
        pending = fc.get("pending_name") or ""
        pending_chip = fc.get("pending_chip") or ""
        if taimi_instant_chat_sheet(tree):
            # Chip opened Instant Chat — we are not using that path. Back, no count.
            fc["awaiting_send"] = False
            fc["pending_name"] = ""
            return _act(
                "press_button",
                "taimi_fc_chip_opened_ic",
                "Suggested chip opened Instant Chat — Back, will not use Instant Chat",
                button="back",
            )
        name_now = taimi_deck_card_name(tree) or ""
        still_pending = bool(pending) and name_now.lower() == pending.lower()
        chip_now = pick_suggested_chip(tree, preferred=text, card_name=name_now)
        same_chip = bool(
            still_pending
            and chip_now
            and pending_chip
            and chip_now["text"].lower() == pending_chip.lower()
        )
        if still_pending and (same_chip or taimi_on_people_deck(tree) and chip_now):
            w = int(fc.get("confirm_tries") or 0) + 1
            fc["confirm_tries"] = w
            if w >= 3:
                fc["awaiting_send"] = False
                fc["pending_name"] = ""
                skip = (taimi_action_row_centers(tree) or {}).get("skip")
                if skip:
                    return _act(
                        "tap",
                        "taimi_fc_skip_unconfirmed",
                        f"Suggested message to {pending} was not confirmed — Skip, will not count it",
                        x=int(skip[0]),
                        y=int(skip[1]),
                    )
                return _act(
                    "wait",
                    "taimi_fc_unconfirmed",
                    f"Suggested message to {pending} was not confirmed — will not count it",
                )
            return _act(
                "wait",
                "taimi_fc_wait_confirm",
                f"Waiting to confirm suggested message to {pending}",
            )
        # Front card moved or the chip is gone — count it.
        if pending and pending not in _sent():
            fc["sent_names"] = _sent() + [pending]
            chips = list(fc.get("sent_chips") or [])
            if pending_chip:
                chips.append(f"{pending}: {pending_chip}")
            fc["sent_chips"] = chips
        fc["awaiting_send"] = False
        fc["pending_name"] = ""
        fc["pending_chip"] = ""
        fc["confirm_tries"] = 0
        if len(_sent()) >= cap:
            return _done("target reached")
        # Fall through to the next card.

    if taimi_instant_chat_sheet(tree):
        n = int(fc.get("ic_backs") or 0) + 1
        fc["ic_backs"] = n
        if n > 3:
            return _act(
                "fail",
                "taimi_fc_ic_stuck",
                "Stuck on Instant Chat — stopped, will not send from that sheet",
            )
        return _act(
            "press_button",
            "taimi_fc_instant_chat_back",
            "Instant Chat sheet — Back, use the deck suggested chip instead",
            button="back",
        )

    if taimi_on_thread(tree):
        n = int(fc.get("thread_backs") or 0) + 1
        fc["thread_backs"] = n
        if n > 3:
            return _act(
                "fail",
                "taimi_fc_blocked_existing",
                "Taimi opened an existing chat — Back, will not message existing chats",
            )
        return _act(
            "press_button",
            "taimi_fc_thread_back",
            "Taimi existing chat — Back, never message existing chats",
            button="back",
        )

    if not _in_taimi_tree(tree):
        r = int(fc.get("open_tries") or 0) + 1
        fc["open_tries"] = r
        if r > 8:
            return _act(
                "fail",
                "taimi_fc_lost",
                "Could not open Taimi (not in the foreground)",
            )
        return _act(
            "open_app",
            "taimi_fc_open",
            "Open Taimi — tree is not Taimi yet",
            app=NAME,
            package=PKG,
        )

    if taimi_on_people_deck(tree) and not taimi_instant_chat_sheet(tree):
        name = taimi_deck_card_name(tree) or ""
        fc["seen_name"] = name
        row = taimi_action_row_centers(tree)
        if name and name in _sent():
            skip = row.get("skip")
            if skip:
                return _act(
                    "tap",
                    "taimi_fc_skip",
                    f"Skip {name} (already sent a suggested message) — never Like",
                    x=int(skip[0]),
                    y=int(skip[1]),
                )
        chip = pick_suggested_chip(tree, preferred=text, card_name=name)
        if not chip:
            skip = row.get("skip")
            w = int(fc.get("no_chip") or 0) + 1
            fc["no_chip"] = w
            if skip and w <= 8:
                return _act(
                    "tap",
                    "taimi_fc_skip_no_chip",
                    f"No suggested message on {name or 'this card'} — Skip, never Like",
                    x=int(skip[0]),
                    y=int(skip[1]),
                )
            if w > 8:
                return _act(
                    "fail",
                    "taimi_fc_no_chip",
                    "No suggested-message chips on the People deck — stopped, never Like or Instant Chat",
                )
            return _act(
                "wait",
                "taimi_fc_wait_chip",
                "People deck — waiting for a suggested-message chip",
            )
        if dry_run:
            return _act(
                "done",
                "taimi_fc_dry",
                f"[DRY RUN] would tap suggested '{chip['text']}' on {name or 'card'} — nothing tapped",
                dry_run_verified=True,
                would_send_text=chip["text"],
            )
        fc["pending_name"] = name
        fc["pending_chip"] = chip["text"]
        fc["awaiting_send"] = True
        fc["confirm_tries"] = 0
        fc["no_chip"] = 0
        # Never pass Like / Instant Chat coordinates.
        like = row.get("like")
        ic = row.get("instant_chat")
        xy = (int(chip["x"]), int(chip["y"]))
        if like and xy == (int(like[0]), int(like[1])):
            return _act(
                "fail",
                "taimi_fc_chip_is_like",
                "Refusing to tap — the chip centre collided with Like",
            )
        if ic and xy == (int(ic[0]), int(ic[1])):
            return _act(
                "fail",
                "taimi_fc_chip_is_ic",
                "Refusing to tap — the chip centre collided with Instant Chat",
            )
        return _act(
            "tap",
            "taimi_fc_suggested",
            f"Tap suggested message '{chip['text']}' on {name or 'card'} — never Like or Instant Chat",
            x=xy[0],
            y=xy[1],
        )

    if taimi_on_chats_list(tree) or re.search(
        r"\b(chats|likes|profile|trending)\b", _blob(tree)
    ):
        x, y = _people_tab_xy(tree)
        n = int(fc.get("tab_tries") or 0) + 1
        fc["tab_tries"] = n
        if n > 5:
            return _act("fail", "taimi_fc_no_deck", "Could not open the Taimi People deck")
        return _act(
            "tap",
            "taimi_fc_people_tab",
            "Open the Taimi People deck — never Chats",
            x=x,
            y=y,
        )

    w = int(fc.get("wait_card") or 0) + 1
    fc["wait_card"] = w
    if w > 4:
        return _act("fail", "taimi_fc_no_card", "Taimi People deck did not show a card")
    return _act("wait", "taimi_fc_wait_card", "Taimi — waiting for a People deck card")
