"""Hily first-contact: Message Before Match from Likes sent (free daily cap 5).

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


def _on_likes_sent(tree: str) -> bool:
    blob = _blob(tree)
    return "likes sent" in blob and "activity" in blob


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
        bulk["done"] = done + 1
        bulk["typed"] = False
        st["bulk_message_new"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": int(send[0]),
                "y": int(send[1]),
                "reason": (
                    f"Hily Send first-contact {bulk['done']}/{cap} "
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

    if _on_activity(ui_tree) and not _on_likes_sent(ui_tree):
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

    if _on_likes_sent(ui_tree) and not req:
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
