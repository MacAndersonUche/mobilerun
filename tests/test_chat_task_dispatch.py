"""Chat run_task must dispatch via durable push, not fake-queue."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "admin")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    import backend.auth as auth_mod
    import backend.main as main_mod

    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    main_mod.connected_devices.clear()
    main_mod.device_websockets.clear()
    main_mod.active_runs.clear()
    main_mod.pairing_tokens.clear()
    return TestClient(main_mod.app), main_mod


def _login(c: TestClient) -> str:
    return c.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).json()["access_token"]


def test_chat_open_settings_dispatches_when_device_connected(client):
    c, main_mod = client
    token = _login(c)
    did = "phone_chat_1"
    main_mod.connected_devices[did] = {
        "device_id": did,
        "name": "Pixel",
        "connected": True,
        "owner": "admin@local",
        "platform": "android",
    }
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    main_mod.device_websockets[did] = mock_ws

    res = c.post(
        "/api/chat",
        json={
            "message": "open settings",
            "device_id": did,
            "target": "hosted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["intent"] == "run_task"
    assert body.get("error") in (None, "")
    assert "Started task" in body["reply"] or body.get("task_id")
    assert mock_ws.send_json.await_count >= 1
    sent = mock_ws.send_json.await_args.args[0]
    assert sent["type"] == "run_task"
    assert "settings" in sent["instruction"].lower() or sent["instruction"]


def test_chat_reports_offline_error_instead_of_silent_queue(client):
    c, main_mod = client
    token = _login(c)
    did = "phone_offline"
    # Owned but not connected / no ws
    from backend.storage import upsert_owned_device

    upsert_owned_device(
        "admin@local",
        {
            "device_id": did,
            "name": "OfflinePhone",
            "connected": False,
            "platform": "android",
        },
    )
    res = c.post(
        "/api/chat",
        json={"message": "open settings", "device_id": did, "target": "hosted"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert (
        body.get("error")
        or "offline" in body["reply"].lower()
        or "Error" in body["reply"]
    )
    assert "Queued task" not in body["reply"]
