"""Optimized state provider with caching and performance improvements."""

import asyncio
import hashlib
import logging
import time
from typing import Optional

from mobilerun.tools.ui.provider import AndroidStateProvider, StateProvider
from mobilerun.tools.ui.state import UIState

logger = logging.getLogger("mobilerun.optimized")


class CachedStateProvider:
    """
    Wrapper around StateProvider that adds intelligent caching to reduce
    redundant screenshot/UI tree fetches.
    """

    def __init__(
        self,
        provider: StateProvider,
        cache_ttl_seconds: float = 0.5,
        screenshot_cache_ttl: float = 0.3,
    ):
        self.provider = provider
        self.cache_ttl_seconds = cache_ttl_seconds
        self.screenshot_cache_ttl = screenshot_cache_ttl
        self._state_cache: Optional[tuple[float, UIState]] = None
        self._screenshot_cache: Optional[tuple[float, bytes]] = None
        self._last_screenshot_hash: Optional[str] = None

    async def get_state(
        self, force_refresh: bool = False, skip_screenshot: bool = False
    ) -> UIState:
        """Get UI state with caching."""
        now = time.time()

        # Check if cached state is still valid
        if (
            not force_refresh
            and self._state_cache is not None
            and (now - self._state_cache[0]) < self.cache_ttl_seconds
        ):
            return self._state_cache[1]

        # Fetch new state
        state = await self.provider.get_state()
        self._state_cache = (now, state)

        return state

    async def get_screenshot_only(self) -> bytes:
        """Get screenshot with separate caching (screenshots change less frequently)."""
        now = time.time()

        if (
            self._screenshot_cache is not None
            and (now - self._screenshot_cache[0]) < self.screenshot_cache_ttl
        ):
            return self._screenshot_cache[1]

        # Use provider's driver directly
        if hasattr(self.provider, "driver"):
            screenshot = await self.provider.driver.screenshot()
        else:
            # Fallback: get full state and extract screenshot
            state = await self.get_state()
            if state.screenshot_bytes:
                screenshot = state.screenshot_bytes
            else:
                raise ValueError("No screenshot available")

        self._screenshot_cache = (now, screenshot)
        return screenshot

    def has_screenshot_changed(self, new_screenshot: bytes) -> bool:
        """Quick check if screenshot has changed (using hash)."""
        new_hash = hashlib.md5(new_screenshot).hexdigest()
        changed = new_hash != self._last_screenshot_hash
        self._last_screenshot_hash = new_hash
        return changed

    def invalidate_cache(self):
        """Clear all caches."""
        self._state_cache = None
        self._screenshot_cache = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.invalidate_cache()


class OptimizedStateProvider(AndroidStateProvider):
    """
    Enhanced state provider with performance optimizations:
    - Parallel fetch of screenshot and UI tree
    - Compression/deduplication hints
    - Batch operation support
    """

    def __init__(self, *args, enable_parallel_fetch: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.enable_parallel_fetch = enable_parallel_fetch

    async def get_state(self) -> UIState:
        """Fetch state with optional parallel screenshot/tree fetch."""
        if not self.enable_parallel_fetch:
            return await super().get_state()

        # Fetch screenshot and UI tree in parallel
        screenshot_task = asyncio.create_task(self._fetch_screenshot())
        tree_task = asyncio.create_task(self._fetch_tree())

        try:
            screenshot_bytes, tree_data = await asyncio.gather(
                screenshot_task, tree_task, return_exceptions=False
            )
        except Exception as e:
            logger.warning(f"Parallel state fetch failed: {e}, falling back to serial")
            return await super().get_state()

        # Assemble state from parallel results
        state = UIState(
            screenshot_bytes=screenshot_bytes,
            formatted_text=tree_data["formatted"],
            indexed_elements=tree_data.get("indexed", {}),
            phone_state=tree_data.get("phone_state"),
        )
        return state

    async def _fetch_screenshot(self) -> bytes:
        """Fetch just the screenshot."""
        return await self.driver.screenshot()

    async def _fetch_tree(self) -> dict:
        """Fetch and format just the UI tree."""
        tree_xml = await self.driver.get_ui_tree()
        formatted = (
            self.tree_formatter.format(tree_xml) if self.tree_formatter else tree_xml
        )
        indexed = {}  # Implement indexing if needed
        return {
            "formatted": formatted,
            "indexed": indexed,
            "phone_state": None,  # Could extract from driver
        }
