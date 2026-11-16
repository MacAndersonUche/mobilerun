"""Template opener library for Dating mode — first-contact only (no LLM).

Buckets by phone local time:
  morning   05:00–11:59
  afternoon 12:00–16:59
  evening   17:00–04:59
  any       time-neutral (always eligible as fallback / mix-in)

Rules:
- Random pick from the active bucket (+ optional neutrals)
- Never repeat the same template to the same match
- Rotate so identical text is not sent back-to-back across matches
- {name} placeholder only when a real name is known; otherwise omit
- Active templates clamped to 2–50
"""

from __future__ import annotations

import json
import random
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

BUCKETS = ("morning", "afternoon", "evening", "any")
MIN_ACTIVE = 2
MAX_ACTIVE = 50

_DEFAULT_PATHS = [
    Path(__file__).resolve().parents[2] / "config" / "dating_openers.json",
    Path.cwd() / "config" / "dating_openers.json",
]


@dataclass
class OpenerTemplate:
    id: str
    text: str
    bucket: str = "any"  # morning | afternoon | evening | any
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenerTemplate":
        bucket = str(data.get("bucket") or "any").lower()
        if bucket not in BUCKETS:
            bucket = "any"
        return cls(
            id=str(data.get("id") or ""),
            text=str(data.get("text") or "").strip(),
            bucket=bucket,
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class OpenerLibrary:
    templates: List[OpenerTemplate] = field(default_factory=list)
    opener_mode: str = "templates"  # templates | ai
    version: int = 1
    min_active: int = MIN_ACTIVE
    max_active: int = MAX_ACTIVE
    # Per-app override: package_name -> templates | ai | None (inherit global)
    per_app_mode: Dict[str, str] = field(default_factory=dict)
    # Rotation / no-repeat state
    used_by_match: Dict[str, List[str]] = field(default_factory=dict)
    last_sent_template_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "opener_mode": self.opener_mode,
            "min_active": self.min_active,
            "max_active": self.max_active,
            "per_app_mode": dict(self.per_app_mode),
            "templates": [t.to_dict() for t in self.templates],
            "used_by_match": {k: list(v) for k, v in self.used_by_match.items()},
            "last_sent_template_id": self.last_sent_template_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenerLibrary":
        raw = data or {}
        templates = [
            OpenerTemplate.from_dict(t)
            for t in (raw.get("templates") or [])
            if t and t.get("id") and t.get("text")
        ]
        mode = str(raw.get("opener_mode") or "templates").lower()
        if mode not in ("templates", "ai"):
            mode = "templates"
        per_app = {}
        for k, v in (raw.get("per_app_mode") or {}).items():
            vv = str(v).lower()
            if vv in ("templates", "ai"):
                per_app[str(k)] = vv
        used = {
            str(k): [str(x) for x in (v or [])]
            for k, v in (raw.get("used_by_match") or {}).items()
        }
        return cls(
            templates=templates,
            opener_mode=mode,
            version=int(raw.get("version") or 1),
            min_active=int(raw.get("min_active") or MIN_ACTIVE),
            max_active=int(raw.get("max_active") or MAX_ACTIVE),
            per_app_mode=per_app,
            used_by_match=used,
            last_sent_template_id=raw.get("last_sent_template_id"),
        )

    def active_templates(self) -> List[OpenerTemplate]:
        enabled = [t for t in self.templates if t.enabled and t.text]
        # Prefer first max_active enabled (UI should enforce; clamp here)
        return (
            enabled[: max(self.min_active, min(self.max_active, len(enabled) or 0))]
            or enabled
        )

    def mode_for_app(self, package_name: str = "") -> str:
        if package_name and package_name in self.per_app_mode:
            return self.per_app_mode[package_name]
        return self.opener_mode

    def set_template(self, tmpl: OpenerTemplate) -> None:
        for i, t in enumerate(self.templates):
            if t.id == tmpl.id:
                self.templates[i] = tmpl
                return
        self.templates.append(tmpl)

    def delete_template(self, template_id: str) -> bool:
        before = len(self.templates)
        self.templates = [t for t in self.templates if t.id != template_id]
        return len(self.templates) < before

    def enabled_count(self) -> int:
        return sum(1 for t in self.templates if t.enabled)


def default_openers_path() -> Path:
    for p in _DEFAULT_PATHS:
        if p.exists():
            return p
    return _DEFAULT_PATHS[0]


def load_default_library(path: Optional[Path] = None) -> OpenerLibrary:
    path = path or default_openers_path()
    if not path.exists():
        return OpenerLibrary()
    data = json.loads(path.read_text())
    return OpenerLibrary.from_dict(data)


def merge_with_defaults(
    user_data: Optional[Dict[str, Any]],
    *,
    defaults: Optional[OpenerLibrary] = None,
) -> OpenerLibrary:
    """User library wins; empty user → seed from file defaults."""
    base = defaults or load_default_library()
    if not user_data:
        return deepcopy(base)
    lib = OpenerLibrary.from_dict(user_data)
    if not lib.templates:
        lib.templates = list(base.templates)
    return lib


def bucket_for_local_time(now: Optional[datetime] = None) -> str:
    """Return morning | afternoon | evening for phone-local time."""
    now = now or datetime.now()
    t = now.time() if isinstance(now, datetime) else now
    if isinstance(t, datetime):
        t = t.time()
    # morning 05:00–11:59
    if dtime(5, 0) <= t <= dtime(11, 59, 59):
        return "morning"
    # afternoon 12:00–16:59
    if dtime(12, 0) <= t <= dtime(16, 59, 59):
        return "afternoon"
    # evening 17:00–04:59 (wraps midnight)
    return "evening"


_NAME_PLACEHOLDER = re.compile(r"\{\s*name\s*\}", re.I)
# Trailing fragments after stripping unknown name, e.g. "Hey ," → "Hey"
_CLEAN_SPACE = re.compile(r"[ \t]{2,}")
_CLEAN_PUNCT = re.compile(r"\s+([,;])")


def render_opener_text(text: str, name: Optional[str] = None) -> str:
    """Substitute {name} only when known; otherwise omit the placeholder cleanly."""
    known = bool(
        name
        and str(name).strip()
        and str(name).strip().lower()
        not in (
            "unknown",
            "match",
            "someone",
            "?",
        )
    )
    if known:
        out = _NAME_PLACEHOLDER.sub(str(name).strip(), text)
    else:
        out = _NAME_PLACEHOLDER.sub("", text)
        out = _CLEAN_PUNCT.sub(r"\1", out)
        out = _CLEAN_SPACE.sub(" ", out)
        out = out.replace(" ,", ",").replace("  ", " ").strip()
        # Fix "Hey ," / "Morning —" leftovers
        out = re.sub(r"\s+,", ",", out)
        out = re.sub(r"^[,;\-\s]+", "", out)
        out = re.sub(r"\s{2,}", " ", out).strip()
    return out.strip()


@dataclass
class OpenerPick:
    template_id: str
    text: str
    bucket: str
    raw_text: str
    used_llm: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _eligible(
    lib: OpenerLibrary,
    bucket: str,
    *,
    match_key: str,
    exclude_ids: Optional[Set[str]] = None,
) -> List[OpenerTemplate]:
    used = set(lib.used_by_match.get(match_key) or [])
    if exclude_ids:
        used |= set(exclude_ids)
    active = lib.active_templates()
    # Primary: current bucket; always allow "any" neutrals in the pool
    pool = [
        t
        for t in active
        if t.id not in used and (t.bucket == bucket or t.bucket == "any")
    ]
    return pool


def pick_template_opener(
    lib: OpenerLibrary,
    *,
    match_id: str,
    package_name: str = "",
    profile_name: Optional[str] = None,
    now: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
) -> OpenerPick:
    """
    Pick a first-contact opener from templates.
    Raises ValueError if library cannot satisfy (caller may fall back to AI).
    """
    rng = rng or random.Random()
    match_key = f"{package_name}:{match_id}" if package_name else str(match_id)
    bucket = bucket_for_local_time(now)
    exclude: Set[str] = set()
    if lib.last_sent_template_id:
        exclude.add(lib.last_sent_template_id)

    pool = _eligible(lib, bucket, match_key=match_key, exclude_ids=exclude)
    if not pool:
        # Allow repeating last_sent across matches if pool empty, still no-repeat per match
        pool = _eligible(lib, bucket, match_key=match_key, exclude_ids=None)
    if not pool:
        # Exhausted for this match — try any unused enabled template regardless of bucket
        used = set(lib.used_by_match.get(match_key) or [])
        pool = [t for t in lib.active_templates() if t.id not in used]
    if not pool:
        raise ValueError(f"No unused templates left for match {match_key}")

    # Prefer exact bucket over "any" when both present
    exact = [t for t in pool if t.bucket == bucket]
    choice_pool = exact or pool
    tmpl = rng.choice(choice_pool)
    rendered = render_opener_text(tmpl.text, profile_name)

    # Record usage
    lib.used_by_match.setdefault(match_key, []).append(tmpl.id)
    lib.last_sent_template_id = tmpl.id

    return OpenerPick(
        template_id=tmpl.id,
        text=rendered,
        bucket=bucket,
        raw_text=tmpl.text,
        used_llm=False,
    )


def compose_dating_message(
    *,
    is_opener: bool,
    lib: OpenerLibrary,
    match_id: str,
    package_name: str = "",
    profile_name: Optional[str] = None,
    now: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
    ai_callable=None,
    inbound_preview: str = "",
) -> Dict[str, Any]:
    """
    Compose an opener or reply.

    - Openers with mode=templates → template library (no LLM)
    - Replies / AI mode openers → ai_callable (required for those paths)
    """
    mode = lib.mode_for_app(package_name)
    if is_opener and mode == "templates":
        pick = pick_template_opener(
            lib,
            match_id=match_id,
            package_name=package_name,
            profile_name=profile_name,
            now=now,
            rng=rng,
        )
        return {
            "text": pick.text,
            "source": "template",
            "template_id": pick.template_id,
            "bucket": pick.bucket,
            "used_llm": False,
            "is_opener": True,
        }

    if ai_callable is None:
        raise ValueError("AI callable required for replies / AI openers")
    text = ai_callable(
        is_opener=is_opener,
        profile_name=profile_name or "",
        inbound_preview=inbound_preview,
        package_name=package_name,
    )
    if isinstance(text, dict):
        out = dict(text)
        out.setdefault("used_llm", True)
        out.setdefault("source", "ai")
        out["is_opener"] = is_opener
        return out
    return {
        "text": str(text),
        "source": "ai",
        "used_llm": True,
        "is_opener": is_opener,
    }


def validate_active_bounds(lib: OpenerLibrary) -> Tuple[bool, str]:
    n = lib.enabled_count()
    lo = lib.min_active or MIN_ACTIVE
    hi = lib.max_active or MAX_ACTIVE
    if n < lo:
        return False, f"Need at least {lo} enabled templates (have {n})"
    if n > hi:
        return False, f"At most {hi} enabled templates (have {n} — disable some)"
    return True, "ok"


def clamp_enabled_to_max(lib: OpenerLibrary) -> int:
    """If too many are enabled, disable extras from the end (keeps file seeds loadable)."""
    enabled = [t for t in lib.templates if t.enabled]
    hi = lib.max_active or MAX_ACTIVE
    if len(enabled) <= hi:
        return 0
    disabled = 0
    for t in reversed(enabled):
        if lib.enabled_count() <= hi:
            break
        t.enabled = False
        disabled += 1
    return disabled


def summarize_buckets(lib: OpenerLibrary) -> Dict[str, int]:
    counts = {b: 0 for b in BUCKETS}
    for t in lib.templates:
        if t.enabled:
            counts[t.bucket if t.bucket in counts else "any"] += 1
    return counts
