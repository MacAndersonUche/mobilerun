"""Server-side phone agent step: UI tree → LLM → one action via WebSocket RPC.

Runs inside the step worker (not the 29s API Gateway Lambda). Checkpoints
progress on the Dynamo job so Tasks/Chat can poll.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mobilerun.cloud_agent")

SYSTEM_PROMPT = """You are MobileRun, controlling an Android phone via accessibility.
Given the goal and a compressed UI tree, pick ONE next action as JSON only:
{"action":"tap","x":123,"y":456,"reason":"..."}
{"action":"swipe","x1":100,"y1":800,"x2":100,"y2":200,"reason":"..."}
{"action":"type","text":"...","reason":"..."}
{"action":"back","reason":"..."}
{"action":"home","reason":"..."}
{"action":"open_app","app":"Settings","reason":"..."}
{"action":"done","reason":"goal achieved"}
{"action":"fail","reason":"cannot proceed: ..."}
Coordinates are screen pixels from node bounds centers. Prefer clickable nodes
matching the goal. Never invent coordinates outside the tree. Reply with JSON only.
"""

# Shown in Tasks/Chat UI when Gemini/OpenAI cannot plan.
LLM_UNAVAILABLE_LABEL = "LLM unavailable: quota"


def _llm_keys_present() -> bool:
    return bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )


def _key_presence() -> Dict[str, bool]:
    return {
        "gemini": bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        ),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "xai": bool(os.environ.get("XAI_API_KEY")),
    }


def _compress_tree(tree: str, limit: int = 12000) -> str:
    if not tree:
        return "(empty UI tree — accessibility may be off)"
    # Drop deeply nested whitespace
    compact = re.sub(r"[ \t]+", " ", tree)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "\n...[truncated]"


def _gemini_models() -> List[str]:
    """Stable Gemini flash IDs first; env LLM_MODEL included but not exclusively."""
    preferred = (os.environ.get("LLM_MODEL") or "").strip()
    # Prefer versioned IDs — aliases like gemini-flash-latest often 503 under load
    defaults = [
        "gemini-2.0-flash-001",
        "gemini-1.5-flash-002",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-flash-latest",
    ]
    out: List[str] = []
    for m in defaults:
        if m not in out:
            out.append(m)
    if preferred and preferred.lower().startswith("gemini") and preferred not in out:
        # Try preferred last so a flaky alias does not block stable IDs
        out.append(preferred)
    return out


def _call_gemini(user_prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("No Gemini/Google API key configured on the backend")
    body = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512},
    }
    last_err: Optional[Exception] = None
    for model in _gemini_models():
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:300]
            last_err = RuntimeError(f"Gemini {model} HTTP {e.code}: {err_body}")
            # Quota / rate-limit is account-wide — stop immediately so OpenAI can run
            if e.code == 429 or (e.code == 503 and "high demand" in err_body.lower()):
                logger.warning(
                    "Gemini model %s failed (%s); skipping remaining Gemini models",
                    model,
                    e.code,
                )
                break
            # Missing / bad request → try next model
            if e.code in (404, 400, 503):
                logger.warning(
                    "Gemini model %s failed (%s); trying next", model, e.code
                )
                continue
            raise last_err from e
        except Exception as e:
            last_err = e
            logger.warning("Gemini model %s error: %s; trying next", model, e)
            continue
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get(
            "parts"
        ) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text.strip():
            last_err = RuntimeError(f"Empty LLM response from {model}: {data}")
            continue
        return text
    raise RuntimeError(f"All Gemini models failed: {last_err}")


def _openai_model() -> str:
    """Use LLM_MODEL only when it looks like an OpenAI chat model."""
    preferred = (os.environ.get("LLM_MODEL") or "").strip()
    if preferred and not preferred.lower().startswith(("gemini", "claude", "grok")):
        return preferred
    return "gpt-4o-mini"


def _call_openai(user_prompt: str) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("No OpenAI API key")
    model = _openai_model()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def probe_llm_providers() -> Dict[str, Any]:
    """Real HTTP probes for Gemini/OpenAI. Never returns secret values."""
    out: Dict[str, Any] = {
        "keys_present": _key_presence(),
        "gemini": None,
        "openai": None,
    }
    prompt = 'Reply with JSON only: {"action":"done","reason":"probe"}'

    # Probe OpenAI first (fast, and preferred when Gemini is quota'd)
    if out["keys_present"]["openai"]:
        try:
            text = _call_openai(prompt)
            out["openai"] = {
                "ok": True,
                "http_status": 200,
                "model": _openai_model(),
                "preview": (text or "")[:80],
            }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:300]
            out["openai"] = {
                "ok": False,
                "http_status": e.code,
                "model": _openai_model(),
                "error": f"OpenAI HTTP {e.code}: {err_body}",
            }
        except Exception as e:
            out["openai"] = {
                "ok": False,
                "http_status": None,
                "model": _openai_model(),
                "error": str(e)[:400],
            }
    else:
        out["openai"] = {
            "ok": False,
            "http_status": None,
            "error": "OPENAI_API_KEY not set (empty) on Lambda",
        }

    if out["keys_present"]["gemini"]:
        try:
            text = _call_gemini(SYSTEM_PROMPT + "\n\n" + prompt)
            out["gemini"] = {
                "ok": True,
                "http_status": 200,
                "preview": (text or "")[:80],
            }
        except Exception as e:
            msg = str(e)
            code_m = re.search(r"HTTP (\d{3})", msg)
            out["gemini"] = {
                "ok": False,
                "http_status": int(code_m.group(1)) if code_m else None,
                "error": msg[:400],
            }
    else:
        out["gemini"] = {
            "ok": False,
            "http_status": None,
            "error": "GEMINI_API_KEY / GOOGLE_API_KEY not set on Lambda",
        }

    out["any_ok"] = bool(
        (out["gemini"] or {}).get("ok") or (out["openai"] or {}).get("ok")
    )
    return out


def plan_next_action(
    instruction: str,
    ui_tree: str,
    history: List[str],
) -> Dict[str, Any]:
    """Plan one action. Multi-step goals require a real LLM (Gemini or OpenAI).

    A non-LLM heuristic may only emit open_app for trivial \"open X\" intents,
    and is always labelled LLM unavailable: quota. It must never complete
    multi-step verification tasks.
    """
    hist = "\n".join(history[-8:]) or "(none)"
    user = (
        f"GOAL: {instruction}\n\n"
        f"RECENT ACTIONS:\n{hist}\n\n"
        f"UI TREE:\n{_compress_tree(ui_tree)}\n\n"
        "JSON action:"
    )
    raw = None
    errors: List[str] = []
    provider_used: Optional[str] = None
    # Prefer OpenAI first when LLM_PROVIDER=openai, or when Gemini is known-unusable
    # via prior 429 (caller still falls through). Default: Gemini then OpenAI.
    prefer_openai = (
        os.environ.get("LLM_PROVIDER") or ""
    ).strip().lower() == "openai" or (
        os.environ.get("PREFER_OPENAI") or ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    providers: List[str] = []
    if prefer_openai and os.environ.get("OPENAI_API_KEY"):
        providers.append("openai")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        providers.append("gemini")
    if "openai" not in providers and os.environ.get("OPENAI_API_KEY"):
        providers.append("openai")

    for prov in providers:
        if raw is not None:
            break
        try:
            if prov == "gemini":
                raw = _call_gemini(SYSTEM_PROMPT + "\n\n" + user)
                provider_used = "gemini"
            else:
                raw = _call_openai(user)
                provider_used = "openai"
        except Exception as e:
            errors.append(f"{prov}: {e}")
            logger.warning("%s failed, trying next provider: %s", prov, e)
            # On Gemini quota, immediately continue to OpenAI (already next in list)
            continue
    if raw is None:
        detail = "; ".join(errors) or "no keys"
        # Trivial open-app only — never multi-step navigation/toggles
        heur = _heuristic_open_app_only(instruction, history)
        if heur:
            logger.warning(
                "Using open-app heuristic (%s); LLM errors: %s",
                LLM_UNAVAILABLE_LABEL,
                detail,
            )
            heur["planner"] = "heuristic"
            heur["llm_provider"] = None
            # Force UI-visible label
            reason = str(heur.get("reason") or "")
            if LLM_UNAVAILABLE_LABEL not in reason:
                heur["reason"] = f"{LLM_UNAVAILABLE_LABEL} — {reason}".strip(" —")
            return heur
        raise RuntimeError(
            f"{LLM_UNAVAILABLE_LABEL} — No working LLM on backend "
            f"(need GEMINI_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY). "
            f"Last errors: {detail}"
        )
    action = _parse_action_json(raw)
    action["planner"] = "llm"
    action["llm_provider"] = provider_used
    return action


def _heuristic_open_app_only(
    instruction: str, history: List[str]
) -> Optional[Dict[str, Any]]:
    """Only handle trivial intents like 'open Settings' / 'open app Chrome'.

    Multi-step goals (navigate, toggle, type, Display, dark theme, …) return None
    so the caller fails with an explicit LLM-unavailable error.
    """
    text = (instruction or "").strip()
    if not text:
        return None
    # Reject anything that looks multi-step
    low = text.lower()
    multi_markers = (
        " and ",
        " then ",
        ",",
        "go to",
        "goto",
        "navigate",
        "turn on",
        "turn off",
        "enable",
        "disable",
        "tap",
        "type ",
        "enter ",
        "swipe",
        "scroll",
        "dark",
        "display",
        "wifi",
        "settings,",
    )
    # Allow "open Settings" but not "open Settings and …"
    if any(m in low for m in multi_markers if m != "settings,"):
        # "open Settings" alone is ok — check via regex below
        if re.search(
            r"\b(and|then|go to|turn on|turn off|enable|disable|tap|type|swipe)\b",
            low,
        ):
            return None
        if "," in text:
            return None

    m = re.match(
        r"^\s*(?:please\s+)?(?:open(?:\s+app)?|launch|start)\s+(.+?)\s*$",
        text,
        re.I,
    )
    if not m:
        return None
    app = m.group(1).strip().strip("\"'")
    # Strip trailing filler
    app = re.sub(r"\s+(please|now|for me)\s*$", "", app, flags=re.I).strip()
    if not app or len(app) > 40:
        return None
    # Already opened?
    hist_blob = " ".join(history).lower()
    if f"open_app({app.lower()})" in hist_blob or f"open_app({app})" in hist_blob:
        return {
            "action": "done",
            "reason": f"{LLM_UNAVAILABLE_LABEL} — already opened {app}",
        }
    return {
        "action": "open_app",
        "app": app,
        "reason": f"{LLM_UNAVAILABLE_LABEL} — open_app({app})",
    }


# Back-compat alias used by older tests / imports
def _heuristic_action(
    instruction: str, ui_tree: str, history: List[str]
) -> Optional[Dict[str, Any]]:
    return _heuristic_open_app_only(instruction, history)


def _parse_action_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Find first {...}
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise RuntimeError(f"LLM did not return JSON: {raw[:200]}")
    return json.loads(m.group(0))


def execute_action(device_id: str, action: Dict[str, Any]) -> str:
    try:
        from device_rpc import call_device
    except ImportError:
        from backend.device_rpc import call_device  # type: ignore

    kind = str(action.get("action") or "").lower()
    if kind == "tap":
        call_device(
            device_id,
            "tap",
            {"x": int(action["x"]), "y": int(action["y"])},
        )
        return f"tap({action.get('x')},{action.get('y')})"
    if kind == "swipe":
        call_device(
            device_id,
            "swipe",
            {
                "x1": int(action["x1"]),
                "y1": int(action["y1"]),
                "x2": int(action["x2"]),
                "y2": int(action["y2"]),
                "duration_ms": int(action.get("duration_ms") or 300),
            },
        )
        return f"swipe({action.get('x1')},{action.get('y1')}->{action.get('x2')},{action.get('y2')})"
    if kind in ("type", "type_text", "input_text"):
        call_device(
            device_id,
            "input_text",
            {"text": str(action.get("text") or ""), "clear": bool(action.get("clear"))},
        )
        return f"type({action.get('text')!r})"
    if kind == "back":
        call_device(device_id, "press_button", {"button": "back"})
        return "back"
    if kind == "home":
        call_device(device_id, "press_button", {"button": "home"})
        return "home"
    if kind in ("open_app", "start_app"):
        app = str(action.get("app") or action.get("package") or "")
        call_device(
            device_id, "open_app", {"app": app, "package": action.get("package")}
        )
        return f"open_app({app})"
    if kind == "done":
        return "done"
    if kind == "fail":
        raise RuntimeError(str(action.get("reason") or "agent failed"))
    raise RuntimeError(f"Unknown action: {kind}")


def run_one_agent_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """Advance an agent job by one LLM+action step. Mutates and returns job."""
    try:
        from device_rpc import call_device
    except ImportError:
        from backend.device_rpc import call_device  # type: ignore
    try:
        from device_push import push_to_device, device_is_reachable
    except ImportError:
        from backend.device_push import push_to_device, device_is_reachable  # type: ignore

    state = job.setdefault("state", {})
    device_id = str(job.get("device_id") or "")
    instruction = str(job.get("instruction") or "")
    step = int(state.get("steps") or 0)
    max_steps = int(job.get("max_steps") or 15)
    history: List[str] = list(state.get("history") or [])

    if not device_id:
        job["status"] = "failed"
        job["error"] = "No device_id on job"
        return job
    if not instruction:
        job["status"] = "failed"
        job["error"] = "No instruction on job"
        return job
    if not device_is_reachable(device_id):
        job["status"] = "failed"
        job["error"] = "Device offline — no live WebSocket"
        state["last_action"] = "device_offline"
        job["state"] = state
        return job
    if not _llm_keys_present():
        job["status"] = "failed"
        job["error"] = (
            f"{LLM_UNAVAILABLE_LABEL} — No LLM API key configured on the AWS backend"
        )
        state["last_action"] = "no_llm_key"
        state["planner"] = None
        job["state"] = state
        return job
    if step >= max_steps:
        job["status"] = "completed"
        job["result"] = state.get("last_action") or f"Reached max_steps={max_steps}"
        return job

    # Notify UI / phone that cloud agent is driving
    push_to_device(
        device_id,
        {
            "type": "agent_control",
            "action": "cloud_step",
            "task_id": job.get("job_id"),
            "step": step + 1,
            "instruction": instruction,
        },
    )

    try:
        ui_tree = call_device(device_id, "get_ui_tree", {}, timeout_s=20) or ""
        if not isinstance(ui_tree, str):
            ui_tree = json.dumps(ui_tree)
        action = plan_next_action(instruction, ui_tree, history)
        kind = str(action.get("action") or "").lower()
        reason = str(action.get("reason") or "")
        planner = action.get("planner") or "llm"
        llm_provider = action.get("llm_provider")
        state["planner"] = planner
        if llm_provider:
            state["llm_provider"] = llm_provider
        if kind == "done":
            state["steps"] = step + 1
            state["last_action"] = f"done: {reason}"
            history.append(f"done: {reason}")
            state["history"] = history
            job["state"] = state
            job["status"] = "completed"
            job["result"] = reason or "Goal completed"
            return job
        if kind == "fail":
            state["steps"] = step + 1
            state["last_action"] = f"fail: {reason}"
            history.append(f"fail: {reason}")
            state["history"] = history
            job["state"] = state
            job["status"] = "failed"
            job["error"] = reason or "Agent could not complete the goal"
            return job

        summary = execute_action(device_id, action)
        state["steps"] = step + 1
        state["last_action"] = summary
        state["last_reason"] = reason
        history.append(f"{summary} — {reason}".strip(" —"))
        state["history"] = history
        job["state"] = state
        # Surface heuristic label in the result line for Tasks UI
        if planner == "heuristic":
            job["result"] = f"Step {step + 1}: {summary} ({LLM_UNAVAILABLE_LABEL})"
        else:
            job["result"] = f"Step {step + 1}: {summary}"
        # Schedule next tick soon (EventBridge also picks up due jobs)
        import time

        job["next_run_at"] = int(time.time()) + 2
        job["updated_at"] = int(time.time())
        # Immediate follow-up invoke for snappier UX when STEP_WORKER_ARN set
        _kick_self(job.get("job_id"))
        return job
    except Exception as e:
        logger.exception("agent step failed job=%s", job.get("job_id"))
        state["last_action"] = f"error: {e}"
        history.append(f"error: {e}")
        state["history"] = history
        job["state"] = state
        # Soft fail a single step (retry) unless hard errors
        msg = str(e)
        low = msg.lower()
        hard = any(
            t in low
            for t in (
                "no llm",
                "no working llm",
                "llm unavailable",
                "offline",
                "api key",
                "failed to push",
            )
        )
        rate_limited = any(t in low for t in ("429", "503", "quota", "high demand"))
        if hard or step + 1 >= max_steps:
            job["status"] = "failed"
            # Ensure Tasks UI shows the standard label
            if LLM_UNAVAILABLE_LABEL.lower() in low or "no working llm" in low:
                if LLM_UNAVAILABLE_LABEL not in msg:
                    job["error"] = f"{LLM_UNAVAILABLE_LABEL} — {msg}"
                else:
                    job["error"] = msg
            else:
                job["error"] = msg
        else:
            import time

            # Rate limits: wait longer and do not burn a step slot
            if rate_limited:
                job["next_run_at"] = int(time.time()) + 20
                job["error"] = f"{LLM_UNAVAILABLE_LABEL} — {msg}"
            else:
                state["steps"] = step + 1
                job["next_run_at"] = int(time.time()) + 5
                job["error"] = msg
            job["updated_at"] = int(time.time())
            _kick_self(job.get("job_id"))
        return job


def _kick_self(job_id: Optional[str]) -> None:
    if not job_id:
        return
    arn = os.environ.get("STEP_WORKER_ARN")
    if not arn or os.environ.get("USE_AWS_STORAGE", "").lower() != "true":
        return
    try:
        import boto3

        boto3.client("lambda").invoke(
            FunctionName=arn,
            InvocationType="Event",
            Payload=json.dumps({"job_id": job_id}).encode(),
        )
    except Exception as e:
        logger.warning("kick step worker failed: %s", e)
