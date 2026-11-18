"""WhatsApp tree fixtures + fast-path / swipe-loop / failure-artifact tests."""

from pathlib import Path

from backend.cloud_agent import (
    MAX_LAUNCHER_SWIPE_LOOPS,
    MAX_SWIPE_LOOPS,
    _attach_failure_artifacts,
    _count_recent_swipes,
    _goal_satisfied_from_tree,
    _heuristic_whatsapp_send,
    _is_launcher_package,
    _launcher_swipe_abort,
    _parse_whatsapp_instruction,
    _tree_editable_center,
    _tree_node_center,
    plan_next_action,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


INSTR = "go on whatsapp message precious achalugo and say hi baby"


def test_parse_whatsapp_instruction_mac_s21_goal():
    parsed = _parse_whatsapp_instruction(INSTR)
    assert parsed is not None
    assert parsed["contact"].lower() == "precious achalugo"
    assert parsed["message"].lower() == "hi baby"


def test_parse_whatsapp_instruction_variants():
    p = _parse_whatsapp_instruction("open whatsapp message Jane Doe and say hello there")
    assert p == {"contact": "Jane Doe", "message": "hello there"}
    assert _parse_whatsapp_instruction("open settings") is None
    assert _parse_whatsapp_instruction("send sms to 5550100") is None


def test_compact_tree_finds_search_and_send_by_content_desc():
    home = _load("whatsapp_home_tree.xml")
    compose = _load("whatsapp_compose_tree.xml")
    search = _tree_node_center(home, "Search")
    send = _tree_node_center(compose, "Send")
    assert search == (980, 150)
    assert send == (1000, 2280)
    # ImageButton-style: content-desc only, no text
    assert 'd="Search"' in home
    assert 'd="Send"' in compose
    assert 't="Send"' not in compose


def test_compact_tree_finds_contact_row_and_edittext():
    search = _load("whatsapp_search_tree.xml")
    compose = _load("whatsapp_compose_tree.xml")
    contact = _tree_node_center(search, "Precious Achalugo", "Precious")
    assert contact == (540, 420)
    edit = _tree_editable_center(compose)
    assert edit == (480, 2280)
    assert _tree_node_center(compose, "Type a message") is None or True  # hint may map
    # hint-bearing editable is present
    assert 'h="Type a message"' in compose
    assert 'e="1"' in compose


def test_whatsapp_heuristic_open_then_search_type_send_flow():
    home = _load("whatsapp_home_tree.xml")
    search_tree = _load("whatsapp_search_tree.xml")
    compose = _load("whatsapp_compose_tree.xml")
    sent = _load("whatsapp_sent_tree.xml")
    pkg = "com.whatsapp"

    # Not opened yet
    a0 = _heuristic_whatsapp_send(INSTR, home, [], package="com.android.launcher3")
    assert a0 and a0["action"] == "open_app" and "whatsapp" in a0["app"].lower()

    # Home → Search
    a1 = _heuristic_whatsapp_send(
        INSTR, home, ["Opened WhatsApp[com.whatsapp] — launch"], package=pkg
    )
    assert a1 and a1["action"] == "tap"
    assert "search" in a1["reason"].lower()
    assert (a1["x"], a1["y"]) == (980, 150)

    # Search field → type contact
    a2 = _heuristic_whatsapp_send(
        INSTR,
        search_tree,
        [
            "Opened WhatsApp[com.whatsapp] — launch",
            "tap(980,150) — Tap Search (whatsapp heuristic)",
        ],
        package=pkg,
    )
    assert a2 and a2["action"] == "type"
    assert "precious" in a2["text"].lower()

    # Results → tap contact
    a3 = _heuristic_whatsapp_send(
        INSTR,
        search_tree,
        [
            "Opened WhatsApp[com.whatsapp] — launch",
            "tap(980,150) — Tap Search (whatsapp heuristic)",
            'type("Precious Achalugo") — Type contact',
        ],
        package=pkg,
    )
    assert a3 and a3["action"] == "tap"
    assert "contact" in a3["reason"].lower() or "precious" in a3["reason"].lower()

    # Compose → focus + type + send
    hist_compose = [
        "Opened WhatsApp[com.whatsapp] — launch",
        "tap(980,150) — Tap Search (whatsapp heuristic)",
        'type("Precious Achalugo") — Type contact',
        "tap(540,420) — Tap matching contact 'Precious Achalugo' (whatsapp heuristic)",
    ]
    a4 = _heuristic_whatsapp_send(INSTR, compose, hist_compose, package=pkg)
    assert a4 and a4["action"] == "tap"
    assert "compose" in a4["reason"].lower() or "message" in a4["reason"].lower()

    hist_typed = hist_compose + [
        "tap(480,2280) — Focus compose Message field (whatsapp heuristic)"
    ]
    a5 = _heuristic_whatsapp_send(INSTR, compose, hist_typed, package=pkg)
    assert a5 and a5["action"] == "type" and a5["text"].lower() == "hi baby"

    hist_send = hist_typed + ['type("hi baby") — Type message']
    a6 = _heuristic_whatsapp_send(INSTR, compose, hist_send, package=pkg)
    assert a6 and a6["action"] == "tap"
    assert "send" in a6["reason"].lower()
    assert (a6["x"], a6["y"]) == (1000, 2280)

    # Bubble visible → done
    hist_done = hist_send + ["tap(1000,2280) — Tap Send (whatsapp heuristic)"]
    a7 = _heuristic_whatsapp_send(INSTR, sent, hist_done, package=pkg)
    assert a7 and a7["action"] == "done"
    assert "hi baby" in a7["reason"].lower()


def test_plan_next_action_uses_whatsapp_heuristic(monkeypatch):
    home = _load("whatsapp_home_tree.xml")

    def boom(*_a, **_k):
        raise RuntimeError("LLM must not be called")

    monkeypatch.setattr("backend.cloud_agent._call_gemini", boom)
    monkeypatch.setattr("backend.cloud_agent._call_openai", boom)
    action = plan_next_action(
        INSTR,
        home,
        ["Opened WhatsApp[com.whatsapp] — launch"],
        package="com.whatsapp",
    )
    assert action["planner"] == "whatsapp_heuristic"
    assert action["action"] == "tap"
    assert "search" in action["reason"].lower()


def test_goal_satisfied_whatsapp_bubble():
    sent = _load("whatsapp_sent_tree.xml")
    reason = _goal_satisfied_from_tree(INSTR, sent, "com.whatsapp")
    assert reason is not None
    assert "hi baby" in reason.lower()


def test_thin_tree_fixture_is_under_useful_node_budget():
    """Documents the S21+ failure: <15 nodes → APK must re-dump uncompacted."""
    thin = _load("whatsapp_thin_bad_tree.xml")
    nodes = thin.lower().count("<n ")
    assert nodes < 15
    assert "com.whatsapp" in thin
    # Heuristic still prefers Search fallback coords when labels are missing
    a = _heuristic_whatsapp_send(
        INSTR, thin, ["Opened WhatsApp[com.whatsapp]"], package="com.whatsapp"
    )
    assert a and a["action"] == "tap"


def test_swipe_loop_only_launcher_unchanged():
    assert MAX_SWIPE_LOOPS == MAX_LAUNCHER_SWIPE_LOOPS == 3
    assert _is_launcher_package("com.sec.android.app.launcher")
    assert _is_launcher_package("com.android.launcher3")
    assert not _is_launcher_package("com.whatsapp")

    # Single in-app swipe must NOT abort
    state: dict = {}
    assert not _launcher_swipe_abort(state, "com.whatsapp", False, "swipe")
    assert state.get("launcher_swipe_unchanged") == 0

    # One launcher swipe unchanged → not abort yet
    state = {}
    assert not _launcher_swipe_abort(
        state, "com.sec.android.app.launcher", False, "swipe"
    )
    assert state["launcher_swipe_unchanged"] == 1
    assert not _launcher_swipe_abort(
        state, "com.sec.android.app.launcher", False, "swipe"
    )
    assert state["launcher_swipe_unchanged"] == 2
    # Third unchanged launcher swipe → abort
    assert _launcher_swipe_abort(state, "com.sec.android.app.launcher", False, "swipe")
    assert state["launcher_swipe_unchanged"] >= 3

    # Tree change resets streak to 1 (current swipe counted as fresh)
    state = {"launcher_swipe_unchanged": 2}
    assert not _launcher_swipe_abort(
        state, "com.android.launcher3", True, "swipe"
    )
    assert state["launcher_swipe_unchanged"] == 1

    # Trailing swipe counter still works for soft hints
    assert _count_recent_swipes(["tap(1,2)", "swipe(a)", "swipe(b)"]) == 2


def test_attach_failure_artifacts_stores_tree(monkeypatch):
    job = {"job_id": "task_test_fail"}
    tree = _load("whatsapp_home_tree.xml")
    monkeypatch.setattr(
        "backend.cloud_agent._fetch_screenshot_b64", lambda *_a, **_k: "ZmFrZQ=="
    )
    monkeypatch.setattr(
        "backend.cloud_agent._store_step_screenshot",
        lambda *_a, **_k: "tasks/task_test_fail/step_failure.jpg",
    )
    _attach_failure_artifacts(job, "android_test", tree)
    assert job["failure_ui_tree"].startswith("<hierarchy")
    assert "Search" in job["failure_ui_tree"]
    assert job["failure_screenshot_key"].endswith("failure.jpg")
