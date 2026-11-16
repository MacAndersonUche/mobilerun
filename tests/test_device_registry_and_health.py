"""Regression: durable device registry, /health alias, device-code persistence."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "mac@macai.local,admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    import importlib
    import backend.auth as auth_mod
    import backend.main as backend_main

    importlib.reload(auth_mod)
    importlib.reload(backend_main)
    backend_main.connected_devices.clear()
    backend_main.device_sessions.clear()
    backend_main.device_link_codes.clear()
    backend_main.device_websockets.clear()
    return TestClient(backend_main.app)


def test_health_alias_and_api_health(client):
    r1 = client.get("/api/health")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"
    r2 = client.get("/health")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"


def test_device_code_persists_across_memory_clear(client, monkeypatch, tmp_path):
    """Simulate Lambda cold start: in-memory map wiped, SETTINGS still has code."""
    from backend.auth import create_access_token
    from backend import main as backend_main

    start = client.post(
        "/api/auth/device/code",
        json={"device_name": "Pixel", "platform": "android"},
    )
    assert start.status_code == 200
    user_code = start.json()["user_code"]
    device_code = start.json()["device_code"]

    backend_main.device_link_codes.clear()  # cold start

    token = create_access_token(
        {"sub": "mac", "email": "mac@macai.local", "user_id": "mac@macai.local"}
    )

    approve = client.post(
        "/api/auth/device/approve",
        json={"user_code": user_code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["device_id"]

    backend_main.device_link_codes.clear()  # cold start again before poll
    poll = client.post(
        "/api/auth/device/token",
        json={"device_code": device_code},
    )
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["session_token"]
    assert body["device_id"]
    assert body["owner"] == "mac@macai.local"


def test_list_devices_merges_persisted_registry(client, monkeypatch, tmp_path):
    from backend.auth import create_access_token
    from backend.storage import upsert_owned_device

    owner = "mac@macai.local"
    upsert_owned_device(
        owner,
        {
            "device_id": "device_abc",
            "name": "Phone",
            "platform": "android",
            "connected": True,
            "connection_type": "cloud",
            "owner": owner,
            "last_seen": "2026-01-01T00:00:00",
        },
    )
    token = create_access_token({"sub": "mac", "email": owner})
    res = client.get(
        "/api/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    ids = [d["device_id"] for d in res.json()]
    assert "device_abc" in ids


def test_ws_handler_register_upserts_owned_device(monkeypatch, tmp_path):
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")

    from backend.storage import list_owned_devices, save_device_session
    from backend import ws_handler

    # Stub management API so handler doesn't need real API GW
    class _FakeClient:
        def post_to_connection(self, **kwargs):
            return None

    monkeypatch.setattr(ws_handler, "_mgmt_client", lambda event: _FakeClient())
    monkeypatch.setattr(ws_handler, "save_connection", lambda *a, **k: None)
    monkeypatch.setattr(ws_handler, "get_device_connections", lambda *_: [])

    save_device_session(
        "sess-1",
        {
            "device_id": "device_ws1",
            "name": "Emulator",
            "platform": "android",
            "owner": "mac@macai.local",
        },
    )
    event = {
        "requestContext": {
            "routeKey": "$default",
            "connectionId": "c1",
            "domainName": "example.execute-api.eu-west-2.amazonaws.com",
            "stage": "prod",
        },
        "body": (
            '{"type":"register","device_id":"device_ws1","session_token":"sess-1",'
            '"device_name":"Emulator","platform":"android","route":"cloud"}'
        ),
    }
    out = ws_handler.handler(event, None)
    assert out["statusCode"] == 200
    owned = list_owned_devices("mac@macai.local")
    assert any(d.get("device_id") == "device_ws1" for d in owned)


def test_dynamo_safe_strips_none_and_floats():
    from backend.storage import _dynamo_safe, _from_dynamo
    from decimal import Decimal

    raw = {"expires_at": 1.5, "owner": None, "ok": True, "n": 2}
    safe = _dynamo_safe(raw)
    assert "owner" not in safe
    assert isinstance(safe["expires_at"], Decimal)
    back = _from_dynamo(safe)
    assert back["expires_at"] == 1.5
    assert back["ok"] is True


def test_merge_device_lists_aws_trusts_ws(monkeypatch, tmp_path):
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "true")

    from backend.storage import upsert_owned_device
    from backend import device_registry

    upsert_owned_device(
        "a@b.com",
        {
            "device_id": "d1",
            "name": "X",
            "connected": True,
            "owner": "a@b.com",
        },
    )
    monkeypatch.setattr("backend.storage.device_is_ws_connected", lambda _did: False)
    # Also patch the import path used inside merge
    import backend.storage as storage

    monkeypatch.setattr(storage, "device_is_ws_connected", lambda _did: False)

    merged = device_registry.merge_device_lists({}, "a@b.com")
    assert merged
    assert merged[0]["connected"] is False
