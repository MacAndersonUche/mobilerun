"""r50: Boo / Breeze / Taimi / Pure / 3Fun fixed runs. Taimi trees are real
(19 Nov); Boo / Breeze / Pure / 3Fun fixtures are GUESSES."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend import dating_run as dr
from backend import dating_schedule as ds
from backend.fixed_like_run import generic_like_button, plan_fixed_like_run

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
TP = _t("taimi_people.xml")
TP2 = TP.replace('t="Alex"', 't="Becky"').replace("12 left", "11 left")
TP3 = TP.replace('t="Alex"', 't="Cleo"').replace("12 left", "10 left")
T_CUR = _t("taimi_curated.xml")
T_CHATS = _t("taimi_chats.xml")
T_THREAD = _t("taimi_thread.xml")
T_ZERO = _t("taimi_zero_left.xml")
BA, BB = _t("boo_deck_a_guess_r50.xml"), _t("boo_deck_b_guess_r50.xml")
B_CHATS = _t("boo_chats_guess_r50.xml")
B_TH, B_TH_T = _t("boo_thread_guess_r50.xml"), _t("boo_thread_typed_guess_r50.xml")
BR1, BR2 = _t("breeze_deck_guess_r50.xml"), _t("breeze_deck_b_guess_r50.xml")
F1, F2 = _t("threefun_deck_guess_r50.xml"), _t("threefun_deck_b_guess_r50.xml")
PURE = _t("pure_deck_guess_r50.xml")
RATE = _t("hily_rate_guess_r49.xml").replace("com.hily.app", "enterprises.dating.boo")
PAID = {(540, 2000), (850, 145), (985, 145), (541, 1948)}


def _run(inst, trees, st=None):
    st = {} if st is None else st
    return [plan_fixed_like_run(inst, t, [], state=st) for t in trees], st


def _xy(a):
    return (a.get("x"), a.get("y"))


def test_taimi_likes_counted_on_card_change_real_trees():
    acts, st = _run("fixed app taimi likes messages 0 likes 2", [TP, TP2, TP3])
    assert [_xy(a) for a in acts[:2]] == [(761, 1948)] * 2
    assert acts[-1]["action"] == "done" and st["fixed_like_run"]["likes"] == 2
    acts, st = _run("fixed app taimi likes messages 0 likes 5", [TP, TP, TP, TP])
    assert acts[-1]["action"] == "fail" and st["fixed_like_run"]["likes"] == 0


def test_taimi_curated_skipped_zero_left_stops():
    a, st = _run("fixed app taimi likes messages 0 likes 5", [T_CUR])
    assert a[0]["fastpath_step"] == "fixed_like_skip_curated" and _xy(a[0]) == (320, 1948)
    assert not st["fixed_like_run"].get("awaiting")
    a, _ = _run("fixed app taimi likes messages 0 likes 5", [T_ZERO])
    assert a[0]["action"] == "done"


def test_taimi_message_then_like():
    typed = T_THREAD.replace('t="" h="Say something..."', 't="hey how are you" h="Say something..."')
    acts, st = _run("fixed app taimi message_likes messages 1 likes 1",
                    [TP, T_CHATS, T_THREAD, typed, T_THREAD, T_CHATS, TP, TP2])
    steps = [a["fastpath_step"] for a in acts]
    assert steps[0] == "fixed_like_chats_tab" and _xy(acts[0]) == (972, 2200)
    assert steps[1] == "fixed_like_open_match" and _xy(acts[1]) == (270, 700)
    assert acts[2]["action"] == "type" and acts[2]["text"] in dr_bank()
    assert steps[3] == "fixed_like_taimi_int_match_send"
    assert steps[4] == "fixed_like_taimi_int_match_back"
    assert st["fixed_like_run"]["match_msgs"] == 1
    assert steps[6] == "fixed_like_tap_like_swipe"
    assert acts[-1]["action"] == "done" and "sent 1/1" in acts[-1]["reason"]


def dr_bank():
    return ("hey how are you", "hi miss", "hello miss", "good morning")


def test_boo_like_and_message_guess():
    acts, st = _run("fixed app boo likes messages 0 likes 2", [BA, BB, BA])
    assert _xy(acts[0]) == (750, 2000) and acts[-1]["action"] == "done"
    acts, st = _run("fixed app boo message_likes messages 1 likes 1",
                    [BA, B_CHATS, B_TH, B_TH_T, B_TH, B_CHATS, BA, BB])
    steps = [a["fastpath_step"] for a in acts]
    assert _xy(acts[0]) == (756, 2200)  # Messages tab
    assert _xy(acts[1]) == (540, 500)  # "Zoe, New match" — never Kim (old chat)
    assert steps[2:5] == ["fixed_like_boo_int_match_type", "fixed_like_boo_int_match_send",
                          "fixed_like_boo_int_match_back"]
    assert acts[-1]["action"] == "done"
    for a in acts:
        assert _xy(a) not in PAID


def test_popup_after_like_not_counted():
    acts, st = _run("fixed app boo likes messages 0 likes 3", [BA, RATE, BA, BB])
    assert acts[1]["fastpath_step"] == "fixed_like_boo_int_close"
    assert st["fixed_like_run"]["likes"] == 1 and st["fixed_like_run"]["unverified"] == 1


def test_breeze_threefun_pure_like_buttons_never_super():
    assert generic_like_button(BR1) == (750, 2000)
    assert generic_like_button(F1) == (750, 2000)  # btn_like, never btn_superlike
    acts, st = _run("fixed app breeze likes messages 0 likes 1", [BR1, BR2])
    assert acts[-1]["action"] == "done"
    acts, st = _run("fixed app threefun likes messages 0 likes 1", [F1, F2])
    assert acts[-1]["action"] == "done"
    a, _ = _run("fixed app pure message messages 2 likes 0", [PURE])
    assert a[0]["fastpath_step"] == "fixed_like_chats_tab" and _xy(a[0]) == (900, 2200)


def test_dating_run_schedule_and_routing():
    for key, pkg in (("boo", "enterprises.dating.boo"), ("breeze", "social.breeze.breeze_app"),
                     ("pure", "com.getpure.pure"), ("3fun", "com.threesome.swingers.threefun"),
                     ("taimi", "com.takimi.android")):
        assert dr.resolve_package(key) == pkg
    assert dr.instruction_for("enterprises.dating.boo", 4,
                              modes={"enterprises.dating.boo": "message_likes"},
                              like_caps={"enterprises.dating.boo:message_likes": 40}
                              ) == "fixed app boo message_likes messages 4 likes 40"
    assert dr.instruction_for("social.breeze.breeze_app", 9) == \
        "fixed app breeze likes messages 0 likes 9"
    assert dr.clean_like_caps({"com.takimi.android:message_likes": 50,
                               "com.takimi.android:likes": 9}) == {
        "com.takimi.android:message_likes": 50}
    job = dr.build_job(device_id="d", queue=["com.getpure.pure"], count=3, dry_run=False,
                       modes={"com.getpure.pure": "message"})
    assert job["instruction"] == "fixed app pure message messages 3 likes 0"
    sch = ds.normalize({"time": "10:00", "device_id": "android_x", "items": [
        {"app": "enterprises.dating.boo", "runs": 1, "count": 2, "mode": "message_likes",
         "likes": 20}, {"app": "com.threesome.swingers.threefun", "count": 5}]})
    items = sch["items"]
    assert items[0]["mode"] == "message_likes" and items[0]["likes"] == 20
    assert items[1]["mode"] == "likes" and "likes" not in items[1]
    assert ds.build_like_caps(sch) == {"enterprises.dating.boo:message_likes": 20}
    a = ca.plan_next_action("fixed app breeze likes messages 0 likes 9", BR1, [],
                            package="social.breeze.breeze_app", agent_state={})
    assert a["planner"] == "fixed_like_run" and _xy(a) == (750, 2000)
    assert ca._is_fixed_swipe_action(a)
    d = ca.plan_next_action("fixed app boo likes messages 0 likes 2", BA, [],
                            package="enterprises.dating.boo", agent_state={}, dry_run=True)
    assert d["action"] == "done" and d.get("dry_run_verified")
