"""
Step-driven worker for dating/agent jobs.

EventBridge invokes this every minute. Each invocation:
1. Loads due jobs from DynamoDB
2. Executes ONE step (e.g. one swipe or one sequential message)
3. Schedules next_run_at with human-like gap
4. Never holds a long loop inside a single Lambda

This avoids Lambda's 15-minute hard limit for dating mode.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from decimal import Decimal
from typing import Any, Dict

from storage import get_device_connections, get_job, list_due_jobs, put_job

logger = logging.getLogger("mobilerun.step")
logger.setLevel(logging.INFO)


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _dynamo_safe(obj: Any) -> Any:
    """Convert floats to Decimal for DynamoDB."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _send_to_device(device_id: str, payload: Dict[str, Any]) -> bool:
    """Push a command to a paired device via API Gateway Management API."""
    endpoint = os.environ.get("WEBSOCKET_MANAGEMENT_ENDPOINT")
    if not endpoint:
        logger.warning("No WEBSOCKET_MANAGEMENT_ENDPOINT; dry-run step only")
        return False
    import boto3

    conns = get_device_connections(device_id)
    if not conns:
        logger.info("No active connections for device %s", device_id)
        return False
    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
    ok = False
    for c in conns:
        cid = c["connection_id"]
        try:
            client.post_to_connection(
                ConnectionId=cid, Data=json.dumps(payload).encode("utf-8")
            )
            ok = True
        except Exception as e:
            logger.warning("Failed to post to %s: %s", cid, e)
    return ok


def run_dating_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one dating step and update job counters."""
    job = _to_plain(job)
    state = job.setdefault("state", {})
    caps = job.get("caps", {})
    device_id = job.get("device_id", "")

    openers = int(state.get("openers_sent", 0))
    replies = int(state.get("replies_sent", 0))
    swipes = int(state.get("swipes_done", 0))
    opener_target = int(caps.get("opener_target", 75))
    global_max = int(caps.get("global_message_max", 500))
    swipe_cap = int(caps.get("swipe_cap", 50))
    reply_cap = int(caps.get("reply_cap", 50))

    total_msgs = openers + replies
    if total_msgs >= global_max or (openers >= opener_target and replies >= reply_cap):
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        return job

    # Prefer openers until target, then replies — always sequential (one per tick)
    if openers < opener_target:
        action = "opener"
        state["openers_sent"] = openers + 1
        gap = random.randint(30, 180)
    elif swipes < swipe_cap and random.random() < 0.3:
        action = "swipe"
        state["swipes_done"] = swipes + 1
        gap = random.randint(2, 8)
    else:
        action = "reply"
        state["replies_sent"] = replies + 1
        gap = random.randint(30, 180)

    state["last_action"] = action
    state["steps"] = int(state.get("steps", 0)) + 1
    job["state"] = state
    job["next_run_at"] = int(time.time()) + gap
    job["updated_at"] = int(time.time())

    _send_to_device(
        device_id,
        {
            "type": "command",
            "command": action,
            "job_id": job.get("job_id"),
            "params": {"dry_run": job.get("dry_run", False)},
        },
    )
    logger.info(
        "dating step job=%s action=%s openers=%s replies=%s swipes=%s next=%s",
        job.get("job_id"),
        action,
        state.get("openers_sent"),
        state.get("replies_sent"),
        state.get("swipes_done"),
        job["next_run_at"],
    )
    return job


def run_agent_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one agent task step."""
    job = _to_plain(job)
    state = job.setdefault("state", {})
    step = int(state.get("steps", 0))
    max_steps = int(job.get("max_steps", 15))
    if step >= max_steps:
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        return job

    state["steps"] = step + 1
    state["last_action"] = f"agent_step_{step + 1}"
    job["state"] = state
    job["next_run_at"] = int(time.time()) + random.randint(3, 10)
    job["updated_at"] = int(time.time())
    _send_to_device(
        job.get("device_id", ""),
        {
            "type": "run_task",
            "task_id": job.get("job_id"),
            "instruction": job.get("instruction", ""),
            "step": step + 1,
        },
    )
    return job


def process_job(job: Dict[str, Any]) -> None:
    kind = job.get("kind", "dating")
    if job.get("status") != "running":
        return
    if kind == "dating":
        updated = run_dating_step(job)
    else:
        updated = run_agent_step(job)
    put_job(_dynamo_safe(updated))


def handler(event: Dict[str, Any], context: Any):
    """EventBridge tick or direct invoke with job_id."""
    if event.get("job_id"):
        job = get_job(event["job_id"])
        if job:
            process_job(job)
            return {"processed": 1, "job_id": event["job_id"]}
        return {"processed": 0, "error": "job not found"}

    due = list_due_jobs(limit=10)
    processed = 0
    for job in due:
        try:
            process_job(job)
            processed += 1
        except Exception as e:
            logger.exception("job failed: %s", e)
    return {"processed": processed, "due": len(due)}
