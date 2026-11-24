"""Hard rule: auto-messaging types ONLY bank or user-provided text.

The AI/vision may navigate (tap profile → Message, dismiss prompts, focus the
compose field) but must NEVER invent or rewrite the message body. Typed text
must equal the selected message-bank entry or the exact user task text.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

# Contact / search fields are allowed to type names — not message bodies
_CONTACT_TYPE_MARKERS = (
    "type contact",
    "recipient",
    "search",
    "5550100",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def extract_quoted_message_text(instruction: str) -> Optional[str]:
    """Message body from explicit quotes only (message "…" / say "…")."""
    text = (instruction or "").strip()
    if not text:
        return None
    patterns = (
        # message "hello miss" to 3 new profiles / reply "hey" to 5 chats
        r"(?:message|reply|auto[- ]?message|send)\s+[\"']([^\"']+)[\"']\s+to\b",
        r"(?:and\s+)?(?:say|send|tell|text)\s*[:\-]?\s*[\"'](.+?)[\"']",
        # r45: '... first contact messages on facebook dating "hi miss …"'
        r"messages?\s+on\s+[\w ]+?\s+\"([^\"]{1,500})\"\s*$",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        body = _norm(m.group(1))
        if body and len(body) <= 2000:
            return body
    return None


def extract_user_message_text(instruction: str) -> Optional[str]:
    """Exact message body from the task instruction, if present.

    Patterns:
      … and say hi baby
      … say "hello there"
      … send: hello
      … tell her hi baby   → hi baby (strips her/him/them)
      … find and message X tell her Y
    """
    text = (instruction or "").strip()
    if not text:
        return None
    quoted = extract_quoted_message_text(text)
    if quoted:
        return quoted
    patterns = (
        # Prefer "say …" / "tell her …" — never match "send a message to …"
        r"(?:and\s+)?(?:say|tell(?:\s+(?:her|him|them))?)\s+(.+)$",
        # "send: hello" / "send hello" only when not "send a … message …"
        r"(?:and\s+)?send\s*[:\-]\s*(.+)$",
        r"(?:and\s+)?send\s+(?!a\s+(?:\w+\s+){0,3}message\b)(.+)$",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        body = _norm(m.group(1))
        # Strip leftover pronouns / instruction words from the body
        body = re.sub(
            r"^(?:her|him|them|that|to\s+her|to\s+him)\s+",
            "",
            body,
            flags=re.I,
        ).strip()
        body = re.sub(r"\s+(please|now|for me)\s*$", "", body, flags=re.I).strip()
        # Reject instruction-shaped captures ("a hinge message to Sam")
        low = body.lower()
        if "message to" in low or re.search(r"\bto\s+\d+\b", low):
            continue
        # r45: "send 5 first contact messages on yubo" is a job instruction,
        # not the message body (Yubo typed it verbatim, 24 Nov 01:49).
        if (
            re.match(r"^\d+\s", low)
            or "first contact" in low
            or re.search(r"\bmessages?\s+(?:on|to|in)\b", low)
        ):
            continue
        if body and len(body) <= 2000:
            return body
    return None


CORE_MESSAGE_BANK = ("hey how are you", "hi miss", "hello miss", "good morning")


def load_message_bank_texts(
    *,
    job: Optional[Dict[str, Any]] = None,
    bank_paths: Optional[Sequence[str]] = None,
) -> List[str]:
    """Collect verbatim texts from opener/message banks on the job or disk."""
    out: List[str] = []
    seen: Set[str] = set()

    def add(text: str) -> None:
        t = _norm(text)
        if not t:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(t)

    job = job or {}
    state = job.get("state") if isinstance(job.get("state"), dict) else {}

    # Job-level explicit allow-list / selected bank entry
    for key in (
        "message_text",
        "bank_text",
        "selected_message",
        "allowed_message_text",
    ):
        if job.get(key):
            add(str(job[key]))
        if state.get(key):
            add(str(state[key]))

    for key in ("message_bank", "allowed_messages", "bank_messages"):
        for blob in (job.get(key), state.get(key)):
            if isinstance(blob, list):
                for item in blob:
                    if isinstance(item, str):
                        add(item)
                    elif isinstance(item, dict) and item.get("text"):
                        add(str(item["text"]))

    # Dating opener library (templates = message bank)
    for lib in (
        job.get("opener_library"),
        state.get("opener_library"),
    ):
        if not isinstance(lib, dict):
            continue
        for tmpl in lib.get("templates") or []:
            if isinstance(tmpl, dict) and tmpl.get("text"):
                if tmpl.get("enabled", True):
                    add(str(tmpl["text"]))

    # Disk banks
    paths = list(bank_paths or [])
    env_path = (os.environ.get("MESSAGE_BANK_PATH") or "").strip()
    if env_path:
        paths.append(env_path)
    # Default dating openers config
    root = Path(__file__).resolve().parents[1]
    paths.append(str(root / "config" / "dating_openers.json"))

    for p in paths:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        templates = data.get("templates") if isinstance(data, dict) else None
        if isinstance(templates, list):
            for tmpl in templates:
                if isinstance(tmpl, dict) and tmpl.get("text"):
                    if tmpl.get("enabled", True):
                        add(str(tmpl["text"]))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict) and item.get("text"):
                    add(str(item["text"]))

    return out


def allowed_message_texts(
    instruction: str,
    *,
    job: Optional[Dict[str, Any]] = None,
    bank_paths: Optional[Sequence[str]] = None,
) -> List[str]:
    """User quoted task text is exclusive when present — bank lines rejected.

    Without a quoted/say user text, allow explicitly selected bank entry or
    full bank (caller still fails empty planner text via enforce).
    """
    allowed: List[str] = []
    # Quoted task text is exclusive — bank lines rejected (incident D)
    quoted = extract_quoted_message_text(instruction)
    if quoted:
        return [quoted]
    user = extract_user_message_text(instruction)
    job = job or {}
    # Explicitly chosen bank entry on the job
    for key in (
        "message_text",
        "bank_text",
        "selected_message",
        "allowed_message_text",
    ):
        if job.get(key):
            allowed.append(_norm(str(job[key])))
            return allowed
    if user:
        allowed.append(user)
    # r45: Mac's own first-contact bank is always allowed (the fixed Yubo /
    # Hily planners type these; the disk opener bank does not list them).
    for t in CORE_MESSAGE_BANK:
        if t.lower() not in {a.lower() for a in allowed}:
            allowed.append(t)
    for t in load_message_bank_texts(job=job, bank_paths=bank_paths):
        if t.lower() not in {a.lower() for a in allowed}:
            allowed.append(t)
    # E2E marker used by messaging harness (explicit fixture, not LLM)
    marker = "hello from macai uitree recovery test"
    if marker not in {a.lower() for a in allowed}:
        # Only include when the instruction is the MacAI SMS E2E goal
        low = (instruction or "").lower()
        if "macai" in low or "5550100" in low:
            allowed.append(marker)
    return allowed


def is_contact_or_search_type(
    action: Dict[str, Any], history: Optional[Iterable[str]] = None
) -> bool:
    """True when typing a contact/search query — not a message body."""
    reason = str(action.get("reason") or "").lower()
    if any(m in reason for m in _CONTACT_TYPE_MARKERS):
        return True
    text = _norm(str(action.get("text") or ""))
    # Pure phone / short token while searching
    if re.fullmatch(r"\+?\d[\d\s\-]{5,}", text):
        return True
    hist = " ".join(str(h) for h in (history or [])).lower()
    if "type contact" in hist and "type message" not in reason:
        # Still allow if reason clearly says message
        if "message" not in reason and "compose" not in reason:
            # Ambiguous — treat as contact only when reason says so
            pass
    return False


def enforce_message_text(
    action: Dict[str, Any],
    instruction: str,
    *,
    job: Optional[Dict[str, Any]] = None,
    history: Optional[Iterable[str]] = None,
    bank_paths: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Rewrite/reject type actions so body text is bank or user-provided only.

    - Contact/search typing: left unchanged
    - Message body: must match an allowed text exactly (case-sensitive prefer;
      falls back to case-insensitive match → canonical allowed string)
    - LLM-invented text is replaced with the user/bank text when uniquely known,
      else the type action is converted to fail
    """
    kind = str(action.get("action") or "").lower()
    if kind not in ("type", "type_text", "input_text"):
        return action

    if is_contact_or_search_type(action, history):
        action = dict(action)
        action["_text_source"] = "contact_or_search"
        return action

    user_text = extract_user_message_text(instruction)
    # Job-selected bank entry (explicit pick) beats generic disk banks
    selected: Optional[str] = None
    job = job or {}
    state = job.get("state") if isinstance(job.get("state"), dict) else {}
    for key in (
        "message_text",
        "bank_text",
        "selected_message",
        "allowed_message_text",
    ):
        for blob in (job.get(key), state.get(key)):
            if blob:
                selected = _norm(str(blob))
                break
        if selected:
            break

    allowed = allowed_message_texts(instruction, job=job, bank_paths=bank_paths)
    raw = str(action.get("text") or "")
    text = _norm(raw)

    # Non-messaging goals (e.g. type into Settings search) — no allow-list
    low_instr = (instruction or "").lower()
    messaging = any(
        k in low_instr
        for k in (
            "message",
            "msg",
            "whatsapp",
            "instagram",
            "messenger",
            "telegram",
            "tinder",
            "bumble",
            "hinge",
            "sms",
            "say ",
            "send ",
            "dm ",
            "macai",
        )
    )
    if not messaging:
        action = dict(action)
        action["_text_source"] = "non_messaging"
        return action

    if not allowed:
        # Messaging goal but no bank/user text — refuse LLM invention
        return {
            "action": "fail",
            "reason": (
                "Message text guard: no user/bank text available — "
                "refusing to type AI-generated copy"
            ),
            "planner": action.get("planner") or "message_text_guard",
            "llm_provider": None,
        }

    def _force(canonical: str, source: str) -> Dict[str, Any]:
        out = dict(action)
        out["text"] = canonical
        out["_text_source"] = source
        out["reason"] = (
            str(action.get("reason") or "")
            + f" [text forced to bank/user: {canonical[:40]}]"
        ).strip()
        return out

    # Exact match
    for a in allowed:
        if text == a:
            out = dict(action)
            out["text"] = a
            out["_text_source"] = "exact_allow"
            return out
    # Case-insensitive → canonical
    for a in allowed:
        if text.lower() == a.lower():
            out = dict(action)
            out["text"] = a
            out["_text_source"] = "casefold_allow"
            return out

    # User-typed task text is authoritative — never let AI rewrite it
    if user_text:
        return _force(user_text, "forced_user_or_bank")

    # Explicitly selected bank entry on the job
    if selected:
        return _force(selected, "forced_user_or_bank")

    # Never invent / default to an arbitrary bank entry. Text must be the
    # user's quoted instruction text or an explicitly selected bank entry.
    if not text:
        return {
            "action": "fail",
            "reason": (
                "Message text guard: no allowed message text — provide quoted "
                "instruction text or an explicitly selected bank entry "
                "(refusing bank_default fallback)"
            ),
            "planner": "message_text_guard",
            "llm_provider": None,
        }

    return {
        "action": "fail",
        "reason": (
            "Message text guard: typed text was not in the message bank / "
            f"user task (got {text[:60]!r})"
        ),
        "planner": "message_text_guard",
        "llm_provider": None,
        "_rejected_text": text[:200],
    }
