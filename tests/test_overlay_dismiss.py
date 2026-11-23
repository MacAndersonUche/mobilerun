"""Mac's rule: auto-dismiss non-target overlays; never fail; never payment taps."""

from __future__ import annotations

from pathlib import Path

from backend.overlay_dismiss import (
    active_window_package,
    detect_foreign_overlay,
    is_foreign_overlay_package,
    is_launcher_package,
    packages_in_tree,
    plan_dismiss_foreign_overlay,
    dismiss_foreign_overlays_before_plan,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_spay_detected_as_foreign_over_taimi():
    tree = _load("spay_overlay_wrong_fg.xml")
    assert is_foreign_overlay_package("com.samsung.android.spay", "com.takimi.android")
    overlay = detect_foreign_overlay(
        tree, "com.takimi.android", reported_package="com.samsung.android.spay"
    )
    assert overlay and "spay" in overlay.lower()
    assert active_window_package(tree).endswith("spay")
    pkgs = packages_in_tree(tree)
    assert any("spay" in p for p in pkgs)
    assert any("takimi" in p for p in pkgs)


def test_spay_dismiss_never_allow_payment():
    tree = _load("spay_payment_sheet.xml")
    act = plan_dismiss_foreign_overlay(
        tree, "com.samsung.android.spay", "com.bumble.app"
    )
    assert act.get("overlay_dismiss") is True
    assert act.get("action") in ("tap", "press_button")
    reason = (act.get("reason") or "").lower()
    assert "allow payment" not in reason
    if act.get("action") == "tap":
        assert (act.get("label") or "").lower() != "allow payment"
        # Prefer Not now over payment CTA
        assert (act.get("label") or "").lower() in (
            "not now",
            "close",
            "dismiss",
            "cancel",
            "no thanks",
            "maybe later",
        )


def test_edge_panel_dismiss_via_close():
    tree = _load("edge_panel_overlay.xml")
    overlay = detect_foreign_overlay(tree, "com.hily.app")
    assert overlay and "cocktail" in overlay.lower()
    act = plan_dismiss_foreign_overlay(
        overlay_package=overlay, ui_tree=tree, target_package="com.hily.app"
    )
    assert act["action"] == "tap"
    assert (act.get("label") or "").lower() == "close"


def test_target_package_not_foreign():
    assert not is_foreign_overlay_package("com.bumble.app", "com.bumble.app")
    assert not is_foreign_overlay_package("com.takimi.android", "com.takimi.android")


def test_dismiss_loop_clears_overlay_and_continues():
    """Runner re-fetches after Back; never fails when overlay clears."""
    spay = _load("spay_overlay_wrong_fg.xml")
    cleared = """
    <hierarchy packages="com.takimi.android">
    <w id="active" p="com.takimi.android" f="1">
     <n t="Alex" xy="300,1580"/>
     <n d="People" c="1" xy="540,2200"/>
    </w></hierarchy>
    """
    calls: list = []

    def execute_action(_device, act):
        calls.append(act)
        return act.get("reason") or "ok"

    state_box = {"n": 0}

    def fetch_tree():
        state_box["n"] += 1
        if state_box["n"] == 1:
            return {"tree": cleared, "package": "com.takimi.android", "empty": False}
        return {"tree": cleared, "package": "com.takimi.android", "empty": False}

    tree, info, hist = dismiss_foreign_overlays_before_plan(
        device_id="dev1",
        call_device=None,
        execute_action=execute_action,
        fetch_tree=fetch_tree,
        ui_tree=spay,
        tree_info={"tree": spay, "package": "com.samsung.android.spay", "empty": True},
        target_package="com.takimi.android",
        history=[],
        state={},
        max_attempts=3,
    )
    assert calls, "expected at least one dismiss action"
    assert calls[0].get("overlay_dismiss") is True
    assert "spay" in (calls[0].get("overlay_package") or "").lower()
    assert info.get("empty") is False
    assert "takimi" in (info.get("package") or "").lower()
    assert any("Dismiss foreign overlay" in h or "overlay" in h.lower() for h in hist)
    # Target content present after clear
    assert "Alex" in tree


def test_no_overlay_noop():
    tree = """
    <hierarchy packages="com.bumble.app">
    <w id="active" p="com.bumble.app" f="1">
     <n t="Sam, 28" xy="300,1700"/>
    </w></hierarchy>
    """
    assert detect_foreign_overlay(tree, "com.bumble.app") is None
    tree2, info, hist = dismiss_foreign_overlays_before_plan(
        device_id="d",
        call_device=None,
        execute_action=lambda *a, **k: "x",
        fetch_tree=lambda: {"tree": tree, "package": "com.bumble.app", "empty": False},
        ui_tree=tree,
        tree_info={"tree": tree, "package": "com.bumble.app", "empty": False},
        target_package="com.bumble.app",
        history=["Opened Bumble"],
        state={},
    )
    assert hist == ["Opened Bumble"]
    assert "Sam" in tree2


def test_home_launcher_not_dismissed_as_overlay():
    """APK 540: jobs pressed Back on Samsung home — must never treat launcher as overlay."""
    assert is_launcher_package("com.sec.android.app.launcher")
    assert not is_foreign_overlay_package(
        "com.sec.android.app.launcher", "com.takimi.android"
    )
    tree = """
    <hierarchy packages="com.sec.android.app.launcher">
    <w id="active" p="com.sec.android.app.launcher" f="1">
     <n t="Taimi" c="1" xy="200,900"/>
    </w></hierarchy>
    """
    assert (
        detect_foreign_overlay(
            tree, "com.takimi.android", reported_package="com.sec.android.app.launcher"
        )
        is None
    )
    calls = []

    def execute_action(_device, act):
        calls.append(act)
        return "x"

    dismiss_foreign_overlays_before_plan(
        device_id="d",
        call_device=None,
        execute_action=execute_action,
        fetch_tree=lambda: {
            "tree": tree,
            "package": "com.sec.android.app.launcher",
            "empty": False,
        },
        ui_tree=tree,
        tree_info={
            "tree": tree,
            "package": "com.sec.android.app.launcher",
            "empty": False,
        },
        target_package="com.takimi.android",
        history=[],
        state={},
    )
    assert calls == []
