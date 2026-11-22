"""Lease writeback + Bumble deck/connections fixes from 22 Nov real-phone dry runs."""

from pathlib import Path

from backend import storage as storage_mod
from backend.bulk_bench_heuristics import (
    _chat_list_screen_verified,
    _deck_visible,
    deck_card_name,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.dm_heuristics import (
    bumble_collapsed_older_chats_center,
    bumble_deck_card_name,
    bumble_first_grid_tile_center,
    bumble_on_connections,
    bumble_on_people_deck,
    bumble_on_photo_grid,
)
from backend.storage import (
    DEFAULT_JOB_LEASE_S,
    acquire_job_lease,
    get_job,
    put_job,
    save_job_progress,
)
from backend.step_worker import process_job

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def setup_function(_fn=None):
    storage_mod._LOCAL_JOBS = {}  # type: ignore[attr-defined]


# --- Lease ---


def test_default_lease_ttl_covers_slow_step():
    assert DEFAULT_JOB_LEASE_S >= 120


def test_save_job_progress_does_not_write_stale_lease():
    put_job({"job_id": "jl1", "status": "running", "state": {"steps": 0}})
    assert acquire_job_lease("jl1", "worker-A", ttl_s=120, now=1000) is True
    live = get_job("jl1")
    assert live["lease_owner"] == "worker-A"
    assert int(live["lease_expires_at"]) == 1120
    # Stale in-memory job still carries an older/empty lease from step start
    stale = {
        "job_id": "jl1",
        "status": "running",
        "state": {"steps": 3},
        "result": "progress",
        "lease_owner": "worker-OLD",
        "lease_expires_at": 500,
    }
    assert save_job_progress(stale, owner="worker-A") is True
    after = get_job("jl1")
    assert after["state"]["steps"] == 3
    # Lease untouched by save_job_progress
    assert after["lease_owner"] == "worker-A"
    assert int(after["lease_expires_at"]) == 1120


def test_process_job_skip_logs_holder_not_skipper(caplog):
    import logging

    put_job({"job_id": "jl2", "status": "running", "kind": "agent", "state": {}})
    assert acquire_job_lease("jl2", "holder-X", ttl_s=120) is True
    with caplog.at_level(logging.INFO, logger="mobilerun.step"):
        process_job(
            {
                "job_id": "jl2",
                "status": "running",
                "kind": "agent",
                "device_id": "d",
                "instruction": "open settings",
                "state": {},
            },
            owner="skipper-Y",
        )
    blob = " ".join(r.message for r in caplog.records)
    assert "lease held by holder-X" in blob
    assert "skipper=skipper-Y" in blob or "skipper-Y" in blob


# --- Bumble deck / Edge panels ---


def test_edge_panels_not_people_deck():
    tree = _load("bumble_people_with_edge_panels.xml")
    assert not bumble_on_people_deck(tree)
    assert not _deck_visible("bumble", tree)


def test_real_card_deck_still_detected():
    deck = _load("bumble_deck.xml")
    assert bumble_on_people_deck(deck)
    assert bumble_deck_card_name(deck) == "Alex"
    assert deck_card_name("bumble", deck) == "Alex"


def test_photo_grid_is_not_deck_fails_cleanly():
    """Grid tiles open PhotoBrowser (SuperSwipe) — never tap; fail cleanly."""
    grid = _load("bumble_people_photo_grid.xml")
    assert bumble_on_photo_grid(grid)
    assert not bumble_on_people_deck(grid)
    tile = bumble_first_grid_tile_center(grid)
    assert tile == (270, 600)
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble like 3 profiles",
        grid,
        ["Opened Bumble — launch", "tap — Open swipe deck"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "fail"
    assert act.get("fastpath_step") == "bulk_bumble_grid_not_deck"
    assert "grid" in (act.get("reason") or "").lower()


# --- Connections / Older chats ---


def test_connections_not_vetoed_by_deck_and_expands_older():
    tree = _load("bumble_connections_older_collapsed.xml")
    assert bumble_on_connections(tree)
    assert _chat_list_screen_verified("bumble", tree)
    older = bumble_collapsed_older_chats_center(tree)
    assert older == (540, 1648)
    st: dict = {}
    act = plan_bulk_message(
        'reply "hey" to 2 existing chats on bumble',
        tree,
        ["Opened Bumble — launch", "Open chats/messages tab"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "tap"
    assert act.get("fastpath_step") == "bulk_expand_older_chats"
    assert (act["x"], act["y"]) == (540, 1648)


# --- Dry-run swipe: one verified card, log N once ---


def test_dry_run_swipe_logs_n_once_with_real_name():
    deck = _load("bumble_deck.xml")
    st: dict = {"bulk_swipe": {"done": 0, "target": 5}}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        deck,
        ["Opened Bumble — launch"],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "done"
    reason = (act.get("reason") or "").lower()
    assert "would like/pass 5 cards" in reason
    assert "deck verified on alex" in reason
    assert "profile_1" not in reason
    assert "profile_2" not in reason
    # Single completion — not 5 identical would-like waits
    assert act.get("bulk_swipe_done") == 5
    assert st["bulk_swipe"]["done"] == 5


def test_dry_run_refuses_profile_n_without_real_name():
    # Deck-ish ids but no Name, Age / main photo
    tree = """
    <hierarchy packages="com.bumble.app"><w id="active" p="com.bumble.app" f="1">
     <n i="com.bumble.app:id/profile_root_container" xy="540,1171"/>
     <n d="People" c="1" xy="540,2197"/>
    </w></hierarchy>
    """
    act = plan_bulk_swipe(
        "bumble auto-swipe 3 profiles",
        tree,
        ["Opened Bumble — launch"],
        state={},
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "fail"
    assert (
        "profile_n" in (act.get("reason") or "").lower()
        or "no real card" in (act.get("reason") or "").lower()
    )
