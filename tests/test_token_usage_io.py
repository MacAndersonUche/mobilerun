"""AI token usage rollup for the Usage page."""

from __future__ import annotations


def test_record_and_summary_last_30_days(monkeypatch):
    from backend import token_usage_io as tio

    store: dict = {}

    def fake_get(uid, name):
        return store.get(f"{uid}:{name}")

    def fake_save(uid, name, data):
        store[f"{uid}:{name}"] = data
        return True

    monkeypatch.setattr(tio, "_storage", lambda: (fake_get, fake_save))
    tio.set_usage_user("mac@test")
    tio.record_llm_tokens(
        provider="gemini",
        model="gemini-test",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    tio.record_llm_tokens(
        provider="openai",
        model="gpt-test",
        prompt_tokens=20,
        completion_tokens=8,
        total_tokens=28,
    )
    summary = tio.usage_summary("mac@test", days=30)
    assert summary["timezone"] == "Europe/London"
    assert summary["days"] == 30
    assert len(summary["daily"]) == 30
    assert summary["totals"]["total_tokens"] == 43
    assert summary["totals"]["requests"] == 2
    assert summary["by_provider"]["gemini"]["total_tokens"] == 15
    assert summary["by_provider"]["openai"]["total_tokens"] == 28
    tio.clear_usage_user()
