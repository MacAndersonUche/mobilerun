"""Run-page Start: real per-app runs on the phone (cloud agent jobs).

The old ``kind=dating`` loop only sends abstract "opener" commands to a mock
stand-in app, so on a real phone it never makes UI progress and fails at the
90s no-progress wall. Start / per-app Run now queue one agent job per app with
the same instructions the verified fixed planners parse (first contact or
fixed swipe). Apps run one after another (``run_queue``), never in parallel.

Per-app caps: Hinge = count from the trigger; Hily 5; Facebook Dating 50;
BLK / Yubo = count; Bumble / Badoo = swipe count. WhatsApp is never run here.
Hily (r46): two modes like Tagged — "Likes only" (Finder free hearts up to
that mode's max likes) and "Message + likes" (like N in Finder, message N
from Activity → Likes sent envelopes, then keep liking up to the max).
One job, ``hily_fixed_run`` planner, never Crush / paid.
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
    "co.yellw.yellowapp": ("yubo", "first_contact", None),
    "com.bumble.app": ("bumble", "swipe", None),
    "com.badoo.mobile": ("badoo", "swipe", None),
    # r45: Tagged — auto swipe (free like) or auto message (per-app mode)
    "com.taggedapp": ("tagged", "tagged", None),
    # r49 (CA-24): Tinder fixed auto-swipe — free right-swipe, popups closed,
    # matches get a bank line
    "com.affinityapps.blk": ("blk", "first_contact", None),  # r49: bottom
    "com.tinder": ("tinder", "tinder", None),
    # r50: generic fixed like / message runs (fixed_like_run.py)
    "com.takimi.android": ("taimi", "fixed_app", None),
    "enterprises.dating.boo": ("boo", "fixed_app", None),
    "social.breeze.breeze_app": ("breeze", "fixed_app", None),
    "com.getpure.pure": ("pure", "fixed_app", None),
    "com.threesome.swingers.threefun": ("threefun", "fixed_app", None),
}
# r50: per-app modes for the fixed_app runs (first = default)
FIXED_APP_MODES: Dict[str, Tuple[str, ...]] = {
    "com.takimi.android": ("likes", "message_likes"),
    "enterprises.dating.boo": ("likes", "message_likes"),
    "social.breeze.breeze_app": ("likes",),
    "com.getpure.pure": ("likes", "message"),
    "com.threesome.swingers.threefun": ("likes",),
}
TINDER_PKG = "com.tinder"
TAGGED_PKG = "com.taggedapp"
TAGGED_MODES = ("swipe", "message")
HILY_PKG = "com.hily.app"
HILY_MODES = ("likes", "message_likes")  # Likes only | Message + likes
DEFAULT_MODE = {
    TAGGED_PKG: "swipe",
    HILY_PKG: "message_likes",
    **{k: v[0] for k, v in FIXED_APP_MODES.items()},
}
RUN_MODES = {TAGGED_PKG: TAGGED_MODES, HILY_PKG: HILY_MODES, **FIXED_APP_MODES}
# Apps with a "Max likes" box per mode (Hily: both; Boo / Taimi: Message + like)
LIKE_CAP_MODES: Dict[str, Tuple[str, ...]] = {
    HILY_PKG: HILY_MODES,
    "com.takimi.android": ("message_likes",),
    "enterprises.dating.boo": ("message_likes",),
}
# Max likes per Hily mode (portal box per mode); cap like the other counts
DEFAULT_LIKES = 30
MAX_LIKES = 500


def clean_modes(raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Per-app run mode: Tagged swipe|message, Hily likes|message_likes."""
    out: Dict[str, str] = {}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else []:
        pkg = resolve_package(str(k))
        m = str(v or "").strip().lower()
        if pkg in RUN_MODES and m in RUN_MODES[pkg]:
            out[pkg] = m
    return out


def clean_like_caps(raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Max likes per app mode, keyed ``"<pkg>:<mode>"`` (Hily only)."""
    out: Dict[str, int] = {}
    for k, v in (raw or {}).items() if isinstance(raw, dict) else []:
        pkg_s, _, mode = str(k).partition(":")
        pkg = resolve_package(pkg_s)
        mode = mode.strip().lower()
        if mode not in LIKE_CAP_MODES.get(pkg or "", ()):
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[f"{pkg}:{mode}"] = min(MAX_LIKES, n)
    return out


def hily_plan(
    count: Optional[int],
    counts: Optional[Dict[str, int]] = None,
    modes: Optional[Dict[str, str]] = None,
    like_caps: Optional[Dict[str, int]] = None,
) -> Tuple[str, int, int]:
    """-> (mode, messages, max_likes). Likes include the N message likes."""
    mode = (modes or {}).get(HILY_PKG) or DEFAULT_MODE[HILY_PKG]
    likes = int((like_caps or {}).get(f"{HILY_PKG}:{mode}") or DEFAULT_LIKES)
    likes = max(1, min(MAX_LIKES, likes))
    if mode == "likes":
        return mode, 0, likes
    msgs = run_count(HILY_PKG, count, counts)
    return mode, msgs, max(likes, msgs)


def fixed_app_plan(
    pkg: str,
    count: Optional[int],
    counts: Optional[Dict[str, int]] = None,
    modes: Optional[Dict[str, str]] = None,
    like_caps: Optional[Dict[str, int]] = None,
) -> Tuple[str, int, int]:
    """r50 -> (mode, messages, likes) for Boo / Breeze / Taimi / Pure / 3Fun.

    likes mode: the card number is the likes. message_likes: the card number
    is the messages, likes come from the mode's Max likes box. message: the
    card number is the messages."""
    allowed = FIXED_APP_MODES[pkg]
    mode = (modes or {}).get(pkg) or allowed[0]
    if mode not in allowed:
        mode = allowed[0]
    n = run_count(pkg, count, counts)
    if mode == "likes":
        return mode, 0, n
    if mode == "message":
        return mode, n, 0
    likes = int((like_caps or {}).get(f"{pkg}:{mode}") or DEFAULT_LIKES)
    return mode, n, max(1, min(MAX_LIKES, likes))


_BY_KEY = {v[0]: k for k, v in RUN_APPS.items()}
_BY_KEY.update(
    {"3fun": "com.threesome.swingers.threefun", "takimi": "com.takimi.android"}
)
# Follow-up step queued right after an app's main job (likes only)
# r46: Hily likes run inside its own job (hily_fixed_run); the old
# ``com.hily.app#like`` step stays known so queued runs still finish.
LIKE_AFTER: Dict[str, str] = {}
_LIKE_STEPS = {"com.hily.app#like"}


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
    pkg: str,
    count: Optional[int],
    counts: Optional[Dict[str, int]] = None,
    modes: Optional[Dict[str, str]] = None,
    like_caps: Optional[Dict[str, int]] = None,
) -> str:
    n = run_count(pkg, count, counts)
    if pkg == HILY_PKG:
        mode, msgs, likes = hily_plan(count, counts, modes, like_caps)
        if mode == "likes":
            return f"fixed hily likes {likes}"
        return f"fixed hily message {msgs} likes {likes}"
    if pkg == TAGGED_PKG:
        mode = (modes or {}).get(pkg) or "swipe"
        return f"fixed tagged {mode} {n}"
    if pkg == TINDER_PKG:
        return f"fixed tinder swipe {n}"
    if pkg in FIXED_APP_MODES:
        mode, msgs, likes = fixed_app_plan(pkg, count, counts, modes, like_caps)
        return f"fixed app {RUN_APPS[pkg][0]} {mode} messages {msgs} likes {likes}"
    if pkg in _LIKE_STEPS:
        # Hily: buttons only (gesture swipe does not register) → free heart
        return f"swipe {n} on {RUN_APPS[base_package(pkg)][0]}"
    key, kind, _cap = RUN_APPS[pkg]
    if kind == "swipe":
        return f"fixed swipe {n} on {key}"
    if key == "facebook":
        return (
            f"send {n} first contact messages on facebook dating "
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
    modes: Optional[Dict[str, str]] = None,
    like_caps: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Agent job for ``queue[0]``; the rest of the queue runs after it ends."""
    pkg = queue[0]
    counts = clean_counts(counts)
    modes = clean_modes(modes)
    like_caps = clean_like_caps(like_caps)
    n = run_count(pkg, count, counts)
    max_steps = min(400, 6 * n + 15)
    wall_s = 0
    if pkg == "co.hinge.app":
        # r53: blind inline panel — heart, wait, focus, type, Send Like,
        # Rose check, next card ≈ 8 steps per message + app open/popups
        max_steps = min(400, 10 * n + 20)
    if pkg == "co.yellw.yellowapp":
        # r48: ~7 steps per card (open, Direct, type, send, popup, swipe,
        # next card); 6n+15 ran out at card 5 on 24 Nov
        max_steps = min(400, 9 * n + 20)
        # Default AGENT_JOB_WALL_S is 600s; 5 cards with popups/waits
        # can exceed that (same class of fail as Hinge 27 Nov).
        wall_s = min(3600, 180 + 120 * n)
    if pkg == TAGGED_PKG:
        # 27 Nov: photo → Your message → send → Back → green heart
        max_steps = min(400, 10 * n + 20)
        wall_s = min(3600, 180 + 90 * n)
    if pkg in FIXED_APP_MODES:
        _m, msgs, likes = fixed_app_plan(pkg, count, counts, modes, like_caps)
        max_steps = min(1500, 3 * likes + 8 * msgs + 30)
        wall_s = min(3600, 120 + 12 * likes + 60 * msgs)
    if pkg == TINDER_PKG:
        # swipe + popup / match-message headroom
        max_steps = min(1500, 3 * n + 30)
        wall_s = min(3600, 120 + 12 * n)
    if pkg == HILY_PKG:
        _m, msgs, likes = hily_plan(count, counts, modes, like_caps)
        # ~1-2 steps per Finder like + ~6 per Likes-sent message
        max_steps = min(1500, 2 * likes + 8 * msgs + 25)
        wall_s = min(3600, 120 + 10 * likes + 60 * msgs)
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
        "instruction": instruction_for(pkg, count, counts, modes, like_caps),
        # ~6 planner steps per message/swipe plus app open + popups
        "max_steps": max_steps,
        "speed_preset": speed_preset,
        "dry_run": bool(dry_run),
        "live_test": False,
        "created_at": now,
        "next_run_at": now,
        "run_queue": list(queue[1:]),
        "run_count": int(count or 0),
        # Per-app per-run numbers from the app cards (package -> n)
        "run_counts": dict(counts),
        "run_modes": dict(modes),
        "run_like_caps": dict(like_caps),
        "state": {
            "steps": 0,
            "history": [],
            "dry_run": bool(dry_run),
            "current_app": base_package(pkg),
        },
        **({"wall_s": wall_s} if wall_s else {}),
        # r53: Hinge Discover is blind — slow empty-tree steps are healthy
        **({"ui_wall_s": 240} if pkg == "co.hinge.app" else {}),
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
    nxt = build_job(
        device_id=str(job.get("device_id") or ""),
        queue=queue,
        count=int(job.get("run_count") or 0) or None,
        dry_run=bool(job.get("dry_run")),
        run_id=str(job.get("run_id") or job.get("job_id") or ""),
        speed_preset=str(job.get("speed_preset") or "balanced"),
        counts=(
            job.get("run_counts") if isinstance(job.get("run_counts"), dict) else None
        ),
        modes=job.get("run_modes") if isinstance(job.get("run_modes"), dict) else None,
        like_caps=(
            job.get("run_like_caps")
            if isinstance(job.get("run_like_caps"), dict)
            else None
        ),
    )
    if job.get("user_id"):
        nxt["user_id"] = job.get("user_id")
        nxt["owner"] = job.get("owner") or job.get("user_id")
    nxt["contact_scope"] = "new"
    return nxt


def latest_in_run(run_id: str, jobs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Newest job of a run (jobs sorted newest first, as list_recent_jobs)."""
    for j in jobs or []:
        if str(j.get("run_id") or "") == run_id:
            return j
    return None


def running_dating_jobs(
    jobs: List[Dict[str, Any]], *, skip: Optional[str] = None
) -> List[Dict[str, Any]]:
    """r45: every still-running dating job (Stop must free the phone even
    when this Lambda lost dating_mode_state['job_id'])."""
    out: List[Dict[str, Any]] = []
    for j in jobs or []:
        if not isinstance(j, dict):
            continue
        if str(j.get("status") or "") != "running":
            continue
        if skip and str(j.get("job_id") or "") == skip:
            continue
        if (
            j.get("dating_run")
            or j.get("dating_app")
            or j.get("schedule_id")
            or str(j.get("mode") or "") == "dating"
        ):
            out.append(j)
    return out
