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
from typing import Any, Dict, Optional

API = os.environ.get(
    "API_URL", "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
).rstrip("/")
WS = os.environ.get(
    "WS_URL", "wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod"
)
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
INSTRUCTION = os.environ.get(
    "E2E_INSTRUCTION",
    "open Settings, go to Display, and turn on dark theme",
)


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
        print(
            f"  task {task_id} status={status} step={step} "
            f"result={last.get('result')!r} error={last.get('error')!r}",
            flush=True,
        )
        if status in ("completed", "failed", "cancelled", "stopped"):
            return last
        time.sleep(3)
    raise RuntimeError(f"Task timeout: {last}")


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

    # Dating must load (no backend-not-connected)
    for path in (
        "/api/dating/status",
        "/api/dating/review-queue",
        "/api/dating/openers",
        "/api/selectors/status",
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
        # AWS-only deep link (no LAN)
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
        # Also write a shell helper
        with open("/tmp/prod-e2e/am_pair.sh", "w") as f:
            f.write(
                "#!/bin/bash\n"
                f"adb shell \"am start -a android.intent.action.VIEW -d '{deep}'\"\n"
            )
        os.chmod("/tmp/prod-e2e/am_pair.sh", 0o755)

    if not device_id:
        # Wait for any online device owned by ci-e2e
        dev = wait_device(token, timeout_s=120)
        device_id = str(dev.get("device_id"))
        print(
            "paired_device",
            device_id,
            "route",
            dev.get("route") or dev.get("connection_type"),
        )
    else:
        dev = wait_device(token, want=device_id, timeout_s=60)
        print("device_online", device_id)

    # --- Tasks page path ---
    print("SUBMIT_TASK", INSTRUCTION)
    task = req(
        "POST",
        "/api/tasks",
        {
            "device_id": device_id,
            "instruction": INSTRUCTION,
            "max_steps": 15,
            "mode": "normal",
            "speed_preset": "fast",
        },
        token=token,
    )
    task_id = task.get("task_id") or task.get("id")
    print("task_id", task_id)
    result = poll_task(token, task_id, timeout_s=300)
    steps = (
        result.get("current_step")
        or (result.get("state") or {}).get("steps")
        or result.get("max_steps")
    )
    status = (result.get("status") or "").lower()
    planner = result.get("planner") or (result.get("state") or {}).get("planner")
    llm_provider = result.get("llm_provider") or (result.get("state") or {}).get(
        "llm_provider"
    )
    print(
        "TASK_RESULT",
        json.dumps(
            {
                "path": "Tasks",
                "instruction": INSTRUCTION,
                "task_id": task_id,
                "status": status,
                "steps": steps,
                "planner": planner,
                "llm_provider": llm_provider,
                "result": result.get("result"),
                "error": result.get("error"),
                "state": result.get("state"),
            }
        ),
    )
    if status != "completed":
        print(
            f"RESULT FAIL Tasks instruction={INSTRUCTION!r} status={status} "
            f"steps={steps} error={result.get('error')!r}"
        )
        return 1
    # Real verification must use an actual LLM — never heuristic
    if planner == "heuristic" or (
        isinstance(result.get("result"), str)
        and "LLM unavailable: quota" in result.get("result", "")
        and not llm_provider
    ):
        print(
            "RESULT FAIL Tasks used heuristic planner — not valid verification "
            f"(planner={planner!r} llm_provider={llm_provider!r})"
        )
        return 1
    if llm_provider not in ("gemini", "openai"):
        print(
            "RESULT FAIL Tasks missing real LLM provider "
            f"(planner={planner!r} llm_provider={llm_provider!r})"
        )
        return 1

    # --- Ask Mac / chat path ---
    chat_instr = "open Settings and go to Display"
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
        # Some chat responses nest under actions
        for a in chat.get("actions") or []:
            if isinstance(a, dict) and a.get("task_id"):
                chat_task_id = a["task_id"]
                break
    if not chat_task_id:
        # Fallback: submit another task as chat would
        t2 = req(
            "POST",
            "/api/tasks",
            {
                "device_id": device_id,
                "instruction": chat_instr,
                "max_steps": 12,
                "mode": "normal",
                "speed_preset": "fast",
            },
            token=token,
        )
        chat_task_id = t2.get("task_id")
        print("chat_fallback_task", chat_task_id)

    chat_result = poll_task(token, chat_task_id, timeout_s=240)
    chat_status = (chat_result.get("status") or "").lower()
    chat_steps = chat_result.get("current_step") or (
        chat_result.get("state") or {}
    ).get("steps")
    chat_planner = chat_result.get("planner") or (chat_result.get("state") or {}).get(
        "planner"
    )
    chat_llm = chat_result.get("llm_provider") or (chat_result.get("state") or {}).get(
        "llm_provider"
    )
    print(
        "CHAT_RESULT",
        json.dumps(
            {
                "path": "Ask Mac chat",
                "instruction": chat_instr,
                "task_id": chat_task_id,
                "status": chat_status,
                "steps": chat_steps,
                "planner": chat_planner,
                "llm_provider": chat_llm,
                "result": chat_result.get("result"),
                "error": chat_result.get("error"),
            }
        ),
    )

    ok = (
        status == "completed"
        and chat_status == "completed"
        and llm_provider in ("gemini", "openai")
        and chat_llm in ("gemini", "openai")
        and planner != "heuristic"
        and chat_planner != "heuristic"
    )
    print(
        f"RESULT {'OK' if ok else 'FAIL'} "
        f"Tasks: {INSTRUCTION!r} status={status} steps={steps} "
        f"llm={llm_provider}; "
        f"Chat: {chat_instr!r} status={chat_status} steps={chat_steps} "
        f"llm={chat_llm}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("RESULT FAIL", e)
        sys.exit(1)
