"""Run-page Start: real per-app runs on the phone (cloud agent jobs).

The old ``kind=dating`` loop only sends abstract "opener" commands to a mock
stand-in app, so on a real phone it never makes UI progress and fails at the
90s no-progress wall. Start / per-app Run now queue one agent job per app with
the same instructions the verified fixed planners parse (first contact or
fixed swipe). Apps run one after another (``run_queue``), never in parallel.

Per-app caps: Hinge = count from the trigger; Hily 5; Facebook Dating 50;
BLK / Yubo = count; Bumble / Badoo = swipe count. WhatsApp is never run here.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_COUNT = 5

# package -> (app key, kind, per-run cap or None = count from the trigger)
RUN_APPS: Dict[str, Tuple[str, str, Optional[int]]] = {
    "co.hinge.app": ("hinge", "first_contact", None),
    "com.hily.app": ("hily", "first_contact", 5),
    "com.facebook.katana": ("facebook", "first_contact", 50),
    "com.affinityapps.blk": ("blk", "first_contact", None),
    "co.yellw.yellowapp": ("yubo", "first_contact", None),
    "com.bumble.app": ("bumble", "swipe", None),
    "com.badoo.mobile": ("badoo", "swipe", None),
}
_BY_KEY = {v[0]: k for k, v in RUN_APPS.items()}
_ALIASES = {"facebook dating": "facebook", "fb": "facebook", "fb dating": "facebook"}


def resolve_package(token: str) -> Optional[str]:
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in RUN_APPS:
        return t
    t = _ALIASES.get(t, t)
    return _BY_KEY.get(t)


def run_count(pkg: str, count: Optional[int]) -> int:
    _key, kind, cap = RUN_APPS[pkg]
    n = int(count or 0)
    if cap is not None:
        # Fixed caps (Hily 5, FB 50) unless the trigger asks for fewer
        return max(1, min(cap, n or cap))
    return max(1, n or DEFAULT_COUNT)


def instruction_for(pkg: str, count: Optional[int]) -> str:
    key, kind, _cap = RUN_APPS[pkg]
    n = run_count(pkg, count)
    if kind == "swipe":
        return f"fixed swipe {n} on {key}"
    if key == "facebook":
        return (
            f'send {n} first contact messages on facebook dating '
            f'"hi miss you look beautiful"'
        )
    return f"send {n} first contact messages on {key}"


def split_supported(apps: List[str]) -> Tuple[List[str], List[str]]:
    ok: List[str] = []
    bad: List[str] = []
    for a in apps or []:
        pkg = resolve_package(a)
        if pkg and pkg not in ok:
            ok.append(pkg)
        elif not pkg:
            bad.append(str(a))
    return ok, bad


def build_job(
    *,
    device_id: str,
    queue: List[str],
    count: Optional[int],
    dry_run: bool,
    run_id: Optional[str] = None,
    speed_preset: str = "balanced",
) -> Dict[str, Any]:
    """Agent job for ``queue[0]``; the rest of the queue runs after it ends."""
    pkg = queue[0]
    n = run_count(pkg, count)
    now = int(time.time())
    job_id = f"task_{secrets.token_hex(8)}"
    return {
        "job_id": job_id,
        "kind": "agent",
        "mode": "dating",
        "dating_run": True,
        "run_id": run_id or job_id,
        "dating_app": pkg,
        "status": "running",
        "device_id": device_id,
        "instruction": instruction_for(pkg, count),
        # ~6 planner steps per message/swipe plus app open + popups
        "max_steps": min(400, 6 * n + 15),
        "speed_preset": speed_preset,
        "dry_run": bool(dry_run),
        "live_test": False,
        "created_at": now,
        "next_run_at": now,
        "run_queue": list(queue[1:]),
        "run_count": int(count or 0),
        "state": {
            "steps": 0,
            "history": [],
            "dry_run": bool(dry_run),
            "current_app": pkg,
        },
        "ttl": now + 86400,
        "result": "Queued for cloud agent",
    }


def next_job_after(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """When a run job finished (or failed), build the job for the next app."""
    if not job.get("dating_run"):
        return None
    if str(job.get("status") or "") not in ("completed", "failed"):
        return None
    queue = [q for q in (job.get("run_queue") or []) if q in RUN_APPS]
    if not queue:
        return None
    return build_job(
        device_id=str(job.get("device_id") or ""),
        queue=queue,
        count=int(job.get("run_count") or 0) or None,
        dry_run=bool(job.get("dry_run")),
        run_id=str(job.get("run_id") or job.get("job_id") or ""),
        speed_preset=str(job.get("speed_preset") or "balanced"),
    )


def latest_in_run(run_id: str, jobs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Newest job of a run (jobs sorted newest first, as list_recent_jobs)."""
    for j in jobs or []:
        if str(j.get("run_id") or "") == run_id:
            return j
    return None
