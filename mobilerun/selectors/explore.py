"""Bounded scroll / carousel exploration when a target isn't on screen.

Scrolls up/down/left/right with human-like gesture fractions, re-checks the
a11y tree after each scroll, and records a replayable navigation path.
No LLM involved in exploration itself.
"""

from __future__ import annotations

import logging
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from mobilerun.selectors.match import find_by_selector
from mobilerun.selectors.models import SelectorMatch, SelectorSpec

log = logging.getLogger("mobilerun.selectors.explore")

Direction = str  # up | down | left | right
DIRECTIONS: Tuple[str, ...] = ("down", "up", "right", "left")


@dataclass
class NavStep:
    """One replayable navigation action discovered during exploration."""

    kind: str  # scroll | tap_tab
    direction: Optional[str] = None
    count: int = 1
    tab_text: Optional[str] = None
    # Normalised gesture endpoints (0–1 screen fractions) for human-like replay
    start_x: float = 0.5
    start_y: float = 0.5
    end_x: float = 0.5
    end_y: float = 0.5
    duration_ms: int = 320

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NavStep":
        raw = data or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass
class ExploreResult:
    found: bool
    match: Optional[SelectorMatch] = None
    nav_path: List[NavStep] = field(default_factory=list)
    scrolls_tried: int = 0
    direction: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "nav_path": [s.to_dict() for s in self.nav_path],
            "scrolls_tried": self.scrolls_tried,
            "direction": self.direction,
            "center": self.match.center if self.match else None,
        }


def human_scroll_gesture(
    direction: str,
    *,
    rng: Optional[random.Random] = None,
) -> NavStep:
    """Build a jittered scroll gesture (fractions of screen)."""
    rng = rng or random.Random()
    # Axis mid with slight jitter
    mx = rng.uniform(0.42, 0.58)
    my = rng.uniform(0.42, 0.58)
    span = rng.uniform(0.28, 0.42)
    dur = int(rng.uniform(240, 480))
    if direction == "down":
        # Finger moves up → content scrolls down
        return NavStep(
            kind="scroll",
            direction="down",
            start_x=mx,
            start_y=my + span / 2,
            end_x=mx + rng.uniform(-0.03, 0.03),
            end_y=my - span / 2,
            duration_ms=dur,
        )
    if direction == "up":
        return NavStep(
            kind="scroll",
            direction="up",
            start_x=mx,
            start_y=my - span / 2,
            end_x=mx + rng.uniform(-0.03, 0.03),
            end_y=my + span / 2,
            duration_ms=dur,
        )
    if direction == "right":
        # Finger moves left → carousel moves right / next
        return NavStep(
            kind="scroll",
            direction="right",
            start_x=mx + span / 2,
            start_y=my,
            end_x=mx - span / 2,
            end_y=my + rng.uniform(-0.03, 0.03),
            duration_ms=dur,
        )
    # left
    return NavStep(
        kind="scroll",
        direction="left",
        start_x=mx - span / 2,
        start_y=my,
        end_x=mx + span / 2,
        end_y=my + rng.uniform(-0.03, 0.03),
        duration_ms=dur,
    )


def explore_for_selector(
    spec: SelectorSpec,
    *,
    get_tree: Callable[[], Any],
    perform_scroll: Callable[[NavStep], None],
    directions: Sequence[str] = DIRECTIONS,
    max_scrolls_per_direction: int = 4,
    tap_tabs: Optional[Sequence[str]] = None,
    perform_tap_tab: Optional[Callable[[str], None]] = None,
    rng: Optional[random.Random] = None,
) -> ExploreResult:
    """
    If selector isn't visible, scroll each direction (bounded) and re-check.

    `get_tree` must return the current a11y tree after any gesture.
    `perform_scroll` executes one human-like scroll (or simulates it in tests).
    """
    rng = rng or random.Random()
    tree = get_tree()
    hit = find_by_selector(tree, spec)
    if hit:
        return ExploreResult(found=True, match=hit, nav_path=[], scrolls_tried=0)

    # Optional tab taps first (e.g. Matches / Messages)
    if tap_tabs and perform_tap_tab:
        for tab in tap_tabs:
            try:
                perform_tap_tab(tab)
            except Exception:
                log.debug("tap_tab failed %s", tab, exc_info=True)
                continue
            step = NavStep(kind="tap_tab", tab_text=tab)
            tree = get_tree()
            hit = find_by_selector(tree, spec)
            if hit:
                return ExploreResult(
                    found=True,
                    match=hit,
                    nav_path=[step],
                    scrolls_tried=0,
                )

    path: List[NavStep] = []
    tried = 0
    for direction in directions:
        # Reset path segment per direction (don't accumulate failed dirs)
        dir_path: List[NavStep] = []
        for i in range(max_scrolls_per_direction):
            gesture = human_scroll_gesture(direction, rng=rng)
            gesture.count = i + 1
            try:
                perform_scroll(gesture)
            except Exception:
                log.debug("scroll %s failed", direction, exc_info=True)
                break
            tried += 1
            dir_path.append(gesture)
            tree = get_tree()
            hit = find_by_selector(tree, spec)
            if hit:
                return ExploreResult(
                    found=True,
                    match=hit,
                    nav_path=list(path) + dir_path,
                    scrolls_tried=tried,
                    direction=direction,
                )
        # Did not find in this direction — discard dir_path for cache
        # (only successful path is cached)

    return ExploreResult(found=False, nav_path=[], scrolls_tried=tried)


def replay_nav_path(
    nav_path: List[NavStep],
    *,
    perform_scroll: Callable[[NavStep], None],
    perform_tap_tab: Optional[Callable[[str], None]] = None,
) -> None:
    """Replay a cached navigation path without LLM."""
    for step in nav_path:
        if step.kind == "scroll":
            perform_scroll(step)
        elif step.kind == "tap_tab" and step.tab_text and perform_tap_tab:
            perform_tap_tab(step.tab_text)
