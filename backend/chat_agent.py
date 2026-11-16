"""AI chat agent: NL → device/dating/task actions with confirm for destructive ops."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from chat_store import append_message, ensure_session, list_messages
except ImportError:  # Lambda package layout
    from backend.chat_store import (  # type: ignore
        append_message,
        ensure_session,
        list_messages,
    )


DESTRUCTIVE_PATTERNS = (
    r"\b(delete|wipe|factory|uninstall|bulk\s*send|send\s+all|mass\s+message)\b",
    r"\b(start\s+dating|dating\s+mode)\b",
)


def _needs_confirm(text: str) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in DESTRUCTIVE_PATTERNS)


def _parse_intent(text: str) -> Tuple[str, Dict[str, Any]]:
    """Lightweight intent parser (works without LLM keys)."""
    t = text.strip()
    lower = t.lower()

    if re.search(r"\b(device\s+info|what\s+device|list\s+devices|status)\b", lower):
        return "device_info", {}

    m = re.search(r"\b(?:message\s+counts?|dating\s+stats|stats)\b", lower)
    if m:
        return "dating_stats", {}

    if re.search(r"\b(stop\s+dating|dating\s+stop)\b", lower):
        return "dating_stop", {}
    if re.search(r"\b(pause\s+dating|dating\s+pause)\b", lower):
        return "dating_pause", {}
    if re.search(r"\b(start\s+dating|dating\s+start|run\s+dating)\b", lower):
        dry = "dry" in lower
        return "dating_start", {"dry_run": dry}

    if re.search(r"\b(stop\s+task|cancel\s+task)\b", lower):
        return "task_stop", {}
    if re.search(r"\b(pause\s+task)\b", lower):
        return "task_pause", {}

    # "open Settings", "run: ...", "do: ..."
    m = re.match(r"^(?:run|do|open|please)\s*[:\-]?\s*(.+)$", t, re.I)
    if m:
        return "run_task", {"instruction": m.group(1).strip()}

    if len(t) > 8 and not lower.startswith(("what", "how", "why", "who", "explain")):
        # Heuristic: treat as a phone task unless clearly a question
        if "?" not in t:
            return "run_task", {"instruction": t}

    return "chat", {"question": t}


def _llm_reply(question: str, context: Dict[str, Any]) -> Optional[str]:
    """Optional OpenAI-compatible completion using configured provider."""
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    model = os.environ.get("LLM_MODEL", "")
    key_map = {
        "openai": "OPENAI_API_KEY",
        "xai": "XAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }
    api_key = os.environ.get(key_map.get(provider, ""), "") or os.environ.get(
        "GEMINI_API_KEY", ""
    )
    if not api_key:
        return None

    # Prefer OpenAI-compatible endpoints for openai/xai
    if provider in ("openai", "xai"):
        try:
            from openai import OpenAI

            base = (
                "https://api.x.ai/v1" if provider == "xai" else "https://api.openai.com/v1"
            )
            client = OpenAI(api_key=api_key, base_url=base)
            use_model = model or ("grok-4.7" if provider == "xai" else "gpt-4o-mini")
            resp = client.chat.completions.create(
                model=use_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Mobilerun assistant for a self-hosted phone "
                            "control center. Be concise. Context: "
                            + json.dumps(context)[:1500]
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                max_tokens=400,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            return f"(LLM unavailable: {e})"
    return None


async def handle_chat(
    *,
    message: str,
    session_id: Optional[str],
    device_id: Optional[str],
    target: str,
    confirmed: bool,
    context: Dict[str, Any],
    execute,
) -> Dict[str, Any]:
    """
    Process a chat turn.

    `execute` is an async callable(intent, params) -> dict result
    provided by the FastAPI layer (has access to devices/dating/tasks).
    """
    sid = ensure_session(session_id)
    append_message(sid, "user", message, {"target": target, "device_id": device_id})

    intent, params = _parse_intent(message)
    needs_confirm = _needs_confirm(message) and intent in {
        "dating_start",
        "run_task",
    }
    if needs_confirm and not confirmed:
        reply = (
            f"This looks like a bulk/dating action (`{intent}`). "
            "Confirm to proceed?"
        )
        append_message(
            sid,
            "assistant",
            reply,
            {"intent": intent, "params": params, "needs_confirm": True},
        )
        return {
            "session_id": sid,
            "reply": reply,
            "intent": intent,
            "params": params,
            "needs_confirm": True,
            "target": target,
            "history": list_messages(sid),
        }

    result: Dict[str, Any] = {}
    if intent == "chat":
        llm = _llm_reply(params.get("question", message), context)
        reply = llm or (
            "I can run phone tasks, start/stop dating mode, and report device/"
            "message stats. Try: `open Settings`, `start dating dry`, "
            "`device info`, or `dating stats`."
        )
    else:
        result = await execute(intent, {**params, "device_id": device_id})
        reply = result.get("message") or json.dumps(result, default=str)[:1200]

    append_message(
        sid,
        "assistant",
        reply,
        {"intent": intent, "params": params, "result": result, "target": target},
    )
    return {
        "session_id": sid,
        "reply": reply,
        "intent": intent,
        "params": params,
        "result": result,
        "needs_confirm": False,
        "target": target,
        "history": list_messages(sid),
    }
