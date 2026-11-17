#!/usr/bin/env python3
"""Multi-step messaging-style task + mid-task WS drop recovery against prod.

Uses Messages stand-in (or Settings multi-step) on a paired emulator APK.
Forces a brief network drop via adb, then asserts the job recovers and
accumulates ≥10 steps / completes without permanent offline.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

API = os.environ.get(
    "API_URL", "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
).rstrip("/")
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
DEVICE_ID = os.environ.get("DEVICE_ID", "")
ARTIFACTS = os.environ.get("ARTIFACTS_DIR", "/tmp/phone-ws-recovery")
os.makedirs(ARTIFACTS, exist_ok=True)


def req(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = 90,
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
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:600]}") from e


def adb(*args: str) -> None:
    subprocess.run(["adb", *args], check=False, capture_output=True)


def main() -> int:
    if not DEVICE_ID:
        raise RuntimeError("DEVICE_ID required")
    tok = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})[
        "access_token"
    ]
    instr = os.environ.get(
        "E2E_INSTRUCTION",
        "open Messages and search for a conversation, then type hello from macai test",
    )
    print("START", instr, flush=True)
    task = req(
        "POST",
        "/api/tasks",
        {
            "device_id": DEVICE_ID,
            "instruction": instr,
            "max_steps": 14,
            "mode": "normal",
            "speed_preset": "fast",
        },
        token=tok,
    )
    tid = task["task_id"]
    print("task", tid, flush=True)

    dropped = False
    last: Dict[str, Any] = {}
    for i in range(120):
        last = req("GET", f"/api/tasks/{tid}", token=tok)
        st = (last.get("status") or "").lower()
        steps = last.get("steps") or []
        print(
            f"  [{i}] {st} steps={len(steps)} result={str(last.get('result'))[:100]}",
            flush=True,
        )
        # Mid-task: briefly drop network once we have ≥2 steps
        if not dropped and len(steps) >= 2 and st == "running":
            print("FORCE network drop 8s", flush=True)
            adb("shell", "svc", "wifi", "disable")
            adb("shell", "svc", "data", "disable")
            time.sleep(8)
            adb("shell", "svc", "wifi", "enable")
            adb("shell", "svc", "data", "enable")
            # Bring app to foreground so it can reconnect
            adb(
                "shell",
                "monkey",
                "-p",
                "ai.mobilerun.selfhosted",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )
            dropped = True
            time.sleep(5)
        if st in ("completed", "failed", "stopped", "cancelled"):
            break
        if len(steps) >= 10 and st == "running":
            # Enough evidence of multi-step progress
            break
        time.sleep(3)

    steps = last.get("steps") or []
    open(f"{ARTIFACTS}/task.json", "w").write(json.dumps(last, indent=2))
    report = {
        "task_id": tid,
        "status": last.get("status"),
        "steps": len(steps),
        "dropped": dropped,
        "result": last.get("result"),
        "error": last.get("error"),
        "sample": [
            {k: s.get(k) for k in ("n", "action", "reason", "ok", "verify")}
            for s in steps[:12]
        ],
    }
    # Success: ≥10 steps OR completed, and not a permanent offline after drop
    ok = (len(steps) >= 10 or (last.get("status") or "").lower() == "completed") and not (
        dropped
        and (last.get("status") or "").lower() == "failed"
        and "offline" in str(last.get("error") or "").lower()
        and len(steps) < 4
    )
    # Also require we didn't just loop open_app
    opens = sum(
        1
        for s in steps
        if str(s.get("action") or "").lower().startswith("opened ")
        or str(s.get("action") or "").lower().startswith("open_app")
    )
    report["open_count"] = opens
    report["ok"] = ok and opens <= 3
    open(f"{ARTIFACTS}/report.json", "w").write(json.dumps(report, indent=2))
    print("RESULT", "OK" if report["ok"] else "FAIL", json.dumps(report)[:800])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("RESULT FAIL", e)
        sys.exit(1)
