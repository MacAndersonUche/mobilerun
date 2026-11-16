"""Short human-typeable pairing codes (no ambiguous chars)."""

from __future__ import annotations

import secrets
from typing import Optional

# No 0/O/1/I/L — easy to read aloud and type on phone keyboards.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_pairing_code(length: int = 8) -> str:
    length = max(6, min(8, int(length)))
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize_pairing_code(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = str(raw).strip().upper()
    # Allow pasted links: take last path segment or c=/token=
    if "://" in s or "/" in s:
        if "/P/" in s:
            s = s.split("/P/", 1)[-1]
        elif "C=" in s:
            s = s.split("C=", 1)[-1]
        elif "TOKEN=" in s:
            s = s.split("TOKEN=", 1)[-1]
        s = s.split("?", 1)[0].split("&", 1)[0].split("#", 1)[0]
        if "/" in s:
            s = s.rstrip("/").rsplit("/", 1)[-1]
    # Strip separators users might type
    s = "".join(ch for ch in s if ch.isalnum())
    return s
