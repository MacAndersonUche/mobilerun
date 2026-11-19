"""Locked-phone open_app verify + max_steps goal-unmet failures."""

from backend.cloud_agent import (
    MAX_STEPS_UNMET_ERROR,
    PHONE_LOCKED_ERROR,
    _fg_matches_open_target,
    _is_lock_screen_package,
    _verify_open_app_result,
    run_one_agent_step,
)


def test_lock_screen_packages():
    assert _is_lock_screen_package("com.android.systemui")
    assert _is_lock_screen_package("com.android.keyguard")
    assert _is_lock_screen_package("com.samsung.android.systemui")
    assert not _is_lock_screen_package("com.whatsapp")
    assert not _is_lock_screen_package("com.android.settings")
    assert not _is_lock_screen_package("")


def test_fg_matches_open_target():
    assert _fg_matches_open_target("WhatsApp", "com.whatsapp")
    assert _fg_matches_open_target("settings", "com.android.settings")
    assert _fg_matches_open_target("com.whatsapp", "com.whatsapp")
    assert not _fg_matches_open_target("WhatsApp", "com.android.systemui")
    assert not _fg_matches_open_target("WhatsApp", "com.android.keyguard")
    assert not _fg_matches_open_target("WhatsApp", "com.android.launcher3")


def test_rpc_ok_alone_does_not_count_as_opened_on_systemui():
    """Bug: rpc_ok + rpc_pkg used to force opened=True while FG stayed SystemUI."""
    r = _verify_open_app_result(
        app_name="WhatsApp",
        fg_package="com.android.systemui",
        tree="<hierarchy/>",
        rpc_pkg="com.whatsapp",
        prior_lock_retries=0,
    )
    assert r["opened"] is False
    assert r["fail_locked"] is False
    assert "open_unconfirmed" in r["verify_msg"]
    assert "lock_screen" in r["verify_msg"]
    assert r["lock_retries"] == 1


def test_lock_screen_fails_after_open_plus_one_retry():
    first = _verify_open_app_result(
        app_name="WhatsApp",
        fg_package="com.android.systemui",
        rpc_pkg="com.whatsapp",
        prior_lock_retries=0,
    )
    assert first["fail_locked"] is False
    assert first["lock_retries"] == 1

    second = _verify_open_app_result(
        app_name="WhatsApp",
        fg_package="com.android.systemui",
        rpc_pkg="com.whatsapp",
        prior_lock_retries=first["lock_retries"],
    )
    assert second["opened"] is False
    assert second["fail_locked"] is True
    assert second["error"] == PHONE_LOCKED_ERROR


def test_keyguard_also_fails_fast_on_retry():
    r = _verify_open_app_result(
        app_name="Settings",
        fg_package="com.android.keyguard",
        prior_lock_retries=1,
    )
    assert r["fail_locked"] is True
    assert r["error"] == PHONE_LOCKED_ERROR


def test_real_fg_match_is_open_ok():
    r = _verify_open_app_result(
        app_name="WhatsApp",
        fg_package="com.whatsapp",
        tree='<hierarchy package="com.whatsapp"/>',
        rpc_pkg="com.whatsapp",
        prior_lock_retries=1,  # prior lock retries clear on success
    )
    assert r["opened"] is True
    assert r["fail_locked"] is False
    assert r["verify_msg"].startswith("open_ok")
    assert r["lock_retries"] == 0


def _patch_reachable(monkeypatch):
    import backend.cloud_agent as ca
    import backend.device_push as device_push

    monkeypatch.setattr(ca, "_attach_failure_artifacts", lambda *_a, **_k: None)
    monkeypatch.setattr(device_push, "device_is_reachable", lambda *_a, **_k: True)
    try:
        import device_push as dp_top  # type: ignore

        monkeypatch.setattr(dp_top, "device_is_reachable", lambda *_a, **_k: True)
    except Exception:
        pass


def test_max_steps_fails_when_goal_unmet(monkeypatch):
    import time

    _patch_reachable(monkeypatch)
    now = int(time.time())

    job = {
        "job_id": "maxsteps1",
        "device_id": "dev1",
        "instruction": "open Settings",  # non-DM → skip ensure_ime
        "max_steps": 5,
        "status": "running",
        "created_at": now,
        "state": {
            "steps": 5,
            "history": ["Opened Settings — launch"],
            "last_action": "Opened Settings",
            "last_progress_at": now,
        },
    }
    out = run_one_agent_step(job)
    assert out["status"] == "failed"
    assert out["error"] == MAX_STEPS_UNMET_ERROR


def test_max_steps_completed_only_when_goal_met(monkeypatch):
    import time

    _patch_reachable(monkeypatch)
    now = int(time.time())

    job = {
        "job_id": "maxsteps2",
        "device_id": "dev1",
        "instruction": "open Settings",
        "max_steps": 8,
        "status": "running",
        "created_at": now,
        "state": {
            "steps": 8,
            "history": ["Opened Settings"],
            "last_action": "Opened Settings",
            "last_progress_at": now,
            "outgoing_confirmed": True,
            "goal_result": "Message sent",
        },
    }
    out = run_one_agent_step(job)
    assert out["status"] == "completed"
    assert out["result"] == "Message sent"
    assert out.get("error") in (None, "")
