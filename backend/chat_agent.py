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

    if re.search(r"\b(dating\s+stats|dating\s+message\s+counts?)\b", lower):
        return "dating_stats", {}
    if (
        re.search(r"\b(stats)\b", lower)
        and "social" not in lower
        and "unread" not in lower
    ):
        return "dating_stats", {}

    if re.search(r"\b(stop\s+dating|dating\s+stop)\b", lower):
        return "dating_stop", {}
    if re.search(r"\b(pause\s+dating|dating\s+pause)\b", lower):
        return "dating_pause", {}
    if re.search(r"\b(start\s+dating|dating\s+start|run\s+dating)\b", lower):
        dry = "dry" in lower
        return "dating_start", {"dry_run": dry}

    # Mode / speed: "use normal mode", "switch to dating", "speed careful"
    if re.search(r"\b(normal\s+mode|switch\s+to\s+normal|general\s+mode)\b", lower):
        return "set_mode", {"mode": "normal"}
    if re.search(r"\b(dating\s+mode|switch\s+to\s+dating)\b", lower):
        return "set_mode", {"mode": "dating"}
    if re.search(r"\b(social\s+mode|switch\s+to\s+social)\b", lower):
        return "set_mode", {"mode": "social"}
    if re.search(r"\b(needs\s+you|escalation\s+queue|review\s+queue)\b", lower):
        return "needs_you_list", {}
    if re.search(r"\b(unread|message\s+counts?)\b", lower) and "dating" not in lower:
        return "social_unreads", {}
    m = re.search(
        r"\b(?:speed|pacing|humanizer)\s*[:=]?\s*(fast|balanced|careful)\b", lower
    )
    if m:
        return "set_mode", {"speed_preset": m.group(1)}
    if re.search(r"\b(fast|balanced|careful)\s+speed\b", lower):
        m2 = re.search(r"\b(fast|balanced|careful)\b", lower)
        if m2:
            return "set_mode", {"speed_preset": m2.group(1)}

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
                "https://api.x.ai/v1"
                if provider == "xai"
                else "https://api.openai.com/v1"
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
            f"This looks like a bulk/dating action (`{intent}`). " "Confirm to proceed?"
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
        if (
            llm is None
            and not os.environ.get("GOOGLE_API_KEY")
            and not os.environ.get("GEMINI_API_KEY")
            and not os.environ.get("OPENAI_API_KEY")
        ):
            # Make missing LLM keys explicit for free-form questions
            reply = (
                "(No LLM API key configured on the server — task commands still work.) "
                + reply
            )
    else:
        result = await execute(intent, {**params, "device_id": device_id})
        reply = result.get("message") or json.dumps(result, default=str)[:1200]
        if result.get("error"):
            reply = f"Error: {result.get('error')}"

    def _jsonable(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _jsonable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_jsonable(v) for v in obj]
        if hasattr(obj, "isoformat"):
            try:
                return obj.isoformat()
            except Exception:
                return str(obj)
        return obj

    safe_result = _jsonable(result)
    meta = {
        "intent": intent,
        "params": params,
        "result": safe_result,
        "target": target,
        "answer": reply,
        "steps": safe_result.get("steps") if isinstance(safe_result, dict) else None,
        "task_id": (
            (safe_result.get("task_id") if isinstance(safe_result, dict) else None)
            or (
                (safe_result.get("task") or {}).get("task_id")
                if isinstance(safe_result, dict)
                else None
            )
        ),
        "device_id": (
            (safe_result.get("device_id") if isinstance(safe_result, dict) else None)
            or device_id
        ),
        "error": safe_result.get("error") if isinstance(safe_result, dict) else None,
    }
    append_message(sid, "assistant", reply, meta)
    return {
        "session_id": sid,
        "reply": reply,
        "intent": intent,
        "params": params,
        "result": result,
        "needs_confirm": False,
        "target": target,
        "task_id": meta.get("task_id"),
        "error": result.get("error"),
        "history": list_messages(sid),
    }
