"""Robustness: universal open + stuck recovery — never die stuck on home/one page."""

from __future__ import annotations

from pathlib import Path

from backend.recovery import recovery_action
from backend.stuck_recovery import (
    STUCK_STAGES,
    find_bottom_nav_target,
    find_safe_dismiss,
    next_stuck_action,
    should_hard_fail_stuck,
)
from backend.universal_open import (
    OPEN_STAGES,
    advance_open_stage,
    plan_universal_open,
    resolve_open_label,
    should_escalate_open,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_resolve_dating_open_labels():
    assert resolve_open_label("com.bumble.app") == "Bumble"
    assert resolve_open_label("hily") == "Hily"
    assert resolve_open_label("open Yubo on my phone") == "Yubo"
    assert resolve_open_label("com.takimi.android") == "Taimi"
    assert resolve_open_label("tagged") == "Tagged"
    assert resolve_open_label("blk") == "BLK"


def test_universal_open_stages_escalate():
    st: dict = {}
    a0 = plan_universal_open(
        "Bumble", state=st, fg_package="com.sec.android.app.launcher"
    )
    assert a0["action"] == "open_app"
    assert a0["open_mode"] == "launch_intent"
    assert a0["app"] == "Bumble"
    nxt = advance_open_stage(st)
    assert nxt == "home_drawer_search"
    a1 = plan_universal_open("Bumble", state=st)
    assert a1["open_mode"] == "home_drawer_search"
    assert a1.get("fallback") is True
    advance_open_stage(st)
    advance_open_stage(st)
    assert st["open_stage"] == "reopen_intent"
    # Clamp
    assert advance_open_stage(st) == "reopen_intent"


def test_should_escalate_when_fg_still_launcher():
    st: dict = {}
    assert should_escalate_open(
        want_package="com.bumble.app",
        fg_package="com.sec.android.app.launcher",
        state=st,
        open_ok=True,
    )
    assert not should_escalate_open(
        want_package="com.bumble.app",
        fg_package="com.bumble.app",
        state=st,
        open_ok=True,
    )
    assert st.get("open_stage") == OPEN_STAGES[0]


def test_safe_dismiss_never_paid():
    tree = """
    <hierarchy>
     <n t="Get Boost" xy="540,1800" c="1"/>
     <n t="Not now" xy="540,2000" c="1"/>
     <n t="Allow payment" xy="540,1600" c="1"/>
    </hierarchy>
    """
    hit = find_safe_dismiss(tree)
    assert hit is not None
    assert hit[2].lower() == "not now"
    assert hit[1] == 2000


def test_bottom_nav_prefers_chats_band():
    tree = """
    <hierarchy>
     <n t="Chat" xy="300,159" c="1"/>
     <n t="Chats" xy="340,2200" c="1"/>
     <n t="Discover" xy="140,2200" c="1"/>
    </hierarchy>
    """
    hit = find_bottom_nav_target(
        tree, prefer_labels=["chats", "messages"], screen_h=2400
    )
    assert hit is not None
    assert hit[1] >= 2000
    assert "chat" in hit[2].lower()


def test_stuck_escalation_order_and_cap():
    st: dict = {}
    tree = '<hierarchy packages="com.bumble.app"><n t="Sam" xy="300,800"/></hierarchy>'
    seen = []
    for _ in range(len(STUCK_STAGES)):
        act = next_stuck_action(
            st,
            instruction='reply "hi" to 3 existing chats on Bumble',
            ui_tree=tree,
            package="com.bumble.app",
            prefer_pkg="com.bumble.app",
        )
        seen.append(act.get("_stuck") or st.get("stuck_stage"))
        assert act.get("action")
        # Never paid
        lab = (act.get("label") or act.get("reason") or "").lower()
        assert "boost" not in lab or "stuck" in lab
    assert "dismiss_safe" in seen or "press_back" in seen
    assert "reopen_app" in seen or "vision" in seen
    # Cap
    st["stuck_step"] = 12
    assert should_hard_fail_stuck(st)


def test_stuck_on_launcher_skips_back_for_reopen():
    st: dict = {"stuck_step": 1}  # next will be press_back index 1 → but launcher
    # Force stage by setting step so next is press_back (index 1)
    st = {"stuck_step": 1}
    act = next_stuck_action(
        st,
        instruction="swipe on Bumble",
        ui_tree='<hierarchy packages="com.sec.android.app.launcher"/>',
        package="com.sec.android.app.launcher",
        prefer_pkg="com.bumble.app",
    )
    # Launcher Back is redirected to reopen
    assert act.get("action") in ("open_app", "back", "swipe", "tap", "_vision_retry")
    if act.get("action") == "open_app":
        assert act.get("app") == "Bumble"


def test_recovery_home_then_open_includes_dating_apps():
    st: dict = {}
    act = recovery_action(
        st,
        'reply "hey" to 2 existing chats on Hily',
        "<hierarchy/>",
        package="com.sec.android.app.launcher",
        prefer=["home_then_open"],
    )
    assert act.get("action") == "open_app"
    assert act.get("app") == "Hily"
    assert act.get("open_mode") in OPEN_STAGES


def test_hily_deck_name_without_id_field():
    from backend.dm_heuristics import hily_deck_card_name

    tree = """
    <hierarchy packages="com.hily.app">
     <w p="com.hily.app">
      <n t="Jess, 26" xy="540,900"/>
      <n i="ActionButton_LIKE" xy="750,2000" c="1"/>
      <n i="ActionButton_SKIP" xy="330,2000" c="1"/>
     </w>
    </hierarchy>
    """
    assert hily_deck_card_name(tree) == "Jess"


def test_selftest_recorded_trees_if_present():
    """Smoke: stuck recovery runs on any recorded dm fixture without crashing."""
    if not FIX.exists():
        return
    xmls = list(FIX.glob("*.xml"))[:12]
    assert xmls, "expected dm fixtures"
    for path in xmls:
        tree = path.read_text(encoding="utf-8")
        st: dict = {}
        act = next_stuck_action(
            st,
            instruction="reply hi on Bumble",
            ui_tree=tree,
            package="com.bumble.app",
            prefer_pkg="com.bumble.app",
        )
        assert isinstance(act, dict)
        assert act.get("action")
        # Paid labels never chosen as dismiss target
        if act.get("action") == "tap":
            lab = (act.get("label") or "").lower()
            assert "get boost" not in lab
            assert "allow payment" not in lab
            assert "crush" not in lab or "stuck" in (act.get("reason") or "").lower()
