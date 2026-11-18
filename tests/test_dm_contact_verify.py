"""DM fast-path: tap result rows (not search), verify chat before typing."""

from pathlib import Path

from backend.dm_heuristics import (
    DM_APP_PROFILES,
    chat_screen_verified,
    find_contact_result_center,
    heuristic_dm_send,
    parse_dm_instruction,
)
from backend.message_text_guard import extract_user_message_text

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


MAC_INSTR = "whatsapp find and message Precious Achalugo tell her hi baby"


def test_parse_find_and_message_tell_her():
    p = parse_dm_instruction(MAC_INSTR)
    assert p is not None
    assert p["app"] == "whatsapp"
    assert p["contact"].lower() == "precious achalugo"
    assert p["message"].lower() == "hi baby"
    assert extract_user_message_text(MAC_INSTR) == "hi baby"


def test_contact_finder_skips_search_edittext_with_typed_name():
    search = _load("whatsapp_search_tree.xml")
    # Real bug: typed contact remains visible in the search EditText
    buggy = search.replace(
        '<n e="1" h="Search…" xy="540,150" b="160,90,980,210"/>',
        '<n e="1" h="Search…" t="Precious Achalugo" xy="540,150" b="160,90,980,210"/>',
    )
    labs = DM_APP_PROFILES["whatsapp"]["search_labels"]
    c = find_contact_result_center(buggy, "Precious Achalugo", search_labels=labs)
    assert c == (540, 420)  # result row, NOT search field at y=150


def test_never_type_message_on_search_screen():
    search = _load("whatsapp_search_tree.xml")
    hist = [
        "Opened WhatsApp[com.whatsapp] — launch",
        "tap(980,150) — Tap Search (whatsapp heuristic)",
        'type("Precious Achalugo") — Type contact',
        # Bad history: claimed tap contact but still on search
        "tap(540,150) — Tap matching contact 'Precious Achalugo' (whatsapp heuristic)",
        "tap(540,150) — Focus compose Message field (whatsapp heuristic)",
    ]
    a = heuristic_dm_send(MAC_INSTR, search, hist, package="com.whatsapp")
    assert a is not None
    # Must NOT type the message body into search
    if a["action"] == "type":
        assert "hi baby" not in a["text"].lower()
        assert "precious" in a["text"].lower()
    else:
        assert a["action"] in ("tap", "swipe", "fail")
        assert "hi baby" not in str(a.get("text") or "").lower()


def test_type_message_only_when_chat_verified():
    compose = _load("whatsapp_compose_tree.xml")
    labs = DM_APP_PROFILES["whatsapp"]["compose_labels"]
    assert chat_screen_verified(compose, "Precious Achalugo", labs)
    hist = [
        "Opened WhatsApp[com.whatsapp] — launch",
        "tap(980,150) — Tap Search (whatsapp heuristic)",
        'type("Precious Achalugo") — Type contact',
        "tap(540,420) — Tap matching contact 'Precious Achalugo' (whatsapp heuristic)",
        "tap(480,2280) — Focus compose Message field (whatsapp heuristic)",
    ]
    a = heuristic_dm_send(MAC_INSTR, compose, hist, package="com.whatsapp")
    assert a and a["action"] == "type"
    assert a["text"].lower() == "hi baby"
    assert a.get("fastpath_step") == "type_message"


def test_dry_run_stops_before_send():
    compose = _load("whatsapp_compose_tree.xml")
    hist = [
        "Opened WhatsApp[com.whatsapp] — launch",
        "tap(980,150) — Tap Search (whatsapp heuristic)",
        'type("Precious Achalugo") — Type contact',
        "tap(540,420) — Tap matching contact 'Precious Achalugo' (whatsapp heuristic)",
        "tap(480,2280) — Focus compose Message field (whatsapp heuristic)",
        'type("hi baby") — Type message',
    ]
    a = heuristic_dm_send(
        MAC_INSTR, compose, hist, package="com.whatsapp", dry_run=True
    )
    assert a and a["action"] == "done"
    assert "dry_run" in a["reason"].lower()
    assert a.get("fastpath_step") == "dry_run_stop"
