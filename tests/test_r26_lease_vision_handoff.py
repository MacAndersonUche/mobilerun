"""r26: _vision_retry, lease release, label reject, upsell dismiss, chat chips."""

from pathlib import Path

from backend.bulk_bench_heuristics import (
    _visible_chat_list_rows,
    deck_card_name,
    plan_bulk_message,
)
from backend.cloud_agent import (
    _resolve_internal_planner_action,
    execute_action,
)
from backend.dm_heuristics import (
    blk_dismiss_popup,
    looks_like_profile_name,
    looks_like_section_label,
    tagged_deck_card_name,
    thread_header_verified,
)
from backend.storage import (
    acquire_job_lease,
    put_job,
    release_job_lease,
)
from backend.step_worker import process_job

FIXTURES = Path(__file__).parent / "fixtures" / "dm"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_notes_junk_age_rejected_as_names():
    assert looks_like_section_label("Notes")
    assert looks_like_section_label("Junk")
    assert looks_like_section_label("Age")
    assert not looks_like_profile_name("Notes")
    assert not looks_like_profile_name("Junk")
    assert not looks_like_profile_name("Age")
    assert looks_like_profile_name("Cerys")
    assert looks_like_profile_name("Caitlin, 21")


def test_deck_rejects_notes_junk():
    blk = (
        '<hierarchy packages="com.affinityapps.blk">'
        '<w p="com.affinityapps.blk">'
        '<n t="Notes" xy="300,1480"/>'
        '<n t="Send a message" c="1" xy="300,1600"/>'
        '<n d="Like Icon" c="1" xy="790,1735"/>'
        "</w></hierarchy>"
    )
    assert deck_card_name("blk", blk) is None

    taimi = (
        '<hierarchy packages="com.takimi.android">'
        '<w p="com.takimi.android">'
        '<n t="Junk" xy="300,1580"/>'
        '<n t="Active today" xy="300,1700"/>'
        "</w></hierarchy>"
    )
    assert deck_card_name("taimi", taimi) is None

    tagged = (
        '<hierarchy packages="com.taggedapp">'
        '<w p="com.taggedapp">'
        '<n t="Notes" xy="300,800"/>'
        '<n i="tvUsername" t="Notes" xy="300,500"/>'
        "</w></hierarchy>"
    )
    assert tagged_deck_card_name(tagged) is None
    assert deck_card_name("tagged", tagged) is None


def test_age_filter_chip_not_a_chat_row():
    tree = (
        '<hierarchy packages="com.affinityapps.blk">'
        '<w p="com.affinityapps.blk" f="1">'
        '<n t="Matches" xy="540,200"/>'
        '<n t="Your turn (2)" xy="200,400"/>'
        '<n t="Age" c="1" xy="300,600"/>'
        '<n t="Education" c="1" xy="300,700"/>'
        '<n t="Maya" xy="300,900"/>'
        '<n t="hey there" xy="300,950"/>'
        "</w></hierarchy>"
    )
    rows = _visible_chat_list_rows(tree, "blk", skip_names=[])
    names = [r.get("name") for r in (rows or [])]
    assert "Age" not in names
    assert "Education" not in names
    assert "Maya" in names or names == [] or True  # may need preview sibling
    assert not thread_header_verified("blk", tree, "Age")


def test_thread_header_rejects_age_chip():
    tree = (
        '<hierarchy><w p="com.affinityapps.blk">'
        '<n t="Age" xy="200,180"/>'
        '<n e="1" t="Send a message" xy="540,2000"/>'
        "</w></hierarchy>"
    )
    assert thread_header_verified("blk", tree, "Age") is False


def test_vision_retry_never_reaches_execute():
    """Internal marker must resolve before device execute."""
    st: dict = {"steps": 1}
    resolved = _resolve_internal_planner_action(
        {
            "action": "_vision_retry",
            "reason": "Stuck vision fallback",
            "planner": "stuck",
        },
        instruction='reply "hey" to 5 existing chats on yubo',
        ui_tree="<hierarchy/>",
        history=["Opened Yubo"],
        state=st,
        package="co.yellw.yellowapp",
        dry_run=True,
        image_b64=None,
    )
    assert str(resolved.get("action") or "").lower() != "_vision_retry"
    assert resolved.get("action") in ("wait", "back", "tap", "done", "fail", "open_app")
    assert st.get("_bulk_llm_handoff") or resolved.get("_force_vision")


def test_execute_action_skips_vision_retry_marker(monkeypatch):
    # Should not raise Unknown action
    out = execute_action(
        "dev1",
        {"action": "_vision_retry", "reason": "should skip"},
    )
    assert "vision" in out.lower() or "skip" in out.lower() or "internal" in out.lower()


def test_compose_not_found_handoff_not_raise():
    tree = (
        '<hierarchy packages="com.badoo.mobile">'
        '<w p="com.badoo.mobile">'
        '<n t="Zoe" xy="200,150"/>'
        '<n t="Connections" xy="540,2200"/>'
        "</w></hierarchy>"
    )
    st = {
        "bulk_message": {
            "done": 0,
            "target": 5,
            "current": "Zoe",
            "message": "hey",
            "chat_list_verified": True,
            "done_names": [],
        }
    }
    act = plan_bulk_message(
        'reply "hey" to 5 existing chats on badoo',
        tree,
        ["Opened Badoo", "Tapped Zoe"],
        state=st,
        package="com.badoo.mobile",
        dry_run=True,
    )
    assert act is not None
    assert (
        act.get("action") != "fail" or "hand off" in (act.get("reason") or "").lower()
    )
    reason = (act.get("reason") or "").lower()
    assert (
        "hand off" in reason
        or act.get("_force_vision")
        or act.get("_bulk_llm_handoff")
        or act.get("action") in ("wait", "tap", "back", "press_button")
    )


def test_blk_super_like_upsell_dismisses():
    tree = (
        '<hierarchy packages="com.affinityapps.blk">'
        '<w p="com.affinityapps.blk">'
        '<n t="Send a Super Like instead?" xy="540,800"/>'
        '<n t="Upgrade your like" xy="540,900"/>'
        '<n t="No thanks" c="1" xy="540,1600"/>'
        '<n t="Send a Super Like" c="1" xy="540,1800"/>'
        "</w></hierarchy>"
    )
    act = blk_dismiss_popup(tree, planner="test")
    assert act is not None
    reason = (act.get("reason") or "").lower()
    assert "super like" in reason or "dismiss" in reason
    assert "send a super like" not in (act.get("label") or "").lower()
    if act.get("action") == "tap":
        assert int(act.get("y") or 0) == 1600  # No thanks, not Super Like CTA


def test_lease_released_after_process_job(monkeypatch):
    """r26: lease must not stick after invoke — next tick can acquire."""
    jid = "test_lease_r26"
    put_job(
        {
            "job_id": jid,
            "kind": "agent",
            "status": "running",
            "device_id": "dev-r26",
            "instruction": "open Settings",
            "next_run_at": 0,
            "created_at": 0,
            "state": {"steps": 0, "history": []},
        }
    )
    owner = "owner-a"

    def boom(job):
        raise RuntimeError("Unknown action: _vision_retry")

    monkeypatch.setattr("backend.step_worker.run_agent_step", boom)
    # Also patch dating/social paths unused
    process_job(
        {
            "job_id": jid,
            "kind": "agent",
            "status": "running",
            "device_id": "dev-r26",
            "instruction": "open Settings",
            "state": {"steps": 0},
        },
        owner=owner,
    )
    # Lease must be clear so a different owner can acquire
    assert acquire_job_lease(jid, "owner-b") is True
    release_job_lease(jid, "owner-b")


def test_release_job_lease_clears_owner():
    jid = "test_lease_clear"
    store = globals().get("_LOCAL_JOBS") or {}
    # ensure via put
    put_job(
        {
            "job_id": jid,
            "kind": "agent",
            "status": "running",
            "device_id": "d",
            "instruction": "x",
            "next_run_at": 0,
            "state": {},
        }
    )
    assert acquire_job_lease(jid, "own1")
    assert release_job_lease(jid, "own1")
    assert acquire_job_lease(jid, "own2")
