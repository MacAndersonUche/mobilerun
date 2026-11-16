"""Push JSON payloads to a phone over API Gateway WebSocket (cross-Lambda safe)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger("mobilerun.push")


def push_to_device(device_id: str, payload: Dict[str, Any]) -> bool:
    """
    Deliver `payload` to every non-UI WebSocket connection for `device_id`.

    Uses CONNECTIONS_TABLE + WEBSOCKET_MANAGEMENT_ENDPOINT so HTTP Lambdas can
    reach phones that registered on the WebSocket Lambda (no in-memory WS).
    """
    if not device_id:
        return False
    endpoint = os.environ.get("WEBSOCKET_MANAGEMENT_ENDPOINT") or ""
    if not endpoint:
        # Local/dev: caller may fall back to in-memory websockets
        return False
    try:
        from storage import get_device_connections
    except ImportError:
        from backend.storage import get_device_connections  # type: ignore

    import boto3

    conns = get_device_connections(device_id)
    if not conns:
        logger.info("No WS connections for device %s", device_id)
        return False
    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
    data = json.dumps(payload).encode("utf-8")
    ok = False
    for c in conns:
        if c.get("role") == "ui":
            continue
        cid = c.get("connection_id")
        if not cid:
            continue
        try:
            client.post_to_connection(ConnectionId=cid, Data=data)
            ok = True
        except Exception as e:
            logger.warning("post_to_connection %s failed: %s", cid, e)
    return ok


def device_is_reachable(device_id: str) -> bool:
    try:
        from storage import device_is_ws_connected
    except ImportError:
        from backend.storage import device_is_ws_connected  # type: ignore

    try:
        return bool(device_is_ws_connected(device_id))
    except Exception:
        return False
