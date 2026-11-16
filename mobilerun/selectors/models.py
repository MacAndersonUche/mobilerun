"""Selector models for dating/social navigation."""

from __future__ import annotations

import uuid
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


# Layout-variant slot policy (configurable; enforced min 2)
DEFAULT_MAX_LAYOUT_VARIANTS = 4
MIN_LAYOUT_VARIANTS = 2


def clamp_max_variants(n: Optional[int]) -> int:
    """Configurable cap; default 4, never below 2."""
    if n is None:
        return DEFAULT_MAX_LAYOUT_VARIANTS
    try:
        return max(MIN_LAYOUT_VARIANTS, int(n))
    except (TypeError, ValueError):
        return DEFAULT_MAX_LAYOUT_VARIANTS


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

    def fingerprint(self) -> str:
        """Stable id for deduping layout variants.

        Prefer resource_id when present (same control, richer metadata later).
        """
        rid = (self.resource_id or "").strip().lower()
        if rid:
            return f"id:{rid}"
        parts = [
            self.content_desc or "",
            self.text or "",
            self.class_name or "",
            self.hint or "",
        ]
        return "|".join(parts).lower()


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
class LayoutVariant:
    """One layout shape for a role (e.g. Hinge chat bar position A vs B)."""

    selector: SelectorSpec
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    nav_path: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "heuristic"  # heuristic | llm | manual | explore
    hits: int = 0
    misses: int = 0
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    label: str = ""  # optional human label (v1 / v2 / bottom_bar)

    @property
    def success_rate(self) -> float:
        total = self.hits + self.misses
        if total <= 0:
            return 0.0
        return float(self.hits) / float(total)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "selector": self.selector.to_dict(),
            "nav_path": list(self.nav_path or []),
            "source": self.source,
            "hits": self.hits,
            "misses": self.misses,
            "success_rate": round(self.success_rate, 4),
            "discovered_at": self.discovered_at,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LayoutVariant":
        raw = data or {}
        return cls(
            id=str(raw.get("id") or uuid.uuid4().hex[:10]),
            selector=SelectorSpec.from_dict(raw.get("selector") or {}),
            nav_path=list(raw.get("nav_path") or []),
            source=str(raw.get("source") or "heuristic"),
            hits=int(raw.get("hits") or 0),
            misses=int(raw.get("misses") or 0),
            discovered_at=str(raw.get("discovered_at") or datetime.now().isoformat()),
            last_success_at=raw.get("last_success_at"),
            last_failure_at=raw.get("last_failure_at"),
            label=str(raw.get("label") or ""),
        )


def _variant_sort_key(v: LayoutVariant) -> tuple:
    """Higher success rate first, then recent success, then hit count."""
    return (
        v.success_rate,
        v.last_success_at or "",
        v.hits,
    )


@dataclass
class CachedEntry:
    """
    Cached selectors for one role on package+version.

    Holds multiple layout variants (default cap 4, min 2). Legacy single-selector
    payloads migrate into ``variants`` on load.
    """

    role: str
    package_name: str
    version_code: str
    variants: List[LayoutVariant] = field(default_factory=list)
    # Legacy single-selector fields kept for migration / convenience
    selector: SelectorSpec = field(default_factory=SelectorSpec)
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    llm_calls: int = 0
    rediscovery_attempts: int = 0
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    source: str = "heuristic"
    nav_path: List[Dict[str, Any]] = field(default_factory=list)

    def ensure_variants(self) -> None:
        """Migrate legacy single-selector entry into variants list."""
        if self.variants:
            best = max(self.variants, key=_variant_sort_key)
            self.selector = best.selector
            self.nav_path = list(best.nav_path or [])
            self.source = best.source
            return
        if not self.selector.is_empty():
            self.variants = [
                LayoutVariant(
                    selector=self.selector,
                    nav_path=list(self.nav_path or []),
                    source=self.source,
                    discovered_at=self.discovered_at,
                    last_success_at=self.last_success_at,
                    last_failure_at=self.last_failure_at,
                    hits=1 if self.last_success_at else 0,
                )
            ]

    def ordered_variants(self) -> List[LayoutVariant]:
        if not self.variants and not self.selector.is_empty():
            self.ensure_variants()
        return sorted(self.variants, key=_variant_sort_key, reverse=True)

    def to_dict(self) -> Dict[str, Any]:
        self.ensure_variants()
        best = self.ordered_variants()[0] if self.variants else None
        return {
            "role": self.role,
            "package_name": self.package_name,
            "version_code": self.version_code,
            "variants": [v.to_dict() for v in self.variants],
            # Legacy mirrors (best / first variant) for older readers
            "selector": (best.selector if best else self.selector).to_dict(),
            "discovered_at": self.discovered_at,
            "llm_calls": self.llm_calls,
            "rediscovery_attempts": self.rediscovery_attempts,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "source": best.source if best else self.source,
            "nav_path": list((best.nav_path if best else self.nav_path) or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedEntry":
        raw = data or {}
        variants_raw = raw.get("variants")
        variants: List[LayoutVariant] = []
        if isinstance(variants_raw, list) and variants_raw:
            variants = [LayoutVariant.from_dict(v) for v in variants_raw]
        entry = cls(
            role=str(raw.get("role") or ""),
            package_name=str(raw.get("package_name") or ""),
            version_code=str(raw.get("version_code") or ""),
            variants=variants,
            selector=SelectorSpec.from_dict(raw.get("selector") or {}),
            discovered_at=str(raw.get("discovered_at") or datetime.now().isoformat()),
            llm_calls=int(raw.get("llm_calls") or 0),
            rediscovery_attempts=int(raw.get("rediscovery_attempts") or 0),
            last_success_at=raw.get("last_success_at"),
            last_failure_at=raw.get("last_failure_at"),
            source=str(raw.get("source") or "heuristic"),
            nav_path=list(raw.get("nav_path") or []),
        )
        entry.ensure_variants()
        return entry


@dataclass
class CacheStatus:
    package_name: str
    version_code: str
    roles: List[Dict[str, Any]] = field(default_factory=list)
    total_llm_calls: int = 0
    last_discovered_at: Optional[str] = None
    max_layout_variants: int = DEFAULT_MAX_LAYOUT_VARIANTS

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
            resource_id="ai.mobilerun.mockdating:id/matchesList",
            content_desc="Matches list",
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
            resource_id="ai.mobilerun.mockdating:id/matchesList",
            content_desc="Matches list",
        ),
        ElementRole.OPEN_CHAT.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/chatLog",
        ),
    },
    "ai.mobilerun.mockdating@v3": {
        ElementRole.MESSAGE_INPUT.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/msgBox",
            hint="Say hi",
            class_name="android.widget.EditText",
            editable=True,
        ),
        ElementRole.SEND_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnPost",
            text="Send",
            content_desc="Post message",
            clickable=True,
        ),
        ElementRole.LIKE_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnYes",
            text="Like",
            clickable=True,
        ),
        ElementRole.PASS_BUTTON.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/btnSkip",
            text="Pass",
            clickable=True,
        ),
        ElementRole.PROFILE_NAME.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/displayName",
        ),
        ElementRole.MATCHES_LIST.value: SelectorSpec(
            resource_id="ai.mobilerun.mockdating:id/matchesList",
            content_desc="Matches list",
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
    ElementRole.MATCHES_LIST.value: SelectorSpec(
        content_desc="Matches list",
        text="Matches",
    ),
}
