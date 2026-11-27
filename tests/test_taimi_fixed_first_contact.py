"""Taimi first-contact: tap the deck suggested-message chip, never Like or Instant Chat."""

from pathlib import Path

from backend.taimi_fixed_first_contact import (
    PLANNER,
    deck_suggested_chips,
    pick_suggested_chip,
    plan_taimi_fixed_first_contact,
)
from backend.cloud_agent import _fixed_swipe_run
from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dm"
LOCAL = Path("/workspace/mrdbg/taimi")
INSTR = 'send 5 first contact messages on taimi "good evening beautiful"'
LIKE = (761, 1948)
IC = (541, 1948)


def _load(*names: str) -> str:
    for n in names:
        for base in (FIXTURES, LOCAL):
            p = base / n
            if p.exists():
                return p.read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError(names)


def _plan(tree: str, **kw):
    st = kw.pop("state", {})
    return plan_taimi_fixed_first_contact(
        INSTR,
        tree,
        kw.pop("history", []),
        state=st,
        package=kw.get("package", "com.takimi.android"),
        dry_run=kw.get("dry_run", False),
        message="good evening beautiful",
        target=kw.get("target", 5),
    ), st


def test_instruction_is_taimi_first_contact_no_llm():
    g = parse_bulk_goal(INSTR)
    assert g and g["app"] == "taimi" and g["first_contact"] is True
    assert _fixed_swipe_run(INSTR, {}) is True


def test_live_deck_taps_eleanor_chip_never_like_or_instant_chat():
    tree = _load("taimi_uiautomator_people.xml", "taimi_01.xml")
    chips = deck_suggested_chips(tree)
    texts = [c["text"] for c in chips]
    assert any("Heyy Eleanor" in t for t in texts)
    picked = pick_suggested_chip(tree, preferred="good evening beautiful", card_name="Eleanor")
    assert picked and "Heyy Eleanor" in picked["text"]
    # Must not pick Katie's chip while Eleanor is the front card.
    assert "Katie" not in picked["text"]
    a, st = _plan(tree)
    assert a["action"] == "tap"
    assert a["fastpath_step"] == "taimi_fc_suggested"
    assert a["_no_llm_handoff"] is True
    assert (a["x"], a["y"]) == (picked["x"], picked["y"])
    assert (a["x"], a["y"]) not in (LIKE, IC)
    assert a["y"] < 1870  # above the action row
    assert "Heyy Eleanor" in (a.get("reason") or "")
    assert st["taimi_fc"]["pending_name"] == "Eleanor"
    assert "Heyy Eleanor" in st["taimi_fc"]["pending_chip"]


def test_compact_people_taps_coffee_chip():
    tree = _load("taimi_people.xml")
    picked = pick_suggested_chip(tree, preferred="good evening beautiful", card_name="Alex")
    assert picked and "Coffee" in picked["text"]
    a, st = _plan(tree)
    assert a["action"] == "tap"
    assert a["fastpath_step"] == "taimi_fc_suggested"
    assert (a["x"], a["y"]) not in (LIKE, IC)
    assert "Coffee" in (a.get("reason") or "")
    assert st["taimi_fc"]["pending_name"] == "Alex"


def test_prefers_chip_matching_good_evening_beautiful():
    # Reuse the compact people tree but inject a preferred chip in-band.
    tree = _load("taimi_people.xml")
    # Append a compact node in the chip band.
    inject = (
        '  <n t="good evening beautiful" d="good evening beautiful" '
        'cls="ViewGroup" c="1" xy="540,1760" b="80,1708,900,1812"/>\n'
    )
    if "</w>" in tree:
        tree = tree.replace("</w>", inject + "</w>", 1)
    else:
        tree = tree + inject
    picked = pick_suggested_chip(tree, preferred="good evening beautiful", card_name="Alex")
    assert picked and "good evening beautiful" in picked["text"].lower()
    a, _ = _plan(tree)
    assert a["fastpath_step"] == "taimi_fc_suggested"
    assert "good evening beautiful" in (a.get("reason") or "").lower()
    assert (a["x"], a["y"]) not in (LIKE, IC)


def test_curated_without_chip_skips_never_likes():
    tree = _load("taimi_curated.xml")
    assert pick_suggested_chip(tree, card_name="Sam") is None
    a, _ = _plan(tree)
    assert a["action"] == "tap"
    assert a["fastpath_step"] == "taimi_fc_skip_no_chip"
    assert (a["x"], a["y"]) != LIKE
    assert (a["x"], a["y"]) != IC


def test_gold_paywall_backs_then_stops_never_continue():
    tree = _load("taimi_paywall_instantchat.xml", "taimi_paywall.xml")
    a, st = _plan(tree)
    assert a["action"] == "press_button"
    assert a.get("button") == "back"
    assert "continue" not in (a.get("reason") or "").lower() or "never continue" in (a.get("reason") or "").lower()
    a2, st = _plan(tree, state=st)
    a3, st = _plan(tree, state=st)
    assert a3["action"] == "fail"
    assert a3["fastpath_step"] == "taimi_fc_paywall_stop"
    assert "never bought" in (a3.get("reason") or "").lower()
    assert not st["taimi_fc"].get("sent_names")


def test_instant_chat_sheet_backs_out_not_used():
    tree = _load("tai_pc1.xml")
    a, _ = _plan(tree)
    assert a["action"] == "press_button"
    assert a.get("button") == "back"
    assert a["fastpath_step"] == "taimi_fc_instant_chat_back"


def test_existing_thread_backs_never_messages():
    tree = _load("taimi_thread.xml")
    a, _ = _plan(tree)
    assert a["action"] == "press_button"
    assert a.get("button") == "back"
    assert a["fastpath_step"] == "taimi_fc_thread_back"


def test_chats_list_opens_people_never_a_tile():
    tree = _load("taimi_chats.xml", "tai_chats2.xml")
    a, _ = _plan(tree)
    assert a["action"] == "tap"
    assert a["fastpath_step"] == "taimi_fc_people_tab"
    assert a["y"] >= 2000
    assert 400 <= a["x"] <= 700


def test_launcher_tree_reopens_taimi():
    # tai2 last_tree was the home screen; job package must not fool us.
    tree = """
    <hierarchy packages="com.sec.android.app.launcher">
     <w id="active" t="active" p="com.sec.android.app.launcher" f="1">
      <n t="Search" xy="540,200"/>
     </w>
    </hierarchy>
    """
    a, _ = _plan(tree, package="com.takimi.android")
    assert a["action"] == "open_app"
    assert a["fastpath_step"] == "taimi_fc_open"


def test_counts_only_after_front_card_changes():
    deck = _load("taimi_uiautomator_people.xml", "taimi_01.xml")
    a1, st = _plan(deck)
    assert a1["fastpath_step"] == "taimi_fc_suggested"
    assert st["taimi_fc"]["awaiting_send"] is True
    assert st["taimi_fc"]["sent_names"] == []
    # Same card still showing the same chip — wait, do not count yet.
    a2, st = _plan(deck, state=st)
    assert a2["fastpath_step"] == "taimi_fc_wait_confirm"
    assert st["taimi_fc"]["sent_names"] == []
    # Next card (Alex) — now count Eleanor.
    next_card = _load("taimi_people.xml")
    a3, st = _plan(next_card, state=st)
    assert "Eleanor" in st["taimi_fc"]["sent_names"]
    assert any("Heyy Eleanor" in c for c in st["taimi_fc"]["sent_chips"])
    # And then it should go on to tap Alex's Coffee chip (need 5).
    assert a3["fastpath_step"] == "taimi_fc_suggested"
    assert "Coffee" in (a3.get("reason") or "")


def test_bulk_router_uses_suggested_chip_planner():
    tree = _load("taimi_people.xml")
    a = plan_bulk_bench(
        INSTR,
        tree,
        [],
        state={},
        package="com.takimi.android",
    )
    assert a
    assert a.get("fastpath_step") == "taimi_fc_suggested"
    assert a.get("action") == "tap"
    assert (a.get("x"), a.get("y")) not in (LIKE, IC)


def test_select_fallback_tree_when_compact_empty():
    from backend.taimi_tree_fallback import is_empty_tree, select_taimi_tree

    compact = _load("taimi_empty_compact.xml")
    full = _load("taimi_uiautomator_people.xml", "taimi_01.xml")
    assert is_empty_tree(compact)
    chosen = select_taimi_tree(compact, full)
    assert chosen == full
    chips = deck_suggested_chips(chosen)
    assert chips, "uiautomator dump must expose suggested chips above Like"
    pick = pick_suggested_chip(chosen, "good evening beautiful", "")
    assert pick
    assert (pick["x"], pick["y"]) not in (LIKE, IC)
    assert 1650 <= int(pick["y"]) <= 1870


def test_plan_uses_uiautomator_dump_chips():
    a, st = _plan(_load("taimi_uiautomator_people.xml", "taimi_01.xml"))
    assert a["action"] == "tap"
    assert a.get("fastpath_step") == "taimi_fc_suggested"
    assert (a["x"], a["y"]) not in (LIKE, IC)
    assert 1650 <= int(a["y"]) <= 1870


def test_empty_compact_waits_for_full_dump_never_backs():
    a, st = _plan(_load("taimi_empty_compact.xml"))
    assert a["action"] == "wait"
    assert a.get("action") != "back"
    assert a.get("_ignore_same_decision") is True
    assert "never Back" in (a.get("reason") or "")
    # After enough empty dumps, fail clearly instead of leaving the app.
    st["taimi_fc"]["empty_dump_waits"] = 12
    a2, st = _plan(_load("taimi_empty_compact.xml"), state=st)
    assert a2["action"] == "fail"
    assert "cannot see suggested chips" in (a2.get("reason") or "").lower() or (
        "empty" in (a2.get("reason") or "").lower()
    )


def test_recovery_redump_and_back_do_not_leave_taimi():
    from backend.recovery import recovery_action

    tree = _load("taimi_empty_compact.xml")
    for strategy in ("redump_tree", "back"):
        a = recovery_action(
            {},
            INSTR,
            tree,
            "com.takimi.android",
            prefer=[strategy],
        )
        assert a["action"] != "back", strategy
        assert a["action"] == "wait", strategy
        assert a.get("_force_redump") is True


def test_recovery_redump_still_backs_for_other_apps():
    from backend.recovery import recovery_action

    a = recovery_action(
        {},
        "send a message on hinge",
        '<hierarchy empty="true" nodes="0"/>',
        "co.hinge.app",
        prefer=["redump_tree"],
    )
    assert a["action"] == "back"


def test_fetch_retries_mode_full_for_taimi():
    from backend.cloud_agent import _fetch_ui_tree_retry

    calls = []
    empty = _load("taimi_empty_compact.xml")
    full = _load("taimi_uiautomator_people.xml", "taimi_01.xml")

    def call_device(_dev, _cmd, params, **_kw):
        calls.append(dict(params or {}))
        if (params or {}).get("mode") == "full":
            return full
        return empty

    info = _fetch_ui_tree_retry(
        "dev",
        call_device,
        preferred_package="com.takimi.android",
        attempts=1,
    )
    assert any(c.get("mode") == "full" for c in calls)
    assert info.get("empty") is False
    assert int(info.get("nodes") or 0) > 0
    assert "Heyy Eleanor" in (info.get("tree") or "") or "Eleanor" in (
        info.get("tree") or ""
    )


def test_cast_prompt_cancel_on_empty_systemui_tree():
    from backend.cast_prompt import (
        CANCEL_XY,
        START_XY,
        cancel_cast_prompt_action,
        looks_like_cast_prompt,
    )

    tree = _load("taimi_cast_prompt_empty.xml")
    assert looks_like_cast_prompt(tree)
    a = cancel_cast_prompt_action(tree, {})
    assert a and a["action"] == "tap"
    assert (a["x"], a["y"]) == CANCEL_XY
    assert (a["x"], a["y"]) != START_XY
    assert "never Start" in (a.get("reason") or "")
    # Once per job
    st = {"dismissed_cast_prompt": True}
    assert cancel_cast_prompt_action(tree, st) is None


def test_plan_dismisses_cast_prompt_before_open():
    tree = _load("taimi_cast_prompt_empty.xml")
    a, st = _plan(tree)
    assert a["action"] == "tap"
    assert a.get("fastpath_step") == "cast_prompt_cancel"
    from backend.cast_prompt import CANCEL_XY, START_XY
    assert (a["x"], a["y"]) == CANCEL_XY
    assert (a["x"], a["y"]) != START_XY
    assert st.get("dismissed_cast_prompt") is True


def test_recovery_dismiss_taps_cancel_not_back():
    from backend.recovery import recovery_action
    from backend.cast_prompt import CANCEL_XY

    tree = _load("taimi_cast_prompt_empty.xml")
    a = recovery_action(
        {},
        INSTR,
        tree,
        "",
        prefer=["dismiss_dialogs"],
    )
    assert a["action"] == "tap"
    assert (a["x"], a["y"]) == CANCEL_XY
    assert a["action"] != "back"
