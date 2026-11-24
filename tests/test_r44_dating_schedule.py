"""r44: dating run schedules (per app + combo), fired by the StepWorker tick."""

from datetime import datetime

import pytest

from backend import dating_schedule as ds

LON = ds.london_tz()


def _ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=LON).timestamp()


def _sch(**kw):
    raw = {
        "items": [{"app": "bumble", "count": 20}],
        "time": "09:30",
        "device_id": "android_x",
        "dry_run": True,
    }
    raw.update(kw)
    return ds.normalize(raw)


def test_normalize_per_app_and_combo():
    s = _sch()
    assert s["kind"] == "app" and s["items"] == [
        {"app": "com.bumble.app", "runs": 1, "count": 20}
    ]
    assert s["enabled"] and s["dry_run"] and s["days"] == []
    c = _sch(
        items=[
            {"app": "hinge", "runs": 2, "count": 3},
            {"app": "facebook", "runs": 1, "count": 80},
            {"app": "hily", "runs": 1, "count": 12},
        ],
        days=[0, 2, 4],
    )
    assert c["kind"] == "combo"
    assert c["items"][1]["count"] == 50  # FB cap
    assert c["days"] == [0, 2, 4]
    queue, counts = ds.build_queue(c)
    assert queue == [
        "co.hinge.app",
        "co.hinge.app",
        "com.facebook.katana",
        "com.hily.app",
    ]
    assert counts["com.hily.app"] == 5  # r46: Hily messages capped at 5


@pytest.mark.parametrize(
    "bad",
    [
        {"items": []},
        {"items": [{"app": "whatsapp"}]},
        {"time": "25:00"},
        {"device_id": ""},
    ],
)
def test_normalize_rejects(bad):
    with pytest.raises(ds.ScheduleError):
        _sch(**bad)


def test_due_window_once_and_days():
    s = _sch(days=[1])  # Tuesday only
    tue = _ts(2026, 11, 24, 9, 31)  # Tue 24 Nov 2026
    assert ds.due_slot(s, _ts(2026, 11, 24, 9, 29)) is None
    assert ds.due_slot(s, tue) is not None
    assert ds.due_slot(s, _ts(2026, 11, 24, 9, 50)) is None  # past window
    assert ds.due_slot(s, _ts(2026, 11, 25, 9, 31)) is None  # Wednesday
    nr = ds.next_run(s, _ts(2026, 11, 24, 10, 0))
    assert nr.strftime("%a %H:%M") == "Tue 09:30" and nr.day == 1  # next Tue
    s["enabled"] = False
    assert ds.due_slot(s, tue) is None and ds.next_run(s, tue) is None


def _fire(s, now, jobs=(), reachable=True):
    saved, put = [], []
    res = ds.fire_due(
        now,
        load=lambda: [s],
        save=lambda x: saved.append(x),
        recent_jobs=lambda: list(jobs),
        put_job=put.append,
        reachable=lambda _d: reachable,
    )
    return res, saved, put


def test_fire_queues_same_chain_as_start_once():
    s = _sch(items=[{"app": "bumble", "count": 20}, {"app": "badoo", "runs": 2, "count": 7}])
    now = _ts(2026, 11, 24, 9, 31)
    res, saved, put = _fire(s, now)
    assert res[0]["result"] == "queued"
    job = put[0]
    assert job["instruction"] == "fixed swipe 20 on bumble"
    assert job["run_queue"] == ["com.badoo.mobile", "com.badoo.mobile"]
    assert job["run_counts"]["com.badoo.mobile"] == 7
    assert job["dry_run"] is True and job["schedule_id"] == s["id"]
    assert saved and s["last_fired_key"] == "2026-11-24 09:30"
    # Same slot never fires twice
    res2, _, put2 = _fire(s, now + 60)
    assert res2 == [] and put2 == []


def test_fire_skips_when_run_active_or_offline():
    s = _sch()
    now = _ts(2026, 11, 24, 9, 31)
    res, _, put = _fire(
        s, now, jobs=[{"job_id": "task_1", "status": "running", "device_id": "android_x"}]
    )
    assert put == [] and "already active" in res[0]["result"]
    assert "skipped" in s["last_result"]
    s2 = _sch()
    res, _, put = _fire(s2, now, reachable=False)
    assert put == [] and res[0]["result"] == "skipped: phone offline"


def test_edit_time_rearms_today():
    s = _sch()
    s["last_fired_key"] = "2026-11-24 09:30"
    e = ds.normalize({"time": "10:00"}, existing=s)
    assert "last_fired_key" not in e and e["id"] == s["id"]
