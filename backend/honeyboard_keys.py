"""Samsung Honeyboard (S21+ 1080x2400) key coords for type_keys.

Measured from the live Hinge keyboard (27 Nov 2026). Letters + space on the
main layer; comma is also on the main bottom row. Apostrophe and question
mark live on the !#1 symbol layer — tap !#1, key them, tap ABC to return.
Never tap Done/Enter (same band as space, right edge).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

# Main QWERTY (number-row layout)
HONEYBOARD_KEYS: Dict[str, Tuple[int, int]] = {}
for _row, _y, _xs in (
    ("qwertyuiop", 1736, (68, 173, 278, 383, 488, 593, 698, 803, 908, 1013)),
    ("asdfghjkl", 1886, (120, 225, 330, 435, 540, 645, 750, 855, 960)),
    ("zxcvbnm", 2036, (225, 330, 435, 540, 645, 750, 855)),
):
    for _ch, _x in zip(_row, _xs):
        HONEYBOARD_KEYS[_ch] = (_x, _y)
HONEYBOARD_KEYS[" "] = (540, 2186)
# Main-layer punctuation (bottom row: !#1 | , | space | . | Enter)
HONEYBOARD_KEYS[","] = (225, 2186)

HONEYBOARD_BACKSPACE = (990, 2036)
HONEYBOARD_SHIFT = (86, 2036)
# !#1 on alpha / ABC on symbols — same key
HONEYBOARD_LAYER = (86, 2186)

# Symbol-layer (!#1) keys — apostrophe and question mark
HONEYBOARD_SYM_KEYS: Dict[str, Tuple[int, int]] = {
    "'": (330, 2036),
    "?": (750, 2036),
}

# Chars we can produce via type_keys (lowercased letters + punctuation)
KEYABLE_CHARS = frozenset(HONEYBOARD_KEYS) | frozenset(HONEYBOARD_SYM_KEYS)


def is_honeyboard_keyable(text: str) -> bool:
    """True when every character can be typed on Honeyboard type_keys."""
    s = (text or "").strip()
    if not s:
        return False
    return all(ch in KEYABLE_CHARS for ch in s.lower())


def first_keyable_line(
    candidates: Sequence[str], *, fallback: str = "hey how are you"
) -> str:
    """First candidate that is honeyboard-keyable, else ``fallback``."""
    for raw in candidates or ():
        t = str(raw or "").strip()
        if t and is_honeyboard_keyable(t):
            return t
    if is_honeyboard_keyable(fallback):
        return fallback
    return "hey how are you"


def key_tap_plan(text: str) -> List[Tuple[str, int, int]]:
    """
    Ordered (label, x, y) taps to type ``text`` (lowercased letters).

    Labels: ``bs`` backspace, ``shift``, ``layer`` (!#1/ABC), ``key:<ch>``.
    Raises ValueError if a character cannot be keyed.
    """
    low = (text or "").lower()
    if not low:
        raise ValueError("type_keys: empty text")
    bad = [ch for ch in low if ch not in KEYABLE_CHARS]
    if bad:
        raise ValueError(
            f"type_keys: cannot key {bad[0]!r} in {text!r} "
            f"(only letters, space, comma, apostrophe, ?)"
        )
    taps: List[Tuple[str, int, int]] = []
    layer = "alpha"  # or "sym"

    def ensure(need: str) -> None:
        nonlocal layer
        if layer == need:
            return
        taps.append(("layer", HONEYBOARD_LAYER[0], HONEYBOARD_LAYER[1]))
        layer = need

    for ch in low:
        if ch in HONEYBOARD_KEYS:
            ensure("alpha")
            x, y = HONEYBOARD_KEYS[ch]
            taps.append((f"key:{ch}", x, y))
        else:
            ensure("sym")
            x, y = HONEYBOARD_SYM_KEYS[ch]
            taps.append((f"key:{ch}", x, y))
    ensure("alpha")  # leave on the letter layer
    return taps


def clear_and_type_plan(
    text: str, *, clear_keys: int = 0, lower_first: bool = False
) -> List[Tuple[str, int, int]]:
    """Backspaces + optional Shift-off + key_tap_plan."""
    taps: List[Tuple[str, int, int]] = []
    for _ in range(max(0, min(40, int(clear_keys or 0)))):
        taps.append(("bs", HONEYBOARD_BACKSPACE[0], HONEYBOARD_BACKSPACE[1]))
    if lower_first and (text[:1].islower() if text else False):
        taps.append(("shift", HONEYBOARD_SHIFT[0], HONEYBOARD_SHIFT[1]))
    taps.extend(key_tap_plan(text))
    return taps


def filter_keyable(lines: Iterable[str]) -> List[str]:
    return [str(x).strip() for x in lines if is_honeyboard_keyable(str(x).strip())]
