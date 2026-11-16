"""Dating mode configuration and app profiles."""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import time


@dataclass
class AppProfile:
    """Configuration for a dating app."""

    name: str
    package_name: str
    daily_swipe_cap: int = 50
    daily_message_cap: int = 20
    daily_reply_cap: int = 50
    enabled: bool = True

    # Activity patterns
    min_swipe_delay_ms: int = 800
    max_swipe_delay_ms: int = 3000
    min_typing_delay_ms: int = 50
    max_typing_delay_ms: int = 150

    # Session limits
    max_swipes_per_session: int = 15
    max_messages_per_session: int = 5
    session_break_min_sec: int = 300  # 5 minutes
    session_break_max_sec: int = 900  # 15 minutes


# Default app profiles (Mac's dating folder)
DEFAULT_APPS = [
    AppProfile(
        name="Taimi",
        package_name="com.taimi.app",
    ),
    AppProfile(
        name="Bumble",
        package_name="com.bumble.app",
        daily_message_cap=10,  # Women message first
    ),
    AppProfile(
        name="Yubo",
        package_name="co.yellownw.yubo",
    ),
    AppProfile(
        name="Badoo",
        package_name="com.badoo.mobile",
    ),
    AppProfile(
        name="BLK",
        package_name="com.match.blk",
    ),
    AppProfile(
        name="Hily",
        package_name="com.hily.app",
    ),
    AppProfile(
        name="Hinge",
        package_name="co.hinge.app",
        daily_swipe_cap=30,  # Hinge has stricter limits
    ),
    AppProfile(
        name="Facebook",
        package_name="com.facebook.katana",
        daily_swipe_cap=20,  # Facebook Dating is more limited
        enabled=False,  # Disabled by default (not primarily dating)
    ),
    AppProfile(
        name="Snapchat",
        package_name="com.snapchat.android",
        enabled=False,  # Disabled by default
    ),
    AppProfile(
        name="Instagram",
        package_name="com.instagram.android",
        enabled=False,  # Disabled by default
    ),
]


@dataclass
class DatingModeConfig:
    """Overall dating mode configuration."""

    # App profiles
    apps: List[AppProfile] = field(default_factory=lambda: DEFAULT_APPS.copy())

    # Scheduling
    active_hours_start: time = time(9, 0)  # 9 AM
    active_hours_end: time = time(23, 0)  # 11 PM

    # Behavior
    review_before_send: bool = True
    human_like_delays: bool = True
    randomize_order: bool = True

    # Mode
    round_robin: bool = True  # vs "one app at a time"

    # Persona
    persona_prompt: str = """You are Mac, a confident and witty person looking for genuine connections.
Keep messages:
- Short and casual (2-3 sentences max)
- Natural and conversational  
- Show interest but not desperate
- Use light humor when appropriate
- Be authentic and direct
- Mirror their energy level

Avoid:
- Generic pickup lines
- Overly formal language
- Long paragraphs
- Being too forward
- Copy-paste vibes"""

    # Global limits (safety)
    max_total_swipes_per_day: int = 300
    max_total_messages_per_day: int = 100

    def get_enabled_apps(self) -> List[AppProfile]:
        """Get list of enabled apps."""
        return [app for app in self.apps if app.enabled]

    def get_app_by_package(self, package_name: str) -> Optional[AppProfile]:
        """Get app profile by package name."""
        return next(
            (app for app in self.apps if app.package_name == package_name), None
        )
