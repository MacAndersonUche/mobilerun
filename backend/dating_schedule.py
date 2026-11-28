"""Dating run schedules (r44): per-app and combo runs at set times.

A schedule fires the same per-app job chain as Run-page Start
(``dating_run.build_job``): apps run one after another, never in parallel.

Shape (stored in the Settings table under ``user:_scheduler:dating_schedules``)::

    {"id", "name", "enabled", "kind": "app"|"combo",
     "items": [{"app": "<package>", "runs": 1, "count": 5}, ...],
     "time": "HH:MM", "days": [0..6] (Mon=0; [] = every day),
     "dry_run": bool, "device_id", "owner",
     "last_fired_key", "last_fired_at", "last_result"}

Times are Europe/London. The StepWorker's 1-minute EventBridge tick calls
``fire_due``. A slot fires at most once, only within ``FIRE_WINDOW_S`` of its
time (so creating a schedule after today's time does not fire it), and is
skipped (and logged) when a run is already active on the device or the phone
is offline. Caps / paid-tap rules are the job's own (same planners as Start).
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from dating_run import (
        DEFAULT_LIKES,
        HILY_MODES,
        FIXED_APP_MODES,
        LIKE_CAP_MODES,
        LIKE_AFTER,
        MAX_COUNT,
        MAX_LIKES,
        RUN_APPS,
        build_job,
        resolve_package,
    )
except ImportError:  # pragma: no cover
    from backend.dating_run import (  # type: ignore
        DEFAULT_LIKES,
        HILY_MODES,
        FIXED_APP_MODES,
        LIKE_CAP_MODES,
        LIKE_AFTER,
        MAX_COUNT,
        MAX_LIKES,
        RUN_APPS,
        build_job,
        resolve_package,
    )

logger = logging.getLogger(__name__)

SCHED_USER = "_scheduler"
SCHED_NAME = "dating_schedules"
FIRE_WINDOW_S = 15 * 60
MAX_RUNS_PER_APP = 10
MAX_SCHEDULES = 50
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def london_tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/London")
    except Exception:  # pragma: no cover - Lambda without tzdata
        from dateutil import tz

        return tz.gettz("Europe/London")


def _now_local(now: Optional[float] = None) -> datetime:
    return datetime.fromtimestamp(time.time() if now is None else now, london_tz())


class ScheduleError(ValueError):
    pass


def normalize(
    raw: Dict[str, Any], existing: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Validate + clean a schedule from the portal. Raises ScheduleError."""
    if not isinstance(raw, dict):
        raise ScheduleError("schedule must be an object")
    base = dict(existing or {})
    items_in = raw.get("items", base.get("items"))
    items: List[Dict[str, Any]] = []
    for it in items_in or []:
        if not isinstance(it, dict):
            continue
        pkg = resolve_package(str(it.get("app") or ""))
        if not pkg or pkg not in RUN_APPS:
            raise ScheduleError(f"app not runnable: {it.get('app')}")
        try:
            runs = int(it.get("runs") or 1)
            count = int(it.get("count") or 5)
        except (TypeError, ValueError):
            raise ScheduleError("runs and count must be numbers")
        runs = max(1, min(MAX_RUNS_PER_APP, runs))
        count = max(1, min(MAX_COUNT, count))
        if pkg == "com.facebook.katana":
            count = min(count, 50)
        item = {"app": pkg, "runs": runs, "count": count}
        mode = str(it.get("mode") or "").strip().lower()
        if pkg == "com.taggedapp":
            item["mode"] = mode if mode in ("swipe", "message") else "swipe"
        if pkg == "com.hily.app":
            # r46: Likes only | Message + likes, each with its max likes
            item["mode"] = mode if mode in HILY_MODES else "message_likes"
            count = min(count, 5)
            item["count"] = count
            try:
                likes = int(it.get("likes") or DEFAULT_LIKES)
            except (TypeError, ValueError):
                raise ScheduleError("max likes must be a number")
            item["likes"] = max(1, min(MAX_LIKES, likes))
        if pkg in FIXED_APP_MODES:
            # r50: Boo / Breeze / Taimi / Pure / 3Fun modes (+ Max likes)
            modes_ok = FIXED_APP_MODES[pkg]
            item["mode"] = mode if mode in modes_ok else modes_ok[0]
            if item["mode"] in LIKE_CAP_MODES.get(pkg, ()):
                try:
                    likes = int(it.get("likes") or DEFAULT_LIKES)
                except (TypeError, ValueError):
                    raise ScheduleError("max likes must be a number")
                item["likes"] = max(1, min(MAX_LIKES, likes))
        items.append(item)
    if not items:
        raise ScheduleError("pick at least one app")
    t = str(raw.get("time", base.get("time")) or "").strip()
    m = _TIME_RE.match(t)
    if not m:
        raise ScheduleError("time must be HH:MM (24h, London time)")
    t = f"{int(m.group(1)):02d}:{m.group(2)}"
    days_in = raw.get("days", base.get("days")) or []
    try:
        days = sorted({int(d) for d in days_in if 0 <= int(d) <= 6})
    except (TypeError, ValueError):
        raise ScheduleError("days must be 0-6 (Mon-Sun)")
    if len(days) == 7:
        days = []
    kind = "app" if len(items) == 1 and items[0]["runs"] == 1 else "combo"
    name = str(raw.get("name", base.get("name")) or "").strip()[:60]
    if not name:
        name = " + ".join(RUN_APPS[i["app"]][0].title() for i in items)
    out = dict(base)
    out.update(
        {
            "id": base.get("id") or f"sch_{secrets.token_hex(5)}",
            "name": name,
            "enabled": bool(raw.get("enabled", base.get("enabled", True))),
            "kind": kind,
            "items": items,
            "time": t,
            "days": days,
            "dry_run": bool(raw.get("dry_run", base.get("dry_run", True))),
            "device_id": str(raw.get("device_id") or base.get("device_id") or ""),
            "created_at": int(base.get("created_at") or time.time()),
        }
    )
    if raw.get("owner"):
        out["owner"] = str(raw["owner"])
    if not out["device_id"]:
        raise ScheduleError("pick your phone first")
    # Edited time/days: allow today's new slot to fire
    if existing and (existing.get("time") != t or existing.get("days") != days):
        out.pop("last_fired_key", None)
    return out


def _slot(day: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def _day_ok(s: Dict[str, Any], d: datetime) -> bool:
    days = s.get("days") or []
    return not days or d.weekday() in [int(x) for x in days]


def slot_key(slot: datetime) -> str:
    return slot.strftime("%Y-%m-%d %H:%M")


def next_run(s: Dict[str, Any], now: Optional[float] = None) -> Optional[datetime]:
    """Next London slot not yet fired (None when disabled)."""
    if not s.get("enabled"):
        return None
    loc = _now_local(now)
    for i in range(0, 8):
        day = (loc + timedelta(days=i)).replace(tzinfo=None)
        day = datetime(day.year, day.month, day.day, tzinfo=london_tz())
        if not _day_ok(s, day):
            continue
        slot = _slot(day, s["time"])
        if slot_key(slot) == s.get("last_fired_key"):
            continue
        if slot.timestamp() + FIRE_WINDOW_S < loc.timestamp():
            continue
        return slot
    return None


def due_slot(s: Dict[str, Any], now: Optional[float] = None) -> Optional[datetime]:
    """Today's slot when it is due now (within the fire window, not fired)."""
    if not s.get("enabled"):
        return None
    loc = _now_local(now)
    day = datetime(loc.year, loc.month, loc.day, tzinfo=london_tz())
    if not _day_ok(s, day):
        return None
    slot = _slot(day, s["time"])
    delta = loc.timestamp() - slot.timestamp()
    if delta < 0 or delta > FIRE_WINDOW_S:
        return None
    if slot_key(slot) == s.get("last_fired_key"):
        return None
    return slot


def build_queue(s: Dict[str, Any]) -> Tuple[List[str], Dict[str, int]]:
    """Run queue (each app repeated ``runs`` times) + per-app counts."""
    queue: List[str] = []
    counts: Dict[str, int] = {}
    for it in s.get("items") or []:
        pkg = it["app"]
        counts[pkg] = int(it.get("count") or 5)
        for _ in range(int(it.get("runs") or 1)):
            queue.append(pkg)
            if pkg in LIKE_AFTER:
                queue.append(LIKE_AFTER[pkg])
    return queue, counts


def build_modes(s: Dict[str, Any]) -> Dict[str, str]:
    """r45: per-app run mode from schedule items (Tagged swipe / message)."""
    return {
        it["app"]: str(it.get("mode")) for it in s.get("items") or [] if it.get("mode")
    }


def build_like_caps(s: Dict[str, Any]) -> Dict[str, int]:
    """r46: Hily max likes for the item's mode."""
    out: Dict[str, int] = {}
    for it in s.get("items") or []:
        if it.get("app") == "com.hily.app" and it.get("likes"):
            mode = str(it.get("mode") or "message_likes")
            out[f"com.hily.app:{mode}"] = int(it["likes"])
        elif it.get("app") in LIKE_CAP_MODES and it.get("likes") and it.get("mode"):
            out[f"{it['app']}:{it['mode']}"] = int(it["likes"])  # r50
    return out


def run_active(device_id: str, jobs: List[Dict[str, Any]]) -> Optional[str]:
    """job_id of a running job on this device, if any."""
    for j in jobs or []:
        if str(j.get("status") or "") != "running":
            continue
        if device_id and str(j.get("device_id") or "") not in ("", device_id):
            continue
        return str(j.get("job_id") or "?")
    return None


# ---- storage -------------------------------------------------------------


def _storage():
    try:
        import storage  # type: ignore
    except ImportError:  # pragma: no cover
        from backend import storage  # type: ignore
    return storage


def load_all() -> List[Dict[str, Any]]:
    data = _storage().get_user_setting(SCHED_USER, SCHED_NAME) or {}
    out = data.get("schedules") if isinstance(data, dict) else None
    return [dict(s) for s in (out or []) if isinstance(s, dict)]


def save_all(schedules: List[Dict[str, Any]]) -> None:
    _storage().save_user_setting(
        SCHED_USER, SCHED_NAME, {"schedules": schedules[:MAX_SCHEDULES]}
    )


def with_next(s: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    out = dict(s)
    nr = next_run(s, now)
    out["next_run"] = nr.isoformat() if nr else None
    out["next_run_label"] = nr.strftime("%a %d %b %H:%M") + " London" if nr else None
    return out


# ---- firing (StepWorker tick) ---------------------------------------------


def fire_due(
    now: Optional[float] = None,
    *,
    load: Callable[[], List[Dict[str, Any]]] = load_all,
    save: Callable[[List[Dict[str, Any]]], None] = save_all,
    recent_jobs: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    put_job: Optional[Callable[[Dict[str, Any]], None]] = None,
    reachable: Optional[Callable[[str], bool]] = None,
) -> List[Dict[str, Any]]:
    """Queue jobs for due schedules. Returns [{id, result, job_id?}]."""
    try:
        schedules = load()
    except Exception as e:
        logger.warning("schedules load failed: %s", e)
        return []
    if not any(due_slot(s, now) for s in schedules):
        return []
    st = _storage() if (recent_jobs is None or put_job is None) else None
    recent_jobs = recent_jobs or (lambda: st.list_recent_jobs(limit=40))
    put_job = put_job or st.put_job
    if reachable is None:
        try:
            from device_push import device_is_reachable as reachable  # type: ignore
        except ImportError:  # pragma: no cover
            try:
                from backend.device_push import device_is_reachable as reachable  # type: ignore
            except ImportError:
                reachable = lambda _d: True  # noqa: E731
    results: List[Dict[str, Any]] = []
    changed = False
    for s in schedules:
        slot = due_slot(s, now)
        if not slot:
            continue
        key = slot_key(slot)
        s["last_fired_key"] = key
        s["last_fired_at"] = int(time.time() if now is None else now)
        changed = True
        did = str(s.get("device_id") or "")
        res: Dict[str, Any] = {"id": s.get("id"), "slot": key}
        try:
            active = run_active(did, recent_jobs())
        except Exception as e:
            active = None
            logger.warning("schedule active-run check failed: %s", e)
        if active:
            res["result"] = f"skipped: run already active ({active})"
        elif not reachable(did):
            res["result"] = "skipped: phone offline"
        else:
            queue, counts = build_queue(s)
            job = build_job(
                device_id=did,
                queue=queue,
                count=None,
                dry_run=bool(s.get("dry_run", True)),
                counts=counts,
                modes=build_modes(s),
                like_caps=build_like_caps(s),
            )
            job["schedule_id"] = s.get("id")
            put_job(job)
            res["result"] = "queued"
            res["job_id"] = job["job_id"]
        s["last_result"] = f"{key}: {res['result']}" + (
            f" {res['job_id']}" if res.get("job_id") else ""
        )
        logger.info(
            "dating schedule fire id=%s slot=%s result=%s job=%s",
            s.get("id"),
            key,
            res["result"],
            res.get("job_id"),
        )
        results.append(res)
    if changed:
        try:
            save(schedules)
        except Exception as e:  # pragma: no cover
            logger.warning("schedules save failed: %s", e)
    return results
