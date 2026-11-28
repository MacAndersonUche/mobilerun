"""Message signature footer helpers (portal no longer appends signatures)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

# Kept for API/config compat; apply() never appends.
DEFAULT_SIGNATURE = "- from MacAI"


@dataclass
class SignatureConfig:
    """Signature toggles. Portal removed signature UI; apply() is a no-op."""

    enabled_global: bool = False
    text: str = DEFAULT_SIGNATURE
    # package_name -> enabled (None = inherit global)
    per_app: Dict[str, Optional[bool]] = field(default_factory=dict)
    # contact key (package|conversation_id or package|name) -> enabled
    per_contact: Dict[str, Optional[bool]] = field(default_factory=dict)

    def contact_key(
        self, package_name: str, conversation_id: str = "", name: str = ""
    ) -> str:
        ident = conversation_id or name or "_"
        return f"{package_name}|{ident}"

    def is_enabled(
        self,
        *,
        package_name: str = "",
        conversation_id: str = "",
        contact_name: str = "",
    ) -> bool:
        # Portal no longer appends signatures.
        return False

    def apply(
        self,
        message: str,
        *,
        package_name: str = "",
        conversation_id: str = "",
        contact_name: str = "",
    ) -> str:
        """Return message unchanged; signatures are no longer appended."""
        del package_name, conversation_id, contact_name
        return (message or "").rstrip()

    def to_dict(self) -> dict:
        return {
            "enabled_global": False,
            "text": self.text,
            "per_app": self.per_app,
            "per_contact": self.per_contact,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "SignatureConfig":
        data = data or {}
        return cls(
            enabled_global=False,
            text=str(data.get("text") or DEFAULT_SIGNATURE),
            per_app=dict(data.get("per_app") or {}),
            per_contact=dict(data.get("per_contact") or {}),
        )
