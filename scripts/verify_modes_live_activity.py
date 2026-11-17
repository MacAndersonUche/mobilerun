#!/usr/bin/env python3
"""E2E: Normal + Dating dry-run + Social dry-run on a real paired APK device.

Requires DEVICE_ID online against live API. Uses /api/jobs/{id}/tick to advance
dry-run modes quickly. Does not send real likes/messages.
"""

from __future__ import annotations

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
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
DEVICE_ID = os.environ.get("DEVICE_ID", "")
ARTIFACTS = os.environ.get("ARTIFACTS_DIR", "/tmp/modes-live-activity")
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


def login() -> str:
    return req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})[
        "access_token"
    ]


def poll_task(token: str, task_id: str, timeout_s: int = 240) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = req("GET", f"/api/tasks/{task_id}", token=token)
        st = (last.get("status") or "").lower()
        print(
            f"  task {task_id} status={st} steps={len(last.get('steps') or [])}",
            flush=True,
        )
        if st in ("completed", "failed", "stopped", "cancelled"):
            return last
        time.sleep(3)
    raise RuntimeError(f"task timeout {last}")


def tick_until_steps(
    token: str, job_id: str, min_steps: int = 3, max_ticks: int = 12
) -> Dict[str, Any]:
    activity: Dict[str, Any] = {}
    for i in range(max_ticks):
        activity = req("POST", f"/api/jobs/{job_id}/tick", {}, token=token)
        act = activity.get("activity") or activity
        n = len(act.get("steps") or [])
        print(
            f"  tick {i+1} job={job_id} status={act.get('status')} steps={n} "
            f"last={act.get('last_action')!r}",
            flush=True,
        )
        open(f"{ARTIFACTS}/{job_id}_tick_{i+1}.json", "w").write(
            json.dumps(activity, indent=2)
        )
        if n >= min_steps or (act.get("status") or "") in (
            "completed",
            "stopped",
            "failed",
        ):
            return act
        time.sleep(1.5)
    return activity.get("activity") or activity


def main() -> int:
    if not DEVICE_ID:
        raise RuntimeError("DEVICE_ID required")
    report: Dict[str, Any] = {"device_id": DEVICE_ID, "modes": {}}
    token = login()
    print("auth ok", flush=True)

    # --- Normal ---
    instr = os.environ.get("E2E_INSTRUCTION", "open settings")
    print("NORMAL", instr, flush=True)
    task = req(
        "POST",
        "/api/tasks",
        {
            "device_id": DEVICE_ID,
            "instruction": instr,
            "max_steps": 8,
            "mode": "normal",
            "speed_preset": "fast",
        },
        token=token,
    )
    tid = task.get("task_id")
    result = poll_task(token, tid, timeout_s=300)
    steps = result.get("steps") or []
    ok_n = (result.get("status") or "").lower() == "completed" and len(steps) >= 1
    report["modes"]["normal"] = {
        "ok": ok_n,
        "task_id": tid,
        "status": result.get("status"),
        "steps": len(steps),
        "llm": result.get("llm_provider"),
        "result": result.get("result"),
        "error": result.get("error"),
    }
    print("NORMAL_RESULT", json.dumps(report["modes"]["normal"]), flush=True)
    if not ok_n:
        raise RuntimeError("normal mode failed")

    # --- Dating dry-run ---
    print("DATING dry-run start", flush=True)
    # stop any prior
    try:
        req("POST", "/api/dating/stop", {}, token=token)
    except Exception:
        pass
    dstart = req(
        "POST",
        "/api/dating/start",
        {
            "device_id": DEVICE_ID,
            "dry_run": True,
            "stand_in_package": os.environ.get(
                "DATING_STAND_IN", "ai.mobilerun.mockdating"
            ),
        },
        token=token,
    )
    djob = (dstart.get("job") or {}).get("job_id") or dstart.get("job_id")
    if not djob:
        raise RuntimeError(f"dating start missing job_id: {dstart}")
    dact = tick_until_steps(token, djob, min_steps=3, max_ticks=10)
    d_steps = dact.get("steps") or []
    ok_d = len(d_steps) >= 2
    report["modes"]["dating"] = {
        "ok": ok_d,
        "job_id": djob,
        "status": dact.get("status"),
        "steps": len(d_steps),
        "dry_run": True,
        "last_action": dact.get("last_action"),
        "package": dact.get("package"),
        "sample": d_steps[:3],
    }
    print("DATING_RESULT", json.dumps(report["modes"]["dating"])[:1500], flush=True)
    req("POST", "/api/dating/stop", {}, token=token)

    # --- Social dry-run ---
    print("SOCIAL dry-run start", flush=True)
    try:
        req("POST", "/api/social/stop", {}, token=token)
    except Exception:
        pass
    sstart = req(
        "POST",
        "/api/social/start",
        {
            "device_id": DEVICE_ID,
            "dry_run": True,
            "stand_in_package": os.environ.get(
                "SOCIAL_STAND_IN", "com.google.android.apps.messaging"
            ),
            "max_steps": 6,
        },
        token=token,
    )
    sjob = (sstart.get("job") or {}).get("job_id") or sstart.get("job_id")
    if not sjob:
        raise RuntimeError(f"social start missing job_id: {sstart}")
    sact = tick_until_steps(token, sjob, min_steps=3, max_ticks=10)
    s_steps = sact.get("steps") or []
    ok_s = len(s_steps) >= 2
    report["modes"]["social"] = {
        "ok": ok_s,
        "job_id": sjob,
        "status": sact.get("status"),
        "steps": len(s_steps),
        "dry_run": True,
        "last_action": sact.get("last_action"),
        "package": sact.get("package"),
        "sample": s_steps[:3],
    }
    print("SOCIAL_RESULT", json.dumps(report["modes"]["social"])[:1500], flush=True)
    req("POST", "/api/social/stop", {}, token=token)

    # History should list dating/social
    hist = req("GET", "/api/tasks?limit=30", token=token) or []
    kinds = [(t.get("mode") or t.get("instruction") or "") for t in hist[:15]]
    report["history_sample"] = kinds
    open(f"{ARTIFACTS}/report.json", "w").write(json.dumps(report, indent=2))

    all_ok = ok_n and ok_d and ok_s
    print("RESULT", "OK" if all_ok else "FAIL", json.dumps(report["modes"]))
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("RESULT FAIL", e)
        sys.exit(1)
