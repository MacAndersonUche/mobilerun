"""Multi-app DM fast-paths + sparse-tree vision gate (Social/Dating)."""

from pathlib import Path

from backend.cloud_agent import (
    _heuristic_dm_send,
    _parse_dm_instruction,
    plan_next_action,
)
from backend.dm_heuristics import (
    DM_APP_PROFILES,
    MIN_USEFUL_TREE_NODES,
    detect_dm_app,
    tree_is_sparse,
    tree_node_count,
)

FIXTURES = Path(__file__).parent / "fixtures"
DM = FIXTURES / "dm"


def _load(name: str) -> str:
    p = DM / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_all_supported_apps_registered():
    for key in (
        "whatsapp",
        "instagram",
        "messenger",
        "telegram",
        "tinder",
        "bumble",
        "hinge",
    ):
        assert key in DM_APP_PROFILES
        assert DM_APP_PROFILES[key]["package"]
        assert DM_APP_PROFILES[key]["search_labels"]
        assert DM_APP_PROFILES[key]["send_labels"]


def test_detect_and_parse_per_app():
    cases = [
        (
            "go on whatsapp message precious achalugo and say hi baby",
            "whatsapp",
            "precious achalugo",
            "hi baby",
        ),
        (
            "instagram message jane_doe and say hey there",
            "instagram",
            "jane_doe",
            "hey there",
        ),
        (
            "messenger message Jane Doe and say hello",
            "messenger",
            "Jane Doe",
            "hello",
        ),
        ("telegram message Bob and say ping", "telegram", "Bob", "ping"),
        ("tinder message Alex and say hey", "tinder", "Alex", "hey"),
        ("bumble message Sam and say hi", "bumble", "Sam", "hi"),
        ("yubo message Sam and say hi", "yubo", "Sam", "hi"),
        ("badoo message Sam and say hi", "badoo", "Sam", "hi"),
        ("hinge message Riley and say hello", "hinge", "Riley", "hello"),
    ]
    for instr, app, contact, msg in cases:
        assert detect_dm_app(instr) == app
        parsed = _parse_dm_instruction(instr)
        assert parsed is not None
        assert parsed["app"] == app
        assert parsed["contact"].lower() == contact.lower()
        assert parsed["message"].lower() == msg.lower()


def test_sparse_tree_gate_for_vision():
    sparse = _load("compose_sparse.xml")
    rich = _load("whatsapp_home_tree.xml")
    assert tree_node_count(sparse) < MIN_USEFUL_TREE_NODES
    assert tree_is_sparse(sparse)
    assert tree_is_sparse(sparse, nodes=4)
    # Prefer reported node count from the dump header when present
    assert not tree_is_sparse(rich, nodes=28)
    assert tree_is_sparse(rich, nodes=4)
    assert tree_node_count(rich) >= 8


def test_instagram_opens_then_inbox_or_search():
    home = _load("instagram_inbox.xml")
    a0 = _heuristic_dm_send(
        "instagram message jane_doe and say hey there",
        home,
        [],
        package="com.android.launcher3",
    )
    assert a0 and a0["action"] == "open_app" and "instagram" in a0["app"].lower()

    a1 = _heuristic_dm_send(
        "instagram message jane_doe and say hey there",
        home,
        ["Opened Instagram[com.instagram.android] — launch"],
        package="com.instagram.android",
    )
    assert a1 and a1["action"] == "tap"
    assert a1["planner"] == "instagram_heuristic"
    # Inbox / Search / chats tab / visible contact row
    assert any(
        k in a1["reason"].lower()
        for k in (
            "inbox",
            "search",
            "dm",
            "message",
            "contact",
            "jane",
            "chat",
            "match",
            "tab",
        )
    )


def test_instagram_compose_send():
    compose = _load("instagram_compose.xml")
    hist = [
        "Opened Instagram — launch",
        "tap — Open inbox/DMs (instagram heuristic)",
        "tap — Tap Search (instagram heuristic)",
        'type("jane_doe") — Type contact',
        "tap — Tap matching contact 'jane_doe' (instagram heuristic)",
        "tap — Focus compose Message field (instagram heuristic)",
        'type("hey there") — Type message',
    ]
    a = _heuristic_dm_send(
        "instagram message jane_doe and say hey there",
        compose,
        hist,
        package="com.instagram.android",
    )
    assert a and a["action"] in ("tap", "ime_send")
    assert "send" in a["reason"].lower()
    if a["action"] == "tap":
        assert (a["x"], a["y"]) == (1000, 2280)


def test_messenger_telegram_tinder_bumble_hinge_search():
    specs = [
        (
            "messenger message Jane Doe and say hello",
            "messenger_home.xml",
            "com.facebook.orca",
            "Messenger",
            "messenger_heuristic",
        ),
        (
            "telegram message Bob and say ping",
            "telegram_home.xml",
            "org.telegram.messenger",
            "Telegram",
            "telegram_heuristic",
        ),
        (
            "tinder message Alex and say hey",
            "tinder_inbox.xml",
            "com.tinder",
            "Tinder",
            "tinder_heuristic",
        ),
        (
            "bumble message Sam and say hi",
            "bumble_inbox.xml",
            "com.bumble.app",
            "Bumble",
            "bumble_heuristic",
        ),
        (
            "hinge message Riley and say hello",
            "hinge_inbox.xml",
            "co.hinge.app",
            "Hinge",
            "hinge_heuristic",
        ),
    ]
    for instr, fixture, pkg, label, planner in specs:
        tree = _load(fixture)
        opened = [f"Opened {label}[{pkg}] — launch"]
        # First in-app action after open
        a = _heuristic_dm_send(instr, tree, opened, package=pkg)
        assert a, f"no action for {label}"
        assert a["planner"] == planner
        assert a["action"] == "tap", f"{label} got {a}"
        reason = a["reason"].lower()
        assert any(
            k in reason for k in ("search", "inbox", "contact", "chat", "match")
        ), reason


def test_plan_prefers_dm_heuristic_over_llm(monkeypatch):
    tree = _load("telegram_home.xml")

    def boom(*_a, **_k):
        raise RuntimeError("LLM must not run")

    monkeypatch.setattr("backend.cloud_agent._call_gemini", boom)
    monkeypatch.setattr("backend.cloud_agent._call_openai", boom)
    action = plan_next_action(
        "telegram message Bob and say ping",
        tree,
        ["Opened Telegram[org.telegram.messenger] — launch"],
        package="org.telegram.messenger",
    )
    assert action["planner"] == "telegram_heuristic"
    assert action["action"] == "tap"


def test_vision_note_when_sparse_and_screenshot(monkeypatch):
    sparse = _load("compose_sparse.xml")
    captured = {}

    def fake_openai(prompt, image_b64=None):
        captured["image"] = bool(image_b64)
        captured["prompt"] = prompt
        return '{"action":"tap","x":980,"y":150,"reason":"vision Search"}'

    monkeypatch.setattr("backend.cloud_agent._call_openai", fake_openai)
    monkeypatch.setattr(
        "backend.cloud_agent._call_gemini",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Clear gemini so openai is used
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    action = plan_next_action(
        "open Settings",  # not a DM heuristic
        sparse,
        [],
        image_b64="ZmFrZWltYWdl",
        package="com.instagram.android",
    )
    assert captured.get("image") is True
    assert (
        "vision" in captured.get("prompt", "").lower()
        or "screenshot" in captured.get("prompt", "").lower()
    )
    assert action["action"] == "tap"
    assert action["planner"] == "llm"
