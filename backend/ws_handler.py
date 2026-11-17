"""
API Gateway WebSocket Lambda handler.

Routes: $connect, $disconnect, $default
Phone and UI clients share the same WS API.
Frames are relayed device→UI without storage (cost/bandwidth).
Device register/heartbeat persist ownership into SETTINGS so HTTP list_devices works.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import boto3

try:
    from storage import (
        delete_connection,
        delete_pairing_token,
        get_device_connections,
        get_pairing_token,
        save_connection,
        save_device_session,
    )
except ImportError:  # Lambda package layout: backend.*
    from backend.storage import (  # type: ignore
        delete_connection,
        delete_pairing_token,
        get_device_connections,
        get_pairing_token,
        save_connection,
        save_device_session,
    )

try:
    from device_registry import resolve_owner_from_message, upsert_from_ws
except ImportError:
    from backend.device_registry import (  # type: ignore
        resolve_owner_from_message,
        upsert_from_ws,
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


def _persist_device(
    body: Dict[str, Any], connection_id: str
) -> tuple[str, Optional[str]]:
    """Auth register/heartbeat and return (device_id, owner). Never log tokens."""
    owner, device_id, sess = resolve_owner_from_message(body)
    # Heartbeats often omit session_token — recover owner from prior $connect/register
    if not owner:
        try:
            from storage import get_connection
        except ImportError:
            from backend.storage import get_connection  # type: ignore

        prev = get_connection(connection_id) or {}
        owner = (prev.get("owner") or "").lower() or None
        if not device_id and prev.get("device_id"):
            device_id = str(prev["device_id"])
        if not sess.get("name") and prev.get("name"):
            sess = {**sess, "name": prev.get("name"), "platform": prev.get("platform")}
    # Pairing owner hint (one-shot token path)
    if not owner and body.get("owner_hint"):
        owner = str(body["owner_hint"]).lower()

    device_id = device_id or str(body.get("device_id") or f"pending_{connection_id}")
    role = body.get("role") or "device"
    name = body.get("device_name") or body.get("name") or sess.get("name") or device_id
    platform = body.get("platform") or sess.get("platform") or "android"
    route = body.get("route")
    latency = body.get("latency_ms")
    perms = body.get("permissions")
    if not isinstance(perms, dict):
        # permission_status messages flatten fields onto the body
        if (
            body.get("type") in ("permissions", "permission_status")
            or body.get("accessibility") is not None
        ):
            perms = {
                k: body.get(k)
                for k in (
                    "accessibility",
                    "notifications",
                    "media_projection",
                    "battery_unrestricted",
                    "overlay",
                    "query_packages",
                    "foreground_service",
                )
                if k in body
            } or None
        else:
            perms = None

    save_connection(
        connection_id,
        str(device_id),
        {
            "platform": platform,
            "last_type": body.get("type") or body.get("action"),
            "role": role,
            "authed": bool(owner) or role == "ui",
            "owner": owner or "",
            "name": name,
            "connected_at": int(time.time()),
        },
    )
    # One live device socket — drop older duplicates (Samsung reconnect leaves ghosts)
    if role != "ui" and device_id:
        try:
            from device_push import prune_stale_device_connections
        except ImportError:
            from backend.device_push import prune_stale_device_connections  # type: ignore

        try:
            prune_stale_device_connections(
                str(device_id), keep_connection_id=connection_id
            )
        except Exception as e:
            logger.warning("prune stale connections failed: %s", e)
    if owner and role != "ui":
        upsert_from_ws(
            owner=owner,
            device_id=str(device_id),
            name=str(name),
            platform=str(platform),
            route=str(route) if route else None,
            latency_ms=float(latency) if latency is not None else None,
            permissions=perms,
            connection_type=str(route or "websocket"),
        )
        # Keep session durable if phone sent one
        st = body.get("session_token")
        if st:
            save_device_session(
                str(st),
                {
                    "device_id": device_id,
                    "name": name,
                    "platform": platform,
                    "owner": owner,
                },
            )
    return str(device_id), owner


def handler(event: Dict[str, Any], context: Any):
    route = event.get("requestContext", {}).get("routeKey")
    connection_id = event.get("requestContext", {}).get("connectionId")
    logger.info("ws route=%s connection=%s", route, connection_id)

    if route == "$connect":
        qs = event.get("queryStringParameters") or {}
        token = qs.get("token")
        role = qs.get("role", "device")
        device_id = qs.get("device_id") or f"pending_{connection_id}"
        owner = None
        if token:
            pairing = get_pairing_token(token)
            if pairing:
                expires = float(pairing.get("expires_at", 0))
                if time.time() > expires:
                    return _ok({"error": "token expired"}, 401)
                device_id = pairing.get("device_id") or device_id
                owner = pairing.get("owner")
                delete_pairing_token(token)
        save_connection(
            connection_id,
            device_id,
            {
                "platform": qs.get("platform", "android"),
                "authed": bool(token) or role == "ui",
                "role": role,
                "owner": owner or "",
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
            if pairing.get("owner"):
                body = {**body, "owner_hint": pairing.get("owner")}
            delete_pairing_token(token)

    # Register / heartbeat / permissions / connection_status → persist ownership
    if msg_type in (
        "register",
        "heartbeat",
        "connection_status",
        "permissions",
        "permission_status",
    ):
        device_id, owner = _persist_device(body, connection_id)
        try:
            _post(
                client,
                connection_id,
                {
                    "status": "connected",
                    "device_id": device_id,
                    "type": "ack" if msg_type == "register" else "heartbeat_ack",
                    "echo_type": msg_type,
                    "owner": owner,
                },
            )
        except Exception as e:
            logger.warning("post_to_connection failed: %s", e)
        return _ok({"received": True, "device_id": device_id})

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
        sent = _send_to_device(
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
            {
                "type": "subscribed",
                "device_id": device_id,
                "state": {},
                "device_sockets": sent,
            },
        )
        return _ok({"subscribed": True, "device_sockets": sent})

    if msg_type == "unsubscribe" and device_id:
        uis = [
            c for c in get_device_connections(str(device_id)) if c.get("role") == "ui"
        ]
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

    if msg_type == "response":
        # Correlate phone replies for step-worker device_rpc.call_device
        rid = body.get("request_id")
        if rid:
            try:
                from device_rpc import store_rpc_response
            except ImportError:
                from backend.device_rpc import store_rpc_response  # type: ignore

            store_rpc_response(
                str(rid),
                {"error": body.get("error"), "result": body.get("result")},
            )
        return _ok({"stored": True, "request_id": rid})

    if msg_type == "task_update":
        task_id = body.get("task_id")
        update = body.get("update") or {}
        if task_id:
            try:
                from storage import get_job, put_job
            except ImportError:
                from backend.storage import get_job, put_job  # type: ignore

            job = get_job(str(task_id)) or {
                "job_id": str(task_id),
                "kind": "agent",
                "device_id": device_id,
            }
            status = update.get("status") or body.get("status") or job.get("status")
            job["status"] = status
            if update.get("result") is not None:
                job["result"] = update.get("result")
            if status in ("completed", "failed", "stopped"):
                job["completed_at"] = int(time.time())
            state = dict(job.get("state") or {})
            state["last_action"] = update.get("result") or status
            if status == "completed":
                state["steps"] = int(state.get("steps") or 0) + 1
            job["state"] = state
            put_job(job)
        if device_id:
            _relay_to_ui(
                client,
                str(device_id),
                {"type": "task_update", "device_id": device_id, **body},
            )
        return _ok({"updated": True, "task_id": task_id})

    # Default ack
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
