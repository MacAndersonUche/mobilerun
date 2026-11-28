"""r45: Yubo Blast/text fixes, device-lock deadlock, Stop sweep."""

import time
from pathlib import Path

import pytest

from backend import storage as storage_mod
from backend.cloud_agent import _fixed_swipe_run, _is_fixed_swipe_action
from backend.dating_run import running_dating_jobs
from backend.dm_heuristics import yubo_direct_sheet_action
from backend.message_text_guard import extract_user_message_text
from backend.yubo_fixed_first_contact import (
    blast_selected,
    plan_yubo_fixed_first_contact,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
BLAST = (FIX / "yubo_blast_sheet_r45.xml").read_text(encoding="utf-8")
HELLO = (FIX / "yubo_say_hello.xml").read_text(encoding="utf-8")
INST = "send 5 first contact messages on yubo"


# ---- message text -------------------------------------------------------


def test_instruction_is_not_message_text():
    # Yubo typed "5 first contact messages on yubo" on 24 Nov 01:49
    assert extract_user_message_text(INST) is None
    assert extract_user_message_text("send 2 first contact messages on hinge") is None


def test_real_user_text_still_extracted():
    assert (
        extract_user_message_text("message Amy and say Goodnight baby")
        == "Goodnight baby"
    )


# ---- Yubo Blast sheet ---------------------------------------------------


def test_blast_sheet_detected():
    assert blast_selected(BLAST)
    assert not blast_selected(HELLO)


def test_heuristic_selects_direct_on_real_blast_sheet():
    act = yubo_direct_sheet_action(BLAST, planner="t")
    assert act and act["action"] == "tap"
    assert 737 <= act["x"] <= 973 and 508 <= act["y"] <= 802


def _plan(tree, st, hist=None):
    return plan_yubo_fixed_first_contact(
        INST,
        tree,
        hist or ["Opened Yubo"],
        state=st,
        dry_run=False,
        message="hey how are you",
        target=5,
    )


def test_fixed_planner_taps_direct_never_send_on_blast():
    st = {"bulk_message_new": {"done": 0, "typed": True}}
    act = _plan(BLAST, st)
    assert act["action"] == "tap"
    assert 737 <= act["x"] <= 973, act  # Direct tile, not send (986,1335)
    assert act.get("_no_llm_handoff") or "no_llm_handoff" in act["planner"]


def test_blast_that_wont_switch_stops_without_sending():
    st = {"bulk_message_new": {"done": 0, "typed": True}}
    acts = [_plan(BLAST, st) for _ in range(4)]
    assert all(a["action"] == "tap" and a["x"] < 980 for a in acts[:3])
    assert acts[3]["action"] == "fail"
    assert "nothing sent" in acts[3]["reason"]


def test_send_not_counted_until_box_clears_then_retry_then_fail():
    hello_typed = HELLO.replace('t="" h="Aa"', 't="hey how are you" h="Aa"')
    assert hello_typed != HELLO
    st = {
        "bulk_message_new": {
            "done": 0,
            "typed": True,
            "awaiting_sent": "hey how are you",
        }
    }
    a1 = _plan(hello_typed, st)
    assert a1["action"] == "tap" and "again" in a1["reason"]
    assert st["bulk_message_new"]["done"] == 0
    a2 = _plan(hello_typed, st)
    assert a2["action"] == "fail" and "did not send" in a2["reason"]
    assert st["bulk_message_new"]["done"] == 0


# ---- no LLM for fixed first-contact ------------------------------------


def test_fixed_first_contact_runs_never_use_llm():
    assert _fixed_swipe_run(INST, {})
    assert _fixed_swipe_run("send 3 first contact messages on hinge", {})
    assert not _fixed_swipe_run("send 3 first contact messages on blk", {})
    assert _is_fixed_swipe_action(
        {"planner": "yubo_fixed_first_contact_no_llm_handoff", "action": "tap"}
    )
    assert not _fixed_swipe_run("reply to messages on yubo", {})


# ---- device lock deadlock ----------------------------------------------


@pytest.fixture
def local_jobs(monkeypatch):
    monkeypatch.delenv("USE_AWS_STORAGE", raising=False)
    monkeypatch.delenv("JOBS_TABLE", raising=False)
    storage_mod._LOCAL_JOBS = {}  # type: ignore[attr-defined]
    yield storage_mod._LOCAL_JOBS
    storage_mod._LOCAL_JOBS = {}  # type: ignore[attr-defined]


def _job(jid, created, steps, updated, lease=0):
    return {
        "job_id": jid,
        "status": "running",
        "device_id": "dev1",
        "created_at": created,
        "updated_at": updated,
        "lease_owner": "w" if lease else "",
        "lease_expires_at": lease,
        "state": {"steps": steps},
    }


def test_queued_newer_job_does_not_block_older(local_jobs):
    now = int(time.time())
    local_jobs["yubo"] = _job("yubo", now - 300, 20, now - 200)
    local_jobs["badoo1"] = _job("badoo1", now - 100, 0, now - 5)  # deferring
    got = storage_mod.other_running_job_on_device(
        "dev1", except_job_id="yubo", now=now, created_at=now - 300
    )
    assert got is None


def test_stale_started_job_releases_phone(local_jobs):
    now = int(time.time())
    local_jobs["yubo"] = _job("yubo", now - 300, 20, now - 200)  # hung, no lease
    got = storage_mod.other_running_job_on_device(
        "dev1", except_job_id="badoo1", now=now, created_at=now - 100
    )
    assert got is None


def test_active_job_still_blocks(local_jobs):
    now = int(time.time())
    local_jobs["bumble"] = _job("bumble", now - 60, 3, now - 10)
    got = storage_mod.other_running_job_on_device(
        "dev1", except_job_id="badoo1", now=now, created_at=now - 5
    )
    assert got and got["job_id"] == "bumble"


def test_defer_does_not_bump_updated_at_and_gives_up(monkeypatch):
    from backend import step_worker as sw

    saved = []
    monkeypatch.setattr(
        sw, "other_running_job_on_device", lambda *a, **k: {"job_id": "yubo"}
    )
    monkeypatch.setattr(sw, "put_job", lambda j: saved.append(dict(j)))
    now = int(time.time())
    job = _job("badoo1", now - 50, 0, now - 50)
    sw.process_job(job)
    assert saved and saved[-1]["updated_at"] == now - 50
    assert saved[-1]["status"] == "running"
    job2 = _job("badoo2", now - 900, 0, now - 900)
    job2["first_deferred_at"] = now - sw.DEFER_MAX_S - 5
    sw.process_job(job2)
    assert saved[-1]["status"] == "failed"
    assert "Phone busy with yubo" in saved[-1]["error"]


# ---- Stop sweep ----------------------------------------------------------


def test_stop_sweeps_every_running_dating_job():
    jobs = [
        {"job_id": "a", "status": "running", "dating_app": "com.badoo.mobile"},
        {"job_id": "b", "status": "running", "dating_run": "r1"},
        {"job_id": "c", "status": "completed", "dating_run": "r1"},
        {"job_id": "d", "status": "running", "kind": "agent"},
        {"job_id": "e", "status": "running", "schedule_id": "s1"},
    ]
    assert [j["job_id"] for j in running_dating_jobs(jobs)] == ["a", "b", "e"]


# ---- Badoo finds its way back to Encounters ----------------------------

from backend.bumble_fixed_swipe import plan_fixed_swipe  # noqa: E402


def _badoo(name):
    t = (FIX / f"{name}.xml").read_text(encoding="utf-8")
    return plan_fixed_swipe(
        "fixed swipe 2 on badoo",
        t,
        [],
        state={},
        package="com.badoo.mobile",
        dry_run=False,
        planner="badoo_fixed",
        app="badoo",
    )


@pytest.mark.parametrize("name", ["badoo_chats_tab_only", "badoo_connections"])
def test_badoo_top_tabs_tap_encounters_never_back(name):
    a = _badoo(name)
    assert a["action"] == "tap" and a["x"] == 324, a
    assert a.get("_no_llm_handoff")


def test_badoo_inside_chat_backs_out():
    a = _badoo("badoo_thread_open")
    assert a["action"] == "press_button" and a["button"] == "back"


def test_badoo_paid_popup_closed_not_bought():
    a = _badoo("badoo_popup_credits")
    assert a["action"] == "tap" and (a["x"], a["y"]) == (985, 1247)
    assert "Continue" not in str(a.get("label"))


def test_badoo_deck_still_swipes():
    a = _badoo("badoo_encounters")
    assert a["action"] == "swipe"


# ---- Hily: fixed planner, new people, Discover --------------------------

from backend import cloud_agent as _ca  # noqa: E402
from backend.hily_fixed_first_contact import (  # noqa: E402
    DISCOVER_TAB_XY,
    plan_hily_fixed_first_contact,
)


def test_dating_run_first_contact_reaches_fixed_planners_not_llm():
    # Root cause: "send 5 first contact messages on hily" skipped the bulk
    # planners entirely, so the LLM drove Hily (opened Google Messages).
    t = (FIX / "hily_chats_r30.xml").read_text(encoding="utf-8")
    a = _ca.plan_next_action(
        "send 5 first contact messages on hily",
        t,
        ["Opened Hily"],
        None,
        package="com.hily.app",
        dry_run=False,
        agent_state={},
    )
    assert a["planner"].startswith("hily_fixed_first_contact")
    assert (a["x"], a["y"]) == (740, 2190)  # Activity, not a chat row


def test_bank_text_passes_guard_for_fixed_planners():
    t = (FIX / "hily_mbm.xml").read_text(encoding="utf-8")
    a = _ca.plan_next_action(
        "send 5 first contact messages on hily",
        t,
        ["Opened Hily"],
        None,
        package="com.hily.app",
        dry_run=False,
        agent_state={},
    )
    assert a["action"] == "type" and a["text"] == "hey how are you"


def test_hily_likes_sent_empty_goes_to_discover():
    t = (FIX / "hily_likes_sent.xml").read_text(encoding="utf-8")
    t = t.replace('d="chat_request"', 'd="photo"')
    # r53: Likes sent tapped and already scrolled to the end
    st = {"bulk_message_new": {"done": 2, "_ls_tapped": True, "_ls_scrolls": 4}}
    a = plan_hily_fixed_first_contact(
        "send 5 first contact messages on hily",
        t,
        [],
        state=st,
        dry_run=False,
        message="hi miss",
        target=5,
    )
    assert (a["x"], a["y"]) == DISCOVER_TAB_XY


def test_hily_discover_grid_opens_person_not_crush():
    t = (FIX / "hily_top_picks_grid.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 2, "_via_discover": True}}
    a = plan_hily_fixed_first_contact(
        "send 5 first contact messages on hily",
        t,
        [],
        state=st,
        dry_run=False,
        message="hi miss",
        target=5,
    )
    assert a["action"] == "tap"
    assert (a["x"], a["y"]) != (900, 700)  # Crush icon


# ---- Hinge: stuck in Matches → tap the H Discover tab -----------------

from backend.hinge_fixed_first_contact import (
    plan_hinge_fixed_first_contact,
)  # noqa: E402


def _hinge(name, hist=("Open Hinge Discover tab",)):
    t = (FIX / f"{name}.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 1, "_opened_discover": True}}
    return plan_hinge_fixed_first_contact(
        "send 5 first contact messages on hinge",
        t,
        list(hist),
        state=st,
        dry_run=False,
        message="hi miss",
        target=5,
    )


@pytest.mark.parametrize("name", ["hinge_matches_your_turn", "hinge_inbox"])
def test_hinge_matches_taps_discover_h(name):
    a = _hinge(name)
    assert (a["action"], a["x"], a["y"]) == ("tap", 110, 2195)


def test_hinge_chat_thread_backs_out():
    a = _hinge("hinge_thread_composer")
    assert a["action"] == "press_button" and a["button"] == "back"


def test_hinge_discover_still_hearts():
    a = _hinge("hinge_discover_da")
    assert (a["x"], a["y"]) == (937, 1356)


def test_hinge_dating_run_goes_to_fixed_planner():
    t = (FIX / "hinge_matches_your_turn.xml").read_text(encoding="utf-8")
    a = _ca.plan_next_action(
        "send 5 first contact messages on hinge",
        t,
        ["Opened Hinge"],
        None,
        package="co.hinge.app",
        dry_run=False,
        agent_state={},
    )
    assert a["planner"].startswith("hinge_fixed_first_contact")
    assert (a["x"], a["y"]) == (110, 2195)
