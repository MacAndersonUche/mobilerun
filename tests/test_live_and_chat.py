"""Live view relay + AI chat agent tests."""

from __future__ import annotations

import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("JWT_SECRET", "test")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    from backend import main as backend_main
    from backend import live_hub

    live_hub.ui_subscribers.clear()
    live_hub.ui_device.clear()
    live_hub.agent_state.clear()
    live_hub.stream_wanted.clear()
    backend_main.connected_devices.clear()
    backend_main.device_websockets.clear()
    backend_main.agent_mode_state.update({"mode": "normal", "speed_preset": "balanced"})
    return TestClient(backend_main.app)


def test_mode_api_and_chat_speed(client):
    res = client.get("/api/mode")
    assert res.status_code == 200
    assert res.json()["mode"] == "normal"
    assert res.json()["speed_preset"] == "balanced"
    assert "fast" in res.json()["presets"]

    res2 = client.post("/api/mode", json={"mode": "dating", "speed_preset": "careful"})
    assert res2.status_code == 200
    assert res2.json()["mode"] == "dating"
    assert res2.json()["speed_preset"] == "careful"

    chat = client.post(
        "/api/chat",
        json={"message": "switch to normal mode", "target": "pc"},
    )
    assert chat.status_code == 200
    assert chat.json()["intent"] == "set_mode"

    chat2 = client.post(
        "/api/chat",
        json={"message": "speed fast", "target": "pc"},
    )
    assert chat2.status_code == 200
    assert chat2.json()["intent"] == "set_mode"
    assert client.get("/api/mode").json()["speed_preset"] == "fast"


def test_chat_device_info_and_history(client):
    res = client.post("/api/chat", json={"message": "device info", "target": "pc"})
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "device_info"
    assert body["needs_confirm"] is False
    sid = body["session_id"]
    hist = client.get(f"/api/chat/{sid}")
    assert hist.status_code == 200
    assert len(hist.json()["messages"]) >= 2


def test_chat_confirms_dating_start(client):
    res = client.post(
        "/api/chat",
        json={"message": "start dating mode", "target": "pc", "confirmed": False},
    )
    assert res.status_code == 200
    assert res.json()["needs_confirm"] is True
    assert res.json()["intent"] == "dating_start"

    res2 = client.post(
        "/api/chat",
        json={
            "message": "start dating mode",
            "session_id": res.json()["session_id"],
            "target": "pc",
            "confirmed": True,
        },
    )
    assert res2.status_code == 200
    assert res2.json()["needs_confirm"] is False
    assert "Dating mode start" in res2.json()["reply"]


def test_chat_run_task_errors_when_device_offline(client):
    """Offline/missing device must surface an error — never silent 'Queued task'."""
    res = client.post(
        "/api/chat",
        json={
            "message": "open Settings",
            "device_id": "emulator",
            "target": "pc",
            "confirmed": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "run_task"
    assert body.get("error") or "Error" in body["reply"] or "offline" in body["reply"].lower()
    assert "Queued task" not in body["reply"]


def test_live_inject_frame_relays_to_ui_subscriber(client):
    from backend import live_hub

    # Tiny 1x1 jpeg
    jpeg = base64.b64encode(
        bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
            "070909080a0c140d0c0b0b0c1913130f141d1a1f1e1d1a1c1c20242e2720222c231c"
            "1c2837292c30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d"
            "0d1832211c2132323232323232323232323232323232323232323232323232323232"
            "32323232323232323232323232323232323232323232323232ffc000110800010001"
            "03011100021101031101ffc40014000100000000000000000000000000000008ffc4"
            "00140110000000000000000000000000000000ffda000c0301000210031000003f00"
            "bf800fffd9"
        )
    ).decode()

    with client.websocket_connect("/api/ui/connect") as ws:
        ws.send_json(
            {"type": "subscribe", "device_id": "emu1", "fps": 2, "quality": 40}
        )
        sub = ws.receive_json()
        assert sub["type"] == "subscribed"
        assert live_hub.stream_wanted.get("emu1") is True

        inj = client.post(
            "/api/live/inject-frame",
            json={
                "device_id": "emu1",
                "data": jpeg,
                "width": 1,
                "height": 1,
                "seq": 7,
            },
        )
        assert inj.status_code == 200
        assert inj.json()["relayed"] >= 1

        frame = ws.receive_json()
        assert frame["type"] == "frame"
        assert frame["seq"] == 7
        assert frame["data"] == jpeg

        ws.send_json({"type": "unsubscribe", "device_id": "emu1"})


def test_live_state_endpoint(client):
    from backend.live_hub import update_agent_state

    update_agent_state("d1", {"current_app": "Settings", "action": "tap", "log": "hi"})
    res = client.get("/api/live/state/d1")
    assert res.status_code == 200
    assert res.json()["state"]["current_app"] == "Settings"
    assert "hi" in res.json()["state"]["logs"]
