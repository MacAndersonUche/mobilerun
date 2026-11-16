"""Rate limits + helpers for QR pairing tokens."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict

_lock = Lock()
_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def check_rate_limit(
    key: str,
    *,
    limit: int = 12,
    window_seconds: float = 60.0,
) -> bool:
    """
    Return True if the call is allowed. Sliding window in-process
    (good enough per Lambda instance; complements API GW throttling).
    """
    now = time.time()
    with _lock:
        q = _buckets[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def client_key(request, owner: str | None = None) -> str:
    """Best-effort client identity for rate limiting."""
    fwd = ""
    try:
        fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    except Exception:
        fwd = ""
    ip = (
        fwd or (getattr(request.client, "host", None) if request else None) or "unknown"
    )
    return f"{owner or 'anon'}:{ip}"
