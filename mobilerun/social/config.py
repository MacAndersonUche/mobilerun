"""Social mode configuration — everyday messaging apps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import List, Optional

from mobilerun.needs_you.escalation import EscalationRules
from mobilerun.social.signature import SignatureConfig


@dataclass
class SocialAppProfile:
    name: str
    package_name: str
    enabled: bool = True
    # Optional per-app signature override (None = inherit)
    signature_enabled: Optional[bool] = None


DEFAULT_SOCIAL_APPS = [
    SocialAppProfile("WhatsApp", "com.whatsapp"),
    SocialAppProfile("Facebook", "com.facebook.katana"),
    SocialAppProfile("Messenger", "com.facebook.orca"),
    SocialAppProfile("X", "com.twitter.android"),
    SocialAppProfile("Snapchat", "com.snapchat.android"),
    SocialAppProfile("Instagram", "com.instagram.android"),
]


DEFAULT_TONE = """You are Mac. Reply in Mac's natural tone:
- Warm, direct, lightly witty
- Short messages (1–3 sentences)
- Match the other person's energy
- No corporate speak, no emoji spam unless they use them
"""


@dataclass
class SocialModeConfig:
    apps: List[SocialAppProfile] = field(
        default_factory=lambda: [
            SocialAppProfile(**a.__dict__) for a in DEFAULT_SOCIAL_APPS
        ]
    )
    active_hours_start: time = time(8, 0)
    active_hours_end: time = time(23, 30)
    speed_preset: str = "balanced"
    tone_prompt: str = DEFAULT_TONE
    signature: SignatureConfig = field(default_factory=SignatureConfig)
    escalation: EscalationRules = field(default_factory=EscalationRules)
    # Optional email notify (off by default)
    email_notify: bool = False
    email_to: str = "macandersonuche@yahoo.com"
    report_unread: bool = True

    def get_enabled_apps(self) -> List[SocialAppProfile]:
        return [a for a in self.apps if a.enabled]

    def get_app(self, package_name: str) -> Optional[SocialAppProfile]:
        return next((a for a in self.apps if a.package_name == package_name), None)

    def sync_signature_app_overrides(self) -> None:
        """Push per-app signature flags into SignatureConfig.per_app."""
        for app in self.apps:
            if app.signature_enabled is not None:
                self.signature.per_app[app.package_name] = app.signature_enabled
