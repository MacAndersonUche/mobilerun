"""Hinge first-contact: photo-heart → comment → free Send Like (never Rose).

Verified on the S21+ (1080x2400), 23 Nov 2026:
  Da  — comment "hey how are you" + Send Like (686, 1277)
  Presh — comment "hi miss" + Send Like (686, 1277)

Discover often has an empty a11y tree, so the heart tap uses the photo-heart
map instead of per-card vision. Prompt-heart Y moves with prompt length and
is not used. The like sheet itself has a11y.

The photo heart's X is stable (937) but its Y moves with the photo: 1010 on
a short top photo, 1356 on the 23 Nov card, 1790 on a tall first photo
(Mac's 24 Nov video, frames scene_003/004). A single fixed Y misses the
heart on most cards — the live run (25 Nov 00:49) tapped (937, 1356) three
times, no sheet ever opened, and the executor's same-decision guard stopped
the run ("Fixed swipe stuck ... not on deck"). So the heart is tried down
a short ladder, one position per cycle, and the run fails honestly when the
ladder is exhausted instead of repeating the same tap.

Video (24 Nov 2026, Mac by hand): after Send Like a "Send a Rose
instead?" sheet can appear — dismiss it with "Send Like anyway", never
"Send a Rose" and never the rose icon next to Send Like. The "Send Like
anyway" tap is tree-resolved only: the map Send Like coords sit between
the Rose button and the anyway link on that sheet, so a map fallback
there could tap Rose.

Blind sheet (25 Nov 2026, Mac watching his phone): the comment box
opened, nothing was typed, the box closed. The sheet had opened but
the tree stayed blind, so the planner fell through to the heart ladder
and re-tapped the heart on the open sheet — which closes it. A heart
tap that opened the sheet sets awaiting_sheet; while that is set and
the tree is blind, the planner never re-taps the heart: it waits once
for the sheet to render, then focuses the comment composer at its map
position (bounded). As soon as the tree shows the box, the normal
verified type/send runs. If the box never appears, it fails honestly
— never blind-type, never blind-send, because the IME path accepts
text unverified and the tree is the only read-back.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _compose_editable,
        _fp,
        _parse_compact_nodes,
        _tree_node_center,
        compose_box_focused,
        compose_box_text,
        hinge_dismiss_enable_prompt,
        hinge_dismiss_play_review,
        hinge_find_compose,
        hinge_like_sheet_action,
        hinge_on_like_sheet,
        hinge_open_discover_tab,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _compose_editable,
        _fp,
        _parse_compact_nodes,
        _tree_node_center,
        compose_box_focused,
        compose_box_text,
        hinge_dismiss_enable_prompt,
        hinge_dismiss_play_review,
        hinge_find_compose,
        hinge_like_sheet_action,
        hinge_on_like_sheet,
        hinge_open_discover_tab,
    )

PLANNER = "hinge_fixed_first_contact_no_llm_handoff"
MESSAGE_BANK = (
    "hey how are you",
    "hi miss",
    "hello miss",
    "good morning",
    "good evening beautiful",
)
PHOTO_HEART_XY = (937, 1356)
# Heart Y ladder: the heart sits at the bottom-right of the visible
# photo, whose height varies by card. 25 Nov 2026 (Mac's 24 Nov video):
# 1010 (short top photo), 1356 (23 Nov map), 1790 (tall first photo).
# 27 Nov 2026 live (S21+): 1356 hit Kelly and Hephzibah; Tronella's
# "Signals" banner sat the heart at ~1528, so 1356 missed. X is 937.
# 1790 is last: on a short card it is near the prompt row — only used
# after earlier rungs (and a vision miss) show the sheet is not open.
PHOTO_HEART_X = 937
PHOTO_HEART_LADDER = (PHOTO_HEART_XY[1], 1528, 1180, 1010, 1680, 1790)
SEND_LIKE_XY = (686, 1277)
COMMENT_XY = (540, 1102)
# r53: inline like panel — "Add a comment" box centre below the photo heart
# (27 Nov 2026 S21+: heart (937, 1356) → box [94,1476][984,1647]).
COMMENT_BELOW_HEART = 200
DISCOVER_TAB_XY = (110, 2195)
ROSE_BOUNDS = (95, 1225, 355, 1330)

# Full paywalls / rose confirms — Back, never tap. On-card chrome such as
# the Dating Intent chip must not abort. Likes You "Boost" / "Upgrade to
# HingeX" is handled by switching to Discover, not by aborting.
_PAYWALL_SHEETS = (
    "send a rose instead",
    "are you sure you want to send a rose",
    "hinge+ is required",
    "subscribe to hinge",
    "get hinge+",
)


def allowed_message(
    text: str,
    state: Optional[Dict[str, Any]] = None,
    *,
    profile_name: str = "",
    store: Optional[Dict[str, Any]] = None,
) -> str:
    """Portal opener library first; MESSAGE_BANK if library empty/unreachable.

    When ``store`` (bulk_message_new) is given, the line is stuck on
    ``store['text']`` for that person so every planner step reuses it.
    Hinge types via Honeyboard, so only keyable lines are chosen.
    """
    try:
        from mobilerun.dating.openers import sticky_first_contact_text
    except ImportError:  # pragma: no cover
        from dating.openers import sticky_first_contact_text  # type: ignore
    if isinstance(store, dict):
        return sticky_first_contact_text(
            store,
            fallback_bank=MESSAGE_BANK,
            message=text,
            state=state if isinstance(state, dict) else None,
            package_name="co.hinge.app",
            profile_name=profile_name or None,
            require_keyable=True,
        )
    try:
        from mobilerun.dating.openers import pick_runner_first_contact_text
    except ImportError:  # pragma: no cover
        from dating.openers import pick_runner_first_contact_text  # type: ignore
    return pick_runner_first_contact_text(
        fallback_bank=MESSAGE_BANK,
        message=text,
        state=state if isinstance(state, dict) else None,
        package_name="co.hinge.app",
        profile_name=profile_name or None,
        require_keyable=True,
    )


def _clear_stuck_text(bulk: Dict[str, Any]) -> None:
    try:
        from mobilerun.dating.openers import clear_sticky_opener
    except ImportError:  # pragma: no cover
        from dating.openers import clear_sticky_opener  # type: ignore
    clear_sticky_opener(bulk)


HINGE_PKG = "co.hinge.app"


def _foreign_tree(tree: str) -> str:
    """Package of a tree that is not Hinge's ('' when it is Hinge's or
    unknown). Uses the hierarchy ``packages`` attribute only."""
    m = re.search(r'\bpackages="([^"]*)"', tree or "")
    if not m:
        return ""
    pkgs = [p.strip() for p in m.group(1).split(",") if p.strip()]
    if not pkgs or HINGE_PKG in pkgs:
        return ""
    # System UI alone (notification shade / IME) is not a foreign app
    if all(
        p in ("com.android.systemui", "com.samsung.android.honeyboard") for p in pkgs
    ):
        return ""
    return pkgs[0]


def in_rose_bounds(x: int, y: int) -> bool:
    x0, y0, x1, y1 = ROSE_BOUNDS
    return x0 <= int(x) <= x1 and y0 <= int(y) <= y1


def _low(tree: str) -> str:
    return (tree or "").lower()


def _deck_readable(ui_tree: str) -> bool:
    """True when the tree carries any readable node (a name, a label, an
    id): the Discover deck has loaded. An empty tree means Hinge's a11y
    is blank or the deck is still loading — the caller waits instead of
    tapping the heart into a screen that has not rendered yet."""
    try:
        nodes = _parse_compact_nodes(ui_tree)
    except Exception:
        return False
    return any(
        (n.get("text") or n.get("label") or n.get("desc") or n.get("id") or "").strip()
        for n in nodes
    )


def _sheet_open(tree: str, bulk: Dict[str, Any]) -> bool:
    """The like sheet is up: detected in the tree, or the comment box is
    present while a heart tap is outstanding. Hinge's sheet usually has
    a11y, but on a sparse tree only the focused comment EditText may
    show — that is still the sheet, and the planner must type into it,
    not re-tap the heart."""
    if hinge_on_like_sheet(tree):
        return True
    if _is_thread(tree):
        return False
    if bulk.get("awaiting_sheet"):
        try:
            return _compose_editable(tree) is not None
        except Exception:
            return False
    return False


def _on_likes_you(tree: str) -> bool:
    blob = _low(tree)
    if "likes you" in blob:
        return True
    if (
        "upgrade to hingex" in blob
        and "boost" in blob
        and not hinge_on_like_sheet(tree)
    ):
        return True
    return False


def _off_discover(tree: str) -> Optional[str]:
    """r45: which non-Discover Hinge screen is showing (None = Discover/unknown)."""
    if not (tree or "").strip() or hinge_on_like_sheet(tree):
        return None
    try:
        from dm_heuristics import _parse_compact_nodes as _pc
    except ImportError:  # pragma: no cover
        from backend.dm_heuristics import _parse_compact_nodes as _pc  # type: ignore
    nodes = _pc(tree)
    labels = [
        (
            str(n.get("label") or n.get("text") or "").strip().lower(),
            int(n.get("y") or 0),
        )
        for n in nodes
    ]
    top = {lab for lab, y in labels if 0 < y < 300}
    blob = " ".join(lab for lab, _y in labels)
    # r53 (27 Nov 2026): Megan's existing chat ("Ask them out" / "End the
    # chat" / "Press and hold to reply") was read as the like sheet and
    # "hello how are you" was typed into it. Those markers are a 1:1 thread.
    if _is_thread(tree):
        return "thread"
    # 1:1 thread: a Message composer near the bottom, no Discover sheet
    for n in nodes:
        lab = str(n.get("label") or n.get("desc") or n.get("hint") or "").lower()
        if (
            n.get("editable")
            and ("message" in lab or "type" in lab)
            and "send a message" not in blob
        ):
            return "thread"
    if "matches" in top or "your turn" in blob or "their turn" in blob:
        return "Matches"
    if "standouts" in top:
        return "Standouts"
    if "likes you" in blob:
        return "Likes You"
    if {"edit profile", "preview"} & top or "my profile" in blob:
        return "Profile"
    return None


_THREAD_MARKERS = (
    "ask them out",
    "end the chat",
    "press and hold to reply",
    "send a message",
)


def _is_thread(tree: str) -> bool:
    """An existing Hinge chat (never a first-contact target)."""
    if hinge_on_like_sheet(tree):
        return False
    blob = " ".join(
        f"{n.get('text') or ''} {n.get('desc') or ''} {n.get('label') or ''} {n.get('hint') or ''}"
        for n in _parse_compact_nodes(tree or "")
    ).lower()
    if any(m in blob for m in _THREAD_MARKERS[:3]):
        return True
    if " you: " in f" {blob} " and "send a message" in blob:
        return True
    return False


def _discover_tab_executed(history: List[str]) -> bool:
    """The Discover tab tap really ran (an executed ``tap(x,y) — …`` entry),
    not just planned — a stuck-recovery wait or a firewall soft-skip can
    replace it, and the planner must not assume it is on Discover."""
    for h in history[-12:]:
        hl = str(h).lower()
        if hl.startswith("tap(") and "discover tab" in hl:
            return True
    return False


def _on_rose_popup(tree: str) -> bool:
    """The "Send a Rose instead?" sheet: Rose button + "Send Like anyway"."""
    blob = _low(tree)
    return "send a rose instead" in blob and "send like anyway" in blob


def _rose_popup_anyway(tree: str, planner: str) -> Optional[Dict[str, Any]]:
    """Tree-resolved "Send Like anyway" tap — None when it is not in the
    tree, so the caller Backs out instead of guessing map coords on a
    sheet where the Rose button sits next to the anyway link."""
    xy = _tree_node_center(tree, "Send Like anyway", "Send like anyway")
    if not xy:
        return None
    return _fp(
        {
            "action": "tap",
            "x": int(xy[0]),
            "y": int(xy[1]),
            "reason": (
                f"Hinge Rose popup — Send Like anyway (never Send a Rose) "
                f"({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_fixed_fc_rose_anyway",
    )


def _on_paywall_sheet(tree: str) -> bool:
    blob = _low(tree)
    if hinge_on_like_sheet(tree) and "send a rose instead" not in blob:
        return False
    return any(p in blob for p in _PAYWALL_SHEETS)


def _send_like_action(tree: str, planner: str, reason_suffix: str) -> Dict[str, Any]:
    """Send Like tap from the tree (or the verified map fallback) — never Rose.

    Does not touch done/typed: the caller counts the send. A tree Send Like
    that resolves inside the Rose bounds is never tapped; the verified map
    coords (686, 1277) are used instead.
    """
    send = hinge_like_sheet_action(tree, planner=planner)
    if send:
        sx, sy = int(send.get("x") or 0), int(send.get("y") or 0)
        if not in_rose_bounds(sx, sy):
            send["reason"] = f"Hinge Send Like {reason_suffix} — never Rose ({planner})"
            send["planner"] = planner
            return send
    return _fp(
        {
            "action": "tap",
            "x": SEND_LIKE_XY[0],
            "y": SEND_LIKE_XY[1],
            "reason": (
                f"Hinge Send Like {reason_suffix} (map xy) " f"— never Rose ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_fixed_fc_send_xy",
    )


def _leave_likes_you(bulk: Dict[str, Any], planner: str) -> Dict[str, Any]:
    """Tap the Discover tab to leave Likes You — bounded. If the tab tap
    never lands, fail honestly instead of tapping it every cycle until the
    executor's same-decision guard stops the run."""
    tries = int(bulk.get("_likes_you_tries") or 0) + 1
    bulk["_likes_you_tries"] = tries
    if tries > 3:
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Hinge still on Likes You after {tries - 1} Discover "
                    f"tab taps — stop, nothing sent ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_likes_you_fail",
        )
    act = hinge_open_discover_tab(planner=planner)
    act["reason"] = (
        f"Leave Hinge Likes You (Boost/HingeX showing) → Discover " f"({planner})"
    )
    return act


def plan_hinge_fixed_first_contact(
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
    """Plan one first-contact step. No vision / LLM handoff."""
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message_new",
        {"done": 0, "typed": False, "awaiting_sheet": False, "skipped": []},
    )
    done = int(bulk.get("done") or 0)
    if done >= max(1, int(target or 1)):
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Hinge first-contact finished {done}/{target} "
                    f"— never Rose ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
            },
            "hinge_fixed_fc_done",
        )

    # r53 (27 Nov 2026, task_4e04f0f22cca5077): right after Hinge opened,
    # the phone served the cached Samsung launcher tree (same 6385 bytes,
    # "cached": true) while Hinge's Matches tab was on screen. The planner
    # read the launcher's search box as the comment field, tapped the
    # "heart" into Matches and then "focused" (540, 437) — a match row.
    # A tree from another app is stale: wait for Hinge's own tree, then
    # reopen Hinge (bounded). Never tap Hinge coordinates off a foreign tree.
    foreign = _foreign_tree(ui_tree)
    if foreign:
        n_f = int(bulk.get("_foreign_n") or 0) + 1
        bulk["_foreign_n"] = n_f
        st["bulk_message_new"] = bulk
        if n_f > 6:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Hinge never showed its own screen (still {foreign}) "
                        f"— stop, nothing sent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_foreign_fail",
            )
        if n_f % 3 == 0:
            return _fp(
                {
                    "action": "open_app",
                    "app": "Hinge",
                    "package": HINGE_PKG,
                    "reason": (
                        f"Screen still reads {foreign}, not Hinge — reopen "
                        f"Hinge ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_foreign_open",
            )
        return _fp(
            {
                "action": "wait",
                "seconds": 1.5,
                "delay_s": 1.5,
                "reason": (
                    f"Tree is from {foreign}, not Hinge (stale) — wait for "
                    f"Hinge's screen, never tap off it ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_foreign_wait",
        )
    bulk.pop("_foreign_n", None)

    # The deck has rendered at least once: a later blind tree means the
    # like sheet (or a render gap), not a deck that never loaded. The
    # blind-sheet recovery below is gated on this — a heart tap into a
    # deck that never rendered cannot have opened a sheet.
    if _deck_readable(ui_tree):
        bulk["_deck_seen"] = True

    # Off the sheet: any post-send / per-profile state is stale (the sheet
    # closed = the like went through, or this is a new profile). Clear it
    # so a stale just_sent can never make the next profile wait and Back
    # out of its sheet instead of typing.
    if not _sheet_open(ui_tree, bulk):
        had_send = bool(bulk.get("just_sent") or bulk.get("closing"))
        bulk.pop("just_sent", None)
        bulk.pop("closing", None)
        bulk["type_tries"] = 0
        bulk["focus_tries"] = 0
        bulk["send_retry"] = 0
        if had_send:
            # The send went through and the sheet closed: the next card
            # needs a moment to render. Re-arm the deck wait so the
            # next heart tap does not fire into an empty screen and burn
            # a ladder rung on a card that is not there yet.
            bulk.pop("_discover_waited", None)

    # On the sheet the heart ladder already did its job — reset it for the
    # next profile. (Never reset it off the sheet: the ladder only advances
    # while the sheet stays closed.)
    if _sheet_open(ui_tree, bulk):
        bulk["heart_tries"] = 0
        bulk.pop("_sheet_waited", None)
        bulk.pop("_blind_focus_tries", None)
    # No longer on Likes You — the leave-Likes-You counter resets too.
    if not _on_likes_you(ui_tree):
        bulk.pop("_likes_you_tries", None)

    play = hinge_dismiss_play_review(ui_tree, planner=planner)
    if play:
        return play
    popup = hinge_dismiss_enable_prompt(ui_tree, planner=planner)
    if popup:
        return popup

    if _on_likes_you(ui_tree) and not hinge_on_like_sheet(ui_tree):
        return _leave_likes_you(bulk, planner)

    text = allowed_message(message, state=st, store=bulk)

    # Video flow: the "Send a Rose instead?" sheet appears after Send Like.
    # Dismiss it with "Send Like anyway" — never "Send a Rose". The sheet
    # is handled here, ahead of the generic paywall Back, because Back
    # would abandon the like instead of confirming it as a free like.
    # Dry runs fall through to the sheet block below (no taps).
    if not dry_run and _on_rose_popup(ui_tree):
        anyway = _rose_popup_anyway(ui_tree, planner)
        if anyway is None:
            # No tree node for the anyway link: Back out rather than
            # guess map coords next to the Rose button.
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Hinge Rose popup without a Send Like anyway node "
                        f"— Back, never guess near Rose ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_rose_back",
            )
        if str(bulk.get("_bc") or "") in ("send_tapped", "probe"):
            # r53 blind compose: Send Like (with the verified comment) was
            # tapped and Hinge asks "Send a Rose instead?" — confirm the
            # free like with "Send Like anyway" and count it now.
            bulk["done"] = done + 1
            bulk.update(
                {
                    "_bc": "",
                    "typed": False,
                    "awaiting_sheet": False,
                    "heart_tries": 0,
                    "_blind_focus_tries": 0,
                    "_bc_wait": 0,
                }
            )
            _clear_stuck_text(bulk)
            bulk.pop("_sheet_waited", None)
            bulk.pop("_discover_waited", None)
            bulk.pop("_vision_last", None)
            st["bulk_message_new"] = bulk
            return anyway
        if bulk.get("just_sent") or bulk.get("closing"):
            # Send Like already went through and was counted — this tap
            # only confirms it as a free like. Never recount.
            bulk["closing"] = False
            st["bulk_message_new"] = bulk
            return anyway
        if compose_box_text(ui_tree).lower() == text.lower():
            # The comment is verified in the box: this tap IS the send.
            bulk["done"] = done + 1
            bulk["typed"] = False
            bulk["awaiting_sheet"] = False
            bulk["just_sent"] = True
            bulk["close_tries"] = 0
            bulk["type_tries"] = 0
            bulk["focus_tries"] = 0
            _clear_stuck_text(bulk)
            st["bulk_message_new"] = bulk
            return anyway
        # Popup before typing: do not send a bare like — Back to the
        # sheet and type first.
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Hinge Rose popup before the comment was typed — Back "
                    f"to the sheet, never send a bare like ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_rose_back",
        )

    if _on_paywall_sheet(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Hinge paid sheet showing — Back, never tap Rose/"
                    f"HingeX/Boost ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_paywall_back",
        )

    on_sheet = hinge_on_like_sheet(ui_tree) or bool(bulk.get("awaiting_sheet"))
    # Prefer a11y when the like sheet is actually in the tree.
    if hinge_on_like_sheet(ui_tree):
        on_sheet = True
        bulk["awaiting_sheet"] = True
        st["bulk_message_new"] = bulk

    if on_sheet and _sheet_open(ui_tree, bulk):
        if dry_run:
            bulk["done"] = target
            bulk["typed"] = True
            bulk["awaiting_sheet"] = False
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] Hinge like/comment sheet verified; "
                        f"would send '{text}' — never typed, never Rose "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "would_send_text": text,
                },
                "hinge_fixed_fc_dry_sheet",
            )
        # The comment, from the tree — never from history. Send Like is
        # only tapped when the exact line is verified in the box.
        box = compose_box_text(ui_tree)
        # Already sent once for this profile but the line is still in the
        # box: the Send Like tap missed. One more Send Like tap, never a
        # retype, never a recount — then fail honestly.
        if (bulk.get("just_sent") or bulk.get("closing")) and (
            box.lower() == text.lower()
        ):
            if int(bulk.get("send_retry") or 0) < 1:
                bulk["send_retry"] = 1
                bulk["just_sent"] = True
                bulk["closing"] = False
                bulk["close_tries"] = 0
                bulk["typed"] = False
                bulk["awaiting_sheet"] = False
                st["bulk_message_new"] = bulk
                return _send_like_action(
                    ui_tree,
                    planner,
                    f"again (comment still in the box) {done}/{target}",
                )
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Hinge comment did not send after a retry "
                        f"— stop, nothing paid ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_not_sent",
            )
        # Already sent for this profile and the box is empty: the sheet is
        # closing. Do not re-type on it — wait, then Back out (bounded).
        if bulk.get("just_sent"):
            bulk["just_sent"] = False
            bulk["closing"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "wait",
                    "seconds": 1.0,
                    "delay_s": 1.0,
                    "reason": (
                        f"Send Like tapped — waiting for the sheet to close "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_wait_close",
            )
        if bulk.get("closing"):
            tries = int(bulk.get("close_tries") or 0) + 1
            bulk["close_tries"] = tries
            st["bulk_message_new"] = bulk
            if tries > 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Hinge like sheet did not close after Send Like "
                            f"— stop ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hinge_fixed_fc_close_fail",
                )
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Send Like tapped — dismiss the sheet ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_close_back",
            )
        if box.lower() == text.lower():
            send = _send_like_action(
                ui_tree, planner, f"first-contact {done + 1}/{target}"
            )
            bulk["done"] = done + 1
            bulk["typed"] = False
            bulk["awaiting_sheet"] = False
            bulk["just_sent"] = True
            bulk["close_tries"] = 0
            bulk["type_tries"] = 0
            bulk["focus_tries"] = 0
            _clear_stuck_text(bulk)
            st["bulk_message_new"] = bulk
            return send
        # The line is not in the box yet: focus it first (tree-verified,
        # not history), then paste it in one commit — never chunked
        # human-paced typing on Discover. Bounded: after 2 failed types,
        # stop honestly.
        if not compose_box_focused(ui_tree):
            compose = hinge_find_compose(ui_tree)
            tries = int(bulk.get("focus_tries") or 0) + 1
            bulk["focus_tries"] = tries
            st["bulk_message_new"] = bulk
            if tries > 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Hinge comment field never took focus "
                            f"— stop, nothing sent ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hinge_fixed_fc_focus_fail",
                )
            xy = compose or COMMENT_XY
            return _fp(
                {
                    "action": "tap",
                    "x": int(xy[0]),
                    "y": int(xy[1]),
                    "reason": f"Focus Add a comment field ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_focus_comment",
            )
        tries = int(bulk.get("type_tries") or 0)
        if tries >= 2:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Hinge comment never landed in the box after 2 tries "
                        f"— stop, nothing sent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_type_fail",
            )
        bulk["type_tries"] = tries + 1
        bulk["typed"] = True
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "type",
                "text": text,
                "reason": (
                    f"Type like-sheet comment '{text}' (paste, one commit) "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "clear": True,
                "humanize": False,
            },
            "hinge_fixed_fc_type",
        )

    # The sheet may be open but the tree blind. A heart tap that opened
    # the sheet sets awaiting_sheet; if the next tree is empty, the old
    # code fell through to the heart ladder and re-tapped the heart on
    # the open sheet — which closes it (Mac watched exactly this on
    # 25 Nov 2026: the comment box opened, nothing was typed, the box
    # closed). Never re-tap the heart while the sheet may be open:
    # wait once for it to render, then focus the comment composer at
    # its map position (bounded). As soon as the tree shows the box,
    # the sheet block above takes over and the normal verified
    # type/send runs. If the box never appears, fail honestly — never
    # blind-type, never blind-send. Gated on _deck_seen: a heart tap
    # into a deck that never rendered cannot have opened a sheet, so
    # that case still falls through to the ladder below.
    # r53 blind compose (27 Nov 2026, Mac watching): Hinge's inline like
    # panel is Compose with no semantics — the comment box, Send Like and
    # Rose never appear in the tree, even with the keyboard up. The box was
    # opened and focused but nothing was typed. With the keyboard up after
    # the focus tap: type the exact text (the phone reads the field back
    # and fails the type if it did not land), confirm on a screenshot that
    # the box shows exactly that text, then tap Send Like at its keyboard-up
    # spot (686, 1277) — the Rose button is at x <= 355 on that row and is
    # never tapped. The send counts only when the panel closes.
    bc = _blind_compose_step(ui_tree, history, bulk, st, text, planner)
    if bc is not None:
        return bc

    # r53: Discover is blind on the S21+ today, so _deck_seen never set and
    # a heart tap that DID open the inline panel fell through to the next
    # ladder rung (1010, then 1790 — next to the Send Like row: a bare-like
    # risk). A Discover tab tap that really ran counts as the deck seen.
    if _discover_tab_executed(history):
        bulk["_deck_seen"] = True
    if (
        bulk.get("awaiting_sheet")
        and bulk.get("_deck_seen")
        and not _deck_readable(ui_tree)
    ):
        # r53n (27 Nov 2026, Tronella): an empty tree is not proof the
        # like sheet is open. The heart tap at 1356 missed (Signals
        # banner sat the heart at ~1528); the tree stayed empty with no
        # keyboard, and the old path assumed a sheet and gave up without
        # trying the rest of the ladder. A keyboard-up tree, or a
        # screenshot that shows the comment/Send Like panel, is the
        # evidence the sheet opened. A screenshot of the Discover card
        # (no panel) is a heart miss — clear awaiting_sheet and continue
        # the ladder. Never re-tap the heart while vision says the
        # panel is open (that closes it: 25 Nov).
        sheet_vis = _vision_answer(bulk, "hinge_sheet_open")
        kb_up = _keyboard_up(ui_tree)
        if sheet_vis is False and not kb_up:
            bulk["awaiting_sheet"] = False
            bulk.pop("_sheet_waited", None)
            bulk.pop("_blind_focus_tries", None)
            bulk.pop("_sheet_vision_tries", None)
            bulk.pop("_vision_last", None)
            st["bulk_message_new"] = bulk
            # Fall through to the next heart-Y rung.
        elif not bulk.get("_sheet_waited"):
            bulk["_sheet_waited"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "wait",
                    "seconds": 1.0,
                    "delay_s": 1.0,
                    "reason": (
                        f"Hinge like sheet may be open but the tree is "
                        f"blind — wait for it to render ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "_vision_check": _SHEET_OPEN_VISION,
                    "_vision_tag": "hinge_sheet_open",
                },
                "hinge_fixed_fc_blind_sheet_wait",
            )
        elif sheet_vis is False and not kb_up:
            # Already handled above; keep the branch exhaustive.
            pass
        elif kb_up or sheet_vis is True or sheet_vis is None:
            # Sheet is open (keyboard or vision YES), or vision has not
            # answered yet. If vision is still unknown after the wait,
            # stay conservative: focus the composer, never re-tap the
            # heart (25 Nov: re-tapping closed the open sheet).
            tries = int(bulk.get("_blind_focus_tries") or 0) + 1
            bulk["_blind_focus_tries"] = tries
            st["bulk_message_new"] = bulk
            if tries > 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Hinge like sheet opened but the comment box "
                            f"never appeared in the tree — stop, nothing "
                            f"sent ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hinge_fixed_fc_blind_sheet_fail",
                )
            # r53 (27 Nov 2026, Mac watching): on today's Discover the like
            # panel opens inline under the photo — "Add a comment" sits ~200px
            # below the photo heart that opened it, with the Rose + Send Like
            # row below that. The old fixed COMMENT_XY (540, 1102) was on the
            # photo, so the box opened but was never focused or typed into.
            # Focus relative to the heart rung that opened the panel; the
            # Rose row is far lower (heart_y + ~380) and is never tapped here.
            hy = int(bulk.get("_heart_y") or 0)
            fy = min(2050, hy + COMMENT_BELOW_HEART) if hy else COMMENT_XY[1]
            return _fp(
                {
                    "action": "tap",
                    "x": COMMENT_XY[0],
                    "y": fy,
                    "reason": (
                        f"Focus Add a comment composer — like sheet open "
                        f"but tree blind ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_blind_focus",
            )

    # Not on the like sheet — leave Likes You / Standouts, then tap the
    # photo heart. Never vision, never Dating Intent / Rewind / Rose.
    if _on_likes_you(ui_tree):
        return _leave_likes_you(bulk, planner)

    if dry_run:
        bulk["done"] = target
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"[DRY RUN] would tap photo heart {PHOTO_HEART_XY} → "
                    f"type '{text}' → Send Like {SEND_LIKE_XY} to "
                    f"{target} new profiles — never typed, never Rose "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "dry_run_verified": True,
                "would_send_text": text,
            },
            "hinge_fixed_fc_dry_discover",
        )

    hist = " ".join(history[-16:]).lower()
    if "discover" not in hist and "photo heart" not in hist and "likes you" not in hist:
        # First live step: land on Discover even if the tree is empty.
        if not bulk.get("_opened_discover"):
            bulk["_opened_discover"] = True
            st["bulk_message_new"] = bulk
            act = hinge_open_discover_tab(planner=planner)
            return act
    # r53: the first Discover tab tap was planned but never ran (the
    # executor's stuck recovery replaced it with a wait; Hinge stayed on
    # Matches, whose tree is blind, and the photo-heart ladder then tapped
    # a match row). On a blind tree, re-issue the tab tap until history
    # shows it executed (bounded) before any heart tap.
    if (
        bulk.get("_opened_discover")
        and not _deck_readable(ui_tree)
        and not _discover_tab_executed(history)
        and not bulk.get("awaiting_sheet")
        and int(bulk.get("done") or 0) == 0
        and int(bulk.get("heart_tries") or 0) == 0
    ):
        n_tab = int(bulk.get("_tab_retry") or 0) + 1
        bulk["_tab_retry"] = n_tab
        st["bulk_message_new"] = bulk
        if n_tab > 4:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Hinge Discover tab tap never ran — stop before "
                        f"any blind heart tap, nothing sent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_tab_fail",
            )
        act = hinge_open_discover_tab(planner=planner)
        act["reason"] = (
            f"Open Hinge Discover tab again — the last tap did not run " f"({planner})"
        )
        return act

    # r45 (Mac: "stuck in Matches, doesn't click the Discover H"): off
    # Discover → a chat thread backs out; Matches / Standouts / Profile tap
    # the H tab (leftmost). Never the blind photo-heart tap there (it opened
    # a match row). Capped, no AI.
    off = _off_discover(ui_tree)
    if off:
        n = int(bulk.get("_recover_n") or 0) + 1
        bulk["_recover_n"] = n
        st["bulk_message_new"] = bulk
        if n > 10:
            return _fp(
                {
                    "action": "fail",
                    "reason": f"Hinge could not get back to Discover after 10 tries — stop ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_recover_fail",
            )
        if off == "thread":
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Hinge chat open — Back out, then Discover ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hinge_fixed_fc_thread_back",
            )
        act = hinge_open_discover_tab(planner=planner)
        act["reason"] = f"Hinge on {off} — tap the H Discover tab ({planner})"
        return act
    bulk["_recover_n"] = 0

    # The deck needs a moment after the Discover tab tap: the live run
    # tapped the heart straight into a still-loading screen. Wait once —
    # but only when the tree shows nothing at all (a loaded deck, with
    # card nodes, is tapped straight away).
    if (
        bulk.get("_opened_discover")
        and not bulk.get("_discover_waited")
        and not _deck_readable(ui_tree)
    ):
        bulk["_discover_waited"] = True
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "wait",
                "seconds": 1.5,
                "delay_s": 1.5,
                "reason": (
                    f"Hinge Discover tab tapped — wait for the deck to load "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_discover_wait",
        )

    # Photo heart down the ladder: one position per cycle, verified by the
    # sheet opening. Never repeat the same tap — the old code tapped
    # (937, 1356) every cycle and the executor stopped the run at x3.
    tries = int(bulk.get("heart_tries") or 0)
    if tries >= len(PHOTO_HEART_LADDER):
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Hinge photo heart did not open the like sheet after "
                    f"{tries} positions {PHOTO_HEART_LADDER} — card layout "
                    f"changed or not on the Discover deck, stop ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hinge_fixed_fc_heart_fail",
        )
    heart_y = PHOTO_HEART_LADDER[tries]
    bulk["_heart_y"] = heart_y
    bulk["heart_tries"] = tries + 1
    bulk["awaiting_sheet"] = True
    bulk["typed"] = False
    bulk.pop("_sheet_waited", None)
    bulk.pop("_blind_focus_tries", None)
    bulk.pop("_sheet_vision_tries", None)
    bulk.pop("_vision_last", None)
    st["bulk_message_new"] = bulk
    return _fp(
        {
            "action": "tap",
            "x": PHOTO_HEART_X,
            "y": heart_y,
            "reason": (
                f"Hinge Discover photo heart ({PHOTO_HEART_X}, {heart_y}) "
                f"to open like sheet — try {tries + 1}/{len(PHOTO_HEART_LADDER)} ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "hinge_fixed_fc_photo_heart",
    )


# Re-export map so tests and profiles stay in one place.
HINGE_FIXED_MAP = {
    "photo_heart_xy": PHOTO_HEART_XY,
    "photo_heart_ladder": PHOTO_HEART_LADDER,
    "send_like_xy": SEND_LIKE_XY,
    "comment_xy": COMMENT_XY,
    "discover_tab_xy": DISCOVER_TAB_XY,
    "rose_button_bounds": ROSE_BOUNDS,
}


def _keyboard_up(tree: str) -> bool:
    m = re.search(r'\bpackages="([^"]*)"', tree or "")
    pk = m.group(1) if m else ""
    return "honeyboard" in pk or "inputmethod" in pk


def _vision_answer(bulk: Dict[str, Any], tag: str) -> Optional[bool]:
    """YES/NO from the last screenshot check, or None if missing/failed.

    An empty raw string is a failed call, not a NO — never treat that
    as evidence the sheet is (or is not) open.
    """
    vlast = (
        bulk.get("_vision_last") if isinstance(bulk.get("_vision_last"), dict) else {}
    )
    if vlast.get("tag") != tag:
        return None
    if not str(vlast.get("raw") or "").strip():
        return None
    return bool(vlast.get("ok"))


# r53n: screenshot questions. YES = the like/comment panel is visible.
_SHEET_OPEN_VISION = (
    "Hinge dating app screenshot. Is the like/comment panel open under the "
    "photo — an 'Add a comment' (or typed comment) text box with a 'Send Like' "
    "button and a small rose button? If you only see a Discover profile card "
    "(filters, photo, no comment box), answer NO. Reply YES or NO only."
)
_PANEL_OPEN_VISION = (
    "Hinge dating app screenshot. Is the comment text box and the 'Send Like' "
    "button still visible under the photo? If a new Discover profile card is "
    "showing and the comment panel is gone, answer NO. Reply YES or NO only."
)


def _blind_compose_step(
    ui_tree: str,
    history: List[str],
    bulk: Dict[str, Any],
    st: Dict[str, Any],
    text: str,
    planner: str,
) -> Optional[Dict[str, Any]]:
    """Type → screenshot-verify → Send Like on Hinge's blind inline panel."""
    phase = str(bulk.get("_bc") or "")
    base = {"planner": planner, "llm_provider": None}
    if hinge_on_like_sheet(ui_tree) or _is_thread(ui_tree):
        return None  # readable sheet → normal verified path; thread → Back
    try:
        hinge_edit = _compose_editable(ui_tree) is not None
    except Exception:
        hinge_edit = False
    kb = _keyboard_up(ui_tree)
    vlast = (
        bulk.get("_vision_last") if isinstance(bulk.get("_vision_last"), dict) else {}
    )

    def _fail(why: str, step: str) -> Dict[str, Any]:
        bulk["_bc"] = "failed"
        st["bulk_message_new"] = bulk
        return _fp(
            {
                **base,
                "action": "fail",
                "reason": f"{why} — stop, nothing more sent ({planner})",
            },
            step,
        )

    if phase == "failed":
        return _fail("Hinge blind compose already failed", "hinge_fixed_fc_bc_failed")

    if not phase:
        # r53 (live 27 Nov 2026, Aaliyah): the photo heart opens the inline
        # panel with "Add a comment" already focused and the keyboard up —
        # no separate focus tap needed. Keyboard up after the heart = focused.
        if not (bulk.get("awaiting_sheet") and kb and not hinge_edit):
            return None
        bulk["_bc"] = "typed"
        bulk["typed"] = True
        st["bulk_message_new"] = bulk
        # r53 (live 27 Nov 2026): a11y SET_TEXT cannot reach Hinge's comment
        # box (no node), so type it on the on-screen keyboard key by key.
        # Never lower_first / Shift: the empty Add-a-comment box already
        # sentence-shifts; an extra Shift tap cycles to CAPS LOCK (28 Nov).
        return _fp(
            {
                **base,
                "action": "type_keys",
                "text": text,
                "clear_keys": 24,
                "lower_first": False,
                "humanize": False,
                "reason": f"Type Hinge comment '{text}' on the keyboard into the focused "
                f"Add a comment box (inline panel, tree blind) ({planner})",
            },
            "hinge_fixed_fc_bc_type",
        )

    if phase == "typed":
        landed = any(
            str(h).lower().startswith(f'typed "{text.lower()}"') for h in history[-4:]
        )
        if not landed:
            return _fail(
                f"Hinge comment '{text}' did not land in the box",
                "hinge_fixed_fc_bc_type_fail",
            )
        if not kb:
            return _fail(
                "Keyboard closed before Send Like — comment box lost focus",
                "hinge_fixed_fc_bc_kb_lost",
            )
        bulk["_bc"] = "send_tapped"
        bulk.pop("_vision_last", None)
        st["bulk_message_new"] = bulk
        return _fp(
            {
                **base,
                "action": "tap",
                "x": SEND_LIKE_XY[0],
                "y": SEND_LIKE_XY[1],
                "label": "Send Like",
                "reason": f"Hinge Send Like with comment '{text}' verified on screen "
                f"— never Rose ({planner})",
                "_vision_check": (
                    "Hinge dating app screenshot. Under the photo there is a comment text box, "
                    "and below it a small rose button and a wide 'Send Like' button. Does the "
                    f'comment text box contain the typed words "{text}" (ignore capitalisation, '
                    "underlines and the cursor)? Reply YES or NO only."
                ),
                "_vision_gate": True,
                "_vision_tag": "hinge_comment_typed",
            },
            "hinge_fixed_fc_bc_send",
        )

    def _probe_after_send() -> Dict[str, Any]:
        # Keyboard gone, or vision shows the comment panel has closed
        # (the tree can still list honeyboard after the deck has already
        # advanced — 27 Nov, Hephzibah). Probe for a Rose upsell, then count.
        bulk["_bc"] = "probe"
        bulk.pop("_vision_last", None)
        st["bulk_message_new"] = bulk
        return _fp(
            {
                **base,
                "action": "wait",
                "seconds": 0.5,
                "delay_s": 0.5,
                "reason": f"Send Like tapped — check the screen for a Rose popup ({planner})",
                "_vision_check": (
                    "This is a Hinge dating app screenshot. Is a popup or sheet visible "
                    "that offers to send a Rose (for example 'Send a Rose instead?' or a "
                    "'Send Like anyway' link)? Reply YES or NO only."
                ),
                "_vision_tag": "hinge_rose_probe",
            },
            "hinge_fixed_fc_bc_probe",
        )

    if phase == "send_tapped":
        if vlast.get("tag") == "hinge_comment_typed" and not vlast.get("ok"):
            return _fail(
                f"Screenshot did not show '{text}' in the comment box, Send Like "
                f"not tapped",
                "hinge_fixed_fc_bc_verify_fail",
            )
        if _on_rose_popup(ui_tree):
            return None  # tree-resolved "Send Like anyway" handled by caller
        # r53n: do not fail "panel stayed open" just because a stale tree
        # still lists the keyboard. A screenshot of the next Discover card
        # (comment panel gone) means the like went through.
        panel_vis = _vision_answer(bulk, "hinge_panel_open")
        if panel_vis is False:
            return _probe_after_send()
        if kb or panel_vis is True:
            n = int(bulk.get("_bc_wait") or 0) + 1
            bulk["_bc_wait"] = n
            st["bulk_message_new"] = bulk
            if n > 2 and panel_vis is True:
                return _fail(
                    "Send Like tapped but the comment panel stayed open",
                    "hinge_fixed_fc_bc_not_sent",
                )
            if n > 3 and panel_vis is None:
                return _fail(
                    "Send Like tapped but the comment panel stayed open",
                    "hinge_fixed_fc_bc_not_sent",
                )
            return _fp(
                {
                    **base,
                    "action": "wait",
                    "seconds": 1.5,
                    "delay_s": 1.5,
                    "reason": f"Send Like tapped — waiting for the panel to close ({planner})",
                    "_vision_check": _PANEL_OPEN_VISION,
                    "_vision_tag": "hinge_panel_open",
                },
                "hinge_fixed_fc_bc_wait",
            )
        # Keyboard gone: confirm on the screenshot it was not a Rose upsell
        return _probe_after_send()

    if phase == "probe":
        if vlast.get("tag") == "hinge_rose_probe" and vlast.get("ok"):
            return _fail(
                "Hinge showed a Rose popup after Send Like and it is not in the "
                "screen tree — left for you, never tapped near Rose",
                "hinge_fixed_fc_bc_rose",
            )
        done = int(bulk.get("done") or 0) + 1
        bulk.update(
            {
                "done": done,
                "_bc": "",
                "typed": False,
                "awaiting_sheet": False,
                "heart_tries": 0,
                "_blind_focus_tries": 0,
                "_bc_wait": 0,
            }
        )
        _clear_stuck_text(bulk)
        bulk.pop("_sheet_waited", None)
        bulk.pop("_discover_waited", None)
        bulk.pop("_vision_last", None)
        st["bulk_message_new"] = bulk
        return _fp(
            {
                **base,
                "action": "wait",
                "seconds": 1.5,
                "delay_s": 1.5,
                "reason": f"Hinge comment like sent {done} — panel closed, next card "
                f"loading ({planner})",
            },
            "hinge_fixed_fc_bc_sent",
        )
    return None
