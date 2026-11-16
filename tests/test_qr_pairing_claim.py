"""QR pairing: create (hashed) → claim → revoke."""

from __future__ import annotations

import importlib

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
    main_mod.device_sessions.clear()
    main_mod.pairing_tokens.clear()
    return TestClient(main_mod.app)


def test_pair_create_requires_auth(client):
    res = client.post("/api/auth/pair/create", json={"device_name": "Pixel"})
    assert res.status_code == 401


def test_pair_claim_and_revoke(client):
    from backend.storage import get_pairing_token, hash_secret

    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    token = login.json()["access_token"]
    created = client.post(
        "/api/auth/pair/create",
        json={"device_name": "Pixel", "platform": "android"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["token"]
    assert "mobilerun://pair?" in body["pairing_url"]
    assert body["https_link"].startswith("http")
    # Hashed at rest — plaintext lookup via hash helper works; raw key not stored as file name
    stored = get_pairing_token(body["token"])
    assert stored is not None
    assert stored.get("owner")
    assert "token" not in (stored or {})

    claim = client.post(
        "/api/auth/pair/claim",
        json={"token": body["token"], "device_name": "Pixel"},
    )
    assert claim.status_code == 200, claim.text
    creds = claim.json()
    assert creds["session_token"]
    assert creds["device_id"]
    assert creds["owner"].startswith("admin")

    # Single-use
    again = client.post(
        "/api/auth/pair/claim",
        json={"token": body["token"], "device_name": "Pixel"},
    )
    assert again.status_code == 400

    devices = client.get(
        "/api/devices", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert any(d["device_id"] == creds["device_id"] for d in devices)

    rev = client.delete(
        f"/api/devices/{creds['device_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rev.status_code == 200
    devices2 = client.get(
        "/api/devices", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert not any(d["device_id"] == creds["device_id"] for d in devices2)


def test_pairing_token_rate_limit(client, monkeypatch):
    from backend import pairing_security

    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    token = login.json()["access_token"]
    # Force tiny limit
    monkeypatch.setattr(
        pairing_security,
        "check_rate_limit",
        lambda *a, **k: False,
    )
    res = client.post(
        "/api/auth/pair/create",
        json={"device_name": "X"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 429
