"""Social mode signature toggles, escalation classification, Needs-you queue."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mobilerun.needs_you.escalation import EscalationRules, classify_escalation
from mobilerun.needs_you.queue import NeedsYouQueue
from mobilerun.social.agent import prepare_outbound, summarize_unreads
from mobilerun.social.config import SocialModeConfig
from mobilerun.social.signature import DEFAULT_SIGNATURE, SignatureConfig


def test_signature_never_appends():
    """Portal removed signature UI; apply() is always a pass-through."""
    sig = SignatureConfig()
    assert sig.apply("Hey there") == "Hey there"
    assert sig.is_enabled() is False


def test_signature_ignores_enabled_flags():
    sig = SignatureConfig(enabled_global=True, text=DEFAULT_SIGNATURE)
    sig.per_app["com.whatsapp"] = True
    assert sig.apply("Hi", package_name="com.whatsapp") == "Hi"
    assert sig.apply("Hi", package_name="com.instagram.android") == "Hi"


def test_signature_ignores_per_contact():
    sig = SignatureConfig(enabled_global=True, text=DEFAULT_SIGNATURE)
    key = sig.contact_key("com.whatsapp", "c1", "Alex")
    sig.per_contact[key] = True
    out = sig.apply(
        "Yo", package_name="com.whatsapp", conversation_id="c1", contact_name="Alex"
    )
    assert out == "Yo"


def test_signature_strips_trailing_whitespace_only():
    sig = SignatureConfig(text="- from MacAI")
    assert sig.apply("Hello  \n") == "Hello"
    assert sig.apply(sig.apply("Hello")) == "Hello"


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
    """Needs-you portal removed; escalations no longer block auto-send."""
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
    assert decision.final_text == "I can meet tomorrow at 8pm"
    assert DEFAULT_SIGNATURE not in decision.final_text


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
    assert body["final_text"] == "Want to grab dinner Friday at 7?"
    assert "from MacAI" not in body["final_text"]

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
