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
        _tree_id_center,
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
        _tree_id_center,
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
        app = detect_dm_app(text)
    except Exception:
        app = None
    if not app:
        # First token often names the app: "tinder auto-swipe 50…"
        first = (text.split() or [""])[0].strip().lower().strip(",:")
        if first in DM_APP_PROFILES:
            app = first
        else:
            for key, prof in DM_APP_PROFILES.items():
                aliases = tuple(prof.get("aliases") or ()) + (key,)
                if any(a and a.lower() in low for a in aliases):
                    app = key
                    break

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


def _exact_label_center(tree: str, label: str) -> Optional[tuple[int, int]]:
    """Center of a node whose text/desc equals label (avoids 'Like' ⊂ 'Super Like')."""
    needle = (label or "").strip().lower()
    if not needle:
        return None
    for n in _parse_compact_nodes(tree):
        blob = " ".join(
            str(n.get(k) or "").strip() for k in ("text", "desc", "hint", "label")
        ).lower()
        # Exact token match on any field
        fields = [
            str(n.get(k) or "").strip().lower()
            for k in ("text", "desc", "hint", "label")
        ]
        if needle not in fields and blob != needle:
            continue
        x, y = int(n.get("x") or 0), int(n.get("y") or 0)
        if x or y:
            return (x, y)
    # Regex exact attr match on compact / uiautomator dumps
    low = (tree or "").lower()
    esc = re.escape(needle)
    for pat in (
        rf'(?:t|d|h|text|content-desc)="{esc}"[^>]*\bxy="(\d+),(\d+)"',
        rf'\bxy="(\d+),(\d+)"[^>]*(?:t|d|h|text|content-desc)="{esc}"',
        rf'(?:text|content-desc)="{esc}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*(?:text|content-desc)="{esc}"',
    ):
        m = re.search(pat, low, re.I)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        if len(g) == 2:
            return (g[0], g[1])
        if len(g) >= 4:
            return ((g[0] + g[2]) // 2, (g[1] + g[3]) // 2)
    return None


def _ensure_app_open(
    goal_app: Optional[str],
    package: str,
    history: List[str],
    planner: str,
) -> Optional[Dict[str, Any]]:
    """Open the instruction's app when FG package does not match."""
    if not goal_app or goal_app not in DM_APP_PROFILES:
        return None
    profile = DM_APP_PROFILES[goal_app]
    want = str(profile.get("package") or "").lower()
    pkg = (package or "").lower()
    if want and want in pkg:
        return None
    hist = " ".join(history[-8:]).lower()
    open_label = str(profile.get("open_label") or goal_app)
    open_l = open_label.lower()
    already = (
        f"opened {open_l}" in hist
        or f"open_app({open_l})" in hist
        or f"open_app({goal_app})" in hist
    )
    # Re-open whenever FG drifted; cap only to avoid infinite loops on broken installs
    opens = sum(1 for h in history[-16:] if "open_app(" in str(h).lower())
    if want and want in pkg:
        return None
    if opens >= 8:
        return None
    return _fp(
        {
            "action": "open_app",
            "app": open_label,
            "reason": f"Open {open_label} for bulk ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "bulk_open_app",
    )


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

    # If deck controls are already on-screen, do not open_app (relaunches reset
    # cold start races and used to rewind the deck cursor).
    deck_visible = bool(
        _exact_label_center(ui_tree, "Like")
        or _exact_label_center(ui_tree, "Pass")
        or _tree_id_center(ui_tree, "id/gamepad_like", "gamepad_like", "id/btn_like")
    )
    if not deck_visible:
        opened = _ensure_app_open(goal.get("app"), package, history, planner)
        if opened:
            return opened

    # Interruptions first (match / upsell / out-of-likes)
    tl = (ui_tree or "").lower()
    if any(
        s in tl
        for s in (
            "keep swiping",
            "maybe later",
            "it's a match",
            "out of likes",
            "get more likes",
            "see plans",
        )
    ):
        if "out of likes" in tl:
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
        for lab in ("Keep swiping", "Maybe later", "OK"):
            c = _exact_label_center(ui_tree, lab) or _dialog_center(ui_tree, (lab,))
            if c:
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
        # Dialog text visible but button coords missing — tap lower-center CTA
        return _fp(
            {
                "action": "tap",
                "x": 540,
                "y": 1500,
                "reason": f"Dismiss dialog fallback ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_dismiss_fallback",
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

    # Do not count likes while FG is wrong / tree empty
    want = ""
    if goal.get("app") and goal["app"] in DM_APP_PROFILES:
        want = str(DM_APP_PROFILES[goal["app"]].get("package") or "").lower()
    if want and want not in (package or "").lower():
        opened = _ensure_app_open(goal.get("app"), package, history, planner)
        if opened:
            return opened

    # Fake-chats Like is the right gamepad control. On 1080x2400 emulators the
    # row sits near y=2200 (above the 63px nav bar) — y=2100 misses entirely.
    like = (950, 2200)
    like_ids = ()
    if goal.get("app") and goal["app"] in DM_APP_PROFILES:
        like_ids = tuple(DM_APP_PROFILES[goal["app"]].get("like_ids") or ())
    located = _tree_id_center(ui_tree, *like_ids) if like_ids else None
    if located and located[0] >= 780 and located[1] >= 2000:
        like = located
    else:
        exact = _exact_label_center(ui_tree, "Like")
        if exact and exact[0] >= 780 and exact[1] >= 2000:
            like = exact
    if not deck_visible and not _exact_label_center(ui_tree, "Like"):
        disc = _tree_node_center(ui_tree, "Discover", "Open Discover")
        if disc and "open swipe deck" not in hist:
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

    # Only advance the counter when we are actually on the target package
    if not want or want in (package or "").lower():
        bulk["done"] = done + 1
        st["bulk_swipe"] = bulk
        next_n = done + 1
    else:
        next_n = done
    return _fp(
        {
            "action": "tap",
            "x": like[0],
            "y": like[1],
            "reason": f"Like profile {next_n}/{target} ({planner})",
            "planner": planner,
            "llm_provider": None,
            "delay_s": sample_human_delay(random.Random(f"like:{done}")),
            "_bulk_swipe_inc": bool(not want or want in (package or "").lower()),
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

    opened = _ensure_app_open(app_key, package, history, planner)
    if opened:
        return opened

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
