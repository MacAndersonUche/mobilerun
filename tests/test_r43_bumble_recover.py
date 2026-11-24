"""r43: Bumble/Badoo fixed swipe recovers to the deck; per-app run counts."""

from pathlib import Path

from backend.bumble_fixed_swipe import (
    bumble_fixed_on_deck,
    plan_bumble_fixed_swipe,
    plan_fixed_swipe,
)
from backend.cloud_agent import _fixed_swipe_run, _is_fixed_swipe_action
from backend.dating_run import (
    build_job,
    clean_counts,
    next_job_after,
    run_count,
    split_supported,
)

FIX = Path(__file__).parent / "fixtures" / "dm"
SCROLLED = (FIX / "bumble_people_scrolled_profile_a9f.xml").read_text()
INST = "fixed swipe 5 on bumble"

LAUNCHER = (
    '<hierarchy windows="1" packages="com.sec.android.app.launcher">'
    '<w id="active" t="active" p="com.sec.android.app.launcher" f="1">'
    '<n d="Page 1 of 1." cls="LinearLayout" xy="540,980" b="51,23,1029,1938"/>'
    "</w></hierarchy>"
)


def _plan(tree, st, hist=None, app="bumble"):
    return plan_fixed_swipe(
        INST if app == "bumble" else "fixed swipe 5 on badoo",
        tree,
        hist or [],
        state=st,
        package=f"com.{app}.app" if app == "bumble" else "com.badoo.mobile",
        dry_run=False,
        planner=f"{app}_fixed",
        app=app,
    )


def test_a9f_people_tab_scrolled_profile_is_deck_scroll_top_then_swipe():
    """Exact failed case: People tab, card scrolled into the profile."""
    assert bumble_fixed_on_deck(SCROLLED)
    st = {"bulk_swipe": {"done": 0, "target": 5}}
    top = _plan(SCROLLED, st)
    assert top["action"] == "swipe"
    assert top["fastpath_step"] == "bumble_fixed_scroll_top"
    assert top["y2"] > top["y1"]  # drag down = back to the card top
    assert top.get("button") != "back"
    like = _plan(SCROLLED, st, [top["reason"]])
    assert like["action"] == "swipe"
    assert (like["x1"], like["y1"], like["x2"], like["y2"]) == (200, 1200, 980, 1200)
    assert "1/5" in like["reason"]


def test_keeps_going_to_the_per_run_count_not_capped_at_five():
    st = {"bulk_swipe": {"done": 0, "target": 12}}
    hist = []
    likes = 0
    for _ in range(40):
        act = _plan(SCROLLED, st, hist)
        if act["action"] == "done":
            break
        assert act["action"] == "swipe"
        if act["fastpath_step"] == "bumble_fixed_like_swipe":
            likes += 1
        hist.append(act["reason"])
    assert likes == 12
    assert st["bulk_swipe"]["done"] == 12
    assert act["action"] == "done" and "12/12" in act["reason"]


def test_launcher_after_open_waits_never_back():
    st = {"bulk_swipe": {"done": 0, "target": 5}}
    a1 = _plan(LAUNCHER, st)
    a2 = _plan(LAUNCHER, st, [a1["reason"]])
    a3 = _plan(LAUNCHER, st, [a1["reason"], a2["reason"]])
    assert a1["action"] == "wait" and a2["action"] == "wait"
    assert a3["action"] == "open_app" and a3["package"] == "com.bumble.app"
    assert all(a.get("button") != "back" for a in (a1, a2, a3))


def test_recover_then_swipe_after_back_on_deck():
    # Chats tab selected (only non-clickable tab), Chats pane on screen.
    CLICK = ' c="1"'
    tabs = "".join(
        f'<n t="{t}" d="{t}" cls="View"{"" if t == "Chats" else CLICK} '
        f'xy="{x},2197" b="{x - 108},2120,{x + 108},2274"/>'
        for t, x in (("Profile", 108), ("Discover", 324), ("People", 540),
                     ("Liked You", 756), ("Chats", 972))
    )
    chats = (
        '<hierarchy windows="1" packages="com.bumble.app">'
        '<w id="active" t="active" p="com.bumble.app" f="1">'
        '<n t="Connections start here" cls="TextView" xy="540,1159" b="100,1111,980,1207"/>'
        f"{tabs}</w></hierarchy>"
    )
    assert not bumble_fixed_on_deck(chats)
    st = {"bulk_swipe": {"done": 2, "target": 5}}
    rec = _plan(chats, st)
    assert rec["action"] == "tap" and rec["fastpath_step"] == "bumble_fixed_recover_tab"
    assert (rec["x"], rec["y"]) == (540, 2197)
    top = _plan(SCROLLED, st, [rec["reason"]])
    assert top["fastpath_step"] == "bumble_fixed_scroll_top"
    like = _plan(SCROLLED, st, [rec["reason"], top["reason"]])
    assert "3/5" in like["reason"]
    assert st["bulk_swipe"]["_fixed_recover_n"] == 0


def test_badoo_chats_taps_encounters_tab():
    tree = (
        '<hierarchy packages="com.badoo.mobile"><w p="com.badoo.mobile">'
        '<n d="Discover" i="com.badoo.mobile:id/nav_bar_button_people_nearby" c="1" xy="108,2200" b="0,2130,216,2270"/>'
        '<n d="Encounters" i="com.badoo.mobile:id/nav_bar_button_encounters" c="1" xy="324,2200" b="216,2130,432,2270"/>'
        '<n d="Chats" i="com.badoo.mobile:id/nav_bar_button_connections" xy="756,2200" b="648,2130,864,2270"/>'
        '<n t="Roya" xy="400,500" b="100,450,700,550"/>'
        "</w></hierarchy>"
    )
    st = {"bulk_swipe": {"done": 0, "target": 5}}
    act = _plan(tree, st, app="badoo")
    assert act["action"] == "tap" and (act["x"], act["y"]) == (324, 2200)


def test_cloud_agent_fixed_helpers():
    st = {"bulk_swipe": {"done": 0, "target": 5}}
    act = _plan(SCROLLED, st)
    assert _is_fixed_swipe_action(act)
    assert _fixed_swipe_run("fixed swipe 20 on bumble", {})
    assert _fixed_swipe_run("x", {"swipe_mode": "fixed"})
    # r45: Hily / Hinge / Yubo first contact are fixed (no LLM) too
    assert _fixed_swipe_run("send 2 first contact messages on hily", {})
    assert not _is_fixed_swipe_action({"action": "swipe", "planner": "llm"})


def test_per_app_counts_drive_each_job():
    counts = clean_counts(
        {"bumble": 20, "com.badoo.mobile": 7, "hily": 12, "facebook": 80, "x": 3}
    )
    assert counts == {
        "com.bumble.app": 20,
        "com.badoo.mobile": 7,
        "com.hily.app": 12,
        "com.facebook.katana": 80,
    }
    assert run_count("com.facebook.katana", None, counts) == 50  # FB cap
    assert run_count("com.hily.app", None, counts) == 5  # Hily messages cap
    assert run_count("com.hily.app#like", None, counts) == 12  # likes after
    queue, _ = split_supported(["bumble", "badoo", "hily"])
    job = build_job(device_id="d", queue=queue, count=None, dry_run=False, counts=counts)
    assert job["instruction"] == "fixed swipe 20 on bumble"
    job["status"] = "completed"
    j2 = next_job_after(job)
    assert j2["instruction"] == "fixed swipe 7 on badoo"
    j2["status"] = "failed"
    j3 = next_job_after(j2)
    # r46: Hily = one job, 5 messages (cap) then likes up to the mode max
    assert j3["instruction"] == "fixed hily message 5 likes 30"
    j3["status"] = "completed"
    assert next_job_after(j3) is None
