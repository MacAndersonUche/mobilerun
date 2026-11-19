"""Bulk swipe/message heuristics — real-app safety + dry_run + parse."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    deck_card_name,
    parse_bulk_goal,
    plan_bulk_message,
    plan_bulk_swipe,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_bulk_swipe():
    g = parse_bulk_goal("tinder auto-swipe 50 profiles")
    assert g and g["kind"] == "swipe" and g["count"] == 50


def test_parse_bulk_message_bank_text():
    g = parse_bulk_goal('hinge auto-message 50 matches tell them "hi baby"')
    assert g and g["kind"] == "message"
    assert g["message"] == "hi baby"
    assert g["count"] == 50


def test_parse_bulk_rejects_mixed_swipe_and_chat():
    """Swipe + open chat/reply must not be swallowed as bulk-only."""
    mixed = [
        "bumble auto-swipe 50 profiles then open chat and reply hi baby",
        "yubo swipe 10 profiles and open chats then message Sam say hi",
        "badoo auto-swipe 50 then reply to matches",
        "tinder swipe 50 profiles then send a message to Alex say hey",
    ]
    for instr in mixed:
        assert parse_bulk_goal(instr) is None, instr


def test_bulk_swipe_like_awaits_name_change_before_count():
    tree1 = """
    <hierarchy><w>
     <n t="Profile01" d="Profile Profile01" xy="540,900" e="0"/>
     <n t="" d="Like" xy="860,2100" c="1" e="0"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "tinder auto-swipe 50 profiles", tree1, [], state=st, package="com.tinder"
    )
    assert act and act.get("action") == "tap"
    assert (act["x"], act["y"]) == (860, 2100)
    # Must NOT increment until top card name changes
    assert st.get("bulk_swipe", {}).get("done") == 0
    assert st.get("bulk_swipe", {}).get("awaiting_verify") is True

    tree2 = """
    <hierarchy><w>
     <n t="Profile02" d="Profile Profile02" xy="540,900" e="0"/>
     <n t="" d="Like" xy="860,2100" c="1" e="0"/>
    </w></hierarchy>
    """
    act2 = plan_bulk_swipe(
        "tinder auto-swipe 50 profiles", tree2, [], state=st, package="com.tinder"
    )
    assert st.get("bulk_swipe", {}).get("done") == 1
    assert act2 and act2.get("action") == "tap"


def test_bulk_swipe_never_uses_nav_fallback_coords():
    """Missing Like → fail; never (950,2200) nav-tab guess."""
    tree = """
    <hierarchy><w>
     <n t="Profile01" xy="540,900"/>
     <n d="Chats" xy="950,2200" c="1"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "tinder auto-swipe 5 profiles", tree, [], state=st, package="com.tinder"
    )
    assert act and act.get("action") == "fail"
    assert "coord" in (act.get("reason") or "").lower()
    assert st.get("bulk_swipe", {}).get("done") == 0


def test_bumble_bulk_uses_like_swipe_not_nav_tap():
    deck = _load("bumble_deck.xml")
    assert deck_card_name("bumble", deck) == "Alex"
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        deck,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
    )
    assert act and act.get("action") == "swipe"
    assert (act["x1"], act["y1"], act["x2"], act["y2"]) == (250, 1000, 1050, 1050)
    # Must not tap Chats nav (972,2197) or People (540,2197)
    assert act.get("action") != "tap"
    assert st.get("bulk_swipe", {}).get("done") == 0
    assert st.get("bulk_swipe", {}).get("awaiting_verify") is True

    # Same name → still no increment
    act_same = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        deck,
        [],
        state=st,
        package="com.bumble.app",
    )
    assert st.get("bulk_swipe", {}).get("done") == 0
    # Next card
    next_deck = deck.replace("Alex, 28", "Jordan, 25").replace("Alex’s", "Jordan’s")
    assert deck_card_name("bumble", next_deck) == "Jordan"
    plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        next_deck,
        [],
        state=st,
        package="com.bumble.app",
    )
    assert st.get("bulk_swipe", {}).get("done") == 1
    assert act_same is not None


def test_yubo_bulk_uses_like_swipe():
    deck = _load("yubo_deck.xml")
    assert deck_card_name("yubo", deck) == "Sam"
    st: dict = {}
    act = plan_bulk_swipe(
        "yubo auto-swipe 5 profiles",
        deck,
        ["Opened Yubo — launch"],
        state=st,
        package="co.yellw.yellowapp",
    )
    assert act and act.get("action") == "swipe"
    assert (act["x1"], act["y1"], act["x2"], act["y2"]) == (250, 1000, 1050, 1050)
    # Never Yubucks pill
    assert (act.get("x"), act.get("y")) != (840, 158)


def test_badoo_bulk_uses_voteyes_not_y2000_filter():
    """VoteYes at (855,1982) must work (old filter required y>=2000)."""
    tree = _load("badoo_encounters.xml")
    assert deck_card_name("badoo", tree) == "Alex"
    st: dict = {}
    act = plan_bulk_swipe(
        "badoo auto-swipe 5 profiles",
        tree,
        ["Opened Badoo — launch"],
        state=st,
        package="com.badoo.mobile",
    )
    assert act and act.get("action") == "tap"
    assert (act["x"], act["y"]) == (855, 1982)
    # Not Crush / Chat-before-match / nav
    assert (act["x"], act["y"]) not in ((1000, 1900), (540, 1982), (756, 2210))
    assert st.get("bulk_swipe", {}).get("done") == 0


def test_bulk_swipe_dry_run_skips_like():
    deck = _load("bumble_deck.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        deck,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run") is True
    assert "like skipped" in (act.get("reason") or "").lower()
    assert st.get("bulk_swipe", {}).get("done") == 0


def test_bulk_message_dry_run_stops_before_send():
    chat = """
    <hierarchy packages="com.tinder"><w p="com.tinder">
     <n t="Match01" xy="400,148" b="200,100,600,196"/>
     <n e="1" f="1" t="" h="Type a message" i="id/message_input" xy="540,2050"
        b="80,2000,900,2100"/>
     <n d="Send" i="id/send_button" c="1" xy="1000,2050" b="940,2000,1060,2100"/>
    </w></hierarchy>
    """
    st = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": "Match01",
            "typed": True,
            "counted_current": False,
        }
    }
    act = plan_bulk_message(
        "tinder auto-message 5 matches tell them hi baby",
        chat,
        ["Opened Tinder — launch", "tap — Open Match01", "type — hi baby"],
        state=st,
        package="com.tinder",
        dry_run=True,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run") is True
    assert "send skipped" in (act.get("reason") or "").lower()
    assert act.get("fastpath_step") == "bulk_dry_run_skip_send"


def test_bulk_message_send_reason_is_bulk_send_step():
    """Guard relies on fastpath_step=bulk_send (reason is 'Send to …')."""
    chat = """
    <hierarchy packages="com.tinder"><w p="com.tinder">
     <n t="Match01" xy="400,148"/>
     <n e="1" f="1" h="Type a message" i="id/message_input" xy="540,2050"/>
     <n d="Send" i="id/send_button" c="1" xy="1000,2050"/>
    </w></hierarchy>
    """
    st = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": "Match01",
            "typed": True,
            "counted_current": False,
        }
    }
    act = plan_bulk_message(
        "tinder auto-message 5 matches tell them hi baby",
        chat,
        [],
        state=st,
        package="com.tinder",
        dry_run=False,
    )
    assert act and act.get("action") == "tap"
    assert act.get("fastpath_step") == "bulk_send"
    assert "Send to Match01" in (act.get("reason") or "")
    # Reason does NOT start with "tap send" — old guard would miss this
    assert not (act.get("reason") or "").lower().startswith("tap send")


def test_out_of_likes_stops():
    tree = """
    <n t="Out of likes" d="Out of likes" xy="540,900" e="0"/>
    <n t="Maybe later" d="Maybe later" xy="540,1400" c="1" e="0"/>
    """
    st = {"bulk_swipe": {"done": 40, "target": 50}}
    act = plan_bulk_swipe(
        "tinder auto-swipe 50 profiles", tree, [], state=st, package="com.tinder"
    )
    assert act and act.get("action") == "done"
    assert act.get("stopped_reason") == "out_of_likes"


def test_cloud_agent_dry_run_guard_blocks_bulk_send_step():
    """Step-type guard must catch bulk_send even when reason is 'Send to …'."""
    from backend.cloud_agent import apply_dry_run_send_guard

    action = {
        "action": "tap",
        "x": 1000,
        "y": 2050,
        "reason": "Send to Match01 (bulk_message_heuristic)",
        "fastpath_step": "bulk_send",
        "_fastpath_step": "bulk_send",
    }
    # Old reason-only guard would miss this:
    low_r = action["reason"].lower()
    assert not ("tap send" in low_r or low_r.startswith("tap send"))
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert out.get("dry_run") is True
    assert "send skipped" in reason.lower()
