"""r24: stall→LLM handoff, SoM tree, section-label card name rejection."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    deck_card_name,
    plan_bulk_swipe,
)
from backend.cloud_agent import (
    BULK_DRY_RUN_LLM_HINT,
    _bulk_action_is_verified_fastpath,
    _bulk_progress_signature,
    _som_indexed_tree,
    plan_next_action,
)
from backend.dm_heuristics import (
    blk_deck_card_name,
    looks_like_profile_name,
    looks_like_section_label,
    taimi_deck_card_name,
)
from backend.step_worker import JOB_WALL_S as STEP_JOB_WALL_S

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_job_wall_raised_for_llm_room():
    """r24: 180s killed every reply/new — need ≥600s for LLM fallback."""
    from backend import step_worker as sw
    from backend import cloud_agent as ca

    assert int(STEP_JOB_WALL_S) >= 600
    assert int(sw.JOB_WALL_S) >= 600
    # cloud_agent TASK timeout still longer than job wall
    assert int(getattr(ca, "TASK_TIMEOUT_S", 900)) >= 600


def test_section_labels_rejected():
    assert looks_like_section_label("Intentions")
    assert looks_like_section_label("Health and Fitness")
    assert looks_like_section_label("Education")
    assert not looks_like_section_label("Aaliyah, 29")
    assert looks_like_profile_name("Aaliyah, 29")
    assert looks_like_profile_name("Maya")
    assert not looks_like_profile_name("Intentions")
    assert not looks_like_profile_name("Health and Fitness")


def test_blk_rejects_intentions_fixture():
    tree = _load("blk_intentions_section.xml")
    assert blk_deck_card_name(tree) is None
    assert deck_card_name("blk", tree) is None


def test_blk_prefers_name_age_over_intentions():
    tree = _load("blk_name_age_card.xml")
    name = blk_deck_card_name(tree)
    assert name and name.lower().startswith("aaliyah")
    assert deck_card_name("blk", tree) == name


def test_taimi_rejects_health_and_fitness_fixture():
    tree = _load("taimi_health_fitness_section.xml")
    assert taimi_deck_card_name(tree) is None
    assert deck_card_name("taimi", tree) is None


def test_dry_swipe_rejects_section_label_forces_vision():
    tree = _load("blk_intentions_section.xml")
    st: dict = {"bulk_swipe": {"done": 0, "target": 1, "_dry_vscroll_done": True}}
    act = plan_bulk_swipe(
        "blk auto-swipe 1 profile",
        tree,
        ["Opened BLK — launch"],
        package="com.affinityapps.blk",
        dry_run=True,
        state=st,
    )
    assert act is not None
    # Must not pass with Intentions as the card name
    reason = (act.get("reason") or "").lower()
    assert (
        "intentions" not in reason or "reject" in reason or act.get("action") != "done"
    )
    if act.get("action") == "done":
        assert act.get("dry_run_verified") is not True or "intentions" not in reason
    else:
        assert (
            act.get("needs_vision")
            or act.get("_force_vision")
            or act.get("action") in ("fail", "wait", "back", "tap")
        )


def test_dry_swipe_accepts_real_name_n1():
    tree = _load("blk_name_age_card.xml")
    st: dict = {"bulk_swipe": {"done": 0, "target": 5, "_dry_vscroll_done": True}}
    act = plan_bulk_swipe(
        "blk auto-swipe 5 profiles",
        tree,
        ["Opened BLK — launch"],
        package="com.affinityapps.blk",
        dry_run=True,
        state=st,
    )
    assert act and act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    reason = (act.get("reason") or "").lower()
    assert "aaliyah" in reason
    assert "intentions" not in reason.split("evaluated")[0] or "aaliyah" in reason


def test_som_indexed_tree_lists_tap_targets():
    tree = _load("blk_name_age_card.xml")
    som = _som_indexed_tree(tree)
    assert "SET-OF-MARKS" in som
    assert "[0]" in som
    assert "Send a message" in som or "send a message" in som.lower()


def test_verified_fastpath_never_blocked():
    assert _bulk_action_is_verified_fastpath(
        {
            "action": "done",
            "dry_run_verified": True,
            "reason": "evaluated 1 card (Maya); would like/pass 5",
        }
    )
    assert _bulk_action_is_verified_fastpath(
        {
            "action": "done",
            "stopped_reason": "nothing_to_reply",
            "reason": "nothing to reply",
        }
    )
    assert _bulk_action_is_verified_fastpath(
        {"action": "open_app", "app": "Bumble", "reason": "launch"}
    )
    assert not _bulk_action_is_verified_fastpath(
        {"action": "wait", "reason": "settle", "seconds": 1}
    )


def test_stall_handoff_after_two_no_progress(monkeypatch):
    """After 2 heuristic steps with no verified progress → LLM (vision) handoff."""
    tree = (
        '<hierarchy packages="com.bumble.app">'
        '<w p="com.bumble.app" f="1">'
        '<n t="People" xy="540,400"/>'
        '<n t="Filters" xy="900,200"/>'
        "</w></hierarchy>"
    )
    st: dict = {
        "bulk_swipe": {"done": 0, "target": 5, "done_names": []},
        "bulk_stall_n": 0,
    }
    # Stub LLM so fallthrough doesn't need API keys when handoff+image
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "backend.cloud_agent._call_openai",
        lambda user, image_b64=None: (
            '{"action":"back","reason":"LLM navigating away from filters"}'
        ),
    )

    # Step 1: recover reopen is NOT verified fastpath → stall increments
    a1 = plan_next_action(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble — launch"],
        dry_run=True,
        agent_state=st,
        package="com.bumble.app",
    )
    assert a1 is not None
    assert (
        not _bulk_action_is_verified_fastpath(a1)
        or int(st.get("bulk_stall_n") or 0) >= 1
    )
    assert int(st.get("bulk_stall_n") or 0) >= 1

    # Step 2 without image: stall≥2 → wait + force vision handoff
    a2 = plan_next_action(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble — launch", str(a1.get("reason") or "step1")],
        dry_run=True,
        agent_state=st,
        package="com.bumble.app",
    )
    assert a2 is not None
    assert int(st.get("bulk_stall_n") or 0) >= 2
    assert (
        a2.get("planner") == "bulk_llm_handoff"
        or a2.get("_bulk_llm_handoff")
        or a2.get("needs_vision")
        or a2.get("_force_vision")
        or st.get("_bulk_llm_handoff")
    )

    # Step 3 with screenshot: fall through to LLM SoM loop
    a3 = plan_next_action(
        "bumble auto-swipe 5 profiles",
        tree,
        ["Opened Bumble — launch", "stall"],
        image_b64="aGVsbG8=",  # tiny fake jpeg bytes as b64
        dry_run=True,
        agent_state=st,
        package="com.bumble.app",
    )
    assert a3 is not None
    # LLM fallthrough or handoff wait both OK — never stuck heuristic loop
    assert a3.get("planner") in ("llm", "bulk_llm_handoff") or a3.get("action") in (
        "back",
        "wait",
        "done",
        "tap",
    )
    assert BULK_DRY_RUN_LLM_HINT.strip()
    assert st.get("_bulk_llm_handoff") or a3.get("planner") in (
        "llm",
        "bulk_llm_handoff",
    )


def test_progress_signature_tracks_done_names():
    st = {
        "bulk_swipe": {
            "done": 1,
            "done_names": ["Maya"],
            "dry_run_verified": True,
            "last_name": "Maya",
        }
    }
    sig = _bulk_progress_signature(st)
    assert sig and sig[0] == "bulk_swipe" and sig[1] == 1
    assert "Maya" in sig[2]
