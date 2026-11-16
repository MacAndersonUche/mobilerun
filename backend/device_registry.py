"""Helpers to resolve device ownership across HTTP + WebSocket Lambdas."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mobilerun.devices")


def resolve_owner_from_message(
    body: Dict[str, Any],
) -> tuple[Optional[str], Optional[str], Dict[str, Any]]:
    """
    Resolve (owner, device_id, session_meta) from a WS register/heartbeat payload.
    Prefers session_token, then JWT auth_token/jwt.
    """
    session_token = body.get("session_token")
    if session_token:
        try:
            from storage import get_device_session
        except ImportError:
            from backend.storage import get_device_session  # type: ignore

        meta = get_device_session(str(session_token)) or {}
        owner = (meta.get("owner") or "").lower() or None
        device_id = body.get("device_id") or meta.get("device_id")
        return owner, (str(device_id) if device_id else None), meta

    jwt = body.get("auth_token") or body.get("jwt")
    if jwt:
        try:
            from backend.auth import decode_bearer
        except ImportError:
            try:
                from auth import decode_bearer  # type: ignore
            except ImportError:
                decode_bearer = None  # type: ignore
        if decode_bearer:
            try:
                claims = decode_bearer(str(jwt))
                owner = (
                    claims.get("email")
                    or claims.get("user_id")
                    or claims.get("sub")
                    or ""
                ).lower() or None
                device_id = body.get("device_id") or claims.get("device_id")
                return (
                    owner,
                    (str(device_id) if device_id else None),
                    {
                        "owner": owner,
                        "from": "jwt",
                    },
                )
            except Exception as e:
                logger.warning("jwt decode failed: %s", e)

    return None, (str(body["device_id"]) if body.get("device_id") else None), {}


def upsert_from_ws(
    *,
    owner: Optional[str],
    device_id: str,
    name: str = "",
    platform: str = "android",
    route: Optional[str] = None,
    latency_ms: Optional[float] = None,
    permissions: Optional[Dict[str, Any]] = None,
    connection_type: str = "websocket",
) -> None:
    if not owner or not device_id:
        return
    try:
        from storage import upsert_owned_device
    except ImportError:
        from backend.storage import upsert_owned_device  # type: ignore

    row = {
        "device_id": device_id,
        "name": name or device_id,
        "platform": platform or "android",
        "connected": True,
        "connection_type": connection_type,
        "route": route,
        "latency_ms": latency_ms,
        "permissions": permissions,
        "last_seen": datetime.now().isoformat(),
        "owner": owner,
    }
    upsert_owned_device(owner, row)


def merge_device_lists(
    memory: Dict[str, Dict[str, Any]],
    owner: Optional[str],
) -> List[Dict[str, Any]]:
    """Merge in-memory + persisted devices; mark connected via WS connections table."""
    try:
        from storage import device_is_ws_connected, list_owned_devices
    except ImportError:
        from backend.storage import device_is_ws_connected, list_owned_devices  # type: ignore

    by_id: Dict[str, Dict[str, Any]] = {}
    if owner:
        for d in list_owned_devices(owner):
            by_id[str(d.get("device_id"))] = dict(d)
    for did, d in (memory or {}).items():
        if owner:
            o = (d.get("owner") or "").lower()
            if o and o != owner.lower():
                continue
        cur = by_id.get(did) or {}
        cur.update(d)
        cur["device_id"] = did
        by_id[did] = cur

    import os

    use_aws = os.environ.get("USE_AWS_STORAGE", "false").lower() == "true"
    out = []
    for did, d in by_id.items():
        row = dict(d)
        ws_up = False
        try:
            ws_up = device_is_ws_connected(did)
        except Exception:
            ws_up = False
        # Prefer live WS truth on AWS; fall back to memory flag locally
        if ws_up:
            row["connected"] = True
            row["connection_type"] = row.get("connection_type") or "websocket"
        elif use_aws:
            # Stale "connected" rows in SETTINGS must not lie once the socket is gone
            row["connected"] = False
        elif row.get("connected") is None:
            row["connected"] = bool(memory.get(did, {}).get("connected"))
        out.append(row)
    out.sort(key=lambda x: str(x.get("last_seen") or ""), reverse=True)
    return out
