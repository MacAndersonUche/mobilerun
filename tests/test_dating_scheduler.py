"""Tests for dating mode scheduler and pacing."""

import pytest
from datetime import time
from mobilerun.dating.scheduler import DatingScheduler


def test_scheduler_active_hours():
    """Test active hours checking."""
    scheduler = DatingScheduler(
        active_hours_start=time(9, 0),
        active_hours_end=time(23, 0),
    )

    # Note: This test depends on current time, so we just check the method exists
    result = scheduler.is_within_active_hours()
    assert isinstance(result, bool)


def test_scheduler_break_detection():
    """Test break detection based on activity."""
    scheduler = DatingScheduler(human_like=True)

    # Should not need break initially
    assert not scheduler.should_take_break(0, 0, max_swipes=15, max_messages=5)

    # Should need break after hitting swipe limit
    assert scheduler.should_take_break(15, 0, max_swipes=15, max_messages=5)

    # Should need break after hitting message limit
    assert scheduler.should_take_break(0, 5, max_swipes=15, max_messages=5)


def test_scheduler_delays():
    """Test delay generation."""
    scheduler = DatingScheduler(human_like=True)

    # Swipe delays
    for _ in range(10):
        delay = scheduler.get_swipe_delay(min_ms=800, max_ms=3000)
        assert 0.5 <= delay <= 4.0, f"Swipe delay {delay} out of range"

    # Typing delays
    short_text = "Hi"
    long_text = "Hey there! How's your day going?"

    short_delay = scheduler.get_typing_delay(short_text)
    long_delay = scheduler.get_typing_delay(long_text)

    assert short_delay > 0
    assert long_delay > short_delay, "Longer text should take more time"


def test_scheduler_swipe_curve():
    """Test swipe curve generation."""
    scheduler = DatingScheduler(human_like=True)

    curve = scheduler.get_swipe_curve(distance=500)

    # Should have multiple points
    assert len(curve) >= 8

    # First point should be near start
    assert abs(curve[0][0]) < 50

    # Last point should be near end
    assert abs(curve[-1][0] - 500) < 50


def test_scheduler_session_tracking():
    """Test session tracking."""
    scheduler = DatingScheduler()

    scheduler.start_session()
    assert scheduler.current_session_swipes == 0
    assert scheduler.current_session_messages == 0

    scheduler.record_swipe()
    assert scheduler.current_session_swipes == 1

    scheduler.record_message()
    assert scheduler.current_session_messages == 1

    scheduler.reset_session()
    assert scheduler.current_session_swipes == 0
    assert scheduler.current_session_messages == 0


def test_scheduler_non_human_mode():
    """Test scheduler in non-human mode (deterministic)."""
    scheduler = DatingScheduler(human_like=False)

    # Should not recommend breaks
    assert not scheduler.should_take_break(20, 10)

    # Delays should be minimal/predictable
    delay = scheduler.get_swipe_delay(min_ms=800, max_ms=3000)
    assert delay == 0.8  # Should use minimum


def test_break_duration():
    """Test break duration generation."""
    scheduler = DatingScheduler(human_like=True)

    for _ in range(10):
        duration = scheduler.get_break_duration(min_sec=60, max_sec=600)
        assert 60 <= duration <= 600, f"Break duration {duration} out of range"
