"""Human-like scheduling and pacing for dating mode."""

import random
import time as time_module
from datetime import datetime, time
from typing import Optional
import math


class DatingScheduler:
    """Manages human-like timing and scheduling."""

    def __init__(
        self,
        active_hours_start: time = time(9, 0),
        active_hours_end: time = time(23, 0),
        human_like: bool = True,
    ):
        self.active_hours_start = active_hours_start
        self.active_hours_end = active_hours_end
        self.human_like = human_like

        # Session state
        self.current_session_swipes = 0
        self.current_session_messages = 0
        self.session_start_time = None

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

        # Gamma distribution for swipe timing (more realistic than uniform)
        shape = 2.0  # Makes it more bell-curved
        scale = (min_ms + max_ms) / 2 / shape

        delay_ms = random.gammavariate(shape, scale)
        delay_ms = max(min_ms, min(delay_ms, max_ms))

        # Add small random jitter (±10%)
        jitter = delay_ms * random.uniform(-0.1, 0.1)

        return (delay_ms + jitter) / 1000.0

    def get_typing_delay(self, text: str, min_ms: int = 50, max_ms: int = 150) -> float:
        """Get delay for typing a message (simulates human typing speed)."""
        if not self.human_like:
            return 0.5

        # Base typing delay per character
        chars = len(text)

        # Typing speed: 40-60 WPM = ~200-300 chars/min = ~3-5 chars/sec
        # So per char: ~0.2-0.33 seconds
        base_delay_per_char = random.uniform(0.18, 0.35)

        # Total typing time
        typing_time = chars * base_delay_per_char

        # Add thinking pause at the beginning (1-3 seconds)
        thinking_pause = random.uniform(1.0, 3.0)

        return thinking_pause + typing_time

    def get_swipe_curve(self, distance: int) -> list:
        """Generate a natural swipe curve with jitter."""
        if not self.human_like:
            # Simple linear path
            return [(i * distance // 10, 0) for i in range(11)]

        # Bezier-like curve with jitter
        points = []
        num_points = random.randint(8, 15)

        for i in range(num_points + 1):
            progress = i / num_points

            # Ease-in-out curve
            if progress < 0.5:
                smooth = 2 * progress * progress
            else:
                smooth = 1 - pow(-2 * progress + 2, 2) / 2

            x = int(smooth * distance)

            # Add jitter (±5 pixels)
            jitter_x = random.randint(-5, 5)
            jitter_y = random.randint(-3, 3)

            points.append((x + jitter_x, jitter_y))

        return points

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
