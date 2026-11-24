"""r46: Hily fixed run — "Likes only" or "Message + likes". No LLM, never paid.

Mac (24 Nov): auto-like from the **Finder** tab (not Discover). Message +
likes: like N cards, then Activity → Likes sent → open each one → envelope →
message tab → send a message-bank line; repeat until N sent; then keep liking
in Finder up to the mode's max likes (the N likes count toward it).

Instructions (dating_run):
  ``fixed hily likes L``              — Likes only
  ``fixed hily message M likes L``    — Message + likes (L includes the M likes)

Coordinates (S21+ 1080x2400):
  Finder tab   ``bottomNavTab_1`` (142, 2190) — id from the Finder map; the
               xy fallback matches the 24 Nov screenshot nav row, not tapped
               live by this planner yet.
  Free Like    ``ActionButton_LIKE`` (750, 1959) — verified map (never CRUSH 540,1959)
  Activity tab (740, 2190), Likes sent (900, 265), envelope ``chat_request``,
  MBM send ``sendMessageButton`` (980, 1329) — verified 23 Nov (Shann, Charlotte).
The message part reuses ``plan_hily_fixed_first_contact`` (send confirm,
allowance 0 → stop, paywall → Back, never Crush) with its Discover fallback
switched off: when Likes sent has no envelopes left the message phase ends.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        _fp,
        _tree_id_center,
        hily_back_from_photo_viewer,
        hily_dismiss_popup,
        hily_like_action,
        hily_on_chats_list,
        hily_on_finder,
        hily_on_mbm,
        hily_on_photo_viewer,
        hily_on_profile_sheet,
    )
    from hily_fixed_first_contact import _is_paywall, plan_hily_fixed_first_contact
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp,
        _tree_id_center,
        hily_back_from_photo_viewer,
        hily_dismiss_popup,
        hily_like_action,
        hily_on_chats_list,
        hily_on_finder,
        hily_on_mbm,
        hily_on_photo_viewer,
        hily_on_profile_sheet,
    )
    from backend.hily_fixed_first_contact import (  # type: ignore
        _is_paywall,
        plan_hily_fixed_first_contact,
    )

try:
    from hily_interrupts import handle_interrupt, is_match_popup
    from hily_fixed_first_contact import allowed_message as _bank_text
except ImportError:  # pragma: no cover
    from backend.hily_interrupts import handle_interrupt, is_match_popup  # type: ignore
    from backend.hily_fixed_first_contact import (  # type: ignore
        allowed_message as _bank_text,
    )

PLANNER = "hily_fixed_run"
LIKE_XY = (750, 1959)  # verified S21 map; Crush (540,1959) is never tapped
PKG = "com.hily.app"
FINDER_TAB_XY = (142, 2190)
MAX_RECOVER = 10
MAX_LIKES = 500
MESSAGE_CAP = 5  # Hily free first messages per run

_RE = re.compile(
    r"\bfixed\s+hily\s+(?:message\s+(\d+)\s+)?likes\s+(\d+)", re.I
)


def parse_hily_instruction(instruction: str) -> Optional[Tuple[int, int]]:
    """-> (messages, max_likes); messages 0 = Likes only."""
    m = _RE.search(instruction or "")
    if not m:
        return None
    msgs = min(MESSAGE_CAP, int(m.group(1) or 0))
    likes = min(MAX_LIKES, max(int(m.group(2)), msgs, 1))
    return msgs, likes


def finder_without_card_nodes(tree: str) -> bool:
    """r47: the Finder screen whose card + buttons are not in the a11y tree.

    24 Nov 10:26 (task_5d7be3ad4bd4dc93): Hily was on Finder — header
    ``finderFiltersButton`` and the nav — but the card stack was an empty
    scroller with no ActionButton_LIKE / name nodes, so ``hily_on_finder``
    said no and the planner tapped the Finder tab 3× until the repeat guard
    stopped the run.
    """
    t = tree or ""
    if "finderFiltersButton" not in t or "bottomNavTab_1" not in t:
        return False
    low = t.lower()
    if "chat_request" in low or "sendmessagebutton" in low or "textinput" in low:
        return False
    return not (hily_on_chats_list(t) or hily_on_mbm(t))


def _act(kind: str, step: str, reason: str, dry_run: bool, **kw: Any) -> Dict[str, Any]:
    a = {
        "action": kind,
        "reason": f"{reason} ({PLANNER})",
        "planner": PLANNER,
        "llm_provider": None,
        "dry_run": bool(dry_run),
        "_no_llm_handoff": True,
    }
    a.update(kw)
    return _fp(a, step)


def _mark(a: Dict[str, Any]) -> Dict[str, Any]:
    a["planner"] = PLANNER
    a["_no_llm_handoff"] = True
    return a


def _drop_unverified_like(hr: dict) -> None:
    """r49 (Mac): a heart tap only counts when the very next screen is the Finder
    deck again. Anything else (popup, notification, match, sheet, other app) means
    the tap may have hit that instead — drop it; the heart is tapped again on Finder."""
    if hr.get("awaiting_like"):
        hr["awaiting_like"] = False
        hr["unverified_likes"] = int(hr.get("unverified_likes") or 0) + 1


def plan_hily_fixed_run(
    instruction: str,
    ui_tree: str,
    history: Optional[List[str]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    message: str = "",
) -> Optional[Dict[str, Any]]:
    parsed = parse_hily_instruction(instruction)
    if not parsed:
        return None
    msgs, max_likes = parsed
    st = state if isinstance(state, dict) else {}
    hr = st.setdefault("hily_run", {"likes": 0, "sent": 0, "phase": "likes1"})
    st["hily_run"] = hr
    likes = int(hr.get("likes") or 0)
    phase = str(hr.get("phase") or "likes1")
    mode = "Message + likes" if msgs else "Likes only"

    if dry_run:
        return _act(
            "done", "hily_run_dry",
            f"[DRY RUN] Hily {mode}: would like {msgs or max_likes} in Finder"
            + (f", send {msgs} messages from Likes sent, then like up to {max_likes}"
               if msgs else "")
            + " — nothing tapped",
            True, dry_run_verified=True,
        )

    # Message phase: delegate to the verified Likes-sent → envelope planner
    if phase == "message":
        fc_state = hr.setdefault("fc", {})
        bulk = fc_state.setdefault("bulk_message_new", {"done": 0, "typed": False})
        bulk["_via_discover"] = False  # never Discover (Mac: Likes sent only)
        a = plan_hily_fixed_first_contact(
            "send %d first contact messages on hily" % msgs, ui_tree, list(history or []),
            state=fc_state, dry_run=False, message=message, target=msgs,
        )
        sent = int(bulk.get("done") or 0)
        hr["sent"] = sent
        step = str((a or {}).get("fastpath_step") or "")
        out_of_targets = step in ("hily_fixed_fc_to_discover", "hily_fixed_fc_no_targets",
                                  "hily_fixed_fc_discover_none")
        stopped = (a or {}).get("stopped_reason") in ("allowance_exhausted", "paywall_done")
        if a is None or (a.get("action") == "done") or out_of_targets:
            hr["phase"] = "likes2"
            hr["msg_end"] = (
                f"sent {sent}/{msgs}" + (" (no more Likes-sent envelopes)" if out_of_targets else "")
            )
            phase = "likes2"
        elif stopped and a.get("action") != "press_button":
            hr["phase"] = "likes2"
            phase = "likes2"
        else:
            return _mark(a)

    target_likes = msgs if (phase == "likes1" and msgs) else max_likes
    if likes >= target_likes and phase == "likes1" and msgs:
        hr["phase"] = "message"
        hr["recover"] = 0
        return plan_hily_fixed_run(instruction, ui_tree, history, state=st,
                                   dry_run=dry_run, message=message)
    if likes >= max_likes and phase != "likes1" or (not msgs and likes >= max_likes):
        return _act("done", "hily_run_done",
                    f"Hily {mode} finished: {likes}/{max_likes} likes"
                    + (f", {hr.get('match_msgs')} match messages" if hr.get("match_msgs") else "")
                    + (f", {hr.get('msg_end') or ('sent %d/%d' % (hr.get('sent', 0), msgs))}"
                       if msgs else ""),
                    False)

    # ---- Finder like phases ----
    # r49: a match popup (or the chat it opened) → free bank message first
    if is_match_popup(ui_tree) or (hr.get("match") or {}).get("open"):
        ia = handle_interrupt(ui_tree, hr, _bank_text(message), PLANNER)
        if ia:
            _drop_unverified_like(hr)
            return ia
    popup = hily_dismiss_popup(ui_tree, planner=PLANNER)
    if popup:
        _drop_unverified_like(hr)
        return _mark(popup)
    if hily_on_photo_viewer(ui_tree):
        _drop_unverified_like(hr)
        return _mark(hily_back_from_photo_viewer(planner=PLANNER))
    if _is_paywall(ui_tree) or (hily_on_profile_sheet(ui_tree) and not hily_on_mbm(ui_tree)):
        _drop_unverified_like(hr)
        return _act("press_button", "hily_run_sheet_back",
                    "Close Hily paid/Crush sheet — Back, nothing bought", False, button="back")

    on_finder = hily_on_finder(ui_tree, _log=False)
    bare_finder = not on_finder and finder_without_card_nodes(ui_tree)
    if on_finder or bare_finder:
        hr["recover"] = 0
        hr.pop("match", None)  # r49: back on Finder — match popup finished
        if hr.get("awaiting_like"):
            hr["awaiting_like"] = False
            likes += 1
            hr["likes"] = likes
            if phase == "likes1" and msgs and likes >= msgs:
                hr["phase"] = "message"
                return plan_hily_fixed_run(instruction, ui_tree, history, state=st,
                                           dry_run=dry_run, message=message)
            if likes >= max_likes:
                return plan_hily_fixed_run(instruction, ui_tree, history, state=st,
                                           dry_run=dry_run, message=message)
        like = hily_like_action(ui_tree, planner=PLANNER) if on_finder else None
        if bare_finder:
            # Card still loading? wait once, then use the verified heart xy
            if not hr.get("bare_waited"):
                hr["bare_waited"] = True
                return _act("wait", "hily_run_wait_card",
                            "Hily Finder card not in the screen tree yet — wait",
                            False, seconds=1.5, delay_s=1.5)
            like = _act("tap", "hily_run_fixed_like_swipe",
                        "Hily Finder free heart (map xy, card not in tree)", False,
                        x=LIKE_XY[0], y=LIKE_XY[1])
        else:
            hr["bare_waited"] = False
        if like:
            hr["awaiting_like"] = True
            like["reason"] = f"Hily Finder free heart {likes + 1}/{target_likes} ({PLANNER})"
            # same heart xy each card by design — exempt from same-tap stop
            like["fastpath_step"] = like["_fastpath_step"] = "hily_run_fixed_like_swipe"
            return _mark(like)

    # r49: notifications / popups / prompts over Finder → close, carry on
    ia = handle_interrupt(ui_tree, hr, _bank_text(message), PLANNER)
    if ia:
        n_int = int(hr.get("interrupts") or 0) + 1
        hr["interrupts"] = n_int
        _drop_unverified_like(hr)
        if ia.get("fastpath_step") == "hily_int_back":
            # blind Back on an unknown screen shares the lost-Finder budget
            nb = int(hr.get("recover") or 0) + 1
            hr["recover"] = nb
            if nb > MAX_RECOVER:
                return _act("fail", "hily_run_lost",
                            f"Hily: could not get back to Finder after {MAX_RECOVER} tries "
                            f"({likes} likes)", False)
        if n_int <= 40:
            return ia

    # Not on Finder → tap the Finder tab (never Back off the top screen)
    n = int(hr.get("recover") or 0) + 1
    hr["recover"] = n
    if n > MAX_RECOVER:
        return _act("fail", "hily_run_lost",
                    f"Hily: could not get back to Finder after {MAX_RECOVER} tries "
                    f"({likes} likes)", False)
    _drop_unverified_like(hr)  # r49: not Finder after the heart → not counted
    pkgs = re.search(r'packages="([^"]*)"', ui_tree or "")
    if (ui_tree or "").strip() and pkgs and PKG not in pkgs.group(1):
        return _act("open_app", "hily_run_open", "Open Hily", False, app="Hily", package=PKG)
    c = _tree_id_center(ui_tree, "bottomNavTab_1", "id/bottomNavTab_1")
    if c:
        return _act("tap", "hily_run_finder_tab", "Open Hily Finder tab", False,
                    x=int(c[0]), y=int(c[1]))
    if n % 3 == 0:
        return _act("press_button", "hily_run_back", "Back toward Hily Finder", False,
                    button="back")
    return _act("tap", "hily_run_finder_tab_xy", "Open Hily Finder tab (map xy)", False,
                x=FINDER_TAB_XY[0], y=FINDER_TAB_XY[1])
