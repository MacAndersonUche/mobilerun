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
Given the goal and a compressed UI tree (and optional screenshot), pick ONE next action as JSON only:
{"action":"tap","x":123,"y":456,"reason":"..."}
{"action":"swipe","x1":100,"y1":800,"x2":100,"y2":200,"reason":"..."}
{"action":"type","text":"...","reason":"..."}
{"action":"back","reason":"..."}
{"action":"home","reason":"..."}
{"action":"open_app","app":"Settings","reason":"..."}
{"action":"done","reason":"goal achieved"}
{"action":"fail","reason":"cannot proceed: ..."}
Rules:
- To launch an app (Settings, WhatsApp, Chrome, Messages, …) ALWAYS use open_app with
  the app label — never hunt launcher icons or swipe the home screen.
- NEVER call open_app again once RECENT ACTIONS already show Opened X / open_ok, or
  the UI tree package already matches the target. Move on (search, tap, type, send).
- Prefer clickable/text nodes with center=(x,y) from the tree. Never invent coordinates.
- If the tree is empty/thin but a screenshot is provided, estimate taps from the image
  or use open_app / fail.
- Do NOT repeat the same swipe. If stuck, use open_app (once), back, or fail.
- Reply with JSON only.
"""

# Wall-clock timeout for a cloud agent job (seconds)
TASK_TIMEOUT_S = int(os.environ.get("AGENT_TASK_TIMEOUT_S") or "300")
# Max identical swipe summaries before hard-fail
MAX_SWIPE_LOOPS = 2

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


def _call_openai(user_prompt: str, image_b64: Optional[str] = None) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("No OpenAI API key")
    model = _openai_model()
    if image_b64:
        # Vision path for thin/empty a11y trees on Samsung One UI
        user_content: Any = [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                    "detail": "low",
                },
            },
        ]
        # Prefer a vision-capable mini model
        if model == "gpt-4o-mini" or "gpt-4o" in model:
            pass
        else:
            model = "gpt-4o-mini"
    else:
        user_content = user_prompt
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
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
    with urllib.request.urlopen(req, timeout=50) as resp:
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

    # Skip Gemini probe when OpenAI already works — avoids HTTP API 29s timeout
    # while Gemini is quota'd / high-demand (each model attempt can take seconds).
    skip_gemini = bool((out.get("openai") or {}).get("ok")) and (
        (os.environ.get("PREFER_OPENAI") or "").strip().lower() in ("1", "true", "yes")
        or (os.environ.get("LLM_PROVIDER") or "").strip().lower() == "openai"
    )
    if skip_gemini:
        out["gemini"] = {
            "ok": False,
            "http_status": None,
            "skipped": True,
            "error": "skipped — OpenAI probe ok (PREFER_OPENAI)",
        }
    elif out["keys_present"]["gemini"]:
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


def _trivial_open_app_target(instruction: str) -> Optional[str]:
    """If instruction is essentially 'open X', return X; else None."""
    text = (instruction or "").strip()
    m = re.match(
        r"^\s*(?:please\s+)?(?:open(?:\s+app)?|launch|start)\s+(.+?)\s*$",
        text,
        re.I,
    )
    if not m:
        return None
    app = m.group(1).strip().strip("\"'")
    app = re.sub(r"\s+(please|now|for me)\s*$", "", app, flags=re.I).strip()
    if not app or len(app) > 40:
        return None
    if re.search(
        r"\b(and|then|go to|turn on|turn off|enable|disable|tap|type|swipe)\b",
        app,
        re.I,
    ):
        return None
    if "," in app:
        return None
    return app


def _history_shows_app_opened(hist_blob: str, app: str) -> bool:
    """True if prior steps already launched ``app`` successfully."""
    if not hist_blob:
        return False
    low = (app or "").lower().strip()
    if not low:
        return "open_ok" in hist_blob or "opened " in hist_blob
    tokens = {low, low.replace(" ", "")}
    if "setting" in low:
        tokens.update({"settings", "com.android.settings"})
    if "whatsapp" in low or low == "wa":
        tokens.update({"whatsapp", "com.whatsapp"})
    if "chrome" in low:
        tokens.update({"chrome", "com.android.chrome"})
    if "message" in low or "sms" in low:
        tokens.update({"messaging", "com.google.android.apps.messaging"})
    if f"open_app({low})" in hist_blob:
        return True
    if f"opened {low}" in hist_blob:
        return True
    if "open_ok" in hist_blob and any(t in hist_blob for t in tokens):
        return True
    if re.search(
        rf"opened\s+\w+\[([a-z0-9._]*{re.escape(low)}[a-z0-9._]*)\]", hist_blob
    ):
        return True
    if hist_blob.count(f"opened {low}") >= 1 or hist_blob.count("open_ok") >= 1:
        if any(t in hist_blob for t in tokens):
            return True
    return False


def _count_recent_open_apps(history: List[str]) -> int:
    n = 0
    for h in reversed(history):
        hs = str(h).lower()
        if hs.startswith("open_app(") or hs.startswith("opened "):
            n += 1
        else:
            break
    return n


def plan_next_action(
    instruction: str,
    ui_tree: str,
    history: List[str],
    image_b64: Optional[str] = None,
) -> Dict[str, Any]:
    """Plan one action. Multi-step goals require a real LLM (Gemini or OpenAI).

    A non-LLM heuristic may only emit open_app for trivial \"open X\" intents,
    and is always labelled LLM unavailable: quota. It must never complete
    multi-step verification tasks.
    """
    open_target = _trivial_open_app_target(instruction)
    hist_blob = " ".join(history).lower()
    hist = "\n".join(history[-8:]) or "(none)"
    tree_note = ""
    if not ui_tree or 'empty="true"' in ui_tree or len(ui_tree) < 80:
        tree_note = (
            "\nNOTE: UI tree is empty/thin (common on Samsung One UI). "
            "Prefer open_app for launching apps. "
            + ("A screenshot is attached.\n" if image_b64 else "No screenshot.\n")
        )
    open_hint = ""
    already_opened = _history_shows_app_opened(hist_blob, open_target or "")
    if open_target and not already_opened:
        open_hint = (
            f"\nHINT: This goal is a simple app launch — use "
            f'{{"action":"open_app","app":"{open_target}"}} immediately '
            f"(PackageManager). Do not swipe the launcher.\n"
        )
    elif already_opened:
        open_hint = (
            "\nHINT: The target app is already open (see RECENT ACTIONS). "
            "Do NOT call open_app again — continue with the next sub-goal "
            "(search, tap contact, type, send).\n"
        )
    user = (
        f"GOAL: {instruction}\n\n"
        f"RECENT ACTIONS:\n{hist}\n\n"
        f"{tree_note}{open_hint}"
        f"UI TREE:\n{_compress_tree(ui_tree)}\n\n"
        "JSON action:"
    )
    raw = None
    errors: List[str] = []
    provider_used: Optional[str] = None
    prefer_openai = (
        (os.environ.get("LLM_PROVIDER") or "").strip().lower() == "openai"
        or (os.environ.get("PREFER_OPENAI") or "").strip().lower()
        in ("1", "true", "yes")
        or bool(image_b64)
    )
    providers: List[str] = []
    if prefer_openai and os.environ.get("OPENAI_API_KEY"):
        providers.append("openai")
    if not image_b64 and (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ):
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
                raw = _call_openai(user, image_b64=image_b64)
                provider_used = "openai"
        except Exception as e:
            errors.append(f"{prov}: {e}")
            logger.warning("%s failed, trying next provider: %s", prov, e)
            continue
    if raw is None:
        detail = "; ".join(errors) or "no keys"
        heur = _heuristic_open_app_only(instruction, history)
        if heur:
            logger.warning(
                "Using open-app heuristic (%s); LLM errors: %s",
                LLM_UNAVAILABLE_LABEL,
                detail,
            )
            heur["planner"] = "heuristic"
            heur["llm_provider"] = None
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
    if _history_shows_app_opened(hist_blob, app):
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


def _normalize_tree_payload(raw: Any) -> Dict[str, Any]:
    """APK may return a plain string or {tree, package, empty, chars}."""
    if isinstance(raw, dict):
        tree = raw.get("tree") or raw.get("result") or ""
        if not isinstance(tree, str):
            tree = json.dumps(tree)
        return {
            "tree": tree,
            "package": str(raw.get("package") or ""),
            "empty": bool(raw.get("empty") or 'empty="true"' in tree or len(tree) < 80),
            "chars": int(raw.get("chars") or len(tree)),
        }
    tree = raw if isinstance(raw, str) else (json.dumps(raw) if raw else "")
    return {
        "tree": tree,
        "package": "",
        "empty": (not tree) or 'empty="true"' in tree or len(tree) < 80,
        "chars": len(tree),
    }


def _fetch_screenshot_b64(device_id: str) -> Optional[str]:
    try:
        from device_rpc import call_device
    except ImportError:
        from backend.device_rpc import call_device  # type: ignore

    try:
        raw = call_device(device_id, "screenshot", {}, timeout_s=15)
    except Exception as e:
        logger.warning("screenshot rpc failed: %s", e)
        return None
    if isinstance(raw, dict):
        if raw.get("ok") and raw.get("data"):
            return str(raw["data"])
        return None
    if isinstance(raw, str) and len(raw) > 100:
        return raw
    return None


def _store_step_screenshot(job_id: str, step_n: int, b64: str) -> Optional[str]:
    """Upload JPEG to S3; return s3 key or None."""
    bucket = os.environ.get("SCREENSHOT_BUCKET") or ""
    if not bucket or not b64:
        return None
    try:
        import base64
        import boto3

        key = f"tasks/{job_id}/step_{step_n}.jpg"
        body = base64.b64decode(b64)
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="image/jpeg",
        )
        return key
    except Exception as e:
        logger.warning("screenshot s3 upload failed: %s", e)
        return None


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
        label = str(
            action.get("label")
            or action.get("text")
            or action.get("element")
            or action.get("target")
            or ""
        ).strip()
        if label:
            return f'Tapped "{label[:60]}"'
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
        return "Swiped"
    if kind in ("type", "type_text", "input_text"):
        text = str(action.get("text") or "")
        call_device(
            device_id,
            "input_text",
            {"text": text, "clear": bool(action.get("clear"))},
        )
        preview = text[:48]
        return f'Typed "{preview}"' if preview else "Typed text"
    if kind == "back":
        call_device(device_id, "press_button", {"button": "back"})
        return "Went back"
    if kind == "home":
        call_device(device_id, "press_button", {"button": "home"})
        return "Went home"
    if kind in ("open_app", "start_app"):
        app = str(action.get("app") or action.get("package") or "")
        raw = call_device(
            device_id,
            "open_app",
            {"app": app, "package": action.get("package")},
            timeout_s=20,
            wait_reconnect_s=60,
        )
        pkg = ""
        if isinstance(raw, dict):
            pkg = str(raw.get("package") or raw.get("active_package") or "")
            if raw.get("ok") is False:
                raise RuntimeError(str(raw.get("error") or f"open_app failed: {app}"))
            # Stash for completion checks
            action["_rpc_package"] = pkg
            action["_rpc_ok"] = bool(raw.get("ok") or raw.get("launched") or pkg)
        # Human-readable primary; keep [package] for rpc_ok / history matching
        nice = app or pkg or "app"
        if nice.startswith("com.") or nice.startswith("ai."):
            nice = nice.split(".")[-1]
        nice = nice[:1].upper() + nice[1:] if nice else "app"
        if pkg:
            return f"Opened {nice}[{pkg}]"
        return f"Opened {nice}"
    if kind == "done":
        return "Finished"
    if kind == "fail":
        raise RuntimeError(str(action.get("reason") or "agent failed"))
    raise RuntimeError(f"Unknown action: {kind}")


def _count_recent_swipes(history: List[str]) -> int:
    n = 0
    for h in reversed(history):
        hs = str(h)
        if hs.startswith("swipe(") or hs.startswith("Swiped"):
            n += 1
        else:
            break
    return n


def run_one_agent_step(job: Dict[str, Any]) -> Dict[str, Any]:
    """Advance an agent job by one LLM+action step. Mutates and returns job."""
    import time

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
    steps_detail: List[Dict[str, Any]] = list(state.get("steps_detail") or [])
    now = int(time.time())
    created = int(job.get("created_at") or now)

    if not device_id:
        job["status"] = "failed"
        job["error"] = "No device_id on job"
        return job
    if not instruction:
        job["status"] = "failed"
        job["error"] = "No instruction on job"
        return job
    # Stale running tasks time out
    if now - created > TASK_TIMEOUT_S:
        job["status"] = "failed"
        job["error"] = f"Task timed out after {TASK_TIMEOUT_S}s"
        state["last_action"] = "timeout"
        job["state"] = state
        job["completed_at"] = now
        return job
    if not device_is_reachable(device_id):
        # Brief wait — phone often reconnects within seconds mid-task
        try:
            from device_push import wait_until_reachable
        except ImportError:
            from backend.device_push import wait_until_reachable  # type: ignore

        if not wait_until_reachable(device_id, timeout_s=45.0):
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
        job["completed_at"] = now
        return job
    if _count_recent_swipes(history) >= MAX_SWIPE_LOOPS:
        job["status"] = "failed"
        job["error"] = (
            "Stopped swipe loop — use open_app for launching apps "
            "(PackageManager), not launcher swipes"
        )
        state["last_action"] = "swipe_loop"
        job["state"] = state
        job["completed_at"] = now
        return job
    if _count_recent_open_apps(history) >= 2:
        # Planner kept re-opening; force it to continue with UI actions
        logger.warning(
            "open_app loop detected job=%s — injecting continue hint via history",
            job.get("job_id"),
        )

    push_to_device(
        device_id,
        {
            "type": "agent_control",
            "action": "cloud_step",
            "task_id": job.get("job_id"),
            "step": step + 1,
            "instruction": instruction,
        },
        wait_reconnect_s=30.0,
    )

    try:
        try:
            tree_raw = (
                call_device(
                    device_id,
                    "get_ui_tree",
                    {},
                    timeout_s=10,
                    wait_reconnect_s=45,
                )
                or ""
            )
        except Exception as tree_err:
            # Overloaded OEM/emulator a11y can hang; still allow open_app.
            # Also soft-fail offline briefly — reconnect wait already ran.
            low = str(tree_err).lower()
            if any(
                t in low
                for t in (
                    "timed out",
                    "timeout",
                    "accessibility",
                    "offline",
                    "failed to push",
                )
            ):
                logger.warning("get_ui_tree failed, using empty tree: %s", tree_err)
                reason_attr = (
                    str(tree_err)[:80]
                    .replace("&", "&amp;")
                    .replace('"', "&quot;")
                    .replace("<", "&lt;")
                )
                tree_raw = {
                    "tree": (
                        '<hierarchy windows="0" nodes="0" empty="true" '
                        f'reason="{reason_attr}"/>'
                    ),
                    "empty": True,
                    "chars": 0,
                    "package": "",
                }
            else:
                raise
        tree_info = _normalize_tree_payload(tree_raw)
        ui_tree = tree_info["tree"]
        image_b64 = None
        # Skip screenshot when tree is healthy — cuts ~5-10s per step
        try:
            if tree_info["empty"]:
                image_b64 = _fetch_screenshot_b64(device_id)
        except Exception as shot_err:
            logger.warning("screenshot skipped: %s", shot_err)
            image_b64 = None
        use_vision = bool(image_b64) and tree_info["empty"]

        action = plan_next_action(
            instruction,
            ui_tree,
            history,
            image_b64=image_b64 if use_vision else None,
        )
        kind = str(action.get("action") or "").lower()
        reason = str(action.get("reason") or "")
        planner = action.get("planner") or "llm"
        llm_provider = action.get("llm_provider")
        state["planner"] = planner
        if llm_provider:
            state["llm_provider"] = llm_provider

        # Do not re-open once open_ok / Opened already in history or FG matches
        if kind in ("open_app", "start_app"):
            app_name = str(action.get("app") or action.get("package") or "")
            hist_blob = " ".join(history).lower()
            fg = (tree_info.get("package") or "").lower()
            app_l = app_name.lower()
            fg_matches = bool(fg) and (
                app_l.replace(" ", "") in fg.replace(".", "")
                or ("whatsapp" in app_l and "whatsapp" in fg)
                or ("setting" in app_l and "settings" in fg)
                or ("message" in app_l and "messaging" in fg)
            )
            if fg_matches or _history_shows_app_opened(hist_blob, app_name):
                logger.info(
                    "skipping repeat open_app(%s) — already open (fg=%s)",
                    app_name,
                    fg,
                )
                # Re-plan with stronger continue hint
                history_hint = list(history) + [
                    f"Opened {app_name}[already] — continue next sub-goal"
                ]
                action = plan_next_action(
                    instruction,
                    ui_tree,
                    history_hint,
                    image_b64=image_b64 if use_vision else None,
                )
                kind = str(action.get("action") or "").lower()
                reason = str(action.get("reason") or reason)
                if kind in ("open_app", "start_app"):
                    # Force progress: ask LLM-equivalent done-or-tap via fail soft
                    kind = "done" if _trivial_open_app_target(instruction) else "fail"
                    if kind == "done":
                        reason = f"App already open ({fg or app_name})"
                        action = {"action": "done", "reason": reason}
                    else:
                        reason = (
                            "App already open — planner must tap/type/send next; "
                            "refusing another open_app"
                        )
                        action = {"action": "fail", "reason": reason}

        # Block swipe when tree empty — force open_app or fail
        if kind == "swipe" and tree_info["empty"]:
            kind = "fail"
            reason = (
                "UI tree empty — refusing swipe. "
                "Re-enable Accessibility or use open_app."
            )
            action = {"action": "fail", "reason": reason}

        def _record_step(
            summary: str,
            *,
            ok: bool = True,
            screenshot_key: Optional[str] = None,
            verify: Optional[str] = None,
        ) -> None:
            entry = {
                "n": step + 1,
                "action": summary,
                "reason": reason,
                "ok": ok,
                "package": tree_info.get("package") or "",
                "tree_chars": tree_info.get("chars") or 0,
                "screenshot_key": screenshot_key,
                "verify": verify,
                "ts": int(time.time()),
            }
            steps_detail.append(entry)
            # Keep Dynamo item small
            state["steps_detail"] = steps_detail[-40:]

        shot_key = None
        if image_b64:
            shot_key = _store_step_screenshot(
                str(job.get("job_id") or ""), step + 1, image_b64
            )

        if kind == "done":
            state["steps"] = step + 1
            state["last_action"] = f"done: {reason}"
            history.append(f"done: {reason}")
            state["history"] = history
            _record_step(f"done: {reason}", screenshot_key=shot_key)
            job["state"] = state
            job["status"] = "completed"
            job["result"] = reason or "Goal completed"
            job["completed_at"] = int(time.time())
            return job
        if kind == "fail":
            state["steps"] = step + 1
            state["last_action"] = f"fail: {reason}"
            history.append(f"fail: {reason}")
            state["history"] = history
            _record_step(f"fail: {reason}", ok=False, screenshot_key=shot_key)
            job["state"] = state
            job["status"] = "failed"
            job["error"] = reason or "Agent could not complete the goal"
            job["completed_at"] = int(time.time())
            return job

        # Identical swipe detection before executing
        pending_summary_prefix = "swipe(" if kind == "swipe" else ""
        if (
            pending_summary_prefix
            and _count_recent_swipes(history) >= MAX_SWIPE_LOOPS - 1
        ):
            raise RuntimeError(
                "Swipe loop detected — aborting. Use open_app instead of launcher swipes."
            )

        summary = execute_action(device_id, action)

        # Verify: re-fetch tree / package after action (short timeout)
        verify_msg = ""
        rpc_pkg = str(action.get("_rpc_package") or "")
        rpc_ok_flag = bool(action.get("_rpc_ok"))
        try:
            after = _normalize_tree_payload(
                call_device(
                    device_id,
                    "get_ui_tree",
                    {},
                    timeout_s=8,
                    wait_reconnect_s=30,
                )
                or ""
            )
            if kind in ("open_app", "start_app"):
                app_l = str(action.get("app") or "").lower()
                pkg_l = (after.get("package") or rpc_pkg or "").lower()
                tree_l = (after.get("tree") or "").lower()
                tokens = []
                pkg_tokens = []
                if "setting" in app_l:
                    tokens.append("settings")
                    pkg_tokens.append("com.android.settings")
                if "whatsapp" in app_l or app_l == "wa":
                    tokens.append("whatsapp")
                    pkg_tokens.append("com.whatsapp")
                if "chrome" in app_l:
                    tokens.append("chrome")
                    pkg_tokens.append("com.android.chrome")
                if "snap" in app_l:
                    tokens.append("snapchat")
                    pkg_tokens.append("com.snapchat.android")
                if "message" in app_l or "sms" in app_l:
                    tokens.append("messaging")
                    pkg_tokens.append("com.google.android.apps.messaging")
                opened = bool(pkg_l) and (
                    any(tok in pkg_l for tok in tokens + pkg_tokens)
                    or app_l.replace(" ", "") in pkg_l.replace(".", "")
                    or any(tok in tree_l for tok in tokens)
                    or any(p in tree_l for p in pkg_tokens)
                )
                if rpc_ok_flag and rpc_pkg:
                    opened = True
                if (
                    not opened
                    and after.get("package")
                    and after["package"] != tree_info.get("package")
                    and after["package"] not in ("android", "com.android.systemui")
                ):
                    opened = True
                    verify_msg = f"package→{after['package']}"
                elif opened:
                    verify_msg = f"open_ok package={after.get('package') or rpc_pkg}"
                else:
                    verify_msg = (
                        f"open_unconfirmed package={after.get('package')!r} "
                        f"tree_chars={after.get('chars')}"
                    )
            else:
                verify_msg = (
                    f"after_chars={after.get('chars')} pkg={after.get('package')}"
                )
        except Exception as ve:
            # Trust PackageManager launch even when verify tree times out
            if kind in ("open_app", "start_app") and (rpc_ok_flag or rpc_pkg):
                verify_msg = f"open_ok package={rpc_pkg or 'rpc'} (verify_skipped={ve})"
            else:
                verify_msg = f"verify_error={ve}"

        state["steps"] = step + 1
        state["last_action"] = summary
        state["last_reason"] = reason
        state["last_verify"] = verify_msg
        history.append(f"{summary} — {reason}".strip(" —"))
        state["history"] = history
        _record_step(summary, screenshot_key=shot_key, verify=verify_msg)
        job["state"] = state
        if planner == "heuristic":
            job["result"] = f"Step {step + 1}: {summary} ({LLM_UNAVAILABLE_LABEL})"
        else:
            job["result"] = f"Step {step + 1}: {summary}"
            if verify_msg:
                job["result"] += f" · {verify_msg}"

        # Pure open_app goal → complete once PackageManager launched
        open_target = _trivial_open_app_target(instruction)
        if open_target and kind in ("open_app", "start_app"):
            # Prefer RPC package in summary: Opened X[com.foo]
            if not rpc_pkg:
                m = re.search(r"\[([a-zA-Z0-9._]+)\]\s*$", summary or "")
                if m:
                    rpc_pkg = m.group(1).lower()
            known = {
                "settings": ("com.android.settings", "settings"),
                "whatsapp": ("com.whatsapp", "whatsapp"),
                "chrome": ("com.android.chrome", "chrome"),
                "snapchat": ("com.snapchat.android", "snap"),
                "messages": ("com.google.android.apps.messaging", "messaging"),
            }
            tokens = []
            for key, (pkg, tok) in known.items():
                if key in open_target.lower():
                    tokens.extend([pkg, tok])
            rpc_ok = bool(rpc_pkg) and (
                any(t in rpc_pkg for t in tokens)
                or open_target.lower() in rpc_pkg
                or rpc_ok_flag
            )
            verify_ok = (
                "open_ok" in verify_msg
                or (
                    "open_unconfirmed" not in verify_msg
                    and bool(verify_msg)
                    and "verify_error" not in verify_msg
                )
            )
            # Overlays (ANR / permission) may report package=android briefly;
            # trust PackageManager launch result for trivial open goals.
            if rpc_ok or verify_ok or rpc_ok_flag:
                job["status"] = "completed"
                job["result"] = (
                    f"Opened {open_target} "
                    f"(pkg={rpc_pkg or 'n/a'}; {verify_msg or summary})"
                )
                job["completed_at"] = int(time.time())
                return job

        # ~1s between steps (was 2s) — target ≤10s wall per step overall
        job["next_run_at"] = int(time.time()) + 1
        job["updated_at"] = int(time.time())
        _kick_self(job.get("job_id"))
        return job
    except Exception as e:
        logger.exception("agent step failed job=%s", job.get("job_id"))
        state["last_action"] = f"error: {e}"
        history.append(f"error: {e}")
        state["history"] = history
        steps_detail.append(
            {
                "n": step + 1,
                "action": f"error: {e}",
                "reason": str(e),
                "ok": False,
                "ts": int(time.time()),
            }
        )
        state["steps_detail"] = steps_detail[-40:]
        job["state"] = state
        msg = str(e)
        low = msg.lower()
        a11y_fail = "accessibility service not connected" in low
        hard = any(
            t in low
            for t in (
                "no llm",
                "no working llm",
                "llm unavailable",
                "offline",
                "api key",
                "failed to push",
                "swipe loop",
            )
        ) or (
            a11y_fail
            and sum(
                1
                for h in history
                if "accessibility service not connected" in str(h).lower()
            )
            >= 2
        )
        rate_limited = any(t in low for t in ("429", "503", "quota", "high demand"))
        if hard or step + 1 >= max_steps:
            job["status"] = "failed"
            job["completed_at"] = int(time.time())
            if LLM_UNAVAILABLE_LABEL.lower() in low or "no working llm" in low:
                if LLM_UNAVAILABLE_LABEL not in msg:
                    job["error"] = f"{LLM_UNAVAILABLE_LABEL} — {msg}"
                else:
                    job["error"] = msg
            else:
                job["error"] = msg
        else:
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
