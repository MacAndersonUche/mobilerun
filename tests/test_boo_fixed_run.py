"""Unit tests for Boo fixed runner (r50, FLAG_SECURE)."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend import dating_run as dr
from backend import dating_schedule as ds
from backend.boo_fixed_run import (
    boo_card_sig,
    boo_like_button,
    boo_message_button,
    boo_on_deck,
    boo_on_message_composer,
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
RATE = _t("hily_rate_guess_r49.xml").replace("com.hily.app", "enterprises.dating.boo")


def _run(inst, trees, st=None):
    st = {} if st is None else st
    return [plan_boo_fixed_run(inst, t, [], state=st) for t in trees], st


def _xy(a):
    return (a.get("x"), a.get("y"))


def test_parse():
    assert parse("fixed boo likes messages 0 likes 10") == ("likes", 0, 10)
    assert parse("fixed boo message_likes messages 3 likes 25") == ("message_likes", 3, 25)
    assert parse("fixed boo message messages 5 likes 0") == ("message", 5, 0)
    assert parse("fixed boo likes messages 0 likes 600") == ("likes", 0, 500)
    assert parse("fixed boo message_likes messages 10 likes 2") == ("message_likes", 5, 2)
    assert parse("random instruction") == ("", 0, 0)


def test_screen_helpers():
    sw, sh = screen_size_from_tree(BA)
    assert 1000 <= sw <= 1100 and 2200 <= sh <= 2500
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
    assert 800 <= xy[0] <= 900 and 1950 <= xy[1] <= 2050


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
    steps = [a["fastpath_step"] for a in acts]
    assert steps[0] == "boo_message_arrow"
    assert 800 <= acts[0]["x"] <= 900
    assert acts[1]["action"] == "type"
    assert steps[2] == "boo_boo_int_match_send"
    assert steps[3] == "boo_boo_int_match_back"
    assert st["boo_run"]["match_msgs"] == 1
    assert steps[5] == "boo_like_swipe"
    assert acts[-1]["action"] == "done" and "sent 1/1" in acts[-1]["reason"]


def test_popup_after_like_not_counted():
    acts, st = _run("fixed boo likes messages 0 likes 3", [BA, RATE, BA, BB])
    assert acts[1]["fastpath_step"] == "boo_boo_int_close"
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
    assert (
        dr.instruction_for(
            "enterprises.dating.boo",
            3,
            modes={"enterprises.dating.boo": "message"},
        )
        == "fixed boo message messages 3 likes 0"
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
    assert st["boo_run"]["match_msgs"] == 1
    assert st["boo_run"]["msg_end"] == "no more new people (all cards seen)"


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
    assert job["planner"] == "boo_fixed_run" or "boo" in job["instruction"]
