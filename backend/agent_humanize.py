"""Lightweight human-like pacing for cloud agent auto-click / messaging.

Uses the shared Humanizer with a Fast preset clamped to ~0.3–1.5s so
deterministic DM fast-paths stay under the 3–5s/step budget.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional, Tuple

# Agent auto-click band (Mac): short, human, never robotic-fixed
AGENT_DELAY_LO = 0.30
AGENT_DELAY_HI = 1.50


def _humanizer(seed: Optional[str] = None):
    from mobilerun.agent.humanizer import (
        AgentMode,
        Humanizer,
        HumanizerConfig,
        SpeedPreset,
    )

    cfg = HumanizerConfig.from_preset(
        SpeedPreset.FAST,
        AgentMode.NORMAL,
        action_delay_min=AGENT_DELAY_LO,
        action_delay_max=AGENT_DELAY_HI,
        typing_char_ms_min=28.0,
        typing_char_ms_max=95.0,
        tap_jitter_frac=0.18,
        idle_chance=0.06,
        micro_pause_chance=0.14,
        long_break_chance=0.0,  # never walk-away mid agent task
        skip_screenshot_when_tree_ok=True,
    )
    rng = random.Random(seed) if seed else random.Random()
    return Humanizer(config=cfg, _rng=rng)


def sample_inter_step_delay_s(seed: Optional[str] = None) -> float:
    """0.3–1.5s log-normal gap between agent actions (+ rare micro-pause)."""
    h = _humanizer(seed)
    delay = h.sample_action_delay()
    # Cap hard so step budget stays ≤5s even with tree/RPC overhead
    return max(AGENT_DELAY_LO, min(AGENT_DELAY_HI, delay))


def jitter_tap(
    x: int,
    y: int,
    *,
    bounds: Optional[Tuple[int, int, int, int]] = None,
    seed: Optional[str] = None,
) -> Tuple[int, int]:
    h = _humanizer(seed)
    b = None
    if bounds and len(bounds) == 4:
        b = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
    return h.jitter_point(float(x), float(y), bounds=b)


def sleep_inter_step(seed: Optional[str] = None) -> float:
    delay = sample_inter_step_delay_s(seed)
    time.sleep(delay)
    return delay


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def update_step_timing_stats(state: Dict[str, Any], wall_ms: float) -> Dict[str, Any]:
    """Append wall_ms and refresh p50/p95 on the job state."""
    samples: List[float] = list(state.get("step_wall_ms") or [])
    samples.append(float(wall_ms))
    # Keep last 40 samples on the job row
    samples = samples[-40:]
    state["step_wall_ms"] = samples
    stats = {
        "n": len(samples),
        "p50_ms": percentile(samples, 50),
        "p95_ms": percentile(samples, 95),
        "last_ms": samples[-1],
    }
    state["step_timing_stats"] = stats
    return stats
