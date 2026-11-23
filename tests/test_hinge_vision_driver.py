"""Hinge vision-first driver, parked flag, Taimi removal, live-test mode.

No network, no device — pure planner/vision-parse tests on fake trees.
"""

from __future__ import annotations

from backend.bulk_bench_heuristics import (
    PARKED_APPS,
    UNSUPPORTED_APPS,
    _real_like_action,
    parse_bulk_goal,
    plan_bulk_swipe,
)
from backend.dating_deck import plan_free_like
from backend.dm_heuristics import DM_APP_PROFILES, hinge_like_sheet_action
from backend.hinge_vision import (
    HINGE_VISION_MAX_ASKS,
    is_plausible_profile_name,
    parse_vision_heart_reply,
    validate_heart_xy,
)
from mobilerun.dating.config import DatingModeConfig


# ---------------------------------------------------------------- vision parse
def test_parse_valid_heart_reply():
    parsed, reason = parse_vision_heart_reply("NAME: Sarah\nHEART: 937 2000")
    assert reason == "ok"
    assert parsed == {"name": "Sarah", "x": 937, "y": 2000}


def test_parse_none_reply():
    parsed, _ = parse_vision_heart_reply("NONE\nNONE")
    assert parsed is None


def test_parse_rejects_folder_name():
    # r30: the agent once took a launcher folder called "Jobs" for a name.
    parsed, reason = parse_vision_heart_reply("NAME: Jobs\nHEART: 937 2000")
    assert parsed is None
    assert "not a plausible profile name" in reason


def test_parse_rejects_rose_region():
    parsed, reason = parse_vision_heart_reply("NAME: Sarah\nHEART: 200 1280")
    assert parsed is None
    assert "Rose" in reason


def test_parse_rejects_nav_bar():
    parsed, reason = parse_vision_heart_reply("NAME: Sarah\nHEART: 540 2300")
    assert parsed is None
    assert "action row" in reason


def test_parse_rejects_left_side_skip_area():
    parsed, _ = parse_vision_heart_reply("NAME: Sarah\nHEART: 115 2000")
    assert parsed is None


def test_parse_rejects_missing_heart():
    parsed, _ = parse_vision_heart_reply("NAME: Sarah\nHEART: NONE")
    assert parsed is None


def test_parse_rejects_empty():
    parsed, _ = parse_vision_heart_reply("")
    assert parsed is None


# ------------------------------------------------------------ heart validation
def test_validate_heart_xy():
    assert validate_heart_xy(937, 2000)[0] is True
    assert validate_heart_xy(200, 1400)[0] is False  # old swipe area
    assert validate_heart_xy(200, 1280)[0] is False  # Rose bounds
    assert validate_heart_xy(540, 2300)[0] is False  # nav bar
    assert validate_heart_xy(1080, 2000)[0] is False  # off-screen x


def test_name_plausibility():
    assert is_plausible_profile_name("Sarah") is True
    assert is_plausible_profile_name("Sarah, 26") is True
    assert is_plausible_profile_name("Jobs") is False
    assert is_plausible_profile_name("Social") is False
    assert is_plausible_profile_name("") is False
    assert is_plausible_profile_name(None) is False


# ---------------------------------------------------------------------- config
def test_config_hinge_parked_taimi_disabled():
    assert "hinge" in PARKED_APPS
    assert "taimi" in UNSUPPORTED_APPS
    cfg = DatingModeConfig()
    names = [a.name for a in cfg.get_enabled_apps()]
    assert "Hinge" not in names
    assert "Taimi" not in names
    assert "Hily" in names
    assert "Bumble" in names
    assert [a.name for a in cfg.get_parked_apps()] == ["Hinge"]


# ------------------------------------------------------------------ goal parse
def test_parse_live_test_goal():
    goal = parse_bulk_goal("hinge live test one like")
    assert goal is not None
    assert goal["kind"] == "swipe"
    assert goal["count"] == 1
    assert goal["app"] == "hinge"
    assert goal["live_test"] is True


def test_parse_swipe_goal_marks_live_test():
    goal = parse_bulk_goal("like 1 profile on hinge live test")
    assert goal is not None
    assert goal["live_test"] is True
    goal2 = parse_bulk_goal("swipe 5 profiles on hinge")
    assert goal2 is not None
    assert goal2.get("live_test") is False


# ----------------------------------------------------------------- parked gate
def test_plan_bulk_swipe_hinge_parked_fails():
    act = plan_bulk_swipe(
        "swipe 5 profiles on hinge", "", [], state={}, package="co.hinge.app"
    )
    assert act is not None
    assert act["action"] == "fail"
    assert "parked" in act["reason"].lower()
    assert act.get("stopped_reason") == "hinge_parked"


def test_plan_bulk_swipe_taimi_unsupported_fails():
    act = plan_bulk_swipe(
        "swipe 5 profiles on taimi", "", [], state={}, package="com.takimi.android"
    )
    assert act is not None
    assert act["action"] == "fail"
    assert act.get("stopped_reason") == "unsupported_app"


# ------------------------------------------------------- vision driver (live)
def _hinge_discover(name="Sarah", age="26"):
    return (
        '<h pkg="co.hinge.app">'
        f'<n t="{name}, {age}" xy="540,900"/>'
        '<n t="Most compatible" xy="540,1000"/>'
        '<n t="Send a message" xy="540,1500"/>'
        '<n t="Discover" xy="110,2195"/>'
        "</h>"
    )


def test_hinge_vision_driver_asks_then_taps():
    state: dict = {}
    hist = ["open hinge discover"]
    act = plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    assert act is not None
    assert act["action"] == "wait"
    assert act.get("_hinge_vision_heart_ask") is True
    assert act.get("needs_vision") is True

    # Screenshot grounded the heart — planner taps it, exactly once.
    state["_hinge_vision_heart"] = {"name": "Sarah", "x": 937, "y": 2000}
    act = plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    assert act is not None
    assert act["action"] == "tap"
    assert int(act["x"]) == 937 and int(act["y"]) == 2000
    assert act.get("_hinge_vision_like") is True
    assert act.get("_free_like") is True
    assert state["bulk_swipe"]["_hinge_vision_like_name"] == "Sarah"
    assert state["bulk_swipe"]["awaiting_verify"] is True
    assert "_hinge_vision_heart" not in state  # consumed exactly once


def test_hinge_vision_like_counts_only_on_card_change():
    state: dict = {}
    hist = ["open hinge discover"]
    plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    state["_hinge_vision_heart"] = {"name": "Sarah", "x": 937, "y": 2000}
    plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    # New card loaded — like counts, live test ends with a report.
    act = plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Emma", "27"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    assert act is not None
    assert act["action"] == "done"
    report = act.get("_hinge_live_test_report") or {}
    assert report.get("verified") is True
    assert report.get("liked") == "Sarah"
    assert report.get("rose_avoided") is True


def test_hinge_vision_like_not_counted_when_same_card():
    state: dict = {}
    hist = ["open hinge discover"]
    plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    state["_hinge_vision_heart"] = {"name": "Sarah", "x": 937, "y": 2000}
    plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    # Same card still on screen — must NOT count, must keep waiting.
    act = plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    assert act is not None
    assert act["action"] == "wait"
    assert int(state["bulk_swipe"].get("done") or 0) == 0


def test_hinge_vision_asks_bounded():
    state: dict = {"bulk_swipe": {"_hinge_vision_heart_asks": HINGE_VISION_MAX_ASKS}}
    hist = ["open hinge discover"]
    act = plan_bulk_swipe(
        "hinge live test one like",
        _hinge_discover("Sarah"),
        hist,
        state=state,
        package="co.hinge.app",
        dry_run=False,
    )
    assert act is not None
    assert act["action"] == "fail"
    assert "never tap blind" in act["reason"].lower()


# ------------------------------------------------------- no swipe fallback
def test_real_like_action_hinge_never_swipes():
    act = _real_like_action("hinge", tree="", planner="test")
    assert act is None  # fail closed — no blind swipe, no guess


def test_plan_free_like_hinge_no_swipe_fallback():
    assert plan_free_like("hinge", "", planner="test") is None
    tree = (
        '<h pkg="co.hinge.app">'
        '<n t="Sarah, 26" xy="540,900"/>'
        '<n t="Like" xy="800,2000" clickable="true"/>'
        "</h>"
    )
    act = plan_free_like("hinge", tree, planner="test")
    assert act is not None
    assert act["action"] == "tap"  # real a11y heart still works


# ------------------------------------------------------- like sheet / Rose guard
def _hinge_sheet(send_like_xy="686,1277"):
    return (
        '<h pkg="co.hinge.app">'
        '<n t="Add a comment" xy="540,1100"/>'
        '<n t="Rose" xy="200,1280"/>'
        f'<n t="Send Like" xy="{send_like_xy}"/>'
        "</h>"
    )


def test_sheet_send_like_ok_outside_rose():
    act = hinge_like_sheet_action(_hinge_sheet(), planner="test")
    assert act is not None
    assert act["action"] == "tap"
    assert int(act["x"]) == 686 and int(act["y"]) == 1277


def test_sheet_send_like_inside_rose_is_refused():
    # A "Send Like" node resolving inside the Rose bounds must not be
    # tapped — the map fallback (outside Rose) is used instead.
    act = hinge_like_sheet_action(_hinge_sheet("200,1280"), planner="test")
    assert act is not None
    assert act["action"] == "tap"
    assert not (95 <= int(act["x"]) <= 355 and 1225 <= int(act["y"]) <= 1330)


def test_sheet_send_like_none_when_everything_is_rose():
    prof = DM_APP_PROFILES["hinge"]
    old = prof.get("send_like_xy")
    prof["send_like_xy"] = (200, 1280)
    try:
        act = hinge_like_sheet_action(_hinge_sheet("200,1280"), planner="test")
        assert act is None
    finally:
        prof["send_like_xy"] = old
