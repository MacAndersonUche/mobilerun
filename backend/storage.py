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


# --- Pairing tokens (settings table with key prefix) ---


def save_pairing_token(token: str, data: Dict[str, Any]) -> None:
    table = _table("SETTINGS_TABLE")
    if table is None:
        return
    item = {
        "key": f"pairing:{token}",
        **{k: v for k, v in data.items() if k != "key"},
        "ttl": int(data.get("expires_at", time.time() + 600)),
    }
    table.put_item(Item=item)


def get_pairing_token(token: str) -> Optional[Dict[str, Any]]:
    table = _table("SETTINGS_TABLE")
    if table is None:
        return None
    resp = table.get_item(Key={"key": f"pairing:{token}"})
    return resp.get("Item")


def delete_pairing_token(token: str) -> None:
    table = _table("SETTINGS_TABLE")
    if table is None:
        return
    table.delete_item(Key={"key": f"pairing:{token}"})


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
        return
    table.put_item(Item=job)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    table = _table("JOBS_TABLE")
    if table is None:
        return None
    resp = table.get_item(Key={"job_id": job_id})
    return resp.get("Item")


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
                "data": data,
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
        return data if isinstance(data, dict) else None

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
