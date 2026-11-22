"""Reply persona + date-flow: timing, radius, no stay-over, handoff, contact ask."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mobilerun.dating.date_flow import (
    DEFAULT_CONTACT_ASK_WHATSAPP,
    DateFlowConfig,
    DateFlowManager,
    build_contact_ask_text,
    build_invite_text,
    contains_stay_over_wording,
    conversation_is_engaged,
    extract_contact_handle,
    is_beyond_radius,
    pick_invite_day_threshold,
    strip_stay_over_wording,
)
from mobilerun.dating.matches import MatchStore, redact_for_log
from mobilerun.dating.persona import PersonaManager


def test_invite_day_threshold_in_window():
    cfg = DateFlowConfig(invite_days_min=3, invite_days_max=7)
    rng = random.Random(0)
    vals = {pick_invite_day_threshold(cfg, rng=rng) for _ in range(40)}
    assert min(vals) >= 3
    assert max(vals) <= 7
    assert vals  # non-empty


def test_radius_logic_stoke_vs_near():
    cfg = DateFlowConfig(home_location="Stoke-on-Trent", radius_miles=50)
    assert is_beyond_radius(80, 50) is True
    assert is_beyond_radius(20, 50) is False
    assert is_beyond_radius(None, 50) is False

    far = build_invite_text(cfg, distance_miles=80, her_name="Sam")
    near = build_invite_text(cfg, distance_miles=10, her_name="Sam")
    assert "Stoke-on-Trent" in far
    assert "convenient" in near.lower()
    assert "Stoke-on-Trent" not in near
    assert not contains_stay_over_wording(far)
    assert not contains_stay_over_wording(near)


@pytest.mark.parametrize(
    "bad",
    [
        "Want to stay over at my place?",
        "Come to my house tonight",
        "You can sleep over",
        "Netflix and chill at my flat",
        "Spend the night at my apartment",
    ],
)
def test_no_stay_over_wording(bad):
    assert contains_stay_over_wording(bad)
    cleaned = strip_stay_over_wording(bad)
    assert not contains_stay_over_wording(cleaned)
    assert "public" in cleaned.lower() or "coffee" in cleaned.lower()
    invite = build_invite_text(DateFlowConfig(), distance_miles=12)
    assert not contains_stay_over_wording(invite)
    assert "my place" not in invite.lower()
    assert "stay over" not in invite.lower()


def test_invite_only_after_days_and_engaged(tmp_path: Path):
    mgr = DateFlowManager(
        DateFlowConfig(invite_days_min=3, invite_days_max=3),
        persist_path=tmp_path / "df.json",
        rng=random.Random(1),
    )
    chat = mgr.get_chat("m1", "co.hinge.app")
    # Too early + not engaged
    chat.chat_started_at = datetime.now().isoformat()
    d0 = mgr.evaluate_turn(
        match_id="m1",
        package_name="co.hinge.app",
        inbound="hey",
    )
    # evaluate increments her_message_count; force low engagement
    assert d0.should_invite is False

    # Age the chat past threshold and add engagement
    chat = mgr.get_chat("m1", "co.hinge.app")
    chat.chat_started_at = (datetime.now() - timedelta(days=4)).isoformat()
    chat.her_message_count = 3
    d1 = mgr.evaluate_turn(
        match_id="m1",
        package_name="co.hinge.app",
        inbound="haha yeah what about you?",
    )
    assert d1.should_invite is True
    assert d1.invite_text
    assert not contains_stay_over_wording(d1.invite_text)

    # Second invite blocked (no repeated pushing)
    d2 = mgr.evaluate_turn(
        match_id="m1",
        package_name="co.hinge.app",
        inbound="nice",
    )
    assert d2.should_invite is False


def test_handoff_stops_ai_on_agree_when_contact_ask_off(tmp_path: Path):
    needs = []
    mgr = DateFlowManager(
        DateFlowConfig(
            invite_days_min=1,
            invite_days_max=1,
            contact_ask_enabled=False,
        ),
        persist_path=tmp_path / "df.json",
        rng=random.Random(0),
        push_needs_you=lambda **kw: needs.append(kw) or "ny1",
    )
    chat = mgr.get_chat("m2", "com.bumble.app")
    chat.chat_started_at = (datetime.now() - timedelta(days=5)).isoformat()
    chat.her_message_count = 5
    chat.invite_sent = True
    chat.engaged = True

    d = mgr.evaluate_turn(
        match_id="m2",
        package_name="com.bumble.app",
        inbound="Yes Saturday 7pm at the café works for me!",
        her_name="Alex",
    )
    assert d.stop_ai is True
    assert d.needs_you is True
    assert d.needs_you_kind == "date_handoff"
    assert chat.ai_replies_stopped is True
    assert chat.date_booked is True
    assert needs

    # PersonaManager must not produce AI reply
    pm = PersonaManager(
        date_flow=mgr,
        ai_callable=lambda **k: (_ for _ in ()).throw(AssertionError("LLM called")),
    )
    out = pm.compose_reply(
        match_id="m2",
        package_name="com.bumble.app",
        inbound_preview="looking forward to it",
        profile_name="Alex",
    )
    assert out.get("stop_ai") is True
    assert out.get("source") == "handoff"
    assert out.get("text") == ""


def test_contact_ask_whatsapp_first_then_capture(tmp_path: Path):
    needs = []
    store = MatchStore("mac@test", persist_path=tmp_path / "matches.json")
    mgr = DateFlowManager(
        DateFlowConfig(contact_ask_enabled=True),
        persist_path=tmp_path / "df.json",
        rng=random.Random(1),
        push_needs_you=lambda **kw: needs.append(kw) or "ny1",
        on_match_upsert=store.upsert_from_date_flow,
    )
    chat = mgr.get_chat("c1", "co.hinge.app")
    chat.invite_sent = True
    chat.her_message_count = 4

    d1 = mgr.evaluate_turn(
        match_id="c1",
        package_name="co.hinge.app",
        inbound="Yes Saturday 7pm at the café works for me!",
        her_name="Sam",
        distance_miles=12,
    )
    assert d1.stop_ai is False
    assert d1.should_contact_ask is True
    assert d1.contact_ask_channel == "whatsapp"
    assert "WhatsApp" in d1.contact_ask_text
    assert "Snapchat" not in d1.contact_ask_text
    assert chat.contact_ask_channel == "whatsapp"
    assert chat.date_booked is True
    assert needs == []
    booked = store.get("c1", "co.hinge.app")
    assert booked is not None
    assert booked.status == "booked"
    assert booked.name == "Sam"

    pm = PersonaManager(
        date_flow=mgr,
        ai_callable=lambda **k: (_ for _ in ()).throw(AssertionError("LLM called")),
    )
    out = pm.compose_reply(
        match_id="c1",
        package_name="co.hinge.app",
        inbound_preview="Yes Saturday 7pm at the café works for me!",
        profile_name="Sam",
    )
    assert out["source"] == "contact_ask"
    assert out["text"] == d1.contact_ask_text

    d2 = mgr.evaluate_turn(
        match_id="c1",
        package_name="co.hinge.app",
        inbound="Sure, my WhatsApp is +44 7700 900123",
        her_name="Sam",
    )
    assert d2.stop_ai is True
    assert d2.contact_kind == "whatsapp"
    assert "7700900123" in d2.contact_handle.replace(" ", "")
    assert chat.whatsapp
    rec = store.get("c1", "co.hinge.app")
    assert rec is not None
    assert "7700900123" in rec.whatsapp.replace(" ", "")
    assert rec.status == "handed_off"
    assert needs[0]["meta"]["never_auto_message_contact"] is True
    red = redact_for_log(needs[0]["meta"])
    assert red["whatsapp"] == "***"


def test_contact_ask_order_decline_whatsapp_then_snap(tmp_path: Path):
    needs = []
    mgr = DateFlowManager(
        DateFlowConfig(contact_ask_enabled=True),
        persist_path=tmp_path / "df.json",
        push_needs_you=lambda **kw: needs.append(kw) or "ny1",
    )
    chat = mgr.get_chat("c2", "com.bumble.app")
    chat.invite_sent = True

    d1 = mgr.evaluate_turn(
        match_id="c2",
        package_name="com.bumble.app",
        inbound="Yes Friday 6pm works!",
        her_name="Lee",
    )
    assert d1.contact_ask_channel == "whatsapp"
    assert "WhatsApp" in build_contact_ask_text(mgr.config, "whatsapp")

    # Decline WhatsApp → ask Snapchat once
    d2 = mgr.evaluate_turn(
        match_id="c2",
        package_name="com.bumble.app",
        inbound="Prefer to keep chatting here thanks",
        her_name="Lee",
    )
    assert d2.stop_ai is False
    assert d2.should_contact_ask is True
    assert d2.contact_ask_channel == "snapchat"
    assert "Snapchat" in d2.contact_ask_text
    assert chat.contact_asks_done == ["whatsapp"]
    assert chat.ai_replies_stopped is False
    assert needs == []

    # Decline Snapchat → hand off, no more asks
    d3 = mgr.evaluate_turn(
        match_id="c2",
        package_name="com.bumble.app",
        inbound="No snap thanks",
        her_name="Lee",
    )
    assert d3.stop_ai is True
    assert d3.reason == "contact_declined"
    assert chat.contact_ask_pending is False
    assert set(chat.contact_asks_done) == {"whatsapp", "snapchat"}
    assert needs


def test_contact_ask_ignore_skips_second_channel(tmp_path: Path):
    mgr = DateFlowManager(
        DateFlowConfig(contact_ask_enabled=True),
        persist_path=tmp_path / "df.json",
    )
    chat = mgr.get_chat("c3", "co.hinge.app")
    chat.invite_sent = True
    mgr.evaluate_turn(
        match_id="c3",
        package_name="co.hinge.app",
        inbound="Sounds good — Saturday coffee works",
    )
    assert chat.contact_ask_channel == "whatsapp"

    d = mgr.evaluate_turn(
        match_id="c3",
        package_name="co.hinge.app",
        inbound="What films have you seen lately?",
    )
    assert d.stop_ai is True
    assert d.reason == "contact_ignored"
    assert d.should_contact_ask is False
    assert chat.contact_ask_pending is False


def test_extract_contact_handle_snap_and_wa():
    h, k = extract_contact_handle("snap: cool.sam92")
    assert k == "snapchat"
    assert h == "cool.sam92"
    h2, k2 = extract_contact_handle("my number is 07700 900456")
    assert k2 in ("phone", "whatsapp")
    assert "7700900456" in h2.replace(" ", "")
    assert extract_contact_handle("haha yeah") == ("", "")
    assert DEFAULT_CONTACT_ASK_WHATSAPP


def test_handoff_on_discomfort(tmp_path: Path):
    mgr = DateFlowManager(
        DateFlowConfig(),
        persist_path=tmp_path / "df.json",
    )
    d = mgr.evaluate_turn(
        match_id="m3",
        package_name="com.badoo.mobile",
        inbound="This is weird, leave me alone",
    )
    assert d.stop_ai is True
    assert d.needs_you_kind == "discomfort"


def test_decline_invite_no_repeat(tmp_path: Path):
    mgr = DateFlowManager(
        DateFlowConfig(invite_days_min=1, invite_days_max=1),
        persist_path=tmp_path / "df.json",
        rng=random.Random(2),
    )
    chat = mgr.get_chat("m4", "co.hinge.app")
    chat.chat_started_at = (datetime.now() - timedelta(days=5)).isoformat()
    chat.her_message_count = 4
    chat.invite_sent = True
    d = mgr.evaluate_turn(
        match_id="m4",
        package_name="co.hinge.app",
        inbound="No thanks, rather not",
    )
    assert d.stop_ai is True
    assert chat.invite_declined is True


def test_persona_injects_invite_without_llm(tmp_path: Path):
    mgr = DateFlowManager(
        DateFlowConfig(invite_days_min=3, invite_days_max=3, radius_miles=50),
        persist_path=tmp_path / "df.json",
        rng=random.Random(3),
    )
    chat = mgr.get_chat("m5", "co.hinge.app")
    chat.chat_started_at = (datetime.now() - timedelta(days=5)).isoformat()
    chat.her_message_count = 4

    calls = []

    def ai(**kwargs):
        calls.append(kwargs)
        return "should not run for invite"

    pm = PersonaManager(date_flow=mgr, ai_callable=ai)
    out = pm.compose_reply(
        match_id="m5",
        package_name="co.hinge.app",
        inbound_preview="haha tell me more about that?",
        profile_name="Riley",
        distance_miles=90,
    )
    assert out["source"] == "date_invite"
    assert "Stoke-on-Trent" in out["text"]
    assert calls == []
    assert not contains_stay_over_wording(out["text"])


def test_conversation_engaged_heuristic():
    assert conversation_is_engaged(her_message_count=1, last_inbound="hi") is False
    assert (
        conversation_is_engaged(
            her_message_count=3, last_inbound="haha yeah what about you?"
        )
        is True
    )


def test_api_date_flow(monkeypatch, tmp_path):
    import importlib

    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)

    import backend.main as main_mod

    importlib.reload(main_mod)
    main_mod._date_flow_mgr = None
    from fastapi.testclient import TestClient

    c = TestClient(main_mod.app)

    r = c.get("/api/dating/date-flow")
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["home_location"] == "Stoke-on-Trent"
    assert cfg["radius_miles"] == 50
    assert cfg["invite_days_min"] == 3

    r2 = c.post(
        "/api/dating/date-flow",
        json={
            "reply_persona_prompt": "Warm and curious.",
            "invite_days_min": 4,
            "invite_days_max": 6,
            "radius_miles": 40,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["config"]["invite_days_min"] == 4
    assert "Warm" in r2.json()["config"]["reply_persona_prompt"]

    # Far match past timing → invite mentions Stoke
    ev = c.post(
        "/api/dating/date-flow/evaluate",
        json={
            "match_id": "api1",
            "package_name": "co.hinge.app",
            "inbound": "haha sounds interesting, what about you?",
            "distance_miles": 100,
            "her_name": "Jordan",
            "days_chatting": 10,
            "her_message_count": 5,
        },
    )
    assert ev.status_code == 200, ev.text
    body = ev.json()
    assert body["should_invite"] is True
    assert "Stoke-on-Trent" in body["invite_text"]
    assert not contains_stay_over_wording(body["invite_text"])

    # Agree → optional contact ask (default on), not immediate handoff
    ev2 = c.post(
        "/api/dating/date-flow/evaluate",
        json={
            "match_id": "api1",
            "package_name": "co.hinge.app",
            "inbound": "Yes Friday 6pm at the café works!",
            "her_name": "Jordan",
        },
    )
    body2 = ev2.json()
    assert body2["stop_ai"] is False
    assert body2["should_contact_ask"] is True
    assert body2["contact_ask_channel"] == "whatsapp"
    assert "WhatsApp" in body2["contact_ask_text"]

    # Share snap while WA pending → still capture + handoff
    ev3 = c.post(
        "/api/dating/date-flow/evaluate",
        json={
            "match_id": "api1",
            "package_name": "co.hinge.app",
            "inbound": "my snap is jordan.j92",
            "her_name": "Jordan",
        },
    )
    body3 = ev3.json()
    assert body3["stop_ai"] is True
    assert body3["needs_you"] is True
    assert body3["contact_handle"] == "jordan.j92"
    assert body3["contact_kind"] == "snapchat"

    # Matches CRM removed — endpoint gone
    matches = c.get("/api/dating/matches")
    assert matches.status_code == 410

    # Compose reply must stop AI
    comp = c.post(
        "/api/dating/compose",
        json={
            "match_id": "api1",
            "package_name": "co.hinge.app",
            "profile_name": "Jordan",
            "is_opener": False,
            "inbound_preview": "see you then",
        },
    )
    assert comp.status_code == 200
    assert comp.json().get("stop_ai") is True
    assert comp.json().get("source") == "handoff"

    # Config includes ordered contact ask fields
    cfg2 = c.get("/api/dating/date-flow").json()["config"]
    assert cfg2["contact_ask_enabled"] is True
    assert cfg2["contact_ask_order"][0] == "whatsapp"
    assert "WhatsApp" in cfg2["contact_ask_whatsapp_text"]
    assert "Snapchat" in cfg2["contact_ask_snapchat_text"]


def test_matches_api_removed(monkeypatch, tmp_path):
    import importlib

    monkeypatch.setenv("ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("MOBILERUN_DATA", str(tmp_path))
    monkeypatch.setenv("USE_AWS_STORAGE", "false")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)

    import backend.main as main_mod

    importlib.reload(main_mod)
    from fastapi.testclient import TestClient

    c = TestClient(main_mod.app)
    assert c.get("/api/dating/matches").status_code == 410
    assert c.post("/api/dating/matches", json={"name": "Alex"}).status_code == 410
    assert c.put("/api/dating/matches/x", json={"name": "Alex"}).status_code == 410
    assert c.delete("/api/dating/matches/x").status_code == 410
    assert c.get("/api/dating/matches/export.csv").status_code == 410


def test_redact_for_log_hides_contacts():
    assert redact_for_log({"whatsapp": "+44123", "name": "Sam"}) == {
        "whatsapp": "***",
        "name": "Sam",
    }
