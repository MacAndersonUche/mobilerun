"""Scroll exploration: bounded U/D/L/R, cache nav_path, replay without LLM."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.explore import (
    NavStep,
    explore_for_selector,
    human_scroll_gesture,
    replay_nav_path,
)
from mobilerun.selectors.models import ElementRole, SelectorSpec
from mobilerun.selectors.navigator import SelectorNavigator

# Non-seeded package so explore tests don't collide with DEFAULT_SELECTORS
PKG = "ai.mobilerun.mockdating.explore"

HIDDEN = {"children": [{"resourceId": f"{PKG}:id/profileName", "text": "Alex"}]}

REVEALED_INPUT = {
    "children": [
        {"resourceId": f"{PKG}:id/profileName", "text": "Alex"},
        {
            "resourceId": f"{PKG}:id/messageInput",
            "hint": "Type a message",
            "className": "android.widget.EditText",
            "editable": True,
            "boundsInScreen": {"left": 40, "top": 800, "right": 1000, "bottom": 920},
        },
        {
            "resourceId": f"{PKG}:id/btnSend",
            "text": "Send",
            "className": "android.widget.Button",
            "clickable": True,
        },
        {
            "resourceId": f"{PKG}:id/matchesList",
            "contentDescription": "Matches list",
            "text": "Matches · Alex, Jordan, Sam",
        },
    ]
}

SPEC_INPUT = SelectorSpec(
    resource_id=f"{PKG}:id/messageInput",
    hint="Type a message",
)
SPEC_SEND = SelectorSpec(resource_id=f"{PKG}:id/btnSend", text="Send")
SPEC_MATCHES = SelectorSpec(
    resource_id=f"{PKG}:id/matchesList",
    content_desc="Matches list",
)


@pytest.fixture
def cache(tmp_path: Path) -> SelectorCache:
    return SelectorCache(
        user_id="test-explore", persist_dir=tmp_path / "sel", max_rediscovery=3
    )


@pytest.mark.parametrize("direction", ["down", "up", "left", "right"])
def test_explore_finds_after_scroll_each_direction(direction: str):
    state = {"tree": HIDDEN, "n": 0}
    reveal_after = 2

    def get_tree():
        return state["tree"]

    def perform_scroll(step: NavStep):
        assert step.kind == "scroll"
        assert 0.0 < step.start_x < 1.0
        assert 0.0 < step.end_y < 1.0 or 0.0 < step.end_x < 1.0
        assert step.duration_ms >= 200
        if step.direction == direction:
            state["n"] += 1
            if state["n"] >= reveal_after:
                state["tree"] = REVEALED_INPUT

    result = explore_for_selector(
        SPEC_INPUT,
        get_tree=get_tree,
        perform_scroll=perform_scroll,
        directions=(direction,),
        max_scrolls_per_direction=4,
    )
    assert result.found is True
    assert result.direction == direction
    assert len(result.nav_path) == reveal_after
    assert all(s.direction == direction for s in result.nav_path)
    assert result.scrolls_tried == reveal_after


def test_explore_bounded_gives_up():
    def get_tree():
        return HIDDEN

    scrolls = []

    def perform_scroll(step: NavStep):
        scrolls.append(step.direction)

    result = explore_for_selector(
        SPEC_INPUT,
        get_tree=get_tree,
        perform_scroll=perform_scroll,
        directions=("down", "up"),
        max_scrolls_per_direction=2,
    )
    assert result.found is False
    assert result.scrolls_tried == 4
    assert scrolls.count("down") == 2
    assert scrolls.count("up") == 2


def test_human_scroll_gesture_jitter():
    g1 = human_scroll_gesture("down", rng=__import__("random").Random(1))
    g2 = human_scroll_gesture("down", rng=__import__("random").Random(2))
    assert g1.kind == "scroll"
    assert g1.direction == "down"
    # Finger moves up for content-down
    assert g1.start_y > g1.end_y
    assert g1.duration_ms != g2.duration_ms or g1.start_x != g2.start_x


def test_navigator_explore_caches_nav_path_and_replays(cache: SelectorCache):
    nav = SelectorNavigator(cache=cache, max_scrolls_per_direction=4)
    state = {"tree": copy.deepcopy(HIDDEN), "n": 0}
    llm_calls = []
    pkg = f"{PKG}.navpath"
    ver = "1"

    def get_tree():
        return state["tree"]

    def perform_scroll(step: NavStep):
        if step.direction == "down":
            state["n"] += 1
            if state["n"] >= 2:
                state["tree"] = copy.deepcopy(REVEALED_INPUT)

    def llm(**kwargs):
        llm_calls.append(kwargs)
        return {}

    # Ensure no seeded / leftover entry
    cache.invalidate(pkg, ver)

    r1 = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name=pkg,
        version_code=ver,
        tree=state["tree"],
        llm_callable=llm,
        get_tree=get_tree,
        perform_scroll=perform_scroll,
        explore=True,
        candidate_spec=SPEC_INPUT,
    )
    assert r1.found is True, r1
    assert r1.source == "explore", r1
    assert r1.used_llm is False
    assert llm_calls == []
    assert r1.nav_path
    assert all(s.get("direction") == "down" for s in r1.nav_path)

    entry = cache.get(pkg, ver, ElementRole.MESSAGE_INPUT.value)
    assert entry is not None
    assert entry.nav_path
    assert entry.source == "explore"

    # Replay: reset tree to hidden; cache hit must replay path then match
    state["tree"] = copy.deepcopy(HIDDEN)
    state["n"] = 0
    r2 = nav.resolve(
        role=ElementRole.MESSAGE_INPUT.value,
        package_name=pkg,
        version_code=ver,
        tree=state["tree"],
        llm_callable=llm,
        get_tree=get_tree,
        perform_scroll=perform_scroll,
    )
    assert r2.found is True
    assert r2.cache_hit is True
    assert r2.used_llm is False
    assert llm_calls == []
    assert state["n"] >= 2


@pytest.mark.parametrize(
    "direction,role,spec",
    [
        ("down", ElementRole.MESSAGE_INPUT.value, SPEC_INPUT),
        ("up", ElementRole.SEND_BUTTON.value, SPEC_SEND),
        ("left", ElementRole.MATCHES_LIST.value, SPEC_MATCHES),
        ("right", ElementRole.MESSAGE_INPUT.value, SPEC_INPUT),
    ],
)
def test_navigator_each_direction_offscreen(
    cache: SelectorCache, direction, role, spec
):
    nav = SelectorNavigator(cache=cache, max_scrolls_per_direction=3)
    state = {"tree": copy.deepcopy(HIDDEN), "n": 0}
    pkg = f"{PKG}.dir.{direction}"
    ver = "1"
    cache.invalidate(pkg, ver)

    def get_tree():
        return state["tree"]

    def perform_scroll(step: NavStep):
        if step.direction == direction:
            state["n"] += 1
            if state["n"] >= 1:
                state["tree"] = copy.deepcopy(REVEALED_INPUT)

    r = nav.resolve(
        role=role,
        package_name=pkg,
        version_code=ver,
        tree=state["tree"],
        allow_llm=False,
        get_tree=get_tree,
        perform_scroll=perform_scroll,
        candidate_spec=spec,
    )
    assert r.found is True, r
    assert r.used_llm is False
    assert r.source == "explore", r
    assert r.nav_path
    assert r.nav_path[0]["direction"] == direction


def test_replay_nav_path_helper():
    seen = []
    path = [
        NavStep(kind="tap_tab", tab_text="Matches"),
        human_scroll_gesture("down", rng=__import__("random").Random(0)),
    ]
    replay_nav_path(
        path,
        perform_scroll=lambda s: seen.append(("scroll", s.direction)),
        perform_tap_tab=lambda t: seen.append(("tab", t)),
    )
    assert seen == [("tab", "Matches"), ("scroll", "down")]
