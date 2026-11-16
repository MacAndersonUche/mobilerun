"""Selector models for dating/social navigation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ElementRole(str, Enum):
    """Stable navigation roles across dating/social apps."""

    MATCHES_LIST = "matches_list"
    OPEN_CHAT = "open_chat"
    MESSAGE_INPUT = "message_input"
    SEND_BUTTON = "send_button"
    LIKE_BUTTON = "like_button"
    PASS_BUTTON = "pass_button"
    PROFILE_NAME = "profile_name"


@dataclass
class SelectorSpec:
    """Stable a11y selector — matched without LLM."""

    resource_id: Optional[str] = None
    content_desc: Optional[str] = None
    text: Optional[str] = None
    class_name: Optional[str] = None
    hint: Optional[str] = None
    # Soft extras
    clickable: Optional[bool] = None
    editable: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SelectorSpec":
        raw = data or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in raw.items() if k in known})

    def is_empty(self) -> bool:
        return not any(
            [
                self.resource_id,
                self.content_desc,
                self.text,
                self.class_name,
                self.hint,
            ]
        )


@dataclass
class SelectorMatch:
    node: Dict[str, Any]
    selector: SelectorSpec
    score: float = 1.0

    @property
    def center(self) -> Optional[tuple]:
        bounds = self.node.get("boundsInScreen") or {}
        if bounds:
            return (
                (int(bounds.get("left", 0)) + int(bounds.get("right", 0))) // 2,
                (int(bounds.get("top", 0)) + int(bounds.get("bottom", 0))) // 2,
            )
        b = self.node.get("bounds")
        if isinstance(b, str) and "," in b:
            left, top, right, bottom = map(int, b.split(",")[:4])
            return ((left + right) // 2, (top + bottom) // 2)
        return None


@dataclass
class CachedEntry:
    role: str
    selector: SelectorSpec
    package_name: str
    version_code: str
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    llm_calls: int = 0
    rediscovery_attempts: int = 0
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    source: str = "heuristic"  # heuristic | llm | manual

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "selector": self.selector.to_dict(),
            "package_name": self.package_name,
            "version_code": self.version_code,
            "discovered_at": self.discovered_at,
            "llm_calls": self.llm_calls,
            "rediscovery_attempts": self.rediscovery_attempts,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedEntry":
        return cls(
            role=str(data.get("role") or ""),
            selector=SelectorSpec.from_dict(data.get("selector") or {}),
            package_name=str(data.get("package_name") or ""),
            version_code=str(data.get("version_code") or ""),
            discovered_at=str(data.get("discovered_at") or datetime.now().isoformat()),
            llm_calls=int(data.get("llm_calls") or 0),
            rediscovery_attempts=int(data.get("rediscovery_attempts") or 0),
            last_success_at=data.get("last_success_at"),
            last_failure_at=data.get("last_failure_at"),
            source=str(data.get("source") or "heuristic"),
        )


@dataclass
class CacheStatus:
    package_name: str
    version_code: str
    roles: List[Dict[str, Any]] = field(default_factory=list)
    total_llm_calls: int = 0
    last_discovered_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Default heuristic selectors for known apps / MockDating
DEFAULT_SELECTORS: Dict[str, Dict[str, SelectorSpec]] = {
    "ai.mobilerun.mockdating": {
        ElementRole.MESSAGE_INPUT.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/messageInput",
            hint="Type a message",
            class_name="android.widget.EditText",
            editable=True,
        ),
        ElementRole.SEND_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnSend",
            text="Send",
            class_name="android.widget.Button",
            clickable=True,
        ),
        ElementRole.LIKE_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnLike",
            text="Like",
            clickable=True,
        ),
        ElementRole.PASS_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnPass",
            text="Pass",
            clickable=True,
        ),
        ElementRole.PROFILE_NAME.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/profileName",
            class_name="android.widget.TextView",
        ),
        ElementRole.MATCHES_LIST.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/mainContent",
        ),
        ElementRole.OPEN_CHAT.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/chatLog",
        ),
    },
    # Layout variant keyed as package@version in cache seed helper
    "ai.mobilerun.mockdating@v2": {
        ElementRole.MESSAGE_INPUT.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/chatComposer",
            hint="Write something",
            class_name="android.widget.EditText",
            editable=True,
        ),
        ElementRole.SEND_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnSendMessage",
            text="Send",
            content_desc="Send message",
            clickable=True,
        ),
        ElementRole.LIKE_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnHeart",
            text="Like",
            clickable=True,
        ),
        ElementRole.PASS_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnNope",
            text="Pass",
            clickable=True,
        ),
        ElementRole.PROFILE_NAME.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/nameLabel",
        ),
        ElementRole.MATCHES_LIST.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/mainContent",
        ),
        ElementRole.OPEN_CHAT.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/chatLog",
        ),
    },
}

# Generic fallbacks when package unknown — text/hint only
GENERIC_FALLBACKS: Dict[str, SelectorSpec] = {
    ElementRole.MESSAGE_INPUT.value: SelectorSpec(
        hint="Type a message",
        class_name="android.widget.EditText",
        editable=True,
    ),
    ElementRole.SEND_BUTTON.value: SelectorSpec(
        text="Send",
        class_name="android.widget.Button",
        clickable=True,
    ),
    ElementRole.LIKE_BUTTON.value: SelectorSpec(text="Like", clickable=True),
    ElementRole.PASS_BUTTON.value: SelectorSpec(text="Pass", clickable=True),
}
