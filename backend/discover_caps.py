"""Per-app daily caps on messages sent on Discover (new contacts).

Mac's numbers (23 Nov 2026):
- Hinge: 50-100/day, configurable in that range, defaulting to 50 (safe end).
- Hily: 5/day.
- BLK, Yubo, Facebook Dating: unlimited.
- Bumble, Badoo, Tagged (and every other app): no cap set — Mac gave no
  number for them, so nothing is invented here; they run uncapped until he
  gives a number.

A cap counts VERIFIED sends only: a send is counted once the outgoing
message is confirmed on screen (see ``discover_send_verified`` in
``bulk_bench_heuristics``). A tap on Send that never lands does not count.

This table mirrors the AppProfile fields in ``mobilerun/dating/config.py``
(``daily_discover_message_cap`` / ``_min`` / ``_max``).
``tests/test_discover_caps.py`` asserts the two agree, so a drift fails the
suite instead of silently diverging.
"""

from typing import Dict, Optional, Tuple

# app key -> (default cap, min, max); None = unlimited.
DISCOVER_MESSAGE_CAPS: Dict[str, Optional[Tuple[int, int, int]]] = {
    "hinge": (50, 50, 100),
    "hily": (5, 5, 5),
    "blk": None,
    "yubo": None,
    "facebook": None,
}

HINGE_DISCOVER_CAP_DEFAULT = 50
HINGE_DISCOVER_CAP_MIN = 50
HINGE_DISCOVER_CAP_MAX = 100


def discover_message_cap_bounds(app: str) -> Optional[Tuple[int, int]]:
    """(min, max) configurable range for the app, or None if unlimited."""
    entry = DISCOVER_MESSAGE_CAPS.get((app or "").lower())
    if entry is None:
        return None
    return (entry[1], entry[2])


def clamp_discover_message_cap(app: str, value: int) -> Optional[int]:
    """Clamp a requested cap into the app's range; None stays unlimited."""
    bounds = discover_message_cap_bounds(app)
    if bounds is None:
        return None
    low, high = bounds
    return max(low, min(high, int(value)))


def discover_message_cap(app: str, override: Optional[int] = None) -> Optional[int]:
    """Effective daily Discover cap for the app (None = unlimited).

    ``override`` is a per-job value (e.g. Mac raising Hinge from 50 toward
    100); it is clamped into the app's range and ignored for unlimited apps.
    """
    entry = DISCOVER_MESSAGE_CAPS.get((app or "").lower())
    if entry is None:
        return None
    if override is None:
        return entry[0]
    return clamp_discover_message_cap(app, override)


def discover_messages_allowed(
    app: str, sent_today: int, override: Optional[int] = None
) -> bool:
    """True if one more verified Discover send is allowed today."""
    cap = discover_message_cap(app, override=override)
    if cap is None:
        return True
    return int(sent_today) < cap


def discover_cap_reason(
    app: str, sent_today: int, override: Optional[int] = None
) -> str:
    """Human-readable cap state for fail reasons / reports."""
    cap = discover_message_cap(app, override=override)
    if cap is None:
        return f"{app}: Discover messages unlimited"
    return (
        f"{app}: Discover message cap reached "
        f"({sent_today}/{cap} verified sends today)"
    )
