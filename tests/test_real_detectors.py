"""Real-phone detector fixes: chat-list / deck / composer / badge / S3 capture."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    DETECTOR_SETTLE_S,
    _chat_list_screen_verified,
    _deck_visible,
    _open_chats_tab_action,
    deck_card_name,
    plan_bulk_message,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    _attach_failure_artifacts,
    save_detector_miss_tree,
)
from backend.dm_heuristics import (
    badoo_on_connections,
    badoo_on_encounters,
    bumble_on_connections,
    bumble_on_people_deck,
    compose_center_in_thread,
    hily_on_finder,
    thread_header_verified,
    yubo_deck_card_name,
    yubo_on_chat_list,
    yubo_on_deck,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- S3 / failure tree capture ---


def test_attach_failure_artifacts_uploads_tree_json(monkeypatch):
    job = {"job_id": "task_det_fail", "status": "failed", "dry_run": True}
    tree = _load("hily_finder.xml")
    keys = []

    def fake_store(jid, filename, body, content_type="application/octet-stream"):
        keys.append(filename)
        assert jid == "task_det_fail"
        if filename.endswith(".json"):
            assert b'"tree"' in (
                body if isinstance(body, (bytes, bytearray)) else body.encode()
            )
        return f"tasks/{jid}/{filename}"

    monkeypatch.setattr("backend.cloud_agent._store_job_artifact", fake_store)
    monkeypatch.setattr(
        "backend.cloud_agent._fetch_screenshot_b64", lambda *_a, **_k: "ZmFrZQ=="
    )
    monkeypatch.setattr(
        "backend.cloud_agent._store_step_screenshot",
        lambda jid, step, b64: f"tasks/{jid}/step_{step}.jpg",
    )
    _attach_failure_artifacts(job, "android_test", tree)
    assert job["failure_ui_tree_key"] == "tasks/task_det_fail/failure_ui_tree.json"
    assert "failure_ui_tree.json" in keys
    assert job["failure_screenshot_key"].endswith("failure.jpg")


def test_save_detector_miss_tree_logs_key(monkeypatch):
    stored = {}

    def fake_store(jid, filename, body, content_type="application/octet-stream"):
        stored["key"] = f"tasks/{jid}/{filename}"
        stored["body"] = body
        return stored["key"]

    monkeypatch.setattr("backend.cloud_agent._store_job_artifact", fake_store)
    key = save_detector_miss_tree(
        "bumble_on_connections", _load("bumble_deck.xml"), job_id="task_x"
    )
    assert key and key.startswith("tasks/task_x/detector_bumble_on_connections_")
    assert "bumble_on_connections" in str(stored["body"])


# --- Chat-list detectors ---


def test_bumble_connections_multi_signal_rows_only():
    tree = _load("bumble_connections_rows_only.xml")
    assert bumble_on_connections(tree)
    assert _chat_list_screen_verified("bumble", tree)
    assert not bumble_on_people_deck(tree)


def test_bumble_deck_not_connections():
    deck = _load("bumble_deck.xml")
    assert bumble_on_people_deck(deck)
    assert not bumble_on_connections(deck)
    assert _deck_visible("bumble", deck)


def test_yubo_chat_list_and_nav_by_content_desc():
    deck = _load("yubo_deck.xml")
    assert yubo_on_deck(deck)
    assert not yubo_on_chat_list(deck)
    act = _open_chats_tab_action("yubo", deck, [], "bulk_message_heuristic")
    assert act and act["action"] == "tap"
    assert (act["x"], act["y"]) == (343, 2180)
    # Must come from Chat content-desc, not a hard-coded invent
    assert act.get("fastpath_step") == "bulk_open_chats"

    chats = _load("yubo_chat_list.xml")
    assert yubo_on_chat_list(chats)
    assert _chat_list_screen_verified("yubo", chats)


def test_yubo_open_chats_refuses_xy_when_tab_missing():
    bare = """
    <hierarchy packages="co.yellw.yellowapp"><w p="co.yellw.yellowapp">
     <n t="Sam" xy="200,400" b="42,360,360,440"/>
    </w></hierarchy>
    """
    assert _open_chats_tab_action("yubo", bare, [], "bulk_message_heuristic") is None


def test_badoo_connections_tab_signal():
    tree = _load("badoo_connections_tab_only.xml")
    assert badoo_on_connections(tree)
    assert _chat_list_screen_verified("badoo", tree)
    assert not badoo_on_encounters(tree)


def test_badoo_encounters_vote_ids():
    enc = _load("badoo_encounters.xml")
    assert badoo_on_encounters(enc)
    assert _deck_visible("badoo", enc)
    assert not badoo_on_connections(enc)


def test_chat_list_settle_wait_after_tab():
    # Still on deck after tab history → settle once
    deck = _load("bumble_deck.xml")
    st: dict = {}
    act = plan_bulk_message(
        'reply "hey" to 2 existing chats on bumble',
        deck,
        [
            "Opened Bumble — launch",
            "Tapped (972,2197) — Open chats/messages tab (bulk_message_heuristic)",
        ],
        state=st,
        package="com.bumble.app",
        dry_run=True,
    )
    assert act and act["action"] == "wait"
    assert act.get("seconds") == DETECTOR_SETTLE_S
    assert act.get("fastpath_step") == "bulk_settle_chats"
    assert st["bulk_message"].get("_chats_settle_done") is True


# --- Deck detectors ---


def test_hily_finder_like_ids():
    tree = _load("hily_finder_like_only.xml")
    assert hily_on_finder(tree)
    assert _deck_visible("hily", tree)


def test_deck_settle_wait():
    # After open_deck, still no like buttons → settle once
    tree = """
    <hierarchy packages="com.hily.app"><w p="com.hily.app">
     <n i="bottomNavTab_1" d="Finder" c="1" xy="142,2190"/>
     <n i="bottomNavTab_2" d="Chats" c="1" xy="341,2190"/>
    </w></hierarchy>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "hily auto-swipe 2 profiles",
        tree,
        ["Opened Hily — launch", "Tapped — Open swipe deck (bulk_swipe_heuristic)"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act and act["action"] == "wait"
    assert act.get("fastpath_step") == "bulk_settle_deck"


# --- Composer after thread header ---


def test_hily_composer_ignores_list_message_node():
    trap = _load("hily_chats_message_trap.xml")
    assert compose_center_in_thread("hily", trap, "Evie") is None
    assert not thread_header_verified("hily", trap, "Evie")

    thread = _load("hily_thread.xml")
    assert thread_header_verified("hily", thread, "Evie")
    c = compose_center_in_thread("hily", thread, "Evie")
    assert c == (480, 2200)
    assert c[1] >= int(2400 * 0.70)


def test_plan_bulk_message_refuses_list_message_compose():
    trap = _load("hily_chats_message_trap.xml")
    st = {
        "bulk_message": {
            "done": 0,
            "target": 1,
            "current": "Evie",
            "done_names": [],
        }
    }
    act = plan_bulk_message(
        'reply "hey" to 1 existing chat on hily',
        trap,
        ["Opened Hily — launch", "Open chats tab", "Open Evie"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    # Still on list → should open row or fail compose, never tap (546,845)
    assert act
    if act["action"] == "tap":
        assert (act.get("x"), act.get("y")) != (546, 845)
        assert act.get("y", 0) != 845


# --- deck_card_name badge skip ---


def test_yubo_deck_card_name_skips_50_plus_badge():
    tree = _load("yubo_deck_badge.xml")
    assert yubo_deck_card_name(tree) == "Sam"
    assert deck_card_name("yubo", tree) == "Sam"
    assert yubo_deck_card_name(tree) != "50+"
