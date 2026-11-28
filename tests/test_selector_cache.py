"""Selector discovery + cache: hit avoids LLM, miss discovers once, version invalidates."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.match import find_by_selector
from mobilerun.selectors.models import ElementRole, SelectorSpec
from mobilerun.selectors.navigator import SelectorNavigator

PKG = "ai.mobilerun.mockdating"

V1_TREE = {
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
            "className": "android.widget.Button",
            "clickable": True,
            "boundsInScreen": {"left": 40, "top": 940, "right": 1000, "bottom": 1040},
        },
        {
            "resourceId": "ai.mobilerun.mockdating:id/btnLike",
            "text": "Like",
            "clickable": True,
        },
    ]
}

V2_TREE = {
    "children": [
        {
            "resourceId": "ai.mobilerun.mockdating:id/chatComposer",
            "hint": "Write something",
            "className": "android.widget.EditText",
            "editable": True,
            "boundsInScreen": {"left": 40, "top": 800, "right": 1000, "bottom": 920},
        },
        {
            "resourceId": "ai.mobilerun.mockdating:id/btnSendMessage",
            "text": "Send",
            "contentDescription": "Send message",
            "clickable": True,
            "boundsInScreen": {"left": 40, "top": 940, "right": 1000, "bottom": 1040},
        },
        {
            "resourceId": "ai.mobilerun.mockdating:id/btnHeart",
            "text": "Like",
            "clickable": True,
        },
    ]
}


@pytest.fixture
def cache(tmp_path: Path) -> SelectorCache:
    return SelectorCache(
        user_id="test", persist_dir=tmp_path / "sel", max_rediscovery=3
    )


def test_cache_hit_avoids_llm(cache: SelectorCache):
    nav = SelectorNavigator(cache=cache)
    calls = []

    def llm(**kwargs):
        calls.append(kwargs)
        return {"resource_id": "SHOULD_NOT_RUN"}

    # First resolve seeds from defaults / heuristic
    r1 = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name=PKG,
        version_code="1",
        tree=V1_TREE,
        llm_callable=llm,
    )
    assert r1.found
    assert r1.used_llm is False
    assert calls == []

    # Second resolve is pure cache hit
    r2 = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name=PKG,
        version_code="1",
        tree=V1_TREE,
        llm_callable=llm,
    )
    assert r2.found
    assert r2.cache_hit is True
    assert r2.used_llm is False
    assert r2.llm_calls == 0
    assert calls == []


def test_miss_triggers_single_llm_then_cached(cache: SelectorCache):
    # Empty cache for unknown package — force LLM path
    nav = SelectorNavigator(cache=cache)
    calls = []

    def llm(**kwargs):
        calls.append(kwargs)
        return {
            "resource_id": "com.other.app:id/composer",
            "hint": "Type a message",
            "class_name": "android.widget.EditText",
        }

    tree = {
        "children": [
            {
                "resourceId": "com.other.app:id/composer",
                "hint": "Type a message",
                "className": "android.widget.EditText",
                "editable": True,
                "boundsInScreen": {"left": 0, "top": 0, "right": 10, "bottom": 10},
            }
        ]
    }

    r1 = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name="com.other.app",
        version_code="10",
        tree=tree,
        llm_callable=llm,
    )
    # May hit heuristic via hint first (no LLM). Force by using obscure role tree
    # without matching hints — clear and use custom role with no fallback.
    # Re-run with a tree that has no "Type a message" but LLM returns id.
    calls.clear()
    cache.invalidate("com.other.app", "10")
    tree2 = {
        "children": [
            {
                "resourceId": "com.other.app:id/weirdInput",
                "className": "android.widget.EditText",
                "editable": True,
                "boundsInScreen": {"left": 0, "top": 0, "right": 10, "bottom": 10},
            }
        ]
    }

    def llm2(**kwargs):
        calls.append(kwargs)
        return {
            "resource_id": "com.other.app:id/weirdInput",
            "class_name": "android.widget.EditText",
        }

    r_miss = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name="com.other.app",
        version_code="10",
        tree=tree2,
        llm_callable=llm2,
    )
    assert r_miss.found
    assert r_miss.used_llm is True
    assert r_miss.llm_calls == 1
    assert len(calls) == 1

    calls.clear()
    r_hit = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name="com.other.app",
        version_code="10",
        tree=tree2,
        llm_callable=llm2,
    )
    assert r_hit.found
    assert r_hit.cache_hit is True
    assert r_hit.used_llm is False
    assert calls == []


def test_version_change_invalidates(cache: SelectorCache):
    nav = SelectorNavigator(cache=cache)
    r1 = nav.resolve(
        role=ElementRole.SEND_BUTTON.value,
        package_name=PKG,
        version_code="1",
        tree=V1_TREE,
        allow_llm=False,
    )
    assert r1.found

    # Version changes → v1 selector must not be reused for v2
    assert cache.invalidate_if_version_changed(PKG, "1", "v2") is True

    # Cached v1 selector fails on v2 tree
    entry = cache.get(PKG, "1", ElementRole.SEND_BUTTON.value)
    assert entry is not None
    assert find_by_selector(V2_TREE, entry.selector) is None

    # Fresh resolve on v2 uses v2 defaults / heuristic — still no LLM if seeded
    r2 = nav.resolve(
        role=ElementRole.SEND_BUTTON.value,
        package_name=PKG,
        version_code="v2",
        tree=V2_TREE,
        allow_llm=False,
    )
    assert r2.found
    assert r2.used_llm is False
    assert "btnSendMessage" in (r2.selector.resource_id or "")


def test_rediscovery_cap_escalates(cache: SelectorCache):
    from mobilerun.selectors.models import CachedEntry

    needs = []
    nav = SelectorNavigator(
        cache=cache,
        max_rediscovery=2,
        push_needs_you=lambda **kw: needs.append(kw) or "ny_1",
    )
    empty = {"children": []}
    cache.put(
        CachedEntry(
            role=ElementRole.SEND_BUTTON.value,
            selector=SelectorSpec(resource_id="missing:id/x", text="__nope__"),
            package_name="com.fail.app",
            version_code="1",
            source="manual",
        )
    )
    last = None
    for _ in range(4):
        last = nav.resolve(
            role=ElementRole.SEND_BUTTON.value,
            package_name="com.fail.app",
            version_code="1",
            tree=empty,
            allow_llm=False,
        )
    assert last is not None
    assert last.needs_you is True
    assert needs


