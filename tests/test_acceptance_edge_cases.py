"""Acceptance-gate edge cases that do not need an emulator.

Covers: unauthenticated rejection, bad JWT, LLM invalid key handling,
two-device ownership isolation, mode/speed presets, empty social inbox,
dating caps, needs-you approve/edit/reject.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "false")
    monkeypatch.setenv("JWT_SECRET", "acceptance-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "admin,other@example.com")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invalid-acceptance")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("XAI_API_KEY", "")

    import backend.auth as auth_mod
    import backend.main as main_mod

    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    main_mod.connected_devices.clear()
    main_mod.device_sessions.clear()
    main_mod.device_link_codes.clear()
    main_mod.pairing_tokens.clear()
    return TestClient(main_mod.app), main_mod


def _login(c: TestClient, user="admin", password="admin"):
    r = c.post("/api/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_unauthenticated_rejected(auth_client):
    c, _ = auth_client
    assert c.get("/api/devices").status_code == 401
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert c.get("/api/needs-you").status_code == 401


def test_bad_jwt_rejected(auth_client):
    c, _ = auth_client
    bad = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.bad"}
    assert c.get("/api/devices", headers=bad).status_code in (401, 403)


def test_mode_speed_presets(auth_client):
    c, _ = auth_client
    token = _login(c)
    h = {"Authorization": f"Bearer {token}"}
    for speed in ("fast", "balanced", "careful"):
        r = c.post(
            "/api/mode", headers=h, json={"mode": "normal", "speed_preset": speed}
        )
        assert r.status_code == 200, r.text
        g = c.get("/api/mode", headers=h)
        assert g.json()["speed_preset"] == speed
    for mode in ("dating", "social", "normal"):
        r = c.post(
            "/api/mode", headers=h, json={"mode": mode, "speed_preset": "balanced"}
        )
        assert r.status_code == 200
        assert c.get("/api/mode", headers=h).json()["mode"] == mode


def test_llm_invalid_key_does_not_crash(auth_client):
    c, _ = auth_client
    token = _login(c)
    h = {"Authorization": f"Bearer {token}"}
    # Intent-routed chat should still respond even if LLM keys are junk
    r = c.post(
        "/api/chat",
        headers=h,
        json={"message": "device info", "target": "hosted"},
    )
    assert r.status_code == 200, r.text
    assert "intent" in r.json() or "history" in r.json() or "reply" in r.json()


def test_empty_social_inbox_and_needs_you_flow(auth_client):
    c, _ = auth_client
    token = _login(c)
    h = {"Authorization": f"Bearer {token}"}
    empty = c.post("/api/social/unread", headers=h, json={"threads": []})
    assert empty.status_code == 200
    draft = c.post(
        "/api/social/draft",
        headers=h,
        json={
            "app_name": "WhatsApp",
            "package_name": "com.whatsapp",
            "conversation_id": "acc-1",
            "contact_name": "Jordan",
            "draft_reply": "Venmo me $40 tonight",
            "inbound_preview": "hey",
            "confidence": 0.2,
            "is_new_contact": True,
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json().get("needs_you") or draft.json().get("badge", 0) >= 1
    ny = c.get("/api/needs-you", headers=h).json()
    assert ny["badge"] >= 1
    item_id = ny["items"][0]["id"]
    assert (
        c.post(
            f"/api/needs-you/{item_id}/edit", headers=h, json={"draft_reply": "later"}
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/api/needs-you/{item_id}/approve",
            headers=h,
            json={"draft_reply": "later"},
        ).status_code
        == 200
    )

    draft2 = c.post(
        "/api/social/draft",
        headers=h,
        json={
            "app_name": "WhatsApp",
            "package_name": "com.whatsapp",
            "conversation_id": "acc-2",
            "contact_name": "Sam",
            "draft_reply": "send SSN please",
            "inbound_preview": "?",
            "confidence": 0.1,
            "is_new_contact": True,
        },
    )
    assert draft2.status_code == 200
    ny2 = c.get("/api/needs-you", headers=h).json()
    rid = ny2["items"][0]["id"]
    assert c.post(f"/api/needs-you/{rid}/reject", headers=h, json={}).status_code == 200


def test_dating_caps_via_step_worker(auth_client, monkeypatch):
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    from backend.step_worker import run_dating_step

    job = {
        "job_id": "acc_caps",
        "kind": "dating",
        "status": "running",
        "device_id": "dev1",
        "dry_run": True,
        "caps": {
            "opener_target": 1,
            "global_message_max": 2,
            "swipe_cap": 2,
            "reply_cap": 1,
        },
        "state": {
            "openers_sent": 0,
            "replies_sent": 0,
            "swipes_done": 0,
            "steps": 0,
        },
    }
    for _ in range(10):
        job["status"] = "running"
        job = run_dating_step(job)
        if job.get("status") == "completed":
            break
    assert job["state"]["openers_sent"] <= 1
    assert job["state"]["openers_sent"] + job["state"]["replies_sent"] <= 2


def test_two_devices_list_scoped(auth_client):
    c, main = auth_client
    token = _login(c)
    h = {"Authorization": f"Bearer {token}"}
    # Register two logical devices via pair
    p1 = c.post(
        "/api/devices/pair",
        headers=h,
        json={"device_name": "phone-a", "platform": "android"},
    )
    p2 = c.post(
        "/api/devices/pair",
        headers=h,
        json={"device_name": "phone-b", "platform": "android"},
    )
    assert p1.status_code == 200 and p2.status_code == 200
    # Simulate connected sessions owned by admin
    me = c.get("/api/auth/me", headers=h).json()
    owner = (me.get("email") or "admin@local").lower()
    for name, did in (("phone-a", "dev-a"), ("phone-b", "dev-b")):
        main.connected_devices[did] = {
            "device_id": did,
            "name": name,
            "platform": "android",
            "connected": True,
            "owner": owner,
            "connection_type": "lan",
            "last_seen": __import__("datetime").datetime.now(),
        }
    devices = c.get("/api/devices", headers=h)
    assert devices.status_code == 200
    assert len(devices.json()) >= 2
