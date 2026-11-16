"""Self-hosted LLM config API: Gemini / OpenAI / Anthropic / xAI Grok."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    from backend import main as backend_main

    return TestClient(backend_main.app)


def test_get_llm_config_lists_xai_as_fourth_provider(client):
    res = client.get("/api/config/llm")
    assert res.status_code == 200
    data = res.json()
    assert data["supported_providers"] == ["gemini", "openai", "anthropic", "xai"]
    assert data["default_models"]["xai"] == "grok-4.7"
    assert data["xai_api_base"] == "https://api.x.ai/v1"


def test_update_llm_config_accepts_xai_and_sets_env(client, monkeypatch):
    res = client.post(
        "/api/config/llm",
        json={
            "provider": "xai",
            "model": "grok-4.7",
            "api_key": "xai-test-key",
            "temperature": 0.5,
            "max_tokens": 1024,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["provider"] == "xai"
    assert body["model"] == "grok-4.7"
    assert os.environ["LLM_PROVIDER"] == "xai"
    assert os.environ["LLM_MODEL"] == "grok-4.7"
    assert os.environ["XAI_API_KEY"] == "xai-test-key"
    assert os.environ["LLM_TEMPERATURE"] == "0.5"


def test_update_llm_config_xai_default_model_when_blank(client):
    res = client.post(
        "/api/config/llm",
        json={
            "provider": "xai",
            "model": "  ",
            "api_key": "",
            "temperature": 0.7,
            "max_tokens": 2048,
        },
    )
    assert res.status_code == 200
    assert res.json()["model"] == "grok-4.7"
    assert os.environ["LLM_MODEL"] == "grok-4.7"


def test_update_llm_config_rejects_unknown_provider(client):
    res = client.post(
        "/api/config/llm",
        json={
            "provider": "ollama",
            "model": "llama3",
            "api_key": "",
            "temperature": 0.7,
            "max_tokens": 2048,
        },
    )
    assert res.status_code == 400
    assert "xai" in res.json()["detail"]


def test_update_llm_config_allows_configurable_grok_model(client):
    res = client.post(
        "/api/config/llm",
        json={
            "provider": "XAI",
            "model": "grok-4.6",
            "api_key": "xai-alt",
            "temperature": 0.2,
            "max_tokens": 512,
        },
    )
    assert res.status_code == 200
    assert res.json()["provider"] == "xai"
    assert res.json()["model"] == "grok-4.6"
    assert os.environ["LLM_MODEL"] == "grok-4.6"
