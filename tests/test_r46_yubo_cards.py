"""r46 (CA-18): Yubo first contact from deck cards — Direct, never Blast,
count only on a sent signal, swipe right, never Conversations."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend.bulk_bench_heuristics import plan_bulk_bench
from backend.yubo_card_first_contact import (
    DECK_TAB_XY,
    ROCKET_XY,
    SEND_XY,
    YUBUCKS_XY,
    on_send_sheet,
    plan_yubo_card_first_contact,
    sent_seen,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
DECK = _t("yubo_card_deck_chloe_r46.xml")
DECK2 = _t("yubo_card_deck_amy_r46.xml")
BLAST = _t("yubo_blast_sheet_r45.xml")  # real 24 Nov dump, instruction text in box
DIRECT = _t("yubo_card_direct_r46.xml")  # bounds from the 22 Nov Direct dump
TYPED = _t("yubo_card_typed_r46.xml")
SENT = _t("yubo_card_sent_r46.xml")
CHATS = _t("yubo_chat_list.xml")
INSTR = "send 2 first contact messages on yubo"
PAID = {YUBUCKS_XY, ROCKET_XY, (855, 1202)}


def _p(tree, st, target=2, dry=False):
    return plan_yubo_card_first_contact(
        INSTR, tree, [], state=st, dry_run=dry, message="hey how are you", target=target
    )


def _xy(a):
    return (a.get("x"), a.get("y"))


def test_detectors():
    assert on_send_sheet(BLAST) and on_send_sheet(DIRECT)
    assert not on_send_sheet(DECK) and not on_send_sheet(CHATS)
    assert sent_seen(SENT, "hey how are you")
    assert not sent_seen(DIRECT, "hey how are you")  # hint "Send a message" ≠ sent
    assert not sent_seen(TYPED, "hey how are you")  # text in the box doesn't count


def test_full_card_cycle_two_messages():
    st: dict = {}
    seq = [DECK, BLAST, DIRECT, TYPED, SENT, DIRECT, DECK,
           DECK2, BLAST, DIRECT, TYPED, SENT, DIRECT, DECK2, DECK]
    acts = [_p(t, st) for t in seq]
    steps = [a["fastpath_step"] for a in acts]
    assert steps[:6] == ["yubo_card_open_send", "yubo_card_select_direct", "yubo_card_type",
                         "yubo_card_send", "yubo_card_close_sheet", "yubo_card_close_sheet"]
    assert _xy(acts[0]) == (210, 2000)  # the pill, not the rocket
    assert acts[2]["text"] == "hey how are you" and acts[2]["clear"] is True
    assert _xy(acts[3]) == SEND_XY
    assert steps[6] == "yubo_card_fixed_like_swipe"
    assert acts[6]["x2"] > acts[6]["x1"]  # right swipe
    assert steps[7] == "yubo_card_open_send"  # next card appeared → repeat
    assert st["yubo_card"]["sent"] == 2
    assert steps[13] == "yubo_card_fixed_like_swipe"
    assert acts[-1]["action"] == "done" and "2/2" in acts[-1]["reason"]
    for a in acts:
        assert _xy(a) not in PAID
        assert a.get("llm_provider") is None and a.get("_no_llm_handoff")
        assert a["fastpath_step"] != "yubo_card_deck_tab"  # never left the cards


def test_never_types_or_sends_on_blast():
    st: dict = {}
    _p(DECK, st)
    for _ in range(3):
        a = _p(BLAST, st)
        assert a["fastpath_step"] == "yubo_card_select_direct"
        assert a["action"] == "tap" and _xy(a) != SEND_XY
    a = _p(BLAST, st)
    assert a["action"] == "fail" and "Blast" in a["reason"]


def test_not_counted_without_sent_signal_and_never_more_than_n_sends():
    st: dict = {}
    for t in (DECK, DIRECT, TYPED):
        _p(t, st, target=1)
    # sheet closed back to the card, no sent signal
    waits = [_p(DECK, st, target=1) for _ in range(3)]
    assert all(w["action"] == "wait" for w in waits)
    a = _p(DECK, st, target=1)
    assert a["fastpath_step"] == "yubo_card_fixed_like_swipe"  # still swiped
    assert st["yubo_card"]["sent"] == 0 and st["yubo_card"]["unconfirmed"] == 1
    a = _p(DECK2, st, target=1)
    assert a["action"] == "done" and "never more than 1" in a["reason"]


def test_text_still_in_box_retries_once_then_moves_on():
    st: dict = {}
    for t in (DECK, DIRECT, TYPED):
        _p(t, st)
    a = _p(TYPED, st)
    assert a["fastpath_step"] == "yubo_card_send_retry"
    a = _p(TYPED, st)
    assert a["fastpath_step"] == "yubo_card_close_sheet"
    assert st["yubo_card"]["sent"] == 0


def test_chats_screen_goes_to_deck_tab_not_conversations():
    a = _p(CHATS, {})
    assert a["fastpath_step"] == "yubo_card_deck_tab" and _xy(a) == DECK_TAB_XY


def test_dry_run_taps_nothing():
    a = _p(DECK, {}, dry=True)
    assert a["action"] == "done" and a["dry_run_verified"]


def test_routed_from_bulk_and_cloud_agent_without_llm():
    st: dict = {}
    a = plan_bulk_bench(INSTR, DECK, [], state=st, package="co.yellw.yellowapp")
    assert a["fastpath_step"] == "yubo_card_open_send"
    st2: dict = {}
    b = ca.plan_next_action(INSTR, DECK, [], package="co.yellw.yellowapp", agent_state=st2)
    assert b["fastpath_step"] == "yubo_card_open_send"
    assert ca._is_fixed_swipe_action(b) and ca._fixed_swipe_run(INSTR, st2)
