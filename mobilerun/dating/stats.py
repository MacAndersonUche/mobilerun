"""Dating mode statistics tracking."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

# Mac is in Europe/London — "today" on the dashboard uses London midnight,
# not the Lambda host's UTC calendar date.
LONDON = ZoneInfo("Europe/London")


def london_today() -> str:
    """ISO date (YYYY-MM-DD) for Europe/London right now."""
    return datetime.now(LONDON).date().isoformat()


def london_now_iso() -> str:
    return datetime.now(LONDON).isoformat()


@dataclass
class AppStats:
    """Statistics for a single app."""

    app_name: str
    package_name: str

    # Daily counts
    swipes_today: int = 0
    likes_today: int = 0
    openers_sent_today: int = 0  # First-contact / send messages
    replies_sent_today: int = 0  # Legacy; dating runs no longer track replies

    # Totals
    total_swipes: int = 0
    total_likes: int = 0
    total_openers: int = 0
    total_replies: int = 0
    total_matches: int = 0

    # Date-flow
    chats_active: int = 0
    invites_sent: int = 0
    dates_booked: int = 0

    # Current state
    unread_messages: int = 0
    new_matches: int = 0

    # Targets & caps
    daily_opener_target: int = 0  # Randomized target for today

    # Last activity
    last_active: Optional[str] = None
    last_stats_update: Optional[str] = None

    def reset_daily_counts(self):
        """Reset daily counters (called at London midnight)."""
        self.swipes_today = 0
        self.likes_today = 0
        self.openers_sent_today = 0
        self.replies_sent_today = 0


@dataclass
class DatingStats:
    """Overall dating mode statistics."""

    # Per-app stats
    app_stats: Dict[str, AppStats]

    # Global stats
    total_sessions: int = 0
    total_runtime_minutes: int = 0

    # Daily totals (kept in sync; get_summary recomputes from apps)
    swipes_today_all: int = 0
    messages_today_all: int = 0

    # Metadata
    last_session_date: Optional[str] = None
    stats_file: Optional[Path] = None

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], *, stats_file: Optional[Path] = None
    ) -> "DatingStats":
        app_stats: Dict[str, AppStats] = {}
        for pkg, stats_dict in (data.get("app_stats") or {}).items():
            if not isinstance(stats_dict, dict):
                continue
            # Drop unknown keys so older/newer blobs still load
            known = {f.name for f in AppStats.__dataclass_fields__.values()}  # type: ignore[attr-defined]
            cleaned = {k: v for k, v in stats_dict.items() if k in known}
            cleaned.setdefault("app_name", "")
            cleaned.setdefault("package_name", pkg)
            app_stats[pkg] = AppStats(**cleaned)
        return cls(
            app_stats=app_stats,
            total_sessions=int(data.get("total_sessions") or 0),
            total_runtime_minutes=int(data.get("total_runtime_minutes") or 0),
            swipes_today_all=int(data.get("swipes_today_all") or 0),
            messages_today_all=int(data.get("messages_today_all") or 0),
            last_session_date=data.get("last_session_date"),
            stats_file=stats_file,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_stats": {pkg: asdict(stats) for pkg, stats in self.app_stats.items()},
            "total_sessions": self.total_sessions,
            "total_runtime_minutes": self.total_runtime_minutes,
            "swipes_today_all": self.swipes_today_all,
            "messages_today_all": self.messages_today_all,
            "last_session_date": self.last_session_date,
            "saved_at": london_now_iso(),
        }

    @classmethod
    def load(cls, stats_file: Path) -> "DatingStats":
        """Load stats from a local JSON file (dev / offline)."""
        if stats_file.exists():
            try:
                with open(stats_file) as f:
                    data = json.load(f)
                return cls.from_dict(data, stats_file=stats_file)
            except Exception as e:
                print(f"Failed to load stats: {e}, starting fresh")

        return cls(app_stats={}, stats_file=stats_file)

    def save(self):
        """Save stats to the local file when one is configured.

        Never raises — Lambda's home dir is not writable; durable stats live
        in Dynamo via dating_stats_io.save_dating_stats. A local write failure
        must not 500 GET /api/dating/stats (dashboard load).
        """
        if not self.stats_file:
            return
        try:
            self.stats_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.stats_file, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
        except OSError:
            # Read-only FS (AWS Lambda) or full disk — ignore.
            pass

    def get_or_create_app_stats(self, app_name: str, package_name: str) -> AppStats:
        """Get or create stats for an app."""
        from mobilerun.dating.config import display_name_for_package

        resolved = display_name_for_package(package_name, app_name)
        if package_name not in self.app_stats:
            self.app_stats[package_name] = AppStats(
                app_name=resolved,
                package_name=package_name,
            )
        elif not (self.app_stats[package_name].app_name or "").strip():
            self.app_stats[package_name].app_name = resolved
        return self.app_stats[package_name]

    def check_and_reset_daily(self):
        """Reset daily counters when the London calendar day rolls over."""
        today = london_today()

        if self.last_session_date != today:
            for stats in self.app_stats.values():
                stats.reset_daily_counts()

            self.swipes_today_all = 0
            self.messages_today_all = 0
            self.last_session_date = today
            self.save()

    def recompute_today_totals(self) -> None:
        """Globals = sum of per-app today (messages = openers only)."""
        self.swipes_today_all = sum(s.swipes_today for s in self.app_stats.values())
        self.messages_today_all = sum(
            s.openers_sent_today for s in self.app_stats.values()
        )

    def record_swipe(
        self, package_name: str, app_name: str, liked: bool = True, n: int = 1
    ):
        """Record one or more swipes/likes."""
        self.check_and_reset_daily()
        stats = self.get_or_create_app_stats(app_name, package_name)
        n = max(0, int(n))
        stats.swipes_today += n
        stats.total_swipes += n
        if liked:
            stats.likes_today += n
            stats.total_likes += n
        self.recompute_today_totals()
        stats.last_active = london_now_iso()

    def record_message(
        self,
        package_name: str,
        app_name: str,
        is_opener: bool = True,
        n: int = 1,
    ):
        """Record sent first-contact message(s). Replies are no longer tracked."""
        self.check_and_reset_daily()
        stats = self.get_or_create_app_stats(app_name, package_name)
        n = max(0, int(n))
        # Dating dashboard only counts first-contact / send messages.
        # Reply tracking was removed — is_opener is kept for call-site compat.
        _ = is_opener
        stats.openers_sent_today += n
        stats.total_openers += n
        self.recompute_today_totals()
        stats.last_active = london_now_iso()

    def update_inbox_count(
        self, package_name: str, app_name: str, unread: int, new_matches: int = 0
    ):
        """Update inbox counts from app scraping."""
        stats = self.get_or_create_app_stats(app_name, package_name)
        stats.unread_messages = unread
        stats.new_matches = new_matches
        stats.last_stats_update = london_now_iso()

    def set_daily_opener_target(self, package_name: str, app_name: str, target: int):
        """Set randomized daily opener target for an app."""
        stats = self.get_or_create_app_stats(app_name, package_name)
        stats.daily_opener_target = target

    def record_date_flow(
        self,
        package_name: str,
        app_name: str,
        *,
        chats_active: Optional[int] = None,
        invite_sent: bool = False,
        date_booked: bool = False,
    ):
        """Update date-flow counters for an app."""
        stats = self.get_or_create_app_stats(app_name, package_name)
        if chats_active is not None:
            stats.chats_active = max(0, int(chats_active))
        if invite_sent:
            stats.invites_sent += 1
        if date_booked:
            stats.dates_booked += 1
        stats.last_active = london_now_iso()

    def get_summary(self) -> Dict:
        """Get summary of all stats. Today totals = sum of per-app today."""
        from mobilerun.dating.config import display_name_for_package

        self.check_and_reset_daily()
        self.recompute_today_totals()

        return {
            "total_sessions": self.total_sessions,
            "total_runtime_minutes": self.total_runtime_minutes,
            "today": {
                "swipes": self.swipes_today_all,
                "messages": self.messages_today_all,
            },
            "apps": [
                {
                    "name": display_name_for_package(
                        stats.package_name, stats.app_name
                    ),
                    "package": stats.package_name,
                    "today": {
                        "swipes": stats.swipes_today,
                        "likes": stats.likes_today,
                        "openers": stats.openers_sent_today,
                        # Reply tracking removed — always 0 for the dashboard
                        "replies": 0,
                        "total_messages": stats.openers_sent_today,
                    },
                    "targets": {
                        "opener_target": stats.daily_opener_target,
                        "opener_progress": stats.openers_sent_today,
                    },
                    "total": {
                        "swipes": stats.total_swipes,
                        "openers": stats.total_openers,
                        "replies": 0,
                        "messages": stats.total_openers,
                        "matches": stats.total_matches,
                    },
                    "date_flow": {
                        "chats_active": stats.chats_active,
                        "invites_sent": stats.invites_sent,
                        "dates_booked": stats.dates_booked,
                    },
                    "inbox": {
                        "unread": stats.unread_messages,
                        "new_matches": stats.new_matches,
                    },
                    "last_active": stats.last_active,
                }
                for stats in self.app_stats.values()
            ],
        }
