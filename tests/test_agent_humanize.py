"""Human-like agent pacing: delays, jitter, step timing percentiles."""

import time

from backend.agent_humanize import (
    AGENT_DELAY_HI,
    AGENT_DELAY_LO,
    jitter_tap,
    percentile,
    sample_inter_step_delay_s,
    update_step_timing_stats,
)
from backend.cloud_agent import plan_next_action


def test_inter_step_delay_band():
    for i in range(40):
        d = sample_inter_step_delay_s(seed=f"t{i}")
        assert AGENT_DELAY_LO - 1e-6 <= d <= AGENT_DELAY_HI + 1e-6


def test_jitter_tap_moves_within_bounds():
    xs = set()
    for i in range(30):
        x, y = jitter_tap(500, 1000, bounds=(400, 900, 600, 1100), seed=f"j{i}")
        xs.add((x, y))
        assert 400 < x < 600
        assert 900 < y < 1100
    # Not a single fixed point
    assert len(xs) > 5


def test_percentile_p50_p95():
    vals = [100.0, 200.0, 300.0, 400.0, 1000.0]
    assert percentile(vals, 50) == 300.0
    assert percentile(vals, 95) >= 400.0
    assert percentile([], 50) is None


def test_update_step_timing_stats():
    state: dict = {}
    for ms in (800, 1200, 900, 3500, 1100):
        update_step_timing_stats(state, ms)
    stats = state["step_timing_stats"]
    assert stats["n"] == 5
    assert stats["p50_ms"] is not None
    assert stats["p95_ms"] is not None
    assert stats["p95_ms"] >= stats["p50_ms"]


def test_dm_fast_path_skips_llm(monkeypatch):
    tree = (
        '<hierarchy nodes="20" packages="com.whatsapp">'
        '<w p="com.whatsapp">'
        '<n d="Search" c="1" xy="980,150"/>'
        "</w></hierarchy>"
    )

    def boom(*_a, **_k):
        raise RuntimeError("LLM must not be called on DM fast-path")

    monkeypatch.setattr("backend.cloud_agent._call_gemini", boom)
    monkeypatch.setattr("backend.cloud_agent._call_openai", boom)
    # No API keys required
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    action = plan_next_action(
        "go on whatsapp message precious achalugo and say hi baby",
        tree,
        ["Opened WhatsApp[com.whatsapp] — launch"],
        package="com.whatsapp",
    )
    assert action["planner"] == "whatsapp_heuristic"
    assert action["action"] == "tap"
    assert action.get("llm_provider") is None


def test_sample_delay_is_fast():
    t0 = time.perf_counter()
    _ = sample_inter_step_delay_s(seed="perf")
    # Sampling itself is instant (no sleep)
    assert (time.perf_counter() - t0) < 0.05
