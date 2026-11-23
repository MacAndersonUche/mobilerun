"""Social mode signature toggles, escalation classification, Needs-you queue."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mobilerun.needs_you.escalation import EscalationRules, classify_escalation
from mobilerun.needs_you.queue import NeedsYouQueue
from mobilerun.social.agent import prepare_outbound, summarize_unreads
from mobilerun.social.config import SocialModeConfig
from mobilerun.social.signature import DEFAULT_SIGNATURE, SignatureConfig


def test_signature_default_on_appends():
    sig = SignatureConfig()
    out = sig.apply("Hey there")
    assert out.endswith(DEFAULT_SIGNATURE)
    assert "Hey there" in out


def test_signature_global_off():
    sig = SignatureConfig(enabled_global=False)
    assert sig.apply("Hi") == "Hi"


def test_signature_per_app_override():
    sig = SignatureConfig(enabled_global=True)
    sig.per_app["com.whatsapp"] = False
    assert sig.apply("Hi", package_name="com.whatsapp") == "Hi"
    assert DEFAULT_SIGNATURE in sig.apply("Hi", package_name="com.instagram.android")


def test_signature_per_contact_overrides_app():
    sig = SignatureConfig(enabled_global=False)
    sig.per_app["com.whatsapp"] = False
    key = sig.contact_key("com.whatsapp", "c1", "Alex")
    sig.per_contact[key] = True
    out = sig.apply(
        "Yo", package_name="com.whatsapp", conversation_id="c1", contact_name="Alex"
    )
    assert out.endswith(DEFAULT_SIGNATURE)


def test_signature_idempotent():
    sig = SignatureConfig(text="— from MacAI")
    once = sig.apply("Hello")
    twice = sig.apply(once)
    assert once == twice
    assert once.count("— from MacAI") == 1


def test_escalation_money():
    d = classify_escalation(draft_reply="Sure, Venmo me $50", confidence=0.95)
    assert d.needs_confirmation
    assert "money" in d.reasons


def test_escalation_new_contact_rule():
    rules = EscalationRules(always_ask_new_contacts=True)
    d = classify_escalation(
        draft_reply="Nice to meet you",
        is_new_contact=True,
        confidence=0.9,
        rules=rules,
    )
    assert d.needs_confirmation
    assert "new_contact" in d.reasons


def test_escalation_low_confidence():
    d = classify_escalation(draft_reply="ok", confidence=0.2)
    assert d.needs_confirmation
    assert "low_confidence" in d.reasons


def test_escalation_autosend_trusted_simple():
    rules = EscalationRules(always_ask_new_contacts=True, trusted_contacts=["alex"])
    d = classify_escalation(
        draft_reply="Sounds good",
        is_new_contact=True,
        contact_name="Alex",
        confidence=0.9,
        rules=rules,
    )
    assert not d.needs_confirmation


def test_prepare_outbound_never_queues_needs_you():
    """Needs-you portal removed — escalations no longer block auto-send."""
    q = NeedsYouQueue()
    cfg = SocialModeConfig()
    decision = prepare_outbound(
        draft_reply="I can meet tomorrow at 8pm",
        config=cfg,
        queue=q,
        app_name="WhatsApp",
        package_name="com.whatsapp",
        conversation_id="t1",
        contact_name="Sam",
        inbound_preview="Free tomorrow?",
        confidence=0.9,
    )
    assert decision.needs_you is False
    assert decision.needs_you_id is None
    assert q.pending_count() == 0
    assert DEFAULT_SIGNATURE in decision.final_text


def test_prepare_outbound_autosend_clean():
    q = NeedsYouQueue()
    cfg = SocialModeConfig()
    cfg.escalation.always_ask_new_contacts = False
    decision = prepare_outbound(
        draft_reply="lol nice",
        config=cfg,
        queue=q,
        app_name="WhatsApp",
        package_name="com.whatsapp",
        conversation_id="t2",
        contact_name="Sam",
        confidence=0.95,
        is_new_contact=False,
    )
    assert not decision.needs_you
    assert q.pending_count() == 0


def test_queue_approve_edit_reject_flow():
    q = NeedsYouQueue()
    item = q.add(
        source="dating",
        app_name="Hinge",
        package_name="co.hinge.app",
        conversation_id="m1",
        contact_name="Pat",
        inbound_preview="Hey",
        draft_reply="Hi!",
        reasons=["dating_review"],
    )
    assert q.pending_count() == 1
    assert q.edit(item.id, "Hi there!")
    approved = q.approve(item.id)
    assert approved and approved.status == "approved"
    assert q.pending_count() == 0

    item2 = q.add(
        source="social",
        app_name="X",
        package_name="com.twitter.android",
        conversation_id="m2",
        contact_name="Lee",
        inbound_preview="",
        draft_reply="yo",
        reasons=["low_confidence"],
    )
    assert q.reject(item2.id)
    assert q.get(item2.id).status == "rejected"


def test_summarize_unreads():
    s = summarize_unreads(
        [
            {"app_name": "WhatsApp", "unread": 3, "contact_name": "A"},
            {"app_name": "WhatsApp", "unread": 1, "contact_name": "B"},
            {"app_name": "Instagram", "unread": 2, "contact_name": "C"},
        ]
    )
    assert s["total_unread"] == 6
    assert s["by_app"]["WhatsApp"] == 4


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("JWT_SECRET", "test")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    from backend import main as backend_main

    backend_main._needs_you_queue = None
    backend_main._social_config_store.clear()
    backend_main.dating_mode_state["review_queue"] = []
    backend_main.agent_mode_state.update({"mode": "normal", "speed_preset": "balanced"})
    return TestClient(backend_main.app)


def test_api_social_draft_autosends_without_needs_you(client):
    res = client.post("/api/mode", json={"mode": "social", "speed_preset": "balanced"})
    assert res.status_code == 200
    assert res.json()["mode"] == "social"

    draft = client.post(
        "/api/social/draft",
        json={
            "app_name": "WhatsApp",
            "package_name": "com.whatsapp",
            "conversation_id": "c9",
            "contact_name": "NewPerson",
            "draft_reply": "Want to grab dinner Friday at 7?",
            "inbound_preview": "We should hang",
            "confidence": 0.9,
            "is_new_contact": True,
        },
    )
    assert draft.status_code == 200
    body = draft.json()
    assert body["needs_you"] is False
    assert body["badge"] == 0
    assert "— from MacAI" in body["final_text"]

    ny = client.get("/api/needs-you")
    assert ny.status_code == 200
    assert ny.json()["badge"] == 0
    assert ny.json()["items"] == []
    assert client.post("/api/needs-you/x/approve").status_code == 410


def test_dating_review_queue_removed(client):
    res = client.post(
        "/api/dating/review",
        json={
            "id": "dating_msg_1",
            "app_name": "Hinge",
            "package_name": "co.hinge.app",
            "conversation_id": "h1",
            "profile_name": "Jordan",
            "message": "Hey, how's your week?",
            "is_opener": True,
        },
    )
    assert res.status_code == 200
    assert res.json().get("removed") is True
    ny = client.get("/api/needs-you?source=dating")
    assert ny.json()["items"] == []
    assert ny.json()["badge"] == 0
