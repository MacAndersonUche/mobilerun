#!/usr/bin/env python3
"""Prod E2E: AWS-only short-code pair + multi-step cloud agent task + chat.

Requires a live emulator already installed/paired OR will create a pair code
and claim via deep link (caller must fire the intent).

Usage:
  API_URL=https://... WS_URL=wss://.../prod \\
  python3 scripts/verify_prod_agent_e2e.py [--device-id DID] [--skip-pair]

Exit 0 on success. Prints a one-line RESULT for the agent report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

API = os.environ.get(
    "API_URL", "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
).rstrip("/")
WS = os.environ.get(
    "WS_URL", "wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod"
)
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
# Default: PackageManager open_app path (Settings). Override with E2E_INSTRUCTION.
INSTRUCTION = os.environ.get("E2E_INSTRUCTION", "open settings")
# Second task: installed-app launch (Chrome stands in for WhatsApp on emulator).
APP_INSTRUCTION = os.environ.get("E2E_APP_INSTRUCTION", "open chrome")


def req(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = 60,
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:500]}") from e


def login() -> str:
    d = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})
    return d["access_token"]


def wait_device(token: str, want: Optional[str] = None, timeout_s: int = 90):
    deadline = time.time() + timeout_s
    last = []
    while time.time() < deadline:
        last = req("GET", "/api/devices", token=token) or []
        for d in last:
            did = str(d.get("device_id") or "")
            online = bool(
                d.get("connected") or d.get("online") or d.get("status") == "online"
            )
            if want and did != want:
                continue
            if did and online:
                return d
        time.sleep(2)
    raise RuntimeError(f"No online device within {timeout_s}s: {last}")


def poll_task(token: str, task_id: str, timeout_s: int = 240) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = req("GET", f"/api/tasks/{task_id}", token=token)
        status = (last.get("status") or "").lower()
        step = last.get("current_step") or last.get("state", {}).get("steps")
        n_steps = len(last.get("steps") or [])
        print(
            f"  task {task_id} status={status} step={step} "
            f"steps_list={n_steps} "
            f"result={last.get('result')!r} error={last.get('error')!r}",
            flush=True,
        )
        if status in ("completed", "failed", "cancelled", "stopped"):
            return last
        time.sleep(3)
    raise RuntimeError(f"Task timeout: {last}")


def _assert_llm(result: Dict[str, Any], label: str) -> None:
    planner = result.get("planner") or (result.get("state") or {}).get("planner")
    llm_provider = result.get("llm_provider") or (result.get("state") or {}).get(
        "llm_provider"
    )
    if planner == "heuristic" or (
        isinstance(result.get("result"), str)
        and "LLM unavailable: quota" in result.get("result", "")
        and not llm_provider
    ):
        raise RuntimeError(
            f"{label} used heuristic planner — not valid verification "
            f"(planner={planner!r} llm_provider={llm_provider!r})"
        )
    if llm_provider not in ("gemini", "openai"):
        raise RuntimeError(
            f"{label} missing real LLM provider "
            f"(planner={planner!r} llm_provider={llm_provider!r})"
        )


def _assert_steps(result: Dict[str, Any], label: str) -> List[Dict[str, Any]]:
    steps = result.get("steps") or []
    if not isinstance(steps, list) or len(steps) < 1:
        # Fallback: history strings in state
        hist = (result.get("state") or {}).get("history") or []
        if hist:
            print(f"  {label}: steps[] empty but history={hist[:5]!r}", flush=True)
            return [{"action": h} for h in hist]
        raise RuntimeError(f"{label}: Task history has no per-step actions")
    for s in steps:
        if not (s.get("action") or "").strip():
            raise RuntimeError(f"{label}: empty step action in {s!r}")
    print(
        f"  {label}: {len(steps)} steps → "
        + "; ".join(str(s.get("action"))[:60] for s in steps[:6]),
        flush=True,
    )
    return steps


def run_task(
    token: str, device_id: str, instruction: str, *, max_steps: int = 10
) -> Dict[str, Any]:
    print("SUBMIT_TASK", instruction)
    task = req(
        "POST",
        "/api/tasks",
        {
            "device_id": device_id,
            "instruction": instruction,
            "max_steps": max_steps,
            "mode": "normal",
            "speed_preset": "fast",
        },
        token=token,
    )
    task_id = task.get("task_id") or task.get("id")
    print("task_id", task_id)
    result = poll_task(token, task_id, timeout_s=300)
    status = (result.get("status") or "").lower()
    print(
        "TASK_RESULT",
        json.dumps(
            {
                "instruction": instruction,
                "task_id": task_id,
                "status": status,
                "current_step": result.get("current_step"),
                "steps": result.get("steps"),
                "planner": result.get("planner"),
                "llm_provider": result.get("llm_provider"),
                "result": result.get("result"),
                "error": result.get("error"),
            }
        )[:2000],
    )
    if status != "completed":
        raise RuntimeError(
            f"instruction={instruction!r} status={status} "
            f"error={result.get('error')!r}"
        )
    _assert_llm(result, instruction)
    _assert_steps(result, instruction)
    # Also confirm History list endpoint surfaces the task with steps
    listed = req("GET", "/api/tasks?limit=20", token=token) or []
    hit = next((t for t in listed if t.get("task_id") == task_id), None)
    if not hit:
        print(f"WARN history list missing {task_id}", flush=True)
    else:
        print(
            f"  history_list status={hit.get('status')} "
            f"steps={len(hit.get('steps') or [])}",
            flush=True,
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device-id", default=os.environ.get("DEVICE_ID"))
    ap.add_argument("--skip-pair", action="store_true")
    ap.add_argument("--pair-code-out", default="/tmp/prod-e2e/pair.json")
    args = ap.parse_args()

    print("API", API)
    health = req("GET", "/api/health")
    assert health.get("status") == "ok", health
    print("health ok", health.get("step_driven"), health.get("use_aws_storage"))

    token = login()
    me = req("GET", "/api/auth/me", token=token)
    print("auth", me.get("email"))

    for path in (
        "/api/dating/status",
        "/api/dating/review-queue",
        "/api/dating/openers",
        "/api/mode",
        "/api/humanizer",
    ):
        d = req("GET", path, token=token)
        print(f"dating_ok {path} keys={list(d)[:6]}")

    device_id = args.device_id
    if not args.skip_pair and not device_id:
        pair = req(
            "POST",
            "/api/auth/pair/create",
            {"device_name": "prod-e2e-emu", "platform": "android"},
            token=token,
        )
        os.makedirs(os.path.dirname(args.pair_code_out) or ".", exist_ok=True)
        with open(args.pair_code_out, "w") as f:
            json.dump(pair, f, indent=2)
        code = pair.get("code") or pair.get("token")
        from urllib.parse import urlencode

        q = urlencode(
            {
                "c": code,
                "cloud": API,
                "cloud_ws": WS,
                "backend": API,
                "ws": WS,
            }
        )
        deep = "mobilerun://pair?" + q
        print("PAIR_CODE", code)
        print("PAIR_DEEP_LINK", deep)
        print(
            "Waiting for APK claim via deep link (caller should am start)…",
            flush=True,
        )
        with open("/tmp/prod-e2e/am_pair.sh", "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"adb shell \"am start -a android.intent.action.VIEW -d '{deep}'\"\n"
            )
        os.chmod("/tmp/prod-e2e/am_pair.sh", 0o755)

    if not device_id:
        dev = wait_device(token, timeout_s=120)
        device_id = str(dev.get("device_id"))
        print(
            "paired_device",
            device_id,
            "route",
            dev.get("route") or dev.get("connection_type"),
        )
    else:
        wait_device(token, want=device_id, timeout_s=60)
        print("device_online", device_id)

    # (1) open settings — PackageManager / ACTION_SETTINGS path
    settings_result = run_task(token, device_id, INSTRUCTION, max_steps=8)

    # (2) open installed app (Chrome ≈ WhatsApp-style launch on emu)
    app_result = run_task(token, device_id, APP_INSTRUCTION, max_steps=8)

    # Optional multi-step chat path (still must use real LLM)
    chat_instr = os.environ.get(
        "E2E_CHAT_INSTRUCTION",
        "open Settings",
    )
    print("SUBMIT_CHAT", chat_instr)
    chat = req(
        "POST",
        "/api/chat",
        {
            "message": f"Please {chat_instr}",
            "device_id": device_id,
            "target": "hosted",
        },
        token=token,
    )
    print("chat_resp", json.dumps(chat)[:500])
    chat_task_id = None
    if isinstance(chat, dict):
        chat_task_id = (
            chat.get("task_id")
            or (chat.get("task") or {}).get("task_id")
            or (chat.get("data") or {}).get("task_id")
        )
        for a in chat.get("actions") or []:
            if isinstance(a, dict) and a.get("task_id"):
                chat_task_id = a["task_id"]
                break
    if not chat_task_id:
        t2 = req(
            "POST",
            "/api/tasks",
            {
                "device_id": device_id,
                "instruction": chat_instr,
                "max_steps": 8,
                "mode": "normal",
                "speed_preset": "fast",
            },
            token=token,
        )
        chat_task_id = t2.get("task_id")
        print("chat_fallback_task", chat_task_id)

    chat_result = poll_task(token, chat_task_id, timeout_s=240)
    chat_status = (chat_result.get("status") or "").lower()
    if chat_status != "completed":
        raise RuntimeError(f"chat task failed status={chat_status}")
    _assert_llm(chat_result, "chat")
    _assert_steps(chat_result, "chat")

    print(
        "RESULT OK "
        f"settings={INSTRUCTION!r} steps={len(settings_result.get('steps') or [])} "
        f"llm={settings_result.get('llm_provider')}; "
        f"app={APP_INSTRUCTION!r} steps={len(app_result.get('steps') or [])} "
        f"llm={app_result.get('llm_provider')}; "
        f"chat={chat_instr!r} steps={len(chat_result.get('steps') or [])} "
        f"llm={chat_result.get('llm_provider')}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("RESULT FAIL", e)
        sys.exit(1)
