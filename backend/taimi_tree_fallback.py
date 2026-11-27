"""Taimi tree fallback: use a full / uiautomator dump when compact is empty.

The live compact get_ui_tree often returns nodes=0 for com.takimi.android
(FLAG_SECURE / Compose) while `adb shell uiautomator dump` and the APK's
fullMode walk have ~200 nodes. When the compact tree is empty, prefer a
full dump if one is available. Never treat an empty compact tree as a
reason to press Back (that left Taimi in tai3).
"""

from __future__ import annotations

import re
from typing import Optional

TAIMI_PKG = "com.takimi.android"


def is_taimi_context(
    instruction: str = "",
    package: str = "",
    tree: str = "",
) -> bool:
    blob = f"{instruction} {package} {tree[:800]}".lower()
    return "takimi" in blob or "taimi" in blob or TAIMI_PKG in blob


def is_empty_tree(tree: str) -> bool:
    raw = tree or ""
    if not raw.strip():
        return True
    if 'empty="true"' in raw:
        return True
    m = re.search(r'\bnodes="(\d+)"', raw)
    if m and int(m.group(1)) == 0:
        return True
    if len(raw) < 120:
        return True
    return False


def tree_has_useful_nodes(tree: str) -> bool:
    """True when the dump has walkable nodes (compact or uiautomator XML)."""
    if is_empty_tree(tree):
        return False
    if "<node " in tree or re.search(r"<n[\s>]", tree):
        # At least one real widget, not just an empty <w>
        return bool(re.search(r"<(node|n)\b[^>]*(text|content-desc|t=|d=)", tree))
    return False


def select_taimi_tree(compact: str, fallback: Optional[str]) -> str:
    """Prefer a non-empty uiautomator / full dump over an empty compact tree."""
    if fallback and tree_has_useful_nodes(fallback):
        if is_empty_tree(compact) or not tree_has_useful_nodes(compact):
            return fallback
    return compact or (fallback or "")
