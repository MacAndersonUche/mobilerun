"""Persist AI API token usage (Europe/London day) for the Usage page."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("mobilerun.token_usage")

LONDON = ZoneInfo("Europe/London")
SETTING_NAME = "llm_token_usage"
_CONTEXT_USER = threading.local()


def london_today() -> str:
    return datetime.now(LONDON).date().isoformat()


def set_usage_user(user_id: Optional[str]) -> None:
    """Bind the current agent step's owner for token recording."""
    _CONTEXT_USER.user_id = (user_id or "local").strip() or "local"


def clear_usage_user() -> None:
    _CONTEXT_USER.user_id = None


def _current_user() -> str:
    return getattr(_CONTEXT_USER, "user_id", None) or "local"


def _storage():
    try:
        from storage import get_user_setting, save_user_setting
    except ImportError:
        from backend.storage import get_user_setting, save_user_setting  # type: ignore

    return get_user_setting, save_user_setting


def _empty_day() -> Dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
        "by_provider": {},
    }


def record_llm_tokens(
    *,
    provider: str,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    user_id: Optional[str] = None,
) -> None:
    """Add one LLM call's tokens to today's London bucket for the user."""
    pt = max(0, int(prompt_tokens or 0))
    ct = max(0, int(completion_tokens or 0))
    tt = max(0, int(total_tokens or 0)) or (pt + ct)
    if tt <= 0 and pt <= 0 and ct <= 0:
        return
    uid = (user_id or _current_user() or "local").strip() or "local"
    prov = (provider or "unknown").strip().lower() or "unknown"
    day = london_today()
    get_user_setting, save_user_setting = _storage()
    try:
        blob = get_user_setting(uid, SETTING_NAME) or {}
    except Exception:
        logger.exception("load llm_token_usage failed user=%s", uid)
        blob = {}
    if not isinstance(blob, dict):
        blob = {}
    days = blob.get("days") if isinstance(blob.get("days"), dict) else {}
    entry = days.get(day) if isinstance(days.get(day), dict) else _empty_day()
    entry["prompt_tokens"] = int(entry.get("prompt_tokens") or 0) + pt
    entry["completion_tokens"] = int(entry.get("completion_tokens") or 0) + ct
    entry["total_tokens"] = int(entry.get("total_tokens") or 0) + tt
    entry["requests"] = int(entry.get("requests") or 0) + 1
    by_p = entry.get("by_provider") if isinstance(entry.get("by_provider"), dict) else {}
    p = by_p.get(prov) if isinstance(by_p.get(prov), dict) else {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
        "models": {},
    }
    p["prompt_tokens"] = int(p.get("prompt_tokens") or 0) + pt
    p["completion_tokens"] = int(p.get("completion_tokens") or 0) + ct
    p["total_tokens"] = int(p.get("total_tokens") or 0) + tt
    p["requests"] = int(p.get("requests") or 0) + 1
    models = p.get("models") if isinstance(p.get("models"), dict) else {}
    if model:
        models[model] = int(models.get(model) or 0) + tt
        p["models"] = models
    by_p[prov] = p
    entry["by_provider"] = by_p
    days[day] = entry
    # Keep ~60 days
    cutoff = (datetime.now(LONDON).date() - timedelta(days=60)).isoformat()
    days = {k: v for k, v in days.items() if k >= cutoff}
    blob = {"days": days, "updated_at": datetime.now(LONDON).isoformat()}
    try:
        save_user_setting(uid, SETTING_NAME, blob)
    except Exception:
        logger.exception("save llm_token_usage failed user=%s", uid)


def usage_summary(user_id: Optional[str] = None, *, days: int = 30) -> Dict[str, Any]:
    """Roll up the last ``days`` (Europe/London) for the Usage page."""
    uid = (user_id or "local").strip() or "local"
    n = max(1, min(90, int(days or 30)))
    get_user_setting, _save = _storage()
    try:
        blob = get_user_setting(uid, SETTING_NAME) or {}
    except Exception:
        logger.exception("load llm_token_usage failed user=%s", uid)
        blob = {}
    day_map = blob.get("days") if isinstance(blob, dict) and isinstance(blob.get("days"), dict) else {}
    today = datetime.now(LONDON).date()
    series: List[Dict[str, Any]] = []
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
    }
    by_provider: Dict[str, Any] = {}
    for i in range(n - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        entry = day_map.get(d) if isinstance(day_map.get(d), dict) else _empty_day()
        row = {
            "date": d,
            "prompt_tokens": int(entry.get("prompt_tokens") or 0),
            "completion_tokens": int(entry.get("completion_tokens") or 0),
            "total_tokens": int(entry.get("total_tokens") or 0),
            "requests": int(entry.get("requests") or 0),
        }
        series.append(row)
        for k in totals:
            totals[k] += row[k]
        provs = entry.get("by_provider") if isinstance(entry.get("by_provider"), dict) else {}
        for pname, pdata in provs.items():
            if not isinstance(pdata, dict):
                continue
            acc = by_provider.setdefault(
                pname,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "requests": 0,
                },
            )
            for k in ("prompt_tokens", "completion_tokens", "total_tokens", "requests"):
                acc[k] += int(pdata.get(k) or 0)
    return {
        "timezone": "Europe/London",
        "days": n,
        "from": series[0]["date"] if series else london_today(),
        "to": series[-1]["date"] if series else london_today(),
        "totals": totals,
        "by_provider": by_provider,
        "daily": series,
    }
