"""Bumble SM-G996B real-device map: deck, popups, chats, composer."""

from pathlib import Path

from backend.cloud_agent import _heuristic_dm_send
from backend.dm_heuristics import (
    DM_APP_PROFILES,
    bumble_dismiss_popup,
    bumble_like_swipe,
    bumble_on_connections,
    bumble_on_people_deck,
    bumble_pass_swipe,
    find_send_center_safe,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"
INSTR = "bumble message Sam and say hi"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_bumble_profile_has_s21_selectors():
    p = DM_APP_PROFILES["bumble"]
    assert p["package"] == "com.bumble.app"
    assert p["search_fallback"] is None
    assert p["send_fallback"] is None
    assert p["compose_fallback"] is None
    assert "chatInput_text" in str(p["compose_ids"])
    assert "connectionsItem_personName" in str(p["result_ids"])
    assert p["like_swipe"] == (250, 1000, 1050, 1050, 300)
    assert p["pass_swipe"] == (850, 1000, 30, 1050, 300)
    assert "toolbar_backtrackContainer" in str(p["never_tap_ids"])
    assert "Send a compliment" in p["never_tap_labels"]


def test_bumble_deck_detection_and_open_chats():
    deck = _load("bumble_deck.xml")
    assert bumble_on_people_deck(deck)
    assert not bumble_on_connections(deck)
    a = _heuristic_dm_send(
        INSTR,
        deck,
        ["Opened Bumble[com.bumble.app] — launch"],
        package="com.bumble.app",
    )
    assert a and a["action"] == "tap"
    assert "chats" in a["reason"].lower()
    assert a.get("fastpath_step") == "bumble_open_chats_tab"
    # Must not be undo / superswipe / compliment
    assert (a["x"], a["y"]) == (972, 2197)


def test_bumble_swipe_recipe_coords():
    like = bumble_like_swipe()
    assert like["action"] == "swipe"
    assert (like["x1"], like["y1"], like["x2"], like["y2"]) == (250, 1000, 1050, 1050)
    assert like["duration_ms"] == 300
    pas = bumble_pass_swipe()
    assert (pas["x1"], pas["y1"], pas["x2"], pas["y2"]) == (850, 1000, 30, 1050)


def test_bumble_popup_interested_yes():
    tree = _load("bumble_popup_interested.xml")
    a = bumble_dismiss_popup(tree)
    assert a and a["action"] == "tap"
    assert "interested" in a["reason"].lower()
    assert a.get("fastpath_step") == "bumble_popup_alert"


def test_bumble_connections_taps_person_not_promo():
    tree = _load("bumble_connections.xml")
    assert bumble_on_connections(tree)
    a = _heuristic_dm_send(
        INSTR,
        tree,
        ["Opened Bumble[com.bumble.app] — launch", "tap — Open Chats tab"],
        package="com.bumble.app",
    )
    assert a and a["action"] == "tap"
    assert "sam" in a["reason"].lower() or "contact" in a["reason"].lower()
    # Not the sticky promo
    assert a["y"] != 650


def test_bumble_chat_focus_type_send_no_av():
    chat = _load("bumble_chat.xml")
    hist = [
        "Opened Bumble[com.bumble.app] — launch",
        "tap — Open Chats tab",
        "tap — Tap visible contact 'Sam'",
        "tap — Focus compose Message/entry field (bumble_heuristic)",
    ]
    a = _heuristic_dm_send(INSTR, chat, hist, package="com.bumble.app")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi"
    hist2 = hist + ['type("hi") — Type message']
    a2 = _heuristic_dm_send(INSTR, chat, hist2, package="com.bumble.app")
    assert a2 and a2["action"] == "tap"
    assert "send" in a2["reason"].lower()
    # Send node, not audio/video
    assert a2["x"] == 1020
    send = find_send_center_safe(
        chat,
        ("Send",),
        send_ids=("send",),
        profile=DM_APP_PROFILES["bumble"],
    )
    assert send == (1020, 2210)


def test_bumble_dry_run_stops_before_send():
    chat = _load("bumble_chat.xml")
    hist = [
        "Opened Bumble — launch",
        "tap — Focus compose",
        'type("hi") — Type message',
    ]
    a = _heuristic_dm_send(INSTR, chat, hist, package="com.bumble.app", dry_run=True)
    assert a and a["action"] == "done"
    assert "dry_run" in a["reason"].lower()
    assert "hi" in a["reason"].lower()
