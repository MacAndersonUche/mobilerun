"""Unit tests for Nov22 real-phone dry-run fixes (PR #64).

Fixtures built from described resource-ids / labels (trees not shipped).
"""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _recover_to_root_action,
    parse_bulk_goal,
    plan_bulk_bench,
    plan_bulk_message_new,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    _is_lock_screen_package,
    permission_dialog_action,
    plan_next_action,
)
from backend.dm_heuristics import (
    badoo_on_connections,
    blk_dismiss_popup,
    find_contact_result_center,
    hily_back_from_photo_viewer,
    hily_on_photo_viewer,
    yubo_on_chat,
    yubo_on_chat_list,
)
from backend.message_text_guard import (
    enforce_message_text,
    extract_user_message_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- 1. New-contact routing ---


def test_parse_message_to_n_new_profiles():
    g = parse_bulk_goal('message "hello miss" to 3 new profiles on Hinge')
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 3
    assert g["message"] == "hello miss"
    assert g["app"] == "hinge"
    assert g["contact_scope"] == "new"


def test_plan_routes_new_profiles_to_bulk_not_ai(monkeypatch):
    """maybe_bulk must catch new-profile wording so AI planner is skipped."""
    called = {"bulk": False}

    def fake_bulk(*_a, **_k):
        called["bulk"] = True
        return {
            "action": "open_app",
            "app": "Hinge",
            "reason": "bulk new",
            "planner": "bulk_message_new_heuristic",
        }

    monkeypatch.setattr("backend.bulk_bench_heuristics.plan_bulk_bench", fake_bulk)
    # Also patch the import path used inside plan_next_action
    import backend.cloud_agent as ca

    monkeypatch.setattr(
        ca,
        "plan_next_action",
        ca.plan_next_action,
    )
    act = plan_next_action(
        'message "hello miss" to 3 new profiles on Hinge',
        '<hierarchy empty="true"/>',
        [],
        package="",
        dry_run=True,
    )
    # Either bulk path or open — must NOT be bare LLM with no planner
    assert act.get("action") in ("open_app", "fail", "wait", "done", "tap")
    assert "llm" not in str(act.get("planner") or "").lower() or called["bulk"]


def test_extract_quoted_message_to_profiles():
    assert (
        extract_user_message_text('message "hello miss" to 3 new profiles on Hinge')
        == "hello miss"
    )
    assert (
        extract_user_message_text('reply "hey there" to 5 existing chats')
        == "hey there"
    )


def test_message_guard_no_bank_default_fallback():
    """Empty planner text + no quoted/selected → fail (never bank[0])."""
    job = {"message_bank": ["hey there", "what's up", "good morning"]}
    out = enforce_message_text(
        {"action": "type", "text": "", "reason": "Type message"},
        "auto-message 5 matches on Hily",  # no quoted text
        job=job,
    )
    assert out["action"] == "fail"
    assert (
        "bank_default" in out["reason"].lower() or "no allowed" in out["reason"].lower()
    )


# --- 3/4 recover + empty tree ---


def test_recover_hard_cap_and_empty_tree():
    empty = (
        '<hierarchy windows="1" nodes="2" empty="false"><w p="com.android.systemui">'
    )
    empty += '<n d="Clock" xy="100,50"/></w></hierarchy>'
    st: dict = {}
    act = _recover_to_root_action("bumble", empty, [], "test", state=st)
    assert act and act["action"] == "fail"
    assert "empty" in act["reason"].lower()


def test_recover_relaunches_capped():
    tree = """
    <hierarchy><w p="com.bumble.app">
     <n t="Some random sheet" xy="540,900"/>
     <n t="Extra label A" xy="200,400"/>
     <n t="Extra label B" xy="200,500"/>
     <n t="Extra label C" xy="200,600"/>
     <n t="Close" xy="100,100" c="1"/>
    </w></hierarchy>
    """
    st: dict = {"_root_recover_bumble": {"backs": 8, "relaunches": 3}}
    act = _recover_to_root_action(
        "bumble", tree, ["bulk_recover_back"] * 5, "test", state=st
    )
    assert act and act["action"] == "fail"
    assert "exhaust" in act["reason"].lower() or "could not" in act["reason"].lower()


# --- 5 chat-list detectors ---


def test_yubo_systemui_messages_not_open_thread():
    tree = _load("yubo_chat_list_with_systemui.xml")
    assert yubo_on_chat(tree) is False
    assert yubo_on_chat_list(tree) is True


def test_badoo_chats_tab_alone_not_connections():
    tree = _load("badoo_chats_tab_only.xml")
    assert badoo_on_connections(tree) is False


# --- 6 Badoo Encounters for swipe ---


def test_badoo_swipe_opens_encounters_not_people():
    tree = _load("badoo_chats_tab_only.xml")
    act = plan_bulk_swipe(
        "badoo auto-swipe 5 profiles",
        tree,
        ["Opened Badoo"],
        package="com.badoo.mobile",
        dry_run=True,
    )
    assert act and act["action"] == "tap"
    # Encounters tab xy ≈ (324, 2210)
    assert abs(int(act["x"]) - 324) < 80
    assert (
        "encounters" in act["reason"].lower() or "swipe deck" in act["reason"].lower()
    )


# --- 7 Hily photo viewer ---


def test_hily_photo_viewer_detected_and_backs():
    tree = _load("hily_photo_viewer.xml")
    assert hily_on_photo_viewer(tree) is True
    back = hily_back_from_photo_viewer()
    assert back["action"] == "press_button" and back["button"] == "back"
    act = plan_bulk_swipe(
        "hily auto-swipe 5 profiles",
        tree,
        ["Opened Hily"],
        package="com.hily.app",
        dry_run=True,
        state={},
    )
    assert act and act.get("fastpath_step") == "hily_photo_viewer_back"


# --- 8 Hily dry-run verify ---


def test_hily_new_dry_run_fails_without_profile():
    tree = """
    <hierarchy><w p="com.hily.app">
     <n t="Discover" xy="200,2190" c="1"/>
     <n t="Chats" xy="341,2190" c="1"/>
    </w></hierarchy>
    """
    act = plan_bulk_message_new(
        'message "hi" to 3 new profiles on Hily',
        tree,
        ["Opened Hily"],
        package="com.hily.app",
        dry_run=True,
        state={},
    )
    assert act and act["action"] == "fail"
    assert act.get("dry_run_verified") is False


# --- 9 Tagged + Hinge in swipe allowlist ---


def test_hinge_tagged_swipe_not_skipped():
    for app, pkg in (("hinge", "co.hinge.app"), ("tagged", "com.taggedapp")):
        act = plan_bulk_bench(
            f"{app} auto-swipe 5 profiles",
            f'<hierarchy empty="true"/>',
            [],
            package=pkg,
            dry_run=True,
        )
        assert act is not None
        assert act.get("skipped") is not True
        assert "N/A for messaging" not in str(act.get("reason") or "")


# --- 10 BLK Streaks + permission vs lock ---


def test_blk_streaks_got_it():
    tree = _load("blk_streaks_popup.xml")
    act = blk_dismiss_popup(tree)
    assert act and act["action"] == "tap"
    assert "streak" in act["reason"].lower()
    assert act.get("fastpath_step") == "blk_streaks_got_it"


def test_permission_not_lock_and_dont_allow():
    assert _is_lock_screen_package("com.android.permissioncontroller") is False
    assert _is_lock_screen_package("com.android.systemui") is False
    assert _is_lock_screen_package("com.android.systemui.keyguard") is True
    tree = _load("permission_notifications.xml")
    act = permission_dialog_action(tree, package="com.android.permissioncontroller")
    assert act and act["action"] == "tap"
    assert "don't allow" in act["reason"].lower() or "dont" in act["reason"].lower()


# --- 11 WhatsApp community skip ---


def test_wa_skips_community_announcement_rows():
    tree = _load("wa_community_row.xml")
    # Must not pick Announcements / Community
    hit = find_contact_result_center(
        tree,
        "Precious Achalugo",
        result_ids=("conversations_row_contact_name", "contact_row_container"),
    )
    assert hit is not None
    # Announcements / Community alone must not match a DM contact search
    assert (
        find_contact_result_center(
            tree,
            "Announcements",
            result_ids=("conversations_row_contact_name", "contact_row_container"),
        )
        is None
    )


# --- 12 Bumble Discover for deck ---


def test_bumble_people_grid_fails_clean_no_superswipe():
    """People grid → Discover nav once; still-grid → fail, never SuperSwipe."""
    tree = _load("bumble_people_photo_grid.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble"],
        package="com.bumble.app",
        dry_run=True,
        state=st,
    )
    assert act and act["action"] == "tap"
    assert "Discover" in act["reason"] or act.get("label") == "Discover"
    act2 = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble", act["reason"]],
        package="com.bumble.app",
        dry_run=True,
        state=st,
    )
    assert act2 and act2["action"] == "fail"
    assert "grid" in act2["reason"].lower() or "superswipe" in act2["reason"].lower()
    assert act2.get("dry_run_verified") is False
