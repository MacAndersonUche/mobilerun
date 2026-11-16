"""Heuristic + optional LLM safety screen detection.

Detects on-screen warnings that mean we must STOP — never solve or bypass:
captcha, unusual activity, rate-limit, account restricted/banned, login/re-auth,
selfie/photo verification, etc.

Uses text + a11y tree heuristics first; optional LLM confirm when uncertain.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class SafetyFinding:
    detected: bool
    category: str = ""  # captcha | unusual_activity | rate_limit | restricted |
    # banned | login | photo_verify | warning | other
    reason: str = ""
    matched_text: str = ""
    confidence: float = 0.0
    source: str = "heuristic"  # heuristic | llm
    pause_all: bool = False  # True for banned / account restricted

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Ordered patterns: (category, pause_all, compiled regex, confidence)
_PATTERNS: List[tuple[str, bool, re.Pattern[str], float]] = [
    (
        "banned",
        True,
        re.compile(
            r"\b(account\s+(banned|disabled|suspended|terminated)|"
            r"you(r account)?\s+(ha(s|ve)\s+)?been\s+(banned|suspended))\b",
            re.I,
        ),
        0.95,
    ),
    (
        "restricted",
        True,
        re.compile(
            r"\b(account\s+(has\s+been\s+)?restricted|temporarily\s+restricted|"
            r"action\s+blocked|we\s+restricted\s+your|"
            r"your\s+account\s+has\s+been\s+restricted)\b",
            re.I,
        ),
        0.92,
    ),
    (
        "captcha",
        False,
        re.compile(
            r"\b(captcha|i'?m\s+not\s+a\s+robot|recaptcha|hcaptcha|"
            r"verify\s+you(re|\s+are)\s+human|complete\s+the\s+challenge|"
            r"select\s+all\s+(squares|images)|puzzle\s+to\s+continue)\b",
            re.I,
        ),
        0.93,
    ),
    (
        "photo_verify",
        False,
        re.compile(
            r"\b(selfie\s+verif|photo\s+verif|verify\s+(your\s+)?(identity|face|selfie)|"
            r"take\s+a\s+(selfie|photo)|liveness\s+check|face\s+match)\b",
            re.I,
        ),
        0.9,
    ),
    (
        "unusual_activity",
        False,
        re.compile(
            r"\b(unusual\s+activity|suspicious\s+activity|"
            r"we\s+noticed\s+unusual|confirm\s+it.?s\s+you|"
            r"this\s+looks\s+automated|bot\s+detected)\b",
            re.I,
        ),
        0.9,
    ),
    (
        "rate_limit",
        False,
        re.compile(
            r"\b(rate\s*limit|too\s+many\s+(requests|attempts|actions)|"
            r"try\s+again\s+later|slow\s+down|you.?re\s+going\s+too\s+fast|"
            r"temporarily\s+limited)\b",
            re.I,
        ),
        0.88,
    ),
    (
        "login",
        False,
        re.compile(
            r"\b(log\s*in\s+again|sign\s+in\s+again|session\s+expired|"
            r"re-?auth|enter\s+your\s+password|two-?factor|"
            r"verify\s+it.?s\s+you|confirm\s+your\s+identity)\b",
            re.I,
        ),
        0.85,
    ),
    (
        "warning",
        False,
        re.compile(
            r"\b(community\s+guidelines|terms\s+of\s+service\s+violation|"
            r"warning:|your\s+account\s+may\s+be|"
            r"we\s+removed\s+your\s+(like|message|swipe))\b",
            re.I,
        ),
        0.8,
    ),
]


def _flatten_ui_text(node: Any, out: List[str]) -> None:
    if node is None:
        return
    if isinstance(node, str):
        if node.strip():
            out.append(node.strip())
        return
    if isinstance(node, dict):
        for key in (
            "text",
            "contentDescription",
            "content-desc",
            "hint",
            "label",
            "name",
        ):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
        children = node.get("children") or node.get("nodes") or []
        if isinstance(children, list):
            for c in children:
                _flatten_ui_text(c, out)
        return
    if isinstance(node, (list, tuple)):
        for c in node:
            _flatten_ui_text(c, out)


def find_safety_in_ui_tree(tree: Any) -> List[str]:
    """Extract visible strings from an a11y / UI tree JSON."""
    out: List[str] = []
    _flatten_ui_text(tree, out)
    return out


def detect_safety_blockers(
    *,
    screen_text: str = "",
    ui_texts: Optional[Sequence[str]] = None,
    ui_tree: Any = None,
    llm_check: bool = False,
    llm_callable: Optional[Any] = None,
) -> SafetyFinding:
    """
    Return a SafetyFinding if the screen looks like a hard stop.

    Never attempts to solve captchas or bypass — detection only.
    """
    chunks: List[str] = []
    if screen_text:
        chunks.append(screen_text)
    if ui_texts:
        chunks.extend([t for t in ui_texts if t])
    if ui_tree is not None:
        chunks.extend(find_safety_in_ui_tree(ui_tree))
    blob = "\n".join(chunks)
    if not blob.strip():
        return SafetyFinding(detected=False)

    for category, pause_all, pattern, conf in _PATTERNS:
        m = pattern.search(blob)
        if m:
            return SafetyFinding(
                detected=True,
                category=category,
                reason=f"Detected {category.replace('_', ' ')} on screen",
                matched_text=m.group(0)[:160],
                confidence=conf,
                source="heuristic",
                pause_all=pause_all,
            )

    # Optional LLM confirm — only when heuristics are inconclusive but
    # soft keywords appear; LLM must NOT suggest bypass steps.
    soft = re.search(
        r"\b(verif|challenge|blocked|suspend|captcha|unusual|restricted)\b",
        blob,
        re.I,
    )
    if llm_check and soft and llm_callable:
        try:
            verdict = llm_callable(blob[:4000])
            if isinstance(verdict, dict) and verdict.get("is_safety_block"):
                return SafetyFinding(
                    detected=True,
                    category=str(verdict.get("category") or "warning"),
                    reason=str(
                        verdict.get("reason")
                        or "LLM flagged a safety / verification screen"
                    ),
                    matched_text=str(verdict.get("snippet") or soft.group(0))[:160],
                    confidence=float(verdict.get("confidence") or 0.7),
                    source="llm",
                    pause_all=bool(verdict.get("pause_all")),
                )
        except Exception:
            pass

    return SafetyFinding(detected=False)
