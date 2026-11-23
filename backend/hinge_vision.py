"""Vision-first Hinge driver helpers (pure — no network, no device).

Hinge Discover/Matches expose almost no accessibility tree, so the agent is
effectively blind there. The old code fell back to a hard-coded tap or a
horizontal swipe to "like" — a swipe on Hinge only flips photos, and a blind
tap risks the paid Rose button sitting next to Send Like.

Rules enforced here (and by the planner that uses them):
- Never tap blind: a like tap needs a vision-grounded heart coordinate AND a
  plausible profile first name from the same screenshot.
- The heart must sit in the Discover action row (right side, above the nav
  bar) and never inside the like-sheet Rose bounds.
- A like only counts when the card name actually changes afterwards.
- After HINGE_VISION_MAX_ASKS failed vision asks, fail — never guess.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# Mac's phone: Samsung SM-G996B / S21+ — all coordinates are native pixels.
HINGE_SCREEN_W = 1080
HINGE_SCREEN_H = 2400

# Discover action row: heart sits right (map: heart x~=937, skip at x=115,
# action row y~=2000). Nav bar starts at y~=2195 — never tap into it.
HINGE_HEART_ZONE = (700, 1500, 1080, 2190)  # (x_min, y_min, x_max, y_max)

# Like-sheet Rose button bounds (from the S21 map) — PAID, never tap.
HINGE_ROSE_BOUNDS = (95, 1225, 355, 1330)  # (x_min, y_min, x_max, y_max)

# How many times the planner may ask vision to ground the heart per card.
HINGE_VISION_MAX_ASKS = 3

# Folder / launcher / section labels vision must never report as a name.
# (Same guard as hinge_deck_card_name's skip list in dm_heuristics.)
_NON_PROFILE_WORDS = frozenset(
    {
        "jobs",
        "notes",
        "social",
        "junk",
        "travel",
        "travel & events",
        "travel and events",
        "online shopping",
        "msc uni info",
        "bible and prayer",
        "watchtv/gallery",
        "indeed job search",
        "finance & investments",
        "finance and investments",
        "discover",
        "standouts",
        "likes you",
        "matches",
        "profile",
        "your turn",
        "their turn",
        "hidden",
        "send a message",
        "like",
        "rose",
        "boost",
        "preferred",
        "hingex",
        "hinge x",
        "message",
        "type a message",
        "say something",
        "skip",
        "comment",
        "share",
        "enable for",
        "dismiss",
        "intentions",
        "education",
        "health and fitness",
    }
)

HINGE_VISION_PROMPT = (
    "This is a screenshot of the Hinge dating app on a 1080x2400 phone. "
    "Reply with exactly two lines:\n"
    "NAME: <first name of the profile card on screen>\n"
    "HEART: <x> <y> (native 1080x2400 pixels of the centre of the heart/like "
    "button on the profile card)\n"
    "Reply NONE on both lines if this is the Android launcher, a home-screen "
    "folder, a paywall, a chat thread, or no profile card is visible. "
    "Never reply with folder titles like Jobs, Social, or Notes, and never "
    "report the Rose button — only the free heart/like button."
)


def _looks_like_name(name: str) -> bool:
    """True for a plausible profile first name; rejects labels/folders."""
    raw = (name or "").strip()
    if not raw or len(raw) > 40:
        return False
    low = raw.lower().split(",")[0].strip()
    if low in _NON_PROFILE_WORDS:
        return False
    try:
        from dm_heuristics import looks_like_profile_name
    except ImportError:  # pragma: no cover - Lambda layout
        from backend.dm_heuristics import looks_like_profile_name  # type: ignore
    return bool(looks_like_profile_name(raw))


def is_plausible_profile_name(name: Optional[str]) -> bool:
    """Public wrapper for name validation (used by the planner + tests)."""
    if not name:
        return False
    return _looks_like_name(str(name))


def _point_in_bounds(
    x: int, y: int, bounds: Tuple[int, int, int, int]
) -> bool:
    x0, y0, x1, y1 = bounds
    return x0 <= x <= x1 and y0 <= y <= y1


def validate_heart_xy(x: int, y: int) -> Tuple[bool, str]:
    """Check a vision-grounded heart coordinate before any tap.

    Returns (ok, reason). Rejects out-of-screen points, the nav bar, the
    left (skip/rewind) side, and the paid Rose region.
    """
    if not (0 <= x < HINGE_SCREEN_W and 0 <= y < HINGE_SCREEN_H):
        return False, f"heart ({x},{y}) outside 1080x2400 screen"
    if _point_in_bounds(x, y, HINGE_ROSE_BOUNDS):
        return False, f"heart ({x},{y}) inside paid Rose bounds — refuse"
    if not _point_in_bounds(x, y, HINGE_HEART_ZONE):
        return False, (
            f"heart ({x},{y}) outside Discover action row "
            f"{HINGE_HEART_ZONE} — refuse blind tap"
        )
    return True, "ok"


def parse_vision_heart_reply(
    text: str,
) -> Tuple[Optional[Dict[str, object]], str]:
    """Parse a vision reply into {"name", "x", "y"} or (None, reason).

    Accepted format (case-insensitive keys, extra whitespace tolerated):
        NAME: Sarah
        HEART: 937 2000
    or a bare NONE (anywhere on the first line) meaning "no profile here".
    """
    raw = (text or "").strip()
    if not raw:
        return None, "empty vision reply"
    first_line = raw.splitlines()[0].strip().upper() if raw.splitlines() else ""
    if first_line == "NONE" or first_line.startswith("NONE"):
        return None, "vision reported no profile (NONE)"
    name_m = re.search(r"NAME\s*:\s*(.+)", raw, re.I)
    heart_m = re.search(r"HEART\s*:\s*(\d+)\s*[,\s]\s*(\d+)", raw, re.I)
    if not name_m:
        return None, "vision reply has no NAME line"
    if not heart_m:
        return None, "vision reply has no HEART coordinates"
    name = name_m.group(1).strip().split(",")[0].strip()
    # Strip any trailing second line the model may have appended to NAME.
    name = name.splitlines()[0].strip()
    if not is_plausible_profile_name(name):
        return None, f"vision name {name!r} is not a plausible profile name"
    try:
        x, y = int(heart_m.group(1)), int(heart_m.group(2))
    except ValueError:
        return None, "vision HEART coordinates are not integers"
    ok, reason = validate_heart_xy(x, y)
    if not ok:
        return None, reason
    return {"name": name, "x": x, "y": y}, "ok"
