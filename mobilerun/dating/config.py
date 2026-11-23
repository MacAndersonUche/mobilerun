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
    daily_reply_cap: int = 50
    enabled: bool = True
    # Parked: do not run this app in routine jobs at all (e.g. Hinge — its
    # Discover/Matches screens expose almost no accessibility tree, so likes
    # cannot be verified except by a supervised live test). A parked app can
    # only run via its explicit live-test mode, never by accident.
    parked: bool = False

    # Opening messages (new matches)
    daily_opener_target_min: int = 50  # Randomized target range
    daily_opener_target_max: int = 100

    # Daily cap on messages sent on Discover (new contacts), counted on
    # VERIFIED sends only. None = unlimited. Mac's numbers (23 Nov 2026):
    # Hinge 50-100 (default 50, safe end), Hily 5/day, BLK / Yubo /
    # Facebook Dating unlimited. Bumble, Badoo, Tagged: no number given, so
    # no cap is set here — do not invent one. Mirrors
    # backend/discover_caps.py; tests/test_discover_caps.py asserts they agree.
    daily_discover_message_cap: Optional[int] = None
    daily_discover_message_cap_min: Optional[int] = None
    daily_discover_message_cap_max: Optional[int] = None

    # Activity patterns
    min_swipe_delay_ms: int = 800
    max_swipe_delay_ms: int = 3000
    min_typing_delay_ms: int = 50
    max_typing_delay_ms: int = 150

    # Sequential message delays (between conversations)
    min_conversation_gap_sec: int = 30  # 30 seconds between conversations
    max_conversation_gap_sec: int = 180  # 3 minutes between conversations

    # Session limits
    max_swipes_per_session: int = 15
    max_messages_per_session: int = 5
    session_break_min_sec: int = 300  # 5 minutes
    session_break_max_sec: int = 900  # 15 minutes

    # First-contact openers: "templates" | "ai" | None (inherit global)
    opener_mode: Optional[str] = None


# Default app profiles (Mac's dating folder)
DEFAULT_APPS = [
    AppProfile(
        name="Taimi",
        package_name="com.takimi.android",  # real package (not com.taimi.app)
        # Unsupported: Taimi sets FLAG_SECURE, so screenshots come back black
        # and the screen cannot be read at all. No code fix can work around
        # that — dropped from the rotation entirely.
        enabled=False,
    ),
    AppProfile(
        name="Bumble",
        package_name="com.bumble.app",
        daily_opener_target_min=20,  # Women message first (lower opener target)
        daily_opener_target_max=40,
    ),
    AppProfile(
        name="Yubo",
        package_name="co.yellw.yellowapp",  # real package
    ),
    AppProfile(
        name="Badoo",
        package_name="com.badoo.mobile",
    ),
    AppProfile(
        name="BLK",
        package_name="com.affinityapps.blk",  # real package
    ),
    AppProfile(
        name="Hily",
        package_name="com.hily.app",
        # Discover message cap (Mac, 23 Nov 2026): 5 verified sends/day.
        daily_discover_message_cap=5,
        daily_discover_message_cap_min=5,
        daily_discover_message_cap_max=5,
    ),
    AppProfile(
        name="Hinge",
        package_name="co.hinge.app",
        daily_swipe_cap=30,  # Hinge has stricter limits
        daily_opener_target_min=30,
        daily_opener_target_max=60,
        # Discover message cap (Mac, 23 Nov 2026): configurable 50-100/day,
        # defaulting to 50, the safe end.
        daily_discover_message_cap=50,
        daily_discover_message_cap_min=50,
        daily_discover_message_cap_max=100,
        # Parked (23 Nov): Discover/Matches are effectively blind — likes
        # can only be proven by the supervised one-live-like test, never by
        # routine live jobs. Dry runs stay available as the safe simulation.
        parked=True,
    ),
    AppProfile(
        name="Tagged",
        package_name="com.taggedapp",
        daily_swipe_cap=40,
        daily_opener_target_min=20,
        daily_opener_target_max=50,
    ),
    AppProfile(
        name="WhatsApp",
        package_name="com.whatsapp",
        daily_swipe_cap=0,
        enabled=True,
    ),
    AppProfile(
        name="Facebook",
        package_name="com.facebook.katana",
        daily_swipe_cap=20,  # Facebook Dating is more limited
        daily_opener_target_min=20,
        daily_opener_target_max=40,
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


def discover_message_cap_for(profile: AppProfile) -> Optional[int]:
    """Effective daily Discover cap for a profile (None = unlimited)."""
    return profile.daily_discover_message_cap


def clamp_discover_message_cap(profile: AppProfile, value: int) -> Optional[int]:
    """Clamp a requested Discover cap into the profile's range."""
    low = profile.daily_discover_message_cap_min
    high = profile.daily_discover_message_cap_max
    if low is None or high is None:
        return None
    return max(low, min(high, int(value)))


def discover_messages_allowed(profile: AppProfile, sent_today: int) -> bool:
    """True if one more verified Discover send is allowed today."""
    cap = discover_message_cap_for(profile)
    if cap is None:
        return True
    return int(sent_today) < cap


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
    # Shared humanizer preset (fast | balanced | careful) — Balanced default
    speed_preset: str = "balanced"
    randomize_order: bool = True
    sequential_messaging: bool = True  # Process one conversation at a time

    # First-contact openers: Templates (no LLM) | AI
    opener_mode: str = "templates"  # templates | ai

    # Mode
    round_robin: bool = True  # vs "one app at a time"

    # Persona (legacy / AI openers)
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

    # Reply persona + date flow (AI replies to existing chats)
    reply_persona_prompt: str = (
        "You are Mac. Keep replies warm and genuine — get to know her, ask about her "
        "day and interests, offer sincere compliments, stay respectful. "
        "No sexual content, no pressure, no pushiness. Short and natural (1–3 sentences)."
    )
    invite_days_min: int = 3
    invite_days_max: int = 7
    home_location: str = "Stoke-on-Trent"
    radius_miles: float = 50.0
    invite_enabled: bool = True
    handoff_enabled: bool = True
    calendar_on_handoff: bool = True

    # Global limits (safety)
    max_total_swipes_per_day: int = 300

    # Global messaging caps (openers + replies across all apps)
    min_total_messages_per_day: int = 100
    max_total_messages_per_day: int = 500

    def get_enabled_apps(self) -> List[AppProfile]:
        """Get list of enabled apps (parked apps never run routinely)."""
        return [app for app in self.apps if app.enabled and not app.parked]

    def get_parked_apps(self) -> List[AppProfile]:
        """Apps parked from routine jobs (live-test mode only)."""
        return [app for app in self.apps if app.parked]

    def get_app_by_package(self, package_name: str) -> Optional[AppProfile]:
        """Get app profile by package name."""
        return next(
            (app for app in self.apps if app.package_name == package_name), None
        )

    def get_daily_message_target(self) -> int:
        """Get randomized daily message target within configured range."""
        import random

        return random.randint(
            self.min_total_messages_per_day, self.max_total_messages_per_day
        )
