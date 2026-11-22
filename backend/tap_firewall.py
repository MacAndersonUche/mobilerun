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
        # Whole-word for short ambiguous tokens like "like" / "send" / "pass".
        # Do NOT treat "matches" / "dislike" / "password" as containing "like"/"pass".
        if k in ("like", "send", "pass", "skip", "heart", "rose"):
            if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", blob):
                return True
            compact = blob.replace("_", "").replace("-", "").replace(" ", "")
            # Known compound resource-id / camelCase forms only
            compounds = (
                f"{k}btn",
                f"{k}button",
                f"{k}icon",
                f"actionbutton{k}",
                f"btn{k}",
                f"gamepad{k}",
                f"voteyes" if k == "like" else "",
                f"voteno" if k == "pass" else "",
            )
            if any(c and c in compact for c in compounds):
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


# Labels that block a tap when ANY node (clickable or not) covers the point.
# Real Hily Crush is a non-clickable ImageView d="Crush" over bottom-nav.
_POINT_BLOCK_LABELS = (
    "crush",
    "major crush",
    "like",
    "super like",
    "superswipe",
    "super swipe",
    "rose",
    "boost",
    "send like",
    "send a like",
    "heart",
    "likebtn",
    "actionbutton_like",
    "actionbutton_crush",
    "message before match",
    "vote yes",
    "pass",
    "dislike",
)

_NAV_INTENT_MARKERS = (
    "chat",
    "chats",
    "messages",
    "matches",
    "connections",
    "discover",
    "people",
    "finder",
    "feed",
    "activity",
    "me",
    "home",
    "inbox",
    "encounters",
    "bottom nav",
    "bottomnav",
    "tab",
)


def _all_nodes_at(
    tree: str,
    x: int,
    y: int,
    *,
    include_invisible: bool = False,
    clickable_only: bool = False,
) -> List[Dict[str, Any]]:
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
        if clickable_only and not (n.get("clickable") or n.get("editable")):
            continue
        if not include_invisible and not n.get("visible", True):
            continue
        if not include_invisible and n.get("off_screen"):
            continue
        if _point_in_node(x, y, n):
            hits.append(n)
    return hits


def find_blocking_label_at(
    tree: str,
    x: int,
    y: int,
    keywords: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Any visible node (clickable or not) at (x,y) matching paid/mutate labels.

    Dump order is NOT z-order — sheet Crush ImageViews often appear *before*
    bottom-nav in the tree. Matching by label at the point is authoritative.
    """
    kws = keywords or _POINT_BLOCK_LABELS
    for n in _all_nodes_at(tree, x, y):
        if node_matches_keywords(n, kws):
            return n
    return None


def _point_near_node(x: int, y: int, n: Dict[str, Any], pad: int = 28) -> bool:
    """True if (x,y) is inside node bounds expanded by ``pad`` (nav tap jitter)."""
    x1, y1, x2, y2 = n.get("x1"), n.get("y1"), n.get("x2"), n.get("y2")
    if None not in (x1, y1, x2, y2):
        return (
            int(x1) - pad <= x <= int(x2) + pad
            and int(y1) - pad <= y <= int(y2) + pad
        )
    cx, cy = int(n.get("x") or -9999), int(n.get("y") or -9999)
    return abs(cx - x) <= 48 + pad and abs(cy - y) <= 48 + pad


def resolve_topmost_clickable_at(
    tree: str,
    x: int,
    y: int,
    *,
    include_invisible: bool = False,
) -> Optional[Dict[str, Any]]:
    """Best-effort clickable at (x,y). Prefer smallest bounds (leaf over parent).

    Dump order is unreliable for z-order (sheet nodes may precede nav). Prefer
    the smallest-area clickable hit; callers must also run find_blocking_label_at.
    If nothing contains the exact point, snap to a nearby clickable (child-label
    / bounds jitter — e.g. BLK Matches tab at 674,2223 just outside bounds).
    """
    hits = _all_nodes_at(
        tree, x, y, include_invisible=include_invisible, clickable_only=True
    )
    if not hits:
        try:
            from dm_heuristics import _parse_compact_nodes
        except ImportError:
            from backend.dm_heuristics import _parse_compact_nodes  # type: ignore

        near: List[Dict[str, Any]] = []
        for n in _parse_compact_nodes(
            tree, include_systemui=True, include_invisible=include_invisible
        ):
            if not (n.get("clickable") or n.get("editable")):
                continue
            if not include_invisible and not n.get("visible", True):
                continue
            if not include_invisible and n.get("off_screen"):
                continue
            if _point_near_node(x, y, n, pad=28):
                near.append(n)
        hits = near
    if not hits:
        return None

    def _area(n: Dict[str, Any]) -> int:
        x1, y1, x2, y2 = n.get("x1"), n.get("y1"), n.get("x2"), n.get("y2")
        if None in (x1, y1, x2, y2):
            return 10**9
        return max(1, int(x2) - int(x1)) * max(1, int(y2) - int(y1))

    hits.sort(
        key=lambda n: (
            _area(n),
            -int(n.get("window_index") or 0),
            -int(n.get("node_index") or 0),
        )
    )
    return hits[0]


def labels_at_point(tree: str, x: int, y: int) -> str:
    """All visible labels covering (x,y) — includes child TextViews of a container."""
    parts: List[str] = []
    for n in _all_nodes_at(tree, x, y):
        parts.append(_norm_blob(n))
    # Also include nearby nodes (label-on-child + tap jitter)
    if not parts:
        try:
            from dm_heuristics import _parse_compact_nodes
        except ImportError:
            from backend.dm_heuristics import _parse_compact_nodes  # type: ignore

        for n in _parse_compact_nodes(tree, include_systemui=True):
            if _point_near_node(x, y, n, pad=28):
                parts.append(_norm_blob(n))
    return " ".join(p for p in parts if p).strip()


def _looks_like_nav_tap(
    action: Dict[str, Any], resolved: Optional[Dict[str, Any]]
) -> bool:
    bits = " ".join(
        str(action.get(k) or "")
        for k in ("label", "text", "element", "target", "reason", "intended_id")
    ).lower()
    if any(m in bits for m in _NAV_INTENT_MARKERS):
        # "Open chats/messages tab" etc.
        if any(
            m in bits
            for m in (
                "tab",
                "nav",
                "bottom",
                "open chats",
                "open matches",
                "open messages",
                "open discover",
                "open people",
            )
        ) or any(
            m in bits for m in ("chats", "messages", "matches", "finder", "discover")
        ):
            return True
    if resolved:
        blob = _norm_blob(resolved)
        rid = str(resolved.get("id") or "").lower()
        if "bottomnav" in rid or "nav_bar" in rid or "tab_" in rid:
            return True
        if (
            any(
                m in blob
                for m in (
                    "chats",
                    "messages",
                    "matches",
                    "discover",
                    "people",
                    "finder",
                    "activity",
                )
            )
            and int(resolved.get("y") or 0) > 2000
        ):
            return True
    return False


def intended_target_matches(
    resolved: Dict[str, Any],
    action: Dict[str, Any],
    *,
    point_labels: str = "",
) -> bool:
    """True when resolved node (or child labels at the point) match intent."""
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
    blob = f"{_norm_blob(resolved)} {point_labels or ''}".lower()
    # Any token from intent appearing in the resolved node / children
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
    point_labels: str = "",
) -> Optional[str]:
    """Return a refuse reason, or None if the tap may proceed."""
    if resolved is None:
        return "tap firewall: could not resolve topmost node at point"
    action = action or {}
    kws = _DRY_RUN_REFUSE if dry_run else _LIVE_PAID_REFUSE
    # Check resolved + child labels at the point (container with TextView child)
    probe = dict(resolved)
    if point_labels:
        probe = {
            **resolved,
            "label": f"{resolved.get('label') or ''} {point_labels}".strip(),
        }
    if node_matches_keywords(probe, kws):
        kind = "dry-run mutating" if dry_run else "paid"
        return (
            f"tap firewall: refuse {kind} target "
            f"{(resolved.get('label') or resolved.get('id') or '?')[:60]!r}"
        )
    if dry_run and not intended_target_matches(
        resolved, action, point_labels=point_labels
    ):
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

# Free-nav / messaging targets vision may green-light on empty trees
_VISION_ALLOW_TOKENS = (
    "chat",
    "chats",
    "messages",
    "matches",
    "connections",
    "discover",
    "people",
    "finder",
    "like",
    "pass",
    "skip",
    "send",
    "composer",
    "compose",
    "type a message",
    "aa",
    "back",
    "got it",
    "don't allow",
    "dont allow",
    "not now",
    "close",
    "row",
    "thread",
)


def _detect_app_from_tree(tree: str) -> Optional[str]:
    try:
        from dm_heuristics import detect_dm_app
    except ImportError:
        from backend.dm_heuristics import detect_dm_app  # type: ignore

    return detect_dm_app(tree) or None


def guard_tap_action(
    action: Dict[str, Any],
    tree: str,
    *,
    dry_run: bool,
    vision_confirmed_label: Optional[str] = None,
    app: Optional[str] = None,
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

    # Status bar / SystemUI clock band — never a planner target
    if y < 90:
        return {
            "action": "fail",
            "reason": f"tap firewall: refuse status-bar tap ({x},{y})",
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
        }
    point_labels = labels_at_point(tree, x, y) if (tree or "").strip() else ""
    if "com.android.systemui" in point_labels and y < 200:
        return {
            "action": "fail",
            "reason": f"tap firewall: refuse SystemUI/status-bar tap ({x},{y})",
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
        # Empty tree apps (Hinge Discover) — vision may green-light free nav
        want = str(
            action.get("label")
            or action.get("text")
            or action.get("element")
            or action.get("target")
            or action.get("reason")
            or ""
        ).strip()
        confirmed = (vision_confirmed_label or "").strip().lower()
        want_l = want.lower()
        vision_ok = bool(confirmed) and (
            (want_l and want_l in confirmed)
            or any(tok in confirmed for tok in _VISION_ALLOW_TOKENS)
        )
        # Still refuse paid tokens even with vision
        paid_hit = any(
            p in confirmed or p in want_l
            for p in (
                "rose",
                "crush",
                "super like",
                "superswipe",
                "boost",
                "gold",
                "premium",
                "spotlight",
            )
        )
        if vision_ok and not paid_hit:
            out = dict(action)
            out["_tap_firewall"] = "vision_confirmed"
            return out
        return {
            "action": "fail",
            "reason": (
                "tap firewall: empty/sparse tree — refuse tap without "
                "screenshot-vision confirmation of free nav/like/pass/"
                "chat-row/composer/send (paid still blocked)"
            ),
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "needs_vision": True,
        }

    # (1) ANY node at point with crush/like/paid labels — ignore dump order /
    # clickable flag (real Crush is a non-clickable ImageView).
    block_kws = _POINT_BLOCK_LABELS if dry_run else _LIVE_PAID_REFUSE
    blocker = find_blocking_label_at(tree, x, y, block_kws)
    if blocker:
        kind = "dry-run mutating" if dry_run else "paid"
        reason = (
            f"tap firewall: refuse {kind} label at point "
            f"{(blocker.get('label') or blocker.get('id') or '?')[:60]!r}"
        )
        logger.warning("%s at (%s,%s)", reason, x, y)
        return {
            "action": "fail",
            "reason": reason,
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "_resolved_label": blocker.get("label"),
            "_resolved_id": blocker.get("id"),
        }

    resolved = resolve_topmost_clickable_at(tree, x, y)

    # (2) Overlay up → refuse nav / underneath taps (Chats under Crush sheet).
    try:
        from dm_heuristics import app_overlay_present
    except ImportError:
        from backend.dm_heuristics import app_overlay_present  # type: ignore

    app_key = (app or action.get("app") or _detect_app_from_tree(tree) or "").lower()
    overlay = app_overlay_present(app_key or None, tree)
    if overlay and _looks_like_nav_tap(action, resolved):
        reason = (
            f"tap firewall: refuse nav tap while {overlay} covers screen "
            f"(close overlay first)"
        )
        logger.warning("%s at (%s,%s)", reason, x, y)
        return {
            "action": "fail",
            "reason": reason,
            "planner": action.get("planner") or "tap_firewall",
            "llm_provider": None,
            "dry_run": bool(dry_run),
            "_resolved_label": (resolved or {}).get("label"),
            "_resolved_id": (resolved or {}).get("id"),
            "_overlay": overlay,
        }

    reason = tap_is_forbidden(
        resolved, dry_run=dry_run, action=action, point_labels=point_labels
    )
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
