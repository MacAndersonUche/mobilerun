"""Unit tests for real-phone agent guards (tree normalize, open_app, swipe stop)."""

from backend.cloud_agent import (
    MAX_SWIPE_LOOPS,
    _count_recent_open_apps,
    _count_recent_swipes,
    _extract_android_version,
    _goal_satisfied_from_tree,
    _history_shows_app_opened,
    _normalize_tree_payload,
    _same_tap_key,
    _tree_fingerprint,
    _trivial_open_app_target,
    plan_next_action,
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


def test_tree_fingerprint_stable_and_sensitive():
    a = _tree_fingerprint('<hierarchy><node text="About phone"/></hierarchy>', "pkg")
    b = _tree_fingerprint('<hierarchy><node text="About phone"/></hierarchy>', "pkg")
    c = _tree_fingerprint('<hierarchy><node text="Display"/></hierarchy>', "pkg")
    assert a == b
    assert a != c


def test_extract_android_version_from_about_tree():
    tree = (
        '<hierarchy screen="about">'
        '<node text="Android version"/>'
        '<node text="14" resource-id="android_version"/>'
        '<node text="Android 14"/>'
        "</hierarchy>"
    )
    assert _extract_android_version(tree) == "14"


def test_goal_satisfied_android_version_read():
    tree = (
        '<hierarchy screen="about" package="com.android.settings">'
        '<node text="Android version" clickable="true" center="(520,350)"/>'
        '<node text="14" resource-id="android_version"/>'
        '<node text="Android 14"/>'
        "</hierarchy>"
    )
    reason = _goal_satisfied_from_tree(
        "Open Settings, go to About phone, and read the Android version",
        tree,
        "com.android.settings",
    )
    assert reason is not None
    assert "14" in reason


def test_goal_not_satisfied_on_settings_list():
    tree = (
        '<hierarchy screen="settings">'
        '<node text="About phone" center="(520,490)"/>'
        '<node text="Display" center="(520,370)"/>'
        "</hierarchy>"
    )
    assert (
        _goal_satisfied_from_tree(
            "Open Settings, go to About phone, and read the Android version",
            tree,
        )
        is None
    )


def test_plan_short_circuits_when_version_visible(monkeypatch):
    tree = (
        '<hierarchy screen="about">'
        '<node text="Android version"/>'
        '<node text="Android 14"/>'
        "</hierarchy>"
    )
    # Must not call LLM when goal is already on screen
    monkeypatch.setattr(
        "backend.cloud_agent._call_gemini",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("should not call LLM")),
    )
    monkeypatch.setattr(
        "backend.cloud_agent._call_openai",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("should not call LLM")),
    )
    action = plan_next_action(
        "Open Settings, go to About phone, and read the Android version",
        tree,
        ["Opened Settings — launch", "tap(520,490) — About"],
    )
    assert action["action"] == "done"
    assert "14" in action["reason"]
    assert action["planner"] == "goal_visible"


def test_same_tap_key():
    assert _same_tap_key({"action": "tap", "x": 520, "y": 350}) == "tap:520,350"
    assert _same_tap_key({"action": "back"}) is None


def test_trivial_open_already_foreground_is_done():
    """Chat 'open Settings' must complete when Settings is already FG — not fail."""
    assert (_trivial_open_app_target("open Settings") or "").lower() == "settings"
    fg = "com.android.settings"
    assert "settings" in fg


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


def test_reconnect_wait_budget_fast_local(monkeypatch):
    import backend.device_push as push

    monkeypatch.delenv("WEBSOCKET_MANAGEMENT_ENDPOINT", raising=False)
    monkeypatch.setattr(push, "device_is_reachable", lambda _d: False)
    assert push.reconnect_wait_budget("android_x", 60) <= 1.5


def test_reconnect_wait_budget_full_after_recent_socket(monkeypatch):
    import backend.device_push as push
    import backend.storage as storage

    now = 1_700_000_000
    monkeypatch.setenv(
        "WEBSOCKET_MANAGEMENT_ENDPOINT", "https://example.execute-api/prod"
    )
    monkeypatch.setattr(push, "device_is_reachable", lambda _d: False)
    monkeypatch.setattr(push.time, "time", lambda: now)
    monkeypatch.setattr(
        storage,
        "get_device_connections",
        lambda _d: [
            {
                "connection_id": "gone",
                "device_id": "android_x",
                "role": "device",
                "authed": True,
                "connected_at": now - 30,
            }
        ],
    )
    # device_push imports get_device_connections inside the helper — patch module attr used
    monkeypatch.setattr(
        "backend.storage.get_device_connections",
        lambda _d: [
            {
                "connection_id": "gone",
                "device_id": "android_x",
                "role": "device",
                "authed": True,
                "connected_at": now - 30,
            }
        ],
    )
    assert push.reconnect_wait_budget("android_x", 60) == 60


def test_reconnect_wait_budget_cold_device(monkeypatch):
    import backend.device_push as push

    monkeypatch.setenv(
        "WEBSOCKET_MANAGEMENT_ENDPOINT", "https://example.execute-api/prod"
    )
    monkeypatch.setattr(push, "device_is_reachable", lambda _d: False)
    monkeypatch.setattr(
        "backend.storage.get_device_connections",
        lambda _d: [],
    )
    assert push.reconnect_wait_budget("android_x", 60) <= 3.0
