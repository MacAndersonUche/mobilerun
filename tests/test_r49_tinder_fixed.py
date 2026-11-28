"""r49 (CA-24): Tinder fixed auto-swipe — popups closed, matches messaged,
a swipe counted only when deck → deck with a new card. Fixtures are GUESSES
(no real Tinder dump yet)."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend import dating_run as dr
from backend.tinder_fixed_swipe import card_sig, plan_tinder_fixed_swipe, tinder_on_deck

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
A, B, C = (_t(f"tinder_deck_{x}_guess_r49.xml") for x in "abc")
MATCH = _t("tinder_match_guess_r49.xml")
MATCH_TYPED = _t("tinder_match_typed_guess_r49.xml")
GOLD = _t("tinder_gold_guess_r49.xml")
OUT = _t("tinder_outoflikes_guess_r49.xml")
SHADE = _t("system_shade_guess_r49.xml")
PAID_XY = {
    (540, 2000),
    (930, 2000),
    (150, 2000),
    (540, 1900),
}  # Super Like/Boost/Rewind/Continue


def _run(n, trees, st=None):
    st = {} if st is None else st
    return [
        plan_tinder_fixed_swipe(f"fixed tinder swipe {n}", t, [], state=st)
        for t in trees
    ], st


def _xy(a):
    return (a.get("x"), a.get("y"))


def test_detects_deck_and_card():
    assert tinder_on_deck(A) and card_sig(A) == "Amy, 24"
    assert not tinder_on_deck(MATCH) and not tinder_on_deck(GOLD)


def test_counts_only_deck_to_new_card():
    acts, st = _run(2, [A, B, C])
    assert [a["action"] for a in acts] == ["swipe", "swipe", "done"]
    assert acts[0]["x1"] < acts[0]["x2"]  # right-swipe, never a button
    assert st["tinder_run"]["likes"] == 2 and "2/2" in acts[-1]["reason"]


def test_same_card_after_swipe_not_counted():
    acts, st = _run(3, [A, A, B])
    assert st["tinder_run"]["likes"] == 1 and st["tinder_run"]["unverified"] == 1
    acts, st = _run(3, [A, A, A, A])
    assert acts[-1]["action"] == "fail" and st["tinder_run"]["likes"] == 0


def test_popup_after_swipe_not_counted_then_closed():
    acts, st = _run(5, [A, GOLD, B, C])
    assert acts[1]["action"] == "tap" and _xy(acts[1]) == (540, 2100)  # No thanks
    assert st["tinder_run"]["likes"] == 1  # only B→C
    acts, st = _run(5, [A, SHADE, B])
    assert acts[1]["button"] == "back" and st["tinder_run"]["likes"] == 0


def test_match_gets_bank_line_and_carries_on():
    acts, st = _run(3, [A, MATCH, MATCH_TYPED, MATCH, B, C, A])
    steps = [a["fastpath_step"] for a in acts]
    assert steps[1:4] == [
        "tinder_int_match_type",
        "tinder_int_match_send",
        "tinder_int_match_close",
    ]
    assert acts[1]["text"] == "hey how are you" and _xy(acts[2]) == (980, 1800)
    assert _xy(acts[3]) == (80, 150)
    assert st["tinder_run"]["match_msgs"] == 1
    assert steps[4] == "tinder_fixed_like_swipe"
    for a in acts:
        assert _xy(a) not in PAID_XY


def test_out_of_likes_stops_never_buys():
    acts, _ = _run(5, [A, OUT])
    assert acts[1]["action"] == "done" and "out of likes" in acts[1]["reason"]


def test_dating_run_and_routing():
    assert dr.resolve_package("tinder") == "com.tinder"
    assert dr.instruction_for("com.tinder", 7) == "fixed tinder swipe 7"
    job = dr.build_job(device_id="d", queue=["com.tinder"], count=7, dry_run=False)
    assert job["instruction"] == "fixed tinder swipe 7" and job["max_steps"] >= 50
    st: dict = {}
    a = ca.plan_next_action(
        "fixed tinder swipe 7", A, [], package="com.tinder", agent_state=st
    )
    assert a["planner"] == "tinder_fixed" and a["action"] == "swipe"
    assert ca._is_fixed_swipe_action(a) and ca._fixed_swipe_run(
        "fixed tinder swipe 7", st
    )
    d = ca.plan_next_action(
        "fixed tinder swipe 7",
        A,
        [],
        package="com.tinder",
        agent_state={},
        dry_run=True,
    )
    assert d["action"] == "done" and d.get("dry_run_verified")
