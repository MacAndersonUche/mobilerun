"""r21 root-cause: chat rows, Treasure skip, watchdog keys, Social/Yubo names."""

from backend.bulk_bench_heuristics import (
    _visible_chat_list_rows,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    MAX_SAME_DECISION,
    NO_PROGRESS_TIMEOUT_S,
    _planner_decision_key,
    _same_tap_key,
)
from backend.dm_heuristics import badoo_dismiss_popup, yubo_deck_card_name


def _yubo_conversations_real() -> str:
    """Mac real strings: Conversations + Roch/Leah/Marcia/Hafsa/Amie ♡."""
    return (
        '<hierarchy windows="1" nodes="30" empty="false" mode="compact" '
        'packages="co.yellw.yellowapp">'
        '<w id="active" t="active" p="co.yellw.yellowapp" f="1">'
        '<n t="Conversations" xy="200,1100" b="40,1072,400,1140"/>'
        '<n t="Roch" xy="242,1200" b="200,1160,360,1240"/>'
        '<n t="Heyy" xy="300,1260" b="200,1240,500,1280"/>'
        '<n t="Leah" xy="242,1380" b="200,1340,360,1420"/>'
        '<n t="Good u" xy="300,1440" b="200,1420,500,1480"/>'
        '<n t="Marcia" xy="242,1560" b="200,1520,400,1600"/>'
        '<n t="Hafsa" xy="242,1740" b="200,1700,360,1780"/>'
        '<n t="Amie ♡" xy="242,1920" b="200,1880,400,1960"/>'
        '<n t="You: hey how are you" xy="400,1980" b="200,1960,700,2020"/>'
        '<n c="1" xy="341,2194" b="280,2140,400,2240"/>'
        "</w></hierarchy>"
    )


def test_yubo_plain_text_chat_rows_from_real_strings():
    tree = _yubo_conversations_real()
    rows = _visible_chat_list_rows(tree, "yubo")
    names = [r["name"] for r in rows]
    assert "Roch" in names
    assert "Leah" in names
    assert "Marcia" in names
    assert "Hafsa" in names
    # Heart suffix allowed
    assert any(n.startswith("Amie") for n in names)
    # Previews must not become rows
    assert "Heyy" not in names
    assert "Good u" not in names
    assert "You: hey how are you" not in names
    assert "Conversations" not in names


def test_yubo_reply_picks_roch_not_scroll_fail():
    tree = _yubo_conversations_real()
    state = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": None,
            "chat_list_verified": True,
        }
    }
    act = plan_bulk_message(
        'reply to 5 chats on Yubo with "hey"',
        tree,
        ["Opened Yubo[open_ok]", "tap — Open Yubo Chat tab by index"],
        package="co.yellw.yellowapp",
        dry_run=True,
        state=state,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "Roch" in (act.get("reason") or "")
    assert "No chat-list rows" not in (act.get("reason") or "")


def test_blk_plain_name_rows_still_work():
    tree = (
        '<hierarchy><w p="com.affinityapps.blk" f="1">'
        '<n t="Matches" xy="540,200"/>'
        '<n t="Your turn" xy="200,400"/>'
        '<n t="Neff" xy="300,600"/>'
        '<n t="hey there" xy="300,660"/>'
        "</w></hierarchy>"
    )
    rows = _visible_chat_list_rows(tree, "blk")
    names = [r["name"] for r in rows]
    assert "Neff" in names
    assert "hey there" not in names


def test_hily_matches_chrome_plain_names():
    tree = (
        '<hierarchy><w p="com.hily.app" f="1">'
        '<n t="Matches" xy="200,200"/>'
        '<n t="All" xy="400,200"/>'
        '<n t="Unread" xy="600,200"/>'
        '<n t="Sofia" xy="300,800"/>'
        '<n t="hi babe" xy="300,860"/>'
        "</w></hierarchy>"
    )
    rows = _visible_chat_list_rows(tree, "hily")
    names = [r["name"] for r in rows]
    assert "Sofia" in names
    assert "All" not in names
    assert "Unread" not in names
    assert "hi babe" not in names


def test_badoo_treasure_dismiss_and_not_a_row():
    tree = (
        '<hierarchy><w p="com.badoo.mobile" f="1">'
        '<n t="Treasure" xy="337,1718" c="1"/>'
        '<n t="Open Treasure" xy="540,1800" c="1"/>'
        '<n t="Close" xy="100,200" c="1"/>'
        '<n t="Ada" xy="300,900"/>'
        "</w></hierarchy>"
    )
    rows = _visible_chat_list_rows(tree, "badoo")
    names = [r["name"].lower() for r in rows]
    assert "treasure" not in names
    assert "open treasure" not in names
    pop = badoo_dismiss_popup(tree)
    assert pop is not None
    assert "treasure" in (pop.get("reason") or "").lower()


def test_badoo_connections_treasure_row_no_dismiss():
    """List row named Treasure must not Back off Connections (r22)."""
    tree = (
        '<hierarchy><w p="com.badoo.mobile" f="1">'
        '<n i="id/connections_root" xy="540,1000"/>'
        '<n i="id/connection_container" xy="540,1200"/>'
        '<n t="Treasure" xy="337,1718" c="1"/>'
        '<n t="Ada" xy="300,900"/>'
        "</w></hierarchy>"
    )
    assert badoo_dismiss_popup(tree) is None


def test_yubo_social_not_card_name():
    tree = (
        '<hierarchy><w p="co.yellw.yellowapp" f="1">'
        '<n t="Social" xy="120,180" b="42,150,280,210"/>'
        '<n t="Send a message" xy="540,1800" c="1"/>'
        "</w></hierarchy>"
    )
    assert yubo_deck_card_name(tree) is None


def test_watchdog_constants_and_decision_key():
    assert NO_PROGRESS_TIMEOUT_S <= 120
    assert MAX_SAME_DECISION <= 4
    assert _same_tap_key({"action": "tap", "x": 342, "y": 2194}) == "tap:342,2194"
    k1 = _planner_decision_key(
        {
            "action": "tap",
            "x": 337,
            "y": 1718,
            "reason": "Open Treasure (bulk_open_row)",
        }
    )
    k2 = _planner_decision_key(
        {
            "action": "tap",
            "x": 337,
            "y": 1718,
            "reason": "Open Treasure (bulk_open_row)",
        }
    )
    assert k1 == k2
    assert "337,1718" in (k1 or "")


def test_bumble_swipe_prefers_leftmost_deck_tab():
    tree = (
        '<hierarchy><w p="com.bumble.app" f="1">'
        '<n t="People" xy="540,400"/>'
        '<n t="Same dating goals" xy="540,800"/>'
        '<n c="1" xy="140,2197" b="80,2140,200,2240"/>'
        '<n t="People" c="1" xy="540,2197" b="480,2140,600,2240"/>'
        '<n t="Chats" c="1" xy="780,2197" b="720,2140,840,2240"/>'
        "</w></hierarchy>"
    )
    state = {"bulk_swipe": {"done": 0, "target": 5}}
    act = plan_bulk_swipe(
        "swipe right on 5 profiles on Bumble",
        tree,
        ["Opened Bumble[open_ok]"],
        package="com.bumble.app",
        dry_run=True,
        state=state,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert int(act.get("x") or 999) < 450
    assert (
        "grid" in (act.get("reason") or "").lower()
        or "deck" in (act.get("reason") or "").lower()
    )
