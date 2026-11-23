"""API tests: safety check → pause; resume only via /api/safety/resume."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)

    import backend.main as main_mod
    from mobilerun.safety.runtime import reset_safety_state

    importlib.reload(main_mod)
    reset_safety_state()
    main_mod.dating_mode_state["running"] = True
    main_mod.dating_mode_state["paused"] = False
    main_mod.get_needs_you_queue().clear()
    return TestClient(main_mod.app), main_mod


def test_humanizer_get_and_update(client):
    c, _ = client
    g = c.get("/api/humanizer")
    assert g.status_code == 200
    body = g.json()
    assert "presets" in body
    assert body["presets"]["balanced"]["action_delay_s"] == [0.6, 3.5] or body[
        "presets"
    ]["balanced"]["action_delay_s"] == (0.6, 3.5)
    # JSON turns tuples into lists
    assert list(body["presets"]["fast"]["action_delay_s"]) == [0.3, 1.8]

    u = c.post(
        "/api/humanizer",
        json={
            "speed_preset": "careful",
            "delay_sigma": 0.8,
            "shuffle_apps": False,
            "session_start_jitter_max": 60,
        },
    )
    assert u.status_code == 200
    assert u.json()["speed_preset"] == "careful"
    assert u.json()["overrides"]["delay_sigma"] == 0.8
    assert u.json()["overrides"]["shuffle_apps"] is False


def test_mock_dating_verification_triggers_pause(client):
    c, main = client
    # Start dating so pause is meaningful
    main.dating_mode_state["running"] = True
    main.dating_mode_state["paused"] = False

    screen = (
        "Verify your identity. We noticed unusual activity. "
        "Take a selfie for photo verification."
    )
    res = c.post(
        "/api/safety/check",
        json={
            "app": "MockDating",
            "package_name": "ai.mobilerun.mockdating",
            "screen_text": screen,
            "ui_texts": ["Verify your identity", "unusual activity"],
            "screenshot_b64": "aGVsbG8=",  # hello
            "device_id": "emulator",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["paused"] is True
    assert data["finding"]["detected"] is True
    assert data["finding"]["category"] in (
        "photo_verify",
        "unusual_activity",
        "login",
    )
    assert data["dating_paused"] is True
    # Internal id may still be minted for notify; portal list stays empty
    ny = c.get("/api/needs-you").json()
    assert ny["items"] == []
    assert ny.get("removed") is True or ny.get("badge", 0) == 0

    # Step worker must honour pause
    from backend.step_worker import run_dating_step

    job = {
        "job_id": "safety_e2e",
        "kind": "dating",
        "status": "running",
        "device_id": "emulator",
        "current_app": "MockDating",
        "caps": {
            "opener_target": 5,
            "global_message_max": 10,
            "swipe_cap": 5,
            "reply_cap": 5,
        },
        "state": {"openers_sent": 0, "replies_sent": 0, "swipes_done": 0, "steps": 0},
        "speed_preset": "balanced",
    }
    out = run_dating_step(job)
    assert out["status"] == "paused"
    assert out["state"]["last_action"] == "safety_pause"

    # Resume only via explicit API (Mac taps Resume)
    r = c.post("/api/safety/resume", json={"app": "MockDating"})
    assert r.status_code == 200
    assert r.json()["dating_paused"] is False
    st = c.get("/api/safety/status").json()
    assert st["blocked"] is False


def test_clean_screen_does_not_pause(client):
    c, main = client
    main.dating_mode_state["paused"] = False
    res = c.post(
        "/api/safety/check",
        json={
            "app": "MockDating",
            "screen_text": "Alex — coffee, dogs. Like Pass Send",
        },
    )
    assert res.status_code == 200
    assert res.json()["paused"] is False
    assert main.dating_mode_state["paused"] is False
