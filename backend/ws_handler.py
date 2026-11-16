"""
API Gateway WebSocket Lambda handler.

Routes: $connect, $disconnect, $default
Phone and UI clients share the same WS API.
Frames are relayed device→UI without storage (cost/bandwidth).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

import boto3

try:
    from storage import (
        delete_connection,
        delete_pairing_token,
        get_device_connections,
        get_pairing_token,
        save_connection,
    )
except ImportError:  # Lambda package layout: backend.*
    from backend.storage import (  # type: ignore
        delete_connection,
        delete_pairing_token,
        get_device_connections,
        get_pairing_token,
        save_connection,
    )

logger = logging.getLogger("mobilerun.ws")
logger.setLevel(logging.INFO)

# Soft size guard — API GW Management API ~128KB; keep JPEG small.
_MAX_FRAME_CHARS = 100_000


def _mgmt_client(event: Dict[str, Any]):
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]
    endpoint = f"https://{domain}/{stage}"
    return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)


def _ok(body: Dict[str, Any] | None = None, status: int = 200):
    return {
        "statusCode": status,
        "body": json.dumps(body or {"ok": True}),
    }


def _post(client, connection_id: str, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    if len(data) > 120_000:
        logger.warning("dropping oversized WS payload (%d bytes)", len(data))
        return
    client.post_to_connection(ConnectionId=connection_id, Data=data)


def _relay_to_ui(client, device_id: str, payload: Dict[str, Any]) -> int:
    sent = 0
    for conn in get_device_connections(device_id):
        if conn.get("role") != "ui":
            continue
        try:
            _post(client, conn["connection_id"], payload)
            sent += 1
        except Exception as e:
            logger.warning("ui relay failed %s: %s", conn.get("connection_id"), e)
    return sent


def _send_to_device(client, device_id: str, payload: Dict[str, Any]) -> int:
    sent = 0
    for conn in get_device_connections(device_id):
        if conn.get("role") == "ui":
            continue
        try:
            _post(client, conn["connection_id"], payload)
            sent += 1
        except Exception as e:
            logger.warning("device send failed %s: %s", conn.get("connection_id"), e)
    return sent


def handler(event: Dict[str, Any], context: Any):
    route = event.get("requestContext", {}).get("routeKey")
    connection_id = event.get("requestContext", {}).get("connectionId")
    logger.info("ws route=%s connection=%s", route, connection_id)

    if route == "$connect":
        qs = event.get("queryStringParameters") or {}
        token = qs.get("token")
        role = qs.get("role", "device")
        device_id = qs.get("device_id") or f"pending_{connection_id}"
        if token:
            pairing = get_pairing_token(token)
            if pairing:
                expires = float(pairing.get("expires_at", 0))
                if time.time() > expires:
                    return _ok({"error": "token expired"}, 401)
                device_id = pairing.get("device_id") or device_id
                delete_pairing_token(token)
        save_connection(
            connection_id,
            device_id,
            {
                "platform": qs.get("platform", "android"),
                "authed": bool(token) or role == "ui",
                "role": role,
            },
        )
        return _ok()

    if route == "$disconnect":
        if connection_id:
            delete_connection(connection_id)
        return _ok()

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _ok({"error": "invalid json"}, 400)

    msg_type = body.get("type") or body.get("action")
    token = body.get("token")
    device_id = body.get("device_id")
    role = body.get("role") or "device"
    client = _mgmt_client(event)

    if token:
        pairing = get_pairing_token(token)
        if pairing:
            expires = float(pairing.get("expires_at", 0))
            if time.time() > expires:
                delete_pairing_token(token)
                return _ok({"error": "token expired"}, 401)
            device_id = device_id or pairing.get("device_name") or connection_id
            delete_pairing_token(token)

    if connection_id and device_id:
        save_connection(
            connection_id,
            str(device_id),
            {
                "platform": body.get("platform", "web" if role == "ui" else "android"),
                "last_type": msg_type,
                "role": role,
                "authed": True,
            },
        )

    # UI subscribe → ask phone to start MediaProjection stream
    if msg_type == "subscribe" and device_id:
        save_connection(
            connection_id,
            str(device_id),
            {"role": "ui", "platform": "web", "authed": True},
        )
        _send_to_device(
            client,
            str(device_id),
            {
                "type": "stream_control",
                "action": "start",
                "fps": int(body.get("fps", 3)),
                "quality": int(body.get("quality", 45)),
                "format": "jpeg",
            },
        )
        _post(
            client,
            connection_id,
            {"type": "subscribed", "device_id": device_id, "state": {}},
        )
        return _ok({"subscribed": True})

    if msg_type == "unsubscribe" and device_id:
        # If no other UI clients, stop stream
        uis = [c for c in get_device_connections(str(device_id)) if c.get("role") == "ui"]
        if len(uis) <= 1:
            _send_to_device(
                client,
                str(device_id),
                {"type": "stream_control", "action": "stop"},
            )
        return _ok({"unsubscribed": True})

    if msg_type == "frame" and device_id:
        data = body.get("data") or ""
        if len(data) > _MAX_FRAME_CHARS:
            return _ok({"error": "frame too large"}, 413)
        relayed = _relay_to_ui(
            client,
            str(device_id),
            {
                "type": "frame",
                "device_id": device_id,
                "mime": body.get("mime", "image/jpeg"),
                "width": body.get("width"),
                "height": body.get("height"),
                "seq": body.get("seq"),
                "ts": body.get("ts"),
                "data": data,
            },
        )
        # No ack body with frame (bandwidth); silent ok
        return _ok({"relayed": relayed})

    if msg_type == "agent_event" and device_id:
        _relay_to_ui(
            client,
            str(device_id),
            {"type": "agent_event", "device_id": device_id, **body},
        )
        return _ok({"relayed": True})

    if msg_type == "input" and device_id:
        action = body.get("action")
        if action in ("tap", "swipe"):
            params = {
                k: v
                for k, v in body.items()
                if k not in ("type", "device_id", "action", "role", "token")
            }
            _send_to_device(
                client,
                str(device_id),
                {
                    "type": "command",
                    "command": action,
                    "request_id": f"ui_{int(time.time())}",
                    "params": params,
                },
            )
        return _ok({"sent": True})

    if msg_type == "task_control" and device_id:
        _send_to_device(client, str(device_id), body)
        return _ok({"sent": True})

    # Default ack for pairing / heartbeat / register
    try:
        _post(
            client,
            connection_id,
            {
                "status": "connected",
                "device_id": device_id,
                "type": "ack",
                "echo_type": msg_type,
            },
        )
    except Exception as e:
        logger.warning("post_to_connection failed: %s", e)

    return _ok({"received": True})
