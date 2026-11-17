"""Push JSON payloads to a phone over API Gateway WebSocket (cross-Lambda safe)."""

from __future__ import annotations

import json
import logging
import os
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
        if c.get("role") != "ui" and c.get("connection_id")
    ]
    # Newest first — prefer live reconnect over stale sockets
    conns.sort(key=lambda c: int(c.get("connected_at") or 0), reverse=True)
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


def push_to_device(device_id: str, payload: Dict[str, Any]) -> bool:
    """
    Deliver `payload` to the newest non-UI WebSocket for `device_id`.

    Prefer a single live socket — duplicate connections (common after Samsung
    reconnect) used to fan-out commands to dead sockets.
    """
    if not device_id:
        return False
    endpoint = os.environ.get("WEBSOCKET_MANAGEMENT_ENDPOINT") or ""
    if not endpoint:
        # Local/dev: caller may fall back to in-memory websockets
        return False

    import boto3

    conns = _sorted_device_conns(device_id)
    if not conns:
        logger.info("No WS connections for device %s", device_id)
        return False

    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
    data = json.dumps(payload).encode("utf-8")

    # Try newest first; on GoneException prune and try next
    try:
        from storage import delete_connection
    except ImportError:
        from backend.storage import delete_connection  # type: ignore

    for c in conns:
        cid = str(c.get("connection_id") or "")
        if not cid:
            continue
        try:
            client.post_to_connection(ConnectionId=cid, Data=data)
            # Best-effort: drop older duplicates after a successful send
            if len(conns) > 1:
                prune_stale_device_connections(device_id, keep_connection_id=cid)
            return True
        except Exception as e:
            logger.warning("post_to_connection %s failed: %s", cid, e)
            err = str(e).lower()
            if "gone" in err or "410" in err or "no longer exists" in err:
                try:
                    delete_connection(cid)
                except Exception:
                    pass
            continue
    return False


def device_is_reachable(device_id: str) -> bool:
    try:
        from storage import device_is_ws_connected
    except ImportError:
        from backend.storage import device_is_ws_connected  # type: ignore

    try:
        return bool(device_is_ws_connected(device_id))
    except Exception:
        return False
