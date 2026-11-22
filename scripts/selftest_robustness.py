#!/usr/bin/env python3
"""Backend self-test: universal open + stuck recovery against recorded trees.

Usage (repo root):
  python3 scripts/selftest_robustness.py
  python3 -m pytest tests/test_robust_never_stuck.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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

    print(f"\n{'PASS' if fails == 0 else 'FAIL'} — {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
