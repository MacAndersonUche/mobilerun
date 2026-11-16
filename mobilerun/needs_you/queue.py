"""Shared 'Needs you' escalation queue for Social + Dating modes."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class NeedsYouSource(str, Enum):
    SOCIAL = "social"
    DATING = "dating"
    NORMAL = "normal"


class NeedsYouStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


@dataclass
class NeedsYouItem:
    id: str
    source: str  # social | dating
    app_name: str
    package_name: str
    conversation_id: str
    contact_name: str
    inbound_preview: str
    draft_reply: str
    reasons: List[str] = field(default_factory=list)
    confidence: float = 0.5
    status: str = NeedsYouStatus.PENDING.value
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NeedsYouItem":
        return cls(
            id=data["id"],
            source=data.get("source", "social"),
            app_name=data.get("app_name", ""),
            package_name=data.get("package_name", ""),
            conversation_id=data.get("conversation_id", ""),
            contact_name=data.get("contact_name", ""),
            inbound_preview=data.get("inbound_preview", ""),
            draft_reply=data.get("draft_reply", ""),
            reasons=list(data.get("reasons") or []),
            confidence=float(data.get("confidence", 0.5)),
            status=data.get("status", NeedsYouStatus.PENDING.value),
            created_at=data.get("created_at") or datetime.now().isoformat(),
            updated_at=data.get("updated_at") or datetime.now().isoformat(),
            meta=dict(data.get("meta") or {}),
        )


class NeedsYouQueue:
    """In-memory + optional JSON persistence for escalation items."""

    def __init__(self, persist_path: Optional[Path] = None):
        self.persist_path = persist_path
        self._items: Dict[str, NeedsYouItem] = {}
        if persist_path and persist_path.exists():
            self.load(persist_path)

    def add(
        self,
        *,
        source: str,
        app_name: str,
        package_name: str,
        conversation_id: str,
        contact_name: str,
        inbound_preview: str,
        draft_reply: str,
        reasons: Optional[List[str]] = None,
        confidence: float = 0.5,
        meta: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None,
    ) -> NeedsYouItem:
        item = NeedsYouItem(
            id=item_id or f"ny_{secrets.token_hex(6)}",
            source=source,
            app_name=app_name,
            package_name=package_name,
            conversation_id=conversation_id,
            contact_name=contact_name,
            inbound_preview=inbound_preview,
            draft_reply=draft_reply,
            reasons=list(reasons or []),
            confidence=confidence,
            meta=dict(meta or {}),
        )
        self._items[item.id] = item
        self._save()
        return item

    def get(self, item_id: str) -> Optional[NeedsYouItem]:
        return self._items.get(item_id)

    def list_pending(self, source: Optional[str] = None) -> List[NeedsYouItem]:
        items = [
            i for i in self._items.values() if i.status == NeedsYouStatus.PENDING.value
        ]
        if source:
            items = [i for i in items if i.source == source]
        return sorted(items, key=lambda i: i.created_at)

    def list_all(self) -> List[NeedsYouItem]:
        return sorted(self._items.values(), key=lambda i: i.created_at, reverse=True)

    def pending_count(self) -> int:
        return len(self.list_pending())

    def approve(
        self, item_id: str, edited_reply: Optional[str] = None
    ) -> Optional[NeedsYouItem]:
        item = self._items.get(item_id)
        if not item or item.status != NeedsYouStatus.PENDING.value:
            return None
        if edited_reply is not None:
            item.draft_reply = edited_reply
        item.status = NeedsYouStatus.APPROVED.value
        item.updated_at = datetime.now().isoformat()
        self._save()
        return item

    def reject(self, item_id: str) -> Optional[NeedsYouItem]:
        item = self._items.get(item_id)
        if not item or item.status != NeedsYouStatus.PENDING.value:
            return None
        item.status = NeedsYouStatus.REJECTED.value
        item.updated_at = datetime.now().isoformat()
        self._save()
        return item

    def edit(self, item_id: str, draft_reply: str) -> Optional[NeedsYouItem]:
        item = self._items.get(item_id)
        if not item or item.status != NeedsYouStatus.PENDING.value:
            return None
        item.draft_reply = draft_reply
        item.updated_at = datetime.now().isoformat()
        self._save()
        return item

    def mark_sent(self, item_id: str) -> Optional[NeedsYouItem]:
        item = self._items.get(item_id)
        if not item:
            return None
        item.status = NeedsYouStatus.SENT.value
        item.updated_at = datetime.now().isoformat()
        self._save()
        return item

    def clear(self) -> None:
        self._items.clear()
        self._save()

    def to_list(self) -> List[Dict[str, Any]]:
        return [i.to_dict() for i in self.list_all()]

    def load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text())
            self._items = {
                d["id"]: NeedsYouItem.from_dict(d) for d in data.get("items", [])
            }
        except Exception:
            self._items = {}

    def _save(self) -> None:
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(
                json.dumps({"items": self.to_list()}, indent=2)
            )
        except Exception:
            pass


# Process-wide default (backend wires a persisted instance)
default_queue = NeedsYouQueue()
