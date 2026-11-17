"""Push JSON payloads to a phone over API Gateway WebSocket (cross-Lambda safe)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mobilerun.push")


def _sorted_device_conns(device_id: str) -> List[Dict[str, Any]]:
    try:
        from storage import get_device_connections
    except ImportError:
        from backend.storage import get_device_connections  # type: ignore

    conns = [
        c
        for c in (get_device_connections(device_id) or [])
        if c.get("role") != "ui"
        and c.get("connection_id")
        and not str(c.get("device_id") or "").startswith("pending_")
    ]

    # Authed + newest first — prefer live reconnect over stale sockets
    def _key(c: Dict[str, Any]) -> tuple:
        return (
            1 if c.get("authed") else 0,
            int(c.get("connected_at") or 0),
        )

    conns.sort(key=_key, reverse=True)
    return conns


def prune_stale_device_connections(
    device_id: str, keep_connection_id: Optional[str] = None
) -> int:
    """Drop older non-UI sockets for a device so commands hit one live phone."""
    try:
        from storage import delete_connection
    except ImportError:
        from backend.storage import delete_connection  # type: ignore

    conns = _sorted_device_conns(device_id)
    if not conns:
        return 0
    keep = keep_connection_id or str(conns[0].get("connection_id") or "")
    removed = 0
    for c in conns:
        cid = str(c.get("connection_id") or "")
        if not cid or cid == keep:
            continue
        try:
            delete_connection(cid)
            removed += 1
            logger.info(
                "pruned stale WS connection %s for device %s (kept %s)",
                cid,
                device_id,
                keep,
            )
        except Exception as e:
            logger.warning("prune connection %s failed: %s", cid, e)
    return removed


def _is_gone(exc: BaseException) -> bool:
    name = type(exc).__name__
    if "Gone" in name:
        return True
    err = str(exc).lower()
    return "gone" in err or "410" in err or "no longer exists" in err


def push_to_device(
    device_id: str,
    payload: Dict[str, Any],
    *,
    wait_reconnect_s: float = 0.0,
) -> bool:
    """
    Deliver `payload` to the newest authed non-UI WebSocket for `device_id`.

    Prefer a single live socket — duplicate connections (common after Samsung
    reconnect) used to fan-out commands to dead sockets.

    When ``wait_reconnect_s`` > 0, if the first push round fails (Gone /
    empty), wait and retry looking up the newest connection until the budget
    expires — phones often reconnect within a few seconds mid-task.
    """
    if not device_id:
        return False
    endpoint = os.environ.get("WEBSOCKET_MANAGEMENT_ENDPOINT") or ""
    if not endpoint:
        # Local/dev: caller may fall back to in-memory websockets
        return False

    import boto3

    try:
        from storage import delete_connection, cleanup_stale_connections
    except ImportError:
        from backend.storage import (  # type: ignore
            delete_connection,
            cleanup_stale_connections,
        )

    # Opportunistic cleanup of pending_* placeholders
    try:
        cleanup_stale_connections()
    except Exception:
        pass

    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
    data = json.dumps(payload).encode("utf-8")
    deadline = time.time() + max(0.0, float(wait_reconnect_s or 0))
    attempt = 0

    while True:
        attempt += 1
        conns = _sorted_device_conns(device_id)
        if not conns:
            logger.info(
                "No WS connections for device %s (attempt %s)", device_id, attempt
            )
        for c in conns:
            cid = str(c.get("connection_id") or "")
            if not cid:
                continue
            try:
                client.post_to_connection(ConnectionId=cid, Data=data)
                if len(conns) > 1:
                    prune_stale_device_connections(device_id, keep_connection_id=cid)
                return True
            except Exception as e:
                logger.warning("post_to_connection %s failed: %s", cid, e)
                if _is_gone(e):
                    try:
                        delete_connection(cid)
                    except Exception:
                        pass
                continue

        if time.time() >= deadline:
            return False
        # Brief pause then re-query Dynamo for a fresh authed reconnect
        time.sleep(min(2.0, max(0.4, deadline - time.time())))


def device_is_reachable(device_id: str) -> bool:
    try:
        from storage import device_is_ws_connected
    except ImportError:
        from backend.storage import device_is_ws_connected  # type: ignore

    try:
        return bool(device_is_ws_connected(device_id))
    except Exception:
        return False


def wait_until_reachable(device_id: str, timeout_s: float = 60.0) -> bool:
    """Poll until an authed WS appears or timeout. Used mid-task after drops."""
    deadline = time.time() + max(0.0, float(timeout_s))
    while time.time() < deadline:
        if device_is_reachable(device_id):
            return True
        time.sleep(1.0)
    return device_is_reachable(device_id)
