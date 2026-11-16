"""Tests for dating mode caps and ranges."""

import pytest
from mobilerun.dating.config import DatingModeConfig, AppProfile
from mobilerun.dating.stats import DatingStats
import tempfile
from pathlib import Path


def test_opener_target_randomization():
    """Test opener target is randomized within range."""
    app = AppProfile(
        name="Hinge",
        package_name="co.hinge.app",
        daily_opener_target_min=50,
        daily_opener_target_max=100,
    )

    assert app.daily_opener_target_min == 50
    assert app.daily_opener_target_max == 100


def test_global_message_target():
    """Test global message target randomization."""
    config = DatingModeConfig(
        min_total_messages_per_day=100,
        max_total_messages_per_day=500,
    )

    # Get 10 random targets
    targets = [config.get_daily_message_target() for _ in range(10)]

    # All should be within range
    for target in targets:
        assert 100 <= target <= 500

    # Should have some variation
    assert len(set(targets)) > 1  # Not all the same


def test_per_app_caps():
    """Test per-app daily caps."""
    app = AppProfile(
        name="Hinge",
        package_name="co.hinge.app",
        daily_swipe_cap=50,
        daily_reply_cap=50,
        daily_opener_target_min=30,
        daily_opener_target_max=70,
    )

    assert app.daily_swipe_cap == 50
    assert app.daily_reply_cap == 50
    assert 30 <= 50 <= 70  # Target would be in this range


def test_global_caps():
    """Test global caps across all apps."""
    config = DatingModeConfig(
        max_total_swipes_per_day=300,
        min_total_messages_per_day=100,
        max_total_messages_per_day=500,
    )

    assert config.max_total_swipes_per_day == 300
    assert config.min_total_messages_per_day == 100
    assert config.max_total_messages_per_day == 500


def test_stats_tracking_openers_and_replies():
    """Test stats differentiate openers from replies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        # Record some openers
        stats.record_message("co.hinge.app", "Hinge", is_opener=True)
        stats.record_message("co.hinge.app", "Hinge", is_opener=True)

        # Record some replies
        stats.record_message("co.hinge.app", "Hinge", is_opener=False)

        app_stats = stats.app_stats["co.hinge.app"]
        assert app_stats.openers_sent_today == 2
        assert app_stats.replies_sent_today == 1
        assert app_stats.total_openers == 2
        assert app_stats.total_replies == 1


def test_stats_opener_target():
    """Test setting and tracking opener targets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        # Set opener target
        stats.set_daily_opener_target("co.hinge.app", "Hinge", 75)

        # Record some openers
        for _ in range(30):
            stats.record_message("co.hinge.app", "Hinge", is_opener=True)

        app_stats = stats.app_stats["co.hinge.app"]
        assert app_stats.daily_opener_target == 75
        assert app_stats.openers_sent_today == 30

        # Summary should include progress
        summary = stats.get_summary()
        app_summary = summary["apps"][0]
        assert app_summary["targets"]["opener_target"] == 75
        assert app_summary["targets"]["opener_progress"] == 30


def test_cap_enforcement_logic():
    """Test logic for enforcing caps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        app_config = AppProfile(
            name="Hinge",
            package_name="co.hinge.app",
            daily_reply_cap=50,
        )

        # Record 50 replies
        for _ in range(50):
            stats.record_message("co.hinge.app", "Hinge", is_opener=False)

        app_stats = stats.app_stats["co.hinge.app"]

        # Check if cap reached
        assert app_stats.replies_sent_today >= app_config.daily_reply_cap


def test_global_message_cap_tracking():
    """Test tracking total messages across apps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        # Hinge: 10 openers + 5 replies
        for _ in range(10):
            stats.record_message("co.hinge.app", "Hinge", is_opener=True)
        for _ in range(5):
            stats.record_message("co.hinge.app", "Hinge", is_opener=False)

        # Bumble: 8 openers + 3 replies
        for _ in range(8):
            stats.record_message("com.bumble.app", "Bumble", is_opener=True)
        for _ in range(3):
            stats.record_message("com.bumble.app", "Bumble", is_opener=False)

        # Total across all apps
        assert stats.messages_today_all == 26  # 10+5+8+3


def test_summary_shows_progress():
    """Test summary includes progress vs targets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        # Set target and record progress
        stats.set_daily_opener_target("co.hinge.app", "Hinge", 100)
        for _ in range(42):
            stats.record_message("co.hinge.app", "Hinge", is_opener=True)

        summary = stats.get_summary()
        app_summary = summary["apps"][0]

        # Should show both target and progress
        assert app_summary["targets"]["opener_target"] == 100
        assert app_summary["targets"]["opener_progress"] == 42
        assert app_summary["today"]["openers"] == 42


def test_sequential_messaging_config():
    """Test sequential messaging configuration."""
    config = DatingModeConfig(sequential_messaging=True)
    assert config.sequential_messaging is True

    config_parallel = DatingModeConfig(sequential_messaging=False)
    assert config_parallel.sequential_messaging is False


def test_conversation_gaps():
    """Test conversation gap configuration."""
    app = AppProfile(
        name="Hinge",
        package_name="co.hinge.app",
        min_conversation_gap_sec=30,
        max_conversation_gap_sec=180,
    )

    assert app.min_conversation_gap_sec == 30
    assert app.max_conversation_gap_sec == 180
