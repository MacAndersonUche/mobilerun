"""Reply persona + date-invite flow for Dating mode AI replies.

Configurable globally and per-app:
- Conversation style prompt (warm, respectful, no sexual content)
- Invite timing: after N days of chatting (default random 3–7) when engaged
- Distance rule vs home (default Stoke-on-Trent, 50 mi): far → meet in Stoke;
  near → somewhere convenient. Never suggest staying over / his home.
- Handoff: stop AI when she agrees day/time/place or asks logistics/personal;
  Needs-you + optional calendar; also escalate on discomfort/decline.
- Optional one-shot WhatsApp/Snapchat ask after date agree (never auto-message
  those apps — Mac continues personally). Decline/ignore → still hand off,
  never ask again. Shared handle saved private per-user on the match record.
"""

from __future__ import annotations

import json
import os
import random
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_REPLY_PERSONA = (
    "You are Mac. Keep replies warm and genuine — get to know her, ask about her "
    "day and interests, offer sincere compliments, stay respectful. "
    "No sexual content, no pressure, no pushiness. Short and natural (1–3 sentences)."
)

DEFAULT_HOME_LOCATION = "Stoke-on-Trent"
DEFAULT_RADIUS_MILES = 50.0
DEFAULT_INVITE_DAYS_MIN = 3
DEFAULT_INVITE_DAYS_MAX = 7
DEFAULT_CONTACT_ASK_ORDER = ["whatsapp", "snapchat"]
DEFAULT_CONTACT_ASK_WHATSAPP = (
    "Would it be easier to chat on WhatsApp? "
    "Totally optional — no pressure either way."
)
DEFAULT_CONTACT_ASK_SNAPCHAT = (
    "No worries — would Snapchat be easier instead? "
    "Totally optional, only if you like."
)
# Legacy combined wording (kept for older configs)
DEFAULT_CONTACT_ASK = DEFAULT_CONTACT_ASK_WHATSAPP

# Hard bans in invite / reply wording
STAY_OVER_PATTERNS = [
    r"\bstay\s*over\b",
    r"\bstay\s*the\s*night\b",
    r"\bsleep\s*over\b",
    r"\bcome\s+to\s+my\s+(place|house|flat|apartment|home)\b",
    r"\bmy\s+(place|house|flat|apartment|home)\b",
    r"\byour\s+place\b",
    r"\bnetflix\s+and\s+chill\b",
    r"\bspend\s+the\s+night\b",
]

POSITIVE_ENGAGEMENT_HINTS = [
    r"\bhaha\b",
    r"\blol\b",
    r"\blmao\b",
    r"\b😊\b",
    r"\b😍\b",
    r"\byeah\b",
    r"\byes\b",
    r"\bdefinitely\b",
    r"\bwould love\b",
    r"\bsounds good\b",
    r"\binteresting\b",
    r"\btell me more\b",
    r"\bwhat about you\b",
    r"\byou\??\s*$",
    r"\?\s*$",  # asking questions back
]

DECLINE_HINTS = [
    r"\bno thanks?\b",
    r"\bnot interested\b",
    r"\bi'?m good\b",
    r"\brather not\b",
    r"\bdon'?t want\b",
    r"\bnot looking\b",
    r"\bstop\b",
    r"\bleave me alone\b",
    r"\bcreepy\b",
    r"\buncomfortable\b",
    r"\bthis is weird\b",
]

HANDOFF_AGREE_HINTS = [
    r"\b(sounds|sounds?\s+good|works|perfect|great|yes|yeah|sure|ok|okay|let'?s)\b.*\b(meet|coffee|drink|dinner|lunch|café|cafe|bar|thursday|friday|saturday|sunday|monday|tuesday|wednesday|tomorrow|tonight|\d{1,2}\s*(am|pm|:))\b",
    r"\b(meet|coffee|drink|dinner)\b.*\b(sounds|works|perfect|yes|yeah|sure|ok|okay)\b",
    r"\bhow about\b.+\b(at|@|:)\b",
    r"\bsee you\b",
    r"\bit'?s a date\b",
]

HANDOFF_LOGISTICS_HINTS = [
    r"\bwhat(?:'s| is)?\s+your\s+(number|phone|instagram|snap|address)\b",
    r"\bwhere (?:exactly |do )?we meet\b",
    r"\bwhat time\b",
    r"\bwhich (cafe|café|bar|restaurant|place)\b",
    r"\bsend (me )?(the )?address\b",
    r"\bmy number is\b",
    r"\badd me on\b",
    r"\bwhatsapp\b",
    r"\bi can do\b.+\b(pm|am|o'?clock)\b",
]

CONTACT_DECLINE_HINTS = [
    r"\bprefer (to )?(keep|stay) (it |chatting )?here\b",
    r"\brather (not|keep)\b",
    r"\bdon'?t (want to )?share\b",
    r"\bno (whats?app|snap|snapchat|number)\b",
    r"\bdon'?t have (a )?(whats?app|snap|snapchat|number)\b",
    r"\bi'?ll (just )?keep (it )?here\b",
    r"\bnot comfortable (sharing|giving)\b",
    r"\bno thanks?\b",
    r"\bi'?m good\b",
]

# Capture WhatsApp / Snap / phone from a reply (after the one optional ask).
# Require "is"/":"/"@" so "no snap thanks" is not treated as a handle.
_CONTACT_SNAP_RE = [
    re.compile(
        r"(?:my\s+)?snap(?:chat)?\s+(?:is|handle|user(?:name)?)\s*[:\-@]?\s*"
        r"@?([A-Za-z][A-Za-z0-9._\-]{2,31})",
        re.I,
    ),
    re.compile(
        r"(?:add\s+me\s+on\s+)?snap(?:chat)?\s*[:\-@]\s*"
        r"@?([A-Za-z][A-Za-z0-9._\-]{2,31})",
        re.I,
    ),
]
_CONTACT_SNAP_STOPWORDS = frozenset(
    {
        "chat",
        "me",
        "is",
        "on",
        "my",
        "thanks",
        "thank",
        "please",
        "here",
        "no",
        "not",
        "dont",
        "don't",
    }
)
_CONTACT_WA_RE = [
    re.compile(
        r"(?:my\s+)?(?:whats?app|wa|number|phone)(?:\s+(?:is|number))?\s*[:\-]?\s*"
        r"(\+?\d[\d\s\-().]{6,}\d)",
        re.I,
    ),
    re.compile(
        r"(?:whats?app|wa)\s*[:\-]?\s*(\+?\d[\d\s\-().]{6,}\d)",
        re.I,
    ),
]
_CONTACT_PHONE_LOOSE_RE = re.compile(
    r"(?<!\d)(\+?\d[\d\s\-().]{7,}\d)(?!\d)",
)


def _match_any(text: str, patterns: List[str]) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t, re.I) for p in patterns)


def contains_stay_over_wording(text: str) -> bool:
    return _match_any(text, STAY_OVER_PATTERNS)


def strip_stay_over_wording(text: str) -> str:
    """Remove banned stay-over / home phrases; leave a safe public-meet line."""
    safe = "Would you like to grab a coffee somewhere public sometime soon?"
    original = text or ""
    out = original
    for p in STAY_OVER_PATTERNS:
        out = re.sub(p, "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,.-!?")
    if (
        not out
        or len(out) < 24
        or contains_stay_over_wording(out)
        or _match_any(original, STAY_OVER_PATTERNS)
    ):
        return safe
    return out


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    return digits


def extract_contact_handle(text: str) -> Tuple[str, str]:
    """
    Parse WhatsApp / Snapchat / phone from an inbound reply.
    Returns (handle, kind) where kind is whatsapp | snapchat | phone | "".
    """
    t = (text or "").strip()
    if not t:
        return "", ""
    for rx in _CONTACT_SNAP_RE:
        m = rx.search(t)
        if m:
            handle = m.group(1).strip().lstrip("@")
            if handle.lower() not in _CONTACT_SNAP_STOPWORDS:
                return handle, "snapchat"
    for rx in _CONTACT_WA_RE:
        m = rx.search(t)
        if m:
            phone = _normalize_phone(m.group(1))
            if len(re.sub(r"\D", "", phone)) >= 7:
                kind = (
                    "whatsapp" if re.search(r"whats?app|\bwa\b", t, re.I) else "phone"
                )
                return phone, kind
    # Loose phone only when message clearly offers a number
    if re.search(r"\b(number|whats?app|wa|text|call|phone)\b", t, re.I):
        m = _CONTACT_PHONE_LOOSE_RE.search(t)
        if m:
            phone = _normalize_phone(m.group(1))
            if len(re.sub(r"\D", "", phone)) >= 7:
                kind = (
                    "whatsapp" if re.search(r"whats?app|\bwa\b", t, re.I) else "phone"
                )
                return phone, kind
    return "", ""


def _normalize_contact_order(raw: Any) -> List[str]:
    allowed = {"whatsapp", "snapchat"}
    out: List[str] = []
    for x in list(raw or []) or list(DEFAULT_CONTACT_ASK_ORDER):
        v = str(x).strip().lower()
        if v in ("wa", "whats", "whatsapp"):
            v = "whatsapp"
        elif v in ("snap", "sc", "snapchat"):
            v = "snapchat"
        if v in allowed and v not in out:
            out.append(v)
    return out or list(DEFAULT_CONTACT_ASK_ORDER)


def build_contact_ask_text(cfg: "DateFlowConfig", channel: str = "whatsapp") -> str:
    ch = (channel or "whatsapp").strip().lower()
    if ch == "snapchat":
        text = (
            cfg.contact_ask_snapchat_text
            or cfg.contact_ask_text
            or DEFAULT_CONTACT_ASK_SNAPCHAT
        ).strip() or DEFAULT_CONTACT_ASK_SNAPCHAT
    else:
        text = (
            cfg.contact_ask_whatsapp_text
            or cfg.contact_ask_text
            or DEFAULT_CONTACT_ASK_WHATSAPP
        ).strip() or DEFAULT_CONTACT_ASK_WHATSAPP
    return strip_stay_over_wording(text) if contains_stay_over_wording(text) else text


@dataclass
class DateFlowConfig:
    """Global (or resolved) reply persona + date-invite settings."""

    reply_persona_prompt: str = DEFAULT_REPLY_PERSONA
    invite_days_min: int = DEFAULT_INVITE_DAYS_MIN
    invite_days_max: int = DEFAULT_INVITE_DAYS_MAX
    home_location: str = DEFAULT_HOME_LOCATION
    radius_miles: float = DEFAULT_RADIUS_MILES
    invite_enabled: bool = True
    handoff_enabled: bool = True
    calendar_on_handoff: bool = True
    contact_ask_enabled: bool = True
    contact_ask_order: List[str] = field(
        default_factory=lambda: list(DEFAULT_CONTACT_ASK_ORDER)
    )
    contact_ask_whatsapp_text: str = DEFAULT_CONTACT_ASK_WHATSAPP
    contact_ask_snapchat_text: str = DEFAULT_CONTACT_ASK_SNAPCHAT
    # Legacy single wording (falls back into channel-specific texts)
    contact_ask_text: str = DEFAULT_CONTACT_ASK
    # Per-app overrides: package -> partial dict
    per_app: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def clamp(self) -> "DateFlowConfig":
        lo = max(1, int(self.invite_days_min))
        hi = max(lo, int(self.invite_days_max))
        self.invite_days_min = lo
        self.invite_days_max = hi
        self.radius_miles = max(1.0, float(self.radius_miles or DEFAULT_RADIUS_MILES))
        self.home_location = (self.home_location or DEFAULT_HOME_LOCATION).strip()
        self.reply_persona_prompt = (
            self.reply_persona_prompt or DEFAULT_REPLY_PERSONA
        ).strip()
        self.contact_ask_order = _normalize_contact_order(self.contact_ask_order)
        self.contact_ask_whatsapp_text = (
            self.contact_ask_whatsapp_text
            or self.contact_ask_text
            or DEFAULT_CONTACT_ASK_WHATSAPP
        ).strip() or DEFAULT_CONTACT_ASK_WHATSAPP
        self.contact_ask_snapchat_text = (
            self.contact_ask_snapchat_text or DEFAULT_CONTACT_ASK_SNAPCHAT
        ).strip() or DEFAULT_CONTACT_ASK_SNAPCHAT
        self.contact_ask_text = (
            self.contact_ask_text or self.contact_ask_whatsapp_text
        ).strip() or DEFAULT_CONTACT_ASK
        return self

    def for_app(self, package_name: str = "") -> "DateFlowConfig":
        """Merge per-app overrides onto a copy."""
        cfg = deepcopy(self)
        ov = (self.per_app or {}).get(package_name) or {}
        for k, v in ov.items():
            if k == "per_app":
                continue
            if hasattr(cfg, k) and v is not None:
                setattr(cfg, k, v)
        return cfg.clamp()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reply_persona_prompt": self.reply_persona_prompt,
            "invite_days_min": self.invite_days_min,
            "invite_days_max": self.invite_days_max,
            "home_location": self.home_location,
            "radius_miles": self.radius_miles,
            "invite_enabled": self.invite_enabled,
            "handoff_enabled": self.handoff_enabled,
            "calendar_on_handoff": self.calendar_on_handoff,
            "contact_ask_enabled": self.contact_ask_enabled,
            "contact_ask_order": list(self.contact_ask_order),
            "contact_ask_whatsapp_text": self.contact_ask_whatsapp_text,
            "contact_ask_snapchat_text": self.contact_ask_snapchat_text,
            "contact_ask_text": self.contact_ask_text,
            "per_app": dict(self.per_app or {}),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DateFlowConfig":
        raw = data or {}
        return cls(
            reply_persona_prompt=str(
                raw.get("reply_persona_prompt") or DEFAULT_REPLY_PERSONA
            ),
            invite_days_min=int(
                raw.get("invite_days_min", DEFAULT_INVITE_DAYS_MIN)
                or DEFAULT_INVITE_DAYS_MIN
            ),
            invite_days_max=int(
                raw.get("invite_days_max", DEFAULT_INVITE_DAYS_MAX)
                or DEFAULT_INVITE_DAYS_MAX
            ),
            home_location=str(raw.get("home_location") or DEFAULT_HOME_LOCATION),
            radius_miles=float(
                raw.get("radius_miles", DEFAULT_RADIUS_MILES) or DEFAULT_RADIUS_MILES
            ),
            invite_enabled=bool(raw.get("invite_enabled", True)),
            handoff_enabled=bool(raw.get("handoff_enabled", True)),
            calendar_on_handoff=bool(raw.get("calendar_on_handoff", True)),
            contact_ask_enabled=bool(raw.get("contact_ask_enabled", True)),
            contact_ask_order=list(
                raw.get("contact_ask_order") or DEFAULT_CONTACT_ASK_ORDER
            ),
            contact_ask_whatsapp_text=str(
                raw.get("contact_ask_whatsapp_text")
                or raw.get("contact_ask_text")
                or DEFAULT_CONTACT_ASK_WHATSAPP
            ),
            contact_ask_snapchat_text=str(
                raw.get("contact_ask_snapchat_text") or DEFAULT_CONTACT_ASK_SNAPCHAT
            ),
            contact_ask_text=str(raw.get("contact_ask_text") or DEFAULT_CONTACT_ASK),
            per_app=dict(raw.get("per_app") or {}),
        ).clamp()


@dataclass
class MatchContactRecord:
    """Private per-user match contact (WhatsApp / Snap) — never auto-messaged."""

    match_id: str
    package_name: str = ""
    contact_handle: str = ""
    contact_kind: str = ""
    whatsapp: str = ""
    snapchat: str = ""
    date_details: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchContactRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class ChatDateState:
    """Per-match date-flow state."""

    match_id: str
    package_name: str = ""
    chat_started_at: Optional[str] = None
    days_chatting: float = 0.0
    message_count: int = 0
    her_message_count: int = 0
    invite_sent: bool = False
    invite_declined: bool = False
    invite_text: str = ""
    handoff: bool = False
    handoff_reason: str = ""
    date_booked: bool = False
    date_details: str = ""
    distance_miles: Optional[float] = None
    ai_replies_stopped: bool = False
    last_inbound: str = ""
    engaged: bool = False
    contact_ask_sent: bool = False
    contact_ask_pending: bool = False
    contact_ask_channel: str = ""
    contact_asks_done: List[str] = field(default_factory=list)
    contact_handle: str = ""
    contact_kind: str = ""
    whatsapp: str = ""
    snapchat: str = ""
    her_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatDateState":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        raw = {k: v for k, v in (data or {}).items() if k in known}
        if "contact_asks_done" in raw and not isinstance(
            raw["contact_asks_done"], list
        ):
            raw["contact_asks_done"] = list(raw["contact_asks_done"] or [])
        return cls(**raw)


@dataclass
class DateFlowDecision:
    """Outcome of evaluating an inbound message / reply turn."""

    stop_ai: bool = False
    needs_you: bool = False
    needs_you_kind: str = ""  # date_handoff | discomfort | invite
    reason: str = ""
    should_invite: bool = False
    invite_text: str = ""
    should_contact_ask: bool = False
    contact_ask_text: str = ""
    contact_ask_channel: str = ""
    contact_handle: str = ""
    contact_kind: str = ""
    beyond_radius: bool = False
    calendar_entry: Optional[Dict[str, Any]] = None
    reply_persona_prompt: str = ""
    chat_state: Optional[ChatDateState] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.chat_state:
            d["chat_state"] = self.chat_state.to_dict()
        return d


def pick_invite_day_threshold(
    cfg: DateFlowConfig, *, rng: Optional[random.Random] = None
) -> int:
    """Random day count in [min, max] inclusive."""
    cfg = cfg.clamp()
    rng = rng or random.Random()
    return rng.randint(cfg.invite_days_min, cfg.invite_days_max)


def is_beyond_radius(distance_miles: Optional[float], radius_miles: float) -> bool:
    if distance_miles is None:
        return False
    try:
        return float(distance_miles) > float(radius_miles)
    except (TypeError, ValueError):
        return False


def build_invite_text(
    cfg: DateFlowConfig,
    *,
    distance_miles: Optional[float] = None,
    her_name: str = "",
) -> str:
    """One polite public-place invite; never stay-over / his home."""
    cfg = cfg.clamp()
    name = (her_name or "").strip()
    prefix = (
        f"{name}, " if name and re.match(r"^[A-Za-z][A-Za-z\-']{0,30}$", name) else ""
    )
    beyond = is_beyond_radius(distance_miles, cfg.radius_miles)
    if beyond:
        text = (
            f"{prefix}I've really enjoyed chatting — would you fancy meeting up in "
            f"{cfg.home_location} sometime for a coffee or a bite somewhere public "
            f"(café / restaurant / bar)? Totally fine if not."
        )
    else:
        text = (
            f"{prefix}I've really enjoyed chatting — want to grab a coffee or a drink "
            f"somewhere convenient for both of us (public place — café / restaurant / bar)? "
            f"No pressure either way."
        )
    return strip_stay_over_wording(text)


def conversation_is_engaged(
    *,
    her_message_count: int,
    last_inbound: str = "",
    recent_inbounds: Optional[List[str]] = None,
) -> bool:
    """Positive/engaged heuristic: replies back + warm cues or questions."""
    if her_message_count < 2:
        return False
    blob = " ".join([last_inbound or ""] + list(recent_inbounds or []))
    if _match_any(blob, DECLINE_HINTS):
        return False
    if her_message_count >= 4:
        return True
    return _match_any(blob, POSITIVE_ENGAGEMENT_HINTS) or "?" in (last_inbound or "")


def detect_handoff(inbound: str, *, invite_was_sent: bool = False) -> Tuple[bool, str]:
    """
    Returns (should_handoff, reason).
    Agreeing day/time/place OR logistical/personal questions → handoff.
    """
    text = inbound or ""
    if _match_any(text, DECLINE_HINTS):
        return True, "discomfort_or_decline"
    if _match_any(text, HANDOFF_LOGISTICS_HINTS):
        return True, "logistics_or_personal"
    if invite_was_sent and _match_any(text, HANDOFF_AGREE_HINTS):
        return True, "date_agreed"
    if _match_any(text, HANDOFF_AGREE_HINTS):
        return True, "date_agreed"
    return False, ""


def days_since(iso_start: Optional[str], now: Optional[datetime] = None) -> float:
    if not iso_start:
        return 0.0
    now = now or datetime.now()
    try:
        start = datetime.fromisoformat(iso_start.replace("Z", ""))
    except ValueError:
        return 0.0
    return max(0.0, (now - start).total_seconds() / 86400.0)


class DateFlowManager:
    """Stateful evaluator for reply persona + date invites + handoff."""

    def __init__(
        self,
        config: Optional[DateFlowConfig] = None,
        *,
        persist_path: Optional[Path] = None,
        rng: Optional[random.Random] = None,
        push_needs_you: Optional[Callable[..., str]] = None,
        on_match_upsert: Optional[Callable[..., Any]] = None,
    ):
        self.config = (config or DateFlowConfig()).clamp()
        self.persist_path = persist_path
        self.rng = rng or random.Random()
        self.push_needs_you = push_needs_you
        # Optional MatchStore.upsert_from_date_flow(**kwargs) — never logs contacts
        self.on_match_upsert = on_match_upsert
        self._chats: Dict[str, ChatDateState] = {}
        self._matches: Dict[str, MatchContactRecord] = {}
        self._invite_threshold: Dict[str, int] = {}
        self._stats = {
            "chats_active": 0,
            "invites_sent": 0,
            "dates_booked": 0,
            "by_app": {},
        }
        if persist_path and persist_path.exists():
            self._load()

    def _key(self, package_name: str, match_id: str) -> str:
        return f"{package_name or '_'}::{match_id}"

    def get_chat(self, match_id: str, package_name: str = "") -> ChatDateState:
        k = self._key(package_name, match_id)
        if k not in self._chats:
            self._chats[k] = ChatDateState(
                match_id=match_id,
                package_name=package_name,
                chat_started_at=datetime.now().isoformat(),
            )
            self._bump_stat(package_name, "chats_active", 1)
        return self._chats[k]

    def get_match_record(
        self, match_id: str, package_name: str = ""
    ) -> Optional[MatchContactRecord]:
        return self._matches.get(self._key(package_name, match_id))

    def save_match_contact(
        self,
        *,
        match_id: str,
        package_name: str,
        contact_handle: str = "",
        contact_kind: str = "",
        whatsapp: str = "",
        snapchat: str = "",
        date_details: str = "",
        her_name: str = "",
        distance_miles: Optional[float] = None,
        status: str = "booked",
    ) -> MatchContactRecord:
        """Persist private per-user contact on the match record (no auto-message)."""
        k = self._key(package_name, match_id)
        wa = whatsapp
        sn = snapchat
        kind = (contact_kind or "").lower()
        if contact_handle and not wa and not sn:
            if kind in ("whatsapp", "phone"):
                wa = contact_handle
                kind = "whatsapp" if kind == "phone" else kind
            elif kind == "snapchat":
                sn = contact_handle
        prev = self._matches.get(k)
        if prev:
            wa = wa or prev.whatsapp
            sn = sn or prev.snapchat
        handle = contact_handle or wa or sn
        kind = kind or (
            "whatsapp" if wa and not sn else "snapchat" if sn else contact_kind
        )
        rec = MatchContactRecord(
            match_id=match_id,
            package_name=package_name,
            contact_handle=handle,
            contact_kind=kind,
            whatsapp=wa,
            snapchat=sn,
            date_details=date_details,
            updated_at=datetime.now().isoformat(),
        )
        self._matches[k] = rec
        self._emit_match_upsert(
            match_id=match_id,
            package_name=package_name,
            name=her_name,
            date_agreed=date_details,
            distance_miles=distance_miles,
            whatsapp=wa,
            snapchat=sn,
            status=status,
        )
        return rec

    def _emit_match_upsert(self, **kwargs: Any) -> None:
        if not self.on_match_upsert:
            return
        try:
            self.on_match_upsert(**kwargs)
        except TypeError:
            try:
                self.on_match_upsert(kwargs)  # type: ignore[misc]
            except Exception:
                pass
        except Exception:
            pass

    def _next_contact_channel(self, cfg: DateFlowConfig, chat: ChatDateState) -> str:
        done = {str(x).lower() for x in (chat.contact_asks_done or [])}
        for ch in cfg.contact_ask_order:
            if ch not in done:
                return ch
        return ""

    def _start_contact_ask(
        self,
        decision: DateFlowDecision,
        chat: ChatDateState,
        cfg: DateFlowConfig,
        *,
        channel: str,
        reason: str = "date_agreed_contact_ask",
    ) -> DateFlowDecision:
        ask = build_contact_ask_text(cfg, channel)
        decision.should_contact_ask = True
        decision.contact_ask_text = ask
        decision.contact_ask_channel = channel
        decision.reason = reason
        chat.contact_ask_sent = True
        chat.contact_ask_pending = True
        chat.contact_ask_channel = channel
        decision.chat_state = chat
        self._persist()
        return decision

    def _bump_stat(self, package_name: str, field_name: str, delta: int = 1) -> None:
        self._stats[field_name] = int(self._stats.get(field_name) or 0) + delta
        by = self._stats.setdefault("by_app", {})
        row = by.setdefault(
            package_name or "_",
            {"chats_active": 0, "invites_sent": 0, "dates_booked": 0},
        )
        row[field_name] = int(row.get(field_name) or 0) + delta

    def invite_threshold_for(self, match_id: str, package_name: str = "") -> int:
        k = self._key(package_name, match_id)
        if k not in self._invite_threshold:
            cfg = self.config.for_app(package_name)
            self._invite_threshold[k] = pick_invite_day_threshold(cfg, rng=self.rng)
        return self._invite_threshold[k]

    def evaluate_turn(
        self,
        *,
        match_id: str,
        package_name: str = "",
        inbound: str = "",
        distance_miles: Optional[float] = None,
        her_name: str = "",
        now: Optional[datetime] = None,
        is_opener: bool = False,
    ) -> DateFlowDecision:
        """
        Evaluate inbound before composing an AI reply.

        If stop_ai: caller must NOT send an AI reply (Needs-you owns the chat).
        After date agree, may emit one optional contact ask before final handoff.
        """
        now = now or datetime.now()
        cfg = self.config.for_app(package_name)
        chat = self.get_chat(match_id, package_name)
        if distance_miles is not None:
            chat.distance_miles = float(distance_miles)
        if inbound:
            chat.last_inbound = inbound
            chat.her_message_count += 1
            chat.message_count += 1
        chat.days_chatting = days_since(chat.chat_started_at, now)
        chat.engaged = conversation_is_engaged(
            her_message_count=chat.her_message_count,
            last_inbound=inbound or chat.last_inbound,
        )

        decision = DateFlowDecision(
            reply_persona_prompt=cfg.reply_persona_prompt,
            chat_state=chat,
            beyond_radius=is_beyond_radius(chat.distance_miles, cfg.radius_miles),
            contact_handle=chat.contact_handle,
            contact_kind=chat.contact_kind,
        )

        if chat.ai_replies_stopped or chat.handoff:
            decision.stop_ai = True
            decision.needs_you = True
            decision.needs_you_kind = chat.handoff_reason or "date_handoff"
            decision.reason = "AI already handed off this chat"
            return decision

        if is_opener:
            self._persist()
            return decision

        if her_name:
            chat.her_name = her_name

        # After a contact ask: capture / decline (maybe next channel) / ignore → hand off.
        # Re-compose with the same agree inbound re-emits the current ask (idempotent).
        if chat.contact_ask_pending and inbound:
            if inbound.strip() == (chat.date_details or "").strip():
                ch = chat.contact_ask_channel or self._next_contact_channel(cfg, chat)
                return self._start_contact_ask(
                    decision, chat, cfg, channel=ch or "whatsapp"
                )
            return self._resolve_contact_ask(
                decision,
                chat,
                cfg,
                inbound=inbound,
                her_name=her_name,
                package_name=package_name,
            )

        # Discomfort / decline always escalates (pre-contact-ask)
        if inbound and _match_any(inbound, DECLINE_HINTS):
            chat.invite_declined = True
            self._emit_match_upsert(
                match_id=match_id,
                package_name=package_name,
                name=her_name or chat.her_name,
                status="handed_off",
                distance_miles=chat.distance_miles,
            )
            return self._handoff(
                decision,
                chat,
                cfg,
                kind="discomfort",
                reason="Match expressed discomfort or declined",
                inbound=inbound,
                her_name=her_name,
                package_name=package_name,
            )

        # Handoff on agree / logistics
        if cfg.handoff_enabled and inbound:
            do_h, why = detect_handoff(inbound, invite_was_sent=chat.invite_sent)
            if do_h:
                if why == "discomfort_or_decline":
                    chat.invite_declined = True
                    return self._handoff(
                        decision,
                        chat,
                        cfg,
                        kind="discomfort",
                        reason=why,
                        inbound=inbound,
                        her_name=her_name,
                        package_name=package_name,
                    )
                if why == "date_agreed":
                    chat.date_booked = True
                    chat.date_details = inbound.strip()
                    self._bump_stat(package_name, "dates_booked", 1)
                    self._emit_match_upsert(
                        match_id=match_id,
                        package_name=package_name,
                        name=her_name or chat.her_name,
                        date_agreed=chat.date_details,
                        distance_miles=chat.distance_miles,
                        status="booked",
                    )
                    # Ordered contact asks (default WhatsApp → Snapchat)
                    if cfg.contact_ask_enabled:
                        channel = self._next_contact_channel(cfg, chat)
                        if channel:
                            return self._start_contact_ask(
                                decision, chat, cfg, channel=channel
                            )
                    return self._handoff(
                        decision,
                        chat,
                        cfg,
                        kind="date_handoff",
                        reason=why,
                        inbound=inbound,
                        her_name=her_name,
                        package_name=package_name,
                    )
                return self._handoff(
                    decision,
                    chat,
                    cfg,
                    kind="date_handoff",
                    reason=why,
                    inbound=inbound,
                    her_name=her_name,
                    package_name=package_name,
                )

        # Maybe send one polite invite
        if (
            cfg.invite_enabled
            and not chat.invite_sent
            and not chat.invite_declined
            and chat.engaged
        ):
            threshold = self.invite_threshold_for(match_id, package_name)
            if chat.days_chatting >= float(threshold):
                invite = build_invite_text(
                    cfg,
                    distance_miles=chat.distance_miles,
                    her_name=her_name,
                )
                assert not contains_stay_over_wording(invite)
                decision.should_invite = True
                decision.invite_text = invite
                chat.invite_sent = True
                chat.invite_text = invite
                self._bump_stat(package_name, "invites_sent", 1)
                self._emit_match_upsert(
                    match_id=match_id,
                    package_name=package_name,
                    name=her_name or chat.her_name,
                    status="invited",
                    distance_miles=chat.distance_miles,
                )

        self._persist()
        decision.chat_state = chat
        return decision

    def _resolve_contact_ask(
        self,
        decision: DateFlowDecision,
        chat: ChatDateState,
        cfg: DateFlowConfig,
        *,
        inbound: str,
        her_name: str,
        package_name: str,
    ) -> DateFlowDecision:
        """Capture handle, or on decline ask next channel once; ignore → hand off."""
        pending_ch = (chat.contact_ask_channel or "whatsapp").lower()
        chat.contact_ask_pending = False
        declined = _match_any(inbound, CONTACT_DECLINE_HINTS) or _match_any(
            inbound, DECLINE_HINTS
        )
        handle, kind = ("", "")
        if not declined:
            handle, kind = extract_contact_handle(inbound)
        if handle:
            # Normalize phone shares while WhatsApp was asked → whatsapp
            if kind == "phone" and pending_ch == "whatsapp":
                kind = "whatsapp"
            if kind not in ("whatsapp", "snapchat"):
                kind = pending_ch if pending_ch in ("whatsapp", "snapchat") else kind
            chat.contact_handle = handle
            chat.contact_kind = kind
            if kind == "snapchat":
                chat.snapchat = handle
            else:
                chat.whatsapp = handle
                kind = "whatsapp"
            decision.contact_handle = handle
            decision.contact_kind = kind
            if pending_ch and pending_ch not in chat.contact_asks_done:
                chat.contact_asks_done.append(pending_ch)
            self.save_match_contact(
                match_id=chat.match_id,
                package_name=package_name,
                contact_handle=handle,
                contact_kind=kind,
                whatsapp=chat.whatsapp,
                snapchat=chat.snapchat,
                date_details=chat.date_details,
                her_name=her_name or chat.her_name,
                distance_miles=chat.distance_miles,
                status="handed_off",
            )
            return self._handoff(
                decision,
                chat,
                cfg,
                kind="date_handoff",
                reason="date_agreed_contact_shared",
                inbound=inbound,
                her_name=her_name,
                package_name=package_name,
            )

        if pending_ch and pending_ch not in chat.contact_asks_done:
            chat.contact_asks_done.append(pending_ch)
        chat.contact_ask_channel = ""

        if declined:
            # Decline WhatsApp → ask Snapchat once (or next in configured order)
            nxt = self._next_contact_channel(cfg, chat)
            if nxt:
                return self._start_contact_ask(
                    decision,
                    chat,
                    cfg,
                    channel=nxt,
                    reason=f"contact_declined_ask_{nxt}",
                )
            return self._handoff(
                decision,
                chat,
                cfg,
                kind="date_handoff",
                reason="contact_declined",
                inbound=inbound,
                her_name=her_name,
                package_name=package_name,
            )

        # Ignore / unrelated reply: still hand off; do not ask further channels
        return self._handoff(
            decision,
            chat,
            cfg,
            kind="date_handoff",
            reason="contact_ignored",
            inbound=inbound,
            her_name=her_name,
            package_name=package_name,
        )

    def _handoff(
        self,
        decision: DateFlowDecision,
        chat: ChatDateState,
        cfg: DateFlowConfig,
        *,
        kind: str,
        reason: str,
        inbound: str,
        her_name: str,
        package_name: str,
    ) -> DateFlowDecision:
        chat.handoff = True
        chat.ai_replies_stopped = True
        chat.contact_ask_pending = False
        chat.handoff_reason = reason
        decision.stop_ai = True
        decision.needs_you = True
        decision.needs_you_kind = kind
        decision.reason = reason
        decision.contact_handle = chat.contact_handle
        decision.contact_kind = chat.contact_kind
        decision.chat_state = chat
        self._emit_match_upsert(
            match_id=chat.match_id,
            package_name=package_name,
            name=her_name or chat.her_name,
            date_agreed=chat.date_details or "",
            distance_miles=chat.distance_miles,
            whatsapp=chat.whatsapp,
            snapchat=chat.snapchat,
            status="handed_off",
        )
        if cfg.calendar_on_handoff and chat.date_booked:
            decision.calendar_entry = {
                "title": f"Date with {her_name or chat.match_id}",
                "details": chat.date_details or inbound,
                "location_hint": (
                    cfg.home_location
                    if decision.beyond_radius
                    else "mutually convenient public place"
                ),
                "created_at": datetime.now().isoformat(),
            }
        if self.push_needs_you:
            bits = []
            if chat.whatsapp:
                bits.append(f"WhatsApp: {chat.whatsapp}")
            if chat.snapchat:
                bits.append(f"Snapchat: {chat.snapchat}")
            if not bits and chat.contact_handle:
                bits.append(
                    f"Contact ({chat.contact_kind or 'shared'}): {chat.contact_handle}"
                )
            contact_line = (" " + "; ".join(bits) + ".") if bits else ""
            try:
                self.push_needs_you(
                    kind=kind,
                    app=package_name,
                    title=f"Needs you · dating · {her_name or chat.match_id}",
                    body=(
                        f"{reason}. "
                        + (
                            f"Date details: {chat.date_details}. "
                            if chat.date_details
                            else ""
                        )
                        + contact_line
                        + " AI replies stopped — take over this chat. "
                        "Do not auto-message WhatsApp/Snap — continue personally."
                    ),
                    category="dating_date_flow",
                    meta={
                        "match_id": chat.match_id,
                        "invite_text": chat.invite_text,
                        "date_details": chat.date_details,
                        "contact_handle": chat.contact_handle,
                        "contact_kind": chat.contact_kind,
                        "whatsapp": chat.whatsapp,
                        "snapchat": chat.snapchat,
                        "calendar": decision.calendar_entry,
                        "never_auto_message_contact": True,
                    },
                )
            except TypeError:
                try:
                    self.push_needs_you(reason)  # type: ignore[misc]
                except Exception:
                    pass
            except Exception:
                pass
        self._persist()
        return decision

    def stats_summary(self) -> Dict[str, Any]:
        return {
            "chats_active": int(self._stats.get("chats_active") or 0),
            "invites_sent": int(self._stats.get("invites_sent") or 0),
            "dates_booked": int(self._stats.get("dates_booked") or 0),
            "by_app": dict(self._stats.get("by_app") or {}),
            "open_chats": [
                c.to_dict() for c in self._chats.values() if not c.ai_replies_stopped
            ],
            "handed_off": [
                c.to_dict() for c in self._chats.values() if c.ai_replies_stopped
            ],
            "match_contacts": {
                k: v.to_dict() for k, v in self._matches.items() if v.contact_handle
            },
        }

    def _persist(self) -> None:
        if not self.persist_path:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": self.config.to_dict(),
            "chats": {k: v.to_dict() for k, v in self._chats.items()},
            "matches": {k: v.to_dict() for k, v in self._matches.items()},
            "invite_threshold": dict(self._invite_threshold),
            "stats": self._stats,
            "saved_at": datetime.now().isoformat(),
        }
        self.persist_path.write_text(json.dumps(payload, indent=2))

    def _load(self) -> None:
        try:
            raw = json.loads(self.persist_path.read_text())  # type: ignore
            self.config = DateFlowConfig.from_dict(raw.get("config"))
            self._chats = {
                k: ChatDateState.from_dict(v)
                for k, v in (raw.get("chats") or {}).items()
            }
            self._matches = {
                k: MatchContactRecord.from_dict(v)
                for k, v in (raw.get("matches") or {}).items()
            }
            self._invite_threshold = {
                k: int(v) for k, v in (raw.get("invite_threshold") or {}).items()
            }
            self._stats = raw.get("stats") or self._stats
        except Exception:
            pass


def default_persist_path() -> Path:
    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    return root / "dating_date_flow.json"
