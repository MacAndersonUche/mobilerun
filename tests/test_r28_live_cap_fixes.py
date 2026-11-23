"""r28: live like cap by control class, cancel, sticky handoff, dry verified, unsupported."""

from __future__ import annotations

import os

import pytest

from backend.cloud_agent import (
    LIVE_TEST_DEFAULT_MAX_N,
    _action_is_billing_or_terms_tap,
    _action_is_like_control,
    _action_is_pass_control,
    _dry_run_done_is_verified,
    _instruction_is_like_or_swipe_job,
    apply_like_job_no_type_guard,
    apply_live_test_guard,
    plan_next_action,
    refresh_job_cancel_status,
    unsupported_app_fail_action,
    verify_pending_live_like,
)
from backend.bulk_bench_heuristics import (
    _card_name_is_owner,
    _card_name_is_real_profile,
    _fg_pkg_matches_target,
    _visible_chat_list_rows,
    plan_bulk_bench,
)
from backend.dating_deck import (
    is_yubo_reactions_or_elite_paywall,
    yubo_paywall_back_action,
)


# --- 1. Like cap by control class, not reason text ---


def test_liking_reason_alone_does_not_count_as_like():
    """LLM reason 'Liking' must NOT trip the cap (Badoo ~25 likes bug)."""
    assert not _action_is_like_control(
        {"action": "tap", "x": 100, "y": 200, "reason": "Liking profile"},
        "tap",
    )
    st: dict = {"live_likes_done": 0, "live_likes_issued": 0, "live_test_max_n": 5}
    kind, reason, action = apply_live_test_guard(
        live_test=True,
        action={"action": "tap", "x": 100, "y": 200, "reason": "Liking"},
        kind="tap",
        reason="Liking",
        state=st,
        max_n=5,
    )
    assert kind == "tap"
    assert st.get("live_likes_issued", 0) == 0
    assert st.get("live_likes_done", 0) == 0


def test_like_control_label_counts_and_caps_before_execute():
    st: dict = {"live_likes_done": 0, "live_likes_issued": 0, "live_test_max_n": 2}
    kind, reason, action = apply_live_test_guard(
        live_test=True,
        action={
            "action": "tap",
            "x": 800,
            "y": 1800,
            "label": "Like",
            "reason": "whatever",
        },
        kind="tap",
        reason="whatever",
        state=st,
        max_n=2,
    )
    assert kind == "tap"
    assert st["live_likes_issued"] == 1
    assert st.get("_pending_live_like") is True
    # done stays 0 until card-name verify
    assert st.get("live_likes_done", 0) == 0

    st["live_likes_issued"] = 2
    kind2, reason2, _ = apply_live_test_guard(
        live_test=True,
        action={"action": "tap", "label": "Like", "x": 800, "y": 1800},
        kind="tap",
        reason="Like",
        state=st,
        max_n=2,
    )
    assert kind2 == "done"
    assert "cap" in reason2.lower()


def test_like_id_token_is_like_control():
    assert _action_is_like_control(
        {"action": "tap", "id": "encounters_profile_voting_buttonVoteYes", "x": 1, "y": 2},
        "tap",
    )
    assert _action_is_like_control(
        {"action": "swipe", "x1": 200, "y1": 1400, "x2": 900, "y2": 1400},
        "swipe",
    )


# --- 2. Never pass in like jobs ---


def test_pass_blocked_in_like_job():
    st: dict = {"live_likes_done": 0, "live_test_max_n": 5}
    kind, reason, action = apply_live_test_guard(
        live_test=True,
        action={"action": "tap", "label": "X", "x": 120, "y": 1900, "reason": "Like"},
        kind="tap",
        reason="Like",
        state=st,
        max_n=5,
        like_job=True,
    )
    assert kind == "wait"
    assert action.get("live_test_blocked_pass") is True
    assert _action_is_pass_control(
        {"action": "tap", "label": "X", "x": 100, "y": 1800}, "tap"
    )
    assert _action_is_pass_control(
        {"action": "tap", "x": 200, "y": 1900}, "tap"
    )  # BLK bottom-left zone


# --- 3. Yubo paywall / billing terms ---


def test_yubo_elite_pack_backs_out():
    tree = '<n t="Elite Pack" xy="100,100"/><n t="See who added you" xy="200,200"/>'
    assert is_yubo_reactions_or_elite_paywall(tree)
    act = yubo_paywall_back_action(tree)
    assert act and act.get("action") == "press_button"
    assert act.get("button") == "back"


def test_billing_terms_tap_blocked():
    assert _action_is_billing_or_terms_tap(
        {
            "action": "tap",
            "label": "Recurring billing. Terms of service apply.",
            "x": 50,
            "y": 2200,
        },
        "tap",
    )


# --- 4. Cancel honour ---


def test_cancel_status_never_overwritten(monkeypatch):
    job = {"job_id": "j1", "status": "running", "state": {}}

    def fake_get(jid):
        return {"job_id": jid, "status": "stopped"}

    monkeypatch.setattr("backend.storage.get_job", fake_get)
    # Also patch the import path cloud_agent uses
    import backend.cloud_agent as ca

    monkeypatch.setattr(ca, "refresh_job_cancel_status", ca.refresh_job_cancel_status)
    # Direct: simulate storage returning stopped
    import backend.storage as storage

    monkeypatch.setattr(storage, "get_job", fake_get)
    assert refresh_job_cancel_status(job) is True
    assert job["status"] == "stopped"


# --- 5. No typing in like/swipe ---


def test_like_job_blocks_type_rewrites_to_open_app():
    kind, reason, action = apply_like_job_no_type_guard(
        action={"action": "type", "text": "Hily", "reason": "Search for Hily"},
        kind="type",
        reason="Search for Hily",
        instruction="hily like 5 profiles",
        job={"live_test": True},
        package="com.sec.android.app.launcher",
    )
    assert kind == "open_app"
    assert "hily" in str(action.get("app") or "").lower()
    assert _instruction_is_like_or_swipe_job("badoo like 5 profiles", {"live_test": True})


# --- 6. Verify like by card name change ---


def test_live_like_verified_only_on_card_change(monkeypatch):
    st: dict = {
        "_pending_live_like": True,
        "_live_like_before_name": "Alice",
        "live_likes_done": 0,
        "live_likes_issued": 1,
        "bulk_swipe": {"last_name": "Alice"},
    }

    def fake_deck(app, tree):
        return "Bob" if "bob" in (tree or "").lower() else "Alice"

    monkeypatch.setattr(
        "backend.bulk_bench_heuristics.deck_card_name", fake_deck
    )
    monkeypatch.setattr(
        "backend.bulk_bench_heuristics._card_name_is_real_profile",
        lambda n: bool(n),
    )
    ok = verify_pending_live_like(st, ui_tree="bob card", app="badoo")
    assert ok is True
    assert st["live_likes_done"] == 1

    st2: dict = {
        "_pending_live_like": True,
        "_live_like_before_name": "Alice",
        "live_likes_done": 0,
        "live_likes_issued": 1,
    }
    monkeypatch.setattr(
        "backend.bulk_bench_heuristics.deck_card_name",
        lambda app, tree: "Alice",
    )
    ok2 = verify_pending_live_like(st2, ui_tree="same", app="badoo")
    assert ok2 is False
    assert st2.get("live_likes_done", 0) == 0


# --- 7. Dry verified editable + distinct chats ---


def test_confirmed_editable_sets_dry_verified_and_counts_chat():
    st: dict = {"bulk_message": {"done": 0, "done_names": [], "target": 3}}
    assert _dry_run_done_is_verified(
        {"action": "done"},
        "[DRY RUN] confirmed editable input for Tosin",
        st,
        instruction='bumble reply "hi" to 3 existing chats',
    )
    assert st.get("dry_run_verified") is True
    assert "Tosin" in (st.get("bulk_message") or {}).get("done_names", [])


def test_identified_card_not_verified_for_messaging():
    st: dict = {"bulk_message_new": {"done": 0, "target": 3}}
    assert not _dry_run_done_is_verified(
        {"action": "done"},
        "[DRY RUN] identified card Hannah; would like/pass",
        st,
        instruction='tagged message "hi" to 3 new profiles',
    )


# --- 8. False card names / owner / pkg ---


def test_reject_social_chats_owner_names():
    assert not _card_name_is_real_profile("Social")
    assert not _card_name_is_real_profile("Chats")
    assert _card_name_is_owner("MacAnderson, 30")
    assert not _card_name_is_real_profile("MacAnderson, 30")
    assert _fg_pkg_matches_target("badoo", "com.badoo.mobile")
    assert not _fg_pkg_matches_target("badoo", "com.sec.android.app.launcher")


# --- 9. Skip reply-paywall rows ---


def test_skip_added_you_and_liked_you_rows():
    tree = """
    <n t="ADDED YOU" xy="100,400"/>
    <n t="Daisy" xy="100,450"/>
    <n t="They liked you" xy="100,600"/>
    <n t="Paige" xy="100,650"/>
    <n t="Send a message" xy="100,800"/>
    <n t="RealChat" xy="120,900" id="chat_row"/>
    """
    # Minimal: ensure ADDED YOU / They liked you labels themselves are skipped
    rows = _visible_chat_list_rows(tree, "yubo", skip_names=[])
    names = [r.get("name") or r.get("label") for r in (rows or [])]
    low = " ".join(str(n).lower() for n in names)
    assert "added you" not in low
    assert "they liked you" not in low
    assert "send a message" not in low


# --- 10. Sticky LLM handoff ---


def test_sticky_llm_handoff_skips_heuristics(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return {"action": "tap", "x": 1, "y": 2, "reason": "should not run"}

    monkeypatch.setattr(
        "backend.bulk_bench_heuristics.plan_bulk_bench", boom
    )
    st: dict = {"_bulk_llm_handoff": True, "bulk_swipe": {"done": 0, "target": 5}}
    # With handoff + no visible name, plan should not call heuristics
    # (may fall through to LLM which needs keys — expect handoff wait or None/LLM)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    try:
        act = plan_next_action(
            "badoo like 5 profiles",
            "<n t='People' xy='100,100'/>",
            ["Opened Badoo"],
            dry_run=False,
            agent_state=st,
            package="com.badoo.mobile",
        )
    except Exception:
        act = None
    assert called["n"] == 0
    assert st.get("_bulk_llm_handoff") is True


# --- 11. Taimi / Hinge unsupported fail-fast ---


def test_taimi_hinge_unsupported_fail_fast():
    a = unsupported_app_fail_action("taimi like 5 profiles")
    assert a and a.get("action") == "fail"
    assert "unsupported" in (a.get("reason") or "").lower() or "FLAG_SECURE" in (
        a.get("reason") or ""
    )
    b = unsupported_app_fail_action("hinge auto-swipe 5 profiles")
    assert b and b.get("action") == "fail"

    act = plan_bulk_bench(
        "taimi like 3 profiles",
        "",
        [],
        dry_run=True,
    )
    assert act and act.get("action") == "fail"
    assert act.get("unsupported_app") == "taimi" or "unsupported" in (
        act.get("reason") or ""
    ).lower() or "FLAG_SECURE" in (act.get("reason") or "")
