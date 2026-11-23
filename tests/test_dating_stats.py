"""Tests for dating mode statistics."""

import tempfile
from pathlib import Path
from mobilerun.dating.stats import DatingStats, AppStats


def test_app_stats_creation():
    """Test AppStats creation and defaults."""
    stats = AppStats(app_name="Hinge", package_name="co.hinge.app")

    assert stats.app_name == "Hinge"
    assert stats.package_name == "co.hinge.app"
    assert stats.swipes_today == 0
    assert stats.total_swipes == 0


def test_app_stats_daily_reset():
    """Test daily counter reset."""
    stats = AppStats(app_name="Hinge", package_name="co.hinge.app")

    stats.swipes_today = 10
    stats.likes_today = 5
    stats.openers_sent_today = 3
    stats.replies_sent_today = 2

    stats.reset_daily_counts()

    assert stats.swipes_today == 0
    assert stats.likes_today == 0
    assert stats.openers_sent_today == 0
    assert stats.replies_sent_today == 0


def test_dating_stats_swipe_recording():
    """Test swipe recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        stats.record_swipe("co.hinge.app", "Hinge", liked=True)
        stats.record_swipe("co.hinge.app", "Hinge", liked=True)
        stats.record_swipe("co.hinge.app", "Hinge", liked=False)

        app_stats = stats.app_stats["co.hinge.app"]
        assert app_stats.swipes_today == 3
        assert app_stats.likes_today == 2
        assert app_stats.total_swipes == 3
        assert stats.swipes_today_all == 3


def test_dating_stats_message_recording():
    """Test opener vs reply recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        stats.record_message("co.hinge.app", "Hinge", is_opener=True)
        stats.record_message("co.hinge.app", "Hinge", is_opener=False)

        app_stats = stats.app_stats["co.hinge.app"]
        assert app_stats.openers_sent_today == 1
        assert app_stats.replies_sent_today == 1
        assert app_stats.total_openers == 1
        assert app_stats.total_replies == 1
        assert stats.messages_today_all == 2


def test_dating_stats_inbox_update():
    """Test inbox count updates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        stats.update_inbox_count("co.hinge.app", "Hinge", unread=5, new_matches=2)

        app_stats = stats.app_stats["co.hinge.app"]
        assert app_stats.unread_messages == 5
        assert app_stats.new_matches == 2
        assert app_stats.last_stats_update is not None


def test_dating_stats_persistence():
    """Test stats save and load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"

        stats1 = DatingStats(app_stats={}, stats_file=stats_file)
        stats1.record_swipe("co.hinge.app", "Hinge", liked=True)
        stats1.record_message("co.hinge.app", "Hinge", is_opener=True)
        stats1.total_sessions = 5
        stats1.save()

        stats2 = DatingStats.load(stats_file)

        assert "co.hinge.app" in stats2.app_stats
        assert stats2.app_stats["co.hinge.app"].total_swipes == 1
        assert stats2.app_stats["co.hinge.app"].total_openers == 1
        assert stats2.total_sessions == 5


def test_dating_stats_daily_reset_detection():
    """Test automatic daily reset."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        stats.record_swipe("co.hinge.app", "Hinge", liked=True)
        stats.swipes_today_all = 10

        stats.last_session_date = "2020-01-01"
        stats.check_and_reset_daily()

        assert stats.swipes_today_all == 0


def test_dating_stats_summary():
    """Test summary generation with progress vs caps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)

        stats.set_daily_opener_target("co.hinge.app", "Hinge", 80)
        stats.record_swipe("co.hinge.app", "Hinge", liked=True)
        stats.record_message("co.hinge.app", "Hinge", is_opener=True)
        stats.update_inbox_count("co.hinge.app", "Hinge", unread=3, new_matches=1)

        summary = stats.get_summary()

        assert "today" in summary
        assert "apps" in summary
        assert len(summary["apps"]) == 1
        assert summary["apps"][0]["name"] == "Hinge"
        assert summary["apps"][0]["today"]["swipes"] == 1
        assert summary["apps"][0]["today"]["openers"] == 1
        assert summary["apps"][0]["targets"]["opener_target"] == 80
        assert summary["apps"][0]["targets"]["opener_progress"] == 1
        assert summary["apps"][0]["inbox"]["unread"] == 3


def test_display_name_for_package_fallback():
    from mobilerun.dating.config import display_name_for_package

    assert display_name_for_package("co.hinge.app", "Hinge") == "Hinge"
    assert display_name_for_package("co.hinge.app", "") == "Hinge"
    assert display_name_for_package("com.bumble.app", "   ") == "Bumble"
    assert display_name_for_package("com.facebook.katana", None) == "Facebook"
    assert display_name_for_package("com.example.unknownapp", "") == "Unknownapp"


def test_summary_fills_empty_stored_app_name():
    """Portal cards read summary name; stored stats may have a blank app_name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stats_file = Path(tmpdir) / "stats.json"
        stats = DatingStats(app_stats={}, stats_file=stats_file)
        stats.app_stats["co.hinge.app"] = AppStats(
            app_name="", package_name="co.hinge.app", swipes_today=2
        )
        stats.app_stats["com.bumble.app"] = AppStats(
            app_name="   ", package_name="com.bumble.app"
        )

        summary = stats.get_summary()
        by_pkg = {row["package"]: row["name"] for row in summary["apps"]}
        assert by_pkg["co.hinge.app"] == "Hinge"
        assert by_pkg["com.bumble.app"] == "Bumble"

        # Recording against an existing blank row should backfill the name.
        stats.record_swipe("co.hinge.app", "", liked=True)
        assert stats.app_stats["co.hinge.app"].app_name == "Hinge"
