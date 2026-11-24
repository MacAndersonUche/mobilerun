"""Social page actions: message one person, or reply to existing chats.

Socials (WhatsApp, Instagram, Messenger, Telegram, Snapchat, X, Facebook)
never get swipe / like / per-run settings. All socials, WhatsApp included,
follow the Dry-run toggle.
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Any, Dict, Optional

# package -> DM profile key (apps the DM planner can drive)
SOCIAL_APPS: Dict[str, str] = {
    "com.whatsapp": "whatsapp",
    "com.instagram.android": "instagram",
    "com.facebook.orca": "messenger",
    "org.telegram.messenger": "telegram",
}
# Every social package (incl. ones without a DM driver yet)
SOCIAL_PACKAGES = set(SOCIAL_APPS) | {
    "com.snapchat.android",
    "com.twitter.android",
}
REPLY_CHATS = 5  # chats per "reply to messages" (no per-run setting)


def is_social(pkg: str) -> bool:
    return str(pkg or "").strip().lower() in SOCIAL_PACKAGES


def _clean(text: str, limit: int = 300) -> str:
    t = re.sub(r"[\r\n\"]+", " ", str(text or "")).strip()
    return re.sub(r"\s+", " ", t)[:limit]


def instruction_for(pkg: str, action: str, contact: str = "", message: str = "") -> str:
    key = SOCIAL_APPS.get(pkg)
    if not key:
        raise ValueError("No message driver for this app yet")
    msg = _clean(message)
    if not msg:
        raise ValueError("Type the message first")
    if action == "message":
        name = _clean(contact, 80)
        if not name:
            raise ValueError("Type the person's name first")
        return f"{key} message {name} and say {msg}"
    if action == "reply":
        return f'reply "{msg}" to {REPLY_CHATS} existing chats on {key}'
    raise ValueError("action must be message or reply")


def build_job(
    *, device_id: str, pkg: str, action: str, contact: str, message: str, dry_run: bool
) -> Dict[str, Any]:
    instruction = instruction_for(pkg, action, contact, message)
    dry = bool(dry_run)
    now = int(time.time())
    job_id = f"task_{secrets.token_hex(8)}"
    return {
        "job_id": job_id,
        "kind": "agent",
        "mode": "social",
        "social_run": True,
        "social_action": action,
        "social_app": pkg,
        "status": "running",
        "device_id": device_id,
        "instruction": instruction,
        "max_steps": 25 if action == "message" else 40,
        "speed_preset": "balanced",
        "dry_run": dry,
        "live_test": False,
        "created_at": now,
        "next_run_at": now,
        "state": {"steps": 0, "history": [], "dry_run": dry, "current_app": pkg},
        "ttl": now + 86400,
        "result": "Queued for cloud agent",
    }
