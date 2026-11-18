"""Hard rule: typed message bodies must be bank or user text — never AI rewrite."""

from backend.cloud_agent import plan_next_action
from backend.message_text_guard import (
    allowed_message_texts,
    enforce_message_text,
    extract_user_message_text,
)

INSTR = "go on whatsapp message precious achalugo and say hi baby"


def test_extract_user_message_from_task():
    assert extract_user_message_text(INSTR) == "hi baby"
    assert (
        extract_user_message_text('instagram message jane and say "hello there"')
        == "hello there"
    )
    assert extract_user_message_text("open settings") is None


def test_enforce_accepts_exact_user_text():
    action = {
        "action": "type",
        "text": "hi baby",
        "reason": "Type message (whatsapp heuristic)",
    }
    out = enforce_message_text(action, INSTR)
    assert out["action"] == "type"
    assert out["text"] == "hi baby"
    assert out["_text_source"] in ("exact_allow", "casefold_allow")


def test_enforce_forces_user_text_when_llm_rewrites():
    action = {
        "action": "type",
        "text": "Hey Precious 😊 missing you!",  # LLM rewrite — forbidden
        "reason": "Type a friendly message",
        "planner": "llm",
    }
    out = enforce_message_text(action, INSTR)
    # Single user text → force verbatim
    assert out["action"] == "type"
    assert out["text"] == "hi baby"
    assert out["_text_source"] == "forced_user_or_bank"


def test_enforce_rejects_invented_text_with_multi_bank():
    job = {
        "message_bank": ["hey there", "what's up", "good morning"],
    }
    action = {
        "action": "type",
        "text": "I rewrote this in a cooler way",
        "reason": "Type message",
        "planner": "llm",
    }
    out = enforce_message_text(
        action,
        "tinder message alex and say hey there",  # user text also allowed
        job=job,
    )
    # User text "hey there" is unique from instruction — forced
    assert out["action"] == "type"
    assert out["text"] == "hey there"


def test_enforce_fails_when_no_allow_list_for_messaging():
    action = {"action": "type", "text": "AI invented opener", "reason": "Type message"}
    out = enforce_message_text(action, "message someone on whatsapp")
    assert out["action"] == "fail"
    assert "guard" in out["reason"].lower() or "bank" in out["reason"].lower()


def test_contact_typing_not_guarded_as_message_body():
    action = {
        "action": "type",
        "text": "Precious Achalugo",
        "reason": "Type contact 'Precious Achalugo' (whatsapp heuristic)",
    }
    out = enforce_message_text(action, INSTR)
    assert out["action"] == "type"
    assert out["text"] == "Precious Achalugo"
    assert out["_text_source"] == "contact_or_search"


def test_bank_entry_allowed():
    job = {"selected_message": "what's cooking?"}
    allowed = allowed_message_texts("send a hinge message to Sam", job=job)
    assert "what's cooking?" in allowed
    out = enforce_message_text(
        {"action": "type", "text": "what's cooking?", "reason": "Type message"},
        "hinge message Sam and say what's cooking?",
        job=job,
    )
    assert out["text"] == "what's cooking?"


def test_plan_llm_type_is_sanitized(monkeypatch):
    tree = (
        '<hierarchy packages="com.whatsapp"><w p="com.whatsapp">'
        '<n e="1" h="Type a message" xy="480,2280"/>'
        '<n d="Send" c="1" xy="1000,2280"/>'
        "</w></hierarchy>"
    )

    def fake_openai(*_a, **_k):
        return (
            '{"action":"type","text":"Heyy baby I miss you so much 💕",'
            '"reason":"compose a sweet message"}'
        )

    monkeypatch.setattr("backend.cloud_agent._call_openai", fake_openai)
    monkeypatch.setattr(
        "backend.cloud_agent._call_gemini",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Bypass DM heuristic so LLM path runs
    monkeypatch.setattr(
        "backend.cloud_agent._heuristic_dm_send", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "backend.cloud_agent._heuristic_messaging_send", lambda *_a, **_k: None
    )

    action = plan_next_action(
        INSTR,
        tree,
        [
            "Opened WhatsApp",
            "tap search",
            'type("Precious Achalugo") — Type contact',
            "tap matching contact",
            "Focus compose Message field",
        ],
        package="com.whatsapp",
    )
    assert action["action"] == "type"
    assert action["text"] == "hi baby"
    assert action.get("_text_source") in (
        "forced_user_or_bank",
        "exact_allow",
        "casefold_allow",
    )
