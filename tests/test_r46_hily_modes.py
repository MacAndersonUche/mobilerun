"""r46: Hily "Likes only" / "Message + likes" — Finder likes, Likes-sent
envelopes, per-mode max likes, no LLM, never Crush / paid / Discover."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict

import pytest

from backend import cloud_agent as ca
from backend import dating_run
from backend.dating_schedule import build_like_caps, build_modes, build_queue, normalize
from backend.hily_fixed_run import (
    FINDER_TAB_XY,
    parse_hily_instruction,
    plan_hily_fixed_run,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
FINDER = (FIX / "hily_finder.xml").read_text(encoding="utf-8")
LIKES_SENT = (FIX / "hily_likes_sent.xml").read_text(encoding="utf-8")
MBM = (FIX / "hily_mbm_shann.xml").read_text(encoding="utf-8")
CHATS = (FIX / "hily_chats.xml").read_text(encoding="utf-8")
LIKES_SENT_EMPTY = "\n".join(
    ln for ln in LIKES_SENT.splitlines() if "chat_request" not in ln
)
PAYWALL = (
    '<hierarchy packages="com.hily.app"><w p="com.hily.app">'
    '<n t="Upgrade to Premium" xy="540,900"/>'
    '<n t="Continue" c="1" xy="540,1800"/></w></hierarchy>'
)
CRUSH_XY = (540, 1959)
DISCOVER_XY = (540, 2190)


def _xy(a):
    return (a.get("x"), a.get("y"))


def _run(inst, trees, st=None):
    st = {} if st is None else st
    out = []
    for t in trees:
        a = plan_hily_fixed_run(inst, t, [], state=st)
        out.append(a)
    return out, st


# ---- instructions / modes / caps ------------------------------------------


def test_parse_instruction():
    assert parse_hily_instruction("fixed hily likes 40") == (0, 40)
    assert parse_hily_instruction("fixed hily message 5 likes 30") == (5, 30)
    # messages capped at 5; likes never below messages
    assert parse_hily_instruction("fixed hily message 9 likes 2") == (5, 5)
    assert parse_hily_instruction("send 5 first contact messages on hily") is None


def test_modes_and_like_caps_per_mode():
    assert dating_run.clean_modes(
        {"hily": "likes", "com.taggedapp": "message", "bumble": "likes"}
    ) == {"com.hily.app": "likes", "com.taggedapp": "message"}
    assert dating_run.clean_modes({"hily": "swipe"}) == {}
    caps = dating_run.clean_like_caps(
        {"hily:likes": "40", "com.hily.app:message_likes": 900,
         "bumble:likes": 3, "hily:bogus": 5, "hily:likes2": "x"}
    )
    assert caps == {"com.hily.app:likes": 40, "com.hily.app:message_likes": 500}
    inst = dating_run.instruction_for
    assert inst("com.hily.app", None, None, {"com.hily.app": "likes"}, caps) == "fixed hily likes 40"
    assert inst("com.hily.app", None, {"com.hily.app": 3}, None, caps) == "fixed hily message 3 likes 500"
    # default mode = Message + likes, default 30 likes, 5 messages
    assert inst("com.hily.app", None) == "fixed hily message 5 likes 30"


def test_build_job_carries_caps_wall_and_next_app():
    j = dating_run.build_job(
        device_id="d", queue=["com.hily.app", "com.bumble.app"], count=None,
        dry_run=False, modes={"com.hily.app": "likes"},
        like_caps={"com.hily.app:likes": 100},
    )
    assert j["instruction"] == "fixed hily likes 100"
    assert j["run_like_caps"] == {"com.hily.app:likes": 100}
    assert j["max_steps"] >= 200 and 600 < j["wall_s"] <= 3600
    assert "com.hily.app#like" not in j["run_queue"]
    j["status"] = "completed"
    nxt = dating_run.next_job_after(j)
    assert nxt["dating_app"] == "com.bumble.app"
    assert nxt["run_like_caps"] == {"com.hily.app:likes": 100}


def test_step_worker_uses_job_wall_for_long_hily_runs():
    import time

    from backend import step_worker as sw

    now = int(time.time())
    job = {"started_at": now - 900, "state": {"last_ui_progress_at": now, "steps": 3}}
    assert sw.enforce_job_wall_clock(dict(job)) is not None  # default 600s
    job["wall_s"] = 1500
    assert sw.enforce_job_wall_clock(dict(job)) is None
    job["wall_s"] = 99999  # bounded at 1h
    job["started_at"] = now - 3700
    assert sw.enforce_job_wall_clock(dict(job)) is not None


def test_schedule_keeps_hily_mode_and_likes():
    s = normalize(
        {"time": "09:00", "device_id": "phone1", "items": [
            {"app": "hily", "runs": 1, "count": 9, "mode": "likes", "likes": 45},
            {"app": "tagged", "runs": 1, "count": 3, "mode": "message"},
        ]}
    )
    hy = s["items"][0]
    assert hy == {"app": "com.hily.app", "runs": 1, "count": 5, "mode": "likes", "likes": 45}
    assert build_modes(s) == {"com.hily.app": "likes", "com.taggedapp": "message"}
    assert build_like_caps(s) == {"com.hily.app:likes": 45}
    q, _ = build_queue(s)
    assert q == ["com.hily.app", "com.taggedapp"]
    d = normalize({"time": "09:00", "device_id": "phone1", "items": [{"app": "hily", "runs": 1, "count": 2}]})
    assert d["items"][0]["mode"] == "message_likes" and d["items"][0]["likes"] == 30


# ---- planner ---------------------------------------------------------------


def test_likes_only_finder_hearts_then_done_never_crush():
    acts, st = _run("fixed hily likes 3", [CHATS] + [FINDER] * 5)
    assert acts[0]["fastpath_step"] == "hily_run_finder_tab"  # Finder, not Discover
    assert _xy(acts[0]) == (142, 2190)
    likes = [a for a in acts if a["fastpath_step"] == "hily_run_fixed_like_swipe"]
    assert len(likes) == 3 and all(_xy(a) == (750, 1959) for a in likes)
    assert acts[4]["action"] == "done" and "3/3 likes" in acts[4]["reason"]
    for a in acts:
        assert _xy(a) not in (CRUSH_XY, DISCOVER_XY)
        assert a["action"] != "type"
        assert a.get("llm_provider") is None


def test_message_and_likes_full_cycle():
    trees = [
        FINDER, FINDER, FINDER,         # 2 likes (counted on the next Finder)
        LIKES_SENT, MBM, MBM,           # envelope → type → send 1
        LIKES_SENT, LIKES_SENT, MBM, MBM,  # confirm 1, envelope, type, send 2
        LIKES_SENT,                     # confirm 2 → back to Finder
        CHATS, FINDER, FINDER, FINDER,  # Finder tab, likes 3,4 → done
    ]
    acts, st = _run("fixed hily message 2 likes 4", trees)
    steps = [a["fastpath_step"] for a in acts]
    assert steps[:3] == ["hily_run_fixed_like_swipe", "hily_run_fixed_like_swipe",
                         "hily_fixed_fc_activity"]
    assert _xy(acts[2]) == (740, 2190)
    assert steps[3] == "hily_fixed_fc_open_request" and _xy(acts[3]) == (445, 925)
    typed = [a for a in acts if a["action"] == "type"]
    assert len(typed) == 2 and all(a["text"] == "hey how are you" for a in typed)
    assert steps.count("hily_fixed_fc_send") == 2
    assert st["hily_run"]["sent"] == 2
    assert steps[10] == "hily_run_finder_tab_xy" and _xy(acts[10]) == FINDER_TAB_XY
    assert acts[-1]["action"] == "done"
    assert "4/4 likes" in acts[-1]["reason"] and "sent 2/2" in acts[-1]["reason"]
    for a in acts:
        assert _xy(a) not in (CRUSH_XY, DISCOVER_XY)
        assert a["planner"] == "hily_fixed_run" and a.get("_no_llm_handoff")


def test_no_envelopes_left_goes_back_to_finder_not_discover():
    st = {"hily_run": {"likes": 2, "sent": 0, "phase": "message"}}
    a = plan_hily_fixed_run("fixed hily message 2 likes 5", LIKES_SENT_EMPTY, [], state=st)
    assert st["hily_run"]["phase"] == "likes2"
    assert _xy(a) == FINDER_TAB_XY
    assert "no more Likes-sent envelopes" in st["hily_run"]["msg_end"]


def test_paywall_closed_with_back():
    a = plan_hily_fixed_run("fixed hily likes 5", PAYWALL, [], state={})
    assert a["action"] == "press_button" and a["button"] == "back"


def test_dry_run_taps_nothing():
    a = plan_hily_fixed_run("fixed hily message 5 likes 30", FINDER, [], state={}, dry_run=True)
    assert a["action"] == "done" and a["dry_run_verified"]


def test_lost_off_finder_fails_cleanly():
    blank = '<hierarchy packages="com.hily.app"><w p="com.hily.app"><n t="?" xy="1,1"/></w></hierarchy>'
    acts, _ = _run("fixed hily likes 5", [blank] * 12)
    assert acts[-1]["action"] == "fail"
    assert all(_xy(a) not in (CRUSH_XY, DISCOVER_XY) for a in acts)


def test_cloud_agent_routes_hily_without_llm():
    st: Dict[str, Any] = {}
    a = ca.plan_next_action("fixed hily likes 3", FINDER, [], package="com.hily.app",
                            agent_state=st)
    assert a["planner"] == "hily_fixed_run" and _xy(a) == (750, 1959)
    assert ca._fixed_swipe_run("fixed hily message 5 likes 30", {})
    assert ca._is_fixed_swipe_action(a)
    st2: Dict[str, Any] = {"hily_run": {"likes": 2, "sent": 0, "phase": "message",
                                        "fc": {"bulk_message_new": {"done": 0, "typed": False}}}}
    t = ca.plan_next_action("fixed hily message 2 likes 4", MBM, [], package="com.hily.app",
                            agent_state=st2)
    assert t["action"] == "type" and t["text"] == "hey how are you"


# ---- API -------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main as main_mod

    jobs: Dict[str, Dict[str, Any]] = {}
    settings: Dict[Any, Any] = {}
    storage = types.ModuleType("storage")
    storage.put_job = lambda j: jobs.__setitem__(j["job_id"], dict(j))
    storage.get_job = lambda jid: jobs.get(jid)
    storage.list_recent_jobs = lambda limit=40: list(jobs.values())[:limit]
    storage.get_user_setting = lambda u, k: settings.get((u, k))
    storage.save_user_setting = lambda u, k, v: settings.__setitem__((u, k), v)
    monkeypatch.setitem(sys.modules, "storage", storage)
    monkeypatch.setitem(sys.modules, "backend.storage", storage)
    push = types.ModuleType("device_push")
    push.device_is_reachable = lambda d: d == "phone1"
    monkeypatch.setitem(sys.modules, "device_push", push)
    monkeypatch.setitem(sys.modules, "backend.device_push", push)
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setattr(main_mod, "_kick_job", lambda jid: None)
    monkeypatch.setattr(main_mod, "_save_dating_runtime", lambda *a, **k: None)
    monkeypatch.setattr(main_mod, "_load_dating_runtime", lambda *a, **k: None)
    main_mod.dating_mode_state["running"] = False
    main_mod.dating_mode_state.pop("job_id", None)
    return TestClient(main_mod.app)


def test_run_counts_api_saves_modes_and_like_caps_per_mode(client):
    r = client.post("/api/dating/run-counts", json={
        "counts": {"com.hily.app": 4},
        "modes": {"com.hily.app": "likes"},
        "like_caps": {"com.hily.app:likes": 60, "com.hily.app:message_likes": 25},
    })
    assert r.status_code == 200, r.text
    g = client.get("/api/dating/run-counts").json()
    assert g["modes"] == {"com.hily.app": "likes"}
    assert g["like_caps"] == {"com.hily.app:likes": 60, "com.hily.app:message_likes": 25}
    assert g["counts"]["com.hily.app"] == 4
    # changing the mode keeps both mode maxes
    client.post("/api/dating/run-counts", json={"modes": {"com.hily.app": "message_likes"}})
    g = client.get("/api/dating/run-counts").json()
    assert g["like_caps"]["com.hily.app:likes"] == 60
    r = client.post("/api/dating/start", json={
        "device_id": "phone1", "dry_run": True, "apps": ["com.hily.app"]})
    assert r.status_code == 200, r.text
    assert r.json()["job"]["instruction"] == "fixed hily message 4 likes 25"


# ---- r47: Finder with the card missing from the tree (prod 24 Nov 10:26) ----

BARE = (FIX / "hily_finder_empty_a11y_r47.xml").read_text(encoding="utf-8")


def test_r47_bare_finder_waits_then_likes_with_map_heart():
    from backend.hily_fixed_run import finder_without_card_nodes

    assert finder_without_card_nodes(BARE)
    assert not finder_without_card_nodes(CHATS) and not finder_without_card_nodes(LIKES_SENT)
    acts, st = _run("fixed hily likes 3", [BARE] * 5)
    assert acts[0]["action"] == "wait"  # card loading — never re-tap the Finder tab
    likes = acts[1:4]
    assert all(a["fastpath_step"] == "hily_run_fixed_like_swipe" for a in likes)
    assert all(_xy(a) == (750, 1959) for a in likes)
    assert acts[4]["action"] == "done" and "3/3" in acts[4]["reason"]
    assert all(_xy(a) not in (CRUSH_XY, DISCOVER_XY, (142, 2190)) for a in acts)


def test_r47_bare_finder_routed_without_llm_or_repeat_stop():
    st: Dict[str, Any] = {}
    a = ca.plan_next_action("fixed hily likes 30", BARE, [], package="com.hily.app",
                            agent_state=st)
    assert a["planner"] == "hily_fixed_run" and a["action"] == "wait"
    b = ca.plan_next_action("fixed hily likes 30", BARE, [], package="com.hily.app",
                            agent_state=st)
    assert _xy(b) == (750, 1959) and ca._is_fixed_swipe_action(b)
    assert b["fastpath_step"].endswith("_fixed_like_swipe")  # same-tap exempt
