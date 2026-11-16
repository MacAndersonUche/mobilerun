"""Match SelectorSpec against an accessibility tree — never calls an LLM."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from mobilerun.selectors.models import SelectorMatch, SelectorSpec


def flatten_nodes(tree: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            out.append(node)
            for c in node.get("children") or node.get("nodes") or []:
                walk(c)
        elif isinstance(node, (list, tuple)):
            for c in node:
                walk(c)

    walk(tree)
    return out


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _field(node: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = node.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _score_node(node: Dict[str, Any], spec: SelectorSpec) -> float:
    """Higher is better. Absolute miss on a hard field → 0."""
    score = 0.0
    checks = 0

    rid = _field(node, "resourceId", "resource-id", "resource_id")
    if spec.resource_id:
        checks += 1
        want = spec.resource_id
        short_want = want.split("/")[-1]
        short_have = rid.split("/")[-1] if rid else ""
        # Exact full or short id only — never substring (btnSend ≠ btnSendMessage)
        if _norm(rid) == _norm(want) or (
            short_want and _norm(short_have) == _norm(short_want)
        ):
            score += 4.0
        else:
            return 0.0

    if spec.content_desc:
        checks += 1
        have = _field(node, "contentDescription", "content-desc", "content_desc")
        if _norm(have) == _norm(spec.content_desc):
            score += 3.0
        elif _norm(spec.content_desc) in _norm(have):
            score += 1.5
        else:
            return 0.0

    if spec.text:
        checks += 1
        have = _field(node, "text")
        if _norm(have) == _norm(spec.text):
            score += 3.0
        elif _norm(spec.text) in _norm(have):
            score += 1.5
        else:
            return 0.0

    if spec.hint:
        checks += 1
        have = _field(node, "hint", "hintText")
        if _norm(have) == _norm(spec.hint):
            score += 3.0
        elif _norm(spec.hint) in _norm(have):
            score += 1.5
        else:
            return 0.0

    if spec.class_name:
        checks += 1
        have = _field(node, "className", "class", "class_name")
        if _norm(have) == _norm(spec.class_name) or _norm(have).endswith(
            "." + _norm(spec.class_name).split(".")[-1]
        ):
            score += 1.0
        else:
            # Soft — class mismatch doesn't hard-fail if other fields matched
            score -= 0.25

    if spec.clickable is not None:
        checks += 1
        if bool(node.get("clickable")) == bool(spec.clickable):
            score += 0.5

    if spec.editable is not None:
        checks += 1
        editable = bool(
            node.get("editable")
            or node.get("isEditable")
            or "edittext" in _norm(_field(node, "className", "class"))
        )
        if editable == bool(spec.editable):
            score += 0.5

    if checks == 0:
        return 0.0
    return score


def find_by_selector(
    tree: Any,
    spec: SelectorSpec,
    *,
    min_score: float = 1.0,
) -> Optional[SelectorMatch]:
    """Return best matching node for spec, or None. No LLM."""
    if spec.is_empty():
        return None
    best: Optional[SelectorMatch] = None
    for node in flatten_nodes(tree):
        sc = _score_node(node, spec)
        if sc < min_score:
            continue
        if best is None or sc > best.score:
            best = SelectorMatch(node=node, selector=spec, score=sc)
    return best


def find_by_hint_patterns(
    tree: Any,
    patterns: Sequence[str],
    *,
    fields: Sequence[str] = ("hint", "text", "contentDescription", "content-desc"),
) -> Optional[Dict[str, Any]]:
    """Heuristic search by common phrases (e.g. Type a message / Send)."""
    regs = [re.compile(re.escape(p), re.I) for p in patterns if p]
    for node in flatten_nodes(tree):
        for f in fields:
            val = node.get(f) or ""
            if not isinstance(val, str):
                continue
            for rg in regs:
                if rg.search(val):
                    return node
    return None
