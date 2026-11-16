"""Multi layout-variant selector cache: ordering, eviction, no LLM on match."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.models import (
    ElementRole,
    LayoutVariant,
    SelectorSpec,
    clamp_max_variants,
)
from mobilerun.selectors.navigator import SelectorNavigator

PKG = "ai.mobilerun.mockdating"
VER = "multi"

V1 = {
    "children": [
        {
            "resourceId": "ai.mobilerun.mockdating:id/messageInput",
            "hint": "Type a message",
            "className": "android.widget.EditText",
            "editable": True,
            "boundsInScreen": {"left": 40, "top": 800, "right": 1000, "bottom": 920},
        },
        {
            "resourceId": "ai.mobilerun.mockdating:id/btnSend",
            "text": "Send",
            "clickable": True,
        },
    ]
}
V2 = {
    "children": [
        {
            "resourceId": "ai.mobilerun.mockdating:id/chatComposer",
            "hint": "Write something",
            "className": "android.widget.EditText",
            "editable": True,
            "boundsInScreen": {"left": 40, "top": 200, "right": 1000, "bottom": 320},
        },
        {
            "resourceId": "ai.mobilerun.mockdating:id/btnSendMessage",
            "text": "Send",
            "contentDescription": "Send message",
            "clickable": True,
        },
    ]
}
V3 = {
    "children": [
        {
            "resourceId": "ai.mobilerun.mockdating:id/msgBox",
            "hint": "Say hi",
            "className": "android.widget.EditText",
            "editable": True,
            "boundsInScreen": {"left": 40, "top": 1500, "right": 800, "bottom": 1620},
        },
        {
            "resourceId": "ai.mobilerun.mockdating:id/btnPost",
            "text": "Send",
            "contentDescription": "Post message",
            "clickable": True,
        },
    ]
}


@pytest.fixture
def cache(tmp_path: Path) -> SelectorCache:
    return SelectorCache(
        user_id="test-variants",
        persist_dir=tmp_path / "sel",
        max_rediscovery=5,
        max_layout_variants=4,
    )


def test_clamp_max_variants():
    assert clamp_max_variants(None) == 4
    assert clamp_max_variants(1) == 2  # min 2
    assert clamp_max_variants(2) == 2
    assert clamp_max_variants(8) == 8


def test_multiple_variants_no_llm_when_any_matches(cache: SelectorCache):
    nav = SelectorNavigator(cache=cache)
    calls = []

    def llm(**kwargs):
        calls.append(kwargs)
        return {"resource_id": "should_not_run"}

    # Discover three layouts under the same app+version
    for tree, label in ((V1, "v1"), (V2, "v2"), (V3, "v3")):
        r = nav.resolve(
            role=ElementRole.MESSAGE_INPUT.value,
            package_name=PKG,
            version_code=VER,
            tree=tree,
            llm_callable=llm,
            allow_llm=True,
        )
        assert r.found, label
        assert r.used_llm is False, label

    entry = cache.get(PKG, VER, ElementRole.MESSAGE_INPUT.value)
    assert entry is not None
    # Seeded default + discovered layouts (at least the three chat-bar shapes)
    assert len(entry.variants) >= 3

    calls.clear()
    # Alternating chats — each hits a cached variant, never LLM
    for tree in (V2, V1, V3, V2, V3, V1):
        r = nav.resolve(
            role=ElementRole.MESSAGE_INPUT.value,
            package_name=PKG,
            version_code=VER,
            tree=tree,
            llm_callable=llm,
        )
        assert r.found
        assert r.cache_hit is True
        assert r.used_llm is False
        assert calls == []


def test_variants_ordered_by_success_rate(cache: SelectorCache):
    # Use a non-default package so DEFAULT_SELECTORS do not seed extra variants
    pkg = "com.hinge.app"
    ver = "42"
    trees = [
        {
            "children": [
                {
                    "resourceId": "com.hinge.app:id/input_a",
                    "hint": "Type a message",
                    "className": "android.widget.EditText",
                    "editable": True,
                }
            ]
        },
        {
            "children": [
                {
                    "resourceId": "com.hinge.app:id/input_b",
                    "hint": "Type a message",
                    "className": "android.widget.EditText",
                    "editable": True,
                }
            ]
        },
        {
            "children": [
                {
                    "resourceId": "com.hinge.app:id/input_c",
                    "hint": "Type a message",
                    "className": "android.widget.EditText",
                    "editable": True,
                }
            ]
        },
    ]
    specs = [
        SelectorSpec(resource_id="com.hinge.app:id/input_a"),
        SelectorSpec(resource_id="com.hinge.app:id/input_b"),
        SelectorSpec(resource_id="com.hinge.app:id/input_c"),
    ]
    ids = []
    for i, spec in enumerate(specs):
        _, v, _ = cache.add_variant(
            package_name=pkg,
            version_code=ver,
            role=ElementRole.MESSAGE_INPUT.value,
            selector=spec,
            source="manual",
            label=f"v{i+1}",
        )
        ids.append(v.id)

    # Make v2 (index 1) most successful; v1 middling; v3 failing
    for _ in range(5):
        cache.mark_variant_success(pkg, ver, ElementRole.MESSAGE_INPUT.value, ids[1])
    for _ in range(2):
        cache.mark_variant_success(pkg, ver, ElementRole.MESSAGE_INPUT.value, ids[0])
    for _ in range(3):
        cache.mark_variant_miss(pkg, ver, ElementRole.MESSAGE_INPUT.value, ids[0])
    for _ in range(4):
        cache.mark_variant_miss(pkg, ver, ElementRole.MESSAGE_INPUT.value, ids[2])

    ordered = cache.ordered_variants(pkg, ver, ElementRole.MESSAGE_INPUT.value)
    assert [v.id for v in ordered][0] == ids[1]
    assert ordered[0].success_rate >= ordered[1].success_rate
    assert ordered[-1].id == ids[2]

    nav = SelectorNavigator(cache=cache)
    r = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name=pkg,
        version_code=ver,
        tree=trees[1],
        allow_llm=False,
    )
    assert r.found
    assert r.variant_id == ids[1]
    assert r.cache_hit is True
    assert r.variants_tried == 1


def test_eviction_at_cap_least_used(cache: SelectorCache):
    cache.max_layout_variants = 2  # min allowed
    assert cache.max_layout_variants == 2
    pkg = "com.example.dating.evict"
    ver = "1"
    cache.invalidate(pkg, ver)

    kept_ids = []
    for i in range(2):
        _, v, ev = cache.add_variant(
            package_name=pkg,
            version_code=ver,
            role=ElementRole.MESSAGE_INPUT.value,
            selector=SelectorSpec(resource_id=f"{pkg}:id/input_{i}"),
            source="manual",
            label=f"slot{i}",
        )
        assert ev is None, ev
        kept_ids.append(v.id)
        # Give first variant many hits so second is least-used when third arrives
        if i == 0:
            for _ in range(10):
                cache.mark_variant_success(
                    pkg, ver, ElementRole.MESSAGE_INPUT.value, v.id
                )

    entry = cache.get(pkg, ver, ElementRole.MESSAGE_INPUT.value)
    assert entry is not None
    assert len(entry.variants) == 2

    _, v3, evicted = cache.add_variant(
        package_name=pkg,
        version_code=ver,
        role=ElementRole.MESSAGE_INPUT.value,
        selector=SelectorSpec(resource_id=f"{pkg}:id/input_new"),
        source="llm",
        label="new",
    )
    assert evicted is not None
    assert evicted.id == kept_ids[1], (evicted.id, kept_ids, evicted.hits)
    entry = cache.get(pkg, ver, ElementRole.MESSAGE_INPUT.value)
    assert entry is not None
    assert len(entry.variants) == 2
    ids = {v.id for v in entry.variants}
    assert kept_ids[0] in ids
    assert v3.id in ids
    assert kept_ids[1] not in ids


def test_status_includes_variant_hit_counts(cache: SelectorCache):
    nav = SelectorNavigator(cache=cache)
    for tree in (V1, V2, V3):
        nav.resolve(
            role=ElementRole.SEND_BUTTON.value,
            package_name=PKG,
            version_code=VER,
            tree=tree,
            allow_llm=False,
        )
    # Extra hits on V1
    for _ in range(3):
        nav.resolve(
            role=ElementRole.SEND_BUTTON.value,
            package_name=PKG,
            version_code=VER,
            tree=V1,
            allow_llm=False,
        )
    st = cache.status(PKG, VER).to_dict()
    assert st["max_layout_variants"] == 4
    role = next(r for r in st["roles"] if r["role"] == ElementRole.SEND_BUTTON.value)
    assert role["variant_count"] >= 3
    assert all("hits" in v for v in role["variants"])
    assert sum(v["hits"] for v in role["variants"]) >= 4


def test_api_multi_variant_alternating(monkeypatch, tmp_path):
    import importlib

    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.setenv("MOBILERUN_MAX_LAYOUT_VARIANTS", "4")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)

    import backend.main as main_mod

    importlib.reload(main_mod)
    main_mod._selector_nav = None
    from fastapi.testclient import TestClient

    c = TestClient(main_mod.app)
    ver = "e2e_multi"
    llm_calls_total = 0
    for tree in (V1, V2, V3):
        r = c.post(
            "/api/selectors/resolve",
            json={
                "role": "message_input",
                "package_name": PKG,
                "version_code": ver,
                "tree": tree,
                "allow_llm": True,
                "llm_stub": {"resource_id": "should_not_need"},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["found"] is True
        assert body["used_llm"] is False
        llm_calls_total += body.get("llm_callable_invocations", 0)
    assert llm_calls_total == 0

    # Alternating — all cache hits
    for tree in (V3, V1, V2, V3):
        r = c.post(
            "/api/selectors/resolve",
            json={
                "role": "message_input",
                "package_name": PKG,
                "version_code": ver,
                "tree": tree,
                "allow_llm": True,
                "llm_stub": {"resource_id": "nope"},
            },
        )
        body = r.json()
        assert body["cache_hit"] is True
        assert body["llm_callable_invocations"] == 0

    st = c.get(
        "/api/selectors/status",
        params={"package_name": PKG, "version_code": ver},
    )
    assert st.status_code == 200
    apps = st.json()["apps"]
    assert apps
    role = next(r for r in apps[0]["roles"] if r["role"] == "message_input")
    assert role["variant_count"] == 3
    assert len(role["variants"]) == 3
    assert all(v.get("hits", 0) >= 1 for v in role["variants"])
