"""Run page Start / per-app Run → real agent jobs, one app at a time."""

from __future__ import annotations

import sys
import types
from typing import Any, Dict

import pytest

from backend import dating_run
from backend.bulk_bench_heuristics import parse_bulk_goal


@pytest.mark.parametrize(
    "pkg,count,app,kind,n",
    [
        ("co.hinge.app", 7, "hinge", "message_new", 7),
        ("com.hily.app", 9, "hily", "message_new", 5),
        ("com.hily.app", None, "hily", "message_new", 5),
        ("com.facebook.katana", None, "facebook", "message_new", 50),
        ("com.facebook.katana", 80, "facebook", "message_new", 50),
        ("com.affinityapps.blk", 30, "blk", "message_new", 30),
        ("co.yellw.yellowapp", 2, "yubo", "message_new", 2),
        ("com.bumble.app", 4, "bumble", "swipe", 4),
        ("com.badoo.mobile", 4, "badoo", "swipe", 4),
    ],
)
def test_instruction_parses_to_fixed_planner(pkg, count, app, kind, n):
    goal = parse_bulk_goal(dating_run.instruction_for(pkg, count))
    assert goal["app"] == app
    assert goal["kind"] == kind
    assert goal["count"] == n


def test_facebook_text_is_exact():
    goal = parse_bulk_goal(dating_run.instruction_for("com.facebook.katana", 3))
    assert goal["message"] == "hi miss you look beautiful"


def test_swipe_instruction_is_fixed_mode():
    assert "fixed" in dating_run.instruction_for("com.bumble.app", 3)


def test_unsupported_apps_skipped():
    ok, bad = dating_run.split_supported(
        ["com.whatsapp", "hinge", "co.hinge.app", "com.taggedapp", "ai.mobilerun.mockdating"]
    )
    assert ok == ["co.hinge.app"]
    assert "com.whatsapp" in bad and "ai.mobilerun.mockdating" in bad


def test_queue_runs_next_app_after_end():
    job = dating_run.build_job(
        device_id="d1", queue=["co.hinge.app", "com.hily.app"], count=3, dry_run=True
    )
    assert job["kind"] == "agent" and job["dating_run"] is True
    assert job["run_id"] == job["job_id"]
    assert dating_run.next_job_after(job) is None  # still running
    job["status"] = "failed"  # e.g. no_progress_timeout still moves on
    nxt = dating_run.next_job_after(job)
    assert nxt["dating_app"] == "com.hily.app"
    assert nxt["run_id"] == job["job_id"]
    assert nxt["dry_run"] is True
    assert nxt["run_queue"] == []
    nxt["status"] = "completed"
    assert dating_run.next_job_after(nxt) is None
    job["status"] = "stopped"
    assert dating_run.next_job_after(job) is None


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main as main_mod

    jobs: Dict[str, Dict[str, Any]] = {}
    storage = types.ModuleType("storage")
    storage.put_job = lambda j: jobs.__setitem__(j["job_id"], dict(j))
    storage.get_job = lambda jid: jobs.get(jid)
    storage.list_recent_jobs = lambda limit=40: sorted(
        jobs.values(), key=lambda j: -int(j.get("created_at") or 0)
    )[:limit]
    monkeypatch.setitem(sys.modules, "storage", storage)
    monkeypatch.setitem(sys.modules, "backend.storage", storage)
    push = types.ModuleType("device_push")
    push.device_is_reachable = lambda d: d == "phone1"
    monkeypatch.setitem(sys.modules, "device_push", push)
    monkeypatch.setitem(sys.modules, "backend.device_push", push)
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    kicked = []
    monkeypatch.setattr(main_mod, "_kick_job", lambda jid: kicked.append(jid))
    monkeypatch.setattr(main_mod, "_save_dating_runtime", lambda *a, **k: None)
    monkeypatch.setattr(main_mod, "_load_dating_runtime", lambda *a, **k: None)
    main_mod.dating_mode_state["running"] = False
    main_mod.dating_mode_state.pop("job_id", None)
    c = TestClient(main_mod.app)
    c.jobs = jobs
    c.kicked = kicked
    return c


def test_start_single_app_creates_agent_job(client):
    r = client.post(
        "/api/dating/start",
        json={"device_id": "phone1", "dry_run": True, "apps": ["com.hily.app"], "count": 9},
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["kind"] == "agent"
    assert job["instruction"] == "send 5 first contact messages on hily"
    assert job["dry_run"] is True
    assert client.kicked == [job["job_id"]]
    st = client.get("/api/dating/status").json()
    assert st["job_id"] == job["job_id"]


def test_start_all_runs_supported_apps_in_order(client):
    r = client.post(
        "/api/dating/start",
        json={
            "device_id": "phone1",
            "apps": ["com.whatsapp", "co.hinge.app", "com.bumble.app"],
            "count": 2,
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["queue"] == ["co.hinge.app", "com.bumble.app"]
    assert d["skipped"] == ["com.whatsapp"]
    assert d["job"]["run_queue"] == ["com.bumble.app"]


def test_start_offline_phone_is_clear_error(client):
    r = client.post("/api/dating/start", json={"device_id": "gone", "apps": ["hinge"]})
    assert r.status_code == 400
    assert "offline" in r.json()["detail"].lower()


def test_start_only_unsupported_apps_400(client):
    r = client.post(
        "/api/dating/start", json={"device_id": "phone1", "apps": ["com.whatsapp"]}
    )
    assert r.status_code == 400


def test_legacy_start_without_apps_unchanged(client):
    r = client.post("/api/dating/start", json={"device_id": "phone1", "dry_run": True})
    assert r.status_code == 200
    assert r.json()["job"]["kind"] == "dating"


def test_step_worker_chains_next_app(monkeypatch):
    from backend import step_worker

    put = []
    monkeypatch.setattr(step_worker, "put_job", lambda j: put.append(j))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    job = dating_run.build_job(
        device_id="d1", queue=["co.hinge.app", "com.badoo.mobile"], count=1, dry_run=True
    )
    job["status"] = "completed"
    step_worker._start_next_run_app(job)
    assert len(put) == 1 and put[0]["dating_app"] == "com.badoo.mobile"


def test_hily_likes_after_five_messages():
    ok, _ = dating_run.split_supported(["com.hily.app", "co.hinge.app"])
    assert ok == ["com.hily.app", "com.hily.app#like", "co.hinge.app"]
    job = dating_run.build_job(device_id="d1", queue=ok, count=12, dry_run=False)
    assert job["instruction"] == "send 5 first contact messages on hily"
    job["status"] = "completed"  # 5/5 sent (or allowance gone → failed, same)
    like = dating_run.next_job_after(job)
    assert like["run_step"] == "like"
    assert like["dating_app"] == "com.hily.app"
    goal = parse_bulk_goal(like["instruction"])
    assert goal == {"kind": "swipe", "count": 12, "message": None, "app": "hily"}
    assert like["run_queue"] == ["co.hinge.app"]
    like["status"] = "failed"
    assert dating_run.next_job_after(like)["dating_app"] == "co.hinge.app"


def test_hily_like_step_never_messages_or_crush():
    from backend.bulk_bench_heuristics import plan_bulk_swipe

    tree = (
        '<hierarchy><w id="active" p="com.hily.app">'
        '<n i="com.hily.app:id/userNameAgeField" t="Amy, 24" cls="TextView" xy="300,1500" b="0,0,1,1"/>'
        '<n i="com.hily.app:id/ActionButton_SKIP" d="Pass" cls="ImageView" c="1" xy="330,1959" b="0,0,1,1"/>'
        '<n i="com.hily.app:id/ActionButton_CRUSH" d="Crush" cls="ImageView" c="1" xy="540,1959" b="0,0,1,1"/>'
        '<n i="com.hily.app:id/ActionButton_LIKE" d="Like" cls="ImageView" c="1" xy="750,1959" b="0,0,1,1"/>'
        "</w></hierarchy>"
    )
    st: Dict[str, Any] = {}
    seen = []
    for _ in range(4):
        act = plan_bulk_swipe(
            "swipe 3 on hily", tree, [], state=st, package="com.hily.app"
        )
        if not act:
            break
        seen.append(act)
        assert act.get("action") not in ("type", "input_text")
        if act.get("action") == "tap":
            assert (act["x"], act["y"]) != (540, 1959)  # never Crush
    taps = [a for a in seen if a.get("action") == "tap"]
    assert any((a["x"], a["y"]) == (750, 1959) for a in taps)
