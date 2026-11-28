"""Reliability: multi-strategy recovery before hard-fail."""

from backend.recovery import (
    MIN_DISTINCT_STRATEGIES,
    distinct_strategy_count,
    popup_center,
    recovery_action,
    should_hard_fail,
    tree_looks_blocked,
)


def test_popup_center_finds_allow():
    tree = (
        '<hierarchy><n t="Allow" c="1" xy="540,1400"/>'
        '<n t="Deny" c="1" xy="540,1600"/></hierarchy>'
    )
    assert popup_center(tree) == (540, 1400)


def test_tree_looks_blocked_anr_and_permission():
    assert tree_looks_blocked(
        '<hierarchy><n t="App isn\'t responding"/><n t="Wait"/><n t="Close app"/></hierarchy>'
    )
    assert tree_looks_blocked(
        '<hierarchy><n t="Allow PhonePilot to send you notifications"/>'
        '<n t="Allow" c="1" xy="200,1800"/></hierarchy>'
    )
    assert not tree_looks_blocked(
        '<hierarchy nodes="20">'
        + ('<n t="Chat" c="1" xy="1,1"/>' * 20)
        + "</hierarchy>"
    )


def test_recovery_rotates_distinct_strategies():
    state: dict = {}
    names = []
    for _ in range(MIN_DISTINCT_STRATEGIES):
        a = recovery_action(
            state,
            "go on whatsapp message bob and say hi",
            '<hierarchy empty="true"/>',
            "",
        )
        names.append(a.get("_recovery") or a["planner"].split(":")[-1])
    assert len(set(names)) >= MIN_DISTINCT_STRATEGIES - 1
    assert distinct_strategy_count(state) >= MIN_DISTINCT_STRATEGIES - 1
    assert not should_hard_fail({"recovery_tried": ["a", "b"], "recovery_counts": {}})


def test_hard_fail_only_after_enough_strategies():
    state = {
        "recovery_tried": [
            "dismiss_dialogs",
            "redump_tree",
            "vision",
            "back",
            "alt_path",
        ],
        "recovery_counts": {
            "dismiss_dialogs": 2,
            "redump_tree": 2,
            "vision": 2,
            "back": 1,
            "alt_path": 1,
        },
    }
    assert should_hard_fail(state)
    assert not should_hard_fail(
        {
            "recovery_tried": ["dismiss_dialogs"],
            "recovery_counts": {"dismiss_dialogs": 1},
        }
    )


def test_whatsapp_recovery_prefers_open_or_search():
    state: dict = {}
    # Force home_then_open by marking others used
    state["recovery_tried"] = [
        "dismiss_dialogs",
        "redump_tree",
        "vision",
        "back",
        "reconnect_wait",
        "alt_path",
    ]
    state["recovery_counts"] = {k: 2 for k in state["recovery_tried"]}
    a = recovery_action(
        state,
        "go on whatsapp message precious and say hi",
        "<hierarchy/>",
        "",
        prefer=["home_then_open"],
    )
    assert a["action"] in ("open_app", "home", "tap", "back")


def test_reliability_10x_dm_heuristic_fixture(monkeypatch):
    """10× WhatsApp Search tap from the same fixture — must succeed every time."""
    from backend.cloud_agent import plan_next_action

    tree = (
        '<hierarchy windows="1" nodes="20" packages="com.whatsapp">'
        '<w p="com.whatsapp">'
        '<n d="Search" c="1" xy="980,150" b="900,80,1060,220"/>'
        '<n t="Chats" c="1" xy="180,280"/>'
        "</w></hierarchy>"
    )

    def boom(*_a, **_k):
        raise RuntimeError("no llm")

    monkeypatch.setattr("backend.cloud_agent._call_gemini", boom)
    monkeypatch.setattr("backend.cloud_agent._call_openai", boom)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    ok = 0
    for i in range(10):
        a = plan_next_action(
            "go on whatsapp message precious achalugo and say hi baby",
            tree,
            ["Opened WhatsApp[com.whatsapp] — launch"],
            package="com.whatsapp",
        )
        if a.get("action") == "tap" and a.get("planner") == "whatsapp_heuristic":
            ok += 1
    assert ok == 10, f"success rate {ok}/10"


def test_reliability_10x_multi_app_open(monkeypatch):
    from backend.cloud_agent import plan_next_action

    def boom(*_a, **_k):
        raise RuntimeError("no llm")

    monkeypatch.setattr("backend.cloud_agent._call_gemini", boom)
    monkeypatch.setattr("backend.cloud_agent._call_openai", boom)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    cases = [
        ("instagram message jane and say hey", "Instagram"),
        ("messenger message jane and say hey", "Messenger"),
        ("telegram message bob and say ping", "Telegram"),
        ("tinder message alex and say hi", "Tinder"),
        ("bumble message sam and say hi", "Bumble"),
        ("hinge message riley and say hello", "Hinge"),
    ]
    ok = 0
    total = 0
    for instr, label in cases:
        for _ in range(10):
            total += 1
            a = plan_next_action(
                instr,
                '<hierarchy empty="true"/>',
                [],
                package="com.android.launcher3",
            )
            if (
                a.get("action") == "open_app"
                and label.lower() in str(a.get("app")).lower()
            ):
                ok += 1
    rate = ok / total
    assert rate == 1.0, f"open_app success {ok}/{total} ({rate:.0%})"
