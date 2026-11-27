"""r45: Tagged auto swipe / auto message (unit-tested from the 22 Nov map)."""

from pathlib import Path

from backend import cloud_agent as ca
from backend.dating_run import build_job, clean_modes, instruction_for, split_supported
from backend.dating_schedule import build_modes, normalize
from backend.tagged_fixed import parse_tagged_instruction, plan_tagged_fixed

FIX = Path(__file__).parent / "fixtures" / "dm"
DECK = (FIX / "tagged_match_card.xml").read_text(encoding="utf-8")
PKG = 'packages="com.taggedapp"'


def _tree(body: str) -> str:
    return f'<hierarchy {PKG}><w p="com.taggedapp" a="1">{body}</w></hierarchy>'


PROFILE = _tree(
    '<n i="tvProfileName" t="Casey" xy="540,400" b="[200,360][880,440]" />'
    '<n t="Message" xy="300,1900" b="[150,1840][450,1960]" c="1" />'
    '<n d="Like" xy="540,2050" b="[460,1990][620,2110]" c="1" />'
    '<n t="Send a gift" xy="800,1900" b="[650,1840][950,1960]" c="1" />'
)
THREAD = _tree(
    '<n d="Back" c="1" xy="80,140" b="[20,80][140,200]" />'
    '<n e="1" h="Type a message..." t="{t}" c="1" xy="500,2200" b="[40,2150][900,2250]" />'
    '<n c="1" xy="990,2200" b="[930,2150][1050,2250]" />'
)
PAID = _tree(
    '<n t="Not enough credits" xy="540,900" b="[100,850][980,950]" />'
    '<n t="Buy credits" c="1" xy="540,1300" b="[200,1250][880,1350]" />'
    '<n t="Not now" c="1" xy="540,1500" b="[200,1450][880,1550]" />'
)


def _plan(inst, tree, st, dry=False):
    return plan_tagged_fixed(inst, tree, [], state=st, dry_run=dry, message="hi miss")


def test_parse_and_instruction():
    assert parse_tagged_instruction("fixed tagged message 3") == ("message", 3)
    assert (
        instruction_for(
            "com.taggedapp", None, {"com.taggedapp": 4}, {"com.taggedapp": "message"}
        )
        == "fixed tagged message 4"
    )
    assert instruction_for("com.taggedapp", 6, None, None) == "fixed tagged swipe 6"
    assert clean_modes({"tagged": "message", "bumble": "message", "x": "y"}) == {
        "com.taggedapp": "message"
    }
    ok, bad = split_supported(["tagged"])
    assert ok == ["com.taggedapp"] and not bad
    j = build_job(
        device_id="d",
        queue=["com.taggedapp"],
        count=None,
        dry_run=True,
        counts={"com.taggedapp": 2},
        modes={"com.taggedapp": "message"},
    )
    assert j["instruction"] == "fixed tagged message 2" and j["run_modes"] == {
        "com.taggedapp": "message"
    }


def test_schedule_keeps_tagged_mode():
    s = normalize(
        {
            "items": [{"app": "tagged", "runs": 1, "count": 3, "mode": "message"}],
            "time": "20:00",
            "days": [],
            "dry_run": True,
            "device_id": "d",
        }
    )
    assert build_modes(s) == {"com.taggedapp": "message"}


def test_swipe_taps_free_like_counts_and_stops():
    st = {}
    a = _plan("fixed tagged swipe 2", DECK, st)
    assert (a["action"], a["x"], a["y"]) == (
        "tap",
        860,
        1908,
    )  # likeBtn, never chat/Go Live
    _plan("fixed tagged swipe 2", DECK, st)
    a = _plan("fixed tagged swipe 2", DECK, st)
    assert a["action"] == "done" and st["tagged_fixed"]["done"] == 2


def test_swipe_dry_run_taps_nothing():
    a = _plan("fixed tagged swipe 2", DECK, {}, dry=True)
    assert a["action"] == "done" and a.get("dry_run_verified")


def test_message_full_cycle():
    # Video (27 Nov 2026): tap the photo → Your message → type → send →
    # Back → green heart. Never the chat bubble, never a bare like first.
    st = {}
    inst = "fixed tagged message 1"
    a = _plan(inst, DECK, st)  # tap the photo, not the chat bubble or heart
    assert a["action"] == "tap" and (a["x"], a["y"]) == (540, 900)
    assert (a["x"], a["y"]) != (540, 1911)
    assert (a["x"], a["y"]) != (860, 1908)
    a = _plan(inst, THREAD.format(t=""), st)  # type bank text
    assert a["action"] == "type" and a["text"] == "hi miss"
    a = _plan(inst, THREAD.format(t="hi miss"), st)  # send arrow
    assert a["action"] == "tap" and (a["x"], a["y"]) == (990, 2200)
    a = _plan(inst, THREAD.format(t=""), st)  # box cleared → sent → Back
    assert a["action"] == "press_button" and a["button"] == "back"
    a = _plan(inst, DECK, st)  # green heart on the same card
    assert a["action"] == "tap" and (a["x"], a["y"]) == (860, 1908)
    assert a["fastpath_step"] == "tagged_fixed_like_after"
    assert st["tagged_fixed"]["done"] == 1
    a = _plan(inst, DECK, st)  # after the like → done
    assert a["action"] == "done"
    assert st["tagged_fixed"]["done"] == 1


def test_message_opens_your_message_on_the_profile():
    # After the photo tap, a "Your message" field is already on the
    # profile — type there, never a gift or a paid button.
    your_msg = _tree(
        '<n i="tvProfileName" t="Casey" xy="540,400" b="[200,360][880,440]" />'
        '<n e="1" h="Your message" t="" c="1" xy="500,2200" b="[40,2150][900,2250]" />'
        '<n c="1" xy="990,2200" b="[930,2150][1050,2250]" />'
        '<n t="Send a gift" xy="800,1900" b="[650,1840][950,1960]" c="1" />'
    )
    st = {}
    inst = "fixed tagged message 1"
    _plan(inst, DECK, st)
    a = _plan(inst, your_msg, st)
    assert a["action"] == "type" and a["text"] == "hi miss"


def test_message_falls_back_to_profile_message_button():
    # Opened profile with no composer yet: tap Message, never the gift.
    st = {}
    inst = "fixed tagged message 1"
    _plan(inst, DECK, st)
    a = _plan(inst, PROFILE, st)
    assert a["action"] == "tap" and (a["x"], a["y"]) == (300, 1900)


def test_message_not_sent_retries_then_stops():
    st = {"tagged_fixed": {"done": 0, "phase": "compose", "awaiting_sent": "hi miss"}}
    a = _plan("fixed tagged message 2", THREAD.format(t="hi miss"), st)
    assert a["action"] == "tap" and "again" in a["reason"]
    a = _plan("fixed tagged message 2", THREAD.format(t="hi miss"), st)
    assert a["action"] == "fail"


def test_paid_popup_closed_never_bought():
    a = _plan("fixed tagged swipe 2", PAID, {})
    assert a["action"] == "tap" and (a["x"], a["y"]) == (540, 1500)


def test_off_screen_recovers_by_tab_not_back():
    chats = _tree(
        '<n i="tab_chats" xy="756,2200" b="[680,2130][840,2270]" c="1" />'
        '<n i="tab_match_game" xy="540,2200" b="[460,2130][620,2270]" c="1" />'
        '<n i="conversationList" xy="540,1000" b="[0,200][1080,2100]" />'
    )
    a = _plan("fixed tagged swipe 2", chats, {})
    assert (a["action"], a["x"], a["y"]) == ("tap", 540, 2200)


def test_cloud_agent_routes_tagged_without_llm():
    a = ca.plan_next_action(
        "fixed tagged swipe 3",
        DECK,
        ["Opened Tagged"],
        None,
        package="com.taggedapp",
        dry_run=False,
        agent_state={},
    )
    assert a["planner"] == "tagged_fixed" and (a["x"], a["y"]) == (860, 1908)


EXISTING = (FIX / "tagged_existing_naomi_r55.xml").read_text(encoding="utf-8")


def test_send_arrow_finds_imSendMessageButton():
    from backend.tagged_fixed import _send_xy, on_existing_thread, _thread_name

    xy = _send_xy(EXISTING)
    assert xy == (995, 1302), xy
    assert on_existing_thread(EXISTING)
    assert _thread_name(EXISTING) == "Naomi Paniagua"


def test_existing_thread_clears_and_skips_never_sends():
    # 27 Nov: leftover "good evening beautiful" in Naomi's existing chat.
    st = {}
    inst = "fixed tagged message 5"
    a = _plan(inst, EXISTING, st)
    assert a["fastpath_step"] == "tagged_fixed_clear_existing"
    assert a["clear"] is True and a.get("_clear_only")
    assert a.get("text") == ""
    # The message-text guard must not rewrite this back into a bank line
    from backend.message_text_guard import enforce_message_text

    guarded = enforce_message_text(a, 'fixed tagged message 5 "good evening beautiful"')
    assert guarded.get("text") == "" and guarded.get("_text_source") == "clear_only"
    # After the clear, Back — never the send arrow
    empty = EXISTING.replace('t="good evening beautiful"', 't=""')
    a = _plan(inst, empty, st)
    assert a["action"] == "press_button" and a["button"] == "back"
    assert a["fastpath_step"] == "tagged_fixed_existing_back"
    # Then X on the deck, not the green heart
    a = _plan(inst, DECK, st)
    assert a["fastpath_step"] == "tagged_fixed_skip_existing"
    assert (a["x"], a["y"]) == (220, 1908)
    assert (a["x"], a["y"]) != (860, 1908)
    assert st["tagged_fixed"]["done"] == 0


FIRST = (FIX / "tagged_first_move_leidy_r57.xml").read_text(encoding="utf-8")


def test_send_arrow_on_first_move_screen():
    from backend.tagged_fixed import _send_xy, on_existing_thread, _thread_name

    assert _send_xy(FIRST) == (995, 1323)
    assert not on_existing_thread(FIRST)
    assert _thread_name(FIRST) == "leidy"


def test_send_arrow_fallback_when_button_omitted():
    """Compact dumps may drop the non-clickable send ImageView."""
    from backend.tagged_fixed import _send_xy

    stripped = "\n".join(
        ln for ln in FIRST.splitlines() if "imSendMessageButton" not in ln
    )
    xy = _send_xy(stripped)
    assert xy is not None and xy[0] >= 980 and abs(xy[1] - 1323) <= 5, xy


def test_focus_composer_when_keyboard_is_closed():
    """Send at y≈2196 hits the bottom nav; focus the box first."""
    closed = _tree(
        '<n i="userName" t="leidy" xy="373,148" b="[317,115][429,181]" />'
        '<n t="Say hello" xy="540,1800" b="[414,1760][666,1840]" />'
        '<n t="Make the first move with leidy!" xy="540,1900" b="[253,1870][827,1950]" />'
        '<n e="1" h="Your message" t="hi miss" c="1" i="etMessageEditText" '
        'xy="603,2196" b="[284,2140][922,2250]" />'
        '<n i="imSendMessageButton" cls="ImageView" xy="995,2187" b="[943,2130][1048,2250]" />'
    )
    from backend.tagged_fixed import _send_xy

    assert _send_xy(closed) is None
    st = {"tagged_fixed": {"done": 0, "phase": "compose"}}
    a = _plan("fixed tagged message 1", closed, st)
    assert a["fastpath_step"] == "tagged_fixed_focus_composer"
    assert a["y"] >= 1800


def test_tap_firewall_allows_nonclickable_send_icon():
    from backend.tap_firewall import guard_tap_action

    tree = (FIX / "tagged_first_move_leidy_r57.xml").read_text(encoding="utf-8")
    a = guard_tap_action(
        {
            "action": "tap",
            "x": 995,
            "y": 1323,
            "planner": "tagged_fixed",
            "reason": "Tagged send arrow — message 1/5 (tagged_fixed)",
        },
        tree,
        dry_run=False,
    )
    assert a["action"] == "tap", a
    assert (a["x"], a["y"]) == (995, 1323)


def test_counts_send_before_existing_hook_then_green_heart():
    """After send, a new bubble used to look like an existing chat.

    The job must count first, Back, then the green heart — never X.
    """
    sent = _tree(
        '<n i="userName" t="Gaby J" xy="540,140" b="[200,80][880,200]" />'
        '<n i="tvMessageText" t="hi miss" xy="700,900" b="[400,850][1000,950]" />'
        '<n i="clOuterMessageItem" t="hi miss" xy="700,900" b="[400,850][1000,950]" />'
        '<n e="1" h="Your message" t="" c="1" i="etMessageEditText" '
        'xy="500,1320" b="[40,1270][900,1370]" />'
        '<n i="imSendMessageButton" xy="995,1320" b="[950,1270][1040,1370]" />'
    )
    from backend.tagged_fixed import on_existing_thread, sent_bubble, _thread_name

    assert sent_bubble(sent, "hi miss")
    # Only our just-sent line — not a prior conversation like Naomi.
    assert not on_existing_thread(sent, "hi miss")
    assert _thread_name(sent) == "Gaby J"

    st = {}
    inst = "fixed tagged message 1"
    _plan(inst, DECK, st)  # open photo (card name is Casey)
    _plan(inst, THREAD.format(t=""), st)  # type
    a = _plan(inst, THREAD.format(t="hi miss"), st)  # send
    assert a["fastpath_step"] == "tagged_fixed_send"
    # Bubble appeared — old hook would have skipped; now count + Back.
    a = _plan(inst, sent, st)
    assert a["action"] == "press_button" and a["button"] == "back"
    assert a["fastpath_step"] == "tagged_fixed_thread_back"
    assert a.get("_vision_tag") == "tagged_sent_bubble"
    assert st["tagged_fixed"]["sent_this"] is True
    assert st["tagged_fixed"]["name"] == "Gaby J"
    a = _plan(inst, DECK, st)  # green heart even though stack says Casey
    assert a["fastpath_step"] == "tagged_fixed_like_after"
    assert (a["x"], a["y"]) == (860, 1908)
    assert st["tagged_fixed"]["done"] == 1
    a = _plan(inst, DECK, st)
    assert a["action"] == "done"


def test_name_comes_from_opened_thread_not_stack():
    thread = _tree(
        '<n i="userName" t="Gaby J" xy="540,140" b="[200,80][880,200]" />'
        '<n t="Say hello" xy="540,810" b="[414,773][666,848]" />'
        '<n t="Make the first move with Gaby J!" xy="540,894" b="[253,869][827,919]" />'
        '<n i="llEmptyView" xy="540,730" b="[0,222][1080,1238]" />'
        '<n e="1" h="Your message" t="" c="1" i="etMessageEditText" '
        'xy="500,1320" b="[40,1270][900,1370]" />'
        '<n i="imSendMessageButton" xy="995,1320" b="[950,1270][1040,1370]" />'
    )
    st = {}
    inst = "fixed tagged message 1"
    _plan(inst, DECK, st)
    assert st["tagged_fixed"]["name"] == "Casey"
    a = _plan(inst, thread, st)
    assert a["action"] == "type" and a["text"] == "hi miss"
    assert st["tagged_fixed"]["name"] == "Gaby J"


def test_already_sent_bubble_does_not_remessage():
    """A chat that already has tonight's line must not be sent again."""
    sent = _tree(
        '<n i="userName" t="Ana A" xy="540,140" b="[200,80][880,200]" />'
        '<n i="tvMessageText" t="hi miss" xy="700,900" b="[400,850][1000,950]" />'
        '<n e="1" h="Your message" t="" c="1" i="etMessageEditText" '
        'xy="500,1320" b="[40,1270][900,1370]" />'
        '<n i="imSendMessageButton" xy="995,1320" b="[950,1270][1040,1370]" />'
    )
    st = {}
    inst = "fixed tagged message 1"
    a = _plan(inst, sent, st)
    assert a["action"] == "press_button" and a["button"] == "back"
    assert a["fastpath_step"] == "tagged_fixed_existing_back"
    assert a["action"] != "type"
    a = _plan(inst, DECK, st)
    assert a["fastpath_step"] == "tagged_fixed_skip_existing"
    assert (a["x"], a["y"]) == (220, 1908)
    assert st["tagged_fixed"]["done"] == 0


def test_skip_names_backs_out_without_typing():
    first = _tree(
        '<n i="userName" t="leidy" xy="540,140" b="[200,80][880,200]" />'
        '<n t="Say hello" xy="540,810" b="[414,773][666,848]" />'
        '<n t="Make the first move with leidy!" xy="540,894" b="[253,869][827,919]" />'
        '<n i="llEmptyView" xy="540,730" b="[0,222][1080,1238]" />'
        '<n e="1" h="Your message" t="" c="1" i="etMessageEditText" '
        'xy="500,1320" b="[40,1270][900,1370]" />'
        '<n i="imSendMessageButton" xy="995,1320" b="[950,1270][1040,1370]" />'
    )
    st = {
        "tagged_fixed": {
            "done": 0,
            "phase": "deck",
            "skip_names": ["Ana A", "Gaby J", "muñequita", "leidy"],
        }
    }
    inst = "fixed tagged message 1"
    _plan(inst, DECK, st)
    a = _plan(inst, first, st)
    assert a["action"] == "press_button" and a["button"] == "back"
    assert "will not message" in a["reason"]
    assert st["tagged_fixed"]["done"] == 0


def test_vision_yes_confirms_sent_bubble():
    st = {
        "tagged_fixed": {
            "done": 0,
            "phase": "compose",
            "awaiting_sent": "hi miss",
            "name": "Gaby J",
        },
        "bulk_message_new": {
            "_vision_last": {
                "ok": True,
                "raw": "YES, a sent bubble.",
                "tag": "tagged_sent_bubble",
            },
        },
    }
    # Box still has text and the tree has no bubble — vision says it sent.
    a = _plan("fixed tagged message 1", THREAD.format(t="hi miss"), st)
    assert a["action"] == "press_button" and a["button"] == "back"
    assert st["tagged_fixed"]["sent_this"] is True
