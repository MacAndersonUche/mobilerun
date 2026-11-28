"""r49: Hily auto-like — close anything that isn't the Finder card; answer a
match popup with a bank line (free send), then carry on liking."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend.hily_fixed_run import plan_hily_fixed_run
from backend.hily_interrupts import is_match_popup, safe_close

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
FINDER = _t("hily_finder.xml")
BARE = _t("hily_finder_empty_a11y_r47.xml")  # real 24 Nov Finder (card not in tree)
MATCH = _t("hily_match_popup_guess_r49.xml")
MATCH_TYPED = _t("hily_match_popup_typed_r49.xml")
SAYHI = _t("hily_match_sayhi_guess_r49.xml")
THREAD = _t("hily_match_thread_r49.xml")
PROMO = _t("hily_promo_guess_r49.xml")
RATE = _t("hily_rate_guess_r49.xml")
SHADE = _t("system_shade_guess_r49.xml")
PERM = _t("permission_dialog_guess_r49.xml")
FIRST_LIKE = _t("hily_popup_first_like.xml")  # real popup map
NOTIF = _t("hily_popup_notif.xml")
CRUSH_XY = (540, 1959)


def _run(inst, trees, st=None):
    st = {} if st is None else st
    return [plan_hily_fixed_run(inst, t, [], state=st) for t in trees], st


def _xy(a):
    return (a.get("x"), a.get("y"))


def test_match_popup_types_sends_closes_and_counts():
    acts, st = _run(
        "fixed hily likes 3",
        [FINDER, MATCH, MATCH_TYPED, MATCH, FINDER, FINDER, FINDER, FINDER],
    )
    steps = [a["fastpath_step"] for a in acts]
    assert steps[:4] == [
        "hily_run_fixed_like_swipe",
        "hily_int_match_type",
        "hily_int_match_send",
        "hily_int_match_close",
    ]
    assert acts[1]["text"] == "hey how are you"
    assert _xy(acts[2]) == (980, 1700)
    assert acts[3]["reason"].startswith("Match message sent") and _xy(acts[3]) == (
        540,
        1950,
    )
    assert st["hily_run"]["match_msgs"] == 1
    assert acts[-1]["action"] == "done"
    assert (
        "3/3 likes" in acts[-1]["reason"] and "1 match messages" in acts[-1]["reason"]
    )
    assert all(_xy(a) != CRUSH_XY for a in acts)


def test_say_hi_opens_thread_sends_then_back():
    acts, st = _run("fixed hily likes 5", [FINDER, SAYHI, THREAD, THREAD, THREAD])
    steps = [a["fastpath_step"] for a in acts]
    assert steps[1] == "hily_int_match_open" and _xy(acts[1]) == (540, 1800)
    assert steps[2] == "hily_int_match_type"
    # THREAD fixture keeps an empty box, so after the type step it shows as typed=0;
    # the send happens once the box holds the text
    st2 = {"hily_run": {"likes": 1, "phase": "likes1", "match": {"open": True}}}
    typed = THREAD.replace('h="Aa"', 'h="Aa" t="hey how are you"')
    a = plan_hily_fixed_run("fixed hily likes 5", typed, [], state=st2)
    assert a["fastpath_step"] == "hily_int_match_send" and _xy(a) == (1017, 1330)
    a = plan_hily_fixed_run("fixed hily likes 5", THREAD, [], state=st2)
    assert a["fastpath_step"] == "hily_int_match_back" and a["button"] == "back"
    assert st2["hily_run"]["match_msgs"] == 1


def test_popups_closed_never_paid():
    st = {"hily_run": {"likes": 0, "phase": "likes1"}}
    a = plan_hily_fixed_run("fixed hily likes 5", PROMO, [], state=st)
    assert a["action"] in ("tap", "press_button")
    if a["action"] == "tap":
        assert _xy(a) == (980, 150)  # the X, never Continue (540,1900)
    a = plan_hily_fixed_run("fixed hily likes 5", RATE, [], state=st)
    assert a["fastpath_step"] == "hily_int_close" and _xy(a) == (540, 1450)  # Not now
    a = plan_hily_fixed_run("fixed hily likes 5", NOTIF, [], state=st)
    assert _xy(a) == (540, 1650)  # Maybe later, never Allow
    a = plan_hily_fixed_run("fixed hily likes 5", FIRST_LIKE, [], state=st)
    assert _xy(a) == (540, 1600)  # Got it


def test_system_shade_and_permission():
    st = {"hily_run": {"likes": 0, "phase": "likes1"}}
    a = plan_hily_fixed_run("fixed hily likes 5", SHADE, [], state=st)
    assert a["fastpath_step"] == "hily_int_system_back" and a["button"] == "back"
    a = plan_hily_fixed_run("fixed hily likes 5", PERM, [], state=st)
    assert a["fastpath_step"] == "hily_int_permission" and _xy(a) == (540, 1650)


def test_detectors_and_finder_untouched():
    assert is_match_popup(MATCH) and is_match_popup(SAYHI)
    assert not is_match_popup(FINDER) and not is_match_popup(BARE)
    assert safe_close(PROMO)[:2] == (980, 150)
    # bare Finder (real tree) still likes with the map heart, no interrupt
    acts, _ = _run("fixed hily likes 2", [BARE, BARE, BARE, BARE])
    assert [a["fastpath_step"] for a in acts][:3] == [
        "hily_run_wait_card",
        "hily_run_fixed_like_swipe",
        "hily_run_fixed_like_swipe",
    ]


def test_heart_followed_by_popup_is_not_counted():
    """Mac 24 Nov: something appeared during the tap → it wasn't a like."""
    acts, st = _run("fixed hily likes 2", [FINDER, RATE, FINDER, FINDER])
    hr = st["hily_run"]
    assert hr["likes"] == 1 and hr["unverified_likes"] == 1
    assert acts[2]["fastpath_step"] == "hily_run_fixed_like_swipe"  # tapped again
    for pop in (NOTIF, FIRST_LIKE, SHADE, PROMO, MATCH):
        st = {}
        _run("fixed hily likes 5", [FINDER, pop, FINDER], st)
        assert st["hily_run"]["likes"] == 0, pop[:80]


def test_heart_counted_only_finder_to_finder():
    acts, st = _run("fixed hily likes 2", [FINDER, FINDER, FINDER])
    assert st["hily_run"]["likes"] == 2 and acts[-1]["action"] == "done"
    assert not st["hily_run"].get("unverified_likes")


def test_routed_without_llm():
    st: dict = {"hily_run": {"likes": 0, "phase": "likes1"}}
    a = ca.plan_next_action(
        "fixed hily likes 5", MATCH, [], package="com.hily.app", agent_state=st
    )
    assert (
        a["fastpath_step"] == "hily_int_match_type" and a["planner"] == "hily_fixed_run"
    )
