"""Unit tests for Boo fixed runner (r50, FLAG_SECURE)."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend import dating_run as dr
from backend import dating_schedule as ds
from backend.boo_fixed_run import (
    boo_card_sig,
    boo_composer,
    boo_like_button,
    boo_message_button,
    boo_on_deck,
    boo_on_message_composer,
    boo_send_button,
    boo_top_card,
    parse,
    plan_boo_fixed_run,
    scale_coords,
    screen_size_from_tree,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
BA = _t("boo_deck_a_guess_r50.xml")
BB = _t("boo_deck_b_guess_r50.xml")
B_TH = _t("boo_thread_guess_r50.xml")
B_TH_T = _t("boo_thread_typed_guess_r50.xml")
LIVE_DECK = _t("boo_live_deck_dm_icon.xml")
LIVE_EMPTY = _t("boo_live_composer_empty.xml")
LIVE_TYPED = _t("boo_live_composer_typed.xml")
LIVE_AFTER = _t("boo_live_after_send_next_card.xml")
RATE = _t("hily_rate_guess_r49.xml").replace("com.hily.app", "enterprises.dating.boo")


def _run(inst, trees, st=None):
    st = {} if st is None else st
    return [plan_boo_fixed_run(inst, t, [], state=st) for t in trees], st


def _xy(a):
    return (a.get("x"), a.get("y"))


def test_parse():
    assert parse("fixed boo likes messages 0 likes 10") == ("likes", 0, 10)
    assert parse("fixed boo message_likes messages 3 likes 25") == (
        "message_likes",
        3,
        25,
    )
    assert parse("fixed boo message messages 5 likes 0") == ("message", 5, 0)
    assert parse("fixed boo likes messages 0 likes 600") == ("likes", 0, 500)
    assert parse("fixed boo message_likes messages 10 likes 2") == (
        "message_likes",
        5,
        2,
    )
    assert parse("random instruction") == ("", 0, 0)


def test_screen_helpers():
    sw, sh = screen_size_from_tree(BA)
    assert 800 <= sw <= 1100 and 1600 <= sh <= 2500
    x, y = scale_coords(1080, 2400, 0.61, 0.85)
    assert 650 <= x <= 670 and 2000 <= y <= 2060


def test_boo_on_deck():
    assert boo_on_deck(BA)
    assert boo_on_deck(BB)
    assert not boo_on_deck(B_TH)


def test_boo_on_message_composer():
    assert boo_on_message_composer(B_TH)
    assert boo_on_message_composer(B_TH_T)
    assert not boo_on_message_composer(BA)


def test_boo_card_sig():
    assert "Ava" in boo_card_sig(BA)
    assert boo_card_sig(BB) != boo_card_sig(BA)


def test_boo_like_button():
    sw, sh = 1080, 2400
    xy = boo_like_button(BA, sw, sh)
    assert xy is not None
    assert 700 <= xy[0] <= 800 and 1950 <= xy[1] <= 2050


def test_boo_message_button():
    sw, sh = 1080, 2400
    xy = boo_message_button(BA, sw, sh)
    assert xy is not None
    # BA has no DM control: fractional fallback on the action row, never the
    # bottom nav "Messages" tab (756, 2200) the old substring match picked.
    assert xy != (756, 2200) and 1900 <= xy[1] <= 2100


def test_boo_likes_only():
    acts, st = _run("fixed boo likes messages 0 likes 2", [BA, BB, BA])
    assert len(acts) == 3
    assert acts[0]["action"] == "tap"
    assert 650 <= acts[0]["x"] <= 850
    assert acts[-1]["action"] == "done" and "2/2 likes" in acts[-1]["reason"]
    assert st["boo_run"]["likes"] == 2


def test_boo_likes_counted_on_card_change():
    acts, st = _run("fixed boo likes messages 0 likes 5", [BA, BA, BA, BA])
    assert acts[-1]["action"] == "fail" and st["boo_run"]["likes"] == 0


def test_boo_message_then_like():
    acts, st = _run(
        "fixed boo message_likes messages 1 likes 1",
        [BA, B_TH, B_TH_T, B_TH, BA, BB, BA],
    )
    steps = [a.get("fastpath_step", "") for a in acts]
    assert steps[0] == "boo_message_arrow"
    assert acts[0]["y"] < 2100  # action row, not the nav Messages tab
    assert any(a["action"] == "type" for a in acts)
    assert "boo_like_swipe" in steps
    assert acts[-1]["action"] == "done"
    assert "1/1 likes" in acts[-1]["reason"]


def test_popup_after_like_not_counted():
    acts, st = _run("fixed boo likes messages 0 likes 3", [BA, RATE, BA, BB])
    assert acts[1]["fastpath_step"] == "boo_fixed_int_close"
    assert st["boo_run"]["likes"] == 1 and st["boo_run"]["unverified"] == 1


def test_boo_dry_run():
    acts, st = _run("fixed boo likes messages 0 likes 10", [BA], st={"dry_run": True})
    a = plan_boo_fixed_run(
        "fixed boo likes messages 0 likes 10", BA, [], state={}, dry_run=True
    )
    assert a["action"] == "done" and a.get("dry_run_verified")


def test_dating_run_instruction_routing():
    assert dr.resolve_package("boo") == "enterprises.dating.boo"
    assert (
        dr.instruction_for(
            "enterprises.dating.boo",
            4,
            modes={"enterprises.dating.boo": "message_likes"},
            like_caps={"enterprises.dating.boo:message_likes": 40},
        )
        == "fixed boo message_likes messages 4 likes 40"
    )
    assert (
        dr.instruction_for("enterprises.dating.boo", 9)
        == "fixed boo likes messages 0 likes 9"
    )


def test_dating_schedule_integration():
    sch = ds.normalize(
        {
            "time": "10:00",
            "device_id": "android_x",
            "items": [
                {
                    "app": "enterprises.dating.boo",
                    "runs": 1,
                    "count": 2,
                    "mode": "message_likes",
                    "likes": 20,
                },
            ],
        }
    )
    items = sch["items"]
    assert items[0]["mode"] == "message_likes" and items[0]["likes"] == 20
    assert ds.build_like_caps(sch) == {"enterprises.dating.boo:message_likes": 20}


def test_cloud_agent_routing():
    a = ca.plan_next_action(
        "fixed boo likes messages 0 likes 9",
        BA,
        [],
        package="enterprises.dating.boo",
        agent_state={},
    )
    assert a["planner"] == "boo_fixed_run"
    assert ca._is_fixed_swipe_action(a)
    d = ca.plan_next_action(
        "fixed boo likes messages 0 likes 2",
        BA,
        [],
        package="enterprises.dating.boo",
        agent_state={},
        dry_run=True,
    )
    assert d["action"] == "done" and d.get("dry_run_verified")


def test_boo_no_repeat_card():
    acts, st = _run(
        "fixed boo message_likes messages 3 likes 1",
        [BA, B_TH, B_TH_T, B_TH, BA, B_TH, B_TH_T, B_TH, BA],
    )
    assert st["boo_run"]["msg_end"] == "no more new people (all cards seen)"
    assert st["boo_run"]["phase"] == "likes"


def test_job_build_boo():
    job = dr.build_job(
        device_id="d",
        queue=["enterprises.dating.boo"],
        count=3,
        dry_run=False,
        modes={"enterprises.dating.boo": "message_likes"},
        like_caps={"enterprises.dating.boo:message_likes": 30},
    )
    assert job["instruction"] == "fixed boo message_likes messages 3 likes 30"
    assert "boo" in job["instruction"]


# ---- r51: live SM-G996B trees (28 Nov 2026): DM icon, send arrow, send animation ----


def test_live_dm_button_is_the_dm_icon_not_love_or_nav():
    # Old substring match picked "Send a Love with Context" (1001, 2223).
    assert boo_message_button(LIVE_DECK, 1080, 2400) == (964, 2025)


def test_live_send_arrow_is_lower_right_icon_never_the_ai_circle():
    edit = boo_composer(LIVE_TYPED)
    assert edit is not None
    # AI mode circle is the unlabelled Button in the field's row at (988, 1219).
    # The send arrow is the lower right ImageView at (992, 1320).
    assert boo_send_button(LIVE_TYPED, edit) == (992, 1320)


def test_send_arrow_missing_refuses_the_ai_circle():
    no_arrow = LIVE_TYPED.replace(
        '<n cls="ImageView" c="1" xy="992,1320" b="957,1285,1028,1356"/>', ""
    )
    assert "992,1320" not in no_arrow
    assert boo_send_button(no_arrow, boo_composer(no_arrow)) is None
    st = {}
    inst = "fixed boo message messages 1 likes 0"
    plan_boo_fixed_run(inst, LIVE_DECK, [], state=st, message="hey how are you")
    plan_boo_fixed_run(inst, LIVE_EMPTY, [], state=st, message="hey how are you")
    a = plan_boo_fixed_run(inst, no_arrow, [], state=st, message="hey how are you")
    assert a["action"] == "press_button"  # leaves the composer, no tap on the circle
    assert st["boo_run"]["msg_end"].startswith("send arrow not found")


def test_live_message_flow_type_send_wait_next_card_then_done():
    inst = "fixed boo message messages 1 likes 0"
    msg = "hey how are you"
    st = {}

    def p(tree):
        return plan_boo_fixed_run(inst, tree, [], state=st, message=msg)

    a = p(LIVE_DECK)
    assert a["fastpath_step"] == "boo_message_arrow" and _xy(a) == (964, 2025)
    a = p(LIVE_EMPTY)  # composer open, empty box
    assert a["action"] == "type" and a["text"] == msg
    a = p(LIVE_TYPED)  # text in the box: tap the SEND arrow
    assert a["fastpath_step"] == "boo_fixed_int_match_send" and _xy(a) == (992, 1320)
    assert (_xy(a)) != (988, 1219)
    # send animation overlay: composer gone, deck not readable yet -> wait, never tap
    overlay = '<hierarchy windows="1"><w id="active" p="enterprises.dating.boo" f="1">\n <n cls="View" xy="540,1200" b="0,0,1080,2400"/>\n</w></hierarchy>'
    a = p(overlay)
    assert a["action"] == "wait"
    # next card showing (front card changed): message counted, run finishes
    a = p(LIVE_AFTER)
    assert a["action"] == "done" and "sent 1/1" in a["reason"]
    assert st["boo_run"]["match_msgs"] == 1


def test_send_not_confirmed_if_deck_never_advances():
    inst = "fixed boo message messages 1 likes 0"
    msg = "hey how are you"
    st = {}

    def p(tree):
        return plan_boo_fixed_run(inst, tree, [], state=st, message=msg)

    p(LIVE_DECK)
    p(LIVE_EMPTY)
    p(LIVE_TYPED)
    acts = [p(LIVE_DECK) for _ in range(12)]  # same front card as before the DM
    assert any(a and a["action"] == "wait" for a in acts)
    assert st["boo_run"].get("match_msgs", 0) == 0
    assert "not confirmed" in st["boo_run"]["msg_end"]


def test_top_card_names():
    assert boo_top_card(LIVE_DECK) == "Kim"
    assert boo_top_card(LIVE_AFTER) == "Sam"


# ---- Send budget guard: never tap send arrow more than the message limit ----


def test_send_budget_guard_refuses_second_tap_with_limit_1():
    """A run with messages=1 can never issue a second send tap."""
    inst = "fixed boo message messages 1 likes 0"
    st = {}

    def p(tree):
        return plan_boo_fixed_run(inst, tree, [], state=st, message="hey how are you")

    # Open composer and simulate having typed the message already
    p(LIVE_DECK)
    # Manually set up state as if we've already typed
    st["boo_run"]["composer"] = {"typed": 1}
    st["boo_run"]["opener"]["text"] = "hey how are you"
    # Now LIVE_TYPED has matching text, so it will tap send (1st attempt)
    act = p(LIVE_TYPED)
    assert act["action"] == "tap" and "attempt 1" in act["reason"]
    assert st["boo_run"]["send_attempts"] == 1
    # Composer still open after tap (send arrow tapped but not confirmed yet)
    # Budget guard: attempted=1, confirmed=0, limit=1 -> no more taps allowed
    act = p(LIVE_TYPED)
    assert act["action"] == "press_button"  # exits composer
    assert "send budget exhausted" in st["boo_run"]["msg_end"]
    assert "attempted 1" in st["boo_run"]["msg_end"]


def test_send_budget_guard_ambiguous_state_exits_without_tapping():
    """If composer state is ambiguous, exit without tapping."""
    inst = "fixed boo message messages 1 likes 0"
    st = {}

    def p(tree):
        return plan_boo_fixed_run(inst, tree, [], state=st, message="hey how are you")

    # Open composer and set up state as if we've typed
    p(LIVE_DECK)
    st["boo_run"]["composer"] = {"typed": 1}
    st["boo_run"]["opener"]["text"] = "hey how are you"
    # Remove send arrow to make state ambiguous
    no_arrow = LIVE_TYPED.replace(
        '<n cls="ImageView" c="1" xy="992,1320" b="957,1285,1028,1356"/>', ""
    )
    act = p(no_arrow)
    assert act["action"] == "press_button"
    assert "send arrow not found" in st["boo_run"]["msg_end"]
    assert st["boo_run"].get("send_attempts", 0) == 0  # never incremented


def test_send_budget_allows_multiple_sends_within_limit():
    """With messages=2, can attempt 2 sends but not 3."""
    inst = "fixed boo message messages 2 likes 0"
    st = {}

    def p(tree):
        return plan_boo_fixed_run(inst, tree, [], state=st, message="hey how are you")

    # First person: set up state as if typed, then send (attempt 1)
    p(LIVE_DECK)
    st["boo_run"]["composer"] = {"typed": 1}
    st["boo_run"]["opener"]["text"] = "hey how are you"
    st["boo_run"]["match"] = {"open": True}
    act = p(LIVE_TYPED)
    assert "attempt 1" in act["reason"]
    assert st["boo_run"]["send_attempts"] == 1
    # Clear match to allow second DM
    st["boo_run"].pop("after_send", None)
    st["boo_run"]["match_msgs"] = 0  # confirmed sends
    st["boo_run"]["composer"] = {}
    st["boo_run"]["opener"] = {"text": "hey how are you"}
    st["boo_run"]["match"] = {"open": True}
    # Second attempt with text already matching
    st["boo_run"]["composer"] = {"typed": 1}
    act = p(LIVE_TYPED)
    assert "attempt 2" in act["reason"]
    assert st["boo_run"]["send_attempts"] == 2
    # Try third tap: budget exhausted (attempted=2, confirmed=0, limit=2)
    st["boo_run"].pop("after_send", None)
    st["boo_run"]["composer"] = {"typed": 1}
    st["boo_run"]["match"] = {"open": True}
    act = p(LIVE_TYPED)
    assert act["action"] == "press_button"
    assert "send budget exhausted" in st["boo_run"]["msg_end"]
    assert "attempted 2" in st["boo_run"]["msg_end"]


def test_no_blind_coordinate_taps_in_composer():
    """Only the identified send arrow is tapped; no blind/coordinate taps."""
    inst = "fixed boo message messages 3 likes 0"  # limit=3 to allow more attempts
    st = {}

    def p(tree):
        return plan_boo_fixed_run(inst, tree, [], state=st, message="hey how are you")

    # Open composer and set up state as if typed
    p(LIVE_DECK)
    st["boo_run"]["composer"] = {"typed": 1}
    st["boo_run"]["opener"]["text"] = "hey how are you"
    st["boo_run"]["match"] = {"open": True}
    # Only tap if boo_send_button returns valid coordinates
    act = p(LIVE_TYPED)
    assert act["action"] == "tap"
    assert act["x"] == 992 and act["y"] == 1320  # identified send arrow
    # Remove send arrow: no fallback coordinate tap
    no_arrow = LIVE_TYPED.replace(
        '<n cls="ImageView" c="1" xy="992,1320" b="957,1285,1028,1356"/>', ""
    )
    # Reset state for second attempt
    st["boo_run"]["opener"] = {"text": "hey how are you"}
    st["boo_run"]["send_attempts"] = 1  # keep the first attempt
    st["boo_run"]["match_msgs"] = 0  # no confirmed sends yet
    st["boo_run"].pop("after_send", None)
    st["boo_run"].pop("msg_end", None)
    st["boo_run"]["phase"] = "message"
    st["boo_run"]["match"] = {"open": True}
    st["boo_run"]["composer"] = {"typed": 1}
    act = p(no_arrow)
    assert act["action"] == "press_button"  # exits, no tap
    assert "send arrow not found" in st["boo_run"]["msg_end"]
    # Verify send_attempts was not incremented
    assert st["boo_run"]["send_attempts"] == 1
