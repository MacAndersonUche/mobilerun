"""Tests for shared humanizer delay distributions and gestures."""

import random
import statistics
from datetime import datetime, time

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
        (SpeedPreset.FAST, 0.3, 1.8),
        (SpeedPreset.BALANCED, 0.6, 3.5),
        (SpeedPreset.CAREFUL, 1.2, 7.0),
    ],
)
def test_action_delay_stays_near_preset_band(preset, lo, hi):
    h = Humanizer(
        config=HumanizerConfig(preset=preset, mode=AgentMode.NORMAL),
        _rng=random.Random(7),
    )
    samples = [h.sample_action_delay() for _ in range(200)]
    # Core sample is clamped to [lo, hi]; micro-pause may add a little
    assert all(lo - 1e-9 <= s <= hi + 0.4 for s in samples)
    assert statistics.pstdev(samples) > (hi - lo) * 0.05
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


def test_message_gaps_lognormal_not_fixed():
    h = Humanizer(
        config=HumanizerConfig.from_preset("balanced", "dating"),
        _rng=random.Random(21),
    )
    samples = [h.sample_message_gap_seconds() for _ in range(60)]
    assert len(set(round(s, 1) for s in samples)) > 8
    assert statistics.pstdev(samples) > 5
    lo, hi = h.message_gap_range()
    # Allow long-break overshoot
    assert all(s >= lo * 0.9 for s in samples)


def test_variable_typing_speed_per_message(seeded: Humanizer):
    factors = [seeded.begin_message() for _ in range(20)]
    assert min(factors) < 0.9
    assert max(factors) > 1.1
    assert len(set(round(f, 3) for f in factors)) > 5


def test_tap_jitter_inside_bounds(seeded: Humanizer):
    bounds = (100.0, 200.0, 300.0, 400.0)
    for _ in range(50):
        x, y = seeded.jitter_point(200, 300, bounds=bounds)
        assert 100 <= x <= 300
        assert 200 <= y <= 400


def test_curved_swipe_variable_path(seeded: Humanizer):
    paths = [seeded.curved_swipe(0, 0, 400, 0, steps=8) for _ in range(5)]
    assert all(len(p) == 9 for p in paths)
    mids = [p[4][1] for p in paths]
    assert len(set(mids)) > 1
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
    assert all(1.0 <= s <= 2.4 for s in samples)  # micro-pause slack


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
    assert d["balanced"]["action_delay_s"] == (0.6, 3.5)
    assert "message_gap_s" in d["balanced"]
    assert "long_break_s" in d["balanced"]


def test_idle_and_long_break_sometimes_nonzero():
    h = Humanizer(
        config=HumanizerConfig.from_preset("careful"),
        _rng=random.Random(11),
    )
    pauses = [h.maybe_idle_pause() for _ in range(80)]
    assert any(p > 0 for p in pauses)
    assert any(p == 0 for p in pauses)
    # Force higher chance via config
    h2 = Humanizer(
        config=HumanizerConfig.from_preset("careful", long_break_chance=0.5),
        _rng=random.Random(5),
    )
    breaks = [h2.maybe_long_break() for _ in range(40)]
    assert any(b > 0 for b in breaks)


def test_session_window_jitter():
    h = Humanizer(
        config=HumanizerConfig(
            session_start_jitter_min=5,
            session_start_jitter_max=20,
            session_end_early_min=5,
            session_end_early_max=15,
        ),
        _rng=random.Random(9),
    )
    now = datetime(2026, 1, 1, 12, 0, 0)
    starts, ends = set(), set()
    for _ in range(15):
        s, e = h.sample_session_window(time(9, 0), time(23, 0), now=now)
        starts.add((s.hour, s.minute))
        ends.add((e.hour, e.minute))
        assert s < e
    assert len(starts) > 1
    assert len(ends) > 1


def test_ordered_apps_and_conversations_shuffle():
    h = Humanizer(
        config=HumanizerConfig(shuffle_apps=True, shuffle_conversations=True),
        _rng=random.Random(4),
    )
    apps = ["Tinder", "Hinge", "Bumble", "OkCupid"]
    orders = {tuple(h.ordered_apps(apps)) for _ in range(20)}
    assert len(orders) > 1
    convos = ["a", "b", "c", "d", "e"]
    c_orders = {tuple(h.ordered_conversations(convos)) for _ in range(20)}
    assert len(c_orders) > 1


def test_from_dict_roundtrip():
    raw = {
        "preset": "fast",
        "mode": "social",
        "delay_sigma": 0.7,
        "shuffle_apps": False,
        "unknown_key": "drop_me",
    }
    cfg = HumanizerConfig.from_dict(raw)
    assert cfg.preset == SpeedPreset.FAST
    assert cfg.mode == AgentMode.SOCIAL
    assert cfg.delay_sigma == 0.7
    assert cfg.shuffle_apps is False
    pub = cfg.to_public_dict()
    assert pub["preset"] == "fast"
    assert "unknown_key" not in pub
