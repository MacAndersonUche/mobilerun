"""Human-like scheduling and pacing for dating mode."""

import random
import time as time_module
from datetime import datetime, time
from typing import Optional
import math

from mobilerun.agent.humanizer import (
    AgentMode,
    Humanizer,
    HumanizerConfig,
    merge_app_humanizer,
)


class DatingScheduler:
    """Manages human-like timing and scheduling (delegates gestures to Humanizer)."""

    def __init__(
        self,
        active_hours_start: time = time(9, 0),
        active_hours_end: time = time(23, 0),
        human_like: bool = True,
        speed_preset: str = "balanced",
        humanizer: Optional[Humanizer] = None,
    ):
        self.active_hours_start = active_hours_start
        self.active_hours_end = active_hours_end
        self.human_like = human_like
        self.speed_preset = speed_preset
        self.humanizer = humanizer or Humanizer(
            config=HumanizerConfig.from_preset(
                speed_preset, AgentMode.DATING, enabled=human_like
            )
        )

        # Session state
        self.current_session_swipes = 0
        self.current_session_messages = 0
        self.session_start_time = None

    def apply_app_profile(
        self,
        *,
        min_swipe_delay_ms: int,
        max_swipe_delay_ms: int,
        min_typing_delay_ms: int,
        max_typing_delay_ms: int,
    ) -> None:
        """Per-app delay overrides on top of the shared preset."""
        self.humanizer.config = merge_app_humanizer(
            self.humanizer.config,
            min_swipe_delay_ms=min_swipe_delay_ms,
            max_swipe_delay_ms=max_swipe_delay_ms,
            min_typing_delay_ms=min_typing_delay_ms,
            max_typing_delay_ms=max_typing_delay_ms,
        )

    def is_within_active_hours(self) -> bool:
        """Check if current time is within active hours."""
        now = datetime.now().time()

        if self.active_hours_start <= self.active_hours_end:
            return self.active_hours_start <= now <= self.active_hours_end
        else:
            # Crosses midnight
            return now >= self.active_hours_start or now <= self.active_hours_end

    def should_take_break(
        self,
        swipes_in_session: int,
        messages_in_session: int,
        max_swipes: int = 15,
        max_messages: int = 5,
    ) -> bool:
        """Determine if agent should take a break."""
        if not self.human_like:
            return False

        # Break after hitting session limits
        if swipes_in_session >= max_swipes or messages_in_session >= max_messages:
            return True

        # Random breaks (10% chance after 5+ actions)
        if swipes_in_session + messages_in_session >= 5:
            if random.random() < 0.10:
                return True

        return False

    def get_break_duration(self, min_sec: int = 300, max_sec: int = 900) -> int:
        """Get break duration in seconds with human-like variation."""
        if not self.human_like:
            return min_sec

        # Log-normal distribution for more realistic breaks
        # Most breaks are short, some are longer
        mean_log = math.log((min_sec + max_sec) / 2)
        sigma = 0.5

        duration = int(random.lognormvariate(mean_log, sigma))
        return max(min_sec, min(duration, max_sec))

    def get_swipe_delay(self, min_ms: int = 800, max_ms: int = 3000) -> float:
        """Get delay between swipes in seconds with natural variation."""
        if not self.human_like:
            return min_ms / 1000.0
        # Prefer shared humanizer ranges; fall back to explicit ms window
        cfg = self.humanizer.config.with_overrides(
            action_delay_min=min_ms / 1000.0,
            action_delay_max=max_ms / 1000.0,
        )
        return Humanizer(config=cfg, _rng=self.humanizer._rng).sample_action_delay()

    def get_typing_delay(self, text: str, min_ms: int = 50, max_ms: int = 150) -> float:
        """Get delay for typing a message (simulates human typing speed)."""
        if not self.human_like:
            return 0.5
        cfg = self.humanizer.config.with_overrides(
            typing_char_ms_min=float(min_ms),
            typing_char_ms_max=float(max_ms),
        )
        h = Humanizer(config=cfg, _rng=self.humanizer._rng)
        # Thinking pause + per-char cadence
        think = (
            h.sample_idle_pause() if h.idle_chance() > 0 else random.uniform(0.4, 1.2)
        )
        return think + h.typing_total_seconds(text)

    def get_swipe_curve(self, distance: int) -> list:
        """Generate a natural swipe curve with jitter."""
        if not self.human_like:
            return [(i * distance // 10, 0) for i in range(11)]
        path = self.humanizer.curved_swipe(
            0, 0, distance, 0, steps=random.randint(8, 14)
        )
        # Return relative (x, y) like the legacy API
        return [(x, y) for x, y in path]

    def start_session(self):
        """Start a new session."""
        self.session_start_time = time_module.time()
        self.current_session_swipes = 0
        self.current_session_messages = 0

    def record_swipe(self):
        """Record a swipe in current session."""
        self.current_session_swipes += 1

    def record_message(self):
        """Record a message in current session."""
        self.current_session_messages += 1

    def get_session_duration(self) -> float:
        """Get current session duration in minutes."""
        if not self.session_start_time:
            return 0.0

        return (time_module.time() - self.session_start_time) / 60.0

    def reset_session(self):
        """Reset session counters."""
        self.current_session_swipes = 0
        self.current_session_messages = 0
        self.session_start_time = None
