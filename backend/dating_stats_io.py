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
    return Path.home() / ".mobilerun" / "dating_stats.json"


def load_dating_stats(user_id: Optional[str] = None):
    """Load DatingStats for a user (or the shared local file)."""
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
        stats = DatingStats.load(_default_file())
    stats.check_and_reset_daily()
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


def _counter_snapshot(state: Dict[str, Any]) -> Tuple[int, int]:
    """(messages_done, likes_or_swipes_done) from agent job state."""
    bulk = (
        state.get("bulk_message_new")
        if isinstance(state.get("bulk_message_new"), dict)
        else {}
    )
    yc = state.get("yubo_card") if isinstance(state.get("yubo_card"), dict) else {}
    hr = state.get("hily_run") if isinstance(state.get("hily_run"), dict) else {}
    swipe = state.get("bulk_swipe") if isinstance(state.get("bulk_swipe"), dict) else {}
    msgs = max(
        int(bulk.get("done") or 0),
        int(yc.get("sent") or 0),
        int(hr.get("sent") or 0),
        int(state.get("live_messages_done") or 0),
        int(state.get("openers_sent") or 0),
    )
    likes = max(
        int(hr.get("likes") or 0),
        int(swipe.get("done") or 0),
        int(state.get("live_likes_done") or 0),
        int(state.get("swipes_done") or 0),
    )
    return msgs, likes


def sync_dating_stats_from_job(
    job: Dict[str, Any],
    *,
    before: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """Record deltas in job counters onto DatingStats. Returns the new snapshot.

    Skips dry-run jobs. Safe to call at the end of every agent/dating step.
    """
    state = job.get("state") if isinstance(job.get("state"), dict) else {}
    after = _counter_snapshot(state)
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
