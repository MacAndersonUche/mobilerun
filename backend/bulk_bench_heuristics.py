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
        badoo_like_action,
        badoo_on_encounters,
        badoo_pass_action,
        blk_dismiss_popup,
        blk_end_of_deck,
        blk_like_action,
        blk_on_deck,
        blk_deck_card_name,
        bumble_like_swipe,
        bumble_on_people_deck,
        bumble_pass_swipe,
        detect_dm_app,
        find_send_center_safe,
        focused_is_compose_not_search,
        hily_deck_card_name,
        hily_dismiss_popup,
        hily_like_action,
        hily_on_finder,
        hily_pass_action,
        taimi_deck_card_name,
        taimi_dismiss_paywall,
        taimi_is_curated_card,
        taimi_is_paywall,
        taimi_like_action,
        taimi_on_people_deck,
        taimi_pass_action,
        taimi_swipes_left,
        yubo_deck_card_name,
        yubo_like_swipe,
        yubo_on_deck,
        yubo_pass_swipe,
    )
except ImportError:
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _parse_compact_nodes,
        _tree_id_center,
        _tree_node_center,
        badoo_like_action,
        badoo_on_encounters,
        badoo_pass_action,
        blk_dismiss_popup,
        blk_end_of_deck,
        blk_like_action,
        blk_on_deck,
        blk_deck_card_name,
        bumble_like_swipe,
        bumble_on_people_deck,
        bumble_pass_swipe,
        detect_dm_app,
        find_send_center_safe,
        focused_is_compose_not_search,
        hily_deck_card_name,
        hily_dismiss_popup,
        hily_like_action,
        hily_on_finder,
        hily_pass_action,
        taimi_deck_card_name,
        taimi_dismiss_paywall,
        taimi_is_curated_card,
        taimi_is_paywall,
        taimi_like_action,
        taimi_on_people_deck,
        taimi_pass_action,
        taimi_swipes_left,
        yubo_deck_card_name,
        yubo_like_swipe,
        yubo_on_deck,
        yubo_pass_swipe,
    )

# Real dating decks that must NOT use emu Like-button / (950,2200) fallbacks.
_REAL_GESTURE_APPS = frozenset({"bumble", "yubo", "badoo", "hily", "blk", "taimi"})


def _delay_band() -> tuple[float, float]:
    """Human-like pacing; CI can tighten via FAKE_CHATS_FAST=1."""
    if os.environ.get("FAKE_CHATS_FAST", "").lower() in ("1", "true", "yes"):
        return (0.05, 0.18)
    return (0.35, 1.25)


def sample_human_delay(rng: random.Random) -> float:
    lo, hi = _delay_band()
    return rng.uniform(lo, hi)


def _is_mixed_bulk_instruction(low: str) -> bool:
    """True when swipe/bulk is mixed with chat/reply — leave to DM heuristics."""
    has_swipe = (
        bool(re.search(r"(?:auto[- ]?)?swipe|\bswipe\s+\d+|auto-swipe", low))
        or "swipe 50" in low
    )
    has_bulk_msg = (
        bool(
            re.search(r"(?:auto[- ]?)?message\s+\d+\s+(?:matches|contacts|people)", low)
        )
        or "message 50" in low
        or "auto-message" in low
    )
    chatish = any(
        tok in low
        for tok in (
            "open chat",
            "go to chat",
            "open chats",
            "then reply",
            "and reply",
            "reply to",
            "then message",
            "and message",
            "send a message to",
            "message to ",
            "then send",
            "open conversation",
        )
    )
    if has_swipe and chatish:
        return True
    if has_swipe and has_bulk_msg:
        return True
    if has_bulk_msg and chatish and "matches" not in low and "contacts" not in low:
        # e.g. "message 50 then open chat and reply" still mixed
        if "then open" in low or "then reply" in low:
            return True
    return False


def parse_bulk_goal(instruction: str) -> Optional[Dict[str, Any]]:
    """Return {kind: swipe|message, count: int, message: str|None, app: str|None}.

    Returns None for mixed goals (swipe + open chat/reply) so the single-DM
    path can handle them instead of swallowing the whole instruction.
    """
    text = (instruction or "").strip()
    low = text.lower()
    if _is_mixed_bulk_instruction(low):
        return None
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


def deck_card_name(app: Optional[str], tree: str) -> Optional[str]:
    """Top-card display name for swipe verification (real maps + fake-chats)."""
    app = (app or "").lower()
    if app == "yubo":
        return yubo_deck_card_name(tree)
    if app == "bumble":
        for n in _parse_compact_nodes(tree):
            text = (n.get("text") or "").strip()
            if not text:
                continue
            # "Name, Age" near bottom of card
            if re.search(r",\s*\d{2}\s*$", text) and int(n.get("y") or 0) > 1500:
                return text.split(",")[0].strip()
        for n in _parse_compact_nodes(tree):
            desc = (n.get("desc") or "").strip()
            m = re.match(r"(.+?)['\u2019]s main photo", desc, re.I)
            if m:
                return m.group(1).strip()
        return None
    if app == "badoo":
        for n in _parse_compact_nodes(tree):
            nid = str(n.get("id") or "").lower()
            if "profileinfo_name" in nid:
                text = (n.get("text") or n.get("label") or "").strip()
                if text:
                    return text.split(",")[0].strip()
                desc = (n.get("desc") or "").strip()
                m = re.match(r"(.+?),\s*\d+", desc)
                if m:
                    return m.group(1).strip()
        return None
    if app == "hily":
        return hily_deck_card_name(tree)
    if app == "blk":
        return blk_deck_card_name(tree)
    if app == "taimi":
        return taimi_deck_card_name(tree)
    # Fake-chats / generic: ProfileNN or first mid-card title
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or n.get("desc") or "").strip()
        if re.match(r"Profile\d+", text, re.I):
            return text
        if re.match(r"Match\d+", text, re.I) and int(n.get("y") or 0) < 1200:
            return text
    return None


def _deck_visible(app: Optional[str], tree: str) -> bool:
    if _exact_label_center(tree, "Like") or _exact_label_center(tree, "Pass"):
        return True
    if _tree_id_center(
        tree, "id/gamepad_like", "gamepad_like", "id/btn_like", "encounter_like"
    ):
        return True
    app = (app or "").lower()
    if app == "bumble" and bumble_on_people_deck(tree):
        return True
    if app == "yubo" and yubo_on_deck(tree):
        return True
    if app == "badoo" and badoo_on_encounters(tree):
        return True
    if app == "hily" and hily_on_finder(tree):
        return True
    if app == "blk" and (blk_on_deck(tree) or blk_end_of_deck(tree)):
        return True
    if app == "taimi" and (
        taimi_on_people_deck(tree) or taimi_swipes_left(tree) is not None
    ):
        return True
    if app and app in DM_APP_PROFILES:
        ids = tuple(DM_APP_PROFILES[app].get("deck_ids") or ())
        if ids and _tree_id_center(tree, *ids):
            return True
        like_ids = tuple(DM_APP_PROFILES[app].get("like_ids") or ())
        if like_ids and _tree_id_center(tree, *like_ids):
            return True
    return False


def _real_like_action(
    app: str,
    tree: str = "",
    planner: str = "bulk_swipe_heuristic",
) -> Optional[Dict[str, Any]]:
    """Per-app like from the S21 map — swipe / button; never nav-tab coords."""
    if app == "bumble":
        act = bumble_like_swipe(planner=planner)
        act["reason"] = f"Bumble like swipe ({planner})"
        return act
    if app == "yubo":
        act = yubo_like_swipe(planner=planner)
        act["reason"] = f"Yubo like swipe ({planner})"
        return act
    if app == "badoo":
        # Prefer VoteYes id when present; helper uses verified map xy
        act = badoo_like_action(planner=planner)
        act["reason"] = f"Badoo Like VoteYes ({planner})"
        return act
    if app == "hily":
        act = hily_like_action(tree, planner=planner)
        if act:
            act["reason"] = f"Hily Like button ({planner})"
        return act
    if app == "blk":
        act = blk_like_action(tree, planner=planner)
        if act:
            act["reason"] = f"BLK Like Icon right/cyan ({planner})"
        return act
    if app == "taimi":
        # Curated → Skip (Like opens GOLD); Instant Chat never for bulk
        act = taimi_like_action(tree, planner=planner)
        if act:
            act["reason"] = f"Taimi Like/Skip ({planner})"
        return act
    return None


def _real_pass_action(
    app: str,
    tree: str = "",
    planner: str = "bulk_swipe_heuristic",
) -> Optional[Dict[str, Any]]:
    if app == "bumble":
        return bumble_pass_swipe(planner=planner)
    if app == "yubo":
        return yubo_pass_swipe(planner=planner)
    if app == "badoo":
        return badoo_pass_action(planner=planner)
    if app == "hily":
        return hily_pass_action(tree, planner=planner)
    if app == "taimi":
        return taimi_pass_action(tree, planner=planner)
    return None


def _fake_like_center(app: Optional[str], tree: str) -> Optional[tuple[int, int]]:
    """Locate Like for fake-chats / button decks. No coordinate guess."""
    like_ids: tuple = ()
    if app and app in DM_APP_PROFILES:
        like_ids = tuple(DM_APP_PROFILES[app].get("like_ids") or ())
    located = _tree_id_center(tree, *like_ids) if like_ids else None
    if located:
        return located
    # Also try common emu ids without the broken y>=2000 filter (Badoo Like
    # sits at y=1982 on real devices; emu Like can be slightly above 2000).
    located = _tree_id_center(
        tree,
        "id/gamepad_like",
        "gamepad_like",
        "id/btn_like",
        "encounter_like",
        "encounters_profile_voting_buttonVoteYes",
    )
    if located:
        return located
    return _exact_label_center(tree, "Like")


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
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    goal = parse_bulk_goal(instruction)
    if not goal or goal["kind"] != "swipe":
        return None
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_swipe",
        {
            "done": 0,
            "target": goal["count"],
            "last_name": None,
            "awaiting_verify": False,
        },
    )
    target = int(bulk.get("target") or goal["count"])
    done = int(bulk.get("done") or 0)
    planner = "bulk_swipe_heuristic"
    hist = " | ".join(history[-12:]).lower()
    app = (goal.get("app") or "") or ""

    # If deck controls are already on-screen, do not open_app (relaunches reset
    # cold start races and used to rewind the deck cursor).
    deck_visible = _deck_visible(app, ui_tree)
    if not deck_visible:
        opened = _ensure_app_open(goal.get("app"), package, history, planner)
        if opened:
            return opened

    # App-specific popups (Hily Got it / Maybe later; BLK Send Like anyway)
    if app == "hily":
        popup = hily_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
    if app == "blk":
        if blk_end_of_deck(ui_tree):
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"BLK end of deck after {done}/{target} likes "
                        f"— stop gracefully ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "bulk_swipe_done": done,
                    "bulk_swipe_target": target,
                    "stopped_reason": "end_of_deck",
                },
                "bulk_blk_deck_end",
            )
        popup = blk_dismiss_popup(ui_tree, planner=planner)
        if popup:
            return popup
    if app == "taimi":
        if taimi_is_paywall(ui_tree):
            # Count as skipped — never Continue; do not increment likes
            bulk["awaiting_verify"] = False
            bulk["last_name"] = None
            st["bulk_swipe"] = bulk
            return taimi_dismiss_paywall(ui_tree, planner=planner)
        left = taimi_swipes_left(ui_tree)
        if left == 0:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"Taimi 0 left after {done}/{target} — stop ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "bulk_swipe_done": done,
                    "bulk_swipe_target": target,
                    "stopped_reason": "swipes_exhausted",
                },
                "bulk_taimi_exhausted",
            )

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
            "unlock infinity",
            "buy credits",
            "enjoying bumble",
            "you gave your first like",
            "send a super like",
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
        for lab in (
            "Keep swiping",
            "Maybe later",
            "Got it",
            "Send Like anyway",
            "OK",
            "Close",
            "YES",
            "NOT INTERESTED",
        ):
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
        # Known upsell/paywall copy → BACK (never tap Buy / paid CTAs)
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss interrupt sheet ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_dismiss_back",
        )

    # Verify previous like: only count when top-card name changed
    if bulk.get("awaiting_verify"):
        if app == "taimi" and taimi_is_paywall(ui_tree):
            bulk["awaiting_verify"] = False
            bulk["last_name"] = None
            st["bulk_swipe"] = bulk
            return taimi_dismiss_paywall(ui_tree, planner=planner)
        name_now = deck_card_name(app, ui_tree)
        last = bulk.get("last_name")
        left_now = taimi_swipes_left(ui_tree) if app == "taimi" else None
        left_last = bulk.get("last_left")
        name_ok = bool(name_now and last and name_now != last)
        left_ok = (
            left_now is None
            or left_last is None
            or (
                isinstance(left_now, int)
                and isinstance(left_last, int)
                and left_now < left_last
            )
        )
        if name_ok and left_ok:
            bulk["done"] = done + 1
            done = int(bulk["done"])
            bulk["last_name"] = name_now
            if left_now is not None:
                bulk["last_left"] = left_now
            bulk["awaiting_verify"] = False
            st["bulk_swipe"] = bulk
        elif name_now and not last:
            bulk["last_name"] = name_now
            if left_now is not None:
                bulk["last_left"] = left_now
            bulk["awaiting_verify"] = False
            st["bulk_swipe"] = bulk
        elif name_now and last and name_now == last:
            # Same card still showing — do not increment; allow retry
            bulk["awaiting_verify"] = False
            st["bulk_swipe"] = bulk
        else:
            # Name unreadable — do not increment
            bulk["awaiting_verify"] = False
            st["bulk_swipe"] = bulk

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

    # Do not act while FG is wrong
    want = ""
    if goal.get("app") and goal["app"] in DM_APP_PROFILES:
        want = str(DM_APP_PROFILES[goal["app"]].get("package") or "").lower()
    if want and want not in (package or "").lower():
        opened = _ensure_app_open(goal.get("app"), package, history, planner)
        if opened:
            return opened

    if not deck_visible:
        disc = _tree_node_center(
            ui_tree, "Discover", "Open Discover", "People", "Encounters"
        )
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

    # dry_run: never like — stop before action (do not mutate the deck)
    if dry_run:
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"dry_run — bulk like skipped at {done}/{target} "
                    f"(no like/swipe) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "bulk_swipe_done": done,
                "bulk_swipe_target": target,
                "screenshot": True,
            },
            "bulk_dry_run_skip_like",
        )

    card_name = deck_card_name(app, ui_tree)
    next_n = done + 1

    # Real Bumble/Yubo/Badoo/Hily/BLK: mapped gestures / buttons — never (950,2200)
    if app in _REAL_GESTURE_APPS:
        act = _real_like_action(app, tree=ui_tree, planner=planner)
        if not act:
            return _fp(
                {
                    "action": "fail",
                    "reason": f"No real-app like gesture for {app} ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_like_missing",
            )
        bulk["last_name"] = card_name
        if app == "taimi":
            bulk["last_left"] = taimi_swipes_left(ui_tree)
        bulk["awaiting_verify"] = True
        bulk["_bulk_swipe_inc"] = False  # only after name change
        st["bulk_swipe"] = bulk
        act = dict(act)
        act["reason"] = f"Like profile {next_n}/{target}: {act.get('reason')}"
        act["delay_s"] = sample_human_delay(random.Random(f"like:{done}"))
        act["_bulk_swipe_inc"] = False
        step = "bulk_like_swipe" if act.get("action") == "swipe" else "bulk_like"
        return _fp(act, step)

    # Fake-chats / button decks: Like by id or exact label — never guessed coords
    like = _fake_like_center(app, ui_tree)
    if not like:
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Like control not found in a11y tree — "
                    f"refusing coord guess ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_like_not_found",
        )

    bulk["last_name"] = card_name
    bulk["awaiting_verify"] = True
    st["bulk_swipe"] = bulk
    return _fp(
        {
            "action": "tap",
            "x": like[0],
            "y": like[1],
            "reason": f"Like profile {next_n}/{target} ({planner})",
            "planner": planner,
            "llm_provider": None,
            "delay_s": sample_human_delay(random.Random(f"like:{done}")),
            "_bulk_swipe_inc": False,
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
    dry_run: bool = False,
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
            # Focus compose — never search; never guessed coords
            c = _tree_node_center(ui_tree, *compose_labels)
            compose_ids = tuple(profile.get("compose_ids") or ())
            if c is None and compose_ids:
                c = _tree_id_center(ui_tree, *compose_ids)
            if c is None:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Compose not found for {next_name} — "
                            f"refusing coord guess ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "bulk_compose_not_found",
                )
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
        # dry_run: stop before send
        if dry_run:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"dry_run — compose filled with '{message}' for "
                        f"{next_name}; send skipped ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "screenshot": True,
                    "bulk_message_done": done,
                    "bulk_message_target": target,
                },
                "bulk_dry_run_skip_send",
            )
        send = find_send_center_safe(
            ui_tree,
            tuple(profile.get("send_labels") or ("Send",)),
            send_ids=tuple(profile.get("send_ids") or ()),
            profile=profile,
        )
        if send is None:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Send control not found for {next_name} — "
                        f"refusing coord guess ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_send_not_found",
            )
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
    dry_run: bool = False,
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
        if (
            app
            and app not in swipe_keys()
            and app
            not in ("facebook", "bumble", "yubo", "badoo", "hily", "blk", "taimi")
        ):
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
            instruction,
            ui_tree,
            history,
            state=state,
            package=package,
            dry_run=dry_run,
        )
    return plan_bulk_message(
        instruction,
        ui_tree,
        history,
        state=state,
        package=package,
        dry_run=dry_run,
    )
