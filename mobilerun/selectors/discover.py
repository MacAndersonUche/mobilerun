"""One-shot LLM discovery → derive a stable SelectorSpec → verify (no bypass)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from mobilerun.selectors.match import find_by_selector, flatten_nodes
from mobilerun.selectors.models import ElementRole, SelectorMatch, SelectorSpec

log = logging.getLogger("mobilerun.selectors.discover")

ROLE_HINTS: Dict[str, List[str]] = {
    ElementRole.MESSAGE_INPUT.value: [
        "Type a message",
        "Write a message",
        "Write something",
        "Say something",
        "Send a message",
        "Message",
    ],
    ElementRole.SEND_BUTTON.value: ["Send", "Send message"],
    ElementRole.LIKE_BUTTON.value: ["Like", "Heart", "Yes"],
    ElementRole.PASS_BUTTON.value: ["Pass", "Nope", "No"],
    ElementRole.MATCHES_LIST.value: ["Matches", "Messages", "Chats", "Inbox"],
    ElementRole.OPEN_CHAT.value: ["Chat", "Conversation", "Open chat"],
    ElementRole.PROFILE_NAME.value: ["Name", "Profile"],
}


def derive_selector_from_node(node: Dict[str, Any]) -> SelectorSpec:
    """Build the most stable selector possible from an a11y node."""
    rid = (
        node.get("resourceId")
        or node.get("resource-id")
        or node.get("resource_id")
        or ""
    )
    content = (
        node.get("contentDescription")
        or node.get("content-desc")
        or node.get("content_desc")
        or ""
    )
    text = node.get("text") or ""
    hint = node.get("hint") or node.get("hintText") or ""
    cls = node.get("className") or node.get("class") or ""
    return SelectorSpec(
        resource_id=rid or None,
        content_desc=content or None,
        text=text if text and len(text) < 40 else None,
        class_name=cls or None,
        hint=hint or None,
        clickable=bool(node.get("clickable")) if "clickable" in node else None,
        editable=bool(
            node.get("editable")
            or node.get("isEditable")
            or "edittext" in (cls or "").lower()
        )
        or None,
    )


def _default_llm_prompt(role: str, tree_summary: str) -> str:
    return (
        "Locate the UI element for role "
        f"'{role}' in this Android accessibility tree. "
        "Reply ONLY with JSON: "
        '{"resource_id":..., "content_desc":..., "text":..., "hint":..., '
        '"class_name":..., "index_hint": <optional int>}. '
        "Prefer resource_id. Do not invent ids that are not in the tree.\n\n"
        f"Tree (truncated):\n{tree_summary[:6000]}"
    )


def _summarize_tree(tree: Any, limit: int = 80) -> str:
    lines = []
    for i, n in enumerate(flatten_nodes(tree)[:limit]):
        bits = []
        for k in (
            "resourceId",
            "resource-id",
            "text",
            "contentDescription",
            "hint",
            "className",
            "class",
        ):
            if n.get(k):
                bits.append(f"{k}={n.get(k)!r}")
        if bits:
            lines.append(f"[{i}] " + ", ".join(bits))
    return "\n".join(lines)


def llm_locate(
    *,
    role: str,
    tree: Any,
    screenshot_b64: Optional[str] = None,
    llm_callable: Optional[Callable[..., Any]] = None,
) -> Optional[SelectorSpec]:
    """
    Call LLM once to locate an element. Returns a SelectorSpec or None.
    Never performs the action — discovery only.
    """
    if llm_callable is None:
        return None
    summary = _summarize_tree(tree)
    prompt = _default_llm_prompt(role, summary)
    try:
        raw = llm_callable(
            role=role,
            prompt=prompt,
            tree_summary=summary,
            screenshot_b64=screenshot_b64,
        )
    except Exception:
        log.exception("LLM locate failed for role=%s", role)
        return None

    data: Dict[str, Any] = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {}
    if not data:
        return None

    # Prefer index_hint if provided and valid
    if "index_hint" in data and isinstance(data["index_hint"], int):
        nodes = flatten_nodes(tree)
        idx = data["index_hint"]
        if 0 <= idx < len(nodes):
            return derive_selector_from_node(nodes[idx])

    spec = SelectorSpec(
        resource_id=data.get("resource_id") or data.get("resourceId"),
        content_desc=data.get("content_desc") or data.get("contentDescription"),
        text=data.get("text"),
        hint=data.get("hint"),
        class_name=data.get("class_name") or data.get("className"),
    )
    if spec.is_empty():
        return None
    return spec


def verify_selector(tree: Any, spec: SelectorSpec) -> Optional[SelectorMatch]:
    """Confirm the derived selector still resolves in the current tree."""
    return find_by_selector(tree, spec)


def heuristic_bootstrap(
    role: str, tree: Any, package_name: str = ""
) -> Optional[SelectorMatch]:
    """Try generic text/hint patterns before spending an LLM call."""
    from mobilerun.selectors.match import find_by_hint_patterns
    from mobilerun.selectors.models import GENERIC_FALLBACKS

    # Package defaults already applied via cache; here: phrase search
    patterns = ROLE_HINTS.get(role) or []
    node = find_by_hint_patterns(tree, patterns) if patterns else None
    if node:
        spec = derive_selector_from_node(node)
        match = find_by_selector(tree, spec)
        if match:
            return match
    fallback = GENERIC_FALLBACKS.get(role)
    if fallback:
        return find_by_selector(tree, fallback)
    return None
