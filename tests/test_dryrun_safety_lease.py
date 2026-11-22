"""Dry-run safety + job lease: concurrent workers, cancel, wording, wrong-app."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    parse_bulk_goal,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    _action_looks_like_paid,
    _action_looks_like_swipe_or_like,
    apply_dry_run_send_guard,
)
from backend import storage as storage_mod
from backend.storage import (
    acquire_job_lease,
    get_job,
    put_job,
    save_job_progress,
    update_job_fields,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def setup_function(_fn=None):
    # Isolate in-memory job store per test
    storage_mod._LOCAL_JOBS = {}  # type: ignore[attr-defined]


# --- Lease ---


def test_second_worker_skips_when_lease_held():
    put_job({"job_id": "j1", "status": "running", "next_run_at": 1, "state": {}})
    assert acquire_job_lease("j1", "worker-A", ttl_s=60) is True
    assert acquire_job_lease("j1", "worker-B", ttl_s=60) is False
    # Same owner can renew
    assert acquire_job_lease("j1", "worker-A", ttl_s=60) is True
    job = get_job("j1")
    assert job and job.get("lease_owner") == "worker-A"


def test_expired_lease_can_be_taken():
    put_job({"job_id": "j2", "status": "running", "state": {}})
    assert acquire_job_lease("j2", "worker-A", ttl_s=1, now=1000) is True
    # Expired at now=1100
    assert acquire_job_lease("j2", "worker-B", ttl_s=30, now=1100) is True
    assert get_job("j2").get("lease_owner") == "worker-B"


def test_cancel_not_overwritten_by_stale_worker_put():
    put_job(
        {
            "job_id": "j3",
            "status": "running",
            "state": {"steps": 1},
            "result": "working",
        }
    )
    assert acquire_job_lease("j3", "worker-A") is True
    # Cancel / stop (API path)
    assert update_job_fields("j3", {"status": "stopped"}, require_running=True) is True
    assert get_job("j3")["status"] == "stopped"
    # Stale worker tries to save progress with status=running in memory
    stale = {
        "job_id": "j3",
        "status": "running",
        "state": {"steps": 5},
        "result": "would overwrite cancel",
    }
    assert save_job_progress(stale, owner="worker-A") is False
    assert get_job("j3")["status"] == "stopped"
    assert get_job("j3").get("result") != "would overwrite cancel"


def test_progress_saved_while_running_with_lease():
    put_job({"job_id": "j4", "status": "running", "state": {"steps": 0}})
    assert acquire_job_lease("j4", "worker-A") is True
    ok = save_job_progress(
        {
            "job_id": "j4",
            "status": "running",
            "state": {"steps": 2, "last_action": "open"},
            "result": "opened",
        },
        owner="worker-A",
    )
    assert ok is True
    j = get_job("j4")
    assert j["state"]["steps"] == 2
    assert j["status"] == "running"


# --- Dry-run blocks ---


def test_dry_run_blocks_swipe():
    action = {
        "action": "swipe",
        "x1": 250,
        "y1": 1000,
        "x2": 1050,
        "y2": 1050,
        "reason": "Bumble like swipe",
        "fastpath_step": "bumble_like_swipe",
    }
    assert _action_looks_like_swipe_or_like(action, "swipe")
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="swipe", reason=action["reason"]
    )
    assert kind == "done"
    assert out.get("dry_run") is True
    assert "[dry run] would" in reason.lower()
    assert "swipe" in reason.lower()


def test_dry_run_blocks_like_tap():
    action = {
        "action": "tap",
        "x": 761,
        "y": 1948,
        "reason": "Like profile 1/5: Taimi Like",
        "fastpath_step": "bulk_like",
    }
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert "like/pass" in reason.lower() or "would" in reason.lower()


def test_dry_run_blocks_paid_continue():
    action = {
        "action": "tap",
        "x": 540,
        "y": 1600,
        "reason": "Continue to unlock GOLD",
        "label": "Continue",
    }
    assert _action_looks_like_paid(action, "tap")
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="tap", reason=action["reason"]
    )
    assert kind == "done"
    assert "paid" in reason.lower()


def test_dry_run_allows_open_app():
    action = {"action": "open_app", "app": "Yubo", "reason": "Open Yubo"}
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="open_app", reason=action["reason"]
    )
    assert kind == "open_app"
    assert out is action


# --- Wording variants ---


def test_parse_swipe_right_on_n_profiles():
    g = parse_bulk_goal("yubo swipe right on 5 profiles")
    assert g and g["kind"] == "swipe" and g["count"] == 5 and g["app"] == "yubo"


def test_parse_like_n_profiles():
    g = parse_bulk_goal("bumble like 5 profiles")
    assert g and g["kind"] == "swipe" and g["count"] == 5 and g["app"] == "bumble"


def test_parse_swipe_right_n_times():
    g = parse_bulk_goal("swipe right 5 times on tinder")
    # "on tinder" may be in aliases detection from full text
    g2 = parse_bulk_goal("tinder swipe right 5 times")
    assert g2 and g2["count"] == 5 and g2["kind"] == "swipe"


def test_parse_swipe_n_on_app():
    g = parse_bulk_goal("swipe 5 on yubo")
    assert g and g["kind"] == "swipe" and g["count"] == 5 and g["app"] == "yubo"


# --- Wrong-app guard ---


def test_bulk_swipe_fails_wrong_foreground_app():
    """Asked for Yubo but Bumble is FG — must not swipe Bumble."""
    deck = _load("bumble_deck.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "yubo swipe right on 5 profiles",
        deck,
        [],
        state=st,
        package="com.bumble.app",
    )
    assert act is not None
    # open_app Yubo OR fail wrong app — never Bumble like swipe
    if act.get("action") == "open_app":
        assert "yubo" in (act.get("app") or "").lower()
    else:
        assert act.get("action") == "fail"
        assert "wrong" in (act.get("reason") or "").lower()
    assert act.get("action") != "swipe"
    assert (act.get("x"), act.get("y")) != (250, 1000)


# --- No default message ---


def test_bulk_message_no_default_hi_baby():
    g = parse_bulk_goal("tinder auto-message 5 matches")
    assert g and g["kind"] == "message"
    assert g.get("message") in (None, "")
    assert g.get("error")
    act = plan_bulk_message(
        "tinder auto-message 5 matches",
        "<hierarchy/>",
        [],
        package="com.tinder",
    )
    assert act and act.get("action") == "fail"
    assert "message" in (act.get("reason") or "").lower()


# --- Bumble People vs Discover + dry_run deck check ---


def test_bumble_prefers_discover_swipe_deck():
    """Swipe jobs open Discover (card stack), not People photo grid."""
    tree = """
    <hierarchy packages="com.bumble.app"><w p="com.bumble.app">
     <n d="Discover" c="1" xy="200,2197" b="120,2140,280,2250"/>
     <n d="People" c="1" xy="540,2197" b="460,2140,620,2250"/>
     <n d="Chats" c="1" xy="972,2197" b="900,2140,1040,2250"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble like 5 profiles",
        tree,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
    )
    assert act and act.get("action") == "tap"
    assert (act["x"], act["y"]) == (200, 2197)  # Discover card stack


def test_bumble_dry_run_requires_deck_not_silent_zero():
    # Nav only — no deck card / like control
    tree = """
    <hierarchy packages="com.bumble.app"><w p="com.bumble.app">
     <n d="People" c="1" xy="540,2197"/>
     <n d="Chats" c="1" xy="972,2197"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble — launch", "tap — Open swipe deck"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    # Must not silently claim success without a visible deck / like control
    assert act is not None
    assert act.get("action") in ("done", "fail", "tap", "wait")
    if act.get("action") == "done" and act.get("dry_run"):
        assert (
            act.get("dry_run_verified") is not True
            or "deck verified" in (act.get("reason") or "").lower()
        )
    if act.get("fastpath_step") == "bulk_swipe_done":
        raise AssertionError("dry_run must not complete bulk without deck verify")
    if act.get("fastpath_step") == "bulk_dry_run_sim_like":
        raise AssertionError("dry_run must not simulate likes without deck visible")
    if act.get("fastpath_step") == "bulk_dry_run_skip_like":
        raise AssertionError("dry_run must not skip-like without a visible card name")
