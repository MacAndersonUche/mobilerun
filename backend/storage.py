"""AWS DynamoDB helpers for Lambda (pairing tokens, connections, jobs)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

USE_AWS = os.environ.get("USE_AWS_STORAGE", "false").lower() == "true"

_dynamodb = None


def _table(name_env: str):
    global _dynamodb
    if not USE_AWS:
        return None
    table_name = os.environ.get(name_env)
    if not table_name:
        return None
    if _dynamodb is None:
        import boto3

        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(table_name)


# --- Pairing tokens (hashed at rest; never store plaintext token) ---


def hash_secret(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def save_pairing_token(token: str, data: Dict[str, Any]) -> None:
    """Persist pairing payload keyed by sha256(token). Plaintext token is never stored."""
    payload = {k: v for k, v in (data or {}).items() if k not in ("key", "token")}
    payload["_ttl_seconds"] = max(
        60,
        int(float(payload.get("expires_at") or time.time() + 600) - time.time()) + 30,
    )
    _settings_put(f"pairing:{hash_secret(token)}", payload)


def get_pairing_token(token: str) -> Optional[Dict[str, Any]]:
    return _settings_get(f"pairing:{hash_secret(token)}")


def delete_pairing_token(token: str) -> None:
    key = f"pairing:{hash_secret(token)}"
    table = _table("SETTINGS_TABLE")
    if table is not None:
        table.delete_item(Key={"key": key})
        return
    import json
    from pathlib import Path

    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    safe = key.replace(":", "_").replace("/", "_")
    path = root / f"{safe}.json"
    if path.exists():
        path.unlink()


def revoke_device_session(session_token: str) -> None:
    """Invalidate a long-lived device credential."""
    key = f"session:{session_token}"
    table = _table("SETTINGS_TABLE")
    if table is not None:
        table.delete_item(Key={"key": key})
        return
    from pathlib import Path

    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    safe = key.replace(":", "_").replace("/", "_")
    path = root / f"{safe}.json"
    if path.exists():
        path.unlink()


def remove_owned_device(owner: str, device_id: str) -> bool:
    owner_key = (owner or "").strip().lower()
    if not owner_key or not device_id:
        return False
    blob = get_user_setting(owner_key, "devices") or {"devices": {}}
    devices = dict(blob.get("devices") or {})
    if device_id not in devices:
        return False
    devices.pop(device_id, None)
    save_user_setting(owner_key, "devices", {"devices": devices})
    return True


# --- WebSocket connections ---


def save_connection(
    connection_id: str, device_id: str, meta: Optional[Dict[str, Any]] = None
) -> None:
    table = _table("CONNECTIONS_TABLE")
    if table is None:
        return
    item = {
        "connection_id": connection_id,
        "device_id": device_id,
        "connected_at": int(time.time()),
        "ttl": int(time.time()) + 86400,
        **(meta or {}),
    }
    table.put_item(Item=item)


def delete_connection(connection_id: str) -> None:
    table = _table("CONNECTIONS_TABLE")
    if table is None:
        return
    table.delete_item(Key={"connection_id": connection_id})


def get_connection(connection_id: str) -> Optional[Dict[str, Any]]:
    table = _table("CONNECTIONS_TABLE")
    if table is None:
        return None
    resp = table.get_item(Key={"connection_id": connection_id})
    return resp.get("Item")


def get_device_connections(device_id: str) -> List[Dict[str, Any]]:
    table = _table("CONNECTIONS_TABLE")
    if table is None:
        return []
    resp = table.query(
        IndexName="device-index",
        KeyConditionExpression="device_id = :d",
        ExpressionAttributeValues={":d": device_id},
    )
    return resp.get("Items", [])


# --- Step jobs ---


def put_job(job: Dict[str, Any]) -> None:
    table = _table("JOBS_TABLE")
    if table is None:
        # Local / unit-test fallback: keep an in-process map so tick/activity work
        store = globals().setdefault("_LOCAL_JOBS", {})
        store[str(job.get("job_id") or "")] = dict(job)
        return
    table.put_item(Item=_dynamo_safe(job))


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    table = _table("JOBS_TABLE")
    if table is None:
        store = globals().get("_LOCAL_JOBS") or {}
        item = store.get(job_id)
        return dict(item) if item else None
    resp = table.get_item(Key={"job_id": job_id}, ConsistentRead=True)
    item = resp.get("Item")
    return _from_dynamo(item) if item else None


def list_due_jobs(
    now_ts: Optional[int] = None, limit: int = 20
) -> List[Dict[str, Any]]:
    table = _table("JOBS_TABLE")
    if table is None:
        return []
    now_ts = now_ts or int(time.time())
    # Query running jobs due for next step
    resp = table.query(
        IndexName="status-index",
        KeyConditionExpression="#s = :running AND next_run_at <= :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":running": "running", ":now": now_ts},
        Limit=limit,
    )
    return resp.get("Items", [])


def list_recent_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """Recent agent/dating jobs across running/completed/failed (for History UI)."""
    table = _table("JOBS_TABLE")
    if table is None:
        return []
    out: List[Dict[str, Any]] = []
    for status in ("running", "completed", "failed", "stopped", "paused"):
        try:
            resp = table.query(
                IndexName="status-index",
                KeyConditionExpression="#s = :st",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":st": status},
                Limit=min(limit, 40),
                ScanIndexForward=False,
            )
            out.extend(resp.get("Items") or [])
        except Exception:
            continue
    out.sort(
        key=lambda j: int(j.get("updated_at") or j.get("created_at") or 0), reverse=True
    )
    return out[:limit]


# --- Per-user settings (dating openers library, etc.) ---


def save_user_setting(user_id: str, name: str, data: Dict[str, Any]) -> bool:
    """Persist a per-user blob to SETTINGS_TABLE (or local JSON when offline)."""
    import json
    from pathlib import Path

    key = f"user:{user_id}:{name}"
    table = _table("SETTINGS_TABLE")
    if table is not None:
        table.put_item(
            Item={
                "key": key,
                "user_id": user_id,
                "name": name,
                "data": _dynamo_safe(data),
                "updated_at": int(time.time()),
            }
        )
        return True

    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{user_id.replace('/', '_')}.json"
    path.write_text(json.dumps({"key": key, "data": data}, indent=2))
    return True


def get_user_setting(user_id: str, name: str) -> Optional[Dict[str, Any]]:
    import json
    from pathlib import Path

    key = f"user:{user_id}:{name}"
    table = _table("SETTINGS_TABLE")
    if table is not None:
        resp = table.get_item(Key={"key": key})
        item = resp.get("Item")
        if not item:
            return None
        data = item.get("data")
        if not isinstance(data, dict):
            return None
        return _from_dynamo(data)

    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    path = root / f"{name}_{user_id.replace('/', '_')}.json"
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text())
        data = blob.get("data") if isinstance(blob, dict) else None
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# --- Device registry + sessions (survive Lambda cold starts) ---


def _dynamo_safe(obj: Any) -> Any:
    """DynamoDB rejects float and None; convert recursively for put_item."""
    import json
    from decimal import Decimal

    def _drop_none(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: _drop_none(v) for k, v in o.items() if v is not None}
        if isinstance(o, list):
            return [_drop_none(v) for v in o if v is not None]
        return o

    cleaned = _drop_none(obj)
    return json.loads(json.dumps(cleaned), parse_float=Decimal)


def _from_dynamo(obj: Any) -> Any:
    """Decimal → int/float for app code."""
    from decimal import Decimal

    if isinstance(obj, list):
        return [_from_dynamo(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    return obj


def _settings_put(key: str, data: Dict[str, Any]) -> bool:
    import json
    from pathlib import Path

    table = _table("SETTINGS_TABLE")
    if table is not None:
        safe_data = _dynamo_safe(data)
        table.put_item(
            Item={
                "key": key,
                "data": safe_data,
                "updated_at": int(time.time()),
                "ttl": int(time.time()) + int(data.get("_ttl_seconds") or 86400 * 30),
            }
        )
        return True
    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    root.mkdir(parents=True, exist_ok=True)
    safe = key.replace(":", "_").replace("/", "_")
    (root / f"{safe}.json").write_text(json.dumps({"key": key, "data": data}, indent=2))
    return True


def _settings_get(key: str) -> Optional[Dict[str, Any]]:
    import json
    from pathlib import Path

    table = _table("SETTINGS_TABLE")
    if table is not None:
        resp = table.get_item(Key={"key": key})
        item = resp.get("Item")
        if not item:
            return None
        data = item.get("data")
        if not isinstance(data, dict):
            return None
        return _from_dynamo(data)
    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    safe = key.replace(":", "_").replace("/", "_")
    path = root / f"{safe}.json"
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text())
        data = blob.get("data") if isinstance(blob, dict) else None
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_device_session(session_token: str, meta: Dict[str, Any]) -> None:
    payload = dict(meta or {})
    payload["_ttl_seconds"] = 86400 * 90
    _settings_put(f"session:{session_token}", payload)


def get_device_session(session_token: str) -> Optional[Dict[str, Any]]:
    return _settings_get(f"session:{session_token}")


def upsert_owned_device(owner: str, device: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a device under the owning account (email/sub)."""
    owner_key = (owner or "").strip().lower()
    if not owner_key:
        raise ValueError("owner required")
    device_id = str(device.get("device_id") or "").strip()
    if not device_id:
        raise ValueError("device_id required")
    blob = get_user_setting(owner_key, "devices") or {"devices": {}}
    devices = dict(blob.get("devices") or {})
    prev = dict(devices.get(device_id) or {})
    prev.update({k: v for k, v in device.items() if v is not None})
    prev["device_id"] = device_id
    prev["owner"] = owner_key
    prev["updated_at"] = int(time.time())
    devices[device_id] = prev
    save_user_setting(owner_key, "devices", {"devices": devices})
    return prev


def list_owned_devices(owner: str) -> List[Dict[str, Any]]:
    owner_key = (owner or "").strip().lower()
    if not owner_key:
        return []
    blob = get_user_setting(owner_key, "devices") or {}
    return list((blob.get("devices") or {}).values())


def device_is_ws_connected(device_id: str) -> bool:
    """True if Dynamo connections table has a non-UI socket for this device."""
    try:
        conns = get_device_connections(device_id)
    except Exception:
        return False
    for c in conns:
        if c.get("role") != "ui":
            return True
    return False


# --- Device-code linking (survive Lambda cold starts) ---


def save_device_link_code(key: str, meta: Dict[str, Any]) -> None:
    payload = dict(meta or {})
    payload["_ttl_seconds"] = max(
        60,
        int(float(payload.get("expires_at") or time.time() + 600) - time.time()) + 60,
    )
    _settings_put(f"devicelink:{key}", payload)


def get_device_link_code(key: str) -> Optional[Dict[str, Any]]:
    return _settings_get(f"devicelink:{key}")


def delete_device_link_code(key: str) -> None:
    table = _table("SETTINGS_TABLE")
    if table is not None:
        table.delete_item(Key={"key": f"devicelink:{key}"})
        return
    import json
    from pathlib import Path

    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    safe = f"devicelink_{key}".replace(":", "_").replace("/", "_")
    path = root / f"{safe}.json"
    if path.exists():
        path.unlink()
