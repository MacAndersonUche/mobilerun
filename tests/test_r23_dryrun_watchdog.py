"""r23 failure signatures: no dry-run swipe/like/pass, 90s wall, empty inbox."""

from backend.bulk_bench_heuristics import (
    _app_tree_empty,
    _inbox_nothing_to_reply,
    plan_bulk_message,
    plan_bulk_message_new,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    NO_PROGRESS_TIMEOUT_S,
    apply_dry_run_send_guard,
)
from backend.step_worker import (
    JOB_WALL_S,
    STEP_WALL_S,
    enforce_job_wall_clock,
)


def _bumble_deck(name: str = "Alex") -> str:
    return (
        f'<hierarchy packages="com.bumble.app">'
        f'<w p="com.bumble.app" f="1">'
        f'<n t="{name}, 28" d="{name}\'s main photo" xy="540,1600" '
        f'b="100,1500,900,1700"/>'
        f'<n t="People" xy="540,400"/>'
        f"</w></hierarchy>"
    )


def test_dry_run_never_emits_horizontal_swipe_or_like_pass():
    """r23 CRITICAL: dry advance must not pass real profiles."""
    st: dict = {"bulk_swipe": {"done": 0, "target": 5}}
    act = plan_bulk_swipe(
        "swipe right on 5 profiles on Yubo",
        _bumble_deck("Cerys").replace("bumble", "yellw").replace(
            "com.bumble.app", "co.yellw.yellowapp"
        ),
        ["Opened Yubo[open_ok]"],
        package="co.yellw.yellowapp",
        dry_run=True,
        state=st,
    )
    # May open deck / wait / done / vertical scroll — never horizontal pass
    assert act is not None
    assert act.get("_dry_run_advance") is not True
    if act.get("action") == "swipe":
        assert act.get("_dry_run_vertical_scroll") is True
        assert abs(int(act["x2"]) - int(act["x1"])) < abs(
            int(act["y2"]) - int(act["y1"])
        )
    if act.get("action") == "tap":
        reason = (act.get("reason") or "").lower()
        assert "pass" not in reason or "would" in reason
        assert "like" not in reason or "would" in reason or "no like" in reason


def test_dry_run_guard_blocks_horizontal_pass_swipe():
    action = {
        "action": "swipe",
        "x1": 850,
        "y1": 1000,
        "x2": 30,
        "y2": 1050,
        "_dry_run_advance": True,
        "reason": "advance via pass",
    }
    kind, reason, out = apply_dry_run_send_guard(
        dry_run=True, action=action, kind="swipe", reason=action["reason"]
    )
    assert kind == "done"
    assert "would swipe" in reason.lower() or "skipped" in reason.lower()
    assert out.get("action") == "done"


def test_dry_run_identifies_card_without_mutating():
    deck = _bumble_deck("Liv")
    st: dict = {"bulk_swipe": {"done": 0, "target": 5, "_dry_vscroll_done": True}}
    act = plan_bulk_swipe(
        "bumble auto-swipe 5 profiles",
        deck,
        ["Opened Bumble — launch"],
        package="com.bumble.app",
        dry_run=True,
        state=st,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    reason = (act.get("reason") or "").lower()
    assert "liv" in reason
    assert "would like/pass 5" in reason
    assert "no swipe/like/pass" in reason or "no like" in reason


def test_blk_your_turn_zero_is_nothing_to_reply():
    tree = (
        '<hierarchy nodes="23" empty="false">'
        '<w p="com.affinityapps.blk" f="1">'
        '<n t="Matches" xy="540,200"/>'
        '<n t="Your turn (0)" xy="200,400"/>'
        '<n t="Their turn (2)" xy="200,500"/>'
        '<n t="Hidden (1)" xy="200,600"/>'
        '<n t="Discover" xy="135,2170" c="1"/>'
        '<n t="Matches" xy="675,2170" c="1"/>'
        "</w></hierarchy>"
    )
    assert not _app_tree_empty(tree, "blk")
    assert _inbox_nothing_to_reply("blk", tree)
    act = plan_bulk_message(
        'reply to 5 chats on BLK with "hey"',
        tree,
        ["Opened BLK", "tap — Open Matches"],
        package="com.affinityapps.blk",
        dry_run=True,
        state={"bulk_message": {"done": 0, "target": 5, "chat_list_verified": True}},
    )
    assert act and act.get("action") == "done"
    assert act.get("stopped_reason") == "nothing_to_reply"
    assert "nothing to reply" in (act.get("reason") or "").lower()


def test_app_tree_empty_only_under_three_useful_nodes():
    rich = (
        '<hierarchy><w>'
        '<n t="Your turn (0)" xy="200,400"/>'
        '<n t="Their turn (2)" xy="200,500"/>'
        '<n t="Hidden (1)" xy="200,600"/>'
        '<n t="Matches" xy="540,200"/>'
        "</w></hierarchy>"
    )
    assert _app_tree_empty(rich, "blk") is False
    empty = '<hierarchy empty="true"><w/></hierarchy>'
    assert _app_tree_empty(empty, "blk") is True


def test_step_worker_wall_constants():
    assert NO_PROGRESS_TIMEOUT_S <= 120
    assert STEP_WALL_S <= 120
    assert JOB_WALL_S <= 300


def test_enforce_job_wall_clock_no_progress():
    import time

    now = int(time.time())
    job = {
        "job_id": "t_wall",
        "status": "running",
        "created_at": now - 200,
        "state": {"steps": 3, "last_ui_progress_at": now - 200},
    }
    failed = enforce_job_wall_clock(job)
    assert failed is not None
    assert failed["status"] == "failed"
    assert "progress" in (failed.get("error") or "").lower() or "wall" in (
        failed.get("error") or ""
    ).lower()


def test_tagged_reply_opens_messages_not_meet_me():
    tree = (
        '<hierarchy><w p="com.taggedapp" f="1">'
        '<n t="Meet Me" c="1" xy="108,2200"/>'
        '<n t="Messages" c="1" xy="756,2200"/>'
        '<n t="Live" c="1" xy="324,2200"/>'
        "</w></hierarchy>"
    )
    st = {"bulk_message": {"done": 0, "target": 5, "current": None}}
    act = plan_bulk_message(
        'reply to 5 chats on Tagged with "hey"',
        tree,
        ["Opened Tagged[open_ok]"],
        package="com.taggedapp",
        dry_run=True,
        state=st,
    )
    assert act is not None
    reason = (act.get("reason") or "").lower()
    # Must prefer Messages/inbox, not Meet Me deck
    if act.get("action") == "tap":
        assert "meet me" not in reason or "messages" in reason
        if "messages" in reason or act.get("label") == "Messages":
            assert int(act.get("x") or 0) >= 500


def test_hinge_dry_editable_sheet_is_success():
    tree = (
        '<hierarchy><w p="co.hinge.app" f="1">'
        '<n t="Send Like" c="1" xy="540,2000"/>'
        '<n e="1" t="" h="Add a comment" xy="540,1800" b="80,1750,1000,1850"/>'
        "</w></hierarchy>"
    )
    act = plan_bulk_message_new(
        'message "hi" to 3 new profiles on Hinge',
        tree,
        ["Opened Hinge", "tap — Focus Add a comment"],
        package="co.hinge.app",
        dry_run=True,
        state={},
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert "editable" in (act.get("reason") or "").lower() or "never typed" in (
        act.get("reason") or ""
    ).lower()
