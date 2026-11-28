"""Template opener library: London slots, no-repeat, runner wiring."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from mobilerun.dating.openers import (
    OpenerLibrary,
    bucket_for_local_time,
    compose_dating_message,
    load_default_library,
    pick_runner_first_contact_text,
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


def test_seed_file_has_about_20_slotted_lines(library: OpenerLibrary):
    assert 18 <= len(library.templates) <= 25
    by = summarize_buckets(library)
    assert by["morning"] >= 3
    assert by["afternoon"] >= 3
    assert by["evening"] >= 3
    assert by["any"] >= 5
    texts = {t.text.lower() for t in library.templates}
    assert "good evening beautiful" in texts
    assert "hi miss you look beautiful" in texts
    assert any("good morning" in t for t in texts)
    for t in library.templates:
        assert "—" not in t.text and "–" not in t.text
        assert not any(ord(c) > 127 for c in t.text)  # no emoji / fancy punctuation
    ok, msg = validate_active_bounds(library)
    assert ok, msg
    assert 2 <= library.enabled_count() <= 50


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (0, 30, "morning"),
        (5, 0, "morning"),
        (9, 30, "morning"),
        (11, 59, "morning"),
        (12, 0, "afternoon"),
        (15, 0, "afternoon"),
        (16, 59, "afternoon"),
        (17, 0, "evening"),
        (23, 0, "evening"),
    ],
)
def test_bucket_selection_london_slots(hour, minute, expected):
    # Naive datetime = Europe/London wall-clock for tests
    now = datetime(2026, 6, 1, hour, minute, 0)
    assert bucket_for_local_time(now) == expected


def test_pick_pool_is_slot_plus_any(library: OpenerLibrary):
    now = datetime(2026, 6, 1, 8, 0, 0)
    pick = pick_template_opener(
        library, match_id="m1", package_name="co.hinge.app", now=now
    )
    assert pick.bucket == "morning"
    tmpl = next(t for t in library.templates if t.id == pick.template_id)
    assert tmpl.bucket in ("morning", "any")


def test_no_repeat_same_template_to_same_match(library: OpenerLibrary):
    now = datetime(2026, 6, 1, 14, 0, 0)
    seen = set()
    # Pool is afternoon + any (~12); pick until we fill unique set
    for _ in range(min(10, library.enabled_count())):
        pick = pick_template_opener(
            library,
            match_id="same-match",
            package_name="com.bumble.app",
            now=now,
        )
        assert pick.template_id not in seen
        seen.add(pick.template_id)


def test_rotate_avoids_identical_back_to_back(library: OpenerLibrary):
    now = datetime(2026, 6, 1, 19, 0, 0)
    first = pick_template_opener(library, match_id="a", package_name="p", now=now)
    second = pick_template_opener(library, match_id="b", package_name="p", now=now)
    assert first.template_id != second.template_id or library.enabled_count() < 2


def test_name_placeholder_omitted_when_unknown():
    assert "{name}" not in render_opener_text("Hey {name}, hi", None)
    assert "Alex" in render_opener_text("Hey {name}, hi", "Alex")


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


def test_pick_runner_uses_library(library: OpenerLibrary):
    state: dict = {"opener_library": library.to_dict(), "bulk_message_new": {"done": 0}}
    text = pick_runner_first_contact_text(
        fallback_bank=("legacy only",),
        message="",
        state=state,
        now=datetime(2026, 6, 1, 18, 0, 0),
        package_name="co.hinge.app",
    )
    assert text
    assert text != "legacy only"
    assert "opener_library" in state
    assert state.get("last_opener_template_id")


def test_pick_runner_falls_back_when_library_empty():
    # All disabled (merge_with_defaults would re-seed a truly empty list)
    lib = load_default_library()
    for t in lib.templates:
        t.enabled = False
    state = {"opener_library": lib.to_dict()}
    text = pick_runner_first_contact_text(
        fallback_bank=("hey how are you", "hi miss"),
        message="",
        state=state,
        now=datetime(2026, 6, 1, 10, 0, 0),
    )
    assert text == "hey how are you"


def test_pick_runner_falls_back_when_unreachable():
    with mock.patch(
        "mobilerun.dating.openers.merge_with_defaults",
        side_effect=RuntimeError("boom"),
    ):
        text = pick_runner_first_contact_text(
            fallback_bank=("good evening beautiful",),
            message="",
            state={},
        )
    assert text == "good evening beautiful"


def test_hinge_allowed_message_uses_library():
    from backend.hinge_fixed_first_contact import MESSAGE_BANK, allowed_message

    state: dict = {"bulk_message_new": {"done": 0}}
    text = allowed_message("", state=state)
    assert text
    assert (
        text in {t.text for t in load_default_library().templates}
        or text in MESSAGE_BANK
    )


def test_hily_allowed_message_uses_library():
    from backend.hily_fixed_first_contact import MESSAGE_BANK, allowed_message

    state: dict = {"bulk_message_new": {"done": 0}}
    text = allowed_message("", state=state)
    assert text
    assert (
        text in {t.text for t in load_default_library().templates}
        or text in MESSAGE_BANK
    )


def test_yubo_allowed_message_uses_library():
    from backend.yubo_fixed_first_contact import MESSAGE_BANK, allowed_message

    state: dict = {"bulk_message_new": {"done": 0}}
    text = allowed_message("", state=state)
    assert text
    assert (
        text in {t.text for t in load_default_library().templates}
        or text in MESSAGE_BANK
    )


def test_tagged_plan_picks_from_library():
    from backend.tagged_fixed import MESSAGE_BANK, plan_tagged_fixed

    state: dict = {}
    act = plan_tagged_fixed(
        "fixed tagged message 3",
        "<hierarchy/>",
        [],
        state=state,
        dry_run=True,
        message="",
    )
    assert act is not None
    assert "opener_library" in state
    assert state.get("last_opener_template_id")


def test_facebook_comment_text_uses_library():
    from backend.facebook_dating_fixed_first_contact import (
        MESSAGE_BANK,
        PHOTO_COMMENT_TEXT,
        comment_text,
    )

    state: dict = {"bulk_message_new": {"done": 0}}
    # Baked-in dating_run quote should rotate via library, not lock to PHOTO_COMMENT_TEXT
    text = comment_text(
        f'send 5 first contact messages on facebook dating "{PHOTO_COMMENT_TEXT}"',
        "",
        state=state,
    )
    assert text
    lib_texts = {t.text for t in load_default_library().templates}
    assert text in lib_texts or text in MESSAGE_BANK
    # Custom quote still wins
    custom = comment_text('send 1 "custom mac line only"', "", state={})
    assert custom == "custom mac line only"


def test_compose_reply_always_uses_ai(library: OpenerLibrary):
    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "Nice to hear that, tell me more?"

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
    assert opener["used_llm"] is False
    assert len(calls) == 0


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
    assert 18 <= len(body["library"]["templates"]) <= 25
    assert body["bucket_now"] in ("morning", "afternoon", "evening")

    opener = c.post(
        "/api/dating/compose",
        json={
            "match_id": "api1",
            "package_name": "co.hinge.app",
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
