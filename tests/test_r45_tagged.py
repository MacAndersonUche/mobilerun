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
    assert instruction_for("com.taggedapp", None, {"com.taggedapp": 4}, {"com.taggedapp": "message"}) == "fixed tagged message 4"
    assert instruction_for("com.taggedapp", 6, None, None) == "fixed tagged swipe 6"
    assert clean_modes({"tagged": "message", "bumble": "message", "x": "y"}) == {"com.taggedapp": "message"}
    ok, bad = split_supported(["tagged"])
    assert ok == ["com.taggedapp"] and not bad
    j = build_job(device_id="d", queue=["com.taggedapp"], count=None, dry_run=True,
                  counts={"com.taggedapp": 2}, modes={"com.taggedapp": "message"})
    assert j["instruction"] == "fixed tagged message 2" and j["run_modes"] == {"com.taggedapp": "message"}


def test_schedule_keeps_tagged_mode():
    s = normalize({"items": [{"app": "tagged", "runs": 1, "count": 3, "mode": "message"}],
                   "time": "20:00", "days": [], "dry_run": True, "device_id": "d"})
    assert build_modes(s) == {"com.taggedapp": "message"}


def test_swipe_taps_free_like_counts_and_stops():
    st = {}
    a = _plan("fixed tagged swipe 2", DECK, st)
    assert (a["action"], a["x"], a["y"]) == ("tap", 860, 1908)  # likeBtn, never chat/Go Live
    _plan("fixed tagged swipe 2", DECK, st)
    a = _plan("fixed tagged swipe 2", DECK, st)
    assert a["action"] == "done" and st["tagged_fixed"]["done"] == 2


def test_swipe_dry_run_taps_nothing():
    a = _plan("fixed tagged swipe 2", DECK, {}, dry=True)
    assert a["action"] == "done" and a.get("dry_run_verified")


def test_message_full_cycle():
    st = {}
    inst = "fixed tagged message 1"
    a = _plan(inst, DECK, st)  # open the profile (name)
    assert a["action"] == "tap" and (a["x"], a["y"]) == (540, 500)
    a = _plan(inst, PROFILE, st)  # open message box (not the gift)
    assert a["action"] == "tap" and (a["x"], a["y"]) == (300, 1900)
    a = _plan(inst, THREAD.format(t=""), st)  # type bank text
    assert a["action"] == "type" and a["text"] == "hi miss"
    a = _plan(inst, THREAD.format(t="hi miss"), st)  # send arrow
    assert a["action"] == "tap" and (a["x"], a["y"]) == (990, 2200)
    a = _plan(inst, THREAD.format(t=""), st)  # box cleared → sent → Back
    assert a["action"] == "press_button" and a["button"] == "back"
    a = _plan(inst, PROFILE, st)  # middle match (free Like)
    assert a["action"] == "tap" and (a["x"], a["y"]) == (540, 2050)
    assert st["tagged_fixed"]["done"] == 1
    a = _plan(inst, DECK, st)
    assert a["action"] == "done"


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
    chats = _tree('<n i="tab_chats" xy="756,2200" b="[680,2130][840,2270]" c="1" />'
                  '<n i="tab_match_game" xy="540,2200" b="[460,2130][620,2270]" c="1" />'
                  '<n i="conversationList" xy="540,1000" b="[0,200][1080,2100]" />')
    a = _plan("fixed tagged swipe 2", chats, {})
    assert (a["action"], a["x"], a["y"]) == ("tap", 540, 2200)


def test_cloud_agent_routes_tagged_without_llm():
    a = ca.plan_next_action("fixed tagged swipe 3", DECK, ["Opened Tagged"], None,
                            package="com.taggedapp", dry_run=False, agent_state={})
    assert a["planner"] == "tagged_fixed" and (a["x"], a["y"]) == (860, 1908)
