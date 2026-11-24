"""r50: shared paid-popup closer (all fixed runs) + Facebook Dating
navigation (real 24 Nov 10:55 post-viewer tree, real 19 Nov home tree)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import cloud_agent as ca
from backend.facebook_dating_fixed_first_contact import (
    plan_facebook_dating_fixed_first_contact as fb,
)
from backend.paid_popup import is_paid_popup, paid_close_target

FIX = Path(__file__).parent / "fixtures" / "dm"
_t = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731
FB_I = 'send 5 first contact messages on facebook dating "hi miss you look beautiful"'


@pytest.mark.parametrize("name,xy", [
    ("badoo_popup_credits.xml", (985, 1247)),     # real: Close, never Continue
    ("blk_boost_peak.xml", (540, 1800)),          # real: Not now
    ("blk_super_like_popup.xml", (540, 1550)),    # real: Send Like anyway (free)
    ("tinder_gold_guess_r49.xml", (540, 2100)),   # guess: No thanks
    ("pure_paywall_guess_r50.xml", (80, 150)),    # guess: Close
])
def test_paid_popup_close_targets(name, xy):
    t = _t(name)
    assert is_paid_popup(t)
    assert paid_close_target(t)[:2] == xy


@pytest.mark.parametrize("name", ["taimi_paywall.xml", "yubo_popup_infinity.xml"])
def test_paid_popup_without_close_uses_back(name):
    t = _t(name)
    assert is_paid_popup(t) and paid_close_target(t) is None
    a = ca.plan_next_action("fixed swipe 5 on bumble", t, [], agent_state={})
    assert a["action"] == "press_button" and a["button"] == "back"


def test_no_false_positives_on_real_screens():
    for f in sorted(FIX.glob("*.xml")):
        if any(k in f.name for k in ("popup_credits", "boost_peak", "super_like_popup",
                                     "paywall", "infinity", "gold", "outoflikes", "promo")):
            continue
        assert not is_paid_popup(f.read_text(encoding="utf-8", errors="ignore")), f.name
    assert not is_paid_popup(_t("yubo_blast_sheet_r45.xml"))  # Direct sheet has a text box


def test_guard_runs_for_every_fixed_planner_and_drops_pending_like():
    st = {"hily_run": {"likes": 2, "awaiting_like": True, "phase": "likes1"}}
    a = ca.plan_next_action("fixed hily likes 5", _t("badoo_popup_credits.xml")
                            .replace("com.badoo.mobile", "com.hily.app"), [], agent_state=st)
    assert a["planner"] == "paid_popup_guard" and a["action"] == "tap"
    assert st["hily_run"]["awaiting_like"] is False and st["hily_run"]["likes"] == 2
    for inst in ("fixed tinder swipe 5", "fixed app boo likes messages 0 likes 3",
                 FB_I, "fixed tagged swipe 5", "send 5 first contact messages on yubo"):
        a = ca.plan_next_action(inst, _t("blk_boost_peak.xml"), [], agent_state={})
        assert a["planner"] == "paid_popup_guard" and (a["x"], a["y"]) == (540, 1800)
    st = {}
    for _ in range(7):
        a = ca.plan_next_action("fixed swipe 5 on badoo", _t("taimi_paywall.xml"), [],
                                agent_state=st)
    assert a["action"] == "fail"


def test_fb_post_viewer_closes_then_dating_tab():
    """Real 24 Nov 10:55 (task_fd4408515608a893): Facebook resumed on a post."""
    st = {}
    a = fb(FB_I, _t("fb_post_viewer_r50.xml"), [], state=st, target=5)
    assert a["fastpath_step"] == "fb_dating_nav_close_post" and (a["x"], a["y"]) == (73, 133)
    a = fb(FB_I, _t("fb_home_feed_r50.xml"), [], state=st, target=5)
    assert a["fastpath_step"] == "fb_dating_nav_tab" and (a["x"], a["y"]) == (630, 2200)
    a = fb(FB_I, _t("fb_dating_profile_ellie.xml"), [], state=st, target=5)
    assert a["fastpath_step"] == "fb_dating_fc_tap_photo"


def test_fb_never_taps_post_photo_and_gives_up_cleanly():
    st = {}
    acts = [fb(FB_I, _t("fb_post_viewer_r50.xml"), [], state=st, target=5) for _ in range(8)]
    assert all(a["fastpath_step"].startswith("fb_dating_nav") for a in acts)
    assert acts[-1]["action"] == "fail"
    # the routed planner too (no LLM, no blind card tap)
    a = ca.plan_next_action(FB_I, _t("fb_home_feed_r50.xml"), [], package="com.facebook.katana",
                            agent_state={})
    assert (a.get("x"), a.get("y")) == (630, 2200)
