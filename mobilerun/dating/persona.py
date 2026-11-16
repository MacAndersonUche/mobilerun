"""Persona / message generation for dating mode.

Openers may come from the template library (no LLM). Replies use AI with the
reply-persona prompt, and the date-flow manager may inject a one-time invite,
one optional WhatsApp/Snap ask after date agree, or stop AI (Needs-you handoff).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Optional

from mobilerun.dating.date_flow import (
    DEFAULT_REPLY_PERSONA,
    DateFlowConfig,
    DateFlowDecision,
    DateFlowManager,
)
from mobilerun.dating.openers import OpenerLibrary, compose_dating_message


class PersonaManager:
    """Manages persona and message generation."""

    def __init__(
        self,
        persona_prompt: str = "",
        opener_library: Optional[OpenerLibrary] = None,
        ai_callable: Optional[Callable[..., Any]] = None,
        date_flow: Optional[DateFlowManager] = None,
        reply_persona_prompt: str = "",
    ):
        self.persona_prompt = persona_prompt
        self.reply_persona_prompt = reply_persona_prompt or DEFAULT_REPLY_PERSONA
        self.opener_library = opener_library or OpenerLibrary()
        self.ai_callable = ai_callable
        self.date_flow = date_flow

    def compose(
        self,
        *,
        is_opener: bool,
        match_id: str,
        package_name: str = "",
        profile_name: str = "",
        inbound_preview: str = "",
        now: Optional[datetime] = None,
        distance_miles: Optional[float] = None,
    ) -> Dict[str, Any]:
        decision: Optional[DateFlowDecision] = None
        if self.date_flow and not is_opener:
            decision = self.date_flow.evaluate_turn(
                match_id=match_id,
                package_name=package_name,
                inbound=inbound_preview,
                distance_miles=distance_miles,
                her_name=profile_name,
                now=now,
                is_opener=False,
            )
            if decision.stop_ai:
                return {
                    "text": "",
                    "source": "handoff",
                    "is_opener": False,
                    "stop_ai": True,
                    "needs_you": True,
                    "needs_you_kind": decision.needs_you_kind,
                    "reason": decision.reason,
                    "date_flow": decision.to_dict(),
                    "used_llm": False,
                }

        # Prefer injecting the polite date invite as the reply when due
        if decision and decision.should_invite and decision.invite_text:
            return {
                "text": decision.invite_text,
                "source": "date_invite",
                "is_opener": False,
                "stop_ai": False,
                "needs_you": False,
                "used_llm": False,
                "date_flow": decision.to_dict(),
            }

        # One optional WhatsApp/Snap ask after date agree (never auto-message those apps)
        if decision and decision.should_contact_ask and decision.contact_ask_text:
            return {
                "text": decision.contact_ask_text,
                "source": "contact_ask",
                "is_opener": False,
                "stop_ai": False,
                "needs_you": False,
                "used_llm": False,
                "date_flow": decision.to_dict(),
            }

        # Wrap AI callable with reply persona for non-openers
        base_ai = self.ai_callable
        ai_for_compose = base_ai
        if not is_opener and base_ai is not None:
            persona = (
                (decision.reply_persona_prompt if decision else None)
                or self.reply_persona_prompt
                or self.persona_prompt
                or DEFAULT_REPLY_PERSONA
            )

            def wrapped_ai(**kwargs):
                prompt = kwargs.get("prompt") or ""
                payload = dict(kwargs)
                payload["persona_prompt"] = persona
                payload["prompt"] = (
                    f"{persona}\n\nConversation context:\n{prompt}\n\n"
                    "Reply as Mac. Never suggest staying over, coming to your home, "
                    "or anything sexual."
                )
                return base_ai(**payload)

            ai_for_compose = wrapped_ai

        result = compose_dating_message(
            is_opener=is_opener,
            lib=self.opener_library,
            match_id=match_id,
            package_name=package_name,
            profile_name=profile_name or None,
            now=now,
            ai_callable=ai_for_compose,
            inbound_preview=inbound_preview,
        )
        if decision:
            result["date_flow"] = decision.to_dict()
        result["stop_ai"] = False
        return result

    def compose_opener(
        self,
        *,
        match_id: str,
        package_name: str = "",
        profile_name: str = "",
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return self.compose(
            is_opener=True,
            match_id=match_id,
            package_name=package_name,
            profile_name=profile_name,
            now=now,
        )

    def compose_reply(
        self,
        *,
        match_id: str,
        package_name: str = "",
        profile_name: str = "",
        inbound_preview: str = "",
        distance_miles: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return self.compose(
            is_opener=False,
            match_id=match_id,
            package_name=package_name,
            profile_name=profile_name,
            inbound_preview=inbound_preview,
            distance_miles=distance_miles,
            now=now,
        )
