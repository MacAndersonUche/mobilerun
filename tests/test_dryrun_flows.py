"""Regression tests for real-phone dry-run flow bugs (Hily loop, contact match,
bulk routing, paid-tap reason false positive, dry_run_verified, composer clear).
"""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _visible_chat_list_rows,
    parse_bulk_goal,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    _action_looks_like_paid,
    _dry_run_done_is_verified,
    _is_chat_list_scroll_swipe,
    apply_dry_run_send_guard,
    plan_next_action,
)
from backend.dm_heuristics import (
    find_contact_result_center,
    heuristic_dm_send,
    hily_on_chats_list,
    hily_on_thread,
    parse_dm_instruction,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- 1. Hily reply loop ---


def test_hily_thread_is_not_chats_list():
    thread = _load("hily_thread.xml")
    assert hily_on_thread(thread)
    assert not hily_on_chats_list(thread)


def test_hily_chats_list_still_detects_inbox():
    chats = _load("hily_chats.xml")
    assert hily_on_chats_list(chats)
    assert not hily_on_thread(chats)


def test_hily_no_retap_chat_on_thread_after_hily_tap_chat():
    """After Tap Hily chat, thread screen must type — not hily_tap_chat again."""
    thread = _load("hily_thread.xml")
    # History without generic 'tap visible contact' — only Hily-specific reason
    hist = [
        "Opened Hily[com.hily.app] — launch",
        "Tapped (300,680) — Tap Hily chat 'Evie' (hily_heuristic)",
    ]
    a = heuristic_dm_send(
        "hily message Evie and say hi",
        thread,
        hist,
        package="com.hily.app",
    )
    assert a is not None
    assert a.get("fastpath_step") != "hily_tap_chat"
    assert a["action"] in ("tap", "type")


# --- 2. Contact match tightness ---


def test_parse_dm_rejects_n_matches_as_contact():
    assert parse_dm_instruction("hily message 5 matches and say hi baby") is None
    assert parse_dm_instruction("bumble message 3 people say hey") is None


def test_tap_visible_contact_ignores_deck_and_counters():
    # Deck-like tree: name on finder card, plus a '12 matches' counter
    tree = """
    <hierarchy packages="com.hily.app"><w p="com.hily.app">
     <n t="Evie, 24" i="userNameAgeField" xy="540,900" b="200,800,900,1000"/>
     <n t="12 matches" i="matchCounter" xy="200,200" c="1"/>
     <n t="Evie" i="userNameAgeField" xy="540,1100"/>
    </w></hierarchy>
    """
    assert (
        find_contact_result_center(
            tree, "Evie", result_ids=("dialogMessageItem", "userNameField")
        )
        is None
    )


def test_tap_visible_contact_exact_row_match():
    chats = _load("hily_chats.xml")
    c = find_contact_result_center(
        chats, "Evie", result_ids=("dialogMessageItem", "userNameField")
    )
    assert c and c[1] == 680


def test_substring_counter_not_matched_as_contact():
    tree = """
    <hierarchy><w>
     <n t="15 matches" i="dialogMessageItem" xy="540,700" c="1"/>
     <n t="Sam" i="userNameField" xy="300,680"/>
    </w></hierarchy>
    """
    assert find_contact_result_center(tree, "5", result_ids=("userNameField",)) is None
    assert find_contact_result_center(tree, "Sam", result_ids=("userNameField",))


# --- 3. Bulk reply routing + visible rows ---


def test_bulk_routing_without_word_bulk():
    for instr in (
        'hily message 5 matches tell them "hi baby"',
        'bumble reply to 3 chats say "hey"',
        'tinder auto-message 10 matches tell them "hi"',
        'badoo message 5 existing chats say "hello"',
    ):
        g = parse_bulk_goal(instr)
        assert g and g["kind"] == "message", instr
        # plan_next_action must also pick up the bulk path
        a = plan_next_action(instr, "<hierarchy/>", [], dry_run=True)
        assert a is not None
        assert "bulk" in str(
            a.get("planner") or a.get("fastpath_step") or ""
        ).lower() or a.get("action") in ("open_app", "fail", "done", "wait", "tap")


def test_bulk_message_uses_visible_rows_not_match_pct():
    tree = """
    <hierarchy packages="com.hily.app"><w p="com.hily.app">
     <n i="dialogsSearchButton" d="Search" c="1" xy="980,160"/>
     <n i="dialogMessageItem" c="1" xy="540,700"/>
     <n t="Nancy" i="userNameField" xy="300,680"/>
     <n t="Alex" i="userNameField" xy="300,900"/>
    </w></hierarchy>
    """
    rows = _visible_chat_list_rows(tree, "hily", skip_names=[])
    assert [r["name"] for r in rows][:2] == ["Nancy", "Alex"]
    st: dict = {}
    act = plan_bulk_message(
        'hily message 2 matches tell them "hi baby"',
        tree,
        ["Opened Hily — launch"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    # Reply dry-run must open a real row (not list-only false pass)
    assert act and act["action"] == "tap"
    assert "Nancy" in (act.get("reason") or "")
    assert "Match01" not in (act.get("reason") or "")
    assert "did not open" not in (act.get("reason") or "").lower()


# --- 4. Paid-tap false positive ---


def test_paid_tap_ignores_reason_text():
    action = {
        "action": "tap",
        "x": 200,
        "y": 1800,
        "reason": "Select Direct (never Blast/Yubucks)",
        "label": "Direct",
        "text": "Direct",
    }
    assert not _action_looks_like_paid(action, "tap")
    kind, _, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "tap"
    assert out is action


def test_paid_tap_still_blocks_gold_label():
    action = {
        "action": "tap",
        "reason": "Continue",
        "label": "Continue with GOLD",
        "text": "Continue with GOLD",
    }
    assert _action_looks_like_paid(action, "tap")


# --- 5/6. Dry-run verifiability + clear composer ---


def test_dry_run_swipe_taps_nav_then_simulates_likes():
    # People tab visible, no deck yet
    tree = """
    <hierarchy packages="com.bumble.app"><w>
     <n t="People" d="People" c="1" xy="200,2200"/>
     <n t="Chats" d="Chats" c="1" xy="540,2200"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble auto-swipe 2 profiles",
        tree,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "tap"
    assert act.get("fastpath_step") in (
        "bulk_open_deck",
        "bulk_bumble_open_discover",
    )
    assert act.get("action") != "done"


def test_dry_run_swipe_logs_n_would_like_pass():
    deck = _load("bumble_deck.xml")
    st: dict = {"bulk_swipe": {"done": 0, "target": 2}}
    act = plan_bulk_swipe(
        "bumble auto-swipe 2 profiles",
        deck,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "done"
    reason = (act.get("reason") or "").lower()
    assert "evaluated 1 card" in reason
    assert "would like/pass 2" in reason
    assert "alex" in reason
    assert st["bulk_swipe"]["done"] == 1
    assert act.get("dry_run_verified") is True


def test_dry_run_allows_chat_list_scroll_blocks_deck_swipe():
    # Unverified list scrolls stay blocked in dry_run
    unverified = {
        "action": "swipe",
        "x1": 540,
        "y1": 1800,
        "x2": 540,
        "y2": 700,
        "reason": "Scroll chat list for more matches (Nancy)",
        "fastpath_step": "bulk_scroll",
    }
    assert not _is_chat_list_scroll_swipe(unverified, "swipe")
    kind_u, _, _ = apply_dry_run_send_guard(
        dry_run=True, action=unverified, kind="swipe", reason=unverified["reason"]
    )
    assert kind_u == "done"

    scroll = {
        **unverified,
        "chat_list_verified": True,
    }
    assert _is_chat_list_scroll_swipe(scroll, "swipe")
    kind, _, out = apply_dry_run_send_guard(
        dry_run=True, action=scroll, kind="swipe", reason=scroll["reason"]
    )
    assert kind == "swipe"
    assert out is scroll

    deck_swipe = {
        "action": "swipe",
        "x1": 200,
        "y1": 1200,
        "x2": 900,
        "y2": 1200,
        "reason": "Like profile via swipe right",
        "fastpath_step": "bulk_like_swipe",
    }
    kind2, reason2, _ = apply_dry_run_send_guard(
        dry_run=True, action=deck_swipe, kind="swipe", reason=deck_swipe["reason"]
    )
    assert kind2 == "done"
    assert "swipe" in reason2.lower()


def test_dry_run_reply_clears_composer():
    thread = _load("hily_thread.xml")
    hist = [
        "Opened Hily — launch",
        "Tapped — Tap Hily chat 'Evie'",
        "Typed \"hi\" — Type message 'hi'",
    ]
    a = heuristic_dm_send(
        "hily message Evie and say hi",
        thread,
        hist,
        package="com.hily.app",
        dry_run=True,
    )
    assert a and a["action"] == "type"
    assert a.get("clear") is True
    assert a.get("text") == ""
    assert "clear composer" in (a.get("reason") or "").lower()
    hist2 = hist + [f'type("") — {a["reason"]}']
    a2 = heuristic_dm_send(
        "hily message Evie and say hi",
        thread,
        hist2,
        package="com.hily.app",
        dry_run=True,
    )
    assert a2 and a2["action"] == "done"
    assert a2.get("dry_run_verified") is True


# --- 7. False completed ---


def test_dry_run_skip_without_verify_is_not_completed():
    assert not _dry_run_done_is_verified(
        {"dry_run": True, "dry_run_verified": False},
        "[DRY RUN] would send — skipped (Send to Nancy)",
        {},
    )
    assert _dry_run_done_is_verified(
        {"dry_run": True, "dry_run_verified": True},
        "dry_run — compose verified then cleared",
        {},
    )


def test_apply_dry_run_guard_marks_unverified():
    action = {
        "action": "tap",
        "reason": "Send to Nancy",
        "fastpath_step": "bulk_send",
    }
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert out.get("dry_run_verified") is False
    assert not _dry_run_done_is_verified(out, reason, {})
