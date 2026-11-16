"""Template opener library: buckets, no-repeat, no LLM for templates."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from mobilerun.dating.openers import (
    OpenerLibrary,
    OpenerTemplate,
    bucket_for_local_time,
    compose_dating_message,
    load_default_library,
    pick_template_opener,
    render_opener_text,
    summarize_buckets,
    validate_active_bounds,
)
from mobilerun.dating.persona import PersonaManager

FIX_PATH = Path(__file__).resolve().parents[1] / "config" / "dating_openers.json"


@pytest.fixture
def library() -> OpenerLibrary:
    assert FIX_PATH.exists(), f"missing seed file {FIX_PATH}"
    return load_default_library(FIX_PATH)


def test_seed_file_covers_buckets(library: OpenerLibrary):
    # Counts include enabled only via summarize_buckets
    all_by_bucket = {b: 0 for b in ("morning", "afternoon", "evening", "any")}
    for t in library.templates:
        all_by_bucket[t.bucket] = all_by_bucket.get(t.bucket, 0) + 1
    assert all_by_bucket["morning"] >= 16
    assert all_by_bucket["afternoon"] >= 16
    assert all_by_bucket["evening"] >= 16
    assert all_by_bucket["any"] >= 5
    assert len(library.templates) >= 50
    ok, msg = validate_active_bounds(library)
    assert ok, msg
    assert 2 <= library.enabled_count() <= 50


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (5, 0, "morning"),
        (9, 30, "morning"),
        (11, 59, "morning"),
        (12, 0, "afternoon"),
        (15, 0, "afternoon"),
        (16, 59, "afternoon"),
        (17, 0, "evening"),
        (23, 0, "evening"),
        (0, 30, "evening"),
        (4, 59, "evening"),
    ],
)
def test_bucket_selection_by_time(hour, minute, expected):
    now = datetime(2026, 6, 1, hour, minute, 0)
    assert bucket_for_local_time(now) == expected


def test_pick_uses_morning_bucket(library: OpenerLibrary):
    now = datetime(2026, 6, 1, 8, 0, 0)
    pick = pick_template_opener(
        library, match_id="m1", package_name="com.hinge.app", now=now
    )
    assert pick.bucket == "morning"
    assert pick.used_llm is False
    tmpl = next(t for t in library.templates if t.id == pick.template_id)
    assert tmpl.bucket in ("morning", "any")


def test_no_repeat_same_template_to_same_match(library: OpenerLibrary):
    now = datetime(2026, 6, 1, 14, 0, 0)
    seen = set()
    for i in range(12):
        pick = pick_template_opener(
            library,
            match_id="same-match",
            package_name="com.bumble.app",
            now=now,
        )
        assert pick.template_id not in seen
        seen.add(pick.template_id)
    used = library.used_by_match["com.bumble.app:same-match"]
    assert len(used) == len(set(used)) == 12


def test_rotate_avoids_identical_back_to_back(library: OpenerLibrary):
    now = datetime(2026, 6, 1, 19, 0, 0)
    first = pick_template_opener(library, match_id="a", package_name="p", now=now)
    second = pick_template_opener(library, match_id="b", package_name="p", now=now)
    # Prefer not reusing last_sent across consecutive matches when pool allows
    assert first.template_id != second.template_id or library.enabled_count() < 2


def test_name_placeholder_omitted_when_unknown(library: OpenerLibrary):
    assert "{name}" not in render_opener_text("Hey {name}, hi", None)
    assert "Alex" in render_opener_text("Hey {name}, hi", "Alex")
    assert (
        render_opener_text("Hope you slept well 😊", None) == "Hope you slept well 😊"
    )


def test_compose_opener_templates_does_not_call_ai(library: OpenerLibrary):
    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "SHOULD_NOT_RUN"

    library.opener_mode = "templates"
    out = compose_dating_message(
        is_opener=True,
        lib=library,
        match_id="x1",
        package_name="com.taimi.app",
        profile_name="Sam",
        now=datetime(2026, 6, 1, 9, 0, 0),
        ai_callable=ai,
    )
    assert out["used_llm"] is False
    assert out["source"] == "template"
    assert calls == []
    assert out["text"]
    assert "SHOULD_NOT_RUN" not in out["text"]


def test_compose_reply_always_uses_ai(library: OpenerLibrary):
    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "Nice to hear that — tell me more?"

    library.opener_mode = "templates"
    out = compose_dating_message(
        is_opener=False,
        lib=library,
        match_id="x1",
        package_name="com.taimi.app",
        profile_name="Sam",
        inbound_preview="Had a chill day",
        ai_callable=ai,
    )
    assert out["used_llm"] is True
    assert out["source"] == "ai"
    assert len(calls) == 1
    assert calls[0]["is_opener"] is False


def test_ai_opener_mode_calls_ai(library: OpenerLibrary):
    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "AI crafted opener"

    library.opener_mode = "ai"
    out = compose_dating_message(
        is_opener=True,
        lib=library,
        match_id="z",
        ai_callable=ai,
    )
    assert out["used_llm"] is True
    assert len(calls) == 1


def test_per_app_mode_override(library: OpenerLibrary):
    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "AI"

    library.opener_mode = "templates"
    library.per_app_mode["com.hinge.app"] = "ai"
    out = compose_dating_message(
        is_opener=True,
        lib=library,
        match_id="h1",
        package_name="com.hinge.app",
        ai_callable=ai,
    )
    assert out["used_llm"] is True
    assert len(calls) == 1

    # Other app still templates
    out2 = compose_dating_message(
        is_opener=True,
        lib=library,
        match_id="t1",
        package_name="com.taimi.app",
        now=datetime(2026, 6, 1, 10, 0, 0),
        ai_callable=ai,
    )
    assert out2["used_llm"] is False
    assert len(calls) == 1


def test_persona_manager_wires_library(library: OpenerLibrary):
    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "reply text"

    pm = PersonaManager(opener_library=library, ai_callable=ai)
    library.opener_mode = "templates"
    opener = pm.compose_opener(
        match_id="pm1",
        package_name="com.badoo.mobile",
        profile_name="Alex",
        now=datetime(2026, 6, 1, 18, 0, 0),
    )
    reply = pm.compose_reply(
        match_id="pm1",
        package_name="com.badoo.mobile",
        profile_name="Alex",
        inbound_preview="Hey!",
    )
    assert opener["used_llm"] is False
    assert reply["used_llm"] is True
    assert len(calls) == 1


def test_step_worker_opener_uses_templates_not_ai(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    from backend.step_worker import run_dating_step

    lib = load_default_library(FIX_PATH)
    lib.opener_mode = "templates"
    job = {
        "job_id": "opener_tmpl",
        "kind": "dating",
        "status": "running",
        "device_id": "emulator",
        "dry_run": True,
        "opener_mode": "templates",
        "opener_library": lib.to_dict(),
        "caps": {
            "opener_target": 3,
            "global_message_max": 10,
            "swipe_cap": 0,
            "reply_cap": 5,
        },
        "state": {
            "openers_sent": 0,
            "replies_sent": 0,
            "swipes_done": 0,
            "steps": 0,
            "current_match_id": "matchA",
            "current_profile_name": "Jordan",
            "apps": ["com.hinge.app"],
        },
        "speed_preset": "fast",
    }
    out = run_dating_step(job)
    assert out["state"]["last_action"] == "opener"
    assert out["state"].get("last_used_llm") is False
    assert out["state"].get("last_message_source") == "template"
    assert out["state"].get("last_message")
    assert out["state"].get("last_template_id")


def test_api_compose_and_library(monkeypatch, tmp_path):
    import importlib

    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)

    import backend.main as main_mod

    importlib.reload(main_mod)
    from fastapi.testclient import TestClient

    c = TestClient(main_mod.app)

    g = c.get("/api/dating/openers")
    assert g.status_code == 200, g.text
    body = g.json()
    assert len(body["library"]["templates"]) >= 50

    # Template opener — no AI
    opener = c.post(
        "/api/dating/compose",
        json={
            "match_id": "api1",
            "package_name": "com.hinge.app",
            "profile_name": "Riley",
            "is_opener": True,
            "local_hour": 9,
            "local_minute": 0,
        },
    )
    assert opener.status_code == 200, opener.text
    od = opener.json()
    assert od["used_llm"] is False
    assert od["source"] == "template"
    assert od["ai_calls"] == 0

    # Reply — AI
    reply = c.post(
        "/api/dating/compose",
        json={
            "match_id": "api1",
            "package_name": "com.hinge.app",
            "profile_name": "Riley",
            "is_opener": False,
            "inbound_preview": "Hey there",
        },
    )
    assert reply.status_code == 200, reply.text
    rd = reply.json()
    assert rd["used_llm"] is True
    assert rd["ai_calls"] == 1

    # Toggle to AI openers
    cfg = c.post(
        "/api/dating/config",
        json={
            "enabled_apps": ["com.hinge.app"],
            "opener_mode": "ai",
            "speed_preset": "balanced",
        },
    )
    assert cfg.status_code == 200, cfg.text
    opener2 = c.post(
        "/api/dating/compose",
        json={
            "match_id": "api2",
            "package_name": "com.hinge.app",
            "is_opener": True,
        },
    )
    assert opener2.status_code == 200
    assert opener2.json()["used_llm"] is True
    assert opener2.json()["ai_calls"] == 1
