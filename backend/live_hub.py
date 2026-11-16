"""In-process live view hub: device frames → UI WebSocket subscribers.

Frames are never stored — only relayed while a UI client is subscribed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger("mobilerun.live")

# device_id -> set of UI websockets
ui_subscribers: Dict[str, Set[WebSocket]] = {}
# UI websocket -> device_id
ui_device: Dict[WebSocket, str] = {}
# Latest agent overlay state per device (tiny; not frames)
agent_state: Dict[str, Dict[str, Any]] = {}
# Streaming requested?
stream_wanted: Dict[str, bool] = {}


def subscribers_for(device_id: str) -> Set[WebSocket]:
    return ui_subscribers.get(device_id, set())


async def subscribe_ui(ws: WebSocket, device_id: str) -> None:
    # Move off previous device if any
    await unsubscribe_ui(ws)
    ui_subscribers.setdefault(device_id, set()).add(ws)
    ui_device[ws] = device_id
    stream_wanted[device_id] = True
    logger.info("UI subscribed to %s (%d clients)", device_id, len(ui_subscribers[device_id]))


async def unsubscribe_ui(ws: WebSocket) -> None:
    device_id = ui_device.pop(ws, None)
    if not device_id:
        return
    clients = ui_subscribers.get(device_id)
    if clients and ws in clients:
        clients.discard(ws)
        if not clients:
            ui_subscribers.pop(device_id, None)
            stream_wanted[device_id] = False
            logger.info("No UI clients left for %s — stream can stop", device_id)


async def broadcast_to_ui(device_id: str, message: Dict[str, Any]) -> int:
    """Fan-out JSON to subscribed UI clients. Returns successful sends."""
    clients = list(subscribers_for(device_id))
    if not clients:
        return 0
    sent = 0
    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_json(message)
            sent += 1
        except Exception:
            dead.append(ws)
    for ws in dead:
        await unsubscribe_ui(ws)
    return sent


def update_agent_state(device_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    state = agent_state.setdefault(device_id, {})
    for k, v in patch.items():
        if v is not None:
            state[k] = v
    logs = state.setdefault("logs", [])
    if patch.get("log"):
        logs.append(str(patch["log"]))
        # Cap in-memory log buffer
        if len(logs) > 200:
            del logs[:-200]
    return state


async def relay_frame(device_id: str, frame: Dict[str, Any]) -> int:
    """Relay a device frame to UI. Drop if nobody is watching (save bandwidth/cost)."""
    if not subscribers_for(device_id):
        return 0
    payload = {"type": "frame", "device_id": device_id, **frame}
    # Avoid duplicating nested device_id/data keys oddly
    if "data" not in payload and "data" in frame:
        payload["data"] = frame["data"]
    return await broadcast_to_ui(device_id, payload)


async def notify_stream_control(
    send_to_device,
    device_id: str,
    action: str,
    fps: int = 3,
    quality: int = 45,
) -> None:
    await send_to_device(
        device_id,
        {
            "type": "stream_control",
            "action": action,
            "fps": fps,
            "quality": quality,
            "format": "jpeg",
        },
    )
