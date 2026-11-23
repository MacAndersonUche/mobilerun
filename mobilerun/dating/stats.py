"""Dating mode statistics tracking."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Optional  # noqa: F401 — Optional used by record_date_flow
from collections import defaultdict


@dataclass
class AppStats:
    """Statistics for a single app."""

    app_name: str
    package_name: str

    # Daily counts
    swipes_today: int = 0
    likes_today: int = 0
    openers_sent_today: int = 0  # Opening messages to new matches
    replies_sent_today: int = 0  # Replies to existing conversations

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
        """Reset daily counters (called at midnight)."""
        self.swipes_today = 0
        self.likes_today = 0
        self.openers_sent_today = 0
        self.replies_sent_today = 0
        # daily_opener_target is re-randomized separately


@dataclass
class DatingStats:
    """Overall dating mode statistics."""

    # Per-app stats
    app_stats: Dict[str, AppStats]

    # Global stats
    total_sessions: int = 0
    total_runtime_minutes: int = 0

    # Daily totals
    swipes_today_all: int = 0
    messages_today_all: int = 0

    # Metadata
    last_session_date: Optional[str] = None
    stats_file: Optional[Path] = None

    @classmethod
    def load(cls, stats_file: Path) -> "DatingStats":
        """Load stats from file."""
        if stats_file.exists():
            try:
                with open(stats_file) as f:
                    data = json.load(f)

                # Reconstruct app_stats
                app_stats = {}
                for pkg, stats_dict in data.get("app_stats", {}).items():
                    app_stats[pkg] = AppStats(**stats_dict)

                return cls(
                    app_stats=app_stats,
                    total_sessions=data.get("total_sessions", 0),
                    total_runtime_minutes=data.get("total_runtime_minutes", 0),
                    swipes_today_all=data.get("swipes_today_all", 0),
                    messages_today_all=data.get("messages_today_all", 0),
                    last_session_date=data.get("last_session_date"),
                    stats_file=stats_file,
                )
            except Exception as e:
                print(f"Failed to load stats: {e}, starting fresh")

        return cls(app_stats={}, stats_file=stats_file)

    def save(self):
        """Save stats to file."""
        if not self.stats_file:
            return

        self.stats_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "app_stats": {pkg: asdict(stats) for pkg, stats in self.app_stats.items()},
            "total_sessions": self.total_sessions,
            "total_runtime_minutes": self.total_runtime_minutes,
            "swipes_today_all": self.swipes_today_all,
            "messages_today_all": self.messages_today_all,
            "last_session_date": self.last_session_date,
            "saved_at": datetime.now().isoformat(),
        }

        with open(self.stats_file, "w") as f:
            json.dump(data, f, indent=2)

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
        """Check if it's a new day and reset daily counters."""
        today = date.today().isoformat()

        if self.last_session_date != today:
            # New day, reset all daily counters
            for stats in self.app_stats.values():
                stats.reset_daily_counts()

            self.swipes_today_all = 0
            self.messages_today_all = 0
            self.last_session_date = today
            self.save()

    def record_swipe(self, package_name: str, app_name: str, liked: bool = True):
        """Record a swipe."""
        stats = self.get_or_create_app_stats(app_name, package_name)
        stats.swipes_today += 1
        stats.total_swipes += 1

        if liked:
            stats.likes_today += 1
            stats.total_likes += 1

        self.swipes_today_all += 1
        stats.last_active = datetime.now().isoformat()

    def record_message(self, package_name: str, app_name: str, is_opener: bool = False):
        """Record a sent message (opener or reply)."""
        stats = self.get_or_create_app_stats(app_name, package_name)

        if is_opener:
            stats.openers_sent_today += 1
            stats.total_openers += 1
        else:
            stats.replies_sent_today += 1
            stats.total_replies += 1

        self.messages_today_all += 1
        stats.last_active = datetime.now().isoformat()

    def update_inbox_count(
        self, package_name: str, app_name: str, unread: int, new_matches: int = 0
    ):
        """Update inbox counts from app scraping."""
        stats = self.get_or_create_app_stats(app_name, package_name)
        stats.unread_messages = unread
        stats.new_matches = new_matches
        stats.last_stats_update = datetime.now().isoformat()

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
        stats.last_active = datetime.now().isoformat()

    def get_summary(self) -> Dict:
        """Get summary of all stats."""
        from mobilerun.dating.config import display_name_for_package

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
                        "replies": stats.replies_sent_today,
                        "total_messages": stats.openers_sent_today
                        + stats.replies_sent_today,
                    },
                    "targets": {
                        "opener_target": stats.daily_opener_target,
                        "opener_progress": stats.openers_sent_today,
                    },
                    "total": {
                        "swipes": stats.total_swipes,
                        "openers": stats.total_openers,
                        "replies": stats.total_replies,
                        "messages": stats.total_openers + stats.total_replies,
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
