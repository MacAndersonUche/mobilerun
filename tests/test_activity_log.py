"""Unit tests for Dating/Social live activity logging."""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest


def test_append_step_mutates_state_and_caps():
    from backend.activity_log import append_step

    state: Dict[str, Any] = {"steps": 0, "steps_detail": []}
    for i in range(3):
        state["steps"] = i + 1
        e = append_step(
            state,
            action=f"act_{i}",
            reason=f"reason_{i}",
            package="ai.mobilerun.mockdating",
            dry_run=True,
        )
        assert e["n"] == i + 1
        assert e["dry_run"] is True
        assert e["ts"] >= int(time.time()) - 5
    assert len(state["steps_detail"]) == 3
    assert state["last_action"] == "act_2"
    assert state["last_package"] == "ai.mobilerun.mockdating"

    # Cap at 60
    state["steps_detail"] = [{"n": i} for i in range(60)]
    state["steps"] = 61
    append_step(state, action="overflow", reason="x")
    assert len(state["steps_detail"]) == 60
    assert state["steps_detail"][-1]["action"] == "overflow"


def test_activity_payload_from_job_empty():
    from backend.activity_log import activity_payload_from_job

    p = activity_payload_from_job(None)
    assert p["status"] == "idle"
    assert p["steps"] == []
    assert p["job_id"] is None


def test_activity_payload_from_job_with_steps(monkeypatch):
    from backend import activity_log

    monkeypatch.setattr(activity_log, "steps_with_urls", lambda steps: list(steps))
    job = {
        "job_id": "dating_abc",
        "kind": "dating",
        "status": "running",
        "dry_run": True,
        "device_id": "dev1",
        "state": {
            "steps": 2,
            "last_action": "opener",
            "last_reason": "dry_run",
            "last_package": "ai.mobilerun.mockdating",
            "steps_detail": [
                {
                    "n": 1,
                    "action": "opener",
                    "reason": "dry_run",
                    "package": "ai.mobilerun.mockdating",
                    "ok": True,
                }
            ],
            "openers_sent": 1,
        },
    }
    p = activity_log.activity_payload_from_job(job)
    assert p["job_id"] == "dating_abc"
    assert p["dry_run"] is True
    assert p["current_step"] == 2
    assert p["last_action"] == "opener"
    assert len(p["steps"]) == 1


def test_run_dating_step_dry_run_logs_activity(monkeypatch):
    from backend import step_worker

    sent: List[Dict[str, Any]] = []

    monkeypatch.setattr(step_worker, "_safety_blocked", lambda job: False)
    monkeypatch.setattr(
        step_worker,
        "_send_to_device",
        lambda device_id, payload: sent.append(payload) or True,
    )
    monkeypatch.setattr(
        step_worker,
        "_compose_for_step",
        lambda *a, **k: {
            "text": "hi",
            "source": "template",
            "template_id": "t1",
            "used_llm": False,
        },
    )

    class FakeHumanizer:
        def __init__(self):
            import random

            self._rng = random.Random(0)

        def sample_message_gap_seconds(self):
            return 10.0

        def sample_swipe_step_gap_seconds(self):
            return 5.0

        def ordered_apps(self, apps):
            return list(apps)

    monkeypatch.setattr(step_worker, "_humanizer_for_job", lambda job: FakeHumanizer())
    monkeypatch.setattr(
        "backend.activity_log.capture_device_context",
        lambda device_id: {
            "package": "ai.mobilerun.mockdating",
            "tree_chars": 42,
            "screenshot_b64": None,
        },
    )
    monkeypatch.setattr("backend.activity_log.store_screenshot", lambda *a, **k: None)
    monkeypatch.setattr(step_worker, "_kick_job_later", lambda *a, **k: None)
    monkeypatch.setattr(step_worker.time, "sleep", lambda *a, **k: None)

    job = {
        "job_id": "dating_test1",
        "kind": "dating",
        "status": "running",
        "device_id": "emu1",
        "dry_run": True,
        "stand_in_package": "ai.mobilerun.mockdating",
        "caps": {
            "opener_target": 3,
            "global_message_max": 6,
            "swipe_cap": 2,
            "reply_cap": 2,
        },
        "state": {
            "openers_sent": 0,
            "replies_sent": 0,
            "swipes_done": 0,
            "steps": 0,
            "steps_detail": [],
        },
    }
    out = step_worker.run_dating_step(job)
    assert out["status"] == "running"
    assert out["state"]["steps"] == 1
    assert out["state"]["openers_sent"] == 1
    detail = out["state"]["steps_detail"]
    assert len(detail) == 1
    assert detail[0]["action"] == "opener"
    assert detail[0]["dry_run"] is True
    assert "dry_run" in (detail[0].get("reason") or "")
    # dry-run opens stand-in instead of sending opener
    assert sent and sent[0]["command"] == "open_app"


def test_run_social_step_dry_run_logs_activity(monkeypatch):
    from backend import step_worker

    monkeypatch.setattr(step_worker, "_safety_blocked", lambda job: False)
    monkeypatch.setattr(step_worker, "_send_to_device", lambda *a, **k: True)
    monkeypatch.setattr(step_worker, "_kick_job_later", lambda *a, **k: None)
    monkeypatch.setattr(step_worker.time, "sleep", lambda *a, **k: None)

    class FakeHumanizer:
        def __init__(self):
            import random

            self._rng = random.Random(1)

        def sample_message_gap_seconds(self):
            return 8.0

    monkeypatch.setattr(step_worker, "_humanizer_for_job", lambda job: FakeHumanizer())
    monkeypatch.setattr(
        "backend.activity_log.capture_device_context",
        lambda device_id: {
            "package": "com.google.android.apps.messaging",
            "tree_chars": 10,
            "screenshot_b64": None,
        },
    )
    monkeypatch.setattr(
        "backend.activity_log.store_screenshot", lambda *a, **k: "shots/1.png"
    )

    job = {
        "job_id": "social_test1",
        "kind": "social",
        "status": "running",
        "device_id": "emu1",
        "dry_run": True,
        "stand_in_package": "com.google.android.apps.messaging",
        "max_steps": 6,
        "state": {"steps": 0, "steps_detail": []},
    }
    out = step_worker.run_social_step(job)
    assert out["state"]["steps"] == 1
    assert len(out["state"]["steps_detail"]) == 1
    assert out["state"]["steps_detail"][0]["screenshot_key"] == "shots/1.png"
    assert out["state"]["steps_detail"][0]["action"] == "open_app"


def test_dating_social_start_activity_endpoints(monkeypatch):
    """API smoke: start dating/social dry-run and fetch activity (in-memory storage)."""
    from fastapi.testclient import TestClient

    from backend import main as main_mod

    jobs: Dict[str, Dict[str, Any]] = {}

    def put_job(job):
        jobs[job["job_id"]] = dict(job)

    def get_job(job_id):
        return jobs.get(job_id)

    def list_recent_jobs(limit=40):
        return list(jobs.values())[:limit]

    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setattr(main_mod, "_kick_job", lambda job_id: None)
    monkeypatch.setattr(main_mod, "_save_dating_runtime", lambda *a, **k: None)
    monkeypatch.setattr(main_mod, "_load_dating_runtime", lambda *a, **k: None)

    # Patch storage imports used inside handlers
    import sys
    import types

    storage = types.ModuleType("storage")
    storage.put_job = put_job
    storage.get_job = get_job
    storage.list_recent_jobs = list_recent_jobs
    monkeypatch.setitem(sys.modules, "storage", storage)
    monkeypatch.setitem(sys.modules, "backend.storage", storage)

    # Reset mode state
    main_mod.dating_mode_state["running"] = False
    main_mod.dating_mode_state.pop("job_id", None)
    main_mod.social_mode_state["running"] = False
    main_mod.social_mode_state.pop("job_id", None)

    c = TestClient(main_mod.app)
    d = c.post(
        "/api/dating/start",
        json={
            "device_id": "emu",
            "dry_run": True,
            "stand_in_package": "ai.mobilerun.mockdating",
        },
    )
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["status"] == "started"
    job_id = body["job"]["job_id"]
    assert job_id in jobs
    assert jobs[job_id]["dry_run"] is True
    assert jobs[job_id]["caps"]["opener_target"] == 3

    act = c.get("/api/dating/activity")
    assert act.status_code == 200
    assert act.json()["job_id"] == job_id

    s = c.post(
        "/api/social/start",
        json={
            "device_id": "emu",
            "dry_run": True,
            "stand_in_package": "com.google.android.apps.messaging",
            "max_steps": 4,
        },
    )
    assert s.status_code == 200, s.text
    sjob = s.json()["job"]["job_id"]
    assert sjob.startswith("social_")
    sact = c.get("/api/social/activity")
    assert sact.json()["job_id"] == sjob

    c.post("/api/dating/stop")
    c.post("/api/social/stop")
