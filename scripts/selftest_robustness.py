#!/usr/bin/env python3
"""Backend self-test: universal open + stuck recovery against recorded trees.

Usage (repo root):
  python3 scripts/selftest_robustness.py
  python3 -m pytest tests/test_robust_never_stuck.py tests/test_dating_deck.py \\
    tests/test_fallback_preserves_per_app.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.dating_deck import (  # noqa: E402
    dismiss_paywall_action,
    find_free_like_target,
    is_paywall_or_billing,
    mark_like_issued,
    plan_wait_for_next_card,
)
from backend.stuck_recovery import find_safe_dismiss, next_stuck_action  # noqa: E402
from backend.universal_open import plan_universal_open, resolve_open_label  # noqa: E402


def main() -> int:
    fix = ROOT / "tests" / "fixtures" / "dm"
    fails = 0
    print("== universal open labels ==")
    for raw, want in (
        ("com.bumble.app", "Bumble"),
        ("hily", "Hily"),
        ("yubo", "Yubo"),
        ("tagged", "Tagged"),
        ("taimi", "Taimi"),
        ("blk", "BLK"),
        ("whatsapp", "WhatsApp"),
    ):
        got = resolve_open_label(raw)
        ok = got == want
        print(f"  {'OK' if ok else 'FAIL'} {raw!r} → {got!r} (want {want!r})")
        fails += 0 if ok else 1

    print("== plan_universal_open drawer stage ==")
    st: dict = {"open_stage": "home_drawer_search"}
    act = plan_universal_open(
        "Bumble", state=st, fg_package="com.sec.android.app.launcher"
    )
    ok = (
        act.get("open_mode") == "home_drawer_search" and act.get("action") == "open_app"
    )
    print(f"  {'OK' if ok else 'FAIL'} {act.get('open_mode')} app={act.get('app')}")
    fails += 0 if ok else 1

    print("== stuck recovery on fixtures ==")
    xmls = sorted(fix.glob("*.xml")) if fix.exists() else []
    if not xmls:
        print("  WARN no fixtures — skipped")
    for path in xmls[:20]:
        tree = path.read_text(encoding="utf-8")
        # Paid dismiss must never win when Not now present
        if "Get Boost" in tree or "Allow payment" in tree:
            hit = find_safe_dismiss(tree + '\n<n t="Not now" xy="540,2100" c="1"/>')
            if hit and "boost" in hit[2].lower():
                print(f"  FAIL paid dismiss on {path.name}: {hit}")
                fails += 1
                continue
        st2: dict = {}
        a = next_stuck_action(
            st2,
            instruction='reply "hi" to 2 existing chats on Bumble',
            ui_tree=tree,
            package="com.bumble.app",
            prefer_pkg="com.bumble.app",
        )
        if not a.get("action"):
            print(f"  FAIL empty action on {path.name}")
            fails += 1
        else:
            print(f"  OK {path.name}: {a.get('action')} / {st2.get('stuck_stage')}")

    print("== dating deck: free like / wait / paywall ==")
    like_tree = (
        '<h pkg="com.bumble.app">'
        '<n t="Super Like" xy="200,2000"/>'
        '<n t="Like" xy="800,2000" clickable="true"/>'
        "</h>"
    )
    hit = find_free_like_target(like_tree, "bumble")
    ok = bool(hit and hit[0] == 800)
    print(f"  {'OK' if ok else 'FAIL'} free Like (never Super) → {hit}")
    fails += 0 if ok else 1

    pay = (
        '<h pkg="com.android.vending">'
        '<n t="Complete your purchase" xy="540,800"/>'
        '<n t="Not now" xy="540,1900" clickable="true"/>'
        "</h>"
    )
    ok = is_paywall_or_billing(pay, "com.android.vending")
    act_p = dismiss_paywall_action(pay, package="com.android.vending")
    ok2 = bool(
        act_p
        and (
            (
                act_p.get("action") == "tap"
                and "not now" in (act_p.get("label") or "").lower()
            )
            or (act_p.get("action") == "press_button" and act_p.get("button") == "back")
        )
    )
    print(f"  {'OK' if ok and ok2 else 'FAIL'} paywall dismiss → {act_p}")
    fails += 0 if (ok and ok2) else 1

    card_a = '<h><n t="Alex" xy="540,900"/><n t="Like" xy="800,2000"/></h>'
    card_b = '<h><n t="Jordan" xy="540,900"/><n t="Like" xy="800,2000"/></h>'
    st3: dict = {"bulk_swipe": {"done": 0, "target": 2}}
    mark_like_issued(st3, app="bumble", tree=card_a)
    assert st3["bulk_swipe"].get("awaiting_verify") is True
    wait = plan_wait_for_next_card(st3, app="bumble", tree=card_a, planner="selftest")
    ok_w = bool(wait and wait.get("action") == "wait" and wait.get("_card_wait"))
    # Same card again → still waiting (dry-run must exercise poll, not skip)
    wait2 = plan_wait_for_next_card(st3, app="bumble", tree=card_a, planner="selftest")
    ok_w2 = bool(wait2 and wait2.get("action") == "wait")
    plan_wait_for_next_card(st3, app="bumble", tree=card_b, planner="selftest")
    ok_c = int(st3["bulk_swipe"].get("done") or 0) == 1
    ok_cleared = st3["bulk_swipe"].get("awaiting_verify") is False
    print(
        f"  {'OK' if ok_w and ok_w2 and ok_c and ok_cleared else 'FAIL'} "
        f"wait-for-next-card poll→advance done={st3['bulk_swipe'].get('done')}"
    )
    fails += 0 if (ok_w and ok_w2 and ok_c and ok_cleared) else 1

    print(f"\n{'PASS' if fails == 0 else 'FAIL'} — {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
