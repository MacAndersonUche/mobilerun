"""Local JWT + device ownership helpers."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "admin,macandersonuche@yahoo.com")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    # Import after env so auth module picks up secrets
    import importlib
    import backend.auth as auth_mod
    import backend.main as main_mod

    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    main_mod.connected_devices.clear()
    main_mod.device_sessions.clear()
    main_mod.device_link_codes.clear()
    main_mod.pairing_tokens.clear()
    return TestClient(main_mod.app), main_mod


def test_login_and_me(client):
    c, _ = client
    bad = c.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    ok = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"].startswith("admin")


def test_device_code_approve_and_list(client):
    c, main = client
    login = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    token = login.json()["access_token"]
    started = c.post("/api/auth/device/code", json={"device_name": "Pixel"})
    assert started.status_code == 200
    user_code = started.json()["user_code"]
    device_code = started.json()["device_code"]

    pending = c.post("/api/auth/device/token", json={"device_code": device_code})
    assert pending.status_code == 400

    approved = c.post(
        "/api/auth/device/approve",
        json={"user_code": user_code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200
    polled = c.post("/api/auth/device/token", json={"device_code": device_code})
    assert polled.status_code == 200
    assert polled.json()["session_token"]

    devices = c.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
    assert devices.status_code == 200
    assert any(d["device_id"] == approved.json()["device_id"] for d in devices.json())
