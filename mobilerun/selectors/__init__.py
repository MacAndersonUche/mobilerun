"""Selector discovery + cache for dating/social navigation (a11y-first, LLM once)."""

from mobilerun.selectors.models import (
    ElementRole,
    SelectorMatch,
    SelectorSpec,
    CachedEntry,
    CacheStatus,
)
from mobilerun.selectors.match import find_by_selector, flatten_nodes
from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.discover import derive_selector_from_node, llm_locate
from mobilerun.selectors.navigator import SelectorNavigator, ResolveResult
from mobilerun.selectors.explore import (
    NavStep,
    ExploreResult,
    explore_for_selector,
    human_scroll_gesture,
    replay_nav_path,
)

__all__ = [
    "ElementRole",
    "SelectorSpec",
    "SelectorMatch",
    "CachedEntry",
    "CacheStatus",
    "find_by_selector",
    "flatten_nodes",
    "SelectorCache",
    "derive_selector_from_node",
    "llm_locate",
    "SelectorNavigator",
    "ResolveResult",
    "NavStep",
    "ExploreResult",
    "explore_for_selector",
    "human_scroll_gesture",
    "replay_nav_path",
]
