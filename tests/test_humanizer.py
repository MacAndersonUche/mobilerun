"""Tests for shared humanizer delay distributions and gestures."""

import random
import statistics

import pytest

from mobilerun.agent.humanizer import (
    AgentMode,
    Humanizer,
    HumanizerConfig,
    PRESET_ACTION_DELAYS,
    SpeedPreset,
    describe_presets,
    merge_app_humanizer,
)


@pytest.fixture
def seeded() -> Humanizer:
    return Humanizer(
        config=HumanizerConfig.from_preset("balanced", "normal"),
        _rng=random.Random(42),
    )


@pytest.mark.parametrize(
    "preset,lo,hi",
    [
        (SpeedPreset.FAST, 0.4, 1.2),
        (SpeedPreset.BALANCED, 0.8, 2.5),
        (SpeedPreset.CAREFUL, 1.5, 5.0),
    ],
)
def test_action_delay_stays_in_preset_band(preset, lo, hi):
    h = Humanizer(
        config=HumanizerConfig(preset=preset, mode=AgentMode.NORMAL),
        _rng=random.Random(7),
    )
    samples = [h.sample_action_delay() for _ in range(200)]
    assert all(lo - 1e-9 <= s <= hi + 1e-9 for s in samples)
    # Not a fixed interval: variance must be meaningful
    assert statistics.pstdev(samples) > (hi - lo) * 0.05
    # Not all equal
    assert len(set(round(s, 4) for s in samples)) > 10


def test_dating_mode_slower_than_normal():
    rng_seed = 99
    normal = Humanizer(
        config=HumanizerConfig.from_preset("balanced", "normal"),
        _rng=random.Random(rng_seed),
    )
    dating = Humanizer(
        config=HumanizerConfig.from_preset("balanced", "dating"),
        _rng=random.Random(rng_seed),
    )
    n_mean = statistics.mean(normal.sample_action_delay() for _ in range(80))
    d_mean = statistics.mean(dating.sample_action_delay() for _ in range(80))
    assert d_mean > n_mean


def test_fast_faster_than_careful_mean():
    fast = Humanizer(config=HumanizerConfig.from_preset("fast"), _rng=random.Random(1))
    careful = Humanizer(
        config=HumanizerConfig.from_preset("careful"), _rng=random.Random(1)
    )
    f_mean = statistics.mean(fast.sample_action_delay() for _ in range(100))
    c_mean = statistics.mean(careful.sample_action_delay() for _ in range(100))
    assert f_mean < c_mean


def test_no_fixed_intervals_across_presets():
    for preset in SpeedPreset:
        h = Humanizer(config=HumanizerConfig(preset=preset), _rng=random.Random(3))
        samples = [round(h.sample_action_delay(), 3) for _ in range(40)]
        assert len(set(samples)) > 5


def test_tap_jitter_inside_bounds(seeded: Humanizer):
    bounds = (100.0, 200.0, 300.0, 400.0)
    for _ in range(50):
        x, y = seeded.jitter_point(200, 300, bounds=bounds)
        assert 100 <= x <= 300
        assert 200 <= y <= 400


def test_curved_swipe_variable_path(seeded: Humanizer):
    paths = [seeded.curved_swipe(0, 0, 400, 0, steps=8) for _ in range(5)]
    assert all(len(p) == 9 for p in paths)
    # Different lateral bulges → not identical midpoints
    mids = [p[4][1] for p in paths]
    assert len(set(mids)) > 1
    # Ends near destination (ease noise can shift last sample slightly)
    assert abs(paths[0][-1][0] - 400) <= 20


def test_typing_delays_scale_with_length(seeded: Humanizer):
    short = seeded.typing_total_seconds("Hi")
    long = seeded.typing_total_seconds("Hey there, how's your day going?")
    assert short > 0
    assert long > short


def test_per_app_overrides_clamp_range():
    base = HumanizerConfig.from_preset("balanced", "normal")
    merged = merge_app_humanizer(
        base,
        min_swipe_delay_ms=1000,
        max_swipe_delay_ms=2000,
        min_typing_delay_ms=40,
        max_typing_delay_ms=80,
    )
    h = Humanizer(config=merged, _rng=random.Random(5))
    lo, hi = h.action_delay_range()
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(2.0)
    samples = [h.sample_action_delay() for _ in range(30)]
    assert all(1.0 <= s <= 2.0 for s in samples)


def test_disabled_humanizer_minimal_delay():
    h = Humanizer(
        config=HumanizerConfig(enabled=False, preset=SpeedPreset.CAREFUL),
        _rng=random.Random(2),
    )
    lo, _ = PRESET_ACTION_DELAYS[SpeedPreset.CAREFUL]
    assert h.sample_action_delay() == lo


def test_describe_presets_keys():
    d = describe_presets()
    assert set(d.keys()) == {"fast", "balanced", "careful"}
    assert d["balanced"]["action_delay_s"] == (0.8, 2.5)


def test_idle_pause_sometimes_nonzero():
    h = Humanizer(
        config=HumanizerConfig.from_preset("careful"),
        _rng=random.Random(11),
    )
    pauses = [h.maybe_idle_pause() for _ in range(80)]
    assert any(p > 0 for p in pauses)
    assert any(p == 0 for p in pauses)
