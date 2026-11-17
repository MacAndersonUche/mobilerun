"""Unit tests for real-phone agent guards (tree normalize, open_app, swipe stop)."""

from backend.cloud_agent import (
    MAX_SWIPE_LOOPS,
    _count_recent_swipes,
    _normalize_tree_payload,
    _trivial_open_app_target,
)


def test_normalize_tree_string():
    fat = "<hierarchy nodes=\"3\">" + ("x" * 100) + "</hierarchy>"
    info = _normalize_tree_payload(fat)
    assert info["empty"] is False
    assert info["chars"] > 80
    assert "hierarchy" in info["tree"]


def test_normalize_tree_empty_flag():
    info = _normalize_tree_payload('<hierarchy windows="0" nodes="0" empty="true"/>')
    assert info["empty"] is True


def test_normalize_tree_dict_payload():
    tree = "<hierarchy>" + ("<node text=\"Hi\"/>" * 20) + "</hierarchy>"
    info = _normalize_tree_payload(
        {
            "tree": tree,
            "package": "com.android.settings",
            "empty": False,
            "chars": len(tree),
        }
    )
    assert info["package"] == "com.android.settings"
    assert info["empty"] is False
    assert "Hi" in info["tree"]


def test_trivial_open_app_targets():
    assert _trivial_open_app_target("open settings") == "settings"
    assert _trivial_open_app_target("Open WhatsApp") == "WhatsApp"
    assert _trivial_open_app_target("open chrome") == "chrome"
    assert _trivial_open_app_target("open Settings and go to Display") is None


def test_swipe_loop_counter():
    hist = ["tap(1,2)", "swipe(0,1->0,2)", "swipe(0,1->0,2)", "swipe(0,1->0,2)"]
    assert _count_recent_swipes(hist) == 3
    assert _count_recent_swipes(hist) >= MAX_SWIPE_LOOPS
    assert _count_recent_swipes(["swipe(1)", "tap(1,1)", "swipe(2)"]) == 1
