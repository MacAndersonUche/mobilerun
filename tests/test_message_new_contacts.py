"""New-contact messaging mode (Hinge / Tagged / Hily + like-only swipe apps)."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_message_new_quoted():
    g = parse_bulk_goal('message "hello miss" to 5 new profiles on Hinge')
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 5
    assert g["message"] == "hello miss"
    assert g["app"] == "hinge"
    assert g["contact_scope"] == "new"


def test_parse_existing_still_message_kind():
    g = parse_bulk_goal('message "hey" to 5 existing chats on Hily')
    assert g is not None
    assert g["kind"] == "message"
    assert g["contact_scope"] == "existing"


def test_hinge_new_dry_run_on_like_sheet():
    tree = (FIX / "hinge_like_sheet.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        'message "hello miss" to 3 new profiles on Hinge',
        tree,
        ["Opened Hinge", "Focus Add a comment field"],
        state={"bulk_message_new": {"done": 0, "typed": True}},
        package="co.hinge.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run") is True
    assert "Rose" in (act.get("reason") or "") or "Send Like" in (
        act.get("reason") or ""
    )


def test_tagged_new_dry_run_on_match_card():
    tree = (FIX / "tagged_match_card.xml").read_text(encoding="utf-8")
    act = plan_bulk_bench(
        'message "hi" to 2 new profiles on Tagged',
        tree,
        ["Opened Tagged"],
        state={},
        package="com.taggedapp",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert "chatBtn" in (act.get("reason") or "")


def test_bumble_new_is_like_only():
    """Swipe apps: new-contact messaging delegates to like/swipe path."""
    g = parse_bulk_goal('message "x" to 2 new profiles on Bumble')
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["app"] == "bumble"
