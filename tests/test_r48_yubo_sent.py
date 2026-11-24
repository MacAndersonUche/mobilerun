"""r48: Yubo prod job task_716b21df9960ff91 (24 Nov 10:28) — 4 Direct sends,
the sheet closed back to the card each time, none counted; the waits
tripped stuck-recovery Back (exits Yubo) and max_steps 45 ended the run."""

from __future__ import annotations

from pathlib import Path

from backend import dating_run
from backend.yubo_card_first_contact import plan_yubo_card_first_contact
from backend.yubo_fixed_first_contact import blast_selected
from backend.dm_heuristics import yubo_direct_sheet_action

FIX = Path(__file__).parent / "fixtures" / "dm"
REAL_DIRECT = (FIX / "yubo_direct_selected_r48.xml").read_text(encoding="utf-8")
DECK = (FIX / "yubo_card_deck_chloe_r46.xml").read_text(encoding="utf-8")
DECK2 = (FIX / "yubo_card_deck_amy_r46.xml").read_text(encoding="utf-8")
TYPED = (FIX / "yubo_card_typed_r46.xml").read_text(encoding="utf-8")


def _p(tree, st, target=5):
    return plan_yubo_card_first_contact(
        "send 5 first contact messages on yubo", tree, [], state=st,
        message="hey how are you", target=target)


def test_real_direct_sheet_is_direct_not_blast_and_types():
    assert not blast_selected(REAL_DIRECT)
    assert yubo_direct_sheet_action(REAL_DIRECT) is None  # Direct already on
    st: dict = {}
    _p(DECK, st)
    a = _p(REAL_DIRECT, st)
    assert a["action"] == "type" and a["text"] == "hey how are you"


def test_five_cards_five_counted_no_waits():
    st: dict = {}
    seq = []
    for i in range(5):
        card = DECK if i % 2 == 0 else DECK2
        nxt = DECK2 if i % 2 == 0 else DECK
        seq += [card, REAL_DIRECT, TYPED, card, nxt]
    acts = [_p(t, st) for t in seq]
    steps = [a["fastpath_step"] for a in acts]
    assert "yubo_card_wait_sent" not in steps
    assert steps.count("yubo_card_send") == 5
    assert st["yubo_card"]["sent"] == 5
    assert acts[-1]["action"] == "done" and "5/5" in acts[-1]["reason"]
    assert all(a["action"] != "press_button" or a.get("button") == "back" for a in acts)


def test_fixed_wait_skips_stuck_recovery():
    import inspect

    from backend import cloud_agent

    src = inspect.getsource(cloud_agent)
    assert 'fixed_wait = kind == "wait" and bool(action.get("_no_llm_handoff"))' in src


def test_yubo_max_steps_room_for_five_cards():
    j = dating_run.build_job(device_id="d", queue=["co.yellw.yellowapp"], count=5, dry_run=False)
    assert j["max_steps"] >= 9 * 5 + 20
