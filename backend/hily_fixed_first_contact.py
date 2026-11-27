"""Hily first-contact: Message Before Match from Likes sent (daily cap 5).

Each message spends 1 Major Crush — a limited credit, not free (video,
24 Nov 2026: allowance 9 → 8 after one send). Only run it with Mac's
approval, and stop when the allowance hits 0.

Verified on the S21+ (1080x2400), 23 Nov 2026:
  Shann    — "hey how are you" via sendMessageButton (980, 1329)
  Charlotte — "hello miss" via sendMessageButton (980, 1329)
  Allowance: 9 → 8 after the first send.

Route: Activity (740, 2190) → Likes sent (900, 265) → chat_request
envelope → type a message-bank line → Send. Never tap deck Crush,
icebreakers, They liked you, Boost/rocket, or send when allowance is 0.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        _tree_id_center,
        hily_close_mbm,
        hily_dismiss_popup,
        hily_mbm_allowance,
        hily_on_mbm,
        hily_on_photo_viewer,
        hily_on_profile_sheet,
        hily_back_from_photo_viewer,
        hily_first_grid_tile_center,
        hily_on_chats_list,
        hily_on_top_picks_grid,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        _tree_id_center,
        hily_close_mbm,
        hily_dismiss_popup,
        hily_mbm_allowance,
        hily_on_mbm,
        hily_on_photo_viewer,
        hily_on_profile_sheet,
        hily_back_from_photo_viewer,
        hily_first_grid_tile_center,
        hily_on_chats_list,
        hily_on_top_picks_grid,
    )

PLANNER = "hily_fixed_first_contact_no_llm_handoff"
MESSAGE_BANK = (
    "hey how are you",
    "hi miss",
    "hello miss",
    "good morning",
)
DAILY_CAP = 5
ACTIVITY_TAB_XY = (740, 2190)
LIKES_SENT_XY = (900, 265)
SEND_XY = (980, 1329)
CLOSE_XY = (74, 160)
CRUSH_XY = (540, 1959)  # deck Major Crush — never
TEXT_INPUT_XY = (540, 1344)
DISCOVER_TAB_XY = (540, 2190)  # bottomNavTab_7 Discover


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


def _is_paywall(tree: str) -> bool:
    blob = _blob(tree)
    needles = (
        "upgrade to premium",
        "get premium",
        "buy credits",
        "out of messages",
        "subscribe",
        "unlock message",
    )
    return any(n in blob for n in needles)


def _on_likes_tab(tree: str) -> bool:
    """Activity → Likes (people who liked Mac): cards carry like/show, no envelopes.

    The "Likes sent" tab header is visible on every Activity tab, so the
    header alone never proves Likes sent is open (r53 live run: the run read
    the Likes tab as an empty Likes sent and finished 0/5).
    """
    if _first_chat_request(tree):
        return False
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or "").strip().lower()
        if d in ("like", "show") and n.get("clickable"):
            return True
    return False


def _on_likes_sent(tree: str, bulk: Optional[Dict[str, Any]] = None) -> bool:
    blob = _blob(tree)
    if not ("likes sent" in blob and "activity" in blob):
        return False
    if _first_chat_request(tree):
        return True
    if _on_likes_tab(tree):
        return False
    # No envelopes and no Likes-tab cards: only trust it once we tapped the tab
    return bool(bulk is None or bulk.get("_ls_tapped"))


def _on_activity(tree: str) -> bool:
    return "activity" in _blob(tree) and (
        "likes sent" in _blob(tree) or "visitors" in _blob(tree)
    )


def _message_sent_sheet(tree: str) -> bool:
    blob = _blob(tree)
    return "message sent" in blob or (
        hily_on_mbm(tree) and "message sent" in blob
    )


def _first_chat_request(tree: str) -> Optional[Tuple[int, int]]:
    for n in _parse_compact_nodes(tree):
        d = str(n.get("desc") or n.get("label") or "").strip().lower()
        nid = str(n.get("id") or "").lower()
        if d == "chat_request" or nid.endswith("chat_request") or d == "chat request":
            return (int(n["x"]), int(n["y"]))
    return None


def _send_center(tree: str) -> Optional[Tuple[int, int]]:
    c = _tree_id_center(
        tree,
        "sendMessageButton",
        "id/sendMessageButton",
        "com.hily.app:id/sendMessageButton",
    )
    return (int(c[0]), int(c[1])) if c else None


def plan_hily_fixed_first_contact(
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
    """Plan one Hily first-contact step. No vision / LLM handoff."""
    cap = min(DAILY_CAP, max(1, int(target or 1)))
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message_new",
        {"done": 0, "typed": False, "awaiting_sheet": False},
    )
    done = int(bulk.get("done") or 0)
    if done >= cap:
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Hily first-contact finished {done}/{cap} "
                    f"(daily cap {DAILY_CAP}) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
            },
            "hily_fixed_fc_done",
        )

    # Navigation landed — the tab-tap counters below reset. (25 Nov 2026:
    # the Activity / Likes-sent taps used to repeat every cycle when they
    # did not land, until the executor's same-decision guard stopped the
    # run. They are now bounded and fail honestly instead.)
    if _on_activity(ui_tree):
        bulk["_activity_tries"] = 0
    if _on_likes_sent(ui_tree, bulk):
        bulk["_likes_sent_tries"] = 0

    pending = str(bulk.get("awaiting_sent") or "")
    if pending:
        box = ""
        for n in _parse_compact_nodes(ui_tree):
            if "textinput" in str(n.get("id") or "").lower() or n.get("editable"):
                box = (n.get("text") or "").strip()
                break
        still = hily_on_mbm(ui_tree) and box.lower() == pending.lower()
        if still and "message sent" not in _blob(ui_tree):
            tries = int(bulk.get("send_retry") or 0)
            bulk["send_retry"] = tries + 1
            st["bulk_message_new"] = bulk
            if tries < 1:
                send = _send_center(ui_tree) or SEND_XY
                return _fp(
                    {
                        "action": "tap",
                        "x": int(send[0]),
                        "y": int(send[1]),
                        "reason": f"Hily Send again — '{pending}' still in the box ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hily_fixed_fc_send_retry",
                )
            return _fp(
                {
                    "action": "fail",
                    "reason": f"Hily message did not send ('{pending}' still in the box) — stop ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_not_sent",
            )
        done += 1
        bulk["done"] = done
        bulk["awaiting_sent"] = ""
        bulk["send_retry"] = 0
        bulk["typed"] = False
        st["bulk_message_new"] = bulk
        if done >= cap:
            return _fp(
                {
                    "action": "done",
                    "reason": f"Hily first-contact finished {done}/{cap} — sent, now auto-like ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                },
                "hily_fixed_fc_done",
            )

    popup = hily_dismiss_popup(ui_tree, planner=planner)
    if popup:
        return popup
    if hily_on_photo_viewer(ui_tree):
        return hily_back_from_photo_viewer(planner=planner)
    if hily_on_profile_sheet(ui_tree) and not hily_on_mbm(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Close Hily Crush/profile sheet — never deck Crush "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_sheet_back",
        )

    if _is_paywall(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": (
                    f"Hily first-contact paywall — Back, never pay "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "stopped_reason": "paywall",
            },
            "hily_fixed_fc_paywall_back",
        )

    text = allowed_message(message)

    if _message_sent_sheet(ui_tree) or (
        hily_on_mbm(ui_tree) and "message sent" in _blob(ui_tree)
    ):
        close = _tree_id_center(
            ui_tree,
            "closeButton",
            "id/closeButton",
            "com.hily.app:id/closeButton",
        ) or CLOSE_XY
        cx, cy = int(close[0]), int(close[1])
        return _fp(
            {
                "action": "tap",
                "x": cx,
                "y": cy,
                "reason": f"Close Hily Message sent sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_close_sent",
        )

    if hily_on_mbm(ui_tree):
        allow = hily_mbm_allowance(ui_tree)
        if allow == 0:
            closed = hily_close_mbm(ui_tree, planner=planner)
            if closed:
                closed["reason"] = (
                    f"Hily Message Before Match allowance is 0 — close, "
                    f"never pay ({planner})"
                )
                closed["stopped_reason"] = "allowance_exhausted"
                return closed
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Hily Message Before Match allowance is 0 — Back, "
                        f"never pay ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "stopped_reason": "allowance_exhausted",
                },
                "hily_fixed_fc_allowance_0",
            )
        if dry_run:
            bulk["done"] = cap
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] Hily Message Before Match composer "
                        f"verified (allowance {allow}); would send '{text}' "
                        f"— never typed, never Crush ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "would_send_text": text,
                },
                "hily_fixed_fc_dry_sheet",
            )
        if not bulk.get("typed"):
            # textInput is usually already focused.
            hist = " ".join(history[-12:]).lower()
            compose = _tree_id_center(
                ui_tree, "textInput", "id/textInput", "com.hily.app:id/textInput"
            )
            if compose and "focus" not in hist and "type " not in hist and "typed" not in hist:
                # Already focused in live tests — type directly when focused.
                focused = False
                for n in _parse_compact_nodes(ui_tree):
                    if "textinput" in str(n.get("id") or "").lower() and n.get("focused"):
                        focused = True
                        break
                if not focused:
                    return _fp(
                        {
                            "action": "tap",
                            "x": int(compose[0]),
                            "y": int(compose[1]),
                            "reason": f"Focus Hily MBM composer ({planner})",
                            "planner": planner,
                            "llm_provider": None,
                        },
                        "hily_fixed_fc_focus",
                    )
            bulk["typed"] = True
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "type",
                    "text": text,
                    "reason": (
                        f"Type MBM first-contact '{text}' ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "clear": True,
                },
                "hily_fixed_fc_type",
            )
        send = _send_center(ui_tree) or SEND_XY
        if send == CRUSH_XY:
            return _fp(
                {
                    "action": "press_button",
                    "button": "back",
                    "reason": (
                        f"Refuse Hily deck Crush coords — never send there "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_refuse_crush",
            )
        # PR #83 rule, every app (video, 24 Nov 2026): Send only when the
        # exact line is verified in the box. A type that never landed
        # retypes (bounded) — it must never reach Send.
        box = ""
        for n in _parse_compact_nodes(ui_tree):
            if "textinput" in str(n.get("id") or "").lower() or n.get("editable"):
                box = (n.get("text") or "").strip()
                break
        if box.lower() != text.lower():
            tries = int(bulk.get("type_tries") or 0)
            if tries >= 2:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Hily MBM comment never landed in the box after "
                            f"2 tries — stop, nothing sent ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "hily_fixed_fc_type_fail",
                )
            bulk["type_tries"] = tries + 1
            bulk["typed"] = False
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "type",
                    "text": text,
                    "reason": (
                        f"Type MBM first-contact '{text}' (retry) ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "clear": True,
                },
                "hily_fixed_fc_type",
            )
        bulk["type_tries"] = 0
        # r45: count only once Hily confirms (Message sent / sheet closed)
        bulk["awaiting_sent"] = text
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": int(send[0]),
                "y": int(send[1]),
                "reason": (
                    f"Hily Send first-contact {done + 1}/{cap} "
                    f"— never Crush ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_send",
        )

    # Navigate to Likes sent and open the next envelope.
    if dry_run and not hily_on_mbm(ui_tree):
        bulk["done"] = cap
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"[DRY RUN] would open Activity → Likes sent → "
                    f"chat_request → type '{text}' → Send to {cap} people "
                    f"(daily cap {DAILY_CAP}) — never typed, never Crush "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "dry_run_verified": True,
                "would_send_text": text,
            },
            "hily_fixed_fc_dry_nav",
        )

    req = _first_chat_request(ui_tree)
    if req and _on_activity(ui_tree):
        bulk["typed"] = False
        bulk["_ls_scrolls"] = 0
        bulk.pop("_ls_names", None)
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": int(req[0]),
                "y": int(req[1]),
                "reason": (
                    f"Open Hily Likes-sent chat_request for first-contact "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_open_request",
        )

    if _on_activity(ui_tree) and not _on_likes_sent(ui_tree, bulk):
        tries = int(bulk.get("_likes_sent_tries") or 0) + 1
        bulk["_likes_sent_tries"] = tries
        bulk["_ls_tapped"] = True
        st["bulk_message_new"] = bulk
        if tries > 3:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Hily Likes sent tab did not open after 3 taps — "
                        f"stop, nothing sent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_likes_sent_fail",
            )
        return _fp(
            {
                "action": "tap",
                "x": LIKES_SENT_XY[0],
                "y": LIKES_SENT_XY[1],
                "reason": f"Open Hily Likes sent ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_likes_sent",
        )

    # r45 (Mac): new people from Discover — open a Top-picks tile, then the
    # free message envelope on the profile. Never Crush.
    if (
        bulk.get("_via_discover")
        and hily_on_top_picks_grid(ui_tree)
        and not hily_on_chats_list(ui_tree)  # chat rows carry Crush chips
        and not _tree_id_center(ui_tree, "ActionButton_LIKE", "id/ActionButton_LIKE")
    ):
        tile = hily_first_grid_tile_center(ui_tree)
        n_tiles = int(bulk.get("_discover_opens") or 0)
        if tile and n_tiles < cap + 5:
            bulk["_discover_opens"] = n_tiles + 1
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": int(tile[0]),
                    "y": int(tile[1]),
                    "reason": f"Open a new person from Hily Discover ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_discover_tile",
            )
    if bulk.get("_via_discover") and not _on_activity(ui_tree):
        env_xy = _first_chat_request(ui_tree)
        if env_xy:
            return _fp(
                {
                    "action": "tap",
                    "x": int(env_xy[0]),
                    "y": int(env_xy[1]),
                    "reason": f"Open free message on this Discover profile ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_discover_envelope",
            )
        if int(bulk.get("_discover_misses") or 0) >= 3:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"Hily: no free message button on Discover profiles "
                        f"after {done}/{cap} sent — moving on to likes ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "stopped_reason": "no_more_targets",
                },
                "hily_fixed_fc_discover_none",
            )
        if not hily_on_top_picks_grid(ui_tree) or hily_on_chats_list(ui_tree):
            bulk["_discover_misses"] = int(bulk.get("_discover_misses") or 0) + 1
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "tap",
                    "x": DISCOVER_TAB_XY[0],
                    "y": DISCOVER_TAB_XY[1],
                    "reason": f"Back to Hily Discover for the next new person ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_discover_tab",
            )

    if _on_likes_sent(ui_tree, bulk) and not req:
        # r53 (live 27 Nov 2026): after 4 sends the next people sat in the
        # grid row behind the bottom nav — scroll Likes sent before calling
        # it empty. Stop scrolling once the visible names stop changing.
        names = "|".join(
            str(n.get("text") or "") for n in _parse_compact_nodes(ui_tree)
            if str(n.get("id") or "").lower().endswith("center_name")
        )
        scrolls = int(bulk.get("_ls_scrolls") or 0)
        if scrolls < 4 and names != str(bulk.get("_ls_names") or "\x00"):
            bulk["_ls_scrolls"] = scrolls + 1
            bulk["_ls_names"] = names
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "swipe",
                    "x1": 540, "y1": 1800, "x2": 540, "y2": 900,
                    "duration_ms": 450,
                    "reason": (
                        f"Scroll Hily Likes sent for more envelopes "
                        f"({done}/{cap} sent) ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "hily_fixed_fc_likes_sent_scroll",
            )
        bulk["_via_discover"] = True
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": DISCOVER_TAB_XY[0],
                "y": DISCOVER_TAB_XY[1],
                "reason": (
                    f"Likes sent has no free envelopes left ({done}/{cap}) — "
                    f"go to Discover for new people ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_to_discover",
        )
    if False:
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"Hily Likes sent has no chat_request envelopes left "
                    f"after {done}/{cap} ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "stopped_reason": "no_more_targets",
            },
            "hily_fixed_fc_no_targets",
        )

    # Finder / elsewhere — open Activity. Never tap deck Crush.
    tries = int(bulk.get("_activity_tries") or 0) + 1
    bulk["_activity_tries"] = tries
    bulk["_ls_tapped"] = False
    st["bulk_message_new"] = bulk
    if tries > 3:
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Hily Activity tab did not open after 3 taps — stop, "
                    f"nothing sent ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "hily_fixed_fc_activity_fail",
        )
    return _fp(
        {
            "action": "tap",
            "x": ACTIVITY_TAB_XY[0],
            "y": ACTIVITY_TAB_XY[1],
            "reason": (
                f"Open Hily Activity for Likes-sent first-contact "
                f"({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "hily_fixed_fc_activity",
    )
