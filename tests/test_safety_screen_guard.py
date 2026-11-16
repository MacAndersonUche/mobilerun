"""Unit tests for safety heuristics + auto-pause escalation."""

from __future__ import annotations

import base64

import pytest

from mobilerun.safety.auto_pause import handle_safety_pause
from mobilerun.safety.runtime import (
    check_screen_and_pause,
    get_safety_state,
    reset_safety_state,
    resume_safety,
)
from mobilerun.safety.screen_guard import (
    detect_safety_blockers,
    find_safety_in_ui_tree,
)


@pytest.fixture(autouse=True)
def _clean_safety():
    reset_safety_state()
    yield
    reset_safety_state()


@pytest.mark.parametrize(
    "text,category",
    [
        ("Please complete the CAPTCHA to continue", "captcha"),
        ("I'm not a robot — verify you're human", "captcha"),
        ("We noticed unusual activity on your account", "unusual_activity"),
        ("Too many requests. Try again later.", "rate_limit"),
        ("Your account has been restricted", "restricted"),
        ("Your account has been banned", "banned"),
        ("Session expired — log in again", "login"),
        ("Take a selfie for photo verification", "photo_verify"),
        ("Verify your identity with a face match", "photo_verify"),
    ],
)
def test_heuristic_categories(text, category):
    finding = detect_safety_blockers(screen_text=text)
    assert finding.detected
    assert finding.category == category
    assert finding.confidence >= 0.8
    if category in ("banned", "restricted"):
        assert finding.pause_all


def test_clean_screen_not_flagged():
    finding = detect_safety_blockers(
        screen_text="Alex · coffee, dogs, and bad jokes. Like Pass Send"
    )
    assert not finding.detected


def test_ui_tree_flatten_and_detect():
    tree = {
        "text": "Home",
        "children": [
            {"contentDescription": "We noticed unusual activity"},
            {"text": "Confirm it's you", "children": []},
        ],
    }
    texts = find_safety_in_ui_tree(tree)
    assert any("unusual" in t.lower() for t in texts)
    finding = detect_safety_blockers(ui_tree=tree)
    assert finding.detected
    assert finding.category == "unusual_activity"


def test_llm_check_optional():
    def llm(_blob):
        return {
            "is_safety_block": True,
            "category": "warning",
            "reason": "Looks like a challenge wall",
            "confidence": 0.75,
            "snippet": "challenge",
        }

    # Soft keyword only — heuristics miss, LLM confirms
    finding = detect_safety_blockers(
        screen_text="Please finish this challenge before chatting",
        llm_check=True,
        llm_callable=llm,
    )
    assert finding.detected
    assert finding.source == "llm"


def test_handle_safety_pause_wires_callbacks():
    calls = {"paused": None, "ny": None, "notify": None, "shot": None}
    finding = detect_safety_blockers(screen_text="Complete the captcha now")

    def pause_app(app):
        calls["paused"] = app

    def push(**kwargs):
        calls["ny"] = kwargs
        return "ny_test_1"

    def notify(**kwargs):
        calls["notify"] = kwargs

    def shot():
        calls["shot"] = "/tmp/x.png"
        return "/tmp/x.png"

    result = handle_safety_pause(
        finding,
        app="MockDating",
        pause_app=pause_app,
        push_needs_you=push,
        notify=notify,
        take_screenshot=shot,
    )
    assert result.paused
    assert calls["paused"] == "MockDating"
    assert calls["ny"]["kind"] == "safety_pause"
    assert calls["notify"]["app"] == "MockDating"
    assert result.screenshot_path == "/tmp/x.png"
    assert result.needs_you_id == "ny_test_1"


def test_check_and_resume_roundtrip():
    paused_modes = []

    def pause_dating():
        paused_modes.append("dating")

    result = check_screen_and_pause(
        app="MockDating",
        screen_text="Verify your identity — take a selfie for photo verification",
        push_needs_you=lambda **kw: "ny_abc",
        notify=lambda **kw: None,
        screenshot_bytes=b"\x89PNG\r\n",
        pause_mode_callbacks={"dating": pause_dating},
    )
    assert result.paused
    assert get_safety_state().is_paused("MockDating")
    assert "dating" in paused_modes

    # Must not auto-clear
    assert get_safety_state().is_paused("MockDating")

    resume_safety(app="MockDating")
    assert not get_safety_state().is_paused("MockDating")


def test_banned_pauses_all():
    result = check_screen_and_pause(
        app="Tinder",
        screen_text="Your account has been banned for violating terms",
        push_needs_you=lambda **kw: "ny_ban",
    )
    assert result.paused
    assert result.pause_all
    assert get_safety_state().pause_all


def test_never_suggests_bypass_in_reason():
    finding = detect_safety_blockers(
        screen_text="Solve this captcha / select all squares with traffic lights"
    )
    assert finding.detected
    assert "bypass" not in finding.reason.lower()
    assert "solve" not in finding.reason.lower()
