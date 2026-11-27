"""Auto-dismiss foreign overlays that steal the foreground from the target app.

Mac's rule (PR #64): when the active/foreground window package is not the
dating/social target (Samsung Pay quick-access, SystemUI dialogs, Edge panels,
other apps' overlays), the runner dismisses via Back / safe Close / tap-outside,
re-checks, and continues. Never fail just because an overlay is in front.
Never tap paid / payment-allow controls.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("mobilerun.overlay_dismiss")

# Packages / substrings that are never the dating/social job target
_FOREIGN_OVERLAY_MARKERS: Tuple[str, ...] = (
    "com.samsung.android.spay",
    "samsung.android.spay",
    "samsungpay",
    "spay",
    "com.android.systemui",
    "systemui",
    "com.samsung.android.app.cocktailbarservice",
    "cocktailbarservice",
    "edgepanels",
    "com.samsung.android.app.cocktailbar",
    "mobilerun.selfhosted",
    "ai.mobilerun.selfhosted",
    "com.samsung.android.bixby",
    "bixby",
    "com.samsung.android.smartcapture",
    "smartcapture",
    "com.samsung.android.app.routines",
    "com.android.permissioncontroller",
    "permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.samsung.android.honeyboard",  # IME steal — Back dismisses
    # NOTE: home launchers are NOT overlays — Back on launcher does nothing
    # useful and blocks open_app (APK 540: job pressed Back on home then failed).
)

# Home screen packages — never Back-dismiss; cloud must open_app instead
_LAUNCHER_MARKERS: Tuple[str, ...] = (
    "com.sec.android.app.launcher",
    "com.android.launcher",
    "com.google.android.apps.nexuslauncher",
    "com.android.launcher3",
    "com.miui.home",
    "launcher",
)

# Safe dismiss labels (exact-ish). Never payment / paid upsells.
_SAFE_CLOSE_LABELS: Tuple[str, ...] = (
    "Close",
    "Not now",
    "No thanks",
    "Maybe later",
    "Dismiss",
    "Cancel",
    "Got it",
    "Got it!",
    "OK",
    "Okay",
    "Later",
    "Skip",
    "No",
)

# Never tap these when dismissing a foreign overlay
_NEVER_TAP_SUBSTRINGS: Tuple[str, ...] = (
    "allow payment",
    "add payment",
    "confirm payment",
    "pay now",
    "pay with",
    "get boost",
    "buy",
    "purchase",
    "subscribe",
    "upgrade",
    "add card",
    "credit card",
    "samsung pay",
    "google pay",
    "apple pay",
    "checkout",
    "continue to pay",
    "enable pay",
    "open pay",
    "use samsung pay",
    "boost",
    "premium",
    "crush",
    "super like",
    "superswipe",
)


def _pkg_matches_target(pkg: str, target: str) -> bool:
    p = (pkg or "").lower().strip()
    t = (target or "").lower().strip()
    if not p or not t:
        return False
    return p == t or t in p or p in t


def is_launcher_package(pkg: str) -> bool:
    p = (pkg or "").lower().strip()
    if not p:
        return False
    return any(m in p for m in _LAUNCHER_MARKERS)


def is_foreign_overlay_package(pkg: str, target_package: str = "") -> bool:
    """True when ``pkg`` is a known non-target overlay / chrome (not home)."""
    p = (pkg or "").lower().strip()
    if not p:
        return False
    if target_package and _pkg_matches_target(p, target_package):
        return False
    # Home screen is not an overlay — never Back-dismiss it
    if is_launcher_package(p):
        return False
    return any(m in p for m in _FOREIGN_OVERLAY_MARKERS)


_IME_MARKERS: Tuple[str, ...] = (
    "com.samsung.android.honeyboard",
    "com.google.android.inputmethod",
    "com.touchtype.swiftkey",
    "inputmethod",
)


def _is_ime_package(pkg: str) -> bool:
    p = (pkg or "").lower()
    return bool(p) and any(m in p for m in _IME_MARKERS)


def packages_in_tree(ui_tree: str) -> List[str]:
    """Unique package names from ``packages=`` attr and ``<w p=...>`` windows."""
    tree = ui_tree or ""
    out: List[str] = []
    seen: set = set()
    m = re.search(r'\bpackages="([^"]+)"', tree, re.I)
    if m:
        for part in m.group(1).split(","):
            p = part.strip()
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
    for wm in re.finditer(r'<w\b[^>]*\bp="([^"]+)"', tree, re.I):
        p = wm.group(1).strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def active_window_package(ui_tree: str, reported_package: str = "") -> str:
    """Package of the active ``<w id="active">`` window, else reported FG."""
    tree = ui_tree or ""
    m = re.search(
        r'<w\b[^>]*\bid="active"[^>]*\bp="([^"]+)"',
        tree,
        re.I,
    )
    if not m:
        m = re.search(
            r'<w\b[^>]*\bp="([^"]+)"[^>]*\bid="active"',
            tree,
            re.I,
        )
    if not m:
        m = re.search(
            r'<w\b[^>]*\bf="1"[^>]*\bp="([^"]+)"',
            tree,
            re.I,
        )
    if m:
        return m.group(1).strip()
    return (reported_package or "").strip()


def detect_foreign_overlay(
    ui_tree: str,
    target_package: str,
    *,
    reported_package: str = "",
) -> Optional[str]:
    """Return the foreign overlay package if FG/active != target, else None.

    Also detects when a foreign overlay window is listed alongside the target
    (spay + dating) even if the dump preferred the target as ``active``.
    """
    target = (target_package or "").strip()
    if not target:
        return None
    active = active_window_package(ui_tree, reported_package)
    # Launcher/home → not a dismissable overlay (open_app instead)
    if active and is_launcher_package(active):
        return None
    # r53 (27 Nov 2026, task_bcfe1e117d926e6e): the keyboard over the
    # target app is part of typing, not an overlay. Back-dismissing it on
    # Hinge's like sheet pressed Back twice — keyboard, then the sheet and
    # Hinge itself — so the comment was never sent. Only an IME that is in
    # front with no target window at all is treated as foreign.
    pkgs_all = packages_in_tree(ui_tree)
    target_listed = any(_pkg_matches_target(p, target) for p in pkgs_all)
    if target_listed and (
        not active or _is_ime_package(active) or _pkg_matches_target(active, target)
    ):
        others = [
            p for p in pkgs_all
            if not _pkg_matches_target(p, target) and not _is_ime_package(p)
        ]
        if not others and (not active or _is_ime_package(active)
                           or _pkg_matches_target(active, target)):
            rep = (reported_package or "").strip()
            if not rep or _is_ime_package(rep) or _pkg_matches_target(rep, target):
                return None
    if active and is_foreign_overlay_package(active, target):
        return active
    if active and not _pkg_matches_target(active, target):
        # Wrong app in front (not necessarily in the marker list)
        if not _pkg_matches_target(active, target):
            return active
    # Multi-window: foreign overlay present while target also listed
    pkgs = packages_in_tree(ui_tree)
    foreign = [
        p
        for p in pkgs
        if is_foreign_overlay_package(p, target) and not _pkg_matches_target(p, target)
    ]
    target_present = any(_pkg_matches_target(p, target) for p in pkgs)
    if foreign and (target_present or not pkgs):
        # Prefer spay / systemui over selfhosted when both present
        for prefer in ("spay", "systemui", "cocktail", "edge", "permission"):
            for p in foreign:
                if prefer in p.lower():
                    return p
        return foreign[0]
    # Reported FG alone
    rep = (reported_package or "").strip()
    if rep and is_foreign_overlay_package(rep, target):
        return rep
    if rep and not _pkg_matches_target(rep, target) and not target_present:
        return rep
    return None


def _label_is_forbidden(label: str) -> bool:
    low = (label or "").strip().lower()
    if not low:
        return True
    return any(tok in low for tok in _NEVER_TAP_SUBSTRINGS)


def _safe_close_center(ui_tree: str) -> Optional[Tuple[int, int, str]]:
    """Find a safe Close/Not now control; never payment/paid labels.

    Include SystemUI / cocktailbar / spay windows — those hosts own the Close
    button that clears the foreign overlay.
    """
    try:
        from dm_heuristics import _parse_compact_nodes
    except ImportError:
        from backend.dm_heuristics import _parse_compact_nodes  # type: ignore

    want = {s.lower() for s in _SAFE_CLOSE_LABELS}
    nodes = _parse_compact_nodes(ui_tree, include_systemui=True)
    # Prefer exact safe labels; skip forbidden payment/paid copy
    for n in nodes:
        for field in ("text", "desc", "label"):
            val = str(n.get(field) or "").strip()
            if not val or val.lower() not in want:
                continue
            if _label_is_forbidden(val):
                continue
            return (int(n["x"]), int(n["y"]), val)
    return None


def plan_dismiss_foreign_overlay(
    ui_tree: str,
    overlay_package: str,
    target_package: str = "",
    *,
    planner: str = "overlay_dismiss",
) -> Dict[str, Any]:
    """Action to clear a foreign overlay — Back / safe Close / tap-outside.

    Never returns a tap on paid or payment-allow controls.
    """
    overlay = (overlay_package or "unknown").strip()
    close = _safe_close_center(ui_tree)
    if close:
        x, y, lab = close
        reason = (
            f"Dismiss foreign overlay {overlay} → tap '{lab}' "
            f"(target={target_package or '-'}) ({planner})"
        )
        logger.info("overlay_dismiss tap label=%s pkg=%s xy=%s,%s", lab, overlay, x, y)
        return {
            "action": "tap",
            "x": x,
            "y": y,
            "reason": reason,
            "planner": planner,
            "llm_provider": None,
            "label": lab,
            "overlay_dismiss": True,
            "overlay_package": overlay,
            "fastpath_step": "overlay_dismiss_close",
            "_fastpath_step": "overlay_dismiss_close",
        }
    # Prefer Back (global) over tap-outside — tap-outside can hit status-bar
    # chrome and trip the tap firewall.
    reason = (
        f"Dismiss foreign overlay {overlay} → Back "
        f"(target={target_package or '-'}) ({planner})"
    )
    logger.info("overlay_dismiss back pkg=%s", overlay)
    return {
        "action": "press_button",
        "button": "back",
        "reason": reason,
        "planner": planner,
        "llm_provider": None,
        "overlay_dismiss": True,
        "overlay_package": overlay,
        "fastpath_step": "overlay_dismiss_back",
        "_fastpath_step": "overlay_dismiss_back",
    }


def dismiss_foreign_overlays_before_plan(
    *,
    device_id: str,
    call_device,
    execute_action,
    fetch_tree,
    ui_tree: str,
    tree_info: Dict[str, Any],
    target_package: str,
    history: Optional[List[str]] = None,
    state: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3,
) -> Tuple[str, Dict[str, Any], List[str]]:
    """Dismiss foreign overlays up to ``max_attempts``; return updated tree.

    Never raises / never marks the job failed for overlays alone.
    """
    hist = list(history or [])
    st = state if isinstance(state, dict) else {}
    tree = ui_tree or ""
    info = dict(tree_info or {})
    target = (target_package or str(st.get("target_package") or "")).strip()
    if not target:
        logger.info("overlay_dismiss skip — no target_package")
        return tree, info, hist

    for attempt in range(max(1, max_attempts)):
        active = active_window_package(tree, str(info.get("package") or ""))
        overlay = detect_foreign_overlay(
            tree,
            target,
            reported_package=str(info.get("package") or ""),
        )
        # Always log so Mac can verify the hook runs (0 dismissals ≠ skipped)
        logger.info(
            "overlay_dismiss check attempt=%s/%s target=%s active=%s foreign=%s",
            attempt + 1,
            max_attempts,
            target,
            active or "-",
            overlay or "none",
        )
        if not overlay:
            break
        # If active already matches target and foreign is only a side window
        # that doesn't own focus, skip dismiss (Android preferred dump).
        active = active_window_package(tree, str(info.get("package") or ""))
        if active and _pkg_matches_target(active, target):
            # Still dismiss when foreign package is the *reported* FG empty case
            # or spay is listed as active id window
            if not is_foreign_overlay_package(active, target):
                # Side-window only — try one Back if spay still in packages list
                pkgs = packages_in_tree(tree)
                if not any(is_foreign_overlay_package(p, target) for p in pkgs):
                    break
        act = plan_dismiss_foreign_overlay(
            tree, overlay, target, planner="overlay_dismiss"
        )
        logger.info(
            "auto-dismiss foreign overlay attempt=%s/%s pkg=%s action=%s",
            attempt + 1,
            max_attempts,
            overlay,
            act.get("action"),
        )
        try:
            summary = execute_action(device_id, act)
        except Exception as e:
            logger.warning("overlay dismiss execute failed: %s", e)
            summary = f"overlay dismiss error: {e}"
        reason = str(act.get("reason") or summary or "overlay dismiss")
        hist.append(reason)
        st["overlay_dismissals"] = int(st.get("overlay_dismissals") or 0) + 1
        st["last_overlay_dismissed"] = overlay
        try:
            info = fetch_tree()
            tree = str(info.get("tree") or tree)
        except Exception as e:
            logger.warning("overlay dismiss re-fetch failed: %s", e)
            break
        # If we cleared the foreign FG, clear empty flag so planning continues
        new_overlay = detect_foreign_overlay(
            tree, target, reported_package=str(info.get("package") or "")
        )
        if not new_overlay:
            info["empty"] = False
            logger.info("foreign overlay cleared — continuing job target=%s", target)
            break
    return tree, info, hist
