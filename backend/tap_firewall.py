"""Runner-level tap firewall — resolve what a tap would actually hit.

Before every tap, take a fresh a11y tree, find the topmost visible clickable
node containing the point (window z-order), and refuse paid / dry-run-mutating
targets. Empty trees require vision confirmation of the intended label.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("mobilerun.tap_firewall")

# Dry-run: refuse ANY of these on the resolved node / ancestors / desc / id
_DRY_RUN_REFUSE = (
    "like",
    "crush",
    "major crush",
    "super like",
    "superswipe",
    "super swipe",
    "superboost",
    "super boost",
    "rose",
    "boost",
    "send",
    "send like",
    "send a like",
    "heart",
    "likebtn",
    "likebutton",
    "actionbutton_like",
    "actionbutton_crush",
    "chatbtn",
    "chat_btn",
    "vote yes",
    "voteyes",
    "pass",
    "skip",
    "dislike",
)

# Live mode: paid / irreversible premium only (Crush etc. stay blocked)
_LIVE_PAID_REFUSE = (
    "crush",
    "major crush",
    "message before match",
    "majorcrush",
    "super like",
    "superswipe",
    "super swipe",
    "rose",
    "boost",
    "spotlight",
    "gold",
    "premium",
    "buy credits",
    "subscribe",
    "yubucks",
    "blast",
    "unlock infinity",
    "instant chat",
    "hingex",
    "hinge+",
    "rewind",
    "send a super like",
    "send superswipe",
)


def _norm_blob(node: Dict[str, Any]) -> str:
    parts = [
        str(node.get("text") or ""),
        str(node.get("desc") or ""),
        str(node.get("hint") or ""),
        str(node.get("label") or ""),
        str(node.get("id") or ""),
        str(node.get("cls") or ""),
    ]
    return " ".join(parts).lower()


def node_matches_keywords(node: Dict[str, Any], keywords: Sequence[str]) -> bool:
    blob = _norm_blob(node)
    if not blob.strip():
        return False
    for kw in keywords:
        k = (kw or "").lower().strip()
        if not k:
            continue
        # Whole-word for short ambiguous tokens like "like" / "send" / "pass"
        if k in ("like", "send", "pass", "skip", "heart", "rose"):
            if re.search(rf"\b{re.escape(k)}\b", blob):
                return True
            # resource-id forms
            if k in blob.replace("_", "").replace("-", ""):
                # likeBtn / ActionButton_LIKE
                compact = blob.replace("_", "").replace("-", "").replace(" ", "")
                if k in compact:
                    return True
            continue
        if k in blob:
            return True
    return False


def _point_in_node(x: int, y: int, n: Dict[str, Any]) -> bool:
    x1, y1, x2, y2 = n.get("x1"), n.get("y1"), n.get("x2"), n.get("y2")
    if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
        return int(x1) <= x <= int(x2) and int(y1) <= y <= int(y2)
    # Fall back to near-center hitbox (~48dp)
    cx, cy = int(n.get("x") or -9999), int(n.get("y") or -9999)
    return abs(cx - x) <= 48 and abs(cy - y) <= 48


def resolve_topmost_clickable_at(
    tree: str,
    x: int,
    y: int,
    *,
    include_invisible: bool = False,
) -> Optional[Dict[str, Any]]:
    """Topmost visible clickable whose bounds contain (x,y).

    Window order: later windows in the dump sit above earlier ones; within a
    window, later nodes are treated as higher z.
    """
    try:
        from dm_heuristics import _parse_compact_nodes
    except ImportError:
        from backend.dm_heuristics import _parse_compact_nodes  # type: ignore

    nodes = _parse_compact_nodes(
        tree,
        include_systemui=True,
        include_invisible=include_invisible,
        with_window_order=True,
    )
    hits: List[Dict[str, Any]] = []
    for n in nodes:
        if not n.get("clickable") and not n.get("editable"):
            continue
        if not include_invisible and not n.get("visible", True):
            continue
        if not include_invisible and n.get("off_screen"):
            continue
        if _point_in_node(x, y, n):
            hits.append(n)
    if not hits:
        return None
    # Highest window_index, then highest node_index within window
    hits.sort(
        key=lambda n: (
            int(n.get("window_index") or 0),
            int(n.get("node_index") or 0),
        )
    )
    return hits[-1]


def intended_target_matches(
    resolved: Dict[str, Any],
    action: Dict[str, Any],
) -> bool:
    """True when resolved node plausibly matches the planner's intended target."""
    want_bits = [
        str(action.get("label") or ""),
        str(action.get("text") or ""),
        str(action.get("element") or ""),
        str(action.get("target") or ""),
        str(action.get("intended_id") or ""),
        str(action.get("resource_id") or ""),
    ]
    want = " ".join(b for b in want_bits if b).strip().lower()
    if not want:
        # No declared intent — only paid/keyword checks apply
        return True
    blob = _norm_blob(resolved)
    # Any token from intent appearing in the resolved node
    for tok in re.findall(r"[a-z0-9_]{3,}", want):
        if tok in ("tap", "open", "bulk", "heuristic", "planner"):
            continue
        if tok in blob:
            return True
    # Exact label equality
    for field in ("text", "desc", "label"):
        val = str(resolved.get(field) or "").strip().lower()
        if val and val in want:
            return True
    return False


def tap_is_forbidden(
    resolved: Optional[Dict[str, Any]],
    *,
    dry_run: bool,
    action: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return a refuse reason, or None if the tap may proceed."""
    if resolved is None:
        return "tap firewall: could not resolve topmost node at point"
    action = action or {}
    kws = _DRY_RUN_REFUSE if dry_run else _LIVE_PAID_REFUSE
    if node_matches_keywords(resolved, kws):
        kind = "dry-run mutating" if dry_run else "paid"
        return (
            f"tap firewall: refuse {kind} target "
            f"{(resolved.get('label') or resolved.get('id') or '?')[:60]!r}"
        )
    if dry_run and not intended_target_matches(resolved, action):
        # Only enforce intent match when the planner named a target
        named = any(
            action.get(k) for k in ("label", "text", "element", "target", "intended_id")
        )
        if named:
            return (
                "tap firewall: resolved node is not the intended target "
                f"(got {(resolved.get('label') or resolved.get('id') or '?')[:40]!r})"
            )
    return None


def guard_tap_action(
    action: Dict[str, Any],
    tree: str,
    *,
    dry_run: bool,
    vision_confirmed_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a tap against a (fresh) tree. Returns action or fail action."""
    try:
        x, y = int(action["x"]), int(action["y"])
    except (KeyError, TypeError, ValueError):
        return {
            "action": "fail",
            "reason": "tap firewall: missing tap coordinates",
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
        }

    # Off-screen absolute refuse
    if x < 0 or y < 0 or x > 2000 or y > 2800:
        return {
            "action": "fail",
            "reason": f"tap firewall: off-screen coordinates ({x},{y})",
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
        }

    tree_l = (tree or "").strip()
    empty = (
        not tree_l
        or 'empty="true"' in tree_l
        or len(tree_l) < 80
        or re.search(r'app_nodes="0"', tree_l)
    )
    if empty:
        # Empty tree apps (Hinge Discover) — require vision confirmation
        want = str(
            action.get("label")
            or action.get("text")
            or action.get("element")
            or action.get("target")
            or ""
        ).strip()
        confirmed = (vision_confirmed_label or "").strip().lower()
        if want and confirmed and want.lower() in confirmed:
            out = dict(action)
            out["_tap_firewall"] = "vision_confirmed"
            return out
        return {
            "action": "fail",
            "reason": (
                "tap firewall: empty/sparse tree — refuse tap without "
                "screenshot-vision confirmation of target label"
            ),
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "needs_vision": True,
        }

    resolved = resolve_topmost_clickable_at(tree, x, y)
    reason = tap_is_forbidden(resolved, dry_run=dry_run, action=action)
    if reason:
        logger.warning("%s at (%s,%s)", reason, x, y)
        return {
            "action": "fail",
            "reason": reason,
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "_resolved_label": (resolved or {}).get("label"),
            "_resolved_id": (resolved or {}).get("id"),
        }
    out = dict(action)
    if resolved:
        out["_resolved_label"] = resolved.get("label")
        out["_resolved_id"] = resolved.get("id")
        out["_tap_firewall"] = "ok"
    return out
