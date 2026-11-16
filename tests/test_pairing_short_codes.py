"""Short pairing codes + tiny /p/ QR payload."""

from __future__ import annotations

import base64
import importlib
import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("ALLOWED_USER_EMAILS", "admin,ci-e2e")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.setenv("FRONTEND_URL", "https://macsmobilerun.netlify.app")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    import backend.auth as auth_mod
    import backend.main as main_mod

    importlib.reload(auth_mod)
    importlib.reload(main_mod)
    main_mod.connected_devices.clear()
    main_mod.device_sessions.clear()
    main_mod.pairing_tokens.clear()
    return TestClient(main_mod.app)


def _login(c: TestClient, user="admin") -> str:
    return c.post(
        "/api/auth/login", json={"username": user, "password": "admin"}
    ).json()["access_token"]


def test_short_code_qr_and_claim(client):
    token = _login(client)
    created = client.post(
        "/api/auth/pair/create",
        json={"device_name": "Pixel", "platform": "android"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    code = body["code"]
    assert 6 <= len(code) <= 8
    assert code == code.upper()
    assert body["token"] == code
    assert body["short_link"].endswith(f"/p/{code}")
    assert "/p/" in body["https_link"]
    assert "c=" in body["pairing_url"]
    # QR PNG decodes and payload is short
    raw = base64.b64decode(body["qr_code"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(body.get("qr_payload") or body["short_link"]) < 64

    claim = client.post(
        "/api/auth/pair/claim",
        json={
            "token": code.lower(),
            "device_name": "Pixel",
            "device_id": "dev_short_1",
        },
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["device_id"] == "dev_short_1"


def test_ci_e2e_login_isolated(client):
    admin = _login(client, "admin")
    ci = _login(client, "ci-e2e")
    # Create under ci-e2e
    created = client.post(
        "/api/auth/pair/create",
        json={"device_name": "ci-phone", "platform": "android"},
        headers={"Authorization": f"Bearer {ci}"},
    )
    code = created.json()["code"]
    claim = client.post(
        "/api/auth/pair/claim",
        json={"token": code, "device_name": "ci-phone", "device_id": "device_ci_only"},
    )
    assert claim.status_code == 200
    # Admin must not see ci device
    admin_devs = client.get(
        "/api/devices", headers={"Authorization": f"Bearer {admin}"}
    ).json()
    assert not any(d["device_id"] == "device_ci_only" for d in admin_devs)
    ci_devs = client.get(
        "/api/devices", headers={"Authorization": f"Bearer {ci}"}
    ).json()
    assert any(d["device_id"] == "device_ci_only" for d in ci_devs)
    # Remove works
    rev = client.delete(
        "/api/devices/device_ci_only",
        headers={"Authorization": f"Bearer {ci}"},
    )
    assert rev.status_code == 200
    ci_devs2 = client.get(
        "/api/devices", headers={"Authorization": f"Bearer {ci}"}
    ).json()
    assert not any(d["device_id"] == "device_ci_only" for d in ci_devs2)


def test_normalize_pairing_code():
    from backend.pairing_codes import normalize_pairing_code

    assert normalize_pairing_code("ab3k7q2m") == "AB3K7Q2M"
    assert (
        normalize_pairing_code("https://macsmobilerun.netlify.app/p/AB3K7Q2M")
        == "AB3K7Q2M"
    )
    assert normalize_pairing_code("mobilerun://pair?c=AB3K7Q2M") == "AB3K7Q2M"
