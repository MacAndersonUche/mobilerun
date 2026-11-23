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
    from storage import (
        acquire_job_lease,
        get_device_connections,
        get_job,
        list_due_jobs,
        other_running_job_on_device,
        put_job,
        save_job_progress,
    )
except ImportError:
    from backend.storage import (  # type: ignore
        acquire_job_lease,
        get_device_connections,
        get_job,
        list_due_jobs,
        other_running_job_on_device,
        put_job,
        save_job_progress,
    )

logger = logging.getLogger("mobilerun.step")
logger.setLevel(logging.INFO)

# Hard walls (r23: jobs sat 209–583s past last progress; entry-only 90s check missed).
try:
    from cloud_agent import NO_PROGRESS_TIMEOUT_S as _NP_S
    from cloud_agent import TASK_TIMEOUT_S as _TASK_WALL_S
except ImportError:
    try:
        from backend.cloud_agent import (  # type: ignore
            NO_PROGRESS_TIMEOUT_S as _NP_S,
            TASK_TIMEOUT_S as _TASK_WALL_S,
        )
    except ImportError:
        _NP_S = 90
        _TASK_WALL_S = 900

# Per StepWorker invoke / single-step wall (default = no-progress 90s)
STEP_WALL_S = int(os.environ.get("AGENT_STEP_WALL_S") or str(_NP_S))
# Job-level hard cap. r24: 180s killed every reply/new before LLM could
# navigate (~24 heuristic rounds). Default 600s; keep 90s no-UI-progress.
JOB_WALL_S = int(os.environ.get("AGENT_JOB_WALL_S") or "600")


def _fail_job_timeout(
    job: Dict[str, Any], *, error: str, last_action: str
) -> Dict[str, Any]:
    state = job.setdefault("state", {})
    if not isinstance(state, dict):
        state = {}
        job["state"] = state
    now = int(time.time())
    job["status"] = "failed"
    job["error"] = error
    job["completed_at"] = now
    job["updated_at"] = now
    state["last_action"] = last_action
    job["state"] = state
    logger.warning(
        "step_worker timeout job=%s action=%s err=%s",
        job.get("job_id"),
        last_action,
        error,
    )
    return job


def enforce_job_wall_clock(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Hard wall-clock fail-fast for StepWorker (per-job + no-UI-progress).

    Returns a failed job dict when the wall is exceeded, else None.
    """
    now = int(time.time())
    created = int(job.get("created_at") or now)
    state = job.get("state") if isinstance(job.get("state"), dict) else {}
    # Absolute job wall (r23: refuse 7+ min hangs)
    wall = min(int(JOB_WALL_S), int(_TASK_WALL_S))
    if now - created > wall:
        return _fail_job_timeout(
            job,
            error=f"Job wall-clock exceeded ({wall}s)",
            last_action="job_wall_timeout",
        )
    # No UI progress wall — use last_ui_progress_at (not busywork last_progress_at)
    last_ui = int(state.get("last_ui_progress_at") or created)
    steps = int(state.get("steps") or 0)
    if now - last_ui > int(STEP_WALL_S) and steps >= 1:
        return _fail_job_timeout(
            job,
            error=(
                f"No UI progress for {STEP_WALL_S}s "
                f"(last_ui_progress_at={last_ui}; StepWorker hard wall)"
            ),
            last_action="no_progress_timeout",
        )
    return None


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

    scope = str(
        job.get("contact_scope") or state.get("contact_scope") or "both"
    ).lower()
    total_msgs = openers + replies
    if total_msgs >= global_max:
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        return job
    if scope == "new" and openers >= opener_target and swipes >= swipe_cap:
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        return job
    if scope == "existing" and replies >= reply_cap:
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        return job
    if scope == "both" and openers >= opener_target and replies >= reply_cap:
        job["status"] = "completed"
        job["completed_at"] = int(time.time())
        return job

    humanizer = _humanizer_for_job(job)

    # Prefer openers until target, then replies — always sequential (one per tick)
    # contact_scope: new → openers/likes only; existing → replies only; both → mix
    dry = bool(job.get("dry_run", False))
    if scope == "existing":
        action = "reply"
        state["replies_sent"] = replies + 1
        gap = humanizer.sample_message_gap_seconds()
    elif scope == "new":
        if openers < opener_target:
            action = "opener"
            state["openers_sent"] = openers + 1
            gap = humanizer.sample_message_gap_seconds()
        elif swipes < swipe_cap:
            action = "swipe"
            state["swipes_done"] = swipes + 1
            gap = humanizer.sample_swipe_step_gap_seconds()
        else:
            job["status"] = "completed"
            job["completed_at"] = int(time.time())
            return job
    elif openers < opener_target:
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

    # Hard wall BEFORE any RPC/LLM (r23: 90s check only inside cloud_agent was late)
    timed = enforce_job_wall_clock(job)
    if timed:
        return timed

    try:
        from cloud_agent import run_one_agent_step
    except ImportError:
        from backend.cloud_agent import run_one_agent_step  # type: ignore

    # Suppress per-step Lambda self-kicks while chaining in-process — one kick
    # after the chain if still running (avoids 6 workers racing one job).
    invoke_t0 = time.time()
    job["_suppress_kick"] = True
    updated = run_one_agent_step(job)
    # Chain several agent steps in one invoke so wall-clock stays ≪ EventBridge
    # 1-minute ticks (target <3–5s/step; humanize sleeps happen inside each step).
    chain_budget = int(os.environ.get("AGENT_STEP_CHAIN") or "6")
    lease_owner = str(job.get("_lease_owner") or job.get("lease_owner") or "")
    lease_jid = str(job.get("job_id") or "")
    for _ in range(max(0, chain_budget - 1)):
        if updated.get("status") != "running":
            break
        # r28: honor cancel between chained steps — never continue after stop
        try:
            from cloud_agent import refresh_job_cancel_status
        except ImportError:
            from backend.cloud_agent import (  # type: ignore
                refresh_job_cancel_status,
            )
        if refresh_job_cancel_status(updated):
            break
        # Per-invoke wall + no-progress re-check between chained steps
        if time.time() - invoke_t0 > float(STEP_WALL_S):
            updated = _fail_job_timeout(
                updated,
                error=f"StepWorker invoke exceeded {STEP_WALL_S}s wall",
                last_action="step_invoke_wall_timeout",
            )
            break
        timed = enforce_job_wall_clock(updated)
        if timed:
            updated = timed
            break
        nra = int(updated.get("next_run_at") or 0)
        # Respect intentional backoff (rate-limit / offline waits)
        if nra > int(time.time()) + 3:
            break
        # Renew between chained steps so a long chain cannot expire the lease
        if lease_jid and lease_owner:
            acquire_job_lease(lease_jid, lease_owner)
            updated["_lease_owner"] = lease_owner
            updated["lease_owner"] = lease_owner
        updated["_suppress_kick"] = True
        updated = run_one_agent_step(updated)
    if updated.get("status") in ("completed", "failed", "stopped"):
        updated["completed_at"] = int(time.time())
    updated["updated_at"] = int(time.time())
    updated.pop("_suppress_kick", None)
    # Single follow-up kick after the in-process chain (not per step)
    if updated.get("status") == "running":
        nra = int(updated.get("next_run_at") or 0)
        delay = max(0, nra - int(time.time()))
        if delay <= 15:
            _kick_job_later(
                str(updated.get("job_id") or ""), delay_s=max(1, delay or 1)
            )
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


def _worker_owner(context: Any = None) -> str:
    """Stable-enough lease owner id for this Lambda invoke / local process."""
    req = ""
    try:
        req = str(getattr(context, "aws_request_id", "") or "")
    except Exception:
        req = ""
    if not req:
        req = f"local-{os.getpid()}-{time.time_ns()}"
    return req


def _cleanup_cancelled_job(job: Dict[str, Any]) -> None:
    """Restore bubble / HOME when a job was cancelled mid-flight (Dynamo stop)."""
    did = str(job.get("device_id") or "")
    if not did:
        return
    try:
        from cloud_agent import _end_job_cleanup
        from device_rpc import call_device
    except ImportError:
        try:
            from backend.cloud_agent import _end_job_cleanup  # type: ignore
            from backend.device_rpc import call_device  # type: ignore
        except ImportError:
            return
    try:
        _end_job_cleanup(job, did, call_device)
    except Exception as e:
        logger.warning("cancelled-job cleanup failed: %s", e)


def process_job(job: Dict[str, Any], *, owner: Optional[str] = None) -> None:
    kind = job.get("kind", "dating")
    if job.get("status") != "running":
        # Cancelled/stopped in Dynamo — still restore overlay bubble
        if str(job.get("status") or "") in ("stopped", "cancelled", "failed"):
            st = job.get("state") if isinstance(job.get("state"), dict) else {}
            if st.get("job_busy_sent") and not st.get("job_cleanup_done"):
                _cleanup_cancelled_job(job)
                st["job_cleanup_done"] = True
                job["state"] = st
        return
    job_id = str(job.get("job_id") or "")
    owner = owner or _worker_owner()
    # Device mutex: another live job on same phone → defer (r19 overlap)
    did = str(job.get("device_id") or "").strip()
    if did and job_id:
        other = other_running_job_on_device(did, except_job_id=job_id)
        if other:
            other_id = str(other.get("job_id") or "?")
            logger.info(
                "process_job defer job=%s — device %s busy with %s " "(lease_owner=%s)",
                job_id,
                did,
                other_id,
                other.get("lease_owner"),
            )
            # Push next_run slightly so we don't hot-spin
            try:
                job["next_run_at"] = int(time.time()) + 15
                job["updated_at"] = int(time.time())
                put_job(_to_plain(job))
            except Exception:
                pass
            return
    # Lease: second concurrent worker skips — prevents parallel swipes
    if job_id and not acquire_job_lease(job_id, owner):
        holder = "?"
        try:
            cur = get_job(job_id) or {}
            holder = str(cur.get("lease_owner") or "?")
            # Still enforce wall clock even when lease is held (r26: stuck lease
            # previously blocked the 90s wall until TTL expired).
            timed = enforce_job_wall_clock(cur if isinstance(cur, dict) else job)
            if timed:
                try:
                    save_job_progress(_to_plain(timed), owner=None)
                except Exception:
                    pass
                try:
                    from storage import release_job_lease as _rel
                except ImportError:
                    from backend.storage import release_job_lease as _rel  # type: ignore
                try:
                    _rel(job_id, None)
                except Exception:
                    pass
                return
        except Exception:
            holder = "?"
        logger.info(
            "process_job skip job=%s — lease held by %s (skipper=%s)",
            job_id,
            holder,
            owner,
        )
        return
    # Propagate owner so step code can renew before slow screenshot/RPC calls
    job["_lease_owner"] = owner
    job["lease_owner"] = owner
    # Fail hung jobs before dispatch (dating/social/agent all share walls)
    timed = enforce_job_wall_clock(job)
    if timed:
        try:
            save_job_progress(_to_plain(timed), owner=owner)
        except Exception:
            pass
        try:
            from storage import release_job_lease
        except ImportError:
            from backend.storage import release_job_lease  # type: ignore
        try:
            release_job_lease(job_id, owner)
        except Exception:
            pass
        return
    try:
        if kind == "dating":
            updated = run_dating_step(job)
        elif kind == "social":
            updated = run_social_step(job)
        else:
            updated = run_agent_step(job)
        # Targeted update — never put_item whole item (would revive cancelled jobs)
        # and never write lease fields (stale writeback bug).
        ok = save_job_progress(_to_plain(updated), owner=owner)
        if not ok:
            logger.warning(
                "process_job progress not saved job=%s — status changed or lease lost",
                job_id,
            )
            # Likely cancelled mid-step — restore bubble
            _cleanup_cancelled_job(updated if isinstance(updated, dict) else job)
    except Exception as e:
        # Persist the crash so Tasks/tick show a real error instead of idle-0.
        logger.exception("process_job crash job=%s: %s", job.get("job_id"), e)
        try:
            state = job.setdefault("state", {})
            if isinstance(state, dict):
                state["last_action"] = f"process_job_crash: {e}"
                # Force LLM handoff on next successful tick if job stays running
                state["_bulk_llm_handoff"] = True
                state["force_vision_once"] = True
                job["state"] = state
            # Keep running when possible so handoff can recover — only hard-fail
            # on truly fatal worker crashes.
            fatal = any(
                tok in str(e).lower()
                for tok in ("no module", "syntaxerror", "memoryerror")
            )
            if fatal:
                job["status"] = "failed"
                job["error"] = f"step_worker crash: {e}"
                job["completed_at"] = int(time.time())
            else:
                job["status"] = "running"
                job["error"] = f"step_worker soft crash → handoff: {e}"
                job["next_run_at"] = int(time.time()) + 2
            job["updated_at"] = int(time.time())
            save_job_progress(_to_plain(job), owner=owner)
        except Exception as persist_err:
            logger.exception(
                "failed to persist process_job crash for %s: %s",
                job.get("job_id"),
                persist_err,
            )
        # Do not re-raise — finally must release the lease
    finally:
        # r26 CRITICAL: always release so the next tick is not skipped with
        # "lease held by <failed invocation>" until the 90s wall.
        if job_id:
            try:
                from storage import release_job_lease
            except ImportError:
                from backend.storage import release_job_lease  # type: ignore
            try:
                released = release_job_lease(job_id, owner)
                logger.info(
                    "process_job lease release job=%s owner=%s ok=%s",
                    job_id,
                    owner,
                    released,
                )
            except Exception as rel_err:
                logger.warning(
                    "process_job lease release failed job=%s: %s", job_id, rel_err
                )


def handler(event: Dict[str, Any], context: Any):
    """EventBridge tick or direct invoke with job_id."""
    owner = _worker_owner(context)
    if event.get("job_id"):
        job = get_job(event["job_id"])
        if job:
            try:
                process_job(job, owner=owner)
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
    skipped = 0
    for job in due:
        try:
            before = str(job.get("lease_owner") or "")
            process_job(job, owner=f"{owner}-{job.get('job_id')}")
            # If lease was held, process_job returns without raising
            after = get_job(str(job.get("job_id") or "")) or {}
            if (
                before
                and before != f"{owner}-{job.get('job_id')}"
                and after.get("lease_owner") == before
            ):
                skipped += 1
            else:
                processed += 1
        except Exception as e:
            errors += 1
            logger.exception("job failed: %s", e)
    return {
        "processed": processed,
        "due": len(due),
        "errors": errors,
        "skipped": skipped,
    }
