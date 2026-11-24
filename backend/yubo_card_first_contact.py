"""r46 (CA-18): Yubo first contact from the deck cards — never Conversations.

Mac (24 Nov): "from the cards click into each card into the send message
box and click direct message not the blast then type the message then click
the up arrow then wait for the chat sent to appear on the screen then swipe
that card to the right and do the same after the next card has appeared".

Per card:
  1. Tap the card's "Send a message" pill (never the rocket boost).
  2. The sheet opens on paid Blast — tap Direct; never type/send on Blast.
  3. Type a message-bank line (cleared box), tap the purple up arrow.
  4. Count it only after a sent signal shows on screen and the text box is
     empty (or the sheet has closed). No signal after a few waits → the card
     is NOT counted, and it is still swiped (never message one person twice).
  5. Swipe the card right, wait for the next card's name, repeat until N.

Coordinates (S21+ 1080x2400):
  "Send a message" pill (260, 2000) — 19 Nov map, text node used when present.
  Direct tile (855, 656); selected Direct text [729,515][875,572] — 22 Nov dump.
  Up arrow (986, 1335) — right of the composer, 22 Nov + 24 Nov dumps.
  Like swipe 250,1000 → 1050,1050 — 19 Nov map.
  Deck tab (140, 2194) — 19 Nov map.
  GUESS: the "sent" text Mac describes was never captured in a dump; the
  planner accepts a text node containing "sent" (e.g. "Message sent",
  "Sent", "Chat sent") or the typed line shown outside the text box.
No LLM; Yubucks (840,158), rocket (1000,2000), Blast, Super Blast,
Infinity/HyperSurge are never tapped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        yubo_deck_card_name,
        yubo_direct_sheet_action,
        yubo_on_deck,
    )
    from yubo_fixed_first_contact import (
        _on_paywall,
        _send_right_of_composer,
        allowed_message,
        blast_selected,
        composer_text,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        yubo_deck_card_name,
        yubo_direct_sheet_action,
        yubo_on_deck,
    )
    from backend.yubo_fixed_first_contact import (  # type: ignore
        _on_paywall,
        _send_right_of_composer,
        allowed_message,
        blast_selected,
        composer_text,
    )

PLANNER = "yubo_card_fixed_first_contact_no_llm_handoff"
PKG = "co.yellw.yellowapp"
SEND_PILL_XY = (260, 2000)
DIRECT_XY = (855, 656)
SEND_XY = (986, 1335)
DECK_TAB_XY = (140, 2194)
YUBUCKS_XY = (840, 158)
ROCKET_XY = (1000, 2000)
_PAID_XY = (YUBUCKS_XY, ROCKET_XY)
MAX_SENT_WAITS = 3
MAX_DIRECT_TRIES = 3
MAX_RECOVER = 8
_SENT_RE = re.compile(r"\b(?:message|chat|reaction)?\s*sent\b", re.I)


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


def on_send_sheet(tree: str) -> bool:
    """The card's 'Send a message' sheet (Blast / Super Blast / Direct tiles)."""
    labels = {
        (n.get("text") or n.get("label") or "").strip().lower()
        for n in _parse_compact_nodes(tree)
    }
    return "direct" in labels and ("blast" in labels or "super blast" in labels)


def sent_seen(tree: str, text: str) -> bool:
    """A sent signal on screen: 'sent' text, or the line shown outside the box."""
    want = (text or "").strip().lower()
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        t = (n.get("text") or n.get("label") or "").strip()
        if not t or len(t) > 60:
            continue
        low = t.lower()
        if "send a message" in low or "unsent" in low:
            continue
        if _SENT_RE.search(low):
            return True
        if want and low == want:
            return True
    return False


def _pill(tree: str) -> Tuple[int, int]:
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        t = (n.get("text") or n.get("label") or "").strip().lower()
        if t == "send a message" and int(n.get("y") or 0) > 1500 and int(n.get("x") or 0) < 800:
            return (int(n["x"]), int(n["y"]))
    return SEND_PILL_XY


def _like_swipe(card: str, n: int) -> Dict[str, Any]:
    x1, y1, x2, y2, dur = DM_APP_PROFILES["yubo"]["like_swipe"]
    return _act(
        "swipe", "yubo_card_fixed_like_swipe",
        f"Swipe {card or 'this card'} right after the message (card {n})",
        x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=dur,
    )


def plan_yubo_card_first_contact(
    instruction: str,
    ui_tree: str,
    history: Optional[List[str]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
    dry_run: bool = False,
    message: str = "",
    target: int = 2,
) -> Optional[Dict[str, Any]]:
    st = state if isinstance(state, dict) else {}
    yc = st.setdefault("yubo_card", {"sent": 0, "cards": 0, "phase": "open"})
    st["yubo_card"] = yc
    cap = max(1, int(target or 1))
    sent = int(yc.get("sent") or 0)
    phase = str(yc.get("phase") or "open")
    text = allowed_message(message)
    # keep bulk counters in step for the bench/progress readers
    st.setdefault("bulk_message_new", {})["done"] = sent

    if sent >= cap and phase == "open":
        return _act("done", "yubo_card_done",
                    f"Yubo first contact finished {sent}/{cap} from deck cards"
                    + (f" ({yc.get('unconfirmed')} unconfirmed)" if yc.get("unconfirmed") else ""))

    if dry_run:
        return _act("done", "yubo_card_dry",
                    f"[DRY RUN] Yubo: per card would open Send a message → Direct "
                    f"(never Blast) → type '{text}' → up arrow → wait for sent → "
                    f"swipe right, {cap} cards — nothing tapped",
                    dry_run=True, dry_run_verified=True, would_send_text=text)

    # Paid upsells (Infinity / HyperSurge) — Back, never Continue/Unlock
    if _on_paywall(ui_tree) and not on_send_sheet(ui_tree):
        return _act("press_button", "yubo_card_paywall_back",
                    "Yubo paid upsell — Back, nothing bought", button="back")

    sheet = on_send_sheet(ui_tree)

    # ---- waiting for the sent signal ----
    if phase == "awaiting_sent":
        box = composer_text(ui_tree).lower() if sheet else ""
        if sent_seen(ui_tree, text) and not box:
            yc["sent"] = sent = sent + 1
            st["bulk_message_new"]["done"] = sent
            yc["phase"] = "swipe"
            yc["waits"] = 0
            phase = "swipe"
        elif sheet and box == text.lower():
            tries = int(yc.get("send_retry") or 0)
            if tries < 1 and not blast_selected(ui_tree):
                yc["send_retry"] = tries + 1
                xy = _send_right_of_composer(ui_tree) or SEND_XY
                if xy not in _PAID_XY:
                    return _act("tap", "yubo_card_send_retry",
                                f"'{text}' still in the box — tap the up arrow again",
                                x=int(xy[0]), y=int(xy[1]))
            yc["phase"] = "swipe"
            yc["unconfirmed"] = int(yc.get("unconfirmed") or 0) + 1
            phase = "swipe"
        else:
            w = int(yc.get("waits") or 0) + 1
            yc["waits"] = w
            if w <= MAX_SENT_WAITS:
                return _act("wait", "yubo_card_wait_sent",
                            f"Waiting for the sent message to show ({w}/{MAX_SENT_WAITS})",
                            seconds=1.5, delay_s=1.5)
            # no sent signal — not counted; still move on (never message twice)
            yc["unconfirmed"] = int(yc.get("unconfirmed") or 0) + 1
            yc["phase"] = "swipe"
            yc["waits"] = 0
            phase = "swipe"

    # ---- the send sheet ----
    if sheet:
        if phase == "swipe":
            # Message done for this card: close the sheet back to the card
            return _act("press_button", "yubo_card_close_sheet",
                        "Close the send sheet back to the card", button="back")
        if blast_selected(ui_tree) or yubo_direct_sheet_action(ui_tree, planner=PLANNER):
            n = int(yc.get("direct_tries") or 0) + 1
            yc["direct_tries"] = n
            if n > MAX_DIRECT_TRIES:
                return _act("fail", "yubo_card_blast_stop",
                            f"Sheet stays on paid Blast after {MAX_DIRECT_TRIES} Direct "
                            f"taps — stop, nothing sent")
            sel = yubo_direct_sheet_action(ui_tree, planner=PLANNER)
            xy = (sel["x"], sel["y"]) if sel and sel.get("action") == "tap" else DIRECT_XY
            return _act("tap", "yubo_card_select_direct",
                        "Select Direct (Blast is paid, never send on it)",
                        x=int(xy[0]), y=int(xy[1]))
        yc["direct_tries"] = 0
        box = composer_text(ui_tree)
        if box.lower() != text.lower():
            if yc.get("typed_n", 0) >= 2:
                return _act("fail", "yubo_card_type_failed",
                            f"Text box shows '{box[:30]}' not '{text}' after 2 tries — stop")
            yc["typed_n"] = int(yc.get("typed_n") or 0) + 1
            return _act("type", "yubo_card_type",
                        f"Type '{text}' in the Direct box", text=text, clear=True)
        if blast_selected(ui_tree):  # belt and braces
            return _act("fail", "yubo_card_refuse_blast", "Blast selected at send — refuse")
        xy = _send_right_of_composer(ui_tree) or SEND_XY
        if xy in _PAID_XY:
            xy = SEND_XY
        yc["attempts"] = int(yc.get("attempts") or 0) + 1
        yc["phase"] = "awaiting_sent"
        yc["waits"] = 0
        yc["send_retry"] = 0
        yc["typed_n"] = 0
        return _act("tap", "yubo_card_send",
                    f"Tap the up arrow — Direct '{text}' to {yc.get('card') or 'this card'} "
                    f"({sent + 1}/{cap})", x=int(xy[0]), y=int(xy[1]))

    # ---- the deck ----
    if yubo_on_deck(ui_tree, _log=False):
        yc["recover"] = 0
        name = yubo_deck_card_name(ui_tree) or ""
        if phase in ("swipe", "awaiting_sent"):
            yc["phase"] = "await_next"
            yc["swiped_card"] = name
            yc["swipes"] = 1
            return _like_swipe(name, int(yc.get("cards") or 0))
        if phase == "await_next":
            if name and name == yc.get("swiped_card"):
                n = int(yc.get("swipes") or 1)
                if n == 1:
                    yc["swipes"] = 2
                    return _act("wait", "yubo_card_wait_next",
                                f"Waiting for the next card after {name}",
                                seconds=1.0, delay_s=1.0)
                if n == 2:
                    yc["swipes"] = 3
                    return _like_swipe(name, int(yc.get("cards") or 0))
                return _act("fail", "yubo_card_stuck",
                            f"Card {name} did not move after 2 swipes — stop")
            yc["phase"] = phase = "open"
            if sent >= cap:
                return plan_yubo_card_first_contact(
                    instruction, ui_tree, history, state=st, package=package,
                    dry_run=dry_run, message=message, target=target)
        # open this card's send box — never more than N up-arrow taps in total
        cards = int(yc.get("cards") or 0)
        attempts = int(yc.get("attempts") or 0)
        if attempts >= cap or cards >= cap + 5:
            return _act("done", "yubo_card_no_more",
                        f"Yubo: {sent}/{cap} confirmed after {attempts} sends — stop "
                        f"({yc.get('unconfirmed') or 0} without a sent signal; never "
                        f"more than {cap} sends)",
                        stopped_reason="unconfirmed_sends")
        yc["cards"] = cards + 1
        yc["card"] = name
        yc["typed_n"] = 0
        xy = _pill(ui_tree)
        return _act("tap", "yubo_card_open_send",
                    f"Open {name or 'this card'}'s Send a message box", x=xy[0], y=xy[1])

    # ---- elsewhere (Chat list, a conversation, another app) → deck tab ----
    n = int(yc.get("recover") or 0) + 1
    yc["recover"] = n
    if n > MAX_RECOVER:
        return _act("fail", "yubo_card_lost",
                    f"Could not get back to the Yubo deck after {MAX_RECOVER} tries")
    pkgs = re.search(r'packages="([^"]*)"', ui_tree or "")
    if (ui_tree or "").strip() and pkgs and PKG not in pkgs.group(1):
        return _act("open_app", "yubo_card_open_app", "Open Yubo", app="Yubo", package=PKG)
    if phase == "awaiting_sent":
        return _act("wait", "yubo_card_wait_sent",
                    f"Waiting for the sent message to show (screen {n})",
                    seconds=1.0, delay_s=1.0)
    return _act("tap", "yubo_card_deck_tab",
                f"Open the Yubo deck tab (never Conversations) — try {n}",
                x=DECK_TAB_XY[0], y=DECK_TAB_XY[1])
