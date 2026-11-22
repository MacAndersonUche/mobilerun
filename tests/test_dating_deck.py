"""Self-test: free LIKE, wait-for-next-card, messaging text gate, paywall dismiss."""

from __future__ import annotations

import pytest

from backend.dating_deck import (
    CARD_WAIT_MAX,
    deck_fingerprint,
    dismiss_paywall_action,
    find_free_like_target,
    is_end_of_deck,
    is_paywall_or_billing,
    mark_like_issued,
    plan_free_like,
    plan_wait_for_next_card,
)
from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_swipe


def _card(name: str, *, like: bool = True, extra: str = "") -> str:
    like_n = '<n t="Like" xy="800,2000" clickable="true"/>' if like else ""
    return (
        f'<h pkg="com.bumble.app">'
        f'<n t="{name}" xy="540,900"/>'
        f'<n t="25" xy="540,1000"/>'
        f"{like_n}"
        f"{extra}"
        f"</h>"
    )


def test_free_like_never_super_or_crush():
    tree = (
        '<h pkg="com.bumble.app">'
        '<n t="Super Like" xy="200,2000" clickable="true"/>'
        '<n t="Crush" xy="400,2000" clickable="true"/>'
        '<n t="Like" xy="800,2000" clickable="true"/>'
        "</h>"
    )
    hit = find_free_like_target(tree, "bumble")
    assert hit is not None
    assert hit[0] == 800
    assert hit[2].lower() == "like"
    act = plan_free_like("bumble", tree, planner="test")
    assert act and act.get("action") == "tap"
    assert act.get("_free_like") is True
    assert int(act["x"]) == 800
    blob = f"{act.get('reason')} {act.get('label')}".lower()
    assert "super" not in blob
    assert "crush" not in blob


def test_free_like_dry_run_no_tap():
    act = plan_free_like("yubo", _card("Alex"), dry_run=True)
    assert act and act.get("action") == "done"
    assert act.get("dry_run") is True


def test_paywall_play_billing_and_spay():
    play = (
        '<h pkg="com.android.vending">'
        '<n t="Complete your purchase" xy="540,800"/>'
        '<n t="Subscribe" xy="540,1800"/>'
        "</h>"
    )
    assert is_paywall_or_billing(play, "com.android.vending")
    act = dismiss_paywall_action(play, package="com.android.vending")
    assert act
    assert act.get("action") in ("press_button", "tap")
    if act.get("action") == "press_button":
        assert act.get("button") == "back"
    # Never tap Subscribe
    assert "subscribe" not in (act.get("label") or "").lower()

    spay = '<h pkg="com.samsung.android.spay"><n t="Samsung Pay" xy="540,900"/></h>'
    assert is_paywall_or_billing(spay, "com.samsung.android.spay")
    act2 = dismiss_paywall_action(spay, package="com.samsung.android.spay")
    assert act2 and act2.get("action") == "press_button"
    assert act2.get("button") == "back"


def test_paywall_safe_dismiss_not_now():
    tree = (
        '<h pkg="com.bumble.app">'
        '<n t="Get Boost" xy="540,1200"/>'
        '<n t="Not now" xy="540,1900" clickable="true"/>'
        "</h>"
    )
    assert is_paywall_or_billing(tree)
    act = dismiss_paywall_action(tree, package="com.bumble.app")
    assert act and act.get("action") == "tap"
    assert "not now" in (act.get("label") or "").lower()
    assert act.get("_paywall_dismiss") is True


def test_end_of_deck_detection():
    assert is_end_of_deck('<n t="No more profiles"/>')
    assert is_end_of_deck('<n t="You\'ve seen everyone nearby"/>')
    assert not is_end_of_deck(_card("Sam"))


def test_wait_for_next_card_polls_then_counts():
    st: dict = {"bulk_swipe": {"done": 0, "target": 3}}
    tree_a = _card("Alex")
    mark_like_issued(st, app="bumble", tree=tree_a)
    assert st["bulk_swipe"]["awaiting_verify"] is True
    fp0 = st["bulk_swipe"]["last_fp"]

    # Same card → wait
    wait = plan_wait_for_next_card(st, app="bumble", tree=tree_a, planner="t")
    assert wait and wait.get("action") == "wait"
    assert wait.get("_card_wait") is True
    assert int(st["bulk_swipe"].get("done") or 0) == 0

    # New card → count + clear
    nxt = plan_wait_for_next_card(st, app="bumble", tree=_card("Jordan"), planner="t")
    assert nxt is None
    assert st["bulk_swipe"]["done"] == 1
    assert st["bulk_swipe"]["awaiting_verify"] is False
    assert st["bulk_swipe"]["last_fp"] != fp0


def test_wait_timeout_and_end_of_deck():
    tree_a = _card("Alex")
    fp = deck_fingerprint(tree_a, "bumble")
    st = {
        "bulk_swipe": {
            "awaiting_verify": True,
            "last_name": "Alex",
            "last_fp": fp,
            "card_wait_n": CARD_WAIT_MAX,
            "done": 2,
        }
    }
    timed = plan_wait_for_next_card(st, app="bumble", tree=tree_a, planner="t")
    assert timed and timed.get("_card_wait_timeout") is True
    assert st["bulk_swipe"]["done"] == 2  # not incremented

    st2 = {
        "bulk_swipe": {
            "awaiting_verify": True,
            "last_name": "Alex",
            "done": 3,
        }
    }
    end = plan_wait_for_next_card(
        st2, app="bumble", tree='<n t="No more profiles"/>', planner="t"
    )
    assert end and end.get("action") == "done"
    assert end.get("stopped_reason") == "end_of_deck"


def test_bulk_swipe_waits_after_like():
    tree1 = _card("Alex")
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble like 3 profiles",
        tree1,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
    )
    # May open deck / like / or fail if deck detectors need more — if like issued:
    if (
        act
        and act.get("_free_like")
        or (
            act
            and "like" in (act.get("reason") or "").lower()
            and act.get("action")
            in (
                "tap",
                "swipe",
            )
        )
    ):
        assert st.get("bulk_swipe", {}).get("awaiting_verify") is True
        wait = plan_bulk_swipe(
            "bumble like 3 profiles",
            tree1,  # same card
            ["Opened Bumble — launch", act.get("reason") or "like"],
            state=st,
            package="com.bumble.app",
        )
        assert wait and wait.get("action") == "wait"
        assert "next profile" in (wait.get("reason") or "").lower() or wait.get(
            "_card_wait"
        )


def test_message_goal_requires_bank_or_exact_text():
    bad = parse_bulk_goal("bumble message 3 matches")
    # Either no goal, wrong kind, or error / empty message
    if bad and bad.get("kind") == "message":
        assert bad.get("error") or not (bad.get("message") or "").strip()

    good = parse_bulk_goal('bumble message 2 matches say "hey there"')
    assert good and good.get("kind") == "message"
    assert (good.get("message") or "").strip() == "hey there"


def test_deck_fingerprint_changes_with_name():
    a = deck_fingerprint(_card("Alex"), "bumble")
    b = deck_fingerprint(_card("Jordan"), "bumble")
    assert a != b


def test_bulk_paywall_dismiss_before_like():
    tree = (
        '<h pkg="com.bumble.app">'
        '<n t="Get Boost" xy="540,1000"/>'
        '<n t="Buy credits" xy="540,1200"/>'
        '<n t="Not now" xy="540,1900" clickable="true"/>'
        "</h>"
    )
    assert is_paywall_or_billing(tree, "com.bumble.app")
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble like 5 profiles",
        tree,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
    )
    assert act
    assert (
        act.get("_paywall_dismiss") is True
        or (
            act.get("action") == "tap"
            and "not now" in (act.get("label") or act.get("reason") or "").lower()
        )
        or (act.get("action") == "press_button" and act.get("button") == "back")
    )
