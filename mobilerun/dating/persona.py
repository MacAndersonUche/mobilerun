"""Persona / message generation for dating mode.

Openers may come from the template library (no LLM). Replies always use AI
when an LLM callable is provided.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Optional

from mobilerun.dating.openers import OpenerLibrary, compose_dating_message


class PersonaManager:
    """Manages persona and message generation."""

    def __init__(
        self,
        persona_prompt: str = "",
        opener_library: Optional[OpenerLibrary] = None,
        ai_callable: Optional[Callable[..., Any]] = None,
    ):
        self.persona_prompt = persona_prompt
        self.opener_library = opener_library or OpenerLibrary()
        self.ai_callable = ai_callable

    def compose(
        self,
        *,
        is_opener: bool,
        match_id: str,
        package_name: str = "",
        profile_name: str = "",
        inbound_preview: str = "",
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return compose_dating_message(
            is_opener=is_opener,
            lib=self.opener_library,
            match_id=match_id,
            package_name=package_name,
            profile_name=profile_name or None,
            now=now,
            ai_callable=self.ai_callable,
            inbound_preview=inbound_preview,
        )

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
    ) -> Dict[str, Any]:
        return self.compose(
            is_opener=False,
            match_id=match_id,
            package_name=package_name,
            profile_name=profile_name,
            inbound_preview=inbound_preview,
        )
