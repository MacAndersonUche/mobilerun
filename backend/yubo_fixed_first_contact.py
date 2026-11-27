"""Yubo first-contact to new friends (empty 'Say hello' threads).

Verified on the S21+ (1080x2400), 23 Nov 2026:
  bethany — "hey how are you" sent, yellow check, Chat preview
            "You: hey how are you · now". Yubucks stayed 150.
  K       — "hello miss" sent, yellow check.

Route: Chat tab → New friends tile (never Reactions / Infinity / Yubucks /
gift / rocket) → type a message-bank line in Aa → send at (1008, 1336).
If the deck 'Send a message' sheet appears, select Direct first; never
send while Blast is selected.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        yubo_direct_sheet_action,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        yubo_direct_sheet_action,
    )

PLANNER = "yubo_fixed_first_contact_no_llm_handoff"
MESSAGE_BANK = (
    "hey how are you",
    "hi miss",
    "hello miss",
    "good morning",
    "good evening beautiful",
)
CHAT_TAB_XY = (341, 2194)
SEND_XY = (1008, 1336)
DIRECT_SEND_XY = (985, 1336)
YUBUCKS_XY = (840, 158)
ROCKET_XY = (1000, 2000)
_SKIP_TILES = {
    "reactions",
    "new friends",
    "conversations",
    "chat",
    "likes",
    "friends",
    "more",
    "yubucks",
}


def allowed_message(text: str) -> str:
    raw = (text or "").strip()
    low = raw.lower()
    for phrase in MESSAGE_BANK:
        if low == phrase:
            return phrase
    if raw:
        return raw
    return MESSAGE_BANK[0]


def _blob(tree: str) -> str:
    return (tree or "").lower()


def _on_say_hello(tree: str) -> bool:
    return "say hello to" in _blob(tree)


def _on_chat_list(tree: str) -> bool:
    blob = _blob(tree)
    return "new friends" in blob or (
        "conversations" in blob and "say hello to" not in blob
    )


def _on_paywall(tree: str) -> bool:
    blob = _blob(tree)
    return (
        any(
            n in blob
            for n in (
                "unlock infinity",
                "infinity pack",
                "launch a hypersurge",
                "get up to x10 more messages",
            )
        )
        and "say hello to" not in blob
        and not _on_chat_list(tree)
    )


_BLAST_MARKERS = (
    "message tons of new people",
    "super blast",
)


def blast_selected(tree: str) -> bool:
    """r45: the 'Send a message' sheet with paid Blast (Yubucks) selected.

    Blast selected shows the 'Message tons of new people at once' line and
    the 50+/100+/200+ reach chips (the tile also shows 'Blast · 490').
    """
    blob = _blob(tree)
    if "blast" not in blob:
        return False
    if "message tons of new people" in blob:
        return True
    return "50+" in blob and "100+" in blob


def composer_text(tree: str) -> str:
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            return (n.get("text") or "").strip()
    return ""


def _composer(tree: str) -> Optional[Tuple[int, int]]:
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            return (int(n["x"]), int(n["y"]))
    return None


def _send_right_of_composer(tree: str) -> Optional[Tuple[int, int]]:
    """Purple up-arrow just to the right of the composer, level with it.

    27 Nov prod: a Samsung Keyboard key at ~(1013, 1469) also sits to the
    right and slightly below the box. The old scan took the last matching
    node, so Direct sends missed the arrow (y~1335) and the text stayed
    in the box.
    """
    edit = None
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            edit = n
    if not edit:
        return None
    ex2 = edit.get("x2")
    ey1, ey2 = edit.get("y1"), edit.get("y2")
    if ex2 is None or ey1 is None or ey2 is None:
        return SEND_XY
    mid_y = (int(ey1) + int(ey2)) / 2
    best = None
    best_score = None
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        x1, y1, x2, y2 = n.get("x1"), n.get("y1"), n.get("x2"), n.get("y2")
        if None in (x1, y1, x2, y2):
            continue
        if int(x1) < int(ex2) - 20:
            continue
        # Must overlap the composer vertically. A keyboard key just
        # below the box (y≈1465 on the S21+) is not the arrow.
        if int(y2) < int(ey1) or int(y1) > int(ey2):
            continue
        w = int(x2) - int(x1)
        h = int(y2) - int(y1)
        if w > 250 or h > 250:
            continue
        cx, cy = int(n["x"]), int(n["y"])
        score = abs(cy - mid_y)
        if best_score is None or score < best_score:
            best_score = score
            best = (cx, cy)
    return best


def _first_new_friend(tree: str) -> Optional[Tuple[int, int]]:
    nodes = _parse_compact_nodes(tree)
    conv_y = None
    for n in nodes:
        t = (n.get("text") or n.get("label") or "").strip().lower()
        if t == "conversations":
            conv_y = int(n.get("y") or n.get("y1") or 0)
            break
    for n in nodes:
        t = (n.get("text") or n.get("label") or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in _SKIP_TILES or "infinity" in low or "hypersurge" in low:
            continue
        if "get up to" in low or "message" in low:
            continue
        y = int(n.get("y") or 0)
        if conv_y is not None and y >= conv_y:
            continue
        # New friends carousel sits above Conversations / the infinity banner.
        if y < 200 or y > 900:
            continue
        return (int(n["x"]), int(n["y"]))
    return None


def plan_yubo_fixed_first_contact(
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
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message_new",
        {"done": 0, "typed": False},
    )
    done = int(bulk.get("done") or 0)
    cap = max(1, int(target or 1))
    if done >= cap:
        return _fp(
            {
                "action": "done",
                "reason": f"Yubo first-contact finished {done}/{cap} ({planner})",
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
            },
            "yubo_fixed_fc_done",
        )

    if _on_paywall(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Yubo paid sheet (Infinity/HyperSurge) — Back, never "
                    f"Continue ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "stopped_reason": "paywall",
            },
            "yubo_fixed_fc_paywall_back",
        )

    # r45: confirm the last Send actually went before counting it.
    pending = str(bulk.get("awaiting_sent") or "")
    if pending:
        left = composer_text(ui_tree).lower()
        if left and left == pending.lower() and not blast_selected(ui_tree):
            tries = int(bulk.get("send_retry") or 0)
            if tries < 1:
                bulk["send_retry"] = tries + 1
                send = _send_right_of_composer(ui_tree) or SEND_XY
                if send not in (YUBUCKS_XY, ROCKET_XY):
                    return _fp(
                        {
                            "action": "tap",
                            "x": int(send[0]),
                            "y": int(send[1]),
                            "reason": f"Yubo Send again — '{pending}' still in the box ({planner})",
                            "planner": planner,
                            "llm_provider": None,
                        },
                        "yubo_fixed_fc_send_retry",
                    )
            bulk["awaiting_sent"] = ""
            bulk["send_retry"] = 0
            bulk["typed"] = False
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Yubo message did not send ('{pending}' still in the "
                        f"box after retry) — stop, nothing paid ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_fixed_fc_not_sent",
            )
        if left == pending.lower() and blast_selected(ui_tree):
            pass  # handled by the Direct guard below (nothing was sent)
        else:
            done += 1
            bulk["done"] = done
            bulk["awaiting_sent"] = ""
            bulk["send_retry"] = 0
            bulk["typed"] = False
            bulk["_close_sheet"] = True
            st["bulk_message_new"] = bulk
            if done >= cap:
                return _fp(
                    {
                        "action": "done",
                        "reason": f"Yubo first-contact finished {done}/{cap} ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": bool(dry_run),
                    },
                    "yubo_fixed_fc_done",
                )

    # r45: never send while paid Blast is selected — pick Direct (max 3).
    if blast_selected(ui_tree):
        n_sel = int(bulk.get("direct_tries") or 0) + 1
        bulk["direct_tries"] = n_sel
        st["bulk_message_new"] = bulk
        if n_sel > 3:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Yubo sheet stays on paid Blast after 3 Direct taps "
                        f"— stop, nothing sent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_fixed_fc_blast_stop",
            )
        sel = yubo_direct_sheet_action(ui_tree, planner=planner)
        if not sel:
            # Detector thinks Direct is selected but Blast markers remain
            sel = _fp(
                {
                    "action": "tap",
                    "x": 855,
                    "y": 655,
                    "reason": f"Select Direct (Blast is paid) ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_select_direct",
            )
        sel["planner"] = planner
        return sel
    bulk["direct_tries"] = 0

    select_direct = yubo_direct_sheet_action(ui_tree, planner=planner)
    if select_direct:
        select_direct["planner"] = planner
        return select_direct

    text = allowed_message(message)
    on_direct = "direct" in _blob(ui_tree) and "blast" in _blob(ui_tree)
    on_hello = _on_say_hello(ui_tree) or (
        _composer(ui_tree) is not None and "say hello" in _blob(ui_tree)
    )

    # r45: after a confirmed Direct send, close the sheet (Back) instead of
    # typing again to the same person; then carry on to the next contact.
    if bulk.get("_close_sheet") and on_direct and not composer_text(ui_tree):
        bulk["_close_sheet"] = False
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Yubo message sent — close the send sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "yubo_fixed_fc_close_sheet",
        )
    if not on_direct:
        bulk["_close_sheet"] = False

    if on_hello or on_direct:
        if dry_run:
            bulk["done"] = cap
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] Yubo first-contact composer verified; "
                        f"would send '{text}' — never typed, never Blast/"
                        f"Yubucks ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "would_send_text": text,
                },
                "yubo_fixed_fc_dry",
            )
        # PR #83 rule, every app (video, 24 Nov 2026): Send only when the
        # exact line is verified in the box. A type that never landed
        # retypes (bounded) — it must never reach Send.
        box = composer_text(ui_tree)
        if not bulk.get("typed") or box.lower() != text.lower():
            tries = int(bulk.get("type_tries") or 0)
            if tries >= 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Yubo first-contact never landed in the box "
                            f"after 2 tries — stop, nothing sent ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "yubo_fixed_fc_type_fail",
                )
            bulk["type_tries"] = tries + 1
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "type",
                    "text": text,
                    "reason": f"Type Yubo first-contact '{text}' ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "clear": True,
                },
                "yubo_fixed_fc_type",
            )
        bulk["type_tries"] = 0
        send = _send_right_of_composer(ui_tree) or (
            DIRECT_SEND_XY if on_direct else SEND_XY
        )
        if send == YUBUCKS_XY or send == ROCKET_XY:
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": f"Refuse Yubo paid send coords ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_fixed_fc_refuse_paid",
            )
        if blast_selected(ui_tree):  # belt and braces — never a paid send
            return _fp(
                {
                    "action": "fail",
                    "reason": f"Yubo Blast selected at send — refuse ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_fixed_fc_refuse_blast",
            )
        bulk["awaiting_sent"] = text
        bulk["send_retry"] = 0
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": int(send[0]),
                "y": int(send[1]),
                "reason": (
                    f"Yubo Send first-contact {done + 1}/{cap} "
                    f"— never Blast/Yubucks ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "yubo_fixed_fc_send",
        )

    if dry_run and _on_chat_list(ui_tree):
        bulk["done"] = cap
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"[DRY RUN] would open a New friends tile → type "
                    f"'{text}' → Send to {cap} new contacts — never typed, "
                    f"never Reactions/Infinity/Yubucks ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "dry_run_verified": True,
                "would_send_text": text,
            },
            "yubo_fixed_fc_dry_list",
        )

    if _on_chat_list(ui_tree) and not dry_run:
        tile = _first_new_friend(ui_tree)
        if tile:
            bulk["typed"] = False
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": int(tile[0]),
                    "y": int(tile[1]),
                    "reason": (
                        f"Open Yubo New friends contact for first-contact "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "yubo_fixed_fc_open_friend",
            )
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Yubo New friends has no remaining first-contact tiles "
                    f"after {done}/{cap} ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "stopped_reason": "no_more_targets",
            },
            "yubo_fixed_fc_no_targets",
        )

    # Deck or elsewhere — open Chat (new friends). Never Yubucks / rocket.
    return _fp(
        {
            "action": "tap",
            "x": CHAT_TAB_XY[0],
            "y": CHAT_TAB_XY[1],
            "reason": f"Open Yubo Chat tab for new friends ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "yubo_fixed_fc_chat_tab",
    )
