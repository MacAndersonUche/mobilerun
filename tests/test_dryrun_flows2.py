"""More real-phone dry-run bugs after #60: swipe-guard false positive,
Match%02d invent, scroll caps, quote-before-to parse, WhatsApp first-N chats.
"""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    MAX_LIST_SCROLLS,
    _chat_list_screen_verified,
    _is_fake_chats_bench,
    _open_chats_tab_action,
    parse_bulk_goal,
    plan_bulk_message,
)
from backend.cloud_agent import (
    _action_looks_like_swipe_or_like,
    _is_chat_list_scroll_swipe,
    _same_tap_key,
    apply_dry_run_send_guard,
    plan_next_action,
)
from backend.dm_heuristics import (
    parse_dm_instruction,
    parse_existing_chats_instruction,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- 1. Swipe/like guard must not flag nav taps ---


def test_bulk_open_deck_not_flagged_as_like_swipe():
    action = {
        "action": "tap",
        "x": 341,
        "y": 2190,
        "reason": "Open swipe deck (bulk_swipe_heuristic)",
        "fastpath_step": "bulk_open_deck",
    }
    assert not _action_looks_like_swipe_or_like(action, "tap")
    kind, _, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "tap"
    assert out is action


def test_bulk_open_chats_not_flagged():
    action = {
        "action": "tap",
        "x": 341,
        "y": 2190,
        "reason": "Open chats/messages tab (bulk_message_heuristic)",
        "fastpath_step": "bulk_open_chats",
    }
    assert not _action_looks_like_swipe_or_like(action, "tap")


def test_bulk_like_still_flagged():
    action = {
        "action": "tap",
        "x": 750,
        "y": 1959,
        "reason": "Like profile 1/5 (bulk_swipe_heuristic)",
        "fastpath_step": "bulk_like",
        "label": "Like",
    }
    assert _action_looks_like_swipe_or_like(action, "tap")


# --- 2. No Match%02d on real apps; open Chats tab first ---


def test_real_app_opens_chats_tab_before_inventing_rows():
    # Hily finder (deck) — no chat rows
    tree = _load("hily_finder.xml")
    st: dict = {}
    act = plan_bulk_message(
        'reply "hey how are you" to 5 existing chats on hily',
        tree,
        ["Opened Hily — launch"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act and act["action"] == "tap"
    assert act.get("fastpath_step") == "bulk_open_chats"
    assert "Match01" not in (act.get("reason") or "")


def test_real_app_fails_without_chat_list_no_match_pct_scroll():
    # Nav-only tree after open-chats already attempted
    tree = """
    <hierarchy packages="com.hily.app"><w p="com.hily.app">
     <n d="Finder" c="1" xy="142,2190"/>
     <n d="Chats" c="1" xy="341,2190"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_message(
        'reply "hey" to 3 existing chats on hily',
        tree,
        [
            "Opened Hily — launch",
            "Tapped (341,2190) — Open chats/messages tab (bulk_message_heuristic)",
        ],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act and act["action"] == "fail"
    reason = (act.get("reason") or "").lower()
    assert "chat list" in reason or "no chat" in reason or "not verified" in reason


def test_match_pct_only_on_fake_chats_bench():
    assert _is_fake_chats_bench(
        '<n t="Match01" xy="100,100"/>', package="com.tinder", instruction="fake-chats"
    )
    assert _is_fake_chats_bench('<hierarchy><n t="Match03"/></hierarchy>')
    assert not _is_fake_chats_bench(
        _load("hily_chats.xml"), package="com.hily.app", instruction="hily reply"
    )


def test_hily_chats_list_verified():
    assert _chat_list_screen_verified("hily", _load("hily_chats.xml"))
    assert not _chat_list_screen_verified("hily", _load("hily_finder.xml"))


def test_open_chats_tab_uses_ui_map_xy():
    tree = _load("hily_finder.xml")
    act = _open_chats_tab_action("hily", tree, [], "bulk_message_heuristic")
    assert act and (act["x"], act["y"]) == (341, 2190)


# --- 3. Scroll cap + same-action key for swipes ---


def test_same_action_key_for_swipes():
    a = {
        "action": "swipe",
        "x1": 540,
        "y1": 1800,
        "x2": 540,
        "y2": 700,
    }
    assert _same_tap_key(a) == "swipe:540,1800->540,700"


def test_list_scroll_capped_and_requires_verified_flag():
    chats = _load("hily_chats.xml")
    # Skip every visible row label (name + preview) so planner must scroll
    st = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "done_names": ["Evie", "hey there"],
            "scroll_count": 0,
        }
    }
    act = plan_bulk_message(
        'reply "hey" to 5 existing chats on hily',
        chats,
        ["Opened Hily — launch", "Open chats tab"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act and act["action"] == "swipe"
    assert act.get("chat_list_verified") is True
    assert act.get("fastpath_step") == "bulk_scroll"

    # Unverified scroll blocked in dry_run
    unverified = {
        "action": "swipe",
        "x1": 540,
        "y1": 1800,
        "x2": 540,
        "y2": 700,
        "reason": "Scroll chat list",
        "fastpath_step": "bulk_scroll",
    }
    assert not _is_chat_list_scroll_swipe(unverified, "swipe")
    kind, _, _ = apply_dry_run_send_guard(
        dry_run=True, action=unverified, kind="swipe", reason=unverified["reason"]
    )
    assert kind == "done"  # blocked

    verified = {**unverified, "chat_list_verified": True}
    assert _is_chat_list_scroll_swipe(verified, "swipe")
    kind2, _, out2 = apply_dry_run_send_guard(
        dry_run=True, action=verified, kind="swipe", reason=verified["reason"]
    )
    assert kind2 == "swipe"
    assert out2 is verified

    # Cap
    st["bulk_message"]["scroll_count"] = MAX_LIST_SCROLLS
    act2 = plan_bulk_message(
        'reply "hey" to 5 existing chats on hily',
        chats,
        ["Opened Hily — launch", "scroll"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act2 and act2["action"] == "fail"


# --- 4. parse_bulk_goal quote-before-to; never default 50 ---


def test_parse_reply_quoted_before_to():
    g = parse_bulk_goal('reply "hey how are you" to 5 existing chats on hily')
    assert g and g["kind"] == "message"
    assert g["count"] == 5
    assert g["message"] == "hey how are you"
    assert g["app"] == "hily"


def test_parse_message_quoted_whatsapp_existing():
    g = parse_bulk_goal('message "hey how are you" to 1 existing chat on WhatsApp')
    assert g and g["count"] == 1
    assert g["message"] == "hey how are you"
    assert g["app"] == "whatsapp"


def test_parse_existing_chats_without_count_fails():
    g = parse_bulk_goal('reply "hi" to existing chats on hily')
    assert g and g.get("error")
    assert g.get("count") == 0


# --- 5. WhatsApp first-N existing chats via parse_dm_instruction ---


def test_parse_dm_existing_chats_whatsapp():
    p = parse_dm_instruction('message "hey how are you" to 1 existing chat on WhatsApp')
    assert p is not None
    assert p["app"] == "whatsapp"
    assert p["message"] == "hey how are you"
    assert int(p.get("existing_count") or 0) == 1
    assert str(p["contact"]).startswith("__existing_")


def test_parse_existing_chats_helper():
    e = parse_existing_chats_instruction(
        'reply "hey how are you" to 5 existing chats on WhatsApp'
    )
    assert e and e["count"] == 5 and e["app"] == "whatsapp"


def test_plan_next_action_routes_whatsapp_existing_to_bulk(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("LLM must not be called")

    monkeypatch.setattr("backend.cloud_agent._call_gemini", boom)
    monkeypatch.setattr("backend.cloud_agent._call_openai", boom)
    # WhatsApp home-ish list
    tree = """
    <hierarchy packages="com.whatsapp"><w p="com.whatsapp">
     <n t="Alice" i="conversations_row_contact_name" c="1" xy="300,500"/>
     <n t="Bob" i="conversations_row_contact_name" c="1" xy="300,700"/>
    </w></hierarchy>
    """
    a = plan_next_action(
        'message "hey how are you" to 1 existing chat on WhatsApp',
        tree,
        ["Opened WhatsApp — launch"],
        package="com.whatsapp",
        dry_run=True,
        agent_state={},
    )
    assert a is not None
    assert a.get("action") in ("tap", "open_app", "type", "wait", "done", "fail")
    # Must not be an AI fail without contact
    assert "LLM" not in (a.get("reason") or "")
    if a.get("action") == "tap":
        assert (
            "Alice" in (a.get("reason") or "")
            or "chat" in (a.get("reason") or "").lower()
        )
