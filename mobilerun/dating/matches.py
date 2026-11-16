"""Private per-user Matches store (DynamoDB or local JSON).

Stores dating match records for Mac only: name, app, date agreed, distance,
WhatsApp / Snapchat, status, notes, timestamps. Never log contact values in
plaintext — callers must not print whatsapp/snapchat into logs.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MATCH_STATUSES = ("chatting", "invited", "booked", "handed_off")

_SENSITIVE_KEYS = frozenset(
    {"whatsapp", "snapchat", "contact_handle", "phone", "number"}
)


def redact_for_log(payload: Any) -> Any:
    """Return a copy safe for logs (contacts redacted)."""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if str(k).lower() in _SENSITIVE_KEYS and v:
                out[k] = "***"
            else:
                out[k] = redact_for_log(v)
        return out
    if isinstance(payload, list):
        return [redact_for_log(x) for x in payload]
    return payload


@dataclass
class MatchRecord:
    """One dating match — private to the owning authenticated user."""

    match_id: str
    user_id: str = ""
    name: str = ""
    app: str = ""
    package_name: str = ""
    date_agreed: str = ""  # day / time / place free text
    distance_miles: Optional[float] = None
    whatsapp: str = ""
    snapchat: str = ""
    status: str = "chatting"  # chatting | invited | booked | handed_off
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def clamp(self) -> "MatchRecord":
        st = (self.status or "chatting").strip().lower().replace(" ", "_")
        if st in ("handed-off", "handoff", "handedoff"):
            st = "handed_off"
        if st not in MATCH_STATUSES:
            st = "chatting"
        self.status = st
        self.match_id = (self.match_id or "").strip() or str(uuid.uuid4())
        self.name = (self.name or "").strip()
        self.app = (self.app or "").strip()
        self.package_name = (self.package_name or "").strip()
        self.date_agreed = (self.date_agreed or "").strip()
        self.whatsapp = (self.whatsapp or "").strip()
        self.snapchat = (self.snapchat or "").strip()
        self.notes = (self.notes or "").strip()
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now
        return self

    def to_dict(self) -> Dict[str, Any]:
        self.clamp()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MatchRecord":
        raw = data or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        dist = raw.get("distance_miles")
        try:
            dist_f = float(dist) if dist is not None and dist != "" else None
        except (TypeError, ValueError):
            dist_f = None
        kwargs = {k: v for k, v in raw.items() if k in known and k != "distance_miles"}
        return cls(distance_miles=dist_f, **kwargs).clamp()

    def match_key(self) -> str:
        pkg = self.package_name or self.app or "_"
        return f"{pkg}#{self.match_id}"


class MatchStore:
    """Per-user match CRUD. DynamoDB MATCHES_TABLE when USE_AWS_STORAGE else local JSON."""

    SETTING_NAME = "dating_matches"

    def __init__(self, user_id: str, *, persist_path: Optional[Path] = None):
        self.user_id = (user_id or "local").strip().lower() or "local"
        self.persist_path = persist_path
        self._items: Dict[str, MatchRecord] = {}
        self._load()

    def _key(self, package_name: str, match_id: str) -> str:
        return f"{package_name or '_'}#{match_id}"

    def list(
        self,
        *,
        q: str = "",
        sort: str = "updated_at",
        order: str = "desc",
    ) -> List[MatchRecord]:
        rows = list(self._items.values())
        needle = (q or "").strip().lower()
        if needle:

            def _hit(m: MatchRecord) -> bool:
                blob = " ".join(
                    [
                        m.name,
                        m.app,
                        m.package_name,
                        m.date_agreed,
                        m.status,
                        m.notes,
                        m.whatsapp,
                        m.snapchat,
                        m.match_id,
                    ]
                ).lower()
                return needle in blob

            rows = [m for m in rows if _hit(m)]
        reverse = (order or "desc").lower() != "asc"
        sort_key = (sort or "updated_at").strip()

        def _sk(m: MatchRecord):
            v = getattr(m, sort_key, None)
            if v is None:
                return ""
            return v

        rows.sort(key=_sk, reverse=reverse)
        return rows

    def get(self, match_id: str, package_name: str = "") -> Optional[MatchRecord]:
        if package_name:
            return self._items.get(self._key(package_name, match_id))
        for m in self._items.values():
            if m.match_id == match_id:
                return m
        return None

    def upsert(self, record: MatchRecord) -> MatchRecord:
        rec = MatchRecord.from_dict({**record.to_dict(), "user_id": self.user_id})
        if not rec.created_at:
            existing = self._items.get(rec.match_key())
            if existing:
                rec.created_at = existing.created_at
        self._items[rec.match_key()] = rec
        self._persist()
        logger.info(
            "match upserted user=%s key=%s status=%s",
            self.user_id,
            rec.match_key(),
            rec.status,
        )
        return rec

    def update(
        self, match_id: str, patch: Dict[str, Any], *, package_name: str = ""
    ) -> Optional[MatchRecord]:
        cur = self.get(match_id, package_name=package_name)
        if not cur:
            return None
        data = cur.to_dict()
        for k, v in (patch or {}).items():
            if k in ("match_id", "user_id", "created_at"):
                continue
            if k in data:
                data[k] = v
        # Preserve created_at
        data["created_at"] = cur.created_at
        return self.upsert(MatchRecord.from_dict(data))

    def delete(self, match_id: str, *, package_name: str = "") -> bool:
        if package_name:
            k = self._key(package_name, match_id)
            if k in self._items:
                del self._items[k]
                self._persist()
                logger.info("match deleted user=%s key=%s", self.user_id, k)
                return True
            return False
        removed = False
        for k in list(self._items.keys()):
            if self._items[k].match_id == match_id:
                del self._items[k]
                removed = True
        if removed:
            self._persist()
            logger.info("match deleted user=%s match_id=%s", self.user_id, match_id)
        return removed

    def export_csv(
        self, *, q: str = "", sort: str = "updated_at", order: str = "desc"
    ) -> str:
        rows = self.list(q=q, sort=sort, order=order)
        buf = io.StringIO()
        fields = [
            "match_id",
            "name",
            "app",
            "package_name",
            "date_agreed",
            "distance_miles",
            "whatsapp",
            "snapchat",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for m in rows:
            d = m.to_dict()
            w.writerow({k: d.get(k, "") for k in fields})
        return buf.getvalue()

    def upsert_from_date_flow(
        self,
        *,
        match_id: str,
        package_name: str = "",
        name: str = "",
        app: str = "",
        date_agreed: str = "",
        distance_miles: Optional[float] = None,
        whatsapp: str = "",
        snapchat: str = "",
        status: str = "",
        notes: str = "",
    ) -> MatchRecord:
        """Merge date-flow events into the match record without wiping contacts."""
        existing = self.get(match_id, package_name=package_name)
        base = (
            existing.to_dict()
            if existing
            else {
                "match_id": match_id,
                "package_name": package_name,
                "user_id": self.user_id,
            }
        )
        if name:
            base["name"] = name
        if app or package_name:
            base["app"] = app or package_name
        if package_name:
            base["package_name"] = package_name
        if date_agreed:
            base["date_agreed"] = date_agreed
        if distance_miles is not None:
            base["distance_miles"] = distance_miles
        if whatsapp:
            base["whatsapp"] = whatsapp
        if snapchat:
            base["snapchat"] = snapchat
        if status:
            base["status"] = status
        if notes:
            base["notes"] = notes
        return self.upsert(MatchRecord.from_dict(base))

    def _local_path(self) -> Path:
        if self.persist_path:
            return self.persist_path
        root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
        safe = re.sub(r"[^a-zA-Z0-9_.@-]+", "_", self.user_id)
        return root / f"matches_{safe}.json"

    def _persist(self) -> None:
        payload = {
            "user_id": self.user_id,
            "matches": {k: v.to_dict() for k, v in self._items.items()},
            "saved_at": datetime.now().isoformat(),
        }
        # Prefer dedicated Dynamo table
        if self._dynamo_put_all(payload["matches"]):
            return
        # Fallback: SETTINGS_TABLE blob or local JSON
        try:
            from backend.storage import save_user_setting, USE_AWS

            if USE_AWS:
                save_user_setting(self.user_id, self.SETTING_NAME, payload)
                return
        except Exception:
            logger.exception(
                "matches settings persist failed (no contact values logged)"
            )
        path = self._local_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))

    def _load(self) -> None:
        items: Dict[str, Any] = {}
        loaded = self._dynamo_scan()
        if loaded is not None:
            items = loaded
        else:
            try:
                from backend.storage import get_user_setting, USE_AWS

                if USE_AWS:
                    blob = get_user_setting(self.user_id, self.SETTING_NAME) or {}
                    items = dict(blob.get("matches") or {})
            except Exception:
                items = {}
            if not items:
                path = self._local_path()
                if path.exists():
                    try:
                        blob = json.loads(path.read_text())
                        items = dict(blob.get("matches") or {})
                    except Exception:
                        items = {}
        self._items = {
            k: MatchRecord.from_dict({**v, "user_id": self.user_id})
            for k, v in items.items()
            if isinstance(v, dict)
        }

    def _dynamo_table(self):
        use_aws = os.environ.get("USE_AWS_STORAGE", "false").lower() == "true"
        table_name = os.environ.get("MATCHES_TABLE")
        if not use_aws or not table_name:
            return None
        try:
            import boto3

            return boto3.resource("dynamodb").Table(table_name)
        except Exception:
            logger.exception("matches dynamo table init failed")
            return None

    def _dynamo_put_all(self, matches: Dict[str, Dict[str, Any]]) -> bool:
        table = self._dynamo_table()
        if table is None:
            return False
        try:
            # Replace all items for this user (small private set)
            existing = (
                table.query(
                    KeyConditionExpression="user_id = :u",
                    ExpressionAttributeValues={":u": self.user_id},
                ).get("Items")
                or []
            )
            with table.batch_writer() as batch:
                for it in existing:
                    batch.delete_item(
                        Key={"user_id": it["user_id"], "match_key": it["match_key"]}
                    )
                for _k, raw in matches.items():
                    rec = MatchRecord.from_dict({**raw, "user_id": self.user_id})
                    item = rec.to_dict()
                    item["match_key"] = rec.match_key()
                    # Dynamo-friendly numbers
                    if item.get("distance_miles") is None:
                        item.pop("distance_miles", None)
                    batch.put_item(Item=item)
            return True
        except Exception:
            logger.exception("matches dynamo put failed")
            return False

    def _dynamo_scan(self) -> Optional[Dict[str, Any]]:
        table = self._dynamo_table()
        if table is None:
            return None
        try:
            resp = table.query(
                KeyConditionExpression="user_id = :u",
                ExpressionAttributeValues={":u": self.user_id},
            )
            out: Dict[str, Any] = {}
            for it in resp.get("Items") or []:
                key = (
                    it.get("match_key")
                    or f"{it.get('package_name', '_')}#{it.get('match_id')}"
                )
                out[key] = it
            return out
        except Exception:
            logger.exception("matches dynamo query failed")
            return None
