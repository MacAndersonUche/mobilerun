"""Every planner-emitted action kind must be executable by the step runner."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from backend.cloud_agent import (
    RUNNER_EXECUTABLE_ACTIONS,
    execute_action,
    runner_can_execute,
)

ROOT = Path(__file__).resolve().parents[1]
PLANNER_FILES = [
    ROOT / "backend" / "bulk_bench_heuristics.py",
    ROOT / "backend" / "dm_heuristics.py",
]


def _planner_action_kinds() -> set[str]:
    """Collect string literals assigned to action= in planner modules."""
    kinds: set[str] = set()
    pat = re.compile(r'["\']action["\']\s*:\s*["\']([a-z_]+)["\']')
    for path in PLANNER_FILES:
        text = path.read_text(encoding="utf-8")
        kinds.update(pat.findall(text))
        # Also AST-walk dict literals for robustness
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "action"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                ):
                    kinds.add(v.value.lower())
    # Internal / non-device markers planners may set
    kinds.discard("cloud_step")
    return kinds


def test_runner_executable_covers_planner_actions():
    kinds = _planner_action_kinds()
    assert kinds, "expected planner action kinds"
    missing = sorted(k for k in kinds if not runner_can_execute(k))
    assert not missing, (
        f"Planner emits action kinds the runner cannot execute: {missing}. "
        f"Known: {sorted(RUNNER_EXECUTABLE_ACTIONS)}"
    )


def test_press_button_is_runner_executable():
    assert runner_can_execute("press_button")
    assert runner_can_execute({"action": "press_button", "button": "back"})


def test_execute_action_press_button_calls_device(monkeypatch):
    calls: list[tuple] = []

    def fake_call(device_id, cmd, params, timeout_s=10):
        calls.append((device_id, cmd, params))
        return {"ok": True}

    import backend.cloud_agent as ca

    monkeypatch.setattr(
        ca,
        "execute_action",
        ca.execute_action,
    )
    # Patch import inside execute_action
    import backend.device_rpc as rpc

    monkeypatch.setattr(rpc, "call_device", fake_call)
    # Also if imported as device_rpc at top of function via try
    import sys

    sys.modules["device_rpc"] = rpc

    msg = execute_action(
        "dev1",
        {"action": "press_button", "button": "back"},
    )
    assert "back" in msg.lower() or "GLOBAL_ACTION_BACK" in msg
    assert calls and calls[0][1] == "press_button"
    assert calls[0][2].get("button") == "back"


def test_execute_action_rejects_unknown_press_button(monkeypatch):
    import backend.device_rpc as rpc

    monkeypatch.setattr(rpc, "call_device", lambda *a, **k: {"ok": True})
    import sys

    sys.modules["device_rpc"] = rpc
    try:
        execute_action("dev1", {"action": "press_button", "button": "power"})
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "back/home/enter" in str(e)
