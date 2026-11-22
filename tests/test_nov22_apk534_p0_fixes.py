"""APK 532/534 P0/P1 fixes: prefer-not-filter hint, dry-run no-type, previews, Hily/Tagged."""

from __future__ import annotations

from backend.bulk_bench_heuristics import (
    _recover_to_root_action,
    _visible_chat_list_rows,
    plan_bulk_message,
)
from backend.cloud_agent import apply_dry_run_send_guard
from backend.dm_heuristics import (
    _looks_like_message_preview,
    hily_on_profile_sheet,
    tagged_dismiss_exit_dialog,
    tagged_exit_dialog_present,
    yubo_bottom_tab_center,
)
from backend.overlay_dismiss import dismiss_foreign_overlays_before_plan


def test_message_preview_not_chat_row_badoo_tagged():
    assert _looks_like_message_preview("Good and you")
    assert _looks_like_message_preview("Hola")
    assert _looks_like_message_preview("hey what's up")
    assert not _looks_like_message_preview("Sam")
    assert not _looks_like_message_preview("Ada Love")

    tree = """
    <hierarchy packages="com.badoo.mobile"><w p="com.badoo.mobile">
     <n t="Sam" i="com.badoo.mobile:id/profileInfo_name" c="1" xy="300,800"/>
     <n t="Good and you" i="com.badoo.mobile:id/connection_container" c="1" xy="300,860"/>
     <n t="Hola" i="clConversationContainer" c="1" xy="300,1000"/>
     <n t="Mia" i="com.badoo.mobile:id/profileInfo_name" c="1" xy="300,1200"/>
    </w></hierarchy>
    """
    rows = _visible_chat_list_rows(tree, "badoo")
    names = {r["name"] for r in rows}
    assert "Sam" in names
    assert "Mia" in names
    assert "Good and you" not in names
    assert "Hola" not in names


def test_dry_run_reply_never_types_into_thread():
    # Open thread + focused compose — dry-run must verify without typing
    tree = """
    <hierarchy packages="com.badoo.mobile"><w p="com.badoo.mobile">
     <n t="Sam" xy="200,120" c="1"/>
     <n t="Type a message" hint="Type a message" c="1" e="1" f="1"
        xy="400,2100" i="com.badoo.mobile:id/chat_message_box"/>
    </w></hierarchy>
    """
    st: dict = {
        "bulk_message": {
            "done": 0,
            "target": 1,
            "current": "Sam",
            "done_names": [],
            "typed": False,
            "cleared": False,
            "dry_verified": False,
        }
    }
    act = plan_bulk_message(
        'reply "hey there" to 1 existing chat on Badoo',
        tree,
        ["Opened Sam", "Focus compose for Sam (bulk_message)"],
        package="com.badoo.mobile",
        dry_run=True,
        state=st,
    )
    assert act is not None
    assert act.get("action") != "type"
    reason = (act.get("reason") or "").lower()
    assert "never typed" in reason or act.get("would_send_text") == "hey there"
    # Guard also blocks type
    kind, reason2, _out = apply_dry_run_send_guard(
        dry_run=True,
        action={"action": "type", "text": "hey there", "clear": True},
        kind="type",
        reason="Type bank",
    )
    assert kind == "done"
    assert "type" in reason2.lower()


def test_hily_chats_list_not_crush_sheet():
    tree = """
    <hierarchy packages="com.hily.app"><w p="com.hily.app">
     <n t="Paige" i="userNameField" xy="300,600" c="1"/>
     <n t="dialog row" i="dialogMessageItem" xy="300,650"/>
     <n t="Crush" i="ActionButton_CRUSH" xy="540,2200"/>
     <n t="Chats" xy="200,2250"/>
    </w></hierarchy>
    """
    assert hily_on_profile_sheet(tree) is False


def test_tagged_end_dialog_cancel():
    tree = """
    <hierarchy packages="com.taggedapp"><w p="com.taggedapp">
     <n t="End Tagged?" xy="540,1000"/>
     <n t="Cancel" c="1" xy="300,1400"/>
     <n t="End" c="1" xy="700,1400"/>
    </w></hierarchy>
    """
    assert tagged_exit_dialog_present(tree)
    act = tagged_dismiss_exit_dialog(tree)
    assert act and act.get("action") == "tap"
    assert (act.get("label") or "").lower() == "cancel"


def test_tagged_recover_avoids_repeat_back():
    tree = """
    <hierarchy packages="com.taggedapp"><w p="com.taggedapp">
     <n t="Something odd" xy="200,400"/>
    </w></hierarchy>
    """
    st = {"bulk_swipe": {"backs": 1, "relaunches": 0}}
    act = _recover_to_root_action(
        "tagged", tree, ["bulk_recover_back once"], "test", state=st
    )
    assert act is not None
    assert act.get("action") != "press_button" or act.get("button") != "back"
    assert "End Tagged" in (act.get("reason") or "") or act.get("needs_vision")


def test_yubo_bottom_tab_by_position_band():
    tree = """
    <hierarchy packages="co.yellw.yellowapp"><w p="co.yellw.yellowapp">
     <n t="Chat" xy="200,159"/>
     <n i="tab_slot" c="1" xy="140,2194"/>
     <n i="tab_slot2" c="1" xy="341,2194"/>
    </w></hierarchy>
    """
    deck = yubo_bottom_tab_center(tree, which="deck")
    chat = yubo_bottom_tab_center(tree, which="chat")
    assert deck and deck[0] == 140
    assert chat and chat[0] == 341


def test_overlay_dismiss_always_logs_check(caplog):
    import logging

    tree = """
    <hierarchy packages="com.bumble.app">
    <w id="active" p="com.bumble.app" f="1">
     <n t="Discover" xy="300,2100"/>
    </w></hierarchy>
    """
    calls = []

    def _exec(*_a, **_k):
        calls.append("exec")
        return "ok"

    def _fetch():
        return {"tree": tree, "package": "com.bumble.app", "empty": False}

    with caplog.at_level(logging.INFO, logger="mobilerun.overlay_dismiss"):
        dismiss_foreign_overlays_before_plan(
            device_id="d1",
            call_device=lambda *a, **k: {},
            execute_action=_exec,
            fetch_tree=_fetch,
            ui_tree=tree,
            tree_info={"package": "com.bumble.app", "empty": False},
            target_package="com.bumble.app",
            history=[],
            state={},
        )
    assert any("overlay_dismiss check" in r.message for r in caplog.records)
    assert calls == []  # no foreign overlay → no dismiss execute
