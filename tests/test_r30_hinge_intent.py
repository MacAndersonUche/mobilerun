"""r30: Hinge card names must come from the profile card; reply via intent."""

from __future__ import annotations

from pathlib import Path

from backend.dm_heuristics import (
    DM_APP_PROFILES,
    hinge_composer_visible,
    hinge_deck_card_name,
    hinge_find_top_match_row,
    hinge_in_foreground,
    hinge_on_thread,
    is_launcher_home_label,
)
from backend.bulk_bench_heuristics import (
    _card_name_is_real_profile,
    plan_bulk_message,
    plan_hinge_reply_step,
)
from backend.cloud_agent import _visible_dry_swipe_card_name
from backend.universal_open import plan_universal_open

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


HINGE_LIKE = "like 5 profiles on Hinge"
HINGE_REPLY = 'reply "hey how are you" to 2 existing chats on Hinge'


def test_jobs_is_not_a_real_profile_name():
    assert is_launcher_home_label("Jobs")
    assert is_launcher_home_label("Jobs, Folder")
    assert is_launcher_home_label("Online Shopping")
    assert not _card_name_is_real_profile("Jobs")
    assert _card_name_is_real_profile("Da")


def test_hinge_deck_name_ignores_launcher_jobs_folder():
    tree = _load("hinge_launcher_jobs.xml")
    assert hinge_deck_card_name(tree) is None
    assert not hinge_in_foreground(tree)
    name = _visible_dry_swipe_card_name(
        HINGE_LIKE,
        tree,
        state={"bulk_swipe": {"last_name": "Jobs"}, "current_profile_name": "Jobs"},
    )
    assert name is None


def test_hinge_deck_name_reads_da_from_profile_card():
    tree = _load("hinge_discover_da.xml")
    assert hinge_deck_card_name(tree) == "Da"
    name = _visible_dry_swipe_card_name(HINGE_LIKE, tree, state={})
    assert name == "Da"


def test_mixed_launcher_and_empty_hinge_is_not_jobs():
    # Active launcher window plus an empty Hinge window must not yield Jobs.
    tree = (
        _load("hinge_launcher_jobs.xml").replace("</hierarchy>", "")
        + '  <w p="co.hinge.app" a="0" f="0"></w>\n</hierarchy>\n'
    )
    assert hinge_deck_card_name(tree) is None
    assert _visible_dry_swipe_card_name(HINGE_LIKE, tree, state={}) is None


def test_universal_open_hinge_never_uses_drawer_search():
    st = {"open_stage": "home_drawer_search"}
    act = plan_universal_open(
        "co.hinge.app",
        instruction="Open Hinge",
        state=st,
        fg_package="com.sec.android.app.launcher",
        reason_prefix="Stuck reopen",
    )
    assert act["open_mode"] != "home_drawer_search"
    assert act["open_mode"] != "drawer_scroll_icon"
    assert act["open_mode"] in ("launch_intent", "reopen_intent")
    assert act.get("app") == "Hinge"


def test_hinge_profile_has_launch_activity_and_top_chat():
    p = DM_APP_PROFILES["hinge"]
    assert p["launch_activity"] == "co.hinge.app/.ui.AppActivity"
    assert p["package"] == "co.hinge.app"
    assert p["top_chat_xy"] == (540, 480)
    assert p["inbox_tab_xy"] == (754, 2195)


def test_empty_tree_reply_opens_matches_not_drawer():
    tree = _load("hinge_empty_tree.xml")
    act = plan_bulk_message(
        HINGE_REPLY,
        tree,
        history=["Opened Hinge — launch_intent"],
        package="co.hinge.app",
        dry_run=True,
        state={},
    )
    assert act is not None
    assert act.get("dry_run_verified") is not True
    reason = str(act.get("reason") or "").lower()
    assert "drawer" not in reason
    assert "search" not in reason
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (754, 2195)
    assert "matches" in reason


def test_after_matches_reply_taps_top_chat():
    tree = _load("hinge_empty_tree.xml")
    act = plan_hinge_reply_step(
        tree,
        history=["Opened Hinge — launch_intent", "Open Hinge Matches tab (nav xy)"],
        package="co.hinge.app",
        dry_run=True,
        message="hey how are you",
        state={},
    )
    assert act is not None
    assert act.get("dry_run_verified") is not True
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == (540, 480)


def test_matches_list_taps_first_your_turn_row():
    tree = _load("hinge_matches_your_turn.xml")
    assert hinge_find_top_match_row(tree) == (300, 420)  # Sam
    act = plan_hinge_reply_step(
        tree,
        history=["Opened Hinge — launch_intent", "hinge_open_matches"],
        package="co.hinge.app",
        dry_run=True,
        message="hey how are you",
        state={},
    )
    assert act is not None
    assert act.get("dry_run_verified") is not True
    assert (act.get("x"), act.get("y")) == (300, 420)


def test_empty_tree_never_sets_dry_run_verified():
    tree = _load("hinge_empty_tree.xml")
    act = plan_bulk_message(
        HINGE_REPLY,
        tree,
        history=[
            "Opened Hinge — launch_intent",
            "Open Hinge Matches tab",
            "Open Hinge top match chat (row xy)",
        ],
        package="co.hinge.app",
        dry_run=True,
        state={},
    )
    assert act is not None
    assert act.get("dry_run_verified") is not True
    assert act.get("needs_vision") is True


def test_thread_composer_sets_dry_run_verified():
    tree = _load("hinge_thread_composer.xml")
    assert hinge_on_thread(tree)
    assert hinge_composer_visible(tree)
    act = plan_bulk_message(
        HINGE_REPLY,
        tree,
        history=["Opened Hinge — launch_intent", "hinge_tap_top_chat"],
        package="co.hinge.app",
        dry_run=True,
        state={"bulk_message": {"done": 0, "target": 2, "current": "Rika"}},
    )
    assert act is not None
    assert act.get("dry_run_verified") is True
    assert "composer verified" in str(act.get("reason") or "").lower()
    assert "rika" in str(act.get("reason") or "").lower()
    assert "never typed" in str(act.get("reason") or "").lower()


def test_vision_caption_can_verify_composer_when_tree_empty():
    tree = _load("hinge_empty_tree.xml")
    assert not hinge_composer_visible(tree)
    assert hinge_composer_visible(
        tree, vision_hint="Hinge thread, composer visible at the bottom"
    )
    act = plan_hinge_reply_step(
        tree,
        history=["hinge_tap_top_chat"],
        package="co.hinge.app",
        dry_run=True,
        message="hey how are you",
        state={"vision_caption": "composer visible in the thread"},
        bulk={"current": "Rika"},
    )
    assert act is not None
    assert act.get("dry_run_verified") is True


def test_launcher_tree_reply_launches_via_intent():
    tree = _load("hinge_launcher_jobs.xml")
    act = plan_bulk_message(
        HINGE_REPLY,
        tree,
        history=[],
        package="com.sec.android.app.launcher",
        dry_run=True,
        state={},
    )
    assert act is not None
    assert act.get("action") == "open_app"
    assert act.get("open_mode") == "launch_intent"
    assert act.get("package") == "co.hinge.app"
    assert "drawer" not in str(act.get("reason") or "").lower()
    assert act.get("dry_run_verified") is not True


def test_dry_guard_blocks_tap_the_like_button_reason():
    from backend.cloud_agent import apply_dry_run_send_guard

    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True,
        action={
            "action": "tap",
            "x": 96,
            "y": 806,
            "reason": "tap the like button on the profile to like it",
        },
        kind="tap",
        reason="tap the like button on the profile to like it",
    )
    assert kind == "done"
    assert "like/pass" in reason.lower() or "skipped" in reason.lower()
    assert out.get("dry_run_verified") is not True
    assert out.get("action") == "done"


def test_hinge_name_from_vision_reply():
    from backend.cloud_agent import hinge_name_from_vision_reply

    assert hinge_name_from_vision_reply("Da") == "Da"
    assert hinge_name_from_vision_reply("Da, 23") == "Da"
    assert hinge_name_from_vision_reply("NONE") is None
    assert hinge_name_from_vision_reply("Jobs") is None
    assert hinge_name_from_vision_reply("Social") is None
