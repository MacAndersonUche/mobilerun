"""r51: Facebook Dating — recognize Dating home (real 24 Nov 11:17 tree),
never tap the header, open Facebook instead of a blind tap on the launcher.

Regression from prod job task_18cd1e4745926294 (11:17 UK): after the Dating
tab opened Dating home, hidden off-screen feed nodes made r50 think it was
still on the feed, so it tapped the non-clickable "Dating" header at
(529,133) three times and stopped. Step 0 had been a fallback photo tap on
the Samsung home screen.
"""

from __future__ import annotations

from pathlib import Path

from backend import cloud_agent as ca
from backend.facebook_dating_fixed_first_contact import (
    CARD_PHOTO_XY,
    LIKE_XY,
    PASS_XY,
    PHOTO_XY,
    _dating_home,
    _in_dating,
    plan_facebook_dating_fixed_first_contact,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
HOME = _t("fb_dating_home_r51.xml")
LAUNCHER = _t("samsung_launcher_r51.xml")
FEED = _t("fb_home_feed_r50.xml")
POST = _t("fb_post_viewer_r50.xml")
ELLIE = _t("fb_dating_profile_ellie.xml")
INSTR = 'send 5 first contact messages on facebook dating "hi miss you look beautiful"'
HEADER = (529, 133)


def _p(tree, st, **kw):
    return plan_facebook_dating_fixed_first_contact(
        INSTR, tree, [], state=st, message="hi miss you look beautiful", target=5, **kw
    )


def test_dating_home_is_dating_despite_hidden_feed_nodes():
    assert "What's on your mind?" in HOME
    assert "Story tray" in HOME
    assert _dating_home(HOME) and _in_dating(HOME)
    assert not _dating_home(FEED) and not _in_dating(FEED)
    assert not _dating_home(POST)


def test_dating_home_never_taps_header_waits_then_taps_card():
    """Real 11:17 failure: r50 tapped (529,133) 'Dating' ×3."""
    st: dict = {}
    acts = [_p(HOME, st) for _ in range(4)]
    steps = [a["fastpath_step"] for a in acts]
    assert steps[:2] == ["fb_dating_fc_wait_card", "fb_dating_fc_wait_card"]
    assert acts[2]["fastpath_step"] == "fb_dating_fc_tap_card"
    assert (acts[2]["x"], acts[2]["y"]) == CARD_PHOTO_XY
    for a in acts:
        assert (a.get("x"), a.get("y")) not in (HEADER, (525, 133), (532, 140), LIKE_XY, PASS_XY)
        assert a.get("llm_provider") is None
        if a.get("action") == "tap":
            assert a["y"] > 300


def test_launcher_opens_facebook_never_blind_photo_tap():
    """Real 11:17 step 0: fallback photo tap (539,999) on the Samsung home screen."""
    st: dict = {}
    a = _p(LAUNCHER, st)
    assert a["fastpath_step"] == "fb_dating_nav_open"
    assert a["action"] == "open_app"
    assert a["app"] == "Facebook"
    assert a.get("package") == "com.facebook.katana"
    assert a.get("x") is None
    # bounded — no endless open loop
    for _ in range(4):
        a = _p(LAUNCHER, st)
    assert a["fastpath_step"] == "fb_dating_nav_open_failed"
    assert a["action"] == "fail"


def test_post_then_feed_then_home_still_works():
    """r50 path is intact: Close the post, tap Dating tab, then Dating home."""
    st: dict = {}
    a = _p(POST, st)
    assert a["fastpath_step"] == "fb_dating_nav_close_post"
    a = _p(FEED, st)
    assert a["fastpath_step"] == "fb_dating_nav_tab" and (a["x"], a["y"]) == (630, 2200)
    a = _p(HOME, st)
    assert a["fastpath_step"] == "fb_dating_fc_wait_card"
    a = _p(ELLIE, st)
    assert a["fastpath_step"] == "fb_dating_fc_tap_like"
    assert (a["x"], a["y"]) == LIKE_XY


def test_routed_without_llm_and_quoted_bank_text():
    st: dict = {}
    a = ca.plan_next_action(INSTR, HOME, [], package="com.facebook.katana", agent_state=st)
    assert a["fastpath_step"] == "fb_dating_fc_wait_card"
    assert ca._is_fixed_swipe_action(a)
    b = ca.plan_next_action(INSTR, LAUNCHER, [], package="com.sec.android.app.launcher",
                            agent_state={})
    assert b["action"] == "open_app" and b.get("x") is None
    c = ca.plan_next_action(INSTR, FEED, [], package="com.facebook.katana", agent_state={})
    assert (c.get("x"), c.get("y")) == (630, 2200)
