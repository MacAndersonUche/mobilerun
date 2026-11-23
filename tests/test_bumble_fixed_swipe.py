"""Unit tests for Bumble fixed-spot swipe guard and planner."""

from pathlib import Path

import pytest

from backend.bumble_fixed_swipe import (
    LIKE_SWIPE_REF,
    bumble_fixed_guard,
    bumble_fixed_on_deck,
    bumble_fixed_swipe_enabled,
    plan_bumble_fixed_swipe,
    scale_like_swipe,
    screen_size_from_tree,
    visible_ui_text,
)
from backend.bulk_bench_heuristics import plan_bulk_swipe
from backend.cloud_agent import _bulk_action_is_verified_fastpath

FIXTURES = Path(__file__).parent / "fixtures" / "dm"
KALIA = (FIXTURES / "bumble_people_sparse_kalia.xml").read_text()
PHOTO = (FIXTURES / "bumble_photo_browser_superswipe.xml").read_text()


def _wrap(inner: str) -> str:
    return (
        '<hierarchy windows="1" packages="com.bumble.app">'
        '<w id="active" t="active" p="com.bumble.app" f="1" kids="1">'
        f"{inner}</w></hierarchy>"
    )


def _tabs(selected: str = "people") -> str:
    items = []
    xs = {
        "profile": 108,
        "discover": 324,
        "people": 540,
        "liked you": 756,
        "chats": 972,
    }
    bounds = {
        "profile": "0,2120,216,2274",
        "discover": "216,2120,432,2274",
        "people": "432,2120,648,2274",
        "liked you": "648,2120,864,2274",
        "chats": "864,2120,1080,2274",
    }
    for name, x in xs.items():
        click = ' c="1"' if name != selected else ""
        title = name.title() if name != "liked you" else "Liked You"
        items.append(
            f'<n t="{title}" d="{title}" cls="View"{click} '
            f'xy="{x},2197" b="{bounds[name]}"/>'
        )
    return "".join(items)


def _deck_tree(*extra: str, selected: str = "people") -> str:
    nodes = [
        '<n i="com.bumble.app:id/mainApp_viewPager" cls="ViewPager" s="1" '
        'xy="540,1097" b="0,75,1080,2120"/>',
        '<n d="Filters" i="com.bumble.app:id/toolbar_filter" cls="Button" '
        'c="1" xy="1006,148" b="975,117,1038,180"/>',
        *extra,
        _tabs(selected),
    ]
    return _wrap("".join(nodes))


def test_guard_clean_on_people_sparse_tree():
    assert bumble_fixed_guard(KALIA) is None
    assert bumble_fixed_on_deck(KALIA)
    # Hidden chats promo must not leak into the guard.
    assert "people are waiting" not in visible_ui_text(KALIA).lower()


def test_guard_ignores_deck_superswipe_badge():
    deck = (FIXTURES / "bumble_deck.xml").read_text()
    assert bumble_fixed_guard(deck) is None
    assert bumble_fixed_on_deck(deck)


def test_guard_ignores_bio_get_and_super():
    tree = _deck_tree(
        '<n t="Kalia, 25" cls="TextView" xy="540,1600" b="200,1500,880,1700"/>',
        '<n t="Let\'s get together for dinner" cls="TextView" '
        'xy="540,1750" b="80,1700,1000,1800"/>',
        '<n t="I\'m super outgoing" cls="TextView" '
        'xy="540,1850" b="80,1800,1000,1900"/>',
        '<n t="Buy me a drink sometime" cls="TextView" '
        'xy="540,1950" b="80,1900,1000,2000"/>',
    )
    assert bumble_fixed_guard(tree) is None
    assert bumble_fixed_on_deck(tree)


@pytest.mark.parametrize(
    "label,needle",
    [
        ("SuperSwipe", "superswipe"),
        ("Send SuperSwipe", "superswipe"),
        ("Boost", "boost"),
        ("Premium", "premium"),
        ("Bumble Premium", "premium"),
        ("Spotlight", "spotlight"),
        ("Upgrade", "upgrade"),
        ("Subscribe", "subscribe"),
        ("Get Premium", "get"),
        ("Buy Boost", "buy"),
        ("Super", "super"),
        ("It's a match", "match"),
        ("You matched", "match"),
    ],
)
def test_guard_aborts_on_paid_and_match_words(label, needle):
    tree = _deck_tree(
        f'<n t="{label}" cls="Button" c="1" xy="540,1400" b="200,1300,880,1500"/>',
    )
    hit = bumble_fixed_guard(tree)
    assert hit, f"expected abort for {label!r}"
    assert needle in hit.lower() or needle in (tree.lower())


def test_guard_aborts_photo_browser_superswipe():
    hit = bumble_fixed_guard(PHOTO)
    assert hit and "super" in hit.lower()
    assert not bumble_fixed_on_deck(PHOTO)


def test_not_on_deck_when_chats_or_liked_you_selected():
    chats = _deck_tree(selected="chats")
    liked = _deck_tree(selected="liked you")
    profile = _deck_tree(selected="profile")
    assert not bumble_fixed_on_deck(chats)
    assert not bumble_fixed_on_deck(liked)
    assert not bumble_fixed_on_deck(profile)
    assert bumble_fixed_on_deck(_deck_tree(selected="discover"))


def test_scale_like_swipe_identity_and_1440():
    assert scale_like_swipe(1080, 2400) == LIKE_SWIPE_REF
    x1, y1, x2, y2, dur = scale_like_swipe(1440, 3200)
    assert (x1, y1, x2, y2, dur) == (333, 1333, 1400, 1400, 300)


def test_screen_size_from_kalia_is_s21():
    assert screen_size_from_tree(KALIA) == (1080, 2400)


def test_dry_plan_returns_coords_and_does_not_swipe():
    act = plan_bumble_fixed_swipe(
        "like 5 profiles on Bumble (fixed)",
        KALIA,
        [],
        state={"bulk_swipe": {"done": 0, "target": 5}},
        package="com.bumble.app",
        dry_run=True,
    )
    assert act is not None
    assert act["action"] == "done"
    assert act["dry_run_verified"] is True
    assert act["action"] != "swipe"
    assert "no swipe" in act["reason"]
    swipe = act["like_swipe"]
    assert swipe["x1"] == 250 and swipe["x2"] == 1050
    assert _bulk_action_is_verified_fastpath(act)


def test_live_plan_swipes_right_and_caps_at_five():
    st = {"bulk_swipe": {"done": 0, "target": 20}}
    act = plan_bumble_fixed_swipe(
        "like 20 profiles on Bumble (fixed)",
        KALIA,
        [],
        state=st,
        package="com.bumble.app",
        dry_run=False,
        live_test_max_n=5,
    )
    assert act is not None
    assert act["action"] == "swipe"
    assert act["x1"] == 250 and act["x2"] == 1050
    assert act["y1"] == 1000 and act["y2"] == 1050
    assert "1/5" in act["reason"]
    assert act["planner"] == "bumble_fixed"
    assert _bulk_action_is_verified_fastpath(act)

    # After the swipe, a still-clean deck counts + issues the next swipe.
    act2 = plan_bumble_fixed_swipe(
        "like 20 profiles on Bumble (fixed)",
        KALIA,
        [act["reason"]],
        state=st,
        package="com.bumble.app",
        dry_run=False,
        live_test_max_n=5,
    )
    assert st["bulk_swipe"]["done"] == 1
    assert act2["action"] == "swipe"
    assert "2/5" in act2["reason"]


def test_guard_fail_does_not_tap():
    tree = _deck_tree(
        '<n t="Bumble Premium" cls="Button" c="1" xy="540,1400" '
        'b="200,1300,880,1500"/>',
    )
    act = plan_bumble_fixed_swipe(
        "like 5 profiles on Bumble (fixed)",
        tree,
        [],
        state={"bulk_swipe": {"done": 0, "target": 5}},
        dry_run=False,
    )
    assert act["action"] == "fail"
    assert "no tap" in act["reason"].lower() or "aborted" in act["reason"].lower()
    assert act.get("x") is None and act.get("x1") is None


def test_not_on_deck_backs_once_then_stops():
    tree = _deck_tree(selected="chats")
    st = {"bulk_swipe": {"done": 0, "target": 5}}
    first = plan_bumble_fixed_swipe(
        "like 5 profiles on Bumble (fixed)",
        tree,
        [],
        state=st,
        dry_run=False,
    )
    assert first["action"] == "press_button" and first["button"] == "back"
    second = plan_bumble_fixed_swipe(
        "like 5 profiles on Bumble (fixed)",
        tree,
        [first["reason"]],
        state=st,
        dry_run=False,
    )
    assert second["action"] == "fail"
    assert "still not" in second["reason"].lower()


def test_plan_bulk_swipe_uses_fixed_branch():
    act = plan_bulk_swipe(
        "like 5 profiles on Bumble (fixed)",
        KALIA,
        [],
        state={"bulk_swipe": {"done": 0, "target": 5}},
        package="com.bumble.app",
        dry_run=True,
    )
    assert act is not None
    assert act["planner"] == "bumble_fixed"
    assert act["action"] == "done"
    assert act["dry_run_verified"] is True


def test_enabled_by_instruction_or_state():
    assert bumble_fixed_swipe_enabled("like 5 on Bumble (fixed)")
    assert bumble_fixed_swipe_enabled("like 5 on Bumble", {"swipe_mode": "fixed"})
    # Opt-in: a normal Bumble like job stays on the existing heuristic path.
    assert not bumble_fixed_swipe_enabled("like 5 profiles on Bumble", {})
    assert bumble_fixed_swipe_enabled(
        "like 5 profiles on Bumble", {"bulk_swipe": {"mode": "fixed"}}
    )
