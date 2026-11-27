"""r54: Yubo Direct send must tap the up arrow, not a keyboard key below it."""

from __future__ import annotations

from pathlib import Path

from backend.yubo_card_first_contact import SEND_XY, plan_yubo_card_first_contact
from backend.yubo_fixed_first_contact import _send_right_of_composer

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
DECK = _t("yubo_card_deck_chloe_r46.xml")
DECK2 = _t("yubo_card_deck_amy_r46.xml")
DIRECT = _t("yubo_card_direct_r46.xml")
TYPED = _t("yubo_card_typed_r46.xml")
TYPED_KB = _t("yubo_card_typed_keyboard_r54.xml")
INSTR = "send 5 first contact messages on yubo"


def _p(tree, st, target=5):
    return plan_yubo_card_first_contact(
        INSTR, tree, [], state=st, message="hey how are you", target=target
    )


def test_send_arrow_ignores_keyboard_key_below_composer():
    xy = _send_right_of_composer(TYPED_KB)
    assert xy == SEND_XY, xy
    assert xy[1] <= 1398
    # control: the clean typed fixture still resolves to the same arrow
    assert _send_right_of_composer(TYPED) == SEND_XY


def test_card_send_taps_arrow_when_keyboard_is_in_the_tree():
    st: dict = {}
    for t in (DECK, DIRECT, TYPED_KB):
        a = _p(t, st, target=1)
    assert a["fastpath_step"] == "yubo_card_send"
    assert (a["x"], a["y"]) == SEND_XY


def test_two_unconfirmed_sends_stop_with_nothing_confirmed():
    """Don't swipe a third card if Direct never left the box twice."""
    st: dict = {}
    for t in (DECK, DIRECT, TYPED):
        _p(t, st, target=5)
    assert _p(TYPED, st, target=5)["fastpath_step"] == "yubo_card_send_retry"
    a = _p(TYPED, st, target=5)
    assert a["fastpath_step"] == "yubo_card_close_sheet"
    assert st["yubo_card"]["unconfirmed"] == 1 and st["yubo_card"]["sent"] == 0
    _p(DECK, st, target=5)  # swipe first card
    for t in (DECK2, DIRECT, TYPED):
        _p(t, st, target=5)
    assert _p(TYPED, st, target=5)["fastpath_step"] == "yubo_card_send_retry"
    a = _p(TYPED, st, target=5)
    assert a["action"] == "fail" and a["fastpath_step"] == "yubo_card_send_missed"
    assert st["yubo_card"]["sent"] == 0 and st["yubo_card"]["unconfirmed"] == 2
    assert "nothing confirmed" in a["reason"]
