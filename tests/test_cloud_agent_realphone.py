"""Unit tests for real-phone agent guards (tree normalize, open_app, swipe stop)."""

from backend.cloud_agent import (
    MAX_SWIPE_LOOPS,
    _count_recent_open_apps,
    _count_recent_swipes,
    _history_shows_app_opened,
    _normalize_tree_payload,
    _trivial_open_app_target,
)


def test_normalize_tree_string():
    fat = '<hierarchy nodes="3">' + ("x" * 100) + "</hierarchy>"
    info = _normalize_tree_payload(fat)
    assert info["empty"] is False
    assert info["chars"] > 80
    assert "hierarchy" in info["tree"]


def test_normalize_tree_empty_flag():
    info = _normalize_tree_payload('<hierarchy windows="0" nodes="0" empty="true"/>')
    assert info["empty"] is True


def test_normalize_tree_dict_payload():
    tree = "<hierarchy>" + ('<node text="Hi"/>' * 20) + "</hierarchy>"
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


def test_history_shows_app_opened_variants():
    assert _history_shows_app_opened(
        "Opened Settings[com.android.settings] — goal", "Settings"
    )
    assert _history_shows_app_opened(
        "step verify open_ok package=com.whatsapp", "WhatsApp"
    )
    assert _history_shows_app_opened("open_app(whatsapp) — launch", "WhatsApp")
    assert not _history_shows_app_opened("Swiped — hunting icon", "WhatsApp")


def test_recent_open_app_counter():
    hist = [
        "Opened WhatsApp[com.whatsapp] — launch",
        "Opened WhatsApp[com.whatsapp] — again",
    ]
    assert _count_recent_open_apps(hist) == 2
    assert _count_recent_open_apps(["Opened X", "Typed hi"]) == 0


def test_device_ws_freshness(monkeypatch):
    import backend.storage as storage

    now = 1_700_000_000

    class _T:
        pass

    def fake_conns(device_id):
        return [
            {
                "connection_id": "old",
                "device_id": device_id,
                "role": "device",
                "authed": True,
                "connected_at": now - 500,
            },
            {
                "connection_id": "pend",
                "device_id": f"pending_abc",
                "role": "device",
                "authed": False,
                "connected_at": now,
            },
        ]

    monkeypatch.setattr(storage, "get_device_connections", fake_conns)
    monkeypatch.setattr(storage.time, "time", lambda: now)
    assert storage.device_is_ws_connected("android_x") is False

    def fresh(device_id):
        return [
            {
                "connection_id": "live",
                "device_id": device_id,
                "role": "device",
                "authed": True,
                "connected_at": now - 10,
            }
        ]

    monkeypatch.setattr(storage, "get_device_connections", fresh)
    assert storage.device_is_ws_connected("android_x") is True
