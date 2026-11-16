"""SelectorCache Dynamo is source of truth; /tmp is read-through only."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.models import CachedEntry, LayoutVariant, SelectorSpec


@pytest.fixture
def dynamo_store(monkeypatch):
    store: Dict[str, Dict[str, Any]] = {}

    def save_user_setting(user_id: str, name: str, data: Dict[str, Any]) -> bool:
        store[f"user:{user_id}:{name}"] = dict(data)
        return True

    def get_user_setting(user_id: str, name: str):
        return store.get(f"user:{user_id}:{name}")

    monkeypatch.setenv("USE_AWS_STORAGE", "true")
    monkeypatch.setattr(
        "mobilerun.selectors.cache._storage_get",
        lambda: (get_user_setting, save_user_setting),
    )
    return store


def test_put_survives_empty_tmp(tmp_path: Path, dynamo_store, monkeypatch):
    dir_a = tmp_path / "a"
    cache = SelectorCache(user_id="mac", persist_dir=dir_a)
    entry = CachedEntry(
        role="send_button",
        selector=SelectorSpec(resource_id="id/send"),
        package_name="com.tinder",
        version_code="99",
        source="llm",
        variants=[
            LayoutVariant(
                selector=SelectorSpec(resource_id="id/send"),
                source="llm",
                label="v99",
            )
        ],
    )
    cache.put(entry)
    assert "user:mac:selectors:com.tinder:99" in dynamo_store
    assert "user:mac:selectors_index" in dynamo_store
    pkgs = dynamo_store["user:mac:selectors_index"]["packages"]
    assert {"package_name": "com.tinder", "version_code": "99"} in pkgs

    # New instance, empty /tmp — still lists + loads from Dynamo
    dir_b = tmp_path / "b"
    cold = SelectorCache(user_id="mac", persist_dir=dir_b)
    listed = cold.list_packages()
    assert any(s.package_name == "com.tinder" for s in listed)
    loaded = cold.get("com.tinder", "99", "send_button")
    assert loaded is not None
    assert loaded.selector.resource_id == "id/send"
    # Read-through cache warmed
    assert (dir_b / "com.tinder@99.json").exists()
