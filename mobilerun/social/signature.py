"""Message signature footer: global / per-app / per-contact overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

DEFAULT_SIGNATURE = "— from MacAI"


@dataclass
class SignatureConfig:
    """Signature toggles. Default ON globally."""

    enabled_global: bool = True
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
        ck = self.contact_key(package_name, conversation_id, contact_name)
        if ck in self.per_contact and self.per_contact[ck] is not None:
            return bool(self.per_contact[ck])
        if package_name in self.per_app and self.per_app[package_name] is not None:
            return bool(self.per_app[package_name])
        return bool(self.enabled_global)

    def apply(
        self,
        message: str,
        *,
        package_name: str = "",
        conversation_id: str = "",
        contact_name: str = "",
    ) -> str:
        """Append signature footer when enabled (idempotent if already present)."""
        body = (message or "").rstrip()
        if not self.is_enabled(
            package_name=package_name,
            conversation_id=conversation_id,
            contact_name=contact_name,
        ):
            return body
        sig = (self.text or DEFAULT_SIGNATURE).strip()
        if not sig:
            return body
        if body.endswith(sig):
            return body
        if not body:
            return sig
        return f"{body}\n{sig}"

    def to_dict(self) -> dict:
        return {
            "enabled_global": self.enabled_global,
            "text": self.text,
            "per_app": self.per_app,
            "per_contact": self.per_contact,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "SignatureConfig":
        data = data or {}
        return cls(
            enabled_global=bool(data.get("enabled_global", True)),
            text=str(data.get("text") or DEFAULT_SIGNATURE),
            per_app=dict(data.get("per_app") or {}),
            per_contact=dict(data.get("per_contact") or {}),
        )
