"""Social page: message this person / reply to messages; never swipe/like."""

from __future__ import annotations

import sys
import types
from typing import Any, Dict

import pytest

from backend import dating_run, social_run
from backend.bulk_bench_heuristics import plan_bulk_swipe
from backend.dm_heuristics import parse_dm_instruction


def test_message_person_instruction_parses():
    inst = social_run.instruction_for(
        "com.instagram.android", "message", "Jo Bloggs", 'hey "you"\nthere'
    )
    assert parse_dm_instruction(inst) == {
        "app": "instagram",
        "contact": "Jo Bloggs",
        "message": "hey you there",
    }


def test_reply_instruction_parses_existing_chats():
    inst = social_run.instruction_for("com.facebook.orca", "reply", "", "hey")
    d = parse_dm_instruction(inst)
    assert d["app"] == "messenger" and d["existing_count"] == social_run.REPLY_CHATS


@pytest.mark.parametrize(
    "pkg,action,contact,msg",
    [
        ("com.snapchat.android", "message", "Jo", "hi"),  # no driver yet
        ("com.whatsapp", "message", "", "hi"),
        ("com.whatsapp", "reply", "", ""),
        ("com.whatsapp", "swipe", "", "hi"),
    ],
)
def test_bad_social_requests_rejected(pkg, action, contact, msg):
    with pytest.raises(ValueError):
        social_run.instruction_for(pkg, action, contact, msg)


def test_whatsapp_follows_dry_run_toggle():
    job = social_run.build_job(
        device_id="d",
        pkg="com.whatsapp",
        action="message",
        contact="Jo",
        message="hi",
        dry_run=False,
    )
    assert job["dry_run"] is False and job["state"]["dry_run"] is False
    dry = social_run.build_job(
        device_id="d",
        pkg="com.whatsapp",
        action="message",
        contact="Jo",
        message="hi",
        dry_run=True,
    )
    assert dry["dry_run"] is True
    ig = social_run.build_job(
        device_id="d",
        pkg="com.instagram.android",
        action="message",
        contact="Jo",
        message="hi",
        dry_run=False,
    )
    assert ig["dry_run"] is False
    assert ig["mode"] == "social" and ig["kind"] == "agent"


@pytest.mark.parametrize(
    "inst,pkg",
    [
        ("swipe 5 on whatsapp", "com.whatsapp"),
        ("swipe 3 on instagram", "com.instagram.android"),
    ],
)
def test_bulk_swipe_never_runs_on_socials(inst, pkg):
    act = plan_bulk_swipe(inst, "<hierarchy/>", [], state={}, package=pkg)
    assert act["action"] == "fail"
    assert act["fastpath_step"] == "bulk_swipe_social_blocked"


def test_dating_run_never_queues_socials():
    ok, bad = dating_run.split_supported(list(social_run.SOCIAL_PACKAGES))
    assert ok == [] and len(bad) == len(social_run.SOCIAL_PACKAGES)


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main as main_mod

    jobs: Dict[str, Dict[str, Any]] = {}
    storage = types.ModuleType("storage")
    storage.put_job = lambda j: jobs.__setitem__(j["job_id"], dict(j))
    storage.get_job = lambda jid: jobs.get(jid)
    storage.list_recent_jobs = lambda limit=40: list(jobs.values())[:limit]
    monkeypatch.setitem(sys.modules, "storage", storage)
    monkeypatch.setitem(sys.modules, "backend.storage", storage)
    push = types.ModuleType("device_push")
    push.device_is_reachable = lambda d: d == "phone1"
    monkeypatch.setitem(sys.modules, "device_push", push)
    monkeypatch.setitem(sys.modules, "backend.device_push", push)
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setattr(main_mod, "_kick_job", lambda jid: None)
    saved = {}
    monkeypatch.setattr(main_mod, "_load_social_runtime", lambda *a, **k: None)
    monkeypatch.setattr(
        main_mod,
        "_save_social_runtime",
        lambda *a, **k: saved.update(job_id=main_mod.social_mode_state.get("job_id")),
    )
    c = TestClient(main_mod.app)
    c.saved = saved
    return c


def test_social_run_endpoint(client):
    r = client.post(
        "/api/social/run",
        json={
            "device_id": "phone1",
            "app": "com.whatsapp",
            "action": "message",
            "contact": "Jo",
            "message": "hi",
            "dry_run": False,
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["dry_run"] is False  # WhatsApp follows the toggle
    assert job["instruction"] == "whatsapp message Jo and say hi"
    assert client.saved["job_id"] == job["job_id"]  # Stop works cross-Lambda
    bad = client.post(
        "/api/social/run",
        json={
            "device_id": "phone1",
            "app": "com.snapchat.android",
            "action": "message",
            "contact": "Jo",
            "message": "hi",
        },
    )
    assert bad.status_code == 400
    off = client.post(
        "/api/social/run",
        json={
            "device_id": "gone",
            "app": "com.instagram.android",
            "action": "reply",
            "message": "hey",
        },
    )
    assert off.status_code == 400 and "offline" in off.json()["detail"].lower()
