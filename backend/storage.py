"""AWS DynamoDB helpers for Lambda (pairing tokens, connections, jobs)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional  # List used by update_job_fields sets

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
    now = int(time.time())
    # Preserve role/owner/authed from meta; always refresh connected_at + TTL so
    # heartbeats keep device_is_ws_connected() true under the same connection_id.
    item = {
        "connection_id": connection_id,
        "device_id": device_id,
        "connected_at": now,
        "last_seen": now,
        "ttl": now + 86400,
        **(meta or {}),
    }
    # meta may override connected_at — force freshness for heartbeats
    item["connected_at"] = now
    item["last_seen"] = now
    item["device_id"] = device_id
    item["connection_id"] = connection_id
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
    """Full replace — prefer update_job_fields / acquire_job_lease for workers."""
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


# Must exceed worst-case step wall time (screenshot retries ~3×15s ≈ 45s+;
# observed 64.8s). Renew before slow RPCs; never rely on a single acquire.
DEFAULT_JOB_LEASE_S = 120


def acquire_job_lease(
    job_id: str,
    owner: str,
    *,
    ttl_s: int = DEFAULT_JOB_LEASE_S,
    now: Optional[int] = None,
) -> bool:
    """Conditional lease: only one worker owns a running job.

    Succeeds when status=='running' and (no lease, expired lease, or same owner).
    Returns False if another live owner holds the lease or status is not running.
    """
    if not job_id or not owner:
        return False
    now = int(now if now is not None else time.time())
    expiry = now + max(5, int(ttl_s))
    table = _table("JOBS_TABLE")
    if table is None:
        store = globals().setdefault("_LOCAL_JOBS", {})
        item = store.get(job_id)
        if not item:
            return False
        if str(item.get("status") or "") != "running":
            return False
        cur_owner = str(item.get("lease_owner") or "")
        cur_exp = int(item.get("lease_expires_at") or 0)
        if cur_owner and cur_owner != owner and cur_exp > now:
            return False
        item = dict(item)
        item["lease_owner"] = owner
        item["lease_expires_at"] = expiry
        item["updated_at"] = now
        store[job_id] = item
        return True
    # DynamoDB conditional update
    try:
        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=(
                "SET lease_owner = :owner, lease_expires_at = :exp, updated_at = :now"
            ),
            ConditionExpression=(
                "#s = :running AND ("
                "attribute_not_exists(lease_owner) OR lease_owner = :owner "
                "OR lease_expires_at <= :now OR attribute_not_exists(lease_expires_at)"
                ")"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":owner": owner,
                ":exp": expiry,
                ":now": now,
                ":running": "running",
            },
        )
        return True
    except Exception as e:
        # ConditionalCheckFailedException → skip; other errors log + skip
        name = type(e).__name__
        if (
            "ConditionalCheckFailed" not in name
            and "ConditionalCheckFailed" not in str(e)
        ):
            import logging

            logging.getLogger("mobilerun.storage").warning(
                "acquire_job_lease failed job=%s: %s", job_id, e
            )
        return False


def update_job_fields(
    job_id: str,
    fields: Dict[str, Any],
    *,
    owner: Optional[str] = None,
    require_running: bool = True,
    allow_terminal_status: bool = True,
) -> bool:
    """Targeted UpdateExpression — never full put_item.

    When require_running=True, refuses to write if status is no longer 'running'
    (so a cancel/stop cannot be overwritten by a stale worker). Terminal status
    transitions (completed/failed/stopped) are allowed when allow_terminal_status
    and the current status is still running.
    """
    if not job_id or not fields:
        return False
    now = int(time.time())
    payload = {k: v for k, v in fields.items() if k != "job_id"}
    payload["updated_at"] = now
    new_status = payload.get("status")

    table = _table("JOBS_TABLE")
    if table is None:
        store = globals().setdefault("_LOCAL_JOBS", {})
        item = store.get(job_id)
        if not item:
            return False
        cur_status = str(item.get("status") or "")
        if require_running and cur_status != "running":
            return False
        if owner:
            cur_owner = str(item.get("lease_owner") or "")
            cur_exp = int(item.get("lease_expires_at") or 0)
            if cur_owner and cur_owner != owner and cur_exp > now:
                return False
        if new_status and new_status != "running" and not allow_terminal_status:
            payload = {k: v for k, v in payload.items() if k != "status"}
        merged = dict(item)
        for k, v in payload.items():
            if k == "status" and cur_status != "running" and v == "running":
                continue  # never revive a cancelled job
            merged[k] = v
        store[job_id] = merged
        return True

    # Build UpdateExpression
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {":now": now}
    sets: List[str] = ["updated_at = :now"]
    for i, (k, v) in enumerate(payload.items()):
        if k == "updated_at":
            continue
        nk = f"#k{i}"
        vk = f":v{i}"
        names[nk] = k
        values[vk] = _dynamo_safe(v)
        sets.append(f"{nk} = {vk}")
    names["#s"] = "status"
    values[":running"] = "running"
    cond = "#s = :running"
    if owner:
        values[":owner"] = owner
        cond += (
            " AND (attribute_not_exists(lease_owner) OR lease_owner = :owner "
            "OR lease_expires_at <= :now OR attribute_not_exists(lease_expires_at))"
        )
    try:
        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression=cond,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return True
    except Exception as e:
        name = type(e).__name__
        if (
            "ConditionalCheckFailed" not in name
            and "ConditionalCheckFailed" not in str(e)
        ):
            import logging

            logging.getLogger("mobilerun.storage").warning(
                "update_job_fields failed job=%s: %s", job_id, e
            )
        return False


def save_job_progress(job: Dict[str, Any], owner: Optional[str] = None) -> bool:
    """Persist worker progress without clobbering a cancelled/stopped status.

    Never writes ``lease_owner`` / ``lease_expires_at`` — those are owned by
    ``acquire_job_lease``. Writing the values loaded at step start would restore
    a stale lease and steal/expire the live holder.
    """
    job_id = str(job.get("job_id") or "")
    if not job_id:
        return False
    # Only write mutable progress fields — never force status back to running
    fields: Dict[str, Any] = {}
    for k in (
        "state",
        "result",
        "error",
        "next_run_at",
        "completed_at",
        "dry_run",
        "kind",
        "device_id",
        "instruction",
        "max_steps",
    ):
        if k in job:
            fields[k] = job[k]
    status = job.get("status")
    if status and status != "running":
        fields["status"] = status
    return update_job_fields(
        job_id,
        fields,
        owner=owner,
        require_running=True,
        allow_terminal_status=True,
    )


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

    # Plain first: Dynamo round-trips already contain Decimal, and json.dumps
    # cannot serialize Decimal without a default.
    cleaned = _drop_none(_from_dynamo(obj))
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


def device_is_ws_connected(device_id: str, *, max_age_s: int = 90) -> bool:
    """True if Dynamo has a fresh authed non-UI socket for this device.

    Ignores pending_* placeholders and sockets whose connected_at is older
    than ``max_age_s`` (heartbeat should refresh within ~15s).
    """
    try:
        conns = get_device_connections(device_id)
    except Exception:
        return False
    now = int(time.time())
    for c in conns:
        if c.get("role") == "ui":
            continue
        did = str(c.get("device_id") or "")
        if did.startswith("pending_"):
            continue
        # Prefer authed phone sockets; allow unauthed only if very fresh
        authed = bool(c.get("authed"))
        connected_at = int(c.get("connected_at") or 0)
        age = now - connected_at if connected_at else 10_000
        if age > max_age_s:
            continue
        if authed or age <= 30:
            return True
    return False


def cleanup_stale_connections(
    *, pending_max_age_s: int = 120, stale_max_age_s: int = 300
) -> int:
    """Delete pending_* and aged-out connection rows. Best-effort.

    Authed device sockets are kept longer (15m) so a brief heartbeat gap or
    Lambda blip does not wipe the only live row while the phone still thinks
    it is Connected. pending_* placeholders still expire quickly.
    """
    import logging

    log = logging.getLogger("mobilerun.storage")
    table = _table("CONNECTIONS_TABLE")
    if table is None:
        return 0
    removed = 0
    now = int(time.time())
    authed_max_age_s = max(stale_max_age_s * 3, 900)
    try:
        # Scan is OK for small connection tables; TTL also cleans eventually
        resp = table.scan(Limit=200)
        items = list(resp.get("Items") or [])
        while resp.get("LastEvaluatedKey") and len(items) < 500:
            resp = table.scan(Limit=200, ExclusiveStartKey=resp["LastEvaluatedKey"])
            items.extend(resp.get("Items") or [])
    except Exception:
        return 0
    for c in items:
        cid = str(c.get("connection_id") or "")
        did = str(c.get("device_id") or "")
        connected_at = int(c.get("connected_at") or 0)
        age = now - connected_at if connected_at else 10_000
        drop = False
        reason = ""
        if did.startswith("pending_") and age > pending_max_age_s:
            drop = True
            reason = "pending_expired"
        elif c.get("role") != "ui" and age > stale_max_age_s and not c.get("authed"):
            drop = True
            reason = "unauthed_stale"
        elif c.get("authed") and age > authed_max_age_s:
            drop = True
            reason = "authed_stale"
        elif (not c.get("authed")) and age > max(stale_max_age_s * 2, 600):
            drop = True
            reason = "unauthed_max"
        if drop and cid:
            try:
                delete_connection(cid)
                removed += 1
                log.info(
                    "cleanup_stale dropped connection=%s device=%s age=%ss reason=%s",
                    cid,
                    did,
                    age,
                    reason,
                )
            except Exception:
                pass
    return removed


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
