"""r46 (CA-7): Facebook Dating — tap the purple heart (not the profile
ScrollView), type into the photo comment box, tap Send, next card.
Regression from the 24 Nov prod job task_8ba607ca28a3eacd (tapped the bio ×3
and stopped). Video (24 Nov 2026) changed the opener from the photo tap to
the heart; the photo tap stays as the fallback when the heart node is
missing."""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend.facebook_dating_fixed_first_contact import (
    LIKE_XY,
    PASS_XY,
    PHOTO_XY,
    SEND_XY,
    _on_comment_sheet,
    _profile_photo_center,
    plan_facebook_dating_fixed_first_contact,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
PROD = _t("fb_dating_profile_scrollview_r46.xml")  # real 24 Nov tree
ELLIE = _t("fb_dating_profile_ellie.xml")
SHEET = _t("fb_dating_comment_sheet.xml")
TYPED = _t("fb_dating_comment_typed_r46.xml")
INSTR = 'send 2 first contact messages on facebook dating "hi miss you look beautiful"'
BLANK = '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana"><n t="x" xy="5,5"/></w></hierarchy>'


def _p(tree, st, target=2):
    return plan_facebook_dating_fixed_first_contact(
        INSTR, tree, [], state=st, message="hi miss you look beautiful", target=target
    )


def test_heart_opens_comment_box_not_profile_scrollview():
    # Video (24 Nov 2026): the purple heart opens the comment box — the
    # photo tap is only the fallback. The ScrollView regression guard
    # stays: the photo centre must be the real photo, never the bio.
    assert _profile_photo_center(PROD) == PHOTO_XY  # was (540,1174) = the bio
    a = _p(PROD, {})
    assert (
        a["fastpath_step"] == "fb_dating_fc_tap_photo" and (a["x"], a["y"]) != LIKE_XY
    )


def test_typed_box_still_counts_as_comment_sheet():
    assert _on_comment_sheet(SHEET) and _on_comment_sheet(TYPED)
    assert not _on_comment_sheet(PROD) and not _on_comment_sheet(ELLIE)


def test_full_flow_two_comments_then_done():
    st: dict = {}
    zoe = ELLIE.replace("Ellie, 21", "Zoe, 27").replace("Ellie", "Zoe")
    seq = [PROD, BLANK, SHEET, TYPED, ELLIE, SHEET, TYPED, zoe]
    acts = [_p(t, st) for t in seq]
    steps = [a["fastpath_step"] for a in acts]
    assert steps == [
        "fb_dating_fc_tap_photo",
        "fb_dating_fc_wait_sheet",
        "fb_dating_fc_type",
        "fb_dating_fc_send",
        "fb_dating_fc_tap_photo",
        "fb_dating_fc_type",
        "fb_dating_fc_send",
        "fb_dating_fc_done",
    ]
    assert acts[2]["text"] == "hi miss you look beautiful"
    assert (acts[3]["x"], acts[3]["y"]) == SEND_XY
    # r53 (Mac: never a bare like): the opener taps are the photo, never the heart
    # Never tap Pass.
    assert (acts[0]["x"], acts[0]["y"]) != LIKE_XY  # r53: photo, never the heart
    assert (acts[4]["x"], acts[4]["y"]) != LIKE_XY
    for a in acts:
        assert (a.get("x"), a.get("y")) != PASS_XY
        assert a.get("llm_provider") is None


def test_unknown_screen_after_photo_waits_not_taps():
    st: dict = {}
    _p(PROD, st)
    assert _p(BLANK, st)["action"] == "wait"
    assert _p(BLANK, st)["action"] == "wait"
    assert _p(BLANK, st)["action"] == "tap"  # then falls back to the card


def test_not_sent_retries_send_once_never_retypes():
    st: dict = {}
    for t in (SHEET, TYPED):
        _p(t, st, target=5)
    a = _p(TYPED, st, target=5)
    assert a["fastpath_step"] == "fb_dating_fc_send_retry"
    a = _p(TYPED, st, target=5)
    assert a["action"] == "fail"
    # Send never landed (text stayed in the box) — do not count it.
    assert st["bulk_message_new"]["done"] == 0


def test_cap_50_and_routed_without_llm():
    st: dict = {}
    a = plan_facebook_dating_fixed_first_contact(INSTR, SHEET, [], state=st, target=80)
    assert a["action"] == "type"
    st2: dict = {}
    b = ca.plan_next_action(
        INSTR, PROD, [], package="com.facebook.katana", agent_state=st2
    )
    assert (
        b["fastpath_step"] == "fb_dating_fc_tap_photo" and (b["x"], b["y"]) != LIKE_XY
    )
    assert ca._is_fixed_swipe_action(b)
    from backend.dating_run import run_count

    assert run_count("com.facebook.katana", 80) == 50
