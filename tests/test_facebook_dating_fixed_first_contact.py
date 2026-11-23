"""Facebook Dating first-contact: no free Discover composer; never Crush/Spotlight."""

from __future__ import annotations

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.facebook_dating_fixed_first_contact import (
    DAILY_CAP,
    LIKE_XY,
    plan_facebook_dating_fixed_first_contact,
)


def test_parse_first_contact_facebook_dating():
    g = parse_bulk_goal("send 2 first contact messages on Facebook Dating")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "facebook"
    assert g["first_contact"] is True
    assert DAILY_CAP == 50


def test_profile_like_pass_only_stops_without_taps():
    tree = (
        '<hierarchy><w p="com.facebook.katana" f="1">'
        '<n d="Profile picture, Ellie, 21" c="1"/>'
        '<n d="No, Thanks" c="1" xy="340,2116"/>'
        '<n d="Like" c="1" xy="739,2116"/>'
        '<n t="Liked you"/>'
        "</w></hierarchy>"
    )
    act = plan_bulk_bench(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state={},
        package="com.facebook.katana",
        dry_run=False,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("stopped_reason") == "no_free_first_contact"
    assert (act.get("x"), act.get("y")) != LIKE_XY
    assert not act.get("needs_vision")


def test_explore_does_not_tap_crush_or_spotlight():
    tree = (
        '<hierarchy><w p="com.facebook.katana" f="1">'
        '<n t="Explore"/>'
        '<n t="Spotlight" c="1"/>'
        '<n t="Crush" c="1"/>'
        "</w></hierarchy>"
    )
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state={},
        dry_run=False,
        message="hey how are you",
        target=2,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("stopped_reason") == "no_free_first_contact"
    reason = (act.get("reason") or "").lower()
    assert "spotlight" in reason or "crush" in reason
    assert act.get("x") is None
