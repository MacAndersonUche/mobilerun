"""LAN vs cloud endpoint selection, pairing URI, backoff — no USB required."""

from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

from mobilerun.connectivity.endpoints import (
    Endpoint,
    build_pairing_url,
    http_to_ws,
    next_backoff_seconds,
    parse_pairing_uri,
    select_endpoint,
)


def test_http_to_ws():
    assert http_to_ws("http://192.168.1.10:8000") == (
        "ws://192.168.1.10:8000/api/devices/connect"
    )
    assert http_to_ws("https://api.example.com").startswith("wss://")


def test_build_and_parse_dual_endpoints():
    url = build_pairing_url(
        token="tok123",
        lan_http="http://192.168.1.5:8000",
        lan_ws="ws://192.168.1.5:8000/api/devices/connect",
        cloud_http="https://api.example.com",
        cloud_ws="wss://ws.example.com",
        backend="http://192.168.1.5:8000",
        ws="ws://192.168.1.5:8000/api/devices/connect",
    )
    assert url.startswith("mobilerun://pair?")
    bundle = parse_pairing_uri(url)
    assert bundle.token == "tok123"
    assert bundle.lan is not None
    assert bundle.lan.kind == "lan"
    assert "192.168.1.5" in bundle.lan.ws_url
    assert bundle.cloud is not None
    assert bundle.cloud.kind == "cloud"
    assert "wss://" in bundle.cloud.ws_url or "ws.example.com" in bundle.cloud.ws_url


def test_select_prefers_fast_lan_over_cloud():
    lan = Endpoint(
        "lan",
        "http://10.0.0.2:8000",
        "ws://10.0.0.2:8000/api/devices/connect",
        latency_ms=12,
    )
    cloud = Endpoint(
        "cloud",
        "https://api.example.com",
        "wss://ws.example.com",
        latency_ms=80,
    )
    assert select_endpoint([cloud, lan]).kind == "lan"


def test_select_falls_back_to_cloud_when_lan_slow_or_dead():
    lan = Endpoint(
        "lan",
        "http://10.0.0.2:8000",
        "ws://10.0.0.2:8000/api/devices/connect",
        latency_ms=900,
    )
    cloud = Endpoint(
        "cloud",
        "https://api.example.com",
        "wss://ws.example.com",
        latency_ms=120,
    )
    pick = select_endpoint([lan, cloud], max_lan_latency_ms=250)
    assert pick.kind == "cloud"


def test_select_unmeasured_lan_before_cloud():
    lan = Endpoint("lan", "http://10.0.2.2:8000", "ws://10.0.2.2:8000/x")
    cloud = Endpoint("cloud", "https://x", "wss://x")
    assert select_endpoint([cloud, lan]).kind == "lan"


def test_backoff_grows_and_is_jittered():
    rng = random.Random(0)
    d0 = next_backoff_seconds(0, rng=rng)
    d3 = next_backoff_seconds(3, rng=rng)
    assert d0 < d3
    assert d3 <= 60.0
    samples = [round(next_backoff_seconds(2, rng=rng), 3) for _ in range(20)]
    assert len(set(samples)) > 1


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("JWT_SECRET", "test")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("HOST", "0.0.0.0")
    from backend import main as backend_main

    backend_main.connected_devices.clear()
    backend_main.device_websockets.clear()
    backend_main.pairing_tokens.clear()
    backend_main.device_sessions.clear()
    return TestClient(backend_main.app)


def test_pair_qr_includes_lan_and_mdns_hint(client):
    res = client.post(
        "/api/devices/pair", json={"device_name": "phone", "platform": "android"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mdns_service"] == "_mobilerun._tcp"
    assert "lan_ws" in body
    assert "mobilerun://pair?" in body["pairing_url"]
    assert "token=" in body["pairing_url"]
    health = client.get("/api/health").json()
    assert health["usb_required"] is False


def test_session_reconnect_without_re_pair(client):
    pair = client.post(
        "/api/devices/pair", json={"device_name": "emu", "platform": "android"}
    ).json()
    token = pair["token"]

    with client.websocket_connect("/api/devices/connect") as ws:
        ws.send_json(
            {
                "type": "register",
                "token": token,
                "device_id": "android_test",
                "platform": "android",
                "route": "lan",
                "latency_ms": 18,
            }
        )
        ack = ws.receive_json()
        assert ack["status"] == "connected"
        session = ack["session_token"]
        assert session
        ws.send_json(
            {
                "type": "connection_status",
                "route": "lan",
                "latency_ms": 22,
            }
        )

    devices = client.get("/api/devices").json()
    assert devices
    # disconnected after close but metadata retained
    d = devices[0]
    assert d["route"] == "lan"
    assert d["latency_ms"] == 22

    with client.websocket_connect("/api/devices/connect") as ws:
        ws.send_json(
            {
                "type": "register",
                "session_token": session,
                "device_id": "android_test",
                "route": "cloud",
                "latency_ms": 140,
            }
        )
        ack2 = ws.receive_json()
        assert ack2["status"] == "connected"
        assert ack2["device_id"] == "android_test"

    devices2 = client.get("/api/devices").json()
    assert devices2[0]["route"] == "cloud"
    assert devices2[0]["latency_ms"] == 140
