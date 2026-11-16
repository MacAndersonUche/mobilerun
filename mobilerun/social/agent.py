"""Social mode helpers: unread reporting, draft prep with signature + escalation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mobilerun.needs_you.escalation import EscalationDecision, classify_escalation
from mobilerun.needs_you.queue import NeedsYouQueue
from mobilerun.social.config import SocialModeConfig
from mobilerun.social.signature import SignatureConfig


@dataclass
class OutboundDecision:
    final_text: str
    needs_you: bool
    escalation: EscalationDecision
    needs_you_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_text": self.final_text,
            "needs_you": self.needs_you,
            "escalation": self.escalation.to_dict(),
            "needs_you_id": self.needs_you_id,
        }


def apply_signature(
    text: str,
    config: SocialModeConfig,
    *,
    package_name: str = "",
    conversation_id: str = "",
    contact_name: str = "",
) -> str:
    config.sync_signature_app_overrides()
    return config.signature.apply(
        text,
        package_name=package_name,
        conversation_id=conversation_id,
        contact_name=contact_name,
    )


def prepare_outbound(
    *,
    draft_reply: str,
    config: SocialModeConfig,
    queue: NeedsYouQueue,
    app_name: str,
    package_name: str,
    conversation_id: str,
    contact_name: str,
    inbound_preview: str = "",
    confidence: float = 0.8,
    is_new_contact: bool = False,
) -> OutboundDecision:
    """
    Apply signature, classify escalation, and enqueue Needs-you when required.
    Does NOT send — caller sends only when needs_you is False (or after approve).
    """
    signed = apply_signature(
        draft_reply,
        config,
        package_name=package_name,
        conversation_id=conversation_id,
        contact_name=contact_name,
    )
    decision = classify_escalation(
        draft_reply=signed,
        inbound_text=inbound_preview,
        confidence=confidence,
        is_new_contact=is_new_contact,
        contact_id=conversation_id,
        contact_name=contact_name,
        rules=config.escalation,
    )
    if not decision.needs_confirmation:
        return OutboundDecision(final_text=signed, needs_you=False, escalation=decision)

    item = queue.add(
        source="social",
        app_name=app_name,
        package_name=package_name,
        conversation_id=conversation_id,
        contact_name=contact_name,
        inbound_preview=inbound_preview,
        draft_reply=signed,
        reasons=decision.reasons,
        confidence=decision.confidence,
    )
    return OutboundDecision(
        final_text=signed,
        needs_you=True,
        escalation=decision,
        needs_you_id=item.id,
    )


def summarize_unreads(threads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate unread counts from accessibility/thread snapshots."""
    by_app: Dict[str, int] = {}
    total = 0
    details = []
    for t in threads:
        app = t.get("app_name") or t.get("package_name") or "unknown"
        n = int(t.get("unread") or 0)
        by_app[app] = by_app.get(app, 0) + n
        total += n
        if n:
            details.append(
                {
                    "app_name": app,
                    "contact": t.get("contact_name") or t.get("title"),
                    "unread": n,
                }
            )
    return {"total_unread": total, "by_app": by_app, "threads": details}


def dating_to_needs_you(
    *,
    queue: NeedsYouQueue,
    app_name: str,
    package_name: str,
    conversation_id: str,
    profile_name: str,
    message: str,
    is_opener: bool = False,
    inbound_preview: str = "",
    reasons: Optional[List[str]] = None,
) -> str:
    """Mirror dating review items into the shared Needs-you queue."""
    item = queue.add(
        source="dating",
        app_name=app_name,
        package_name=package_name,
        conversation_id=conversation_id,
        contact_name=profile_name,
        inbound_preview=inbound_preview,
        draft_reply=message,
        reasons=reasons or (["dating_review"] + (["opener"] if is_opener else [])),
        confidence=0.5,
        meta={"is_opener": is_opener},
    )
    return item.id
