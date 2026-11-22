"""Yubo + Badoo SM-G996B real-device maps: deck, popups, chats, composer."""

from pathlib import Path

from backend.cloud_agent import _heuristic_dm_send
from backend.dm_heuristics import (
    DM_APP_PROFILES,
    badoo_dismiss_popup,
    badoo_like_action,
    badoo_like_swipe,
    badoo_on_connections,
    badoo_on_encounters,
    badoo_pass_action,
    find_send_center_safe,
    yubo_deck_card_name,
    yubo_direct_sheet_action,
    yubo_dismiss_popup,
    yubo_find_conversation_tap,
    yubo_find_send_center,
    yubo_like_swipe,
    yubo_on_chat_list,
    yubo_on_deck,
    yubo_outgoing_verified,
    yubo_pass_swipe,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"
YUBO_INSTR = "yubo message Sam and say hi"
BADOO_INSTR = "badoo message Sam and say hi"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- Yubo ---


def test_yubo_profile_s21_selectors():
    p = DM_APP_PROFILES["yubo"]
    assert p["package"] == "co.yellw.yellowapp"
    assert p["launch_activity"].endswith(".main.MainActivity")
    assert p["open_settle_s"] == 8.0
    assert p["like_swipe"] == (250, 1000, 1050, 1050, 300)
    assert p["inbox_tab_xy"] == (341, 2194)  # unlabeled Chat tab by index (22 Nov)
    assert p["search_fallback"] is None
    assert p["send_fallback"] is None
    assert "Blast" in p["never_tap_labels"]
    assert "HyperSurge" in str(p["never_tap_labels"])


def test_yubo_deck_opens_chat_tab_not_yubucks():
    deck = _load("yubo_deck.xml")
    assert yubo_on_deck(deck)
    assert yubo_deck_card_name(deck) == "Sam"
    a = _heuristic_dm_send(
        YUBO_INSTR,
        deck,
        ["Opened Yubo[co.yellw.yellowapp] — launch"],
        package="co.yellw.yellowapp",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "yubo_open_chat_tab"
    assert (a["x"], a["y"]) == (343, 2180)
    # Must not tap Yubucks pill
    assert (a["x"], a["y"]) != (840, 158)


def test_yubo_swipe_recipe():
    like = yubo_like_swipe()
    assert (like["x1"], like["y1"], like["x2"], like["y2"]) == (250, 1000, 1050, 1050)
    assert like["duration_ms"] == 300
    pas = yubo_pass_swipe()
    assert (pas["x1"], pas["y1"], pas["x2"], pas["y2"]) == (850, 1000, 30, 1050)


def test_yubo_direct_sheet_selects_direct_never_blast():
    tree = _load("yubo_direct_sheet.xml")
    a = yubo_direct_sheet_action(tree)
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "yubo_select_direct"
    assert "blast" not in a["reason"].lower() or "never" in a["reason"].lower()
    # Tap Direct tile, not Blast center
    assert a["x"] >= 700


def test_yubo_infinity_upsell_back():
    a = yubo_dismiss_popup(_load("yubo_popup_infinity.xml"))
    assert a and a["action"] == "press_button" and a.get("button") == "back"


def test_yubo_chat_list_taps_conversation_not_hypersurge():
    tree = _load("yubo_chat_list.xml")
    assert yubo_on_chat_list(tree)
    tap = yubo_find_conversation_tap(tree, "Sam")
    assert tap == (540, 1200 + 27)
    a = _heuristic_dm_send(
        YUBO_INSTR,
        tree,
        ["Opened Yubo — launch", "tap — Open Chat tab"],
        package="co.yellw.yellowapp",
    )
    assert a and a["action"] == "tap"
    assert a["y"] == 1227
    assert a["x"] == 540
    # Not HyperSurge banner
    assert a["y"] != 700


def test_yubo_chat_focus_type_send():
    chat = _load("yubo_chat.xml")
    hist = [
        "Opened Yubo — launch",
        "tap — Open Chat tab",
        "tap — Tap Yubo conversation 'Sam'",
    ]
    a = _heuristic_dm_send(YUBO_INSTR, chat, hist, package="co.yellw.yellowapp")
    assert a and a["action"] in ("tap", "type")
    if a["action"] == "tap":
        assert "compose" in a["reason"].lower() or "message" in a["reason"].lower()
        hist = hist + [f"tap({a['x']},{a['y']}) — {a['reason']}"]
        a = _heuristic_dm_send(YUBO_INSTR, chat, hist, package="co.yellw.yellowapp")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi"
    assert a.get("clear") is True
    hist2 = hist + ['type("hi") — Type message']
    a2 = _heuristic_dm_send(YUBO_INSTR, chat, hist2, package="co.yellw.yellowapp")
    assert a2 and a2["action"] == "tap"
    assert "send" in a2["reason"].lower()
    send = yubo_find_send_center(chat)
    assert send == (1008, 1336)


def test_yubo_outgoing_right_aligned():
    tree = """
    <hierarchy packages="co.yellw.yellowapp">
    <w p="co.yellw.yellowapp">
     <n t="hi" xy="800,900" b="700,860,900,940"/>
     <n t="12:01" xy="820,960" b="760,940,880,980"/>
     <n e="1" h="Aa" xy="540,2201" b="120,2160,900,2240"/>
    </w></hierarchy>
    """
    assert yubo_outgoing_verified(tree, "hi")


def test_yubo_dry_run_stops_before_send():
    chat = _load("yubo_chat.xml")
    hist = [
        "Opened Yubo — launch",
        "tap — Focus compose",
        'type("hi") — Type message',
    ]
    a = _heuristic_dm_send(
        YUBO_INSTR, chat, hist, package="co.yellw.yellowapp", dry_run=True
    )
    # Dry-run clears the draft first, then stops
    assert a and a["action"] in ("type", "done")
    assert a.get("dry_run") is True
    if a["action"] == "type":
        assert a.get("clear") is True
        hist2 = hist + [a.get("reason") or "clear composer"]
        a2 = _heuristic_dm_send(
            YUBO_INSTR, chat, hist2, package="co.yellw.yellowapp", dry_run=True
        )
        assert a2 and a2["action"] == "done"
        assert a2.get("dry_run_verified") is True


# --- Badoo ---


def test_badoo_profile_s21_selectors():
    p = DM_APP_PROFILES["badoo"]
    assert p["package"] == "com.badoo.mobile"
    assert "BadooActivity" in p["launch_activity"]
    assert p["open_settle_s"] == 8.0
    assert "buttonChat" in str(p["never_tap_ids"])
    assert "buttonCrush" in str(p["never_tap_ids"])
    assert "encountersCards_undo" in str(p["never_tap_ids"])
    assert p["send_fallback"] is None
    assert "chatInput_text" in str(p["compose_ids"])
    assert "chatInput_button_send" in str(p["send_ids"])


def test_badoo_encounters_opens_chats_not_paid():
    tree = _load("badoo_encounters.xml")
    assert badoo_on_encounters(tree)
    a = _heuristic_dm_send(
        BADOO_INSTR,
        tree,
        ["Opened Badoo[com.badoo.mobile] — launch"],
        package="com.badoo.mobile",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "badoo_open_chats_tab"
    assert (a["x"], a["y"]) == (756, 2210)
    # Not Crush / Chat-before-match / Undo
    assert (a["x"], a["y"]) not in ((1000, 1900), (540, 1982), (100, 400))


def test_badoo_like_pass_coords_and_swipe():
    like = badoo_like_action()
    assert (like["x"], like["y"]) == (855, 1982)
    pas = badoo_pass_action()
    assert (pas["x"], pas["y"]) == (225, 1982)
    sw = badoo_like_swipe()
    assert (sw["x1"], sw["y1"], sw["x2"], sw["y2"]) == (250, 1100, 1050, 1150)


def test_badoo_buy_credits_close():
    a = badoo_dismiss_popup(_load("badoo_popup_credits.xml"))
    assert a and a["action"] == "tap"
    assert (a["x"], a["y"]) == (985, 1247)
    assert "credits" in a["reason"].lower()


def test_badoo_connections_taps_person_not_likes_or_favorite():
    tree = _load("badoo_connections.xml")
    assert badoo_on_connections(tree)
    a = _heuristic_dm_send(
        BADOO_INSTR,
        tree,
        ["Opened Badoo — launch", "tap — Open Chats tab"],
        package="com.badoo.mobile",
    )
    assert a and a["action"] == "tap"
    assert "sam" in a["reason"].lower() or "contact" in a["reason"].lower()
    # Not Likes tile or favorite heart
    assert a["y"] != 400
    assert a["x"] != 1000


def test_badoo_chat_type_send_no_video():
    chat = _load("badoo_chat.xml")
    hist = [
        "Opened Badoo — launch",
        "tap — Open Chats",
        "tap — Tap visible contact 'Sam'",
        "tap — Focus compose Message/entry field (badoo_heuristic)",
    ]
    a = _heuristic_dm_send(BADOO_INSTR, chat, hist, package="com.badoo.mobile")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi"
    assert a.get("clear") is True
    hist2 = hist + ['type("hi") — Type message']
    a2 = _heuristic_dm_send(BADOO_INSTR, chat, hist2, package="com.badoo.mobile")
    assert a2 and a2["action"] == "tap"
    assert "send" in a2["reason"].lower()
    assert a2["x"] == 1000
    send = find_send_center_safe(
        chat,
        ("Send message", "Send"),
        send_ids=("chatInput_button_send", "send"),
        profile=DM_APP_PROFILES["badoo"],
    )
    assert send == (1000, 2210)
    # Not video button
    assert send != (1000, 148)


def test_badoo_dry_run_stops_before_send():
    chat = _load("badoo_chat.xml")
    hist = [
        "Opened Badoo — launch",
        "tap — Focus compose",
        'type("hi") — Type message',
    ]
    a = _heuristic_dm_send(
        BADOO_INSTR, chat, hist, package="com.badoo.mobile", dry_run=True
    )
    assert a and a["action"] in ("type", "done")
    assert a.get("dry_run") is True
    if a["action"] == "type":
        assert a.get("clear") is True
        hist2 = hist + [a.get("reason") or "clear composer"]
        a2 = _heuristic_dm_send(
            BADOO_INSTR, chat, hist2, package="com.badoo.mobile", dry_run=True
        )
        assert a2 and a2["action"] == "done"
        assert a2.get("dry_run_verified") is True
