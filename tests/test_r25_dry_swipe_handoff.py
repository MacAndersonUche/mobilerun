"""r25: dry swipe identify-as-success, 20s handoff, live_test caps."""

from pathlib import Path

from backend.bulk_bench_heuristics import plan_bulk_swipe
from backend.cloud_agent import (
    BULK_DRY_RUN_LLM_HINT,
    BULK_STALL_HANDOFF_S,
    LIVE_TEST_DEFAULT_MAX_N,
    _dry_run_done_is_verified,
    _salvage_dry_swipe_done,
    _visible_dry_swipe_card_name,
    apply_dry_run_send_guard,
    apply_live_test_guard,
    plan_next_action,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_bulk_stall_handoff_seconds_is_20():
    assert int(BULK_STALL_HANDOFF_S) == 20


def test_dry_hint_says_identify_name_is_success():
    low = BULK_DRY_RUN_LLM_HINT.lower()
    assert "identified card" in low or "identify" in low
    assert "do not swipe" in low or "don't swipe" in low or "no swipe" in low
    assert "dry_run_verified" in low


def test_dry_swipe_identifies_name_without_vscroll():
    """r25: real name → done verified immediately (no intermediate scroll)."""
    tree = _load("blk_name_age_card.xml")
    st: dict = {"bulk_swipe": {"done": 0, "target": 5}}
    act = plan_bulk_swipe(
        "blk auto-swipe 5 profiles",
        tree,
        ["Opened BLK — launch"],
        package="com.affinityapps.blk",
        dry_run=True,
        state=st,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert "aaliyah" in (act.get("reason") or "").lower()
    assert act.get("_dry_run_vertical_scroll") is not True


def test_dry_run_guard_salvages_swipe_when_name_visible():
    tree = _load("blk_name_age_card.xml")
    st = {"bulk_swipe": {"done": 0, "target": 1, "last_name": "Aaliyah"}}
    kind, reason, action = apply_dry_run_send_guard(
        dry_run=True,
        action={
            "action": "swipe",
            "x1": 800,
            "y1": 1000,
            "x2": 100,
            "y2": 1000,
            "reason": "pass card",
        },
        kind="swipe",
        reason="pass card",
    )
    assert kind == "done"
    assert action.get("dry_run_verified") is False  # guard alone still unverified
    salvaged = _salvage_dry_swipe_done(
        instruction="blk auto-swipe 5 profiles",
        ui_tree=tree,
        state=st,
        action=action,
        reason=reason,
    )
    assert salvaged is not None
    assert salvaged.get("dry_run_verified") is True
    assert "aaliyah" in (salvaged.get("reason") or "").lower()
    assert _dry_run_done_is_verified(salvaged, salvaged["reason"], st)


def test_visible_name_from_tree():
    tree = _load("blk_name_age_card.xml")
    name = _visible_dry_swipe_card_name("blk auto-swipe 5 profiles", tree, {})
    assert name and name.lower().startswith("aaliyah")


def test_timed_handoff_after_20s(monkeypatch):
    """No verified progress for 20s → LLM handoff even at stall_n < 2."""
    tree = (
        '<hierarchy packages="com.bumble.app">'
        '<w p="com.bumble.app" f="1">'
        '<n t="People" xy="540,400"/>'
        '<n t="Filters" xy="900,200"/>'
        "</w></hierarchy>"
    )
    now = 1_700_000_000.0
    monkeypatch.setattr("backend.cloud_agent.time.time", lambda: now)
    st: dict = {
        "bulk_swipe": {"done": 0, "target": 5, "done_names": []},
        "bulk_stall_n": 0,
        "bulk_last_progress_at": now - 25,  # 25s ago
        "_bulk_progress_sig": ("bulk_swipe", 0, (), False, "", False),
    }
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    act = plan_next_action(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble — launch"],
        dry_run=True,
        agent_state=st,
        package="com.bumble.app",
    )
    assert act is not None
    assert st.get("_bulk_llm_handoff") or act.get("planner") == "bulk_llm_handoff"
    reason = (act.get("reason") or "").lower()
    assert "hand off" in reason or "timed" in reason or act.get("_force_vision")


def test_live_test_blocks_paid_allows_like_cap():
    assert LIVE_TEST_DEFAULT_MAX_N >= 1
    st: dict = {"live_likes_done": 0, "live_likes_issued": 0, "live_test_max_n": 2}
    kind, reason, action = apply_live_test_guard(
        live_test=True,
        action={"action": "tap", "x": 100, "y": 200, "reason": "Super Like"},
        kind="tap",
        reason="Super Like",
        state=st,
        max_n=2,
    )
    assert kind == "wait"
    assert "paid" in reason.lower() or "super" in reason.lower()

    kind2, reason2, action2 = apply_live_test_guard(
        live_test=True,
        action={
            "action": "tap",
            "x": 800,
            "y": 1800,
            "reason": "Like profile",
            "label": "Like",
        },
        kind="tap",
        reason="Like profile",
        state=st,
        max_n=2,
    )
    assert kind2 == "tap"
    # r28: issued increments immediately; done waits for card-name verify
    assert st.get("live_likes_issued") == 1
    assert st.get("live_likes_done", 0) == 0

    st["live_likes_issued"] = 2
    kind3, reason3, action3 = apply_live_test_guard(
        live_test=True,
        action={
            "action": "tap",
            "x": 800,
            "y": 1800,
            "reason": "Like profile",
            "label": "Like",
        },
        kind="tap",
        reason="Like profile",
        state=st,
        max_n=2,
    )
    assert kind3 == "done"
    assert "cap" in reason3.lower()
    assert action3.get("live_test_verified") is True


def test_plan_prefers_identify_over_llm_when_name_visible(monkeypatch):
    tree = _load("blk_name_age_card.xml")
    st: dict = {
        "bulk_swipe": {"done": 0, "target": 5},
        "_bulk_llm_handoff": True,  # even with handoff set
        "bulk_stall_n": 5,
    }
    act = plan_next_action(
        "blk auto-swipe 5 profiles",
        tree,
        ["Opened BLK"],
        image_b64="aGVsbG8=",
        dry_run=True,
        agent_state=st,
        package="com.affinityapps.blk",
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert "aaliyah" in (act.get("reason") or "").lower()
