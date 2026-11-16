"""Request/response RPC to a paired phone over API Gateway WebSocket + Dynamo.

Step worker (or HTTP Lambda) posts a command with request_id; the WS Lambda
stores the phone's `response` under SETTINGS; we poll until it arrives.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("mobilerun.rpc")


def _put_pending(request_id: str) -> None:
    try:
        from storage import _settings_put
    except ImportError:
        from backend.storage import _settings_put  # type: ignore

    _settings_put(
        f"rpc:{request_id}",
        {"status": "pending", "created_at": int(time.time()), "_ttl_seconds": 120},
    )


def store_rpc_response(request_id: str, payload: Dict[str, Any]) -> None:
    """Called from ws_handler when the phone replies."""
    if not request_id:
        return
    try:
        from storage import _settings_put
    except ImportError:
        from backend.storage import _settings_put  # type: ignore

    data = {
        "status": "done",
        "error": payload.get("error"),
        "result": payload.get("result"),
        "updated_at": int(time.time()),
        "_ttl_seconds": 120,
    }
    _settings_put(f"rpc:{request_id}", data)


def _get_rpc(request_id: str) -> Optional[Dict[str, Any]]:
    try:
        from storage import _settings_get
    except ImportError:
        from backend.storage import _settings_get  # type: ignore

    return _settings_get(f"rpc:{request_id}")


def call_device(
    device_id: str,
    command: str,
    params: Optional[Dict[str, Any]] = None,
    timeout_s: float = 25.0,
) -> Any:
    """Send a command to the phone and wait for its response (or raise)."""
    try:
        from device_push import push_to_device, device_is_reachable
    except ImportError:
        from backend.device_push import push_to_device, device_is_reachable  # type: ignore

    if not device_is_reachable(device_id):
        raise RuntimeError("Device offline — no live WebSocket")

    request_id = f"rpc_{uuid.uuid4().hex[:16]}"
    _put_pending(request_id)
    payload = {
        "type": "command",
        "command": command,
        "request_id": request_id,
        "params": params or {},
    }
    if not push_to_device(device_id, payload):
        raise RuntimeError("Failed to push command to device WebSocket")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        row = _get_rpc(request_id) or {}
        if row.get("status") == "done":
            if row.get("error"):
                raise RuntimeError(str(row["error"]))
            return row.get("result")
        time.sleep(0.35)

    raise TimeoutError(f"Command {command} timed out after {timeout_s}s")
