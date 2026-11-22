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
        _nav_tab_center,
        _parse_compact_nodes,
        _tree_id_center,
        _tree_node_center,
        badoo_like_action,
        badoo_on_connections,
        badoo_on_encounters,
        badoo_pass_action,
        blk_dismiss_popup,
        blk_end_of_deck,
        blk_like_action,
        blk_on_deck,
        blk_deck_card_name,
        bumble_back_from_photo_browser,
        bumble_collapsed_older_chats_center,
        bumble_deck_card_name,
        bumble_first_grid_tile_center,
        bumble_like_swipe,
        bumble_on_people_deck,
        bumble_on_photo_browser,
        bumble_on_photo_grid,
        bumble_pass_swipe,
        compose_center_in_thread,
        detect_dm_app,
        find_send_center_safe,
        focused_is_compose_not_search,
        hily_close_mbm,
        hily_deck_card_name,
        hily_dismiss_popup,
        hily_first_grid_tile_center,
        hily_like_action,
        hily_back_from_photo_viewer,
        hily_on_finder,
        hily_on_mbm,
        hily_on_photo_viewer,
        hily_on_top_picks_grid,
        hily_pass_action,
        _is_system_chrome_package,
        hinge_deck_card_name,
        hinge_dismiss_enable_prompt,
        hinge_dismiss_play_review,
        hinge_find_compose,
        hinge_find_send_a_message,
        hinge_like_sheet_action,
        hinge_on_discover,
        hinge_on_like_sheet,
        hinge_on_matches,
        hinge_open_discover_tab,
        keyboard_likely_up,
        known_root_screen,
        tab_bar_verified,
        tagged_chat_action,
        tagged_deck_card_name,
        tagged_like_action,
        tagged_location_overlay_continue,
        tagged_on_deck,
        yubo_chat_tab_xy,
        taimi_deck_card_name,
        taimi_dismiss_paywall,
        taimi_is_curated_card,
        taimi_is_paywall,
        taimi_like_action,
        taimi_on_people_deck,
        taimi_pass_action,
        taimi_swipes_left,
        thread_header_verified,
        yubo_deck_card_name,
        yubo_like_swipe,
        yubo_on_deck,
        yubo_pass_swipe,
    )
except ImportError:
    from backend.dm_heuristics import (  # type: ignore
        DM_APP_PROFILES,
        _fp,
        _nav_tab_center,
        _parse_compact_nodes,
        _tree_id_center,
        _tree_node_center,
        badoo_like_action,
        badoo_on_connections,
        badoo_on_encounters,
        badoo_pass_action,
        blk_dismiss_popup,
        blk_end_of_deck,
        blk_like_action,
        blk_on_deck,
        blk_deck_card_name,
        bumble_back_from_photo_browser,
        bumble_collapsed_older_chats_center,
        bumble_deck_card_name,
        bumble_first_grid_tile_center,
        bumble_like_swipe,
        bumble_on_people_deck,
        bumble_on_photo_browser,
        bumble_on_photo_grid,
        bumble_pass_swipe,
        compose_center_in_thread,
        detect_dm_app,
        find_send_center_safe,
        focused_is_compose_not_search,
        hily_close_mbm,
        hily_deck_card_name,
        hily_dismiss_popup,
        hily_first_grid_tile_center,
        hily_like_action,
        hily_back_from_photo_viewer,
        hily_on_finder,
        hily_on_mbm,
        hily_on_photo_viewer,
        hily_on_top_picks_grid,
        hily_pass_action,
        _is_system_chrome_package,
        hinge_deck_card_name,
        hinge_dismiss_enable_prompt,
        hinge_dismiss_play_review,
        hinge_find_compose,
        hinge_find_send_a_message,
        hinge_like_sheet_action,
        hinge_on_discover,
        hinge_on_like_sheet,
        hinge_on_matches,
        hinge_open_discover_tab,
        keyboard_likely_up,
        known_root_screen,
        tab_bar_verified,
        tagged_chat_action,
        tagged_deck_card_name,
        tagged_like_action,
        tagged_location_overlay_continue,
        tagged_on_deck,
        yubo_chat_tab_xy,
        taimi_deck_card_name,
        taimi_dismiss_paywall,
        taimi_is_curated_card,
        taimi_is_paywall,
        taimi_like_action,
        taimi_on_people_deck,
        taimi_pass_action,
        taimi_swipes_left,
        thread_header_verified,
        yubo_deck_card_name,
        yubo_like_swipe,
        yubo_on_deck,
        yubo_pass_swipe,
    )

DETECTOR_SETTLE_S = 1.5

# Real dating decks that must NOT use emu Like-button / (950,2200) fallbacks.
# Hinge Discover uses Send-a-message (handled separately); Tagged scaffold uses ids.
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
        bool(
            re.search(
                r"(?:auto[- ]?)?swipe|\bswipe\s+\d+|auto-swipe|\blike\s+\d+\s+profiles?",
                low,
            )
        )
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

    # Swipe / like wording variants (never invent a count)
    swipe_patterns = (
        # swipe right on 5 profiles / swipe 5 profiles / auto-swipe 50 profiles
        r"(?:auto[- ]?)?swipe(?:\s+right)?(?:\s+on)?\s+(\d+)\s+profiles?",
        # swipe right 5 times / swipe 5 times
        r"(?:auto[- ]?)?swipe(?:\s+right)?\s+(\d+)\s+times?",
        # like 5 profiles
        r"\blike\s+(\d+)\s+profiles?",
        # swipe 5 on yubo / swipe 5 on <app>
        r"(?:auto[- ]?)?swipe(?:\s+right)?\s+(\d+)\s+on\s+([a-z0-9._]+)",
    )
    for pat in swipe_patterns:
        m = re.search(pat, low)
        if m:
            n = int(m.group(1))
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                # "swipe N on <app>" — prefer explicit app token
                token = m.group(2).strip().lower()
                if token in DM_APP_PROFILES:
                    app = token
                else:
                    for key, prof in DM_APP_PROFILES.items():
                        aliases = tuple(prof.get("aliases") or ()) + (key,)
                        if token in aliases or any(a == token for a in aliases):
                            app = key
                            break
            return {"kind": "swipe", "count": n, "message": None, "app": app}
    if "swipe 50" in low or "auto-swipe" in low:
        return {"kind": "swipe", "count": counts["swipe"], "message": None, "app": app}

    # New-contact messaging: message "hello miss" to 5 new profiles on Hinge
    qm_new_quoted = re.search(
        r"(?:reply|message|auto[- ]?message)\s+[\"']([^\"']+)[\"']\s+"
        r"to\s+(\d+)\s+new\s+(?:profiles?|matches|contacts|people)",
        text,
        re.I,
    )
    if qm_new_quoted:
        return {
            "kind": "message_new",
            "count": int(qm_new_quoted.group(2)),
            "message": qm_new_quoted.group(1).strip(),
            "app": app,
            "contact_scope": "new",
        }
    qm_new_n = re.search(
        r"(?:message|auto[- ]?message)\s+(\d+)\s+new\s+"
        r"(?:profiles?|matches|contacts|people)",
        low,
    )
    if qm_new_n:
        n_new = int(qm_new_n.group(1))
        qm_body = re.search(r"[\"']([^\"']+)[\"']", text)
        msg_new = qm_body.group(1).strip() if qm_body else None
        if not msg_new:
            return {
                "kind": "message_new",
                "count": n_new,
                "message": None,
                "app": app,
                "contact_scope": "new",
                "error": (
                    "No message text in instruction — provide quoted text "
                    "for new-contact messaging"
                ),
            }
        return {
            "kind": "message_new",
            "count": n_new,
            "message": msg_new,
            "app": app,
            "contact_scope": "new",
        }

    # Quoted message BEFORE "to N": reply "hey" to 5 existing chats on Hily
    qm_first = re.search(
        r"(?:reply|message|auto[- ]?message)\s+[\"']([^\"']+)[\"']\s+"
        r"to\s+(\d+)\s+(?:existing\s+)?(?:matches|contacts|people|chats?)",
        text,
        re.I,
    )
    if qm_first:
        return {
            "kind": "message",
            "count": int(qm_first.group(2)),
            "message": qm_first.group(1).strip(),
            "app": app,
            "contact_scope": "existing",
        }

    m = re.search(
        r"(?:auto[- ]?)?(?:message|reply to)\s+(\d+)\s+"
        r"(?:existing\s+)?(?:matches|contacts|people|chats?)",
        low,
    )
    # Explicit "message 50" / "auto-message" with a countable N only — never
    # invent count=50 from bare "existing chats" without a number.
    if m or re.search(r"(?:message|auto[- ]?message)\s+50\b", low):
        if m:
            n = int(m.group(1))
        else:
            n = 50
        # Message body: ONLY explicit instruction text or bank phrase — never invent
        msg = None
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
        # Leading quoted body: message "hi" to 5 matches (without existing)
        qm2 = re.search(
            r"(?:message|reply|auto[- ]?message)\s+[\"']([^\"']+)[\"']",
            text,
            re.I,
        )
        if qm2:
            msg = qm2.group(1).strip()
        if msg is None and "hi baby" in low:
            # Only when the user literally wrote hi baby in the instruction
            msg = "hi baby"
        if not msg:
            return {
                "kind": "message",
                "count": n,
                "message": None,
                "app": app,
                "error": (
                    "No message text in instruction — refuse default; "
                    "provide say/tell text or a message-bank entry"
                ),
            }
        return {"kind": "message", "count": n, "message": msg, "app": app}

    # Bare "existing chats" without a parseable count → fail (never default 50)
    if "existing chat" in low or "existing match" in low:
        return {
            "kind": "message",
            "count": 0,
            "message": None,
            "app": app,
            "error": (
                "Could not parse chat count — refuse default 50; "
                'use e.g. reply "hi" to 5 existing chats'
            ),
        }
    return None


def _visible_chat_list_rows(
    ui_tree: str,
    app: Optional[str],
    *,
    skip_names: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Visible inbox/match row names from the a11y tree (skip already-done)."""
    try:
        from dm_heuristics import _looks_like_chat_list_row
    except ImportError:
        from backend.dm_heuristics import _looks_like_chat_list_row  # type: ignore

    skip = {str(s).strip().lower() for s in (skip_names or []) if s}
    profile = DM_APP_PROFILES.get((app or "").lower(), {}) if app else {}
    result_ids = tuple(profile.get("result_ids") or ())
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for n in _parse_compact_nodes(ui_tree):
        if not _looks_like_chat_list_row(n, result_ids):
            continue
        label = (n.get("text") or n.get("label") or "").strip()
        if not label:
            continue
        # Strip "Chat with X" / "Match X" prefixes for the contact key
        name = label
        low = label.lower()
        for pref in ("chat with ", "match "):
            if low.startswith(pref):
                name = label[len(pref) :].strip()
                break
        # Skip counters / chrome
        if re.search(r"^\d+\s*(matches?|people|likes?)$", name, re.I):
            continue
        if "they liked you" in low or "liked you" == low:
            continue
        key = name.lower()
        if key in skip or key in seen:
            continue
        if len(name) < 2 or len(name) > 40:
            continue
        seen.add(key)
        rows.append(
            {
                "name": name,
                "x": int(n["x"]),
                "y": int(n["y"]),
                "label": label,
            }
        )
    rows.sort(key=lambda r: (r["y"], r["x"]))
    return rows


MAX_LIST_SCROLLS = 3


def _is_fake_chats_bench(
    ui_tree: str, package: str = "", instruction: str = ""
) -> bool:
    """True only for the fake-chats test APK (Match%02d rows / instruction hint)."""
    instr = (instruction or "").lower()
    if "fake-chats" in instr or "fake chats" in instr:
        return True
    # Synthetic Match01..MatchNN labels are exclusive to the bench app
    if re.search(r"\bMatch\d{2}\b", ui_tree or ""):
        return True
    pkg = (package or "").lower()
    if "fakechats" in pkg or "fake_chats" in pkg:
        return True
    return False


def _chat_list_screen_verified(app: Optional[str], ui_tree: str) -> bool:
    """True when the foreground looks like an inbox / matches list (not deck/thread)."""
    app_l = (app or "").lower()
    try:
        from dm_heuristics import (
            badoo_on_connections,
            blk_on_matches,
            bumble_on_connections,
            hily_on_chats_list,
            taimi_on_chats_list,
            yubo_on_chat_list,
        )
    except ImportError:
        from backend.dm_heuristics import (  # type: ignore
            badoo_on_connections,
            blk_on_matches,
            bumble_on_connections,
            hily_on_chats_list,
            taimi_on_chats_list,
            yubo_on_chat_list,
        )

    if app_l == "hily":
        return hily_on_chats_list(ui_tree)
    if app_l == "blk":
        return blk_on_matches(ui_tree)
    if app_l == "taimi":
        return taimi_on_chats_list(ui_tree)
    if app_l == "bumble":
        return bumble_on_connections(ui_tree)
    if app_l == "yubo":
        return yubo_on_chat_list(ui_tree)
    if app_l == "badoo":
        return badoo_on_connections(ui_tree)
    if app_l == "whatsapp":
        # Home chats list: conversation row name / contact row
        return bool(
            _tree_id_center(
                ui_tree,
                "conversations_row_contact_name",
                "contact_row_container",
                "id/conversations_row_contact_name",
                "id/contact_row_container",
            )
            or _visible_chat_list_rows(ui_tree, "whatsapp")
        )
    # Generic: visible chat-list rows OR known result ids
    if _visible_chat_list_rows(ui_tree, app):
        return True
    profile = DM_APP_PROFILES.get(app_l, {}) if app_l else {}
    result_ids = tuple(profile.get("result_ids") or ())
    return bool(result_ids and _tree_id_center(ui_tree, *result_ids))


def _open_chats_tab_action(
    app: Optional[str],
    ui_tree: str,
    history: List[str],
    planner: str,
) -> Optional[Dict[str, Any]]:
    """Tap the app's Chats/Messages/Matches nav using the UI map (never invent).

    Prefer resource-id / content-desc. Fixed-xy only when the tab bar is verified
    on screen. Yubo uses index-mapped coords (no text/desc on real tabs).
    """
    hist = " ".join(history[-12:]).lower()
    if any(
        t in hist
        for t in (
            "open chats",
            "open matches",
            "open messages",
            "bulk_open_chats",
            "chats/messages tab",
            "yubo chat tab by index",
        )
    ):
        return None  # already tried — caller should verify/fail
    app_l = (app or "").lower()
    # Never blind-tap nav while stuck in photo browser / MBM / keyboard
    if app_l == "bumble" and bumble_on_photo_browser(ui_tree):
        return bumble_back_from_photo_browser(planner=planner)
    if app_l == "hily" and hily_on_mbm(ui_tree):
        return hily_close_mbm(ui_tree, planner=planner)
    if keyboard_likely_up(ui_tree):
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Dismiss keyboard before chats tab ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_dismiss_keyboard",
        )
    profile = DM_APP_PROFILES.get(app_l, {}) if app_l else {}
    labels = tuple(
        profile.get("inbox_tab_labels")
        or profile.get("inbox_labels")
        or ("Chats", "Messages", "Matches", "Connections", "Chat")
    )
    inbox_ids = tuple(profile.get("inbox_tab_ids") or profile.get("inbox_ids") or ())
    if app_l == "badoo":
        inbox_ids = inbox_ids + (
            "nav_bar_button_connections",
            "com.badoo.mobile:id/nav_bar_button_connections",
        )
    if app_l == "hily":
        inbox_ids = inbox_ids + ("bottomNavTab_2", "id/bottomNavTab_2")
    if app_l == "tagged":
        inbox_ids = inbox_ids + ("tab_chats", "id/tab_chats")
    c = _nav_tab_center(ui_tree, *labels, ids=inbox_ids)
    if c is None:
        for lab in labels:
            c = _exact_label_center(ui_tree, lab)
            if c:
                break
    if c is None and app_l == "yubo":
        # Unlabeled tabs — index map only when bottom clickables exist
        if (
            tab_bar_verified("yubo", ui_tree)
            or len([n for n in _parse_compact_nodes(ui_tree) if n.get("clickable")])
            >= 4
        ):
            c = yubo_chat_tab_xy()
            return _fp(
                {
                    "action": "tap",
                    "x": int(c[0]),
                    "y": int(c[1]),
                    "reason": f"Open Yubo Chat tab by index ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_open_chats",
            )
        return None
    if c is None:
        # Fixed-xy only with verified tab bar (never while on thread/keyboard)
        if tab_bar_verified(app_l, ui_tree):
            xy = profile.get("inbox_tab_xy")
            if isinstance(xy, (tuple, list)) and len(xy) >= 2:
                c = (int(xy[0]), int(xy[1]))
    if not c:
        return None
    return _fp(
        {
            "action": "tap",
            "x": int(c[0]),
            "y": int(c[1]),
            "reason": f"Open chats/messages tab ({planner})",
            "planner": planner,
            "llm_provider": None,
        },
        "bulk_open_chats",
    )


_ROOT_RECOVER_APPS = frozenset(
    {"bumble", "yubo", "badoo", "hily", "hinge", "tagged", "blk", "taimi"}
)


def _app_tree_empty(ui_tree: str, app: Optional[str] = None) -> bool:
    """True when the dump has no useful app-window nodes (SystemUI-only / blank)."""
    nodes = _parse_compact_nodes(ui_tree)
    if not nodes:
        return True
    app_l = (app or "").lower()
    pkg = ""
    if app_l and app_l in DM_APP_PROFILES:
        pkg = str(DM_APP_PROFILES[app_l].get("package") or "")
    useful = 0
    for n in nodes:
        p = str(n.get("package") or "")
        if _is_system_chrome_package(p):
            continue
        if pkg and pkg.lower() not in p.lower() and p:
            # Other apps OK if we have interactive content
            pass
        useful += 1
    return useful < 3


def _recover_to_root_action(
    app: Optional[str],
    ui_tree: str,
    history: List[str],
    planner: str,
    *,
    state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Back out / relaunch until deck, chat list, or tab bar is visible.

    Only for real dating apps that leave leftover sheets/threads between jobs.
    Hard-caps relaunches/backs so we never loop open↔back unbounded.
    """
    app_l = (app or "").lower()
    if app_l not in _ROOT_RECOVER_APPS:
        return None
    if known_root_screen(app_l, ui_tree):
        return None
    st = state if isinstance(state, dict) else {}
    key = f"_root_recover_{app_l}"
    bucket = st.setdefault(
        key, {"backs": 0, "relaunches": 0, "relaunched": False}
    )
    hist = " ".join(history[-16:]).lower()
    relaunches = int(bucket.get("relaunches") or 0)
    backs = int(bucket.get("backs") or 0)

    # Empty app tree → fail fast (don't thrash Back/Home)
    if _app_tree_empty(ui_tree, app_l):
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Empty app a11y tree for {app_l} after recover — "
                    f"fail fast (needs vision / unlock) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "needs_vision": True,
            },
            "bulk_recover_empty_tree",
        )

    if relaunches >= 3 or backs >= 8:
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Root recover exhausted for {app_l} "
                    f"(backs={backs} relaunches={relaunches}) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_recover_exhausted",
        )

    if app_l == "bumble" and bumble_on_photo_browser(ui_tree):
        return bumble_back_from_photo_browser(planner=planner)
    if app_l == "hily" and hily_on_photo_viewer(ui_tree):
        return hily_back_from_photo_viewer(planner=planner)
    # Hily MBM is handled in plan_bulk_message (skip contact) — not here
    if app_l == "hinge":
        play = hinge_dismiss_play_review(ui_tree, planner=planner)
        if play:
            return play
        en = hinge_dismiss_enable_prompt(ui_tree, planner=planner)
        if en:
            return en
        if hinge_on_like_sheet(ui_tree):
            # Not a root — back out of like sheet if we landed mid-job
            pass
    if app_l == "tagged":
        loc = tagged_location_overlay_continue(ui_tree, planner=planner)
        if loc:
            return loc

    if keyboard_likely_up(ui_tree) or (
        app_l == "badoo"
        and any(n.get("editable") for n in _parse_compact_nodes(ui_tree))
        and not badoo_on_encounters(ui_tree)
        and not badoo_on_connections(ui_tree)
    ):
        bucket["backs"] = backs + 1
        st[key] = bucket
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Back to leave thread/keyboard → root ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_recover_back",
        )

    # Count recent recover backs across full recent history (not last 80 chars)
    recent_backs = sum(
        1 for h in history[-12:] if "bulk_recover_back" in str(h).lower()
    )
    if backs < 4 and recent_backs < 3:
        bucket["backs"] = backs + 1
        st[key] = bucket
        return _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Back toward known root for {app_l} ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_recover_back",
        )
    if relaunches < 3 and app_l in DM_APP_PROFILES:
        bucket["relaunches"] = relaunches + 1
        bucket["relaunched"] = True
        # Do NOT reset backs — keep the hard cap honest
        st[key] = bucket
        label = str(DM_APP_PROFILES[app_l].get("open_label") or app_l)
        return _fp(
            {
                "action": "open_app",
                "app": label,
                "reason": f"Relaunch {label} to known root ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_recover_relaunch",
        )
    return _fp(
        {
            "action": "fail",
            "reason": (
                f"Could not reach known root for {app_l} ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "bulk_recover_fail",
    )


def deck_card_name(app: Optional[str], tree: str) -> Optional[str]:
    """Top-card display name for swipe verification (real maps + fake-chats)."""
    app = (app or "").lower()
    if app == "yubo":
        return yubo_deck_card_name(tree)
    if app == "bumble":
        return bumble_deck_card_name(tree)
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
    if app == "hinge":
        return hinge_deck_card_name(tree)
    if app == "tagged":
        return tagged_deck_card_name(tree)
    # Fake-chats / generic: ProfileNN or first mid-card title
    for n in _parse_compact_nodes(tree):
        text = (n.get("text") or n.get("desc") or "").strip()
        if re.match(r"Profile\d+", text, re.I):
            return text
        if re.match(r"Match\d+", text, re.I) and int(n.get("y") or 0) < 1200:
            return text
    return None


def _deck_visible(app: Optional[str], tree: str) -> bool:
    """True when the swipe/like deck is on screen (map like/pass ids first)."""
    app = (app or "").lower()
    profile = DM_APP_PROFILES.get(app, {}) if app else {}
    # Map like/pass resource-ids first (Hily ActionButton_*, Badoo VoteYes/No, …)
    like_ids = tuple(profile.get("like_ids") or ())
    pass_ids = tuple(profile.get("pass_ids") or ())
    if like_ids and _tree_id_center(tree, *like_ids):
        return True
    if pass_ids and _tree_id_center(tree, *pass_ids):
        return True
    deck_ids = tuple(profile.get("deck_ids") or ())
    if deck_ids and _tree_id_center(tree, *deck_ids):
        return True
    if _tree_id_center(
        tree, "id/gamepad_like", "gamepad_like", "id/btn_like", "encounter_like"
    ):
        return True
    # Exact bottom-row Like/Pass (avoid matching "likely" etc. via substring)
    like = _exact_label_center(tree, "Like")
    pass_ = _exact_label_center(tree, "Pass")
    if like and int(like[1]) > 1700:
        return True
    if pass_ and int(pass_[1]) > 1700:
        return True
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
    if app == "hinge" and hinge_on_discover(tree):
        return True
    if app == "tagged" and tagged_on_deck(tree):
        return True
    if app == "hily" and hily_on_top_picks_grid(tree):
        # Grid is Discover — not a likeable deck until a tile is opened
        return False
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

    # ALWAYS verify FG package matches the named app before any swipe/tap.
    # (Previously skipped open_app when any deck was visible — swiped Bumble for Yubo.)
    want_pkg = ""
    if app and app in DM_APP_PROFILES:
        want_pkg = str(DM_APP_PROFILES[app].get("package") or "").lower()
    pkg_l = (package or "").lower()
    if want_pkg and want_pkg not in pkg_l:
        opened = _ensure_app_open(goal.get("app"), package, history, planner)
        if opened:
            return opened
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Wrong foreground app for bulk swipe: want {app} "
                    f"({want_pkg}) got '{package or '?'}' ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_wrong_app",
        )

    # Job start: leave leftover photo browser / thread / keyboard
    recover = _recover_to_root_action(app, ui_tree, history, planner, state=st)
    if recover:
        return recover

    deck_visible = _deck_visible(app, ui_tree)
    # Bumble photo browser (SuperSwipe only) — back out before deck checks
    if app == "bumble" and bumble_on_photo_browser(ui_tree):
        return bumble_back_from_photo_browser(planner=planner)
    # Hily photo viewer ('1 of 4' + app_top_bar_back) — back before swipe/HOME
    if app == "hily" and hily_on_photo_viewer(ui_tree):
        return hily_back_from_photo_viewer(planner=planner)
    # Hily Discover grid: open first tile → profile once; never loop tile 3x
    if app == "hily" and hily_on_top_picks_grid(ui_tree):
        tile_taps = sum(
            1
            for h in history[-10:]
            if "hily grid tile" in str(h).lower()
            or "bulk_hily_open_grid_tile" in str(h).lower()
            or "open grid tile" in str(h).lower()
        )
        tile = hily_first_grid_tile_center(ui_tree)
        if tile and tile_taps < 1:
            return _fp(
                {
                    "action": "tap",
                    "x": tile[0],
                    "y": tile[1],
                    "reason": f"Open Hily Top picks grid tile → profile ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                },
                "bulk_hily_open_grid_tile",
            )
        if tile_taps >= 1 or dry_run:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"dry_run — Hily Discover is a Top picks grid "
                        f"(Crush tiles paid); refuse repeated tile taps "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                    "dry_run_verified": False,
                },
                "bulk_dry_run_hily_grid",
            )
    # People photo-grid ≠ swipe deck. Opening a tile lands in PhotoBrowser
    # (Send SuperSwipe only — paid). Switch to Discover tab (card deck) once.
    if app == "bumble" and bumble_on_photo_grid(ui_tree):
        if "bumble_open_discover" not in hist and "open swipe deck" not in hist:
            xy = DM_APP_PROFILES["bumble"].get("discover_tab_xy") or (324, 2197)
            return _fp(
                {
                    "action": "tap",
                    "x": int(xy[0]),
                    "y": int(xy[1]),
                    "reason": (
                        f"Bumble People grid → Discover card deck "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                },
                "bumble_open_discover",
            )
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Bumble People photo grid is not a swipe deck — "
                    f"Discover card stack required (pass/like); "
                    f"do not tap grid tiles (PhotoBrowser SuperSwipe is paid) "
                    f"({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
                "dry_run_verified": False,
            },
            "bulk_bumble_grid_not_deck",
        )
    if not deck_visible:
        opened = _ensure_app_open(goal.get("app"), package, history, planner)
        if opened:
            return opened
        # After open_deck / People / Finder tab — settle once then re-check.
        # Do NOT settle on a bare "Opened … launch" (that blocks opening the deck).
        if any(
            t in hist
            for t in (
                "open swipe deck",
                "bulk_open_deck",
                "open finder",
                "open people",
            )
        ) and not bulk.get("_deck_settle_done"):
            bulk["_deck_settle_done"] = True
            st["bulk_swipe"] = bulk
            try:
                from cloud_agent import save_detector_miss_tree as _miss
            except ImportError:
                try:
                    from backend.cloud_agent import (  # type: ignore
                        save_detector_miss_tree as _miss,
                    )
                except ImportError:
                    _miss = None  # type: ignore
            if _miss:
                _miss(f"deck_{app or 'app'}", ui_tree, package=package)
            return _fp(
                {
                    "action": "wait",
                    "seconds": DETECTOR_SETTLE_S,
                    "delay_s": DETECTOR_SETTLE_S,
                    "reason": (
                        f"Settle {DETECTOR_SETTLE_S}s for deck detectors "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_settle_deck",
            )

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
    if app == "hinge":
        play = hinge_dismiss_play_review(ui_tree, planner=planner)
        if play:
            return play
        popup = hinge_dismiss_enable_prompt(ui_tree, planner=planner)
        if popup:
            return popup
        if hinge_on_like_sheet(ui_tree):
            # Like sheet is a11y — Send Like only (never Rose)
            if dry_run:
                card = deck_card_name(app, ui_tree) or "like sheet"
                bulk["done"] = target
                st["bulk_swipe"] = bulk
                return _fp(
                    {
                        "action": "done",
                        "reason": (
                            f"[DRY RUN] would like/pass {target} cards "
                            f"(deck verified on {card}) — no Send Like/Rose "
                            f"({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": True,
                        "bulk_swipe_done": target,
                        "bulk_swipe_target": target,
                        "screenshot": True,
                    },
                    "bulk_dry_run_skip_like",
                )
            return hinge_like_sheet_action(ui_tree, planner=planner)
        if hinge_on_matches(ui_tree) and not hinge_on_discover(ui_tree):
            if "open hinge discover" not in hist and "hinge_open_discover" not in hist:
                act = hinge_open_discover_tab(planner=planner)
                act["dry_run"] = bool(dry_run)
                return act
        if not deck_visible and "open hinge discover" not in hist:
            # Discover has no a11y — nav xy only after recover; vision for hearts
            act = hinge_open_discover_tab(planner=planner)
            act["dry_run"] = bool(dry_run)
            act["needs_vision"] = True
            return act
        # Discover "like" = heart (vision) → like sheet Send Like — never Rose
        if dry_run and deck_visible:
            card = deck_card_name(app, ui_tree)
            send_cta = hinge_find_send_a_message(ui_tree)
            compose = hinge_find_compose(ui_tree)
            if not card and not send_cta and not compose:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"dry_run — Hinge Discover not verified "
                            f"(no name / Send a message) ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": False,
                    },
                    "bulk_dry_run_hinge_unverified",
                )
            label = card or "Discover card"
            bulk["done"] = target
            bulk["dry_logs"] = [
                f"[DRY RUN] would like/pass {target} cards "
                f"(deck verified on {label})"
            ]
            st["bulk_swipe"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] would like/pass {target} cards "
                        f"(deck verified on {label}) — no Rose/Send "
                        f"({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "bulk_swipe_done": target,
                    "bulk_swipe_target": target,
                    "screenshot": True,
                },
                "bulk_dry_run_skip_like",
            )
        if not dry_run and deck_visible:
            # Live Discover likes require message-bank / say text — refuse Rose
            msg = (goal.get("message") or "").strip()
            if not msg:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            "Hinge Discover requires message-bank / say text "
                            f"— refusing Rose/Boost/Preferred/HingeX ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "bulk_hinge_needs_message",
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

    if not deck_visible:
        # Bumble: People is a photo GRID — Discover (left tab) is the card deck.
        # Badoo: Encounters (nav_bar_button_encounters), never People/Discover.
        if app == "bumble":
            disc = (
                _exact_label_center(ui_tree, "Discover")
                or _tree_node_center(ui_tree, "Discover", "Open Discover")
            )
            if not disc:
                xy = DM_APP_PROFILES["bumble"].get("discover_tab_xy") or (324, 2197)
                disc = (int(xy[0]), int(xy[1]))
        elif app == "badoo":
            disc = (
                _tree_id_center(
                    ui_tree,
                    "nav_bar_button_encounters",
                    "com.badoo.mobile:id/nav_bar_button_encounters",
                )
                or _exact_label_center(ui_tree, "Encounters")
                or _tree_node_center(ui_tree, "Encounters")
            )
            if not disc:
                xy = DM_APP_PROFILES["badoo"].get("encounters_tab_xy") or (324, 2210)
                disc = (int(xy[0]), int(xy[1]))
        else:
            disc = (
                _exact_label_center(ui_tree, "People")
                or _exact_label_center(ui_tree, "Discover")
                or _tree_node_center(
                    ui_tree, "People", "Encounters", "Discover", "Open Discover"
                )
            )
        if disc and "open swipe deck" not in hist:
            # Dry-run: tap the harmless nav tab so we can verify the like
            # control next — never stop at "would open deck" without proof.
            return _fp(
                {
                    "action": "tap",
                    "x": disc[0],
                    "y": disc[1],
                    "reason": f"Open swipe deck ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                },
                "bulk_open_deck",
            )

    # dry_run: verify ONE real card, then log would like/pass N once (no loop)
    if dry_run:
        like_ok = bool(deck_visible or _fake_like_center(app, ui_tree))
        if not like_ok and not deck_visible:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"dry_run — deck/like control not visible for {app or '?'} "
                        f"at {done}/{target}; refusing silent 0/{target} ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": False,
                },
                "bulk_dry_run_no_deck",
            )
        card = deck_card_name(app, ui_tree)
        if not card:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"dry_run — deck visible but no real card name for "
                        f"{app or '?'}; refusing profile_N invent ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": False,
                },
                "bulk_dry_run_no_card_name",
            )
        bulk["done"] = target
        bulk["dry_logs"] = [
            f"[DRY RUN] would like/pass {target} cards (deck verified on {card})"
        ]
        st["bulk_swipe"] = bulk
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"[DRY RUN] would like/pass {target} cards "
                    f"(deck verified on {card}) — no like/swipe ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": True,
                "dry_run_verified": True,
                "bulk_swipe_done": target,
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
    if goal.get("error") or not (goal.get("message") or "").strip():
        return _fp(
            {
                "action": "fail",
                "reason": (
                    goal.get("error")
                    or (
                        "No message text — refuse AI-authored default; "
                        "provide say/tell text or a message-bank entry "
                        "(bulk_message_heuristic)"
                    )
                ),
                "planner": "bulk_message_heuristic",
                "llm_provider": None,
            },
            "bulk_message_missing_text",
        )
    message = str(goal["message"]).strip()
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

    # Hily MBM BEFORE root recover — close + skip (list still underneath)
    if app_key == "hily" and hily_on_mbm(ui_tree):
        skip_name = str(bulk.get("current") or "").strip()
        if skip_name:
            names = list(bulk.get("done_names") or [])
            if skip_name.lower() not in {str(x).lower() for x in names}:
                names.append(skip_name)
            bulk["done_names"] = names
            bulk["current"] = None
            bulk["typed"] = False
            st["bulk_message"] = bulk
        return hily_close_mbm(ui_tree, planner=planner) or _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Close Hily MBM and skip contact ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_hily_mbm_skip",
        )

    recover = _recover_to_root_action(app_key, ui_tree, history, planner, state=st)
    if recover:
        return recover

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

    done_names = list(bulk.get("done_names") or [])
    fake_bench = _is_fake_chats_bench(ui_tree, package, instruction)
    list_ok = _chat_list_screen_verified(app_key, ui_tree)
    bulk["chat_list_verified"] = bool(list_ok)
    st["bulk_message"] = bulk

    # Ensure we're on the Chats/Messages list before inventing targets
    if not list_ok and not bulk.get("current"):
        open_tab = _open_chats_tab_action(app_key, ui_tree, history, planner)
        if open_tab:
            bulk.pop("_chats_settle_done", None)
            st["bulk_message"] = bulk
            return open_tab
        opened_hist = any(
            "open chats" in str(h).lower()
            or "bulk_open_chats" in str(h).lower()
            or "chats/messages tab" in str(h).lower()
            for h in history[-8:]
        )
        # Retry once after a short settle — real apps animate the list in.
        if opened_hist and not bulk.get("_chats_settle_done"):
            bulk["_chats_settle_done"] = True
            st["bulk_message"] = bulk
            try:
                from cloud_agent import save_detector_miss_tree as _miss
            except ImportError:
                try:
                    from backend.cloud_agent import (  # type: ignore
                        save_detector_miss_tree as _miss,
                    )
                except ImportError:
                    _miss = None  # type: ignore
            if _miss:
                _miss(
                    f"chat_list_{app_key or 'app'}",
                    ui_tree,
                    package=package,
                )
            return _fp(
                {
                    "action": "wait",
                    "seconds": DETECTOR_SETTLE_S,
                    "delay_s": DETECTOR_SETTLE_S,
                    "reason": (
                        f"Settle {DETECTOR_SETTLE_S}s after chats tab "
                        f"before re-check ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_settle_chats",
            )
        if opened_hist:
            return _fp(
                {
                    "action": "fail",
                    "reason": (
                        f"Chat list not verified for {app_key or 'app'} — "
                        f"refusing Match%02d / blind scroll ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": bool(dry_run),
                    "dry_run_verified": False,
                },
                "bulk_chat_list_unverified",
            )
        # First attempt with mapped coords even if label miss (not Yubo xy)
        open_tab = _open_chats_tab_action(app_key, ui_tree, [], planner)
        if open_tab:
            return open_tab
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"No Chats/Messages tab found for {app_key or 'app'} ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_chats_tab_missing",
        )

    # Bumble: collapsed "Older chats · (N)" must be expanded before picking rows
    if (
        list_ok
        and (app_key or "").lower() == "bumble"
        and not bulk.get("current")
        and "older chats" not in " ".join(history[-6:]).lower()
    ):
        rows_probe = _visible_chat_list_rows(ui_tree, app_key, skip_names=done_names)
        older = bumble_collapsed_older_chats_center(ui_tree)
        if older and not rows_probe:
            return _fp(
                {
                    "action": "tap",
                    "x": older[0],
                    "y": older[1],
                    "reason": f"Expand Older chats section ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "bulk_expand_older_chats",
            )

    next_name = str(bulk.get("current") or "").strip()
    if not next_name:
        rows = _visible_chat_list_rows(ui_tree, app_key, skip_names=done_names)
        if rows:
            next_name = str(rows[0]["name"])
            bulk["_next_row"] = rows[0]
        elif fake_bench:
            # Match%02d ONLY on the fake-chats bench APK
            next_name = "Match%02d" % (done + 1)
            bulk.pop("_next_row", None)
        else:
            next_name = ""
            bulk.pop("_next_row", None)

    # On conversation with current match — require verified thread header
    header_hit = bool(next_name) and thread_header_verified(app_key, ui_tree, next_name)
    if not header_hit and next_name:
        # Legacy soft match for apps without header_ids (still top-of-screen)
        header_hit = any(
            next_name.lower() in f"{n.get('label')}".lower()
            and int(n.get("y") or 0) < 400
            for n in nodes
        )
    if header_hit or (
        bulk.get("current") == next_name
        and next_name
        and thread_header_verified(app_key, ui_tree, next_name)
    ):
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
                bulk["cleared"] = False
                if next_name and next_name.lower() not in {
                    str(x).lower() for x in done_names
                }:
                    done_names.append(next_name)
                bulk["done_names"] = done_names
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

        # Type / send — composer ONLY after header verified; bottom 30% ids
        if not focused_is_compose_not_search(ui_tree, compose_labels, search_labels):
            c = compose_center_in_thread(app_key, ui_tree, next_name)
            if c is None:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"Compose not found for {next_name} after header "
                            f"verify — refusing list Message tap ({planner})"
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
            bulk["cleared"] = False
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
        # dry_run: verify compose, CLEAR draft, go back, continue until target
        if dry_run:
            if not bulk.get("cleared"):
                bulk["cleared"] = True
                st["bulk_message"] = bulk
                return _fp(
                    {
                        "action": "type",
                        "text": "",
                        "clear": True,
                        "reason": (
                            f"[DRY RUN] clear composer after verify "
                            f"('{message}' for {next_name})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": True,
                        "screenshot": True,
                    },
                    "bulk_dry_run_clear_composer",
                )
            # Count this dry-run reply and return to list
            if not bulk.get("counted_current"):
                bulk["done"] = done + 1
                bulk["counted_current"] = True
                bulk["typed"] = False
                bulk["cleared"] = False
                if next_name and next_name.lower() not in {
                    str(x).lower() for x in done_names
                }:
                    done_names.append(next_name)
                bulk["done_names"] = done_names
                bulk["current"] = None
                st["bulk_message"] = bulk
            if bulk["done"] >= target:
                return _fp(
                    {
                        "action": "done",
                        "reason": (
                            f"dry_run — replied (typed+cleared) to "
                            f"{bulk['done']}/{target} chats; send skipped ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": True,
                        "screenshot": True,
                        "bulk_message_done": bulk["done"],
                        "bulk_message_target": target,
                    },
                    "bulk_dry_run_skip_send",
                )
            return _fp(
                {
                    "action": "back",
                    "reason": (
                        f"[DRY RUN] cleared composer for {next_name}; "
                        f"back to list ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                },
                "bulk_dry_run_back",
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

    # Tap next visible chat-list row (skip already-done names)
    rows = _visible_chat_list_rows(ui_tree, app_key, skip_names=done_names)
    row = rows[0] if rows else None
    if row is None and fake_bench and next_name:
        # Bench fallback: Match%02d synthetic rows only
        c = _tree_node_center(ui_tree, next_name, f"Match {next_name}")
        if c:
            row = {"name": next_name, "x": c[0], "y": c[1]}
    if row:
        bulk["current"] = str(row["name"])
        bulk["typed"] = False
        bulk["cleared"] = False
        bulk["counted_current"] = False
        bulk["scroll_count"] = 0
        st["bulk_message"] = bulk
        return _fp(
            {
                "action": "tap",
                "x": int(row["x"]),
                "y": int(row["y"]),
                "reason": f"Open {row['name']} ({planner})",
                "planner": planner,
                "llm_provider": None,
                "delay_s": sample_human_delay(random.Random(f"open:{done}")),
                "chat_list_verified": True,
            },
            "bulk_open_match",
        )

    # No rows: scroll only on a verified list, cap at MAX_LIST_SCROLLS
    scroll_n = int(bulk.get("scroll_count") or 0)
    if list_ok and scroll_n < MAX_LIST_SCROLLS:
        bulk["scroll_count"] = scroll_n + 1
        st["bulk_message"] = bulk
        return _fp(
            {
                "action": "swipe",
                "x1": 540,
                "y1": 1800,
                "x2": 540,
                "y2": 700,
                "reason": (
                    f"Scroll verified chat list for more rows "
                    f"({scroll_n + 1}/{MAX_LIST_SCROLLS}) ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "chat_list_verified": True,
                "_chat_list_verified": True,
            },
            "bulk_scroll",
        )

    return _fp(
        {
            "action": "fail",
            "reason": (
                f"No chat-list rows for {app_key or 'app'} after "
                f"{scroll_n} scrolls — refusing Match%02d invent ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "dry_run_verified": False,
        },
        "bulk_no_chat_rows",
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


def plan_bulk_message_new(
    instruction: str,
    ui_tree: str,
    history: List[str],
    *,
    state: Optional[Dict[str, Any]] = None,
    package: str = "",
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """Message NEW contacts (not existing chats).

    Hinge: heart → like-sheet comment → Send Like / Send Like anyway (never Rose).
    Tagged: chatBtn on Match card.
    Hily: first free message; skip Message Before Match / paid.
    Other swipe apps: like-only (delegate to swipe planner).
    """
    goal = parse_bulk_goal(instruction)
    if not goal or goal.get("kind") != "message_new":
        return None
    if goal.get("error") or not (goal.get("message") or "").strip():
        return _fp(
            {
                "action": "fail",
                "reason": str(
                    goal.get("error") or "No message text for new-contact messaging"
                ),
                "planner": "bulk_message_new_heuristic",
                "llm_provider": None,
            },
            "bulk_message_new_missing_text",
        )
    app = (goal.get("app") or "").lower()
    planner = "bulk_message_new_heuristic"
    message = str(goal["message"]).strip()
    target = int(goal.get("count") or 1)
    st = state if isinstance(state, dict) else {}
    bulk = st.setdefault(
        "bulk_message_new",
        {"done": 0, "typed": False, "awaiting_send": False},
    )
    done = int(bulk.get("done") or 0)
    hist = " ".join(history[-16:]).lower()

    # Swipe-only apps: new-contact "message" = like only
    like_only = {
        "bumble",
        "yubo",
        "badoo",
        "blk",
        "taimi",
        "tinder",
        "facebook",
    }
    if app in like_only:
        # Rewrite as swipe so dry-run/like path runs
        fake = f"{app} like {target} profiles"
        return plan_bulk_swipe(
            fake,
            ui_tree,
            history,
            state=state,
            package=package,
            dry_run=dry_run,
        )

    opened = _ensure_app_open(app, package, history, planner)
    if opened:
        return opened

    if app == "hily" and hily_on_mbm(ui_tree):
        return hily_close_mbm(ui_tree, planner=planner) or _fp(
            {
                "action": "press_button",
                "button": "back",
                "reason": f"Close Hily MBM — skip paid new contact ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_hily_mbm_skip_new",
        )

    recover = _recover_to_root_action(app, ui_tree, history, planner, state=st)
    if recover:
        return recover

    if done >= target:
        return _fp(
            {
                "action": "done",
                "reason": (
                    f"New-contact messaging complete: {done}/{target} ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "dry_run": bool(dry_run),
            },
            "bulk_message_new_done",
        )

    if app == "tagged":
        loc = tagged_location_overlay_continue(ui_tree, planner=planner)
        if loc:
            return loc
        if tagged_on_deck(ui_tree):
            if dry_run:
                bulk["done"] = target
                st["bulk_message_new"] = bulk
                name = tagged_deck_card_name(ui_tree) or "match card"
                return _fp(
                    {
                        "action": "done",
                        "reason": (
                            f"[DRY RUN] would chatBtn → message {target} new "
                            f"contacts (verified on {name}) — no send ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": True,
                    },
                    "bulk_dry_run_tagged_new",
                )
            chat = tagged_chat_action(ui_tree, planner=planner)
            if chat:
                return chat
        return _fp(
            {
                "action": "fail",
                "reason": f"Tagged Match card / chatBtn not found ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "bulk_tagged_new_missing",
        )

    if app == "hinge":
        play = hinge_dismiss_play_review(ui_tree, planner=planner)
        if play:
            return play
        popup = hinge_dismiss_enable_prompt(ui_tree, planner=planner)
        if popup:
            return popup
        if hinge_on_like_sheet(ui_tree):
            compose = hinge_find_compose(ui_tree)
            if compose and not bulk.get("typed"):
                if "tap" in hist and "comment" in hist:
                    bulk["typed"] = True
                    st["bulk_message_new"] = bulk
                    return _fp(
                        {
                            "action": "type",
                            "text": message,
                            "reason": (
                                f"Type like-sheet comment for new contact "
                                f"({planner})"
                            ),
                            "planner": planner,
                            "llm_provider": None,
                            "dry_run": bool(dry_run),
                        },
                        "bulk_hinge_new_type",
                    )
                return _fp(
                    {
                        "action": "tap",
                        "x": compose[0],
                        "y": compose[1],
                        "reason": f"Focus Add a comment field ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "bulk_hinge_new_focus_comment",
                )
            if dry_run:
                bulk["done"] = target
                st["bulk_message_new"] = bulk
                return _fp(
                    {
                        "action": "done",
                        "reason": (
                            f"[DRY RUN] would Send Like with comment to "
                            f"{target} new profiles — never Rose ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": True,
                    },
                    "bulk_dry_run_hinge_new",
                )
            send = hinge_like_sheet_action(ui_tree, planner=planner)
            if send:
                bulk["done"] = done + 1
                bulk["typed"] = False
                st["bulk_message_new"] = bulk
                return send
        if not hinge_on_discover(ui_tree):
            act = hinge_open_discover_tab(planner=planner)
            act["dry_run"] = bool(dry_run)
            return act
        if dry_run and hinge_on_discover(ui_tree):
            card = hinge_deck_card_name(ui_tree) or "Discover"
            bulk["done"] = target
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] would heart → like sheet → Send Like to "
                        f"{target} new profiles (verified on {card}) "
                        f"— never Rose ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                    "needs_vision": True,
                },
                "bulk_dry_run_hinge_new_discover",
            )
        # Live: heart is vision-only on Discover — mark for vision path
        return _fp(
            {
                "action": "wait",
                "seconds": 0.5,
                "reason": (
                    f"Hinge Discover heart requires vision tap "
                    f"(x≈937) then like sheet ({planner})"
                ),
                "planner": planner,
                "llm_provider": None,
                "needs_vision": True,
                "vision_hint": "hinge_heart",
            },
            "bulk_hinge_new_need_vision",
        )

    if app == "hily":
        if hily_on_photo_viewer(ui_tree):
            return hily_back_from_photo_viewer(planner=planner)
        if hily_on_top_picks_grid(ui_tree):
            tile_taps = sum(
                1
                for h in history[-8:]
                if "grid tile" in str(h).lower()
                or "bulk_hily_new_grid_tile" in str(h).lower()
            )
            tile = hily_first_grid_tile_center(ui_tree)
            if tile and tile_taps < 1:
                return _fp(
                    {
                        "action": "tap",
                        "x": tile[0],
                        "y": tile[1],
                        "reason": f"Open Hily grid tile for new message ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "bulk_hily_new_grid_tile",
                )
        # Dry-run must verify a real profile + message/like control — never bare done
        card = hily_deck_card_name(ui_tree)
        like_ctl = hily_like_action(ui_tree, planner=planner)
        compose = _tree_node_center(
            ui_tree, "Type a message", "Message", "Say something"
        ) or _tree_id_center(ui_tree, "messageInput", "id/messageInput")
        if dry_run:
            if not card and not like_ctl and not compose:
                return _fp(
                    {
                        "action": "fail",
                        "reason": (
                            f"dry_run — Hily: no profile card / like / composer "
                            f"verified for {target} new contacts ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                        "dry_run": True,
                        "dry_run_verified": False,
                    },
                    "bulk_dry_run_hily_new_unverified",
                )
            bulk["done"] = target
            st["bulk_message_new"] = bulk
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"[DRY RUN] would first-message {target} new Hily "
                        f"contacts (verified on {card or 'like/composer'}) "
                        f"— skip MBM/paid ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "dry_run_verified": True,
                },
                "bulk_dry_run_hily_new",
            )
        if like_ctl:
            return like_ctl

    return _fp(
        {
            "action": "fail",
            "reason": (
                f"New-contact messaging not supported / screen unknown "
                f"for {app or 'app'} ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
        },
        "bulk_message_new_unsupported",
    )


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
            not in (
                "facebook",
                "bumble",
                "yubo",
                "badoo",
                "hily",
                "blk",
                "taimi",
                "hinge",
                "tagged",
            )
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
    if goal["kind"] == "message_new":
        return plan_bulk_message_new(
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
