"""r22 failure signatures: dry-run 5 cards, foreign card names, Treasure,
Yubo editable Aa, list_ok when rows visible, vision deferral."""

from backend.bulk_bench_heuristics import (
    _card_name_is_foreign,
    _visible_chat_list_rows,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.cloud_agent import apply_dry_run_send_guard, plan_next_action
from backend.dm_heuristics import (
    _looks_like_notif_or_app_title,
    badoo_dismiss_popup,
    taimi_deck_card_name,
    yubo_on_chat,
    yubo_on_chat_list,
)


def _bumble_deck(name: str = "Alex") -> str:
    return (
        f'<hierarchy packages="com.bumble.app">'
        f'<w p="com.bumble.app" f="1">'
        f'<n t="{name}, 28" d="{name}\'s main photo" xy="540,1600" '
        f'b="100,1500,900,1700"/>'
        f'<n t="People" xy="540,400"/>'
        f"</w></hierarchy>"
    )


def test_dry_run_swipe_advances_not_one_card_done():
    """r22: must not finish after evaluating a single card when target=5."""
    tree = _bumble_deck("Cerys")
    st: dict = {"bulk_swipe": {"done": 0, "target": 5}}
    act = plan_bulk_swipe(
        "swipe right on 5 profiles on Bumble",
        tree,
        ["Opened Bumble[open_ok]"],
        package="com.bumble.app",
        dry_run=True,
        state=st,
    )
    assert act is not None
    assert act.get("action") != "done"
    assert act.get("_dry_run_advance") is True
    assert "cerys" in (act.get("reason") or "").lower()
    assert st["bulk_swipe"]["done"] == 1
    assert st["bulk_swipe"].get("awaiting_verify") is True


def test_dry_run_advance_allowed_by_send_guard():
    action = {
        "action": "swipe",
        "x1": 820,
        "y1": 1400,
        "x2": 180,
        "y2": 1400,
        "_dry_run_advance": True,
        "reason": "[DRY RUN] advance 1/5 via pass",
    }
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="swipe", reason=action["reason"]
    )
    assert kind == "swipe"
    assert out.get("action") == "swipe"
    assert out.get("_dry_run_advance") is True


def test_dry_run_rejects_indeed_job_search_card():
    assert _looks_like_notif_or_app_title("Indeed Job Search")
    assert _card_name_is_foreign("Indeed Job Search")
    tree = (
        '<hierarchy packages="com.takimi.android">'
        '<w p="com.android.systemui" f="0">'
        '<n t="Indeed Job Search" xy="540,1580"/>'
        "</w>"
        '<w p="com.takimi.android" f="1">'
        '<n t="Curated for you" xy="200,200"/>'
        "</w></hierarchy>"
    )
    assert taimi_deck_card_name(tree) is None


def test_taimi_accepts_real_name_in_taimi_window():
    tree = (
        '<hierarchy packages="com.takimi.android">'
        '<w p="com.takimi.android" f="1">'
        '<n t="Liv" xy="540,1580" b="200,1500,800,1660"/>'
        '<n t="Curated for you" xy="200,200"/>'
        "</w></hierarchy>"
    )
    assert taimi_deck_card_name(tree) == "Liv"
    assert not _card_name_is_foreign("Liv")


def test_badoo_treasure_row_on_connections_does_not_back():
    """r22: Connections list row 'Treasure' must not trigger promo Back."""
    tree = (
        '<hierarchy><w p="com.badoo.mobile" f="1">'
        '<n i="id/connections_root" xy="540,1000"/>'
        '<n i="id/connection_list_component" xy="540,1200"/>'
        '<n t="Treasure" xy="337,1718" c="1"/>'
        '<n t="Liv" xy="300,900"/>'
        '<n t="hey" xy="300,960"/>'
        "</w></hierarchy>"
    )
    pop = badoo_dismiss_popup(tree)
    assert pop is None


def test_badoo_open_treasure_sheet_still_dismisses():
    tree = (
        '<hierarchy><w p="com.badoo.mobile" f="1">'
        '<n t="Open Treasure" xy="540,1800" c="1"/>'
        '<n t="Close" xy="100,200" c="1"/>'
        "</w></hierarchy>"
    )
    pop = badoo_dismiss_popup(tree)
    assert pop is not None
    assert "treasure" in (pop.get("reason") or "").lower()


def test_yubo_on_chat_requires_editable_aa():
    """Non-editable Aa + Back on Conversations must not look like a thread."""
    tree = (
        '<hierarchy packages="co.yellw.yellowapp">'
        '<w p="co.yellw.yellowapp" f="1">'
        '<n t="Conversations" xy="200,1100"/>'
        '<n t="New Friends" xy="200,400"/>'
        '<n t="Aa" xy="540,2000"/>'  # not editable
        '<n t="Back" xy="80,200" c="1"/>'
        '<n t="Roch" xy="242,1200"/>'
        '<n t="Leah" xy="242,1380"/>'
        "</w></hierarchy>"
    )
    assert yubo_on_chat_list(tree) is True
    assert yubo_on_chat(tree) is False


def test_yubo_reply_after_back_opens_row_not_back_loop():
    tree = (
        '<hierarchy windows="1" nodes="20" empty="false">'
        '<w p="co.yellw.yellowapp" f="1">'
        '<n t="Conversations" xy="200,1100"/>'
        '<n t="Roch" xy="242,1200" b="200,1160,360,1240"/>'
        '<n t="Heyy" xy="300,1260"/>'
        '<n t="Leah" xy="242,1380"/>'
        "</w></hierarchy>"
    )
    state = {
        "bulk_message": {
            "done": 1,
            "target": 5,
            "current": None,
            "done_names": ["Amie"],
            "chat_list_verified": False,
            "_await_list_after_back": True,
        }
    }
    act = plan_bulk_message(
        'reply to 5 chats on Yubo with "hey"',
        tree,
        ["Opened Yubo", "tap — Open Roch", "back — Message sent"],
        package="co.yellw.yellowapp",
        dry_run=True,
        state=state,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "Roch" in (act.get("reason") or "") or "Leah" in (act.get("reason") or "")
    assert act.get("action") != "press_button"


def test_list_ok_when_rows_visible_blk():
    tree = (
        '<hierarchy><w p="com.affinityapps.blk" f="1">'
        '<n t="Matches" xy="540,200"/>'
        '<n t="Your turn" xy="200,400"/>'
        '<n t="Neff" xy="300,600"/>'
        '<n t="hey there" xy="300,660"/>'
        "</w></hierarchy>"
    )
    rows = _visible_chat_list_rows(tree, "blk")
    assert any(r["name"] == "Neff" for r in rows)
    state = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": None,
            "chat_list_verified": False,
            "_chats_settle_done": True,
            "_chats_settle_n": 1,
            "_chats_tab_taps": 1,
        }
    }
    act = plan_bulk_message(
        'reply to 5 chats on BLK with "hey"',
        tree,
        ["Opened BLK", "tap — Open Matches", "wait — Settle 1.5s"],
        package="com.affinityapps.blk",
        dry_run=True,
        state=state,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert "Neff" in (act.get("reason") or "")


def test_bulk_vision_wait_deferred_when_screenshot_present():
    """With image_b64, bulk needs_vision wait must not short-circuit LLM."""
    empty = (
        '<hierarchy nodes="0" empty="true" packages="">'
        "<w/></hierarchy>"
    )
    # plan_next_action with empty tree + bulk goal + fake image should not
    # return a bulk wait when vision can run (may return LLM/heuristic action).
    st: dict = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": None,
            "_chats_tab_taps": 1,
            "_chats_settle_done": True,
            "_chats_settle_n": 1,
            "_chats_vision_n": 0,
        }
    }
    act = plan_next_action(
        'reply to 5 chats on Taimi with "hey"',
        empty,
        ["Opened Taimi", "tap — Open Chats"],
        image_b64="dGVzdA==",  # "test"
        package="com.takimi.android",
        dry_run=True,
        agent_state=st,
    )
    # Must not be the short vision-wait that previously blocked LLM
    assert not (
        act.get("action") == "wait"
        and act.get("needs_vision")
        and "vision locate" in (act.get("reason") or "").lower()
        and act.get("planner") == "bulk_message_heuristic"
    )


def test_dry_run_records_five_distinct_cards():
    st: dict = {"bulk_swipe": {"done": 0, "target": 5}}
    names = ["Cerys", "Court", "Liv", "Neff", "Alex"]
    last = None
    for i, name in enumerate(names):
        if last is not None:
            # Simulate awaiting after advance
            st["bulk_swipe"]["awaiting_verify"] = True
            st["bulk_swipe"]["last_name"] = last
            st["bulk_swipe"]["card_wait_n"] = 0
        act = plan_bulk_swipe(
            "swipe right on 5 profiles on Bumble",
            _bumble_deck(name),
            ["Opened Bumble[open_ok]"],
            package="com.bumble.app",
            dry_run=True,
            state=st,
        )
        assert act is not None
        last = name
        if i < 4:
            assert act.get("_dry_run_advance") is True or act.get("action") == "wait"
        else:
            assert act.get("action") == "done"
            assert act.get("bulk_swipe_evaluated") == 5
            reason = (act.get("reason") or "").lower()
            assert "evaluated 5 cards" in reason
            assert "cerys" in reason and "alex" in reason
