"""Load test-apps/fake-chats/catalog.json for matrix + heuristics (catalog soft-fail).

On Lambda the catalog file is not packaged — return safe empty defaults so
normal (non-bench) agent jobs never crash on import/plan.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("mobilerun.fake_chats_catalog")  # deploy-queue-unstick

_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_PATH = _ROOT / "test-apps" / "fake-chats" / "catalog.json"

# Minimal fallback when catalog.json is absent (prod Lambda asset).
_EMPTY_CATALOG: Dict[str, Any] = {
    "apps": [],
    "bulk": {"swipe_count": 50, "message_count": 50},
}


@lru_cache(maxsize=1)
def load_catalog() -> Dict[str, Any]:
    try:
        if not _CATALOG_PATH.is_file():
            logger.warning(
                "fake-chats catalog missing at %s — using empty defaults",
                _CATALOG_PATH,
            )
            return dict(_EMPTY_CATALOG)
        return json.loads(_CATALOG_PATH.read_text())
    except Exception as e:
        logger.warning("fake-chats catalog load failed: %s — using empty defaults", e)
        return dict(_EMPTY_CATALOG)


def apps() -> List[Dict[str, Any]]:
    return list(load_catalog().get("apps") or [])


def app_by_key(key: str) -> Dict[str, Any]:
    for a in apps():
        if a.get("key") == key:
            return a
    raise KeyError(key)


def packages() -> Dict[str, str]:
    return {a["key"]: a["package"] for a in apps() if a.get("key") != "securefolder"}


def swipe_keys() -> List[str]:
    return [a["key"] for a in apps() if a.get("family") in ("swipe", "facebook_dating")]


def messaging_keys() -> List[str]:
    return [a["key"] for a in apps() if a.get("family") == "messaging"]


def dm_keys() -> List[str]:
    """Apps that support single-DM Precious flow (all except securefolder)."""
    return [a["key"] for a in apps() if a.get("key") != "securefolder"]


def bulk_counts() -> Dict[str, int]:
    b = load_catalog().get("bulk") or {}
    return {
        "swipe": int(b.get("swipe_count") or 50),
        "message": int(b.get("message_count") or 50),
    }

