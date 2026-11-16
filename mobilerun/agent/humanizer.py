"""Shared humanizer: fast but human-like pacing for Normal + Dating modes.

Presets (Balanced default):
  Fast     ~0.4–1.2s per action
  Balanced ~0.8–2.5s
  Careful  ~1.5–5s

Also provides tap jitter, curved swipes, per-character typing cadence,
and occasional idle "reading" pauses — no fixed intervals.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple


class SpeedPreset(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    CAREFUL = "careful"


class AgentMode(str, Enum):
    NORMAL = "normal"
    DATING = "dating"


# Inclusive (lo, hi) seconds for inter-action delays.
PRESET_ACTION_DELAYS: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (0.4, 1.2),
    SpeedPreset.BALANCED: (0.8, 2.5),
    SpeedPreset.CAREFUL: (1.5, 5.0),
}

PRESET_TYPING_CHAR_MS: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (30.0, 90.0),
    SpeedPreset.BALANCED: (50.0, 150.0),
    SpeedPreset.CAREFUL: (80.0, 220.0),
}

PRESET_IDLE_PAUSE: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (0.3, 1.0),
    SpeedPreset.BALANCED: (0.8, 2.5),
    SpeedPreset.CAREFUL: (1.5, 4.0),
}

PRESET_CACHE_TTL: dict[SpeedPreset, float] = {
    SpeedPreset.FAST: 0.8,
    SpeedPreset.BALANCED: 0.45,
    SpeedPreset.CAREFUL: 0.2,
}

PRESET_IDLE_CHANCE: dict[SpeedPreset, float] = {
    SpeedPreset.FAST: 0.05,
    SpeedPreset.BALANCED: 0.12,
    SpeedPreset.CAREFUL: 0.22,
}


@dataclass
class HumanizerConfig:
    """Configurable humanizer knobs (global, per-mode, or per-app)."""

    preset: SpeedPreset = SpeedPreset.BALANCED
    mode: AgentMode = AgentMode.NORMAL
    enabled: bool = True
    # Optional absolute overrides (seconds / ms); None → derive from preset
    action_delay_min: Optional[float] = None
    action_delay_max: Optional[float] = None
    typing_char_ms_min: Optional[float] = None
    typing_char_ms_max: Optional[float] = None
    tap_jitter_frac: float = 0.18  # fraction of element half-size
    swipe_curve_amp: float = 0.12  # lateral bulge relative to swipe length
    idle_chance: Optional[float] = None
    cache_ttl_seconds: Optional[float] = None
    skip_screenshot_when_tree_ok: bool = True
    # Dating tends to be slightly slower than normal at the same preset
    dating_delay_multiplier: float = 1.15

    def with_overrides(self, **kwargs) -> "HumanizerConfig":
        return replace(self, **kwargs)

    @classmethod
    def from_preset(
        cls,
        preset: str | SpeedPreset = SpeedPreset.BALANCED,
        mode: str | AgentMode = AgentMode.NORMAL,
        **kwargs,
    ) -> "HumanizerConfig":
        p = (
            preset
            if isinstance(preset, SpeedPreset)
            else SpeedPreset(str(preset).lower())
        )
        m = mode if isinstance(mode, AgentMode) else AgentMode(str(mode).lower())
        return cls(preset=p, mode=m, **kwargs)


@dataclass
class Humanizer:
    """Stateful humanizer (tracks last action time; never uses fixed intervals)."""

    config: HumanizerConfig = field(default_factory=HumanizerConfig)
    _rng: random.Random = field(default_factory=random.Random)
    _last_action_at: float = field(default_factory=lambda: 0.0)
    _actions_since_idle: int = 0

    # --- ranges ---------------------------------------------------------

    def action_delay_range(self) -> Tuple[float, float]:
        lo, hi = PRESET_ACTION_DELAYS[self.config.preset]
        if self.config.action_delay_min is not None:
            lo = self.config.action_delay_min
        if self.config.action_delay_max is not None:
            hi = self.config.action_delay_max
        if self.config.mode == AgentMode.DATING:
            mult = self.config.dating_delay_multiplier
            lo, hi = lo * mult, hi * mult
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    def typing_char_ms_range(self) -> Tuple[float, float]:
        lo, hi = PRESET_TYPING_CHAR_MS[self.config.preset]
        if self.config.typing_char_ms_min is not None:
            lo = self.config.typing_char_ms_min
        if self.config.typing_char_ms_max is not None:
            hi = self.config.typing_char_ms_max
        return (lo, hi) if hi >= lo else (hi, lo)

    def idle_chance(self) -> float:
        if self.config.idle_chance is not None:
            return self.config.idle_chance
        return PRESET_IDLE_CHANCE[self.config.preset]

    def cache_ttl(self) -> float:
        if self.config.cache_ttl_seconds is not None:
            return self.config.cache_ttl_seconds
        return PRESET_CACHE_TTL[self.config.preset]

    # --- sampling -------------------------------------------------------

    def _sample_skewed(self, lo: float, hi: float) -> float:
        """Gamma-ish sample inside [lo, hi] — not uniform, not fixed."""
        if not self.config.enabled:
            return lo
        if hi <= lo:
            return lo
        mean = (lo + hi) / 2.0
        shape = 2.2
        scale = mean / shape
        val = self._rng.gammavariate(shape, scale)
        # Jitter ±12% then clamp
        val *= 1.0 + self._rng.uniform(-0.12, 0.12)
        return max(lo, min(hi, val))

    def sample_action_delay(self) -> float:
        lo, hi = self.action_delay_range()
        return self._sample_skewed(lo, hi)

    def sample_idle_pause(self) -> float:
        lo, hi = PRESET_IDLE_PAUSE[self.config.preset]
        if self.config.mode == AgentMode.DATING:
            lo, hi = lo * 1.2, hi * 1.3
        return self._sample_skewed(lo, hi)

    def maybe_idle_pause(self) -> float:
        """Occasional reading pause; returns 0 most of the time."""
        self._actions_since_idle += 1
        if not self.config.enabled:
            return 0.0
        chance = self.idle_chance()
        # Slightly more likely after a burst of actions
        if self._actions_since_idle >= 4:
            chance = min(0.45, chance * 1.5)
        if self._rng.random() < chance:
            self._actions_since_idle = 0
            return self.sample_idle_pause()
        return 0.0

    async def wait_action_gap(self) -> float:
        """Async sleep for a human-like inter-action gap (+ optional idle)."""
        import asyncio

        delay = self.sample_action_delay()
        idle = self.maybe_idle_pause()
        total = delay + idle
        # Ensure we don't fire faster than the sampled gap since last action
        now = time.monotonic()
        if self._last_action_at:
            elapsed = now - self._last_action_at
            total = max(0.0, total - max(0.0, elapsed))
        if total > 0 and self.config.enabled:
            await asyncio.sleep(total)
        self._last_action_at = time.monotonic()
        return delay + idle

    # --- gestures -------------------------------------------------------

    def jitter_point(
        self,
        x: float,
        y: float,
        *,
        bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> Tuple[int, int]:
        """Jitter tap inside element bounds (or small radius around point)."""
        if not self.config.enabled:
            return int(round(x)), int(round(y))
        if bounds:
            left, top, right, bottom = bounds
            cx = (left + right) / 2.0
            cy = (top + bottom) / 2.0
            hw = max(1.0, (right - left) / 2.0)
            hh = max(1.0, (bottom - top) / 2.0)
            jx = cx + self._rng.uniform(
                -hw * self.config.tap_jitter_frac, hw * self.config.tap_jitter_frac
            )
            jy = cy + self._rng.uniform(
                -hh * self.config.tap_jitter_frac, hh * self.config.tap_jitter_frac
            )
            jx = max(left + 1, min(right - 1, jx))
            jy = max(top + 1, min(bottom - 1, jy))
            return int(round(jx)), int(round(jy))
        radius = 6.0 + 10.0 * self.config.tap_jitter_frac
        return (
            int(round(x + self._rng.uniform(-radius, radius))),
            int(round(y + self._rng.uniform(-radius, radius))),
        )

    def curved_swipe(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        steps: int = 5,
    ) -> List[Tuple[int, int]]:
        """Quadratic Bézier path with random lateral bulge + variable spacing."""
        if steps < 2:
            steps = 2
        mx = (x1 + x2) / 2.0
        my = (y1 + y2) / 2.0
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        # Perpendicular unit
        px, py = -dy / length, dx / length
        amp = length * self.config.swipe_curve_amp * self._rng.uniform(0.4, 1.0)
        if self._rng.random() < 0.5:
            amp = -amp
        cx, cy = mx + px * amp, my + py * amp
        points: List[Tuple[int, int]] = []
        # Non-uniform t samples (ease-in/out velocity feel)
        for i in range(steps + 1):
            u = i / steps
            # Ease: slow–fast–slow via smoothstep then slight noise
            t = u * u * (3 - 2 * u)
            t = min(1.0, max(0.0, t + self._rng.uniform(-0.03, 0.03)))
            bx = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t**2 * x2
            by = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t**2 * y2
            points.append((int(round(bx)), int(round(by))))
        return points

    def swipe_duration_ms(self, distance_px: float) -> int:
        """Variable velocity duration from distance + preset."""
        lo, hi = self.action_delay_range()
        # Map distance to a duration band; Faster presets → shorter ms
        base = 180 + distance_px * 0.35
        factor = {"fast": 0.7, "balanced": 1.0, "careful": 1.35}[
            self.config.preset.value
        ]
        dur = base * factor * self._rng.uniform(0.85, 1.2)
        # Keep loosely related to action delay scale
        dur = max(120.0, min(hi * 1000.0, dur))
        return int(dur)

    def typing_delays_ms(self, text: str) -> List[float]:
        """Per-character delays with occasional longer pauses (thinking)."""
        lo, hi = self.typing_char_ms_range()
        delays: List[float] = []
        for i, ch in enumerate(text):
            d = self._rng.uniform(lo, hi)
            if ch in " .,!?;:\n":
                d *= self._rng.uniform(1.4, 2.2)
            # Occasional pause mid-word / mid-sentence
            if i > 0 and self._rng.random() < 0.08:
                d += self._rng.uniform(120.0, 400.0)
            delays.append(d)
        return delays

    def typing_total_seconds(self, text: str) -> float:
        return sum(self.typing_delays_ms(text)) / 1000.0


def merge_app_humanizer(
    base: HumanizerConfig,
    *,
    min_swipe_delay_ms: Optional[int] = None,
    max_swipe_delay_ms: Optional[int] = None,
    min_typing_delay_ms: Optional[int] = None,
    max_typing_delay_ms: Optional[int] = None,
) -> HumanizerConfig:
    """Apply per-app delay overrides from dating AppProfile fields."""
    kwargs = {}
    if min_swipe_delay_ms is not None:
        kwargs["action_delay_min"] = min_swipe_delay_ms / 1000.0
    if max_swipe_delay_ms is not None:
        kwargs["action_delay_max"] = max_swipe_delay_ms / 1000.0
    if min_typing_delay_ms is not None:
        kwargs["typing_char_ms_min"] = float(min_typing_delay_ms)
    if max_typing_delay_ms is not None:
        kwargs["typing_char_ms_max"] = float(max_typing_delay_ms)
    return base.with_overrides(**kwargs) if kwargs else base


def describe_presets() -> dict:
    return {
        p.value: {
            "action_delay_s": PRESET_ACTION_DELAYS[p],
            "typing_char_ms": PRESET_TYPING_CHAR_MS[p],
            "idle_pause_s": PRESET_IDLE_PAUSE[p],
            "cache_ttl_s": PRESET_CACHE_TTL[p],
        }
        for p in SpeedPreset
    }
