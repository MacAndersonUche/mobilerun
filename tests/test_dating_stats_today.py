"""Today totals: London day boundary + sync from dating-run job counters."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from mobilerun.dating.stats import DatingStats, london_today


def test_london_today_is_iso_date():
    d = london_today()
    assert len(d) == 10 and d[4] == "-" and d[7] == "-"


def test_today_totals_equal_sum_of_per_app_openers_and_swipes():
    with tempfile.TemporaryDirectory() as tmp:
        stats = DatingStats(app_stats={}, stats_file=Path(tmp) / "s.json")
        stats.record_message("co.hinge.app", "Hinge", is_opener=True, n=5)
        stats.record_message("co.yellw.yellowapp", "Yubo", is_opener=True, n=5)
        stats.record_message("com.hily.app", "Hily", is_opener=True, n=5)
        stats.record_swipe("com.hily.app", "Hily", liked=True, n=3)
        summary = stats.get_summary()
        assert summary["today"]["messages"] == 15
        assert summary["today"]["swipes"] == 3
        per = {a["package"]: a for a in summary["apps"]}
        assert per["co.hinge.app"]["today"]["openers"] == 5
        assert per["co.yellw.yellowapp"]["today"]["openers"] == 5
        assert per["com.hily.app"]["today"]["openers"] == 5
        assert per["com.hily.app"]["today"]["swipes"] == 3
        assert (
            sum(a["today"]["openers"] for a in summary["apps"])
            == summary["today"]["messages"]
        )
        assert (
            sum(a["today"]["swipes"] for a in summary["apps"])
            == summary["today"]["swipes"]
        )
        # Reply tracking removed from the summary
        assert all(a["today"]["replies"] == 0 for a in summary["apps"])


def test_daily_reset_uses_london_date_not_stale_string():
    with tempfile.TemporaryDirectory() as tmp:
        stats = DatingStats(app_stats={}, stats_file=Path(tmp) / "s.json")
        stats.record_message("co.hinge.app", "Hinge", n=2)
        assert stats.messages_today_all == 2
        stats.last_session_date = "2020-01-01"
        stats.check_and_reset_daily()
        assert stats.messages_today_all == 0
        assert stats.last_session_date == london_today()


def test_save_swallows_readonly_filesystem_errors(tmp_path):
    """Lambda home is often read-only — save must not 500 the stats API."""
    stats = DatingStats(
        app_stats={},
        stats_file=Path("/proc/mobilerun-no-write/dating_stats.json"),
    )
    stats.last_session_date = "2020-01-01"
    # Would raise OSError without the guard; must complete and still reset.
    stats.check_and_reset_daily()
    assert stats.last_session_date == london_today()
    summary = stats.get_summary()
    assert summary["today"]["messages"] == 0


def test_default_file_honors_mobilerun_data(monkeypatch, tmp_path):
    from backend import dating_stats_io as dio

    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("LAMBDA_TASK_ROOT", raising=False)
    assert dio._default_file() == tmp_path / "data" / "dating_stats.json"


def test_load_dating_stats_survives_reset_save_failure(monkeypatch, tmp_path):
    """load must return stats even when day-reset local save hits Errno 30."""
    from backend import dating_stats_io as dio

    store: dict = {}
    monkeypatch.setattr(
        dio,
        "_storage",
        lambda: (
            lambda uid, name: store.get(f"{uid}:{name}"),
            lambda uid, name, data: store.__setitem__(f"{uid}:{name}", data) or True,
        ),
    )
    monkeypatch.setattr(
        dio, "_default_file", lambda: Path("/proc/mobilerun-no-write/dating_stats.json")
    )
    stats = dio.load_dating_stats("mac")
    assert stats.get_summary()["today"]["messages"] == 0
    assert stats.last_session_date == london_today()


def test_sync_dating_stats_from_job_records_message_delta(monkeypatch, tmp_path):
    from backend import dating_stats_io as dio

    store: dict = {}

    def fake_get(uid, name):
        return store.get(f"{uid}:{name}")

    def fake_save(uid, name, data):
        store[f"{uid}:{name}"] = data
        return True

    monkeypatch.setattr(dio, "_storage", lambda: (fake_get, fake_save))
    monkeypatch.setattr(dio, "_default_file", lambda: tmp_path / "dating_stats.json")

    job = {
        "dating_run": True,
        "dating_app": "co.hinge.app",
        "user_id": "mac",
        "dry_run": False,
        "state": {"bulk_message_new": {"done": 0}},
    }
    before = dio._counter_snapshot(job["state"])
    job["state"]["bulk_message_new"]["done"] = 5
    dio.sync_dating_stats_from_job(job, before=before)
    stats = dio.load_dating_stats("mac")
    summary = stats.get_summary()
    assert summary["today"]["messages"] == 5
    assert summary["apps"][0]["package"] == "co.hinge.app"
    assert summary["apps"][0]["today"]["openers"] == 5


def test_sync_skips_dry_run(monkeypatch, tmp_path):
    from backend import dating_stats_io as dio

    store: dict = {}
    monkeypatch.setattr(
        dio,
        "_storage",
        lambda: (
            lambda uid, name: store.get(f"{uid}:{name}"),
            lambda uid, name, data: store.__setitem__(f"{uid}:{name}", data) or True,
        ),
    )
    monkeypatch.setattr(dio, "_default_file", lambda: tmp_path / "dating_stats.json")
    job = {
        "dating_run": True,
        "dating_app": "co.yellw.yellowapp",
        "user_id": "mac",
        "dry_run": True,
        "state": {"yubo_card": {"sent": 0}, "dry_run": True},
    }
    before = dio._counter_snapshot(job["state"])
    job["state"]["yubo_card"]["sent"] = 5
    dio.sync_dating_stats_from_job(job, before=before)
    stats = dio.load_dating_stats("mac")
    assert stats.get_summary()["today"]["messages"] == 0


def test_record_message_ignores_reply_flag_counts_as_opener():
    with tempfile.TemporaryDirectory() as tmp:
        stats = DatingStats(app_stats={}, stats_file=Path(tmp) / "s.json")
        stats.record_message("co.hinge.app", "Hinge", is_opener=False, n=1)
        summary = stats.get_summary()
        assert summary["today"]["messages"] == 1
        assert summary["apps"][0]["today"]["openers"] == 1
        assert summary["apps"][0]["today"]["replies"] == 0


def test_counter_snapshot_includes_tagged_fixed_messages():
    from backend import dating_stats_io as dio

    job = {
        "dating_app": "com.taggedapp",
        "run_modes": {"com.taggedapp": "message"},
        "state": {"tagged_fixed": {"done": 4}, "current_app": "com.taggedapp"},
    }
    msgs, likes = dio._counter_snapshot(job["state"], job)
    assert msgs == 4
    assert likes == 0


def test_counter_snapshot_tagged_swipe_counts_as_likes():
    from backend import dating_stats_io as dio

    job = {
        "dating_app": "com.taggedapp",
        "run_modes": {"com.taggedapp": "swipe"},
        "state": {"tagged_fixed": {"done": 7}},
    }
    msgs, likes = dio._counter_snapshot(job["state"], job)
    assert msgs == 0
    assert likes == 7


def test_apply_job_totals_heals_underreported_today(monkeypatch, tmp_path):
    from backend import dating_stats_io as dio

    store: dict = {}
    monkeypatch.setattr(
        dio,
        "_storage",
        lambda: (
            lambda uid, name: store.get(f"{uid}:{name}"),
            lambda uid, name, data: store.__setitem__(f"{uid}:{name}", data) or True,
        ),
    )
    monkeypatch.setattr(dio, "_default_file", lambda: tmp_path / "dating_stats.json")
    stats = dio.load_dating_stats("mac")
    job = {
        "dating_run": True,
        "dating_app": "co.hinge.app",
        "user_id": "mac",
        "dry_run": False,
        "state": {"bulk_message_new": {"done": 5}},
    }
    assert dio.apply_job_totals_to_stats(stats, job) is True
    summary = stats.get_summary()
    assert summary["today"]["messages"] == 5
    # Second apply with same totals is a no-op
    assert dio.apply_job_totals_to_stats(stats, job) is False
