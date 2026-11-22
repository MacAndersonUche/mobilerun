"""APK 540 home-empty + WS screenshot size: backend must fix empty + open_app; S3 shots."""

from __future__ import annotations

import base64
from typing import Any, Dict, List

from backend.cloud_agent import (
    _fetch_screenshot_b64,
    _is_launcher_package,
    _launcher_open_target_action,
    _normalize_tree_payload,
    _open_label_for_package,
)
from backend.overlay_dismiss import (
    detect_foreign_overlay,
    dismiss_foreign_overlays_before_plan,
    is_foreign_overlay_package,
    is_launcher_package,
)

# Exact shape APK 540 shipped: 38 launcher nodes, app_nodes=0, empty=true
_APK540_HOME = (
    '<hierarchy windows="1" nodes="38" app_nodes="0" partial="false" '
    'empty="true" mode="compact" packages="com.sec.android.app.launcher">\n'
    + "".join(
        f'<n t="Icon{i}" c="1" xy="{100 + (i % 4) * 200},{400 + (i // 4) * 220}"/>\n'
        for i in range(38)
    )
    + "</hierarchy>"
)


def test_is_launcher_package_samsung_and_aosp():
    assert _is_launcher_package("com.sec.android.app.launcher")
    assert _is_launcher_package("com.android.launcher3")
    assert _is_launcher_package("com.google.android.apps.nexuslauncher")
    assert is_launcher_package("com.sec.android.app.launcher")
    assert not _is_launcher_package("com.bumble.app")
    assert not _is_launcher_package("com.takimi.android")
    assert not _is_launcher_package("com.android.systemui")


def test_normalize_apk540_launcher_empty_flag_forced_false():
    """Backend-only: trust nodes>0 on launcher even when APK says empty=true."""
    info = _normalize_tree_payload(
        {
            "tree": _APK540_HOME,
            "package": "com.sec.android.app.launcher",
            "empty": True,
            "nodes": 38,
            "chars": len(_APK540_HOME),
        }
    )
    assert info["empty"] is False
    assert info["nodes"] == 38
    assert "com.sec.android.app.launcher" in info["package"]
    assert "Icon0" in info["tree"]


def test_normalize_launcher_string_header_empty_true():
    info = _normalize_tree_payload(_APK540_HOME)
    assert info["empty"] is False
    assert info["nodes"] == 38


def test_normalize_systemui_only_stays_empty():
    tree = (
        '<hierarchy windows="1" nodes="2" app_nodes="0" empty="true" '
        'packages="com.android.systemui">'
        '<n t="Clock" xy="100,40"/><n t="Battery" xy="900,40"/>'
        "</hierarchy>"
    )
    info = _normalize_tree_payload(
        {"tree": tree, "package": "com.android.systemui", "empty": True, "nodes": 2}
    )
    # SystemUI chrome is not a launcher — keep empty=true (app_nodes=0)
    assert info["empty"] is True


def test_normalize_dating_app_nodes_overrides_empty_lie():
    tree = (
        '<hierarchy windows="1" nodes="5" app_nodes="5" empty="true" '
        'packages="com.bumble.app">'
        '<n t="Sam" c="1" xy="300,800"/>'
        "</hierarchy>"
    )
    info = _normalize_tree_payload(
        {"tree": tree, "package": "com.bumble.app", "empty": True, "nodes": 5}
    )
    assert info["empty"] is False


def test_open_label_for_dating_packages():
    assert _open_label_for_package("com.bumble.app") == "Bumble"
    assert _open_label_for_package("com.takimi.android") == "Taimi"
    assert _open_label_for_package("com.hily.app") == "Hily"


def test_launcher_open_target_action_emits_open_app():
    act = _launcher_open_target_action("com.bumble.app", "com.sec.android.app.launcher")
    assert act is not None
    assert act["action"] == "open_app"
    assert act["app"] == "Bumble"
    assert act["package"] == "com.bumble.app"
    assert act["planner"] == "launcher_open_target"
    assert "launcher" in (act["reason"] or "").lower()


def test_launcher_open_target_noop_when_already_fg():
    assert _launcher_open_target_action("com.bumble.app", "com.bumble.app") is None
    assert _launcher_open_target_action("", "com.sec.android.app.launcher") is None
    assert _launcher_open_target_action("com.bumble.app", "") is None


def test_launcher_not_foreign_overlay_never_back_dismiss():
    assert not is_foreign_overlay_package(
        "com.sec.android.app.launcher", "com.bumble.app"
    )
    tree = (
        '<hierarchy packages="com.sec.android.app.launcher">'
        '<w id="active" p="com.sec.android.app.launcher" f="1">'
        '<n t="Bumble" c="1" xy="200,800"/>'
        "</w></hierarchy>"
    )
    assert detect_foreign_overlay(tree, "com.bumble.app") is None

    calls: List[Dict[str, Any]] = []

    def execute_action(_device, act):
        calls.append(act)
        return "ok"

    _tree, info, hist = dismiss_foreign_overlays_before_plan(
        device_id="dev1",
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
        target_package="com.bumble.app",
        history=[],
        state={},
        max_attempts=3,
    )
    assert calls == [], "must not Back-dismiss the home launcher"
    assert hist == []
    assert "launcher" in (info.get("package") or "")


def _install_fake_call_device(monkeypatch, fake_call):
    import sys
    import types

    mod = types.ModuleType("device_rpc")
    mod.call_device = fake_call  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "device_rpc", mod)
    monkeypatch.setattr("backend.device_rpc.call_device", fake_call)


def test_fetch_screenshot_uses_s3_when_presigned(monkeypatch):
    """Cloud asks phone for S3 upload; downloads JPEG — never needs WS base64."""
    jpeg = b"\xff\xd8\xff" + b"fakejpeg" * 8000  # ~56KB — would blow 32KB WS frame
    put_urls: List[str] = []
    rpc_params: List[Dict[str, Any]] = []

    monkeypatch.setenv("SCREENSHOT_BUCKET", "mobilerun-screenshots-test")

    class _FakeS3:
        def generate_presigned_url(self, *a, **k):
            return "https://s3.example/put-shot"

        def get_object(self, Bucket, Key):  # noqa: N803
            assert Bucket == "mobilerun-screenshots-test"
            assert Key.startswith("tasks/")

            class _Body:
                def read(self):
                    return jpeg

            return {"Body": _Body()}

    import sys
    import types

    fake_boto = types.ModuleType("boto3")
    fake_boto.client = lambda *_a, **_k: _FakeS3()  # type: ignore
    monkeypatch.setitem(sys.modules, "boto3", fake_boto)

    def fake_call(device_id, cmd, params=None, **kwargs):
        assert cmd == "screenshot"
        rpc_params.append(dict(params or {}))
        put_urls.append(str((params or {}).get("upload_url") or ""))
        assert (params or {}).get("upload_url")
        assert (params or {}).get("s3_key")
        return {
            "ok": True,
            "encoding": "s3",
            "s3_key": params["s3_key"],
            "bytes": len(jpeg),
            "source": "a11y",
        }

    _install_fake_call_device(monkeypatch, fake_call)

    b64 = _fetch_screenshot_b64("dev1", job={"job_id": "job-ss-1"})
    assert b64 is not None
    assert base64.b64decode(b64) == jpeg
    assert put_urls and put_urls[0].startswith("https://")
    assert rpc_params[0].get("max_width") == 720
    assert rpc_params[0].get("quality") == 42


def test_fetch_screenshot_without_bucket_still_calls_rpc(monkeypatch):
    monkeypatch.delenv("SCREENSHOT_BUCKET", raising=False)
    seen: List[Dict[str, Any]] = []

    def fake_call(device_id, cmd, params=None, **kwargs):
        seen.append(dict(params or {}))
        # Tiny inline OK for legacy path
        return {
            "ok": True,
            "data": base64.b64encode(b"tiny").decode(),
            "bytes": 4,
        }

    _install_fake_call_device(monkeypatch, fake_call)
    out = _fetch_screenshot_b64("dev1", job={"job_id": "j2"})
    assert out is not None
    assert "upload_url" not in (seen[0] or {})
