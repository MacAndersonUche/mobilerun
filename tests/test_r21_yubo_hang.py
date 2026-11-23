"""r21: Yubo same-coord hang fail-fast + Social is not a card name."""

from backend.dm_heuristics import yubo_deck_card_name, yubo_on_deck
from backend.bulk_bench_heuristics import plan_bulk_message, deck_card_name
from backend.cloud_agent import MAX_SAME_COORD_ANY, MAX_SAME_TAP, _same_tap_key


def test_yubo_deck_rejects_social_tab_label():
    # Top filter "Social" at left edge must not count as the card person
    tree = (
        '<hierarchy><w p="co.yellw.yellowapp" f="1">'
        '<n t="Social" xy="120,180" b="42,150,280,210"/>'
        '<n t="50+" xy="60,400" b="42,380,100,420"/>'
        '<n t="Send a message" xy="540,1800" c="1"/>'
        "</w></hierarchy>"
    )
    assert yubo_deck_card_name(tree) is None
    assert deck_card_name("yubo", tree) is None
    assert yubo_on_deck(tree) is False


def test_yubo_deck_still_finds_real_name():
    tree = (
        '<hierarchy><w p="co.yellw.yellowapp" f="1">'
        '<n t="Social" xy="120,180" b="42,150,280,210"/>'
        '<n t="Sam" xy="200,500" b="42,470,360,540"/>'
        '<n t="Send a message" xy="540,1800" c="1"/>'
        "</w></hierarchy>"
    )
    assert yubo_deck_card_name(tree) == "Sam"
    assert deck_card_name("yubo", tree) == "Sam"
    assert yubo_on_deck(tree) is True


def test_yubo_reply_does_not_retap_chat_tab_forever():
    """After Yubo Chat-tab-by-index + settle, next plan is vision then fail —
    never empty-history re-tap(341,2194)."""
    tree = (
        '<hierarchy><w p="co.yellw.yellowapp" f="1">'
        '<n t="Social" xy="120,180" b="42,150,280,210"/>'
        '<n c="1" xy="341,2194" b="280,2140,400,2240"/>'
        '<n c="1" xy="540,2194" b="480,2140,600,2240"/>'
        '<n c="1" xy="739,2194" b="680,2140,800,2240"/>'
        '<n c="1" xy="938,2194" b="880,2140,1000,2240"/>'
        "</w></hierarchy>"
    )
    state = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": None,
            "_chats_settle_done": True,
            "_chats_settle_n": 1,
            "_chats_tab_taps": 1,
        }
    }
    hist = [
        "Opened Yubo[open_ok]",
        "tap(341,2194) — Open Yubo Chat tab by index (bulk_open_chats)",
        "wait — Settle 1.5s after chats tab before re-check",
    ]
    act = plan_bulk_message(
        'reply to 5 chats on Yubo with "hey"',
        tree,
        hist,
        package="co.yellw.yellowapp",
        dry_run=True,
        state=state,
    )
    assert act is not None
    # First post-settle: vision locate (not another fixed-xy tap)
    assert act.get("action") == "wait"
    assert act.get("needs_vision") or act.get("_force_vision")
    assert "vision" in (act.get("reason") or "").lower()
    assert not (
        act.get("action") == "tap"
        and int(act.get("y") or 0) >= 2100
    )

    # Second call: fail fast — still no chat list
    state["bulk_message"]["_chats_vision_n"] = 1
    hist2 = hist + [
        "wait — Vision locate yubo Chats/messages tab (speech bubble / per-app map)"
    ]
    act2 = plan_bulk_message(
        'reply to 5 chats on Yubo with "hey"',
        tree,
        hist2,
        package="co.yellw.yellowapp",
        dry_run=True,
        state=state,
    )
    assert act2 is not None
    assert act2.get("action") == "fail"
    reason = (act2.get("reason") or "").lower()
    assert "fail fast" in reason or "not verified" in reason


def test_same_tap_key_and_caps_defined():
    assert _same_tap_key({"action": "tap", "x": 342, "y": 2194}) == "tap:342,2194"
    assert MAX_SAME_COORD_ANY >= MAX_SAME_TAP
    assert MAX_SAME_TAP >= 2
