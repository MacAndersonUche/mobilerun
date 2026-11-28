"""r46: Hily fixed run — "Likes only" or "Message + likes". No LLM, never paid.

Mac (24 Nov / 28 Nov): auto-like from the **Finder** tab (not Discover).
Message + likes:
  1. Activity → Likes sent → envelope → message tab → send a message-bank
     line; repeat until M messages sent (existing first-contact route).
  2. Then free hearts in Finder for ``likes_to_do = max(0, L - M)`` cards.
Likes-only: Finder hearts only, up to L.

Instructions (dating_run):
  ``fixed hily likes L``              — Likes only (L Finder hearts)
  ``fixed hily message M likes L``    — Message + likes (M msgs, L-M hearts)

Coordinates (S21+ 1080x2400):
  Finder tab   ``bottomNavTab_1`` (142, 2190) — id from the Finder map; the
               xy fallback matches the 24 Nov screenshot nav row, not tapped
               live by this planner yet.
  Free Like    ``ActionButton_LIKE`` (750, 1959) — verified map (never CRUSH 540,1959)
  Activity tab (740, 2190), Likes sent (900, 265), envelope ``chat_request``,
  MBM send ``sendMessageButton`` (980, 1329) — verified 23 Nov (Shann, Charlotte).
The message part reuses ``plan_hily_fixed_first_contact`` (send confirm,
allowance 0 → stop, paywall → Back, never Crush) with its Discover fallback
switched off: when Likes sent has no envelopes left the message phase ends
and any remaining Finder likes still run.

Deck recovery (25 Nov 2026): the Finder tab tap is at the right coords
(verified against Mac's 24 Nov video: the tab sits at (142, 2190)), but
the live run tapped it 3x and the deck never appeared — the planner
re-tapped every cycle with no wait, so the executor's same-decision guard
stopped the run before the deck could load. Recovery is now a bounded
ladder — tab, wait, Back, tab, wait — then an honest fail naming the
screen state, never the same tap twice in a row.
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
        hily_on_top_picks_grid,
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
        hily_on_top_picks_grid,
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

# Finder recovery ladder, one rung per cycle (25 Nov 2026): the rungs are
# deliberately all different, so the executor's same-decision guard can
# never fire on recovery. n is the consecutive recovery count (1-based).
_FINDER_RECOVER_LADDER = (
    "tab",
    "wait",
    "back",
    "tab",
    "wait",
    "back",
    "tab",
    "wait",
    "back",
    "tab",
)

_RE = re.compile(r"\bfixed\s+hily\s+(?:message\s+(\d+)\s+)?likes\s+(\d+)", re.I)


def parse_hily_instruction(instruction: str) -> Optional[Tuple[int, int]]:
    """-> (messages, max_likes); messages 0 = Likes only."""
    m = _RE.search(instruction or "")
    if not m:
        return None
    msgs = min(MESSAGE_CAP, int(m.group(1) or 0))
    likes = min(MAX_LIKES, max(int(m.group(2)), msgs, 1))
    return msgs, likes


def likes_to_do(msgs: int, max_likes: int) -> int:
    """Finder free hearts after (or instead of) the message phase.

    Message + likes: max_likes is total people; messages come from Likes
    sent, so remaining hearts are ``max(0, max_likes - messages)``.
    Likes only (msgs=0): all max_likes are Finder hearts.
    """
    return max(0, int(max_likes) - int(msgs))


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


def _deck_not_loaded(tree: str) -> bool:
    """The Hily nav bar is up but no deck, chat list, composer or grid is
    readable: the Finder deck is still loading (or empty). This is the
    state the live run (25 Nov 00:52) was stuck in — ``finder_without_card_nodes``
    needs the filters button, which is absent while the screen loads, so
    the old code fell through to tapping the Finder tab every cycle. The
    caller waits once here instead of tapping; the heart is never tapped
    blind on an unreadable screen."""
    t = tree or ""
    if "bottomNavTab_1" not in t:
        return False
    if hily_on_finder(t, _log=False) or finder_without_card_nodes(t):
        return False
    if hily_on_mbm(t) or hily_on_chats_list(t) or hily_on_top_picks_grid(t):
        return False
    if hily_on_photo_viewer(t) or hily_on_profile_sheet(t):
        return False
    low = t.lower()
    if "chat_request" in low or "sendmessagebutton" in low or "textinput" in low:
        return False
    return True


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
    extra_likes = likes_to_do(msgs, max_likes)
    st = state if isinstance(state, dict) else {}
    # Message + likes: messages from Likes sent first, then Finder hearts
    # for likes_to_do = max(0, max_likes - messages). Do not treat the
    # message-phase "done" as the whole job finishing when hearts remain.
    hr = st.setdefault(
        "hily_run",
        {
            "likes": 0,
            "sent": 0,
            "phase": "message" if msgs else "likes",
        },
    )
    st["hily_run"] = hr
    # Legacy phase names from older runs / tests.
    if hr.get("phase") in ("likes1", "likes2"):
        hr["phase"] = "likes"
    likes = int(hr.get("likes") or 0)
    phase = str(hr.get("phase") or ("message" if msgs else "likes"))
    mode = "Message + likes" if msgs else "Likes only"

    if dry_run:
        dry_bits = []
        if msgs:
            dry_bits.append(f"send {msgs} messages from Likes sent")
        if extra_likes:
            dry_bits.append(f"like {extra_likes} in Finder")
        return _act(
            "done",
            "hily_run_dry",
            f"[DRY RUN] Hily {mode}: "
            + (", ".join(dry_bits) if dry_bits else f"like {max_likes} in Finder")
            + " - nothing tapped",
            True,
            dry_run_verified=True,
        )

    def _finish_reason() -> str:
        bits = [f"Hily {mode} finished"]
        if msgs:
            bits.append(hr.get("msg_end") or f"sent {int(hr.get('sent') or 0)}/{msgs}")
        bits.append(f"{likes}/{extra_likes} Finder likes")
        if hr.get("match_msgs"):
            bits.append(f"{hr.get('match_msgs')} match messages")
        return ": ".join(bits[:1]) + (
            (" - " + ", ".join(bits[1:])) if len(bits) > 1 else ""
        )

    # Message phase: delegate to the verified Likes-sent → envelope planner
    if phase == "message":
        fc_state = hr.setdefault("fc", {})
        bulk = fc_state.setdefault("bulk_message_new", {"done": 0, "typed": False})
        bulk["_via_discover"] = False  # never Discover (Mac: Likes sent only)
        a = plan_hily_fixed_first_contact(
            "send %d first contact messages on hily" % msgs,
            ui_tree,
            list(history or []),
            state=fc_state,
            dry_run=False,
            message=message,
            target=msgs,
        )
        # Opener pick lives on nested fc_state — promote so the job records
        # last_opener_template_id / opener_library (was empty on phone).
        try:
            from mobilerun.dating.openers import promote_opener_state
        except ImportError:  # pragma: no cover
            from dating.openers import promote_opener_state  # type: ignore
        promote_opener_state(fc_state, st)
        sent = int(bulk.get("done") or 0)
        hr["sent"] = sent
        step = str((a or {}).get("fastpath_step") or "")
        out_of_targets = step in (
            "hily_fixed_fc_to_discover",
            "hily_fixed_fc_no_targets",
            "hily_fixed_fc_discover_none",
        )
        stopped = (a or {}).get("stopped_reason") in (
            "allowance_exhausted",
            "paywall_done",
        )
        if (
            a is None
            or (a.get("action") == "done")
            or out_of_targets
            or (stopped and a.get("action") != "press_button")
        ):
            hr["msg_end"] = f"sent {sent}/{msgs}" + (
                " (no more Likes-sent envelopes)" if out_of_targets else ""
            )
            # Message "done" must not end the job when Finder likes remain.
            if extra_likes > 0 and likes < extra_likes:
                hr["phase"] = "likes"
                hr["recover"] = 0
                return plan_hily_fixed_run(
                    instruction,
                    ui_tree,
                    history,
                    state=st,
                    dry_run=dry_run,
                    message=message,
                )
            hr["phase"] = "finished"
            return _act("done", "hily_run_done", _finish_reason(), False)
        return _mark(a)

    if phase == "finished":
        return _act("done", "hily_run_done", _finish_reason(), False)

    # Finder like phase: target is likes_to_do (0 when max_likes == messages).
    target_likes = extra_likes
    if target_likes <= 0 or likes >= target_likes:
        hr["phase"] = "finished"
        return _act("done", "hily_run_done", _finish_reason(), False)

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
    if _is_paywall(ui_tree) or (
        hily_on_profile_sheet(ui_tree) and not hily_on_mbm(ui_tree)
    ):
        _drop_unverified_like(hr)
        return _act(
            "press_button",
            "hily_run_sheet_back",
            "Close Hily paid/Crush sheet — Back, nothing bought",
            False,
            button="back",
        )

    on_finder = hily_on_finder(ui_tree, _log=False)
    bare_finder = not on_finder and finder_without_card_nodes(ui_tree)
    if on_finder or bare_finder:
        hr["recover"] = 0
        hr.pop("_deck_waited", None)  # deck loaded — the loading wait resets
        hr.pop("match", None)  # r49: back on Finder — match popup finished
        if hr.get("awaiting_like"):
            hr["awaiting_like"] = False
            likes += 1
            hr["likes"] = likes
            if likes >= target_likes:
                return plan_hily_fixed_run(
                    instruction,
                    ui_tree,
                    history,
                    state=st,
                    dry_run=dry_run,
                    message=message,
                )
        like = hily_like_action(ui_tree, planner=PLANNER) if on_finder else None
        if bare_finder:
            # Card still loading? wait once, then use the verified heart xy
            if not hr.get("bare_waited"):
                hr["bare_waited"] = True
                return _act(
                    "wait",
                    "hily_run_wait_card",
                    "Hily Finder card not in the screen tree yet — wait",
                    False,
                    seconds=1.5,
                    delay_s=1.5,
                )
            like = _act(
                "tap",
                "hily_run_fixed_like_swipe",
                "Hily Finder free heart (map xy, card not in tree)",
                False,
                x=LIKE_XY[0],
                y=LIKE_XY[1],
            )
        else:
            hr["bare_waited"] = False
        if like:
            hr["awaiting_like"] = True
            like["reason"] = (
                f"Hily Finder free heart {likes + 1}/{target_likes} ({PLANNER})"
            )
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
                return _act(
                    "fail",
                    "hily_run_lost",
                    f"Hily: could not get back to Finder after {MAX_RECOVER} tries "
                    f"({likes} likes)",
                    False,
                )
        if n_int <= 40:
            return ia

    # Deck still loading (or empty) — nav bar up, nothing readable. Wait
    # once for it to render instead of tapping the Finder tab into a
    # loading screen (live 25 Nov 00:52: tab tapped 3x, deck never came).
    if _deck_not_loaded(ui_tree) and not hr.get("_deck_waited"):
        hr["_deck_waited"] = True
        return _act(
            "wait",
            "hily_run_deck_wait",
            "Hily screen not readable yet — wait for the deck to load",
            False,
            seconds=1.5,
            delay_s=1.5,
        )

    # Not on Finder → bounded recovery ladder (tab, wait, Back, tab, wait,
    # ...): every rung is different, so the executor's same-decision guard
    # can never fire on recovery, and the run fails honestly naming the
    # screen instead of "Fixed swipe stuck ... not on deck".
    n = int(hr.get("recover") or 0) + 1
    hr["recover"] = n
    if n > MAX_RECOVER:
        return _act(
            "fail",
            "hily_run_lost",
            f"Hily: could not get back to Finder after {MAX_RECOVER} tries "
            f"({likes} likes) — Finder tab tapped, waited and Backed, "
            f"deck never appeared",
            False,
        )
    _drop_unverified_like(hr)  # r49: not Finder after the heart → not counted
    pkgs = re.search(r'packages="([^"]*)"', ui_tree or "")
    if (ui_tree or "").strip() and pkgs and PKG not in pkgs.group(1):
        return _act(
            "open_app", "hily_run_open", "Open Hily", False, app="Hily", package=PKG
        )
    rung = _FINDER_RECOVER_LADDER[(n - 1) % len(_FINDER_RECOVER_LADDER)]
    if rung == "wait":
        return _act(
            "wait",
            "hily_run_finder_wait",
            "Hily Finder tab tapped — wait for the deck to load",
            False,
            seconds=1.5,
            delay_s=1.5,
        )
    if rung == "back":
        return _act(
            "press_button",
            "hily_run_finder_back",
            "Hily Finder deck not showing — Back to clear the screen",
            False,
            button="back",
        )
    # rung == "tab": tap the Finder tab (tree-resolved, else the map xy).
    # The try number is in the reason so one tab tap never shares a
    # decision key with the next.
    tab_try = (n + 2) // 3
    c = _tree_id_center(ui_tree, "bottomNavTab_1", "id/bottomNavTab_1")
    if c:
        return _act(
            "tap",
            "hily_run_finder_tab",
            f"Open Hily Finder tab (try {tab_try})",
            False,
            x=int(c[0]),
            y=int(c[1]),
        )
    return _act(
        "tap",
        "hily_run_finder_tab_xy",
        f"Open Hily Finder tab (map xy, try {tab_try})",
        False,
        x=FINDER_TAB_XY[0],
        y=FINDER_TAB_XY[1],
    )
