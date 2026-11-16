"""Classify whether a draft reply needs Mac's confirmation before send."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

# Money / payments
MONEY_PATTERNS = [
    r"\b(venmo|cash\s*app|paypal|zelle|wire|bank|iban|routing)\b",
    r"\b(send|pay|transfer)\s+(me\s+)?\$?\d+",
    r"\$\d+",
    r"\b(bitcoin|btc|crypto|wallet)\b",
]

# Commitments / plans / dates / times
COMMITMENT_PATTERNS = [
    r"\b(i('ll| will)\s+(come|be there|pick you up|meet|pay))\b",
    r"\b(promise|guaranteed|definitely will)\b",
    r"\b(meet|meetup|hang\s*out|date|dinner|coffee|drinks)\b",
    r"\b(tonight|tomorrow|this\s+(weekend|week|friday|saturday|sunday))\b",
    r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b",
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
]

# Personal / sensitive info
PERSONAL_PATTERNS = [
    r"\b(ssn|social\s*security|passport|driver.?s?\s*license)\b",
    r"\b(address|where\s+do\s+you\s+live|home\s+address)\b",
    r"\b(my\s+number\s+is|call\s+me\s+at|\+?\d{10,})\b",
    r"\b(password|otp|verification\s+code|2fa)\b",
    r"\b(nude|nudes|explicit|send\s+pics?\b).*\b(me|you)\b",
]

# Inbound asks that should escalate even if draft looks fine
INBOUND_SENSITIVE = [
    r"\b(how\s+much\s+(do\s+you\s+)?(make|earn)|salary)\b",
    r"\b(where\s+do\s+you\s+live|what('s| is)\s+your\s+address)\b",
    r"\b(send\s+(me\s+)?(money|cash|\$))\b",
    r"\b(are\s+you\s+free\s+(tonight|tomorrow))\b",
]


@dataclass
class EscalationRules:
    """Configurable auto-send vs confirm rules."""

    always_ask_new_contacts: bool = True
    always_ask_money: bool = True
    always_ask_commitments: bool = True
    always_ask_personal_info: bool = True
    always_ask_plans_times: bool = True
    min_confidence_to_autosend: float = 0.72
    extra_patterns: List[str] = field(default_factory=list)
    # Known contacts that may auto-send (conversation_id or contact name)
    trusted_contacts: List[str] = field(default_factory=list)


@dataclass
class EscalationDecision:
    needs_confirmation: bool
    reasons: List[str]
    confidence: float

    def to_dict(self) -> dict:
        return {
            "needs_confirmation": self.needs_confirmation,
            "reasons": self.reasons,
            "confidence": self.confidence,
        }


def _match_any(text: str, patterns: Sequence[str]) -> Optional[str]:
    lower = text.lower()
    for p in patterns:
        if re.search(p, lower, re.I):
            return p
    return None


def classify_escalation(
    *,
    draft_reply: str,
    inbound_text: str = "",
    confidence: float = 0.8,
    is_new_contact: bool = False,
    contact_id: str = "",
    contact_name: str = "",
    rules: Optional[EscalationRules] = None,
) -> EscalationDecision:
    """Return whether Mac must confirm before the agent sends."""
    rules = rules or EscalationRules()
    reasons: List[str] = []
    blob = f"{inbound_text}\n{draft_reply}"

    trusted = {
        *(c.lower() for c in rules.trusted_contacts),
    }
    contact_keys = {contact_id.lower(), contact_name.lower()} - {""}
    is_trusted = bool(contact_keys & trusted)

    if rules.always_ask_new_contacts and is_new_contact and not is_trusted:
        reasons.append("new_contact")

    if rules.always_ask_money and _match_any(blob, MONEY_PATTERNS):
        reasons.append("money")

    if rules.always_ask_commitments or rules.always_ask_plans_times:
        if _match_any(blob, COMMITMENT_PATTERNS):
            reasons.append("commitment_or_plan")

    if rules.always_ask_personal_info and _match_any(blob, PERSONAL_PATTERNS):
        reasons.append("personal_info")

    if _match_any(inbound_text, INBOUND_SENSITIVE):
        reasons.append("sensitive_inbound")

    if rules.extra_patterns and _match_any(blob, rules.extra_patterns):
        reasons.append("custom_rule")

    if confidence < rules.min_confidence_to_autosend:
        reasons.append("low_confidence")

    # Trusted contacts still escalate on money/personal
    if is_trusted:
        hard = {"money", "personal_info", "sensitive_inbound"}
        reasons = [r for r in reasons if r in hard or r == "low_confidence"]

    return EscalationDecision(
        needs_confirmation=bool(reasons),
        reasons=reasons,
        confidence=confidence,
    )
