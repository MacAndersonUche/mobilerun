"""Run-page Start: real per-app runs on the phone (cloud agent jobs).

The old ``kind=dating`` loop only sends abstract "opener" commands to a mock
stand-in app, so on a real phone it never makes UI progress and fails at the
90s no-progress wall. Start / per-app Run now queue one agent job per app with
the same instructions the verified fixed planners parse (first contact or
fixed swipe). Apps run one after another (``run_queue``), never in parallel.

Per-app caps: Hinge = count from the trigger; Hily 5; Facebook Dating 50;
BLK / Yubo = count; Bumble / Badoo = swipe count. WhatsApp is never run here.
Hily: after its 5 first-contact messages the run keeps going with free
heart likes only (``com.hily.app#like`` → bulk swipe, never a message,
never Crush / paid).
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
# Follow-up step queued right after an app's main job (likes only)
LIKE_AFTER = {"com.hily.app": "com.hily.app#like"}
_LIKE_STEPS = set(LIKE_AFTER.values())


def base_package(item: str) -> str:
    return str(item or "").split("#", 1)[0]


def _known(item: str) -> bool:
    return item in RUN_APPS or item in _LIKE_STEPS
_ALIASES = {"facebook dating": "facebook", "fb": "facebook", "fb dating": "facebook"}


def resolve_package(token: str) -> Optional[str]:
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in RUN_APPS:
        return t
    t = _ALIASES.get(t, t)
    return _BY_KEY.get(t)


MAX_COUNT = 500


def clean_counts(raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Per-app per-run counts keyed by package ({} when none / bad input)."""
    out: Dict[str, int] = {}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else []:
        pkg = resolve_package(str(k))
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if pkg and n > 0:
            out[pkg] = min(MAX_COUNT, n)
    return out


def count_for(
    pkg: str, count: Optional[int], counts: Optional[Dict[str, int]] = None
) -> Optional[int]:
    """The app's own per-run number (Hily#like uses Hily's), else ``count``."""
    c = counts or {}
    base = base_package(pkg)
    if c.get(base):
        return int(c[base])
    return count


def run_count(
    pkg: str, count: Optional[int], counts: Optional[Dict[str, int]] = None
) -> int:
    count = count_for(pkg, count, counts)
    if pkg in _LIKE_STEPS:
        return max(1, int(count or 0) or DEFAULT_COUNT)
    _key, kind, cap = RUN_APPS[pkg]
    n = int(count or 0)
    if cap is not None:
        # Fixed caps (Hily 5, FB 50) unless the trigger asks for fewer
        return max(1, min(cap, n or cap))
    return max(1, n or DEFAULT_COUNT)


def instruction_for(
    pkg: str, count: Optional[int], counts: Optional[Dict[str, int]] = None
) -> str:
    n = run_count(pkg, count, counts)
    if pkg in _LIKE_STEPS:
        # Hily: buttons only (gesture swipe does not register) → free heart
        return f"swipe {n} on {RUN_APPS[base_package(pkg)][0]}"
    key, kind, _cap = RUN_APPS[pkg]
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
            if pkg in LIKE_AFTER:
                ok.append(LIKE_AFTER[pkg])
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
    counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Agent job for ``queue[0]``; the rest of the queue runs after it ends."""
    pkg = queue[0]
    counts = clean_counts(counts)
    n = run_count(pkg, count, counts)
    now = int(time.time())
    job_id = f"task_{secrets.token_hex(8)}"
    return {
        "job_id": job_id,
        "kind": "agent",
        "mode": "dating",
        "dating_run": True,
        "run_id": run_id or job_id,
        "dating_app": base_package(pkg),
        "run_step": "like" if pkg in _LIKE_STEPS else "main",
        "status": "running",
        "device_id": device_id,
        "instruction": instruction_for(pkg, count, counts),
        # ~6 planner steps per message/swipe plus app open + popups
        "max_steps": min(400, 6 * n + 15),
        "speed_preset": speed_preset,
        "dry_run": bool(dry_run),
        "live_test": False,
        "created_at": now,
        "next_run_at": now,
        "run_queue": list(queue[1:]),
        "run_count": int(count or 0),
        # Per-app per-run numbers from the app cards (package -> n)
        "run_counts": dict(counts),
        "state": {
            "steps": 0,
            "history": [],
            "dry_run": bool(dry_run),
            "current_app": base_package(pkg),
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
    queue = [q for q in (job.get("run_queue") or []) if _known(q)]
    if not queue:
        return None
    return build_job(
        device_id=str(job.get("device_id") or ""),
        queue=queue,
        count=int(job.get("run_count") or 0) or None,
        dry_run=bool(job.get("dry_run")),
        run_id=str(job.get("run_id") or job.get("job_id") or ""),
        speed_preset=str(job.get("speed_preset") or "balanced"),
        counts=job.get("run_counts") if isinstance(job.get("run_counts"), dict) else None,
    )


def latest_in_run(run_id: str, jobs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Newest job of a run (jobs sorted newest first, as list_recent_jobs)."""
    for j in jobs or []:
        if str(j.get("run_id") or "") == run_id:
            return j
    return None
