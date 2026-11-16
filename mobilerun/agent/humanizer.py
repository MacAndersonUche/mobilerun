"""Shared humanizer: randomised human-like pacing for Normal + Dating + Social.

Presets (Balanced default) — wider bands, log-normal sampling (never fixed):
  Fast     ~0.3–1.8s per action (core), occasional longer idle
  Balanced ~0.6–3.5s
  Careful  ~1.2–7.0s

Also: micro-pauses, rare long breaks, per-message typing speed, tap jitter,
curved swipes, randomised session windows, shuffled app/conversation order.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time as dtime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")


class SpeedPreset(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    CAREFUL = "careful"


class AgentMode(str, Enum):
    NORMAL = "normal"
    DATING = "dating"
    SOCIAL = "social"


# Inclusive (lo, hi) seconds for inter-action delays (wider than v1).
PRESET_ACTION_DELAYS: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (0.3, 1.8),
    SpeedPreset.BALANCED: (0.6, 3.5),
    SpeedPreset.CAREFUL: (1.2, 7.0),
}

PRESET_TYPING_CHAR_MS: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (25.0, 110.0),
    SpeedPreset.BALANCED: (40.0, 180.0),
    SpeedPreset.CAREFUL: (70.0, 280.0),
}

PRESET_IDLE_PAUSE: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (0.25, 1.4),
    SpeedPreset.BALANCED: (0.6, 3.2),
    SpeedPreset.CAREFUL: (1.2, 5.5),
}

# Rare longer "walk away" breaks (seconds)
PRESET_LONG_BREAK: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (8.0, 45.0),
    SpeedPreset.BALANCED: (20.0, 120.0),
    SpeedPreset.CAREFUL: (45.0, 300.0),
}

PRESET_CACHE_TTL: dict[SpeedPreset, float] = {
    SpeedPreset.FAST: 0.8,
    SpeedPreset.BALANCED: 0.45,
    SpeedPreset.CAREFUL: 0.2,
}

PRESET_IDLE_CHANCE: dict[SpeedPreset, float] = {
    SpeedPreset.FAST: 0.08,
    SpeedPreset.BALANCED: 0.16,
    SpeedPreset.CAREFUL: 0.28,
}

PRESET_MICRO_PAUSE_CHANCE: dict[SpeedPreset, float] = {
    SpeedPreset.FAST: 0.12,
    SpeedPreset.BALANCED: 0.22,
    SpeedPreset.CAREFUL: 0.35,
}

PRESET_LONG_BREAK_CHANCE: dict[SpeedPreset, float] = {
    SpeedPreset.FAST: 0.02,
    SpeedPreset.BALANCED: 0.04,
    SpeedPreset.CAREFUL: 0.07,
}

# Inter-message / step-worker gaps (seconds) — log-normal, never fixed
PRESET_MESSAGE_GAP: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (18.0, 95.0),
    SpeedPreset.BALANCED: (28.0, 180.0),
    SpeedPreset.CAREFUL: (45.0, 320.0),
}

PRESET_SWIPE_STEP_GAP: dict[SpeedPreset, Tuple[float, float]] = {
    SpeedPreset.FAST: (1.2, 6.0),
    SpeedPreset.BALANCED: (2.0, 10.0),
    SpeedPreset.CAREFUL: (3.5, 18.0),
}


@dataclass
class HumanizerConfig:
    """Configurable humanizer knobs (global, per-mode, or per-app)."""

    preset: SpeedPreset = SpeedPreset.BALANCED
    mode: AgentMode = AgentMode.NORMAL
    enabled: bool = True
    # Absolute overrides (seconds / ms); None → derive from preset
    action_delay_min: Optional[float] = None
    action_delay_max: Optional[float] = None
    typing_char_ms_min: Optional[float] = None
    typing_char_ms_max: Optional[float] = None
    tap_jitter_frac: float = 0.22
    swipe_curve_amp: float = 0.14
    idle_chance: Optional[float] = None
    micro_pause_chance: Optional[float] = None
    long_break_chance: Optional[float] = None
    cache_ttl_seconds: Optional[float] = None
    skip_screenshot_when_tree_ok: bool = True
    dating_delay_multiplier: float = 1.18
    social_delay_multiplier: float = 1.08
    # Log-normal sigma (higher = heavier tail / more variance)
    delay_sigma: float = 0.55
    # Absolute overrides for step-worker / inter-message gaps (seconds)
    message_gap_min: Optional[float] = None
    message_gap_max: Optional[float] = None
    swipe_step_gap_min: Optional[float] = None
    swipe_step_gap_max: Optional[float] = None
    # Session window: randomize start/end within active hours (minutes)
    session_start_jitter_min: int = 0
    session_start_jitter_max: int = 45
    session_end_early_min: int = 0
    session_end_early_max: int = 35
    shuffle_apps: bool = True
    shuffle_conversations: bool = True

    def with_overrides(self, **kwargs) -> "HumanizerConfig":
        return replace(self, **kwargs)

    def to_public_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["preset"] = self.preset.value
        d["mode"] = self.mode.value
        return d

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanizerConfig":
        raw = dict(data or {})
        preset = raw.pop("preset", "balanced")
        mode = raw.pop("mode", "normal")
        # Drop unknown keys quietly
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        filtered = {k: v for k, v in raw.items() if k in known}
        return cls.from_preset(preset, mode, **filtered)


@dataclass
class Humanizer:
    """Stateful humanizer — never uses fixed intervals."""

    config: HumanizerConfig = field(default_factory=HumanizerConfig)
    _rng: random.Random = field(default_factory=random.Random)
    _last_action_at: float = field(default_factory=lambda: 0.0)
    _actions_since_idle: int = 0
    _message_typing_factor: float = 1.0

    # --- ranges ---------------------------------------------------------

    def _mode_mult(self) -> float:
        if self.config.mode == AgentMode.DATING:
            return self.config.dating_delay_multiplier
        if self.config.mode == AgentMode.SOCIAL:
            return self.config.social_delay_multiplier
        return 1.0

    def action_delay_range(self) -> Tuple[float, float]:
        lo, hi = PRESET_ACTION_DELAYS[self.config.preset]
        if self.config.action_delay_min is not None:
            lo = self.config.action_delay_min
        if self.config.action_delay_max is not None:
            hi = self.config.action_delay_max
        mult = self._mode_mult()
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

    def micro_pause_chance(self) -> float:
        if self.config.micro_pause_chance is not None:
            return self.config.micro_pause_chance
        return PRESET_MICRO_PAUSE_CHANCE[self.config.preset]

    def long_break_chance(self) -> float:
        if self.config.long_break_chance is not None:
            return self.config.long_break_chance
        return PRESET_LONG_BREAK_CHANCE[self.config.preset]

    def cache_ttl(self) -> float:
        if self.config.cache_ttl_seconds is not None:
            return self.config.cache_ttl_seconds
        return PRESET_CACHE_TTL[self.config.preset]

    # --- sampling -------------------------------------------------------

    def _sample_lognormal(self, lo: float, hi: float) -> float:
        """Log-normal sample clamped to [lo, hi] — heavy tail, non-uniform."""
        if not self.config.enabled:
            return lo
        if hi <= lo:
            return lo
        # Geometric mean as center of mass
        mu = math.log(max(1e-6, math.sqrt(lo * hi)))
        sigma = max(0.15, float(self.config.delay_sigma))
        val = self._rng.lognormvariate(mu, sigma)
        # Extra multiplicative jitter
        val *= self._rng.uniform(0.88, 1.18)
        return max(lo, min(hi, val))

    def sample_action_delay(self) -> float:
        lo, hi = self.action_delay_range()
        delay = self._sample_lognormal(lo, hi)
        # Random micro-pause appended sometimes
        if self._rng.random() < self.micro_pause_chance():
            delay += self._rng.uniform(0.05, 0.35) * self._mode_mult()
        return delay

    def sample_idle_pause(self) -> float:
        lo, hi = PRESET_IDLE_PAUSE[self.config.preset]
        mult = self._mode_mult()
        return self._sample_lognormal(lo * mult, hi * mult)

    def sample_long_break(self) -> float:
        lo, hi = PRESET_LONG_BREAK[self.config.preset]
        return self._sample_lognormal(lo, hi)

    def maybe_idle_pause(self) -> float:
        """Occasional reading pause; returns 0 most of the time."""
        self._actions_since_idle += 1
        if not self.config.enabled:
            return 0.0
        chance = self.idle_chance()
        if self._actions_since_idle >= 4:
            chance = min(0.55, chance * 1.6)
        if self._rng.random() < chance:
            self._actions_since_idle = 0
            return self.sample_idle_pause()
        return 0.0

    def maybe_long_break(self) -> float:
        """Rare longer break (coffee / distraction)."""
        if not self.config.enabled:
            return 0.0
        if self._rng.random() < self.long_break_chance():
            self._actions_since_idle = 0
            return self.sample_long_break()
        return 0.0

    def message_gap_range(self) -> Tuple[float, float]:
        lo, hi = PRESET_MESSAGE_GAP[self.config.preset]
        if self.config.message_gap_min is not None:
            lo = self.config.message_gap_min
        if self.config.message_gap_max is not None:
            hi = self.config.message_gap_max
        mult = self._mode_mult()
        lo, hi = lo * mult, hi * mult
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    def swipe_step_gap_range(self) -> Tuple[float, float]:
        lo, hi = PRESET_SWIPE_STEP_GAP[self.config.preset]
        if self.config.swipe_step_gap_min is not None:
            lo = self.config.swipe_step_gap_min
        if self.config.swipe_step_gap_max is not None:
            hi = self.config.swipe_step_gap_max
        mult = self._mode_mult()
        lo, hi = lo * mult, hi * mult
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    def sample_message_gap_seconds(self) -> float:
        """Inter-message gap for dating/social step workers (log-normal)."""
        lo, hi = self.message_gap_range()
        gap = self._sample_lognormal(lo, hi)
        if self._rng.random() < self.micro_pause_chance():
            gap += self._rng.uniform(0.5, 4.0) * self._mode_mult()
        if self._rng.random() < self.long_break_chance():
            gap += self.sample_long_break()
        return gap

    def sample_swipe_step_gap_seconds(self) -> float:
        lo, hi = self.swipe_step_gap_range()
        gap = self._sample_lognormal(lo, hi)
        if self._rng.random() < self.micro_pause_chance():
            gap += self._rng.uniform(0.15, 1.2) * self._mode_mult()
        return gap

    def sample_step_gap_seconds(self, *, kind: str = "action") -> float:
        """Full gap for step workers — never a fixed interval.

        kind: action | message | swipe
        """
        if kind == "message":
            return self.sample_message_gap_seconds()
        if kind == "swipe":
            return self.sample_swipe_step_gap_seconds()
        return (
            self.sample_action_delay()
            + self.maybe_idle_pause()
            + self.maybe_long_break()
        )

    def begin_message(self) -> float:
        """Sample a per-message typing speed factor (sticky for one message)."""
        # 0.65x–1.55x: some messages rushed, some careful
        self._message_typing_factor = self._rng.uniform(0.65, 1.55)
        return self._message_typing_factor

    async def wait_action_gap(self) -> float:
        """Async sleep for a human-like inter-action gap (+ optional idle/break)."""
        import asyncio

        delay = self.sample_action_delay()
        idle = self.maybe_idle_pause()
        long_b = self.maybe_long_break()
        total = delay + idle + long_b
        now = time.monotonic()
        if self._last_action_at:
            elapsed = now - self._last_action_at
            total = max(0.0, total - max(0.0, elapsed))
        if total > 0 and self.config.enabled:
            await asyncio.sleep(total)
        self._last_action_at = time.monotonic()
        return delay + idle + long_b

    # --- gestures -------------------------------------------------------

    def jitter_point(
        self,
        x: float,
        y: float,
        *,
        bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> Tuple[int, int]:
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
        radius = 6.0 + 12.0 * self.config.tap_jitter_frac
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
        if steps < 2:
            steps = 2
        mx = (x1 + x2) / 2.0
        my = (y1 + y2) / 2.0
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length
        amp = length * self.config.swipe_curve_amp * self._rng.uniform(0.35, 1.15)
        if self._rng.random() < 0.5:
            amp = -amp
        cx, cy = mx + px * amp, my + py * amp
        points: List[Tuple[int, int]] = []
        for i in range(steps + 1):
            u = i / steps
            t = u * u * (3 - 2 * u)
            t = min(1.0, max(0.0, t + self._rng.uniform(-0.04, 0.04)))
            bx = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t**2 * x2
            by = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t**2 * y2
            points.append((int(round(bx)), int(round(by))))
        return points

    def swipe_duration_ms(self, distance_px: float) -> int:
        lo, hi = self.action_delay_range()
        base = 160 + distance_px * 0.4
        factor = {"fast": 0.65, "balanced": 1.0, "careful": 1.4}[
            self.config.preset.value
        ]
        dur = base * factor * self._rng.uniform(0.8, 1.35)
        dur = max(100.0, min(hi * 1000.0, dur))
        return int(dur)

    def typing_delays_ms(self, text: str) -> List[float]:
        """Per-character delays; uses sticky per-message speed factor."""
        lo, hi = self.typing_char_ms_range()
        factor = self._message_typing_factor or 1.0
        delays: List[float] = []
        for i, ch in enumerate(text):
            d = self._sample_lognormal(lo, hi) * factor
            if ch in " .,!?;:\n":
                d *= self._rng.uniform(1.3, 2.4)
            if i > 0 and self._rng.random() < 0.1:
                d += self._rng.uniform(80.0, 520.0) * factor
            if self._rng.random() < self.micro_pause_chance() * 0.5:
                d += self._rng.uniform(30.0, 160.0)
            delays.append(d)
        return delays

    def typing_total_seconds(self, text: str) -> float:
        self.begin_message()
        return sum(self.typing_delays_ms(text)) / 1000.0

    # --- session / ordering ---------------------------------------------

    def sample_session_window(
        self,
        active_start: dtime,
        active_end: dtime,
        *,
        now: Optional[datetime] = None,
    ) -> Tuple[dtime, dtime]:
        """Randomise today's session start/end inside active hours."""
        now = now or datetime.now()
        base = now.replace(
            hour=active_start.hour,
            minute=active_start.minute,
            second=0,
            microsecond=0,
        )
        end_base = now.replace(
            hour=active_end.hour,
            minute=active_end.minute,
            second=0,
            microsecond=0,
        )
        if end_base <= base:
            end_base += timedelta(days=1)
        start_j = self._rng.randint(
            self.config.session_start_jitter_min,
            max(
                self.config.session_start_jitter_min,
                self.config.session_start_jitter_max,
            ),
        )
        end_j = self._rng.randint(
            self.config.session_end_early_min,
            max(self.config.session_end_early_min, self.config.session_end_early_max),
        )
        start_dt = base + timedelta(minutes=start_j)
        end_dt = end_base - timedelta(minutes=end_j)
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=30)
        return start_dt.time(), end_dt.time()

    def shuffle(self, items: Sequence[T]) -> List[T]:
        """Fisher–Yates shuffle copy (apps or conversations)."""
        out = list(items)
        if not self.config.enabled:
            return out
        self._rng.shuffle(out)
        return out

    def ordered_apps(self, apps: Sequence[T]) -> List[T]:
        if self.config.shuffle_apps:
            return self.shuffle(apps)
        return list(apps)

    def ordered_conversations(self, convos: Sequence[T]) -> List[T]:
        if self.config.shuffle_conversations:
            return self.shuffle(convos)
        return list(convos)


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
            "long_break_s": PRESET_LONG_BREAK[p],
            "message_gap_s": PRESET_MESSAGE_GAP[p],
            "swipe_step_gap_s": PRESET_SWIPE_STEP_GAP[p],
            "cache_ttl_s": PRESET_CACHE_TTL[p],
            "idle_chance": PRESET_IDLE_CHANCE[p],
            "micro_pause_chance": PRESET_MICRO_PAUSE_CHANCE[p],
            "long_break_chance": PRESET_LONG_BREAK_CHANCE[p],
        }
        for p in SpeedPreset
    }
