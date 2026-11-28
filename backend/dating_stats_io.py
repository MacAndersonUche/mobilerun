"""Load / save dating dashboard stats (SETTINGS_TABLE or local JSON).

Root cause of zero "today" totals: fixed first-contact runs only bumped
job.state.bulk_message_new.done and never called DatingStats.record_*.
This module bridges those counters into durable per-user stats and uses
Europe/London for the day boundary.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("mobilerun.dating_stats_io")

SETTING_NAME = "dating_stats"


def _storage():
    try:
        from storage import get_user_setting, save_user_setting
    except ImportError:
        from backend.storage import get_user_setting, save_user_setting  # type: ignore

    return get_user_setting, save_user_setting


def _default_file() -> Path:
    """Local cache path. Honor MOBILERUN_DATA (Lambda sets /tmp/mobilerun).

    Never use Path.home() on Lambda — home is read-only (Errno 30) and
    check_and_reset_daily() → save() used to 500 GET /api/dating/stats.
    """
    import os

    root = os.environ.get("MOBILERUN_DATA") or ""
    if root.strip():
        return Path(root.strip()) / "dating_stats.json"
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("LAMBDA_TASK_ROOT"):
        return Path("/tmp/mobilerun") / "dating_stats.json"
    return Path.home() / ".mobilerun" / "dating_stats.json"


def load_dating_stats(user_id: Optional[str] = None):
    """Load DatingStats for a user (or the shared local file).

    Local day-reset save failures must never raise — Dynamo is authoritative.
    """
    from mobilerun.dating.stats import DatingStats

    uid = (user_id or "local").strip() or "local"
    get_user_setting, _save = _storage()
    try:
        blob = get_user_setting(uid, SETTING_NAME)
    except Exception:
        logger.exception("load dating_stats failed user=%s", uid)
        blob = None
    if isinstance(blob, dict) and blob:
        stats = DatingStats.from_dict(blob, stats_file=_default_file())
    else:
        # Migrate legacy ~/.mobilerun/dating_stats.json once if present
        try:
            stats = DatingStats.load(_default_file())
        except Exception:
            logger.exception("dating_stats local load failed; starting empty")
            stats = DatingStats(app_stats={}, stats_file=_default_file())
    try:
        stats.check_and_reset_daily()
    except Exception:
        # save() inside reset must not blow up the dashboard
        logger.exception("dating_stats check_and_reset_daily failed user=%s", uid)
    return stats


def save_dating_stats(stats, user_id: Optional[str] = None) -> None:
    """Persist DatingStats for a user + keep the local file in sync."""
    uid = (user_id or "local").strip() or "local"
    stats.recompute_today_totals()
    _get, save_user_setting = _storage()
    try:
        save_user_setting(uid, SETTING_NAME, stats.to_dict())
    except Exception:
        logger.exception("save dating_stats failed user=%s", uid)
    try:
        if not stats.stats_file:
            stats.stats_file = _default_file()
        stats.save()
    except Exception:
        logger.exception("save dating_stats local file failed")


def record_dating_messages(
    package_name: str,
    *,
    app_name: str = "",
    n: int = 1,
    user_id: Optional[str] = None,
) -> None:
    if n <= 0 or not package_name:
        return
    stats = load_dating_stats(user_id)
    stats.record_message(package_name, app_name or package_name, is_opener=True, n=n)
    save_dating_stats(stats, user_id)


def record_dating_swipes(
    package_name: str,
    *,
    app_name: str = "",
    liked: bool = True,
    n: int = 1,
    user_id: Optional[str] = None,
) -> None:
    if n <= 0 or not package_name:
        return
    stats = load_dating_stats(user_id)
    stats.record_swipe(package_name, app_name or package_name, liked=liked, n=n)
    save_dating_stats(stats, user_id)


def _int_done(blob: Any, *keys: str) -> int:
    """Best-effort int from a nested state dict (missing → 0)."""
    if not isinstance(blob, dict):
        return 0
    best = 0
    for k in keys:
        try:
            best = max(best, int(blob.get(k) or 0))
        except (TypeError, ValueError):
            continue
    return best


def _counter_snapshot(
    state: Dict[str, Any], job: Optional[Dict[str, Any]] = None
) -> Tuple[int, int]:
    """(messages_done, likes_or_swipes_done) from agent job state.

    Covers every Working fixed planner: Hinge/FB/Yubo/Hily use
    ``bulk_message_new`` / ``yubo_card`` / ``hily_run``; Tagged uses
    ``tagged_fixed.done`` (messages vs likes by run mode); Bumble/Badoo
    use ``bulk_swipe``. Nested Hily first-contact counters are included.
    """
    bulk = (
        state.get("bulk_message_new")
        if isinstance(state.get("bulk_message_new"), dict)
        else {}
    )
    yc = state.get("yubo_card") if isinstance(state.get("yubo_card"), dict) else {}
    hr = state.get("hily_run") if isinstance(state.get("hily_run"), dict) else {}
    hr_fc = hr.get("fc") if isinstance(hr.get("fc"), dict) else {}
    hr_fc_bulk = (
        hr_fc.get("bulk_message_new")
        if isinstance(hr_fc.get("bulk_message_new"), dict)
        else {}
    )
    swipe = state.get("bulk_swipe") if isinstance(state.get("bulk_swipe"), dict) else {}
    tagged = (
        state.get("tagged_fixed") if isinstance(state.get("tagged_fixed"), dict) else {}
    )
    tagged_done = _int_done(tagged, "done")
    # Tagged: auto message → messages; auto swipe → likes/swipes
    tagged_mode = ""
    if isinstance(job, dict):
        modes = job.get("run_modes") if isinstance(job.get("run_modes"), dict) else {}
        pkg = str(job.get("dating_app") or state.get("current_app") or "").strip()
        tagged_mode = str((modes or {}).get(pkg) or "").lower()
    if not tagged_mode:
        tagged_mode = str(tagged.get("mode") or tagged.get("phase") or "").lower()
    tagged_as_message = "message" in tagged_mode and "swipe" not in tagged_mode

    msgs = max(
        _int_done(bulk, "done"),
        _int_done(yc, "sent", "done"),
        _int_done(hr, "sent"),
        _int_done(hr_fc_bulk, "done"),
        _int_done(state, "live_messages_done", "openers_sent"),
        tagged_done if tagged_as_message else 0,
    )
    likes = max(
        _int_done(hr, "likes"),
        _int_done(swipe, "done"),
        _int_done(state, "live_likes_done", "swipes_done"),
        tagged_done if not tagged_as_message else 0,
    )
    return msgs, likes


def apply_job_totals_to_stats(
    stats,
    job: Dict[str, Any],
) -> bool:
    """Raise per-app today counts up to this job's final counter snapshot.

    Used when loading the dashboard so Today never under-reports a finished
    (or in-progress) live dating run whose step-sync was missed. Never
    decreases existing stats. Skips dry-run. Returns True if anything changed.
    """
    if not isinstance(job, dict):
        return False
    state = job.get("state") if isinstance(job.get("state"), dict) else {}
    if bool(job.get("dry_run") or state.get("dry_run")):
        return False
    pkg = str(
        job.get("dating_app")
        or state.get("current_app")
        or state.get("target_package")
        or ""
    ).strip()
    if not pkg:
        return False
    msgs, likes = _counter_snapshot(state, job)
    if msgs <= 0 and likes <= 0:
        return False
    try:
        from mobilerun.dating.config import display_name_for_package

        name = display_name_for_package(pkg, "")
    except Exception:
        name = pkg
    stats.check_and_reset_daily()
    app = stats.get_or_create_app_stats(name, pkg)
    changed = False
    if msgs > int(app.openers_sent_today or 0):
        delta = msgs - int(app.openers_sent_today or 0)
        app.openers_sent_today = msgs
        app.total_openers = int(app.total_openers or 0) + delta
        changed = True
    if likes > int(app.swipes_today or 0):
        delta = likes - int(app.swipes_today or 0)
        app.swipes_today = likes
        app.likes_today = max(int(app.likes_today or 0), likes)
        app.total_swipes = int(app.total_swipes or 0) + delta
        app.total_likes = int(app.total_likes or 0) + delta
        changed = True
    if changed:
        stats.recompute_today_totals()
    return changed


def merge_recent_dating_jobs_into_stats(
    stats, jobs: list, *, user_id: Optional[str] = None
) -> bool:
    """Apply finals from this owner's dating_run jobs onto ``stats``."""
    uid = (user_id or "").strip().lower()
    changed = False
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        if not (
            job.get("dating_run")
            or job.get("dating_app")
            or job.get("mode") == "dating"
        ):
            continue
        owner = str(job.get("user_id") or job.get("owner") or "").strip().lower()
        if uid and owner and owner != uid:
            continue
        if apply_job_totals_to_stats(stats, job):
            changed = True
    return changed


def sync_dating_stats_from_job(
    job: Dict[str, Any],
    *,
    before: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """Record deltas in job counters onto DatingStats. Returns the new snapshot.

    Skips dry-run jobs. Safe to call at the end of every agent/dating step.
    """
    state = job.get("state") if isinstance(job.get("state"), dict) else {}
    after = _counter_snapshot(state, job)
    if before is None:
        return after
    if bool(job.get("dry_run") or state.get("dry_run")):
        return after
    msg_delta = max(0, after[0] - before[0])
    like_delta = max(0, after[1] - before[1])
    if msg_delta == 0 and like_delta == 0:
        return after
    pkg = str(
        job.get("dating_app")
        or state.get("current_app")
        or state.get("target_package")
        or ""
    ).strip()
    if not pkg:
        return after
    uid = str(job.get("user_id") or job.get("owner") or "local")
    try:
        from mobilerun.dating.config import display_name_for_package

        name = display_name_for_package(pkg, "")
    except Exception:
        name = pkg
    try:
        if msg_delta:
            record_dating_messages(pkg, app_name=name, n=msg_delta, user_id=uid)
        if like_delta:
            record_dating_swipes(
                pkg, app_name=name, liked=True, n=like_delta, user_id=uid
            )
    except Exception:
        logger.exception(
            "dating stats sync failed pkg=%s msg=+%s like=+%s",
            pkg,
            msg_delta,
            like_delta,
        )
    return after
