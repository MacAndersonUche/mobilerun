"""Deterministic bulk swipe / bulk message fast-paths for fake-chats bench.

Hard rule: message bodies come only from the instruction / message bank —
never AI-generated text.
"""

from __future__ import annotations

import os
import random
import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from fake_chats_catalog import bulk_counts, swipe_keys
except ImportError:
    from backend.fake_chats_catalog import bulk_counts, swipe_keys  # type: ignore

try:
    from dm_heuristics import (
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        _tree_node_center,
        detect_dm_app,
        focused_is_compose_not_search,
        find_send_center,
    )
except ImportError:
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        _tree_node_center,
        detect_dm_app,
        focused_is_compose_not_search,
        find_send_center,
    )


def _delay_band() -> tuple[float, float]:
    """Human-like pacing; CI can tighten via FAKE_CHATS_FAST=1."""
    if os.environ.get("FAKE_CHATS_FAST", "").lower() in ("1", "true", "yes"):
        return (0.05, 0.18)
    return (0.35, 1.25)


def sample_human_delay(rng: random.Random) -> float:
    lo, hi = _delay_band()
    return rng.uniform(lo, hi)


def parse_bulk_goal(instruction: str) -> Optional[Dict[str, Any]]:
    """Return {kind: swipe|message, count: int, message: str|None, app: str|None}."""
    text = (instruction or "").strip()
    low = text.lower()
    counts = bulk_counts()
    app = None
    try:
        app, _ = detect_dm_app(text, "")
    except Exception:
        app = None

    m = re.search(r"(?:auto[- ]?)?swipe\s+(\d+)\s+profiles?", low)
    if m or "swipe 50" in low or "auto-swipe" in low:
        n = int(m.group(1)) if m else counts["swipe"]
        return {"kind": "swipe", "count": n, "message": None, "app": app}

    m = re.search(
        r"(?:auto[- ]?)?message\s+(\d+)\s+(?:matches|contacts|people)",
        low,
    )
    if m or "message 50" in low or "auto-message" in low:
        n = int(m.group(1)) if m else counts["message"]
        # Exact bank text: "tell them hi baby" / "message … hi baby"
        msg = "hi baby"
        tm = re.search(
            r"(?:tell them|say|with(?: the)?(?: message)?|text)\s+(.+)$",
            text,
            re.I,
        )
        if tm:
            msg = tm.group(1).strip().strip("\"'")
        # Prefer trailing quoted / known bank
        qm = re.search(r"[\"']([^\"']+)[\"']\s*$", text)
        if qm:
            msg = qm.group(1).strip()
        if "hi baby" in low:
            msg = "hi baby"
        return {"kind": "message", "count": n, "message": msg, "app": app}
    return None


def _dialog_center(tree: str, labels: Sequence[str]) -> Optional[tuple[int, int]]:
    return _tree_node_center(tree, *labels)


def plan_bulk_swipe(
    instruction: str,
    ui_tree: str,
    history: List[str],
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
) -> Optional[Dict[str, Any]]:
    goal = parse_bulk_goal(instruction)
    if not goal or goal["kind"] != "swipe":
        return None
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault("bulk_swipe", {"done": 0, "target": goal["count"]})
    target = int(bulk.get("target") or goal["count"])
    done = int(bulk.get("done") or 0)
    planner = "bulk_swipe_heuristic"
    hist = " | ".join(history[-12:]).lower()

    # Interruptions first
    if _dialog_center(
        ui_tree,
        ("Keep swiping", "Maybe later", "OK", "It's a match", "Out of likes"),
    ):
        # Prefer Keep swiping / Maybe later over See plans
        for lab in ("Keep swiping", "Maybe later", "OK"):
            c = _dialog_center(ui_tree, (lab,))
            if c:
                if "out of likes" in ui_tree.lower():
                    return _fp(
                        {
                            "action": "done",
                            "reason": (
                                f"Stopped: out of likes after {done}/{target} swipes "
                                f"({planner})"
                            ),
                            "planner": planner,
                            "llm_provider": None,
                            "bulk_swipe_done": done,
                            "bulk_swipe_target": target,
                            "stopped_reason": "out_of_likes",
                        },
                        "bulk_out_of_likes",
                    )
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": f"Dismiss '{lab}' ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                        "delay_s": sample_human_delay(random.Random(f"{done}:{lab}")),
                    },
                    "bulk_dismiss_dialog",
                )

    if done >= target:
        return _fp(
            {
                "action": "done",
                "reason": f"Bulk swipe complete: {done}/{target} ({planner})",
                "planner": planner,
                "llm_provider": None,
                "bulk_swipe_done": done,
                "bulk_swipe_target": target,
            },
            "bulk_swipe_done",
        )

    # Ensure deck visible — tap Discover / Like area
    like = _tree_node_center(ui_tree, "Like", "like")
    if not like:
        # Try open discover from chats
        disc = _tree_node_center(ui_tree, "Discover", "Matches")
        if disc and "like" not in hist:
            return _fp(
                {
                    "action": "tap",
                    "x": disc[0],
                    "y": disc[1],
                    "reason": f"Open swipe deck ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_open_deck",
            )
        # Fallback coords for like button
        like = (860, 2100)

    bulk["done"] = done + 1
    st["bulk_swipe"] = bulk
    return _fp(
        {
            "action": "tap",
            "x": like[0],
            "y": like[1],
            "reason": f"Like profile {done + 1}/{target} ({planner})",
            "planner": planner,
            "llm_provider": None,
            "delay_s": sample_human_delay(random.Random(f"like:{done}")),
            "_bulk_swipe_inc": True,
        },
        "bulk_like",
    )


def plan_bulk_message(
    instruction: str,
    ui_tree: str,
    history: List[str],
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
) -> Optional[Dict[str, Any]]:
    goal = parse_bulk_goal(instruction)
    if not goal or goal["kind"] != "message":
        return None
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message",
        {"done": 0, "target": goal["count"], "current": None, "typed": False},
    )
    target = int(bulk.get("target") or goal["count"])
    done = int(bulk.get("done") or 0)
    message = goal["message"] or "hi baby"
    planner = "bulk_message_heuristic"
    nodes = _parse_compact_nodes(ui_tree)

    # Refuse if search field focused with message text risk
    app_key = goal.get("app")
    profile = DM_APP_PROFILES.get(app_key or "", {})
    compose_labels = tuple(
        profile.get("compose_labels") or ("Type a message", "Message")
    )
    search_labels = tuple(profile.get("search_labels") or ("Search", "Search matches"))

    if done >= target:
        return _fp(
            {
                "action": "done",
                "reason": f"Bulk message complete: {done}/{target} ({planner})",
                "planner": planner,
                "llm_provider": None,
                "bulk_message_done": done,
                "bulk_message_target": target,
            },
            "bulk_message_done",
        )

    next_name = "Match%02d" % (done + 1)

    # On conversation with current match
    header_hit = any(
        next_name.lower() in f"{n.get('label')}".lower() and int(n.get("y") or 0) < 400
        for n in nodes
    )
    if header_hit or (bulk.get("current") == next_name):
        bulk["current"] = next_name
        # If already sent (new outgoing), go back
        if (
            f"new outgoing message" in ui_tree.lower()
            and message.lower() in ui_tree.lower()
        ):
            # Count this send
            if not bulk.get("counted_current"):
                bulk["done"] = done + 1
                bulk["counted_current"] = True
                bulk["typed"] = False
                bulk["current"] = None
                st["bulk_message"] = bulk
            return _fp(
                {
                    "action": "back",
                    "reason": f"Message sent to {next_name}; back to list ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "delay_s": sample_human_delay(random.Random(f"back:{done}")),
                },
                "bulk_back_after_send",
            )

        # Type / send
        if not focused_is_compose_not_search(ui_tree, compose_labels, search_labels):
            # Focus compose — never search
            c = _tree_node_center(ui_tree, *compose_labels) or (540, 2050)
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Focus compose for {next_name} ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_focus_compose",
            )
        if not bulk.get("typed"):
            bulk["typed"] = True
            st["bulk_message"] = bulk
            return _fp(
                {
                    "action": "type",
                    "text": message,
                    "clear": True,
                    "reason": f"Type bank text to {next_name} ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "delay_s": sample_human_delay(random.Random(f"type:{done}")),
                },
                "bulk_type",
            )
        send = find_send_center(
            ui_tree,
            tuple(profile.get("send_labels") or ("Send",)),
            send_ids=tuple(profile.get("send_ids") or ()),
        ) or (1000, 2050)
        return _fp(
            {
                "action": "tap",
                "x": send[0],
                "y": send[1],
                "reason": f"Send to {next_name} ({planner})",
                "planner": planner,
                "llm_provider": None,
                "delay_s": sample_human_delay(random.Random(f"send:{done}")),
            },
            "bulk_send",
        )

    # Open Matches tab / list
    if "match" not in ui_tree.lower() and "connection" not in ui_tree.lower():
        c = _tree_node_center(ui_tree, "Matches", "Connections", "Chats")
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Open matches list ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_open_matches",
            )

    # Tap next match row
    c = _tree_node_center(ui_tree, next_name, f"Match {next_name}")
    if c:
        bulk["current"] = next_name
        bulk["typed"] = False
        bulk["counted_current"] = False
        st["bulk_message"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Open {next_name} ({planner})",
                "planner": planner,
                "llm_provider": None,
                "delay_s": sample_human_delay(random.Random(f"open:{done}")),
            },
            "bulk_open_match",
        )

    # Scroll for more matches
    return _fp(
        {
            "action": "swipe",
            "x1": 540,
            "y1": 1800,
            "x2": 540,
            "y2": 700,
            "reason": f"Scroll matches for {next_name} ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "bulk_scroll_matches",
    )


def plan_secure_folder(
    instruction: str,
    ui_tree: str,
    history: List[str],
) -> Optional[Dict[str, Any]]:
    low = (instruction or "").lower()
    if "secure folder" not in low:
        return None
    planner = "secure_folder_heuristic"
    # Unlock
    c = _tree_node_center(ui_tree, "Unlock Secure Folder", "Unlock")
    if c and "unlock" not in " ".join(history[-5:]).lower():
        return _fp(
            {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Unlock Secure Folder ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "sf_unlock",
        )
    # Open target app by label
    for label in (
        "Tinder",
        "Bumble",
        "Hinge",
        "WhatsApp",
        "Instagram",
        "Hily",
        "OkCupid",
    ):
        if label.lower() in low:
            c = _tree_node_center(ui_tree, f"Open {label}", label)
            if c:
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": f"Open {label} from Secure Folder ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "sf_open_app",
                )
    if "unlocked" in ui_tree.lower() or "secure folder · unlocked" in ui_tree.lower():
        return _fp(
            {
                "action": "done",
                "reason": f"Secure Folder unlocked ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "sf_done",
        )
    return None


def plan_bulk_bench(
    instruction: str,
    ui_tree: str,
    history: List[str],
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
) -> Optional[Dict[str, Any]]:
    sf = plan_secure_folder(instruction, ui_tree, history)
    if sf:
        return sf
    goal = parse_bulk_goal(instruction)
    if not goal:
        return None
    if goal["kind"] == "swipe":
        # Only for swipe-capable apps when detected
        app = goal.get("app")
        if app and app not in swipe_keys() and app not in ("facebook",):
            # messaging apps: no-op skip with done reason
            return _fp(
                {
                    "action": "done",
                    "reason": f"Bulk swipe N/A for messaging app {app}",
                    "planner": "bulk_swipe_heuristic",
                    "llm_provider": None,
                    "skipped": True,
                },
                "bulk_swipe_skip",
            )
        return plan_bulk_swipe(
            instruction, ui_tree, history, state=state, package=package
        )
    return plan_bulk_message(
        instruction, ui_tree, history, state=state, package=package
    )
