"""
Step-driven worker for dating/agent jobs.

EventBridge invokes this every minute. Each invocation:
1. Loads due jobs from DynamoDB
2. Executes ONE step (e.g. one swipe or one sequential message)
3. Schedules next_run_at with human-like (log-normal) gap — never fixed
4. Never holds a long loop inside a single Lambda
5. Honours safety auto-pause (skips work until Mac resumes)

This avoids Lambda's 15-minute hard limit for dating mode.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from decimal import Decimal
from typing import Any, Dict, Optional

try:
    from storage import get_device_connections, get_job, list_due_jobs, put_job
except ImportError:
    from backend.storage import (  # type: ignore
        get_device_connections,
        get_job,
        list_due_jobs,
        put_job,
    )

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
    """Convert floats to Decimal for DynamoDB (plain first — obj may already have Decimals)."""
    return json.loads(json.dumps(_to_plain(obj)), parse_float=Decimal)


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
                ConnectionId=cid,
                Data=json.dumps(_to_plain(payload)).encode("utf-8"),
            )
            ok = True
        except Exception as e:
            logger.warning("Failed to post to %s: %s", cid, e)
    return ok


def _humanizer_for_job(job: Dict[str, Any]):
    from mobilerun.agent.humanizer import AgentMode, Humanizer, HumanizerConfig

    speed = (
        job.get("speed_preset")
        or job.get("state", {}).get("speed_preset")
        or "balanced"
    )
    cfg_data = job.get("humanizer") or {}
    if isinstance(cfg_data, dict) and cfg_data:
        cfg = HumanizerConfig.from_dict({**cfg_data, "preset": speed, "mode": "dating"})
    else:
        cfg = HumanizerConfig.from_preset(speed, AgentMode.DATING)
    seed = job.get("job_id") or str(time.time())
    rng = random.Random(f"{seed}:{job.get('state', {}).get('steps', 0)}")
    return Humanizer(config=cfg, _rng=rng)


def _compose_for_step(
    job: Dict[str, Any],
    state: Dict[str, Any],
    *,
    action: str,
    rng,
) -> Dict[str, Any]:
    """Compose opener via templates (no LLM) or reply via AI stub/callable."""
    try:
        from mobilerun.dating.openers import (
            compose_dating_message,
            merge_with_defaults,
        )
    except Exception:
        logger.exception("opener library import failed")
        return {}

    raw_lib = job.get("opener_library") or state.get("opener_library")
    lib = merge_with_defaults(raw_lib if isinstance(raw_lib, dict) else None)
    # HARD RULE: message bodies come ONLY from the template/message bank —
    # never AI-generated or rewritten copy (navigation may still use LLM elsewhere).
    lib.opener_mode = "templates"
    package = (
        state.get("current_app")
        or job.get("current_app")
        or (state.get("app_order") or [""])[0]
        or ""
    )
    match_id = state.get("current_match_id") or f"match_{state.get('steps', 0)}"
    profile = state.get("current_profile_name") or ""

    # Explicit user/bank override on the job wins
    forced = (
        job.get("message_text")
        or job.get("bank_text")
        or job.get("selected_message")
        or state.get("message_text")
        or state.get("bank_text")
    )
    if forced:
        text = str(forced).strip()
        state["last_composed_text"] = text
        state["last_composed_source"] = "job_bank_or_user"
        return {
            "text": text,
            "source": "job_bank_or_user",
            "used_llm": False,
            "is_opener": action == "opener",
            "ai_calls": 0,
        }

    try:
        # Always template path (is_opener=True) so replies also use the bank
        result = compose_dating_message(
            is_opener=True,
            lib=lib,
            match_id=str(match_id),
            package_name=str(package),
            profile_name=profile or None,
            rng=rng,
            ai_callable=None,
            inbound_preview="",
        )
        result["ai_calls"] = 0
        result["used_llm"] = False
        result["source"] = result.get("source") or "template"
        # Persist rotation state back onto job for subsequent ticks
        state["opener_library"] = lib.to_dict()
        job["opener_library"] = lib.to_dict()
        state["last_composed_text"] = result.get("text")
        state["last_composed_source"] = "template"
        return result
    except Exception:
        logger.exception("compose for step failed action=%s", action)
        return {}


def _safety_blocked(job: Dict[str, Any]) -> bool:
    """Skip work while safety pause is active for this job's app / all."""
    if job.get("safety_paused"):
        return True
    try:
        from mobilerun.safety.runtime import get_safety_state

        st = get_safety_state()
        app = job.get("current_app") or job.get("state", {}).get("current_app")
        return st.is_paused(app)
    except Exception:
        return False


def run_dating_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one dating step and update job counters."""
    job = _to_plain(job)
    state = job.setdefault("state", {})
    caps = job.get("caps", {})
    device_id = job.get("device_id", "")

    if _safety_blocked(job):
        job["status"] = "paused"
        state["last_action"] = "safety_pause"
        job["state"] = state
        job["next_run_at"] = int(time.time()) + 60
        job["updated_at"] = int(time.time())
        logger.warning("dating step skipped — safety pause job=%s", job.get("job_id"))
        return job

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

    humanizer = _humanizer_for_job(job)

    # Prefer openers until target, then replies — always sequential (one per tick)
    # Randomise action choice slightly when both swipe and reply are eligible
    dry = bool(job.get("dry_run", False))
    if openers < opener_target:
        action = "opener"
        state["openers_sent"] = openers + 1
        gap = humanizer.sample_message_gap_seconds()
    elif swipes < swipe_cap and humanizer._rng.random() < 0.3:
        action = "swipe"
        state["swipes_done"] = swipes + 1
        gap = humanizer.sample_swipe_step_gap_seconds()
    else:
        action = "reply"
        state["replies_sent"] = replies + 1
        gap = humanizer.sample_message_gap_seconds()

    # Dry-run / emulator verification: short ticks so activity UI updates live
    if dry:
        gap = 2 + humanizer._rng.random() * 2
    gap_i = max(1, int(round(gap)))
    state["last_action"] = action
    state["last_gap_s"] = gap_i
    state["steps"] = int(state.get("steps", 0)) + 1
    # Shuffle next app hint when multiple apps configured
    apps = job.get("apps") or state.get("apps") or []
    if apps:
        ordered = humanizer.ordered_apps(apps)
        state["app_order"] = list(ordered)
        state["current_app"] = ordered[0] if ordered else state.get("current_app")

    # Compose opener from templates (no LLM) or leave reply to AI path
    composed: Dict[str, Any] = {}
    if action in ("opener", "reply"):
        composed = _compose_for_step(job, state, action=action, rng=humanizer._rng)
        if composed:
            state["last_message"] = composed.get("text")
            state["last_message_source"] = composed.get("source")
            state["last_template_id"] = composed.get("template_id")
            state["last_used_llm"] = bool(composed.get("used_llm"))

    job["state"] = state
    job["next_run_at"] = int(time.time()) + gap_i
    job["updated_at"] = int(time.time())

    params: Dict[str, Any] = {"dry_run": dry}
    if composed:
        params["message"] = composed.get("text")
        params["source"] = composed.get("source")
        params["used_llm"] = composed.get("used_llm")
        if composed.get("template_id"):
            params["template_id"] = composed["template_id"]

    # Live activity: capture screen before/after command for History UI
    try:
        from activity_log import append_step, capture_device_context, store_screenshot
    except ImportError:
        from backend.activity_log import (  # type: ignore
            append_step,
            capture_device_context,
            store_screenshot,
        )

    ctx = capture_device_context(str(device_id))
    pkg = (
        str(ctx.get("package") or "")
        or str(state.get("current_app") or "")
        or str(job.get("current_app") or "")
    )
    reason_bits = [f"dating {action}"]
    if dry:
        reason_bits.append("dry_run — no real send/like")
    if composed.get("text"):
        reason_bits.append(f"msg={str(composed.get('text'))[:60]}")
    if composed.get("source"):
        reason_bits.append(f"source={composed.get('source')}")

    if not dry:
        _send_to_device(
            device_id,
            {
                "type": "command",
                "command": action,
                "job_id": job.get("job_id"),
                "params": params,
            },
        )
    else:
        # Still nudge the phone onto the stand-in / target app for screenshots
        stand_in = job.get("stand_in_package") or state.get("stand_in_package")
        if stand_in:
            _send_to_device(
                device_id,
                {
                    "type": "command",
                    "command": "open_app",
                    "job_id": job.get("job_id"),
                    "params": {"app": stand_in, "package": stand_in},
                },
            )
            time.sleep(1.2)
            ctx = capture_device_context(str(device_id))
            pkg = str(ctx.get("package") or pkg)

    shot_key = store_screenshot(
        str(job.get("job_id") or ""),
        int(state.get("steps") or 1),
        ctx.get("screenshot_b64"),
    )
    append_step(
        state,
        action=action,
        reason=" · ".join(reason_bits),
        package=pkg,
        screen=pkg,
        ok=True,
        screenshot_key=shot_key,
        dry_run=dry,
        verify=f"tree_chars={ctx.get('tree_chars')}",
    )
    job["state"] = state

    logger.info(
        "dating step job=%s action=%s openers=%s replies=%s swipes=%s next=%s gap=%s dry=%s",
        job.get("job_id"),
        action,
        state.get("openers_sent"),
        state.get("replies_sent"),
        state.get("swipes_done"),
        job["next_run_at"],
        gap_i,
        dry,
    )
    if dry and job.get("status") == "running":
        _kick_job_later(str(job.get("job_id") or ""), delay_s=gap_i)
    return job


def run_agent_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one real LLM agent step (UI tree → plan → WS action)."""
    job = _to_plain(job)
    state = job.setdefault("state", {})
    if _safety_blocked(job):
        job["status"] = "paused"
        state["last_action"] = "safety_pause"
        job["state"] = state
        job["next_run_at"] = int(time.time()) + 60
        job["updated_at"] = int(time.time())
        return job

    try:
        from cloud_agent import run_one_agent_step
    except ImportError:
        from backend.cloud_agent import run_one_agent_step  # type: ignore

    updated = run_one_agent_step(job)
    # Chain several agent steps in one invoke so wall-clock stays ≪ EventBridge
    # 1-minute ticks (target <3–5s/step; humanize sleeps happen inside each step).
    chain_budget = int(os.environ.get("AGENT_STEP_CHAIN") or "6")
    for _ in range(max(0, chain_budget - 1)):
        if updated.get("status") != "running":
            break
        nra = int(updated.get("next_run_at") or 0)
        # Respect intentional backoff (rate-limit / offline waits)
        if nra > int(time.time()) + 3:
            break
        updated = run_one_agent_step(updated)
    if updated.get("status") in ("completed", "failed", "stopped"):
        updated["completed_at"] = int(time.time())
    updated["updated_at"] = int(time.time())
    return updated


def run_social_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """One Social-mode tick: open stand-in / messaging app, log activity (dry-run safe)."""
    job = _to_plain(job)
    state = job.setdefault("state", {})
    device_id = str(job.get("device_id") or "")
    dry = bool(job.get("dry_run", True))  # default safe
    max_steps = int(job.get("max_steps") or 8)

    if _safety_blocked(job):
        job["status"] = "paused"
        state["last_action"] = "safety_pause"
        job["state"] = state
        job["next_run_at"] = int(time.time()) + 60
        job["updated_at"] = int(time.time())
        return job

    steps = int(state.get("steps") or 0)
    if steps >= max_steps:
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        job["result"] = state.get("last_action") or "Social dry-run finished"
        return job

    try:
        from activity_log import append_step, capture_device_context, store_screenshot
    except ImportError:
        from backend.activity_log import (  # type: ignore
            append_step,
            capture_device_context,
            store_screenshot,
        )

    stand_in = (
        job.get("stand_in_package")
        or state.get("stand_in_package")
        or "com.google.android.apps.messaging"
    )
    # Rotate simple social actions for the live activity feed
    cycle = ["open_app", "scan_unread", "draft_preview", "idle"]
    action = cycle[steps % len(cycle)]
    state["steps"] = steps + 1

    if action == "open_app":
        _send_to_device(
            device_id,
            {
                "type": "command",
                "command": "open_app",
                "job_id": job.get("job_id"),
                "params": {"app": stand_in, "package": stand_in},
            },
        )
        time.sleep(1.0)
        reason = f"open stand-in messaging app ({stand_in})"
    elif action == "scan_unread":
        reason = "scan unread threads (dry_run — no replies sent)"
    elif action == "draft_preview":
        reason = "prepare draft reply for Needs-you / dry_run (not sent)"
        state["drafts_prepared"] = int(state.get("drafts_prepared") or 0) + 1
    else:
        reason = "humanizer idle tick"

    if dry:
        reason = f"dry_run — {reason}"

    ctx = capture_device_context(device_id)
    pkg = str(ctx.get("package") or stand_in)
    state["current_app"] = pkg
    shot_key = store_screenshot(
        str(job.get("job_id") or ""),
        int(state.get("steps") or 1),
        ctx.get("screenshot_b64"),
    )
    append_step(
        state,
        action=action,
        reason=reason,
        package=pkg,
        screen=pkg,
        ok=True,
        screenshot_key=shot_key,
        dry_run=dry,
        verify=f"tree_chars={ctx.get('tree_chars')}",
    )

    humanizer = _humanizer_for_job({**job, "kind": "social"})
    gap = max(2, int(round(humanizer.sample_message_gap_seconds() * 0.25)))
    job["state"] = state
    job["next_run_at"] = int(time.time()) + gap
    job["updated_at"] = int(time.time())
    logger.info(
        "social step job=%s action=%s steps=%s dry=%s pkg=%s",
        job.get("job_id"),
        action,
        state.get("steps"),
        dry,
        pkg,
    )
    if dry and job.get("status") == "running":
        _kick_job_later(str(job.get("job_id") or ""), delay_s=gap)
    return job


def _step_worker_target() -> Optional[str]:
    """ARN/name for self-invoke; avoid STEP_WORKER_ARN self-Ref on this Lambda."""
    return (
        os.environ.get("STEP_WORKER_ARN")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or None
    )


def _kick_job_later(job_id: str, delay_s: int = 2) -> None:
    """Best-effort async re-invoke for dry-run live activity (no EventBridge wait)."""
    if not job_id:
        return
    arn = _step_worker_target()
    if not arn or os.environ.get("USE_AWS_STORAGE", "").lower() != "true":
        return
    # Schedule via next_run_at; EventBridge will pick up. Also try immediate
    # re-invoke after a short sleep in a detached thread when delay is small.
    if delay_s > 15:
        return
    try:
        import threading

        def _run():
            time.sleep(max(1, delay_s))
            try:
                import boto3

                boto3.client("lambda").invoke(
                    FunctionName=arn,
                    InvocationType="Event",
                    Payload=json.dumps({"job_id": job_id}).encode(),
                )
            except Exception as e:
                logger.warning("kick later failed: %s", e)

        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        logger.warning("kick later schedule failed: %s", e)


def process_job(job: Dict[str, Any]) -> None:
    kind = job.get("kind", "dating")
    if job.get("status") != "running":
        return
    try:
        if kind == "dating":
            updated = run_dating_step(job)
        elif kind == "social":
            updated = run_social_step(job)
        else:
            updated = run_agent_step(job)
        put_job(_dynamo_safe(updated))
    except Exception as e:
        # Persist the crash so Tasks/tick show a real error instead of idle-0.
        logger.exception("process_job crash job=%s: %s", job.get("job_id"), e)
        try:
            state = job.setdefault("state", {})
            if isinstance(state, dict):
                state["last_action"] = f"process_job_crash: {e}"
                job["state"] = state
            job["status"] = "failed"
            job["error"] = f"step_worker crash: {e}"
            job["completed_at"] = int(time.time())
            job["updated_at"] = int(time.time())
            put_job(_dynamo_safe(job))
        except Exception as persist_err:
            logger.exception(
                "failed to persist process_job crash for %s: %s",
                job.get("job_id"),
                persist_err,
            )
        raise


def handler(event: Dict[str, Any], context: Any):
    """EventBridge tick or direct invoke with job_id."""
    if event.get("job_id"):
        job = get_job(event["job_id"])
        if job:
            try:
                process_job(job)
            except Exception as e:
                return {
                    "processed": 0,
                    "job_id": event["job_id"],
                    "error": str(e),
                }
            return {"processed": 1, "job_id": event["job_id"]}
        return {"processed": 0, "error": "job not found"}

    due = list_due_jobs(limit=10)
    processed = 0
    errors = 0
    for job in due:
        try:
            process_job(job)
            processed += 1
        except Exception as e:
            errors += 1
            logger.exception("job failed: %s", e)
    return {"processed": processed, "due": len(due), "errors": errors}
