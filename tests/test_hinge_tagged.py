"""Hinge + Tagged detectors from Mac's 22 Nov mapping / scaffolds."""

from __future__ import annotations

from pathlib import Path

from backend.dm_heuristics import (
    DM_APP_PROFILES,
    hinge_deck_card_name,
    hinge_dismiss_enable_prompt,
    hinge_find_match_row,
    hinge_find_send_a_message,
    hinge_on_discover,
    hinge_on_matches,
    hinge_on_thread,
    hinge_open_discover_tab,
    hinge_open_matches_tab,
    tagged_deck_card_name,
    tagged_on_deck,
)
from backend.bulk_bench_heuristics import deck_card_name, plan_bulk_swipe, _deck_visible
from backend.cloud_agent import _action_looks_like_paid, apply_dry_run_send_guard

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_hinge_profile_nav_xy_and_never_tap():
    p = DM_APP_PROFILES["hinge"]
    assert p["package"] == "co.hinge.app"
    assert p["deck_tab_xy"] == (110, 2195)
    assert p["inbox_tab_xy"] == (754, 2195)
    labels = " ".join(p["never_tap_labels"]).lower()
    for bad in ("rose", "boost", "preferred", "hingex", "enable for"):
        assert bad in labels


def test_tagged_scaffold_profile():
    p = DM_APP_PROFILES["tagged"]
    assert p["package"] == "com.taggedapp"
    assert "tagged_like" in " ".join(p["like_ids"])


def test_hinge_discover_send_message_not_rose():
    tree = _load("hinge_discover_send_message.xml")
    assert hinge_on_discover(tree)
    assert not hinge_on_matches(tree)
    assert hinge_deck_card_name(tree) == "Alex"
    cta = hinge_find_send_a_message(tree)
    assert cta is not None
    assert cta[1] > 1900


def test_hinge_matches_skips_hidden():
    tree = _load("hinge_matches_your_turn.xml")
    assert hinge_on_matches(tree)
    assert not hinge_on_discover(tree)
    sam = hinge_find_match_row(tree, "Sam")
    assert sam is not None
    # Riley is under Hidden — must not match
    assert hinge_find_match_row(tree, "Riley") is None


def test_hinge_dismiss_enable_for_never_enable():
    tree = _load("hinge_enable_for_prompt.xml")
    act = hinge_dismiss_enable_prompt(tree)
    assert act is not None
    assert act["action"] == "tap"
    assert act["x"] == 985
    assert "Enable" not in (act.get("reason") or "") or "Dismiss" in act["reason"]


def test_hinge_nav_tab_actions():
    d = hinge_open_discover_tab()
    assert d["x"] == 110 and d["y"] == 2195
    m = hinge_open_matches_tab()
    assert m["x"] == 754 and m["y"] == 2195


def test_hinge_thread_only_edittext():
    tree = """
    <hierarchy><w p="co.hinge.app" a="1">
      <n t="Sam" xy="540,200" b="[200,160][880,240]" />
      <n e="1" xy="400,2200" b="[80,2140][900,2260]" h="Message" />
      <n t="Send" xy="980,2200" b="[920,2140][1060,2260]" c="1" />
    </w></hierarchy>
    """
    assert hinge_on_thread(tree)
    assert not hinge_on_matches(tree)


def test_tagged_deck_scaffold():
    tree = _load("tagged_deck_scaffold.xml")
    assert tagged_on_deck(tree)
    assert tagged_deck_card_name(tree) == "Morgan"
    assert _deck_visible("tagged", tree)
    assert deck_card_name("tagged", tree) == "Morgan"


def test_hinge_dry_run_bulk_verifies_once():
    tree = _load("hinge_discover_send_message.xml")
    st: dict = {}
    act = plan_bulk_swipe(
        "hinge like 5 profiles",
        tree,
        ["Opened Hinge"],
        state=st,
        package="co.hinge.app",
        dry_run=True,
    )
    assert act is not None
    # r22: multi-card dry-run — advance or wait, never premature one-card done
    if act.get("action") == "done":
        assert act.get("dry_run_verified") is True
        assert "Alex" in (act.get("reason") or "")
    else:
        assert act.get("_dry_run_advance") or act.get("action") in (
            "swipe",
            "tap",
            "wait",
            "press_button",
        )
        assert "Alex" in (act.get("reason") or "") or st.get("bulk_swipe", {}).get(
            "done"
        )


def test_paid_guard_blocks_rose_and_hingex():
    for label in ("Rose", "Send a Rose", "Preferred", "HingeX", "Boost"):
        assert _action_looks_like_paid({"label": label, "action": "tap"}, "tap")
    kind, reason, act = apply_dry_run_send_guard(
        dry_run=True,
        action={"action": "tap", "x": 1, "y": 2, "label": "Rose"},
        kind="tap",
        reason="would rose",
    )
    assert act["action"] == "done"
    assert "paid" in reason.lower() or "DRY RUN" in reason
