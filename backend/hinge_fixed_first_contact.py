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
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
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
)
PHOTO_HEART_XY = (937, 1356)
# Heart Y ladder (25 Nov 2026): the heart sits at the bottom-right of the
# visible photo/prompt, whose height varies by card — measured from Mac's
# 24 Nov video: 1010 (short top photo), 1356 (23 Nov map), 1790 (tall
# first photo). X is stable at 937 on all three.
PHOTO_HEART_X = 937
PHOTO_HEART_LADDER = (PHOTO_HEART_XY[1], 1010, 1790)
SEND_LIKE_XY = (686, 1277)
COMMENT_XY = (540, 1102)
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


def allowed_message(text: str) -> str:
    raw = (text or "").strip()
    low = raw.lower()
    for phrase in MESSAGE_BANK:
        if low == phrase:
            return phrase
    # Exact text Mac gave in the instruction is allowed.
    if raw:
        return raw
    return MESSAGE_BANK[0]


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


def _on_likes_you(tree: str) -> bool:
    blob = _low(tree)
    if "likes you" in blob:
        return True
    if "upgrade to hingex" in blob and "boost" in blob and not hinge_on_like_sheet(tree):
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
        (str(n.get("label") or n.get("text") or "").strip().lower(), int(n.get("y") or 0))
        for n in nodes
    ]
    top = {lab for lab, y in labels if 0 < y < 300}
    blob = " ".join(lab for lab, _y in labels)
    # 1:1 thread: a Message composer near the bottom, no Discover sheet
    for n in nodes:
        lab = str(n.get("label") or n.get("desc") or n.get("hint") or "").lower()
        if n.get("editable") and ("message" in lab or "type" in lab) and "send a message" not in blob:
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
            send["reason"] = (
                f"Hinge Send Like {reason_suffix} — never Rose ({planner})"
            )
            send["planner"] = planner
            return send
    return _fp(
        {
            "action": "tap",
            "x": SEND_LIKE_XY[0],
            "y": SEND_LIKE_XY[1],
            "reason": (
                f"Hinge Send Like {reason_suffix} (map xy) "
                f"— never Rose ({planner})"
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
        f"Leave Hinge Likes You (Boost/HingeX showing) → Discover "
        f"({planner})"
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

    # Off the sheet: any post-send / per-profile state is stale (the sheet
    # closed = the like went through, or this is a new profile). Clear it
    # so a stale just_sent can never make the next profile wait and Back
    # out of its sheet instead of typing.
    if not hinge_on_like_sheet(ui_tree):
        bulk.pop("just_sent", None)
        bulk.pop("closing", None)
        bulk["type_tries"] = 0
        bulk["focus_tries"] = 0
        bulk["send_retry"] = 0

    # On the sheet the heart ladder already did its job — reset it for the
    # next profile. (Never reset it off the sheet: the ladder only advances
    # while the sheet stays closed.)
    if hinge_on_like_sheet(ui_tree):
        bulk["heart_tries"] = 0
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

    text = allowed_message(message)

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

    if on_sheet and hinge_on_like_sheet(ui_tree):
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
    bulk["heart_tries"] = tries + 1
    bulk["awaiting_sheet"] = True
    bulk["typed"] = False
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
