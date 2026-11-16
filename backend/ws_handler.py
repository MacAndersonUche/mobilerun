"""
API Gateway WebSocket Lambda handler.

Routes: $connect, $disconnect, $default
Phone sends pairing token on first message after connect (or querystring).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict

import boto3

try:
    from storage import (
        delete_connection,
        delete_pairing_token,
        get_pairing_token,
        save_connection,
    )
except ImportError:  # Lambda package layout: backend.*
    from backend.storage import (  # type: ignore
        delete_connection,
        delete_pairing_token,
        get_pairing_token,
        save_connection,
    )

logger = logging.getLogger("mobilerun.ws")
logger.setLevel(logging.INFO)


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


def handler(event: Dict[str, Any], context: Any):
    route = event.get("requestContext", {}).get("routeKey")
    connection_id = event.get("requestContext", {}).get("connectionId")
    logger.info("ws route=%s connection=%s", route, connection_id)

    if route == "$connect":
        # Accept connection; auth happens on first message or via query token
        qs = event.get("queryStringParameters") or {}
        token = qs.get("token")
        device_id = qs.get("device_id") or f"pending_{connection_id}"
        if token:
            pairing = get_pairing_token(token)
            # Fall back: allow connect, validate on $default if no Dynamo item
            if pairing:
                expires = float(pairing.get("expires_at", 0))
                if time.time() > expires:
                    return _ok({"error": "token expired"}, 401)
                device_id = pairing.get("device_id") or device_id
                delete_pairing_token(token)
        save_connection(
            connection_id,
            device_id,
            {"platform": qs.get("platform", "android"), "authed": bool(token)},
        )
        return _ok()

    if route == "$disconnect":
        if connection_id:
            delete_connection(connection_id)
        return _ok()

    # $default — JSON messages from device
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _ok({"error": "invalid json"}, 400)

    msg_type = body.get("type") or body.get("action")
    token = body.get("token")
    device_id = body.get("device_id")

    if token:
        pairing = get_pairing_token(token)
        if not pairing:
            # Also allow already-consumed in-memory style: reject if unknown when USE_AWS
            if os.environ.get("USE_AWS_STORAGE", "").lower() == "true":
                # Token may have been consumed at $connect
                pass
            else:
                return _ok({"error": "invalid token"}, 401)
        else:
            expires = float(pairing.get("expires_at", 0))
            if time.time() > expires:
                delete_pairing_token(token)
                return _ok({"error": "token expired"}, 401)
            device_id = device_id or pairing.get("device_name") or connection_id
            delete_pairing_token(token)
            save_connection(
                connection_id,
                str(device_id),
                {"platform": body.get("platform", "android"), "authed": True},
            )

    if connection_id and device_id:
        save_connection(
            connection_id,
            str(device_id),
            {"platform": body.get("platform", "android"), "last_type": msg_type},
        )

    # Echo ack for pairing / heartbeat
    try:
        client = _mgmt_client(event)
        client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(
                {
                    "status": "connected",
                    "device_id": device_id,
                    "type": "ack",
                    "echo_type": msg_type,
                }
            ).encode("utf-8"),
        )
    except Exception as e:
        logger.warning("post_to_connection failed: %s", e)

    return _ok({"received": True})
