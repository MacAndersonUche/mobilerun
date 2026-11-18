"""Push JSON payloads to a phone over API Gateway WebSocket (cross-Lambda safe)."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mobilerun.push")


def _try_local_memory_push(device_id: str, payload: Dict[str, Any]) -> bool:
    """Deliver via in-process FastAPI WebSocket (local uvicorn / emulator e2e).

    Must be callable from a worker thread while the uvicorn event loop stays free
    to process the phone's RPC response — never block the loop waiting on RPC.
    """
    if not device_id:
        return False
    for mod_name in ("main", "backend.main"):
        try:
            main_mod = importlib.import_module(mod_name)
        except Exception:
            continue
        sockets = getattr(main_mod, "device_websockets", None) or {}
        ws = sockets.get(device_id)
        if ws is None:
            continue
        loop = getattr(main_mod, "_app_loop", None)
        if loop is None or not loop.is_running():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    loop = asyncio.get_event_loop()
                except Exception:
                    loop = None
        if loop is None or not loop.is_running():
            logger.warning(
                "local WS for %s found but no running event loop to schedule send",
                device_id,
            )
            continue

        async def _send() -> None:
            await ws.send_json(payload)

        try:
            # Always schedule on the uvicorn loop from this (worker) thread.
            fut = asyncio.run_coroutine_threadsafe(_send(), loop)
            fut.result(timeout=15)
            return True
        except Exception as e:
            logger.warning("local in-memory send to %s failed: %s", device_id, e)
            return False
    return False


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
        # Local/dev (emulator bench): push over in-memory device_websockets
        return _try_local_memory_push(device_id, payload)

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
    """True if AWS has a fresh authed socket OR local in-memory WS is up."""
    if not device_id:
        return False
    try:
        from storage import device_is_ws_connected
    except ImportError:
        from backend.storage import device_is_ws_connected  # type: ignore

    try:
        if bool(device_is_ws_connected(device_id)):
            return True
    except Exception:
        pass

    # Local FastAPI (emulator e2e / self-hosted) keeps sockets in-process
    for mod_name in ("main", "backend.main"):
        try:
            import importlib

            main_mod = importlib.import_module(mod_name)
        except Exception:
            continue
        sockets = getattr(main_mod, "device_websockets", None) or {}
        if device_id in sockets:
            return True
        connected = getattr(main_mod, "connected_devices", None) or {}
        row = connected.get(device_id) or {}
        if row.get("connected"):
            return True
    return False


def reconnect_wait_budget(device_id: str, requested: float) -> float:
    """How long to wait for a phone reconnect before failing a command.

    Full budget only when API Gateway management is configured AND the device
    had a recent socket (typical mid-task drop). Local/dev and cold devices
    fail fast so CI does not burn 60s per RPC.
    """
    requested = max(0.0, float(requested or 0.0))
    if requested <= 0 or device_is_reachable(device_id):
        return 0.0
    endpoint = os.environ.get("WEBSOCKET_MANAGEMENT_ENDPOINT") or ""
    if not endpoint:
        return min(1.5, requested)
    try:
        from storage import get_device_connections
    except ImportError:
        from backend.storage import get_device_connections  # type: ignore

    try:
        conns = get_device_connections(device_id) or []
    except Exception:
        conns = []
    now = time.time()
    for c in conns:
        if c.get("role") == "ui":
            continue
        if str(c.get("device_id") or "").startswith("pending_"):
            continue
        age = now - float(c.get("connected_at") or 0)
        # Saw a real socket in the last 5 minutes → allow full reconnect wait
        if age <= 300:
            return requested
    return min(3.0, requested)


def wait_until_reachable(device_id: str, timeout_s: float = 60.0) -> bool:
    """Poll until an authed WS appears or timeout. Used mid-task after drops."""
    budget = reconnect_wait_budget(device_id, timeout_s)
    if budget <= 0:
        return device_is_reachable(device_id)
    deadline = time.time() + budget
    while time.time() < deadline:
        if device_is_reachable(device_id):
            return True
        time.sleep(0.5 if budget <= 5 else 1.0)
    return device_is_reachable(device_id)
