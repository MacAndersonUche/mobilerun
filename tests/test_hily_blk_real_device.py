"""Hily + BLK SM-G996B real-device maps: deck buttons, popups, chats, composer."""

from pathlib import Path

from backend.bulk_bench_heuristics import deck_card_name, plan_bulk_swipe
from backend.cloud_agent import _heuristic_dm_send
from backend.dm_heuristics import (
    DM_APP_PROFILES,
    blk_deck_card_name,
    blk_dismiss_popup,
    blk_end_of_deck,
    blk_find_match_row,
    blk_like_action,
    blk_on_deck,
    blk_on_matches,
    blk_outgoing_verified,
    blk_send_relative_to_edittext,
    find_send_center_safe,
    hily_deck_card_name,
    hily_dismiss_popup,
    hily_find_chat_row,
    hily_find_send_center,
    hily_like_action,
    hily_mbm_allowance,
    hily_on_finder,
    hily_outgoing_verified,
    hily_pass_action,
    hily_send_is_audio,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"
HILY_INSTR = "hily message Evie and say hi"
BLK_INSTR = "blk message Maya and say hi"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- Hily ---


def test_hily_profile_s21_selectors():
    p = DM_APP_PROFILES["hily"]
    assert p["package"] == "com.hily.app"
    assert "MainActivity" in p["launch_activity"]
    assert p["like_xy"] == (750, 1959)
    assert p["pass_xy"] == (330, 1959)
    assert p["inbox_tab_xy"] == (341, 2190)
    assert p["search_fallback"] is None
    assert p["send_fallback"] is None
    assert "ActionButton_CRUSH" in p["never_tap_ids"]
    assert "They liked you!" in p["never_tap_labels"]
    assert "Audio message" in p["never_tap_labels"]
    assert "Allow" in p["never_tap_labels"]


def test_hily_finder_opens_chats_not_crush():
    tree = _load("hily_finder.xml")
    assert hily_on_finder(tree)
    assert hily_deck_card_name(tree) == "Evie"
    a = _heuristic_dm_send(
        HILY_INSTR,
        tree,
        ["Opened Hily[com.hily.app] — launch"],
        package="com.hily.app",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "hily_open_chats_tab"
    assert (a["x"], a["y"]) == (341, 2190)
    # Never Crush / Like / Pass while messaging
    assert (a["x"], a["y"]) not in ((540, 1959), (750, 1959), (330, 1959))


def test_hily_like_pass_buttons_never_crush():
    tree = _load("hily_finder.xml")
    like = hily_like_action(tree)
    assert like and (like["x"], like["y"]) == (750, 1959)
    assert "crush" not in like["reason"].lower()
    pas = hily_pass_action(tree)
    assert pas and (pas["x"], pas["y"]) == (330, 1959)
    # Crush node exists but must not be selected
    assert (like["x"], like["y"]) != (540, 1959)


def test_hily_first_like_got_it():
    a = hily_dismiss_popup(_load("hily_popup_first_like.xml"))
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "hily_got_it"
    assert "got it" in a["reason"].lower()


def test_hily_notif_maybe_later_never_allow():
    a = hily_dismiss_popup(_load("hily_popup_notif.xml"))
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "hily_maybe_later"
    assert (a["x"], a["y"]) == (540, 1650)
    assert (a["x"], a["y"]) != (540, 1500)


def test_hily_filter_got_it():
    a = hily_dismiss_popup(_load("hily_popup_filter.xml"))
    assert a and a.get("fastpath_step") == "hily_got_it"


def test_hily_chats_taps_row_not_they_liked_you():
    tree = _load("hily_chats.xml")
    row = hily_find_chat_row(tree, "Evie")
    assert row and row[1] == 680
    a = _heuristic_dm_send(
        HILY_INSTR,
        tree,
        ["Opened Hily — launch", "tap — Open Chats tab"],
        package="com.hily.app",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "hily_tap_chat"
    assert a["y"] == 680
    # Not premium "They liked you!" badge center
    assert a["x"] != 800


def test_hily_thread_type_send_never_toggle():
    chat = _load("hily_thread.xml")
    hist = [
        "Opened Hily — launch",
        "tap — Open Chats tab",
        "tap — Tap Hily chat 'Evie'",
    ]
    a = _heuristic_dm_send(HILY_INSTR, chat, hist, package="com.hily.app")
    assert a and a["action"] in ("tap", "type")
    if a["action"] == "tap":
        assert "compose" in a["reason"].lower() or "message" in a["reason"].lower()
        # Never Ready for Date toggle
        assert (a["x"], a["y"]) != (900, 400)
        hist = hist + [f"tap({a['x']},{a['y']}) — {a['reason']}"]
        a = _heuristic_dm_send(HILY_INSTR, chat, hist, package="com.hily.app")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi"
    assert a.get("clear") is True
    hist2 = hist + ['type("hi") — Type message']
    a2 = _heuristic_dm_send(HILY_INSTR, chat, hist2, package="com.hily.app")
    assert a2 and a2["action"] == "tap"
    assert "send" in a2["reason"].lower()
    send = hily_find_send_center(chat)
    assert send == (980, 2200)


def test_hily_never_tap_audio_message():
    tree = _load("hily_thread_audio.xml")
    assert hily_send_is_audio(tree)
    assert hily_find_send_center(tree) is None
    c = find_send_center_safe(
        tree,
        ("Send",),
        send_ids=("threadSend",),
        profile=DM_APP_PROFILES["hily"],
    )
    assert c is None


def test_hily_mbm_allowance_and_zero_stop():
    assert hily_mbm_allowance(_load("hily_mbm.xml")) == 3
    zero = _load("hily_mbm_zero.xml")
    assert hily_mbm_allowance(zero) == 0
    a = _heuristic_dm_send(
        HILY_INSTR,
        zero,
        ["Opened Hily — launch"],
        package="com.hily.app",
    )
    assert a and a["action"] == "fail"
    assert a.get("fastpath_step") == "hily_mbm_exhausted"


def test_hily_outgoing_verified():
    tree = """
    <hierarchy packages="com.hily.app">
    <w p="com.hily.app">
     <n t="hi" i="threadTextMessage_true" xy="700,900" b="500,860,900,940"/>
     <n e="1" h="Aa" i="threadInputFieldText" xy="480,2200"/>
    </w></hierarchy>
    """
    assert hily_outgoing_verified(tree, "hi")


def test_hily_dry_run_stops_before_send():
    chat = _load("hily_thread.xml")
    hist = [
        "Opened Hily — launch",
        "tap — Focus compose",
    ]
    a = _heuristic_dm_send(HILY_INSTR, chat, hist, package="com.hily.app", dry_run=True)
    # Hard rule: dry-run never types into a real chat — verify + done
    assert a is not None
    assert a["action"] != "type"
    assert a["action"] in ("done", "wait", "back")
    reason = (a.get("reason") or "").lower()
    assert a.get("dry_run") is True or "dry" in reason or a["action"] == "done"
    if a["action"] == "done":
        assert a.get("dry_run_verified") is True or "never typed" in reason


def test_hily_bulk_uses_like_button_not_nav():
    deck = _load("hily_finder.xml")
    assert deck_card_name("hily", deck) == "Evie"
    st: dict = {}
    act = plan_bulk_swipe(
        "hily auto-swipe 5 profiles",
        deck,
        ["Opened Hily — launch"],
        state=st,
        package="com.hily.app",
    )
    assert act and act.get("action") == "tap"
    assert (act["x"], act["y"]) == (750, 1959)
    # Never Crush / Chats nav / Pass
    assert (act["x"], act["y"]) not in ((540, 1959), (341, 2190), (330, 1959))
    assert st.get("bulk_swipe", {}).get("awaiting_verify") is True
    assert st.get("bulk_swipe", {}).get("done") == 0


def test_hily_bulk_dry_run_skips_like():
    deck = _load("hily_finder.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "hily auto-swipe 5 profiles",
        deck,
        ["Opened Hily — launch"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    # r22: pass-advance through 5 cards — never Like / never one-card done
    assert act and act.get("dry_run") is True
    assert act.get("action") != "done"
    assert act.get("_dry_run_advance") is True or act.get("action") in (
        "swipe",
        "tap",
        "wait",
    )
    reason = (act.get("reason") or "").lower()
    assert "like" not in reason or "no like" in reason


# --- BLK ---


def test_blk_profile_s21_selectors():
    p = DM_APP_PROFILES["blk"]
    assert p["package"] == "com.affinityapps.blk"
    assert "MainActivity" in p["launch_activity"]
    assert p["inbox_tab_xy"] == (675, 2170)
    assert p["like_min_x1"] == 850
    assert p["search_fallback"] is None
    assert p["send_fallback"] is None
    assert "Boost" in p["never_tap_labels"]
    assert "Send a Super Like" in p["never_tap_labels"]
    assert "Send a message" in p["never_tap_labels"]


def test_blk_deck_opens_matches_not_boost():
    tree = _load("blk_deck.xml")
    assert blk_on_deck(tree)
    assert blk_deck_card_name(tree) == "Maya"
    a = _heuristic_dm_send(
        BLK_INSTR,
        tree,
        ["Opened BLK[com.affinityapps.blk] — launch"],
        package="com.affinityapps.blk",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "blk_open_matches_tab"
    assert (a["x"], a["y"]) == (675, 2170)
    assert (a["x"], a["y"]) != (540, 2000)  # Boost
    assert (a["x"], a["y"]) != (300, 1600)  # Send a message on card


def test_blk_like_picks_right_icon_never_super():
    tree = _load("blk_deck.xml")
    like = blk_like_action(tree)
    assert like is not None
    # Right cyan heart center ≈ (933, 1733); left super ≈ (790, 1735)
    assert like["x"] >= 850
    assert like["x"] == 933
    assert like["y"] == 1733


def test_blk_super_like_popup_send_like_anyway():
    a = blk_dismiss_popup(_load("blk_super_like_popup.xml"))
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "blk_send_like_anyway"
    assert (a["x"], a["y"]) == (540, 1550)
    assert (a["x"], a["y"]) != (540, 1400)


def test_blk_end_of_deck_stops():
    tree = _load("blk_end_deck.xml")
    assert blk_end_of_deck(tree)
    st: dict = {}
    act = plan_bulk_swipe(
        "blk auto-swipe 5 profiles",
        tree,
        ["Opened BLK — launch"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act and act.get("action") == "done"
    assert "end" in (act.get("reason") or "").lower()


def test_blk_matches_skips_hidden():
    tree = _load("blk_matches.xml")
    assert blk_on_matches(tree)
    row = blk_find_match_row(tree, "Maya")
    assert row and row[1] == 450
    hidden = blk_find_match_row(tree, "HiddenPerson")
    assert hidden is None
    a = _heuristic_dm_send(
        BLK_INSTR,
        tree,
        ["Opened BLK — launch", "tap — Open Matches"],
        package="com.affinityapps.blk",
    )
    assert a and a["action"] == "tap"
    assert a.get("fastpath_step") == "blk_tap_match"
    assert a["y"] == 450


def test_blk_thread_notif_close_then_send_relative():
    tree = _load("blk_thread.xml")
    a = blk_dismiss_popup(tree)
    assert a and a.get("fastpath_step") == "blk_notif_close"
    assert (a["x"], a["y"]) == (980, 300)

    send = blk_send_relative_to_edittext(tree)
    assert send is not None
    # Unlabeled View right of EditText ≈ (985, 1324)
    assert send[0] >= 950
    assert abs(send[1] - 1324) <= 20


def test_blk_thread_type_send_dry_run():
    # Without notif banner so compose path proceeds
    tree = """
    <hierarchy packages="com.affinityapps.blk">
    <w p="com.affinityapps.blk" f="1">
     <n t="Maya" xy="400,148" b="200,100,700,196"/>
     <n e="1" f="1" t="" h="Message" c="1" xy="480,1324" b="80,1290,940,1358"/>
     <n c="1" xy="985,1324" b="959,1298,1012,1351"/>
    </w></hierarchy>
    """
    hist = [
        "Opened BLK — launch",
        "tap — Open Matches",
        "tap — Tap BLK match 'Maya'",
    ]
    a = _heuristic_dm_send(BLK_INSTR, tree, hist, package="com.affinityapps.blk")
    assert a and a["action"] in ("tap", "type")
    if a["action"] == "tap":
        hist = hist + [f"tap({a['x']},{a['y']}) — {a['reason']}"]
        a = _heuristic_dm_send(BLK_INSTR, tree, hist, package="com.affinityapps.blk")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi"
    # Dry-run on composer: never type — verify + done
    a2 = _heuristic_dm_send(
        BLK_INSTR,
        tree,
        hist + ['type("hi") — Type message'],
        package="com.affinityapps.blk",
        dry_run=True,
    )
    assert a2 is not None
    assert a2["action"] != "type" or a2.get("text") == ""
    if a2["action"] == "done":
        assert a2.get("dry_run") is True
        assert (
            a2.get("dry_run_verified") is True
            or "never typed" in (a2.get("reason") or "").lower()
        )
    else:
        # clear-only then done on next tick is also OK
        a3 = _heuristic_dm_send(
            BLK_INSTR,
            tree,
            hist + ['type("hi") — Type message', f'{a2["action"]} — {a2["reason"]}'],
            package="com.affinityapps.blk",
            dry_run=True,
        )
        assert a3 and a3["action"] == "done"
        assert (
            a3.get("dry_run_verified") is True
            or "never typed" in (a3.get("reason") or "").lower()
        )


def test_blk_outgoing_requires_sent():
    tree = _load("blk_thread.xml")
    assert blk_outgoing_verified(tree, "hey")
    no_sent = tree.replace('<n t="Sent"', '<n t="Delivered"')
    assert not blk_outgoing_verified(no_sent, "hey")


def test_blk_bulk_uses_right_like_icon():
    deck = _load("blk_deck.xml")
    assert deck_card_name("blk", deck) == "Maya"
    st: dict = {}
    act = plan_bulk_swipe(
        "blk auto-swipe 5 profiles",
        deck,
        ["Opened BLK — launch"],
        state=st,
        package="com.affinityapps.blk",
    )
    assert act and act.get("action") == "tap"
    assert act["x"] == 933
    assert act["y"] == 1733
    # Never left super-like / Boost / card Send a message / Matches nav
    assert (act["x"], act["y"]) not in (
        (790, 1735),
        (540, 2000),
        (300, 1600),
        (675, 2170),
    )
    assert st.get("bulk_swipe", {}).get("done") == 0
