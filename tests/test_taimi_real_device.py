"""Taimi (com.takimi.android) SM-G996B: People deck, GOLD paywall, Chats, composer."""

from pathlib import Path

from backend.bulk_bench_heuristics import deck_card_name, plan_bulk_swipe
from backend.cloud_agent import _heuristic_dm_send
from backend.dm_heuristics import (
    DM_APP_PROFILES,
    detect_dm_app,
    taimi_action_row_centers,
    taimi_deck_card_name,
    taimi_dismiss_paywall,
    taimi_find_chat_tile,
    taimi_is_curated_card,
    taimi_is_paywall,
    taimi_like_action,
    taimi_on_chats_list,
    taimi_on_people_deck,
    taimi_outgoing_verified,
    taimi_pass_action,
    taimi_send_relative_to_edittext,
    taimi_swipes_left,
)
from backend.fake_chats_catalog import app_by_key

FIXTURES = Path(__file__).parent / "fixtures" / "dm"
INSTR = "taimi message Alex and say hi"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_taimi_package_is_takimi_not_taimi():
    p = DM_APP_PROFILES["taimi"]
    assert p["package"] == "com.takimi.android"
    assert "takimi" in p["pkg_markers"]
    assert "taimi" not in p["package"]
    assert detect_dm_app("taimi message Alex and say hi") == "taimi"
    cat = app_by_key("taimi")
    assert cat["package"] == "com.takimi.android"
    assert p["launch_activity"].endswith(".MainActivityDefault")
    assert p.get("flag_secure") is True
    assert p["inbox_tab_xy"] == (972, 2200)
    assert p["search_fallback"] is None
    assert p["send_fallback"] is None
    assert "Continue" in p["never_tap_labels"]


def test_taimi_people_opens_chats_not_instant_or_top_chrome():
    tree = _load("taimi_people.xml")
    assert taimi_on_people_deck(tree)
    assert taimi_deck_card_name(tree) == "Alex"
    assert taimi_swipes_left(tree) == 12
    a = _heuristic_dm_send(
        INSTR,
        tree,
        ["Opened Taimi[com.takimi.android] — launch"],
        package="com.takimi.android",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "taimi_open_chats_tab"
    assert (a["x"], a["y"]) == (972, 2200)
    # Never Instant Chat centre / Like / Skip / top-right chrome while messaging
    assert (a["x"], a["y"]) not in (
        (541, 1948),
        (761, 1948),
        (320, 1948),
        (850, 145),
        (985, 145),
    )


def test_taimi_action_row_three_siblings():
    tree = _load("taimi_people.xml")
    row = taimi_action_row_centers(tree)
    assert row["skip"] == (320, 1948)
    assert row["instant_chat"] == (541, 1948)
    assert row["like"] == (761, 1948)
    like = taimi_like_action(tree)
    assert like and (like["x"], like["y"]) == (761, 1948)
    pas = taimi_pass_action(tree)
    assert pas and (pas["x"], pas["y"]) == (320, 1948)


def test_taimi_curated_skips_never_like():
    tree = _load("taimi_curated.xml")
    assert taimi_is_curated_card(tree)
    act = taimi_like_action(tree)
    assert act and act.get("fastpath_step") == "taimi_pass"
    assert (act["x"], act["y"]) == (320, 1948)
    assert "curated" in act["reason"].lower() or "gold" in act["reason"].lower()


def test_taimi_paywall_back_never_continue():
    tree = _load("taimi_paywall.xml")
    assert taimi_is_paywall(tree)
    a = taimi_dismiss_paywall(tree)
    assert a and a["action"] == "press_button" and a.get("button") == "back"
    assert a.get("fastpath_step") == "taimi_paywall_back"
    # Heuristic path also backs out
    a2 = _heuristic_dm_send(
        INSTR,
        tree,
        ["Opened Taimi — launch"],
        package="com.takimi.android",
    )
    assert a2 and a2["action"] == "press_button"
    assert a2.get("button") == "back"


def test_taimi_zero_left_stops():
    tree = _load("taimi_zero_left.xml")
    assert taimi_swipes_left(tree) == 0
    a = _heuristic_dm_send(
        INSTR,
        tree,
        ["Opened Taimi — launch"],
        package="com.takimi.android",
    )
    assert a and a["action"] == "done"
    assert a.get("fastpath_step") == "taimi_swipes_exhausted"


def test_taimi_chats_start_chat_skips_daily_pick_and_notify():
    tree = _load("taimi_chats.xml")
    assert taimi_on_chats_list(tree)
    tile = taimi_find_chat_tile(tree, "Alex")
    assert tile == (270, 700)
    # Daily pick must not resolve as Sam target when asking Alex
    assert taimi_find_chat_tile(tree, "Sam") is None
    a = _heuristic_dm_send(
        INSTR,
        tree,
        ["Opened Taimi — launch", "tap — Open Chats"],
        package="com.takimi.android",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "taimi_tap_chat"
    assert (a["x"], a["y"]) == (270, 700)
    assert (a["x"], a["y"]) != (900, 280)  # Notify me
    assert (a["x"], a["y"]) != (810, 700)  # daily pick


def test_taimi_thread_type_send_never_canned():
    chat = _load("taimi_thread.xml")
    hist = [
        "Opened Taimi — launch",
        "tap — Open Chats",
        "tap — Tap Taimi chat/Start chat 'Alex'",
    ]
    a = _heuristic_dm_send(INSTR, chat, hist, package="com.takimi.android")
    assert a and a["action"] in ("tap", "type")
    if a["action"] == "tap":
        # Never canned chip
        assert (a["x"], a["y"]) != (540, 900)
        hist = hist + [f"tap({a['x']},{a['y']}) — {a['reason']}"]
        a = _heuristic_dm_send(INSTR, chat, hist, package="com.takimi.android")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi"
    assert a.get("clear") is True
    hist2 = hist + ['type("hi") — Type message']
    a2 = _heuristic_dm_send(INSTR, chat, hist2, package="com.takimi.android")
    assert a2 and a2["action"] == "tap"
    assert "send" in a2["reason"].lower()
    send = taimi_send_relative_to_edittext(chat)
    assert send is not None
    assert send[0] >= 900


def test_taimi_outgoing_requires_delivered():
    tree = _load("taimi_thread.xml")
    assert taimi_outgoing_verified(tree, "hey")
    no_del = tree.replace("Delivered", "Seen")
    assert not taimi_outgoing_verified(no_del, "hey")


def test_taimi_dry_run_stops_before_send():
    chat = _load("taimi_thread.xml")
    hist = [
        "Opened Taimi — launch",
        "tap — Focus compose",
        'type("hi") — Type message',
    ]
    a = _heuristic_dm_send(
        INSTR, chat, hist, package="com.takimi.android", dry_run=True
    )
    assert a and a["action"] == "type"
    assert a.get("clear") is True and a.get("text") == ""
    hist2 = hist + [f'type("") — {a["reason"]}']
    a2 = _heuristic_dm_send(
        INSTR, chat, hist2, package="com.takimi.android", dry_run=True
    )
    assert a2 and a2["action"] == "done"
    assert a2.get("dry_run") is True
    assert a2.get("dry_run_verified") is True


def test_taimi_bulk_like_right_button_not_nav():
    deck = _load("taimi_people.xml")
    assert deck_card_name("taimi", deck) == "Alex"
    st: dict = {}
    act = plan_bulk_swipe(
        "taimi auto-swipe 5 profiles",
        deck,
        ["Opened Taimi — launch"],
        state=st,
        package="com.takimi.android",
    )
    assert act and act.get("action") == "tap"
    assert (act["x"], act["y"]) == (761, 1948)
    # Never Instant Chat / Chats nav / top chrome
    assert (act["x"], act["y"]) not in ((541, 1948), (972, 2200), (850, 145))
    assert st.get("bulk_swipe", {}).get("awaiting_verify") is True
    assert st.get("bulk_swipe", {}).get("done") == 0


def test_taimi_bulk_curated_uses_skip():
    deck = _load("taimi_curated.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "taimi auto-swipe 5 profiles",
        deck,
        ["Opened Taimi — launch"],
        state=st,
        package="com.takimi.android",
    )
    assert act and act.get("action") == "tap"
    assert (act["x"], act["y"]) == (320, 1948)


def test_taimi_bulk_paywall_backs_out():
    st: dict = {"bulk_swipe": {"done": 1, "target": 5, "awaiting_verify": True}}
    act = plan_bulk_swipe(
        "taimi auto-swipe 5 profiles",
        _load("taimi_paywall.xml"),
        ["Opened Taimi — launch"],
        state=st,
        package="com.takimi.android",
    )
    assert act and act["action"] == "press_button"
    assert act.get("button") == "back"
    assert st["bulk_swipe"].get("done") == 1  # not incremented on paywall


def test_taimi_bulk_zero_left_done():
    st: dict = {}
    act = plan_bulk_swipe(
        "taimi auto-swipe 5 profiles",
        _load("taimi_zero_left.xml"),
        ["Opened Taimi — launch"],
        state=st,
        package="com.takimi.android",
    )
    assert act and act["action"] == "done"
    assert (
        "0 left" in (act.get("reason") or "").lower()
        or "exhaust" in (act.get("reason") or "").lower()
    )


def test_taimi_bulk_dry_run_skips_like():
    deck = _load("taimi_people.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "taimi auto-swipe 5 profiles",
        deck,
        ["Opened Taimi — launch"],
        state=st,
        package="com.takimi.android",
        dry_run=True,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run") is True
    reason = (act.get("reason") or "").lower()
    assert "would like/pass 5 cards" in reason
    assert "deck verified on alex" in reason
