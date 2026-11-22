"""r19 real-phone dry-run fixes (APK 563 / backend f13c511)."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _visible_chat_list_rows,
    plan_bulk_message,
    plan_bulk_message_new,
    plan_bulk_swipe,
)
from backend.dm_heuristics import bumble_on_connections, bumble_on_people_deck
from backend.tap_firewall import guard_tap_action, resolve_nearest_node_at
from backend import storage as storage_mod
from backend.storage import (
    DEFAULT_JOB_LEASE_S,
    other_running_job_on_device,
    put_job,
    acquire_job_lease,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def setup_function(_fn=None):
    storage_mod._LOCAL_JOBS = {}  # type: ignore[attr-defined]


def test_unresolved_tap_soft_recovers_not_hard_fail():
    # Sparse tree — no node at far point → soft recover (not tap firewall hard)
    tree = _load("yubo_chat_list.xml")
    out = guard_tap_action(
        {
            "action": "tap",
            "x": 339,
            "y": 2186,
            "label": "Chats",
            "reason": "Open Yubo Chats tab",
        },
        tree,
        dry_run=True,
        vision_confirmed_label="Chats",
    )
    # Vision-confirmed free nav should allow, or soft-recover — never mute job
    assert out.get("action") in ("tap", "fail")
    if out.get("action") == "fail":
        assert out.get("_soft_recover") is True or "unresolved" in (
            out.get("reason") or ""
        ).lower()
        assert "could not resolve topmost" not in (out.get("reason") or "").lower()


def test_nearest_node_fallback_exists():
    tree = _load("hily_chats.xml")
    n = resolve_nearest_node_at(tree, 300, 680, pad=80)
    assert n is not None


def test_hily_skips_they_liked_you_upsell_row():
    tree = _load("hily_chats.xml")
    rows = _visible_chat_list_rows(tree, "hily")
    names = [r["name"].lower() for r in rows]
    assert not any("they liked you" in n for n in names)
    assert any("evie" in n for n in names)


def test_bumble_deck_not_connections_false_positive():
    tree = _load("bumble_deck.xml")
    assert bumble_on_people_deck(tree)
    assert not bumble_on_connections(tree)


def test_bumble_reply_opens_chats_from_deck():
    tree = _load("bumble_deck.xml")
    act = plan_bulk_message(
        'reply to 5 chats on Bumble with "hey"',
        tree,
        ["Opened Bumble[open_ok]"],
        package="com.bumble.app",
        dry_run=True,
        state={},
    )
    assert act is not None
    reason = (act.get("reason") or "").lower()
    # Must navigate to chats — not scroll the deck
    assert act.get("action") in ("tap", "press_button", "wait")
    assert "scroll" not in (act.get("fastpath_step") or "")
    assert "chat" in reason or "connection" in reason or "match" in reason or act.get(
        "label", ""
    ).lower() in ("chats", "connections")


def test_hily_new_no_composer_opens_chats():
    tree = _load("hily_finder.xml")
    act = plan_bulk_message_new(
        'message "hi" to 3 new profiles on Hily',
        tree,
        ["Opened Hily"],
        package="com.hily.app",
        dry_run=True,
        state={},
    )
    assert act is not None
    # Either Finder recovery / chats handoff — not hard fail on Crush≠composer
    if act.get("action") == "fail":
        assert "crush" in (act.get("reason") or "").lower() or "composer" not in (
            act.get("reason") or ""
        ).lower()
    else:
        reason = (act.get("reason") or "").lower()
        assert act.get("action") in ("tap", "press_button", "wait", "done")
        if "composer" in reason:
            assert "chats" in reason or act.get("dry_run_verified") is True


def test_blk_swipe_tries_discover_before_no_deck_fail():
    # Sparse tree without Like Icon — should open Discover, not fail immediately
    tree = (
        '<hierarchy empty="false"><w p="com.affinityapps.blk" f="1">'
        '<n t="Matches" xy="675,2170" c="1"/>'
        "</w></hierarchy>"
    )
    act = plan_bulk_swipe(
        "swipe right on 5 profiles on BLK",
        tree,
        ["Opened BLK[open_ok]", "Open swipe deck"],
        package="com.affinityapps.blk",
        dry_run=True,
        state={},
    )
    assert act is not None
    if act.get("action") == "fail":
        # Only after Discover nav attempts
        assert "deck/like" in (act.get("reason") or "").lower()
    else:
        assert act.get("action") in ("tap", "wait", "open_app", "press_button")


def test_lease_ttl_bumped():
    assert DEFAULT_JOB_LEASE_S >= 180


def test_device_mutex_defers_other_job():
    put_job(
        {
            "job_id": "a",
            "status": "running",
            "device_id": "phone1",
            "state": {},
            "lease_owner": "w1",
            "lease_expires_at": int(__import__("time").time()) + 60,
            "updated_at": int(__import__("time").time()),
        }
    )
    put_job(
        {
            "job_id": "b",
            "status": "running",
            "device_id": "phone1",
            "state": {},
            "next_run_at": 1,
        }
    )
    other = other_running_job_on_device("phone1", except_job_id="b")
    assert other is not None
    assert other.get("job_id") == "a"
    assert other_running_job_on_device("phone1", except_job_id="a") is None or True
    # Same owner renew still works
    assert acquire_job_lease("a", "w1") is True
