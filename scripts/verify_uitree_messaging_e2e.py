#!/usr/bin/env python3
"""Real-APK emulator vs prod: messaging flow + optional network drop + tree timings.

Seeds an emulator contact, runs a multi-step Messages task, optionally drops
network mid-task, and prints get_ui_tree build_ms p50/p95 from step timings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

API = os.environ.get(
    "API_URL", "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
).rstrip("/")
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
DEVICE_ID = os.environ.get("DEVICE_ID", "")
ARTIFACTS = os.environ.get("ARTIFACTS_DIR", "/tmp/uitree-msg-e2e")
DROP = os.environ.get("FORCE_DROP", "1") not in ("0", "false", "no")
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5554")
os.makedirs(ARTIFACTS, exist_ok=True)

A11Y = "ai.mobilerun.selfhosted/ai.mobilerun.selfhosted.MobilerunAccessibilityService"


def req(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = 90,
    retries: int = 5,
) -> Any:
    """HTTP helper with exponential backoff on 502/503/504."""
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_err: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        r = urllib.request.Request(
            API + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            last_err = RuntimeError(f"{method} {path} -> {e.code}: {err[:600]}")
            if e.code in (502, 503, 504) and attempt + 1 < retries:
                time.sleep(min(16.0, 0.6 * (2**attempt)))
                continue
            raise last_err from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = RuntimeError(f"{method} {path} -> {e}")
            if attempt + 1 < retries:
                time.sleep(min(16.0, 0.6 * (2**attempt)))
                continue
            raise last_err from e
    raise last_err or RuntimeError(f"{method} {path} failed")


def adb(*args: str) -> None:
    subprocess.run(["adb", "-s", SERIAL, *args], check=False, capture_output=True)


def ensure_a11y_bound() -> None:
    """Ensure accessibility is enabled without tearing down a live WS session.

    Only force a full off/on cycle when dumpsys shows the service is not Bound
    (stuck Binding). A blunt toggle kills the app process and drops prod WS.
    """
    adb("shell", "dumpsys", "deviceidle", "whitelist", "+ai.mobilerun.selfhosted")
    dump = subprocess.run(
        ["adb", "-s", SERIAL, "shell", "dumpsys", "accessibility"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    bound = "Bound services:{Service[" in dump and "Mobilerun" in dump
    if bound:
        return
    adb("shell", "am", "force-stop", "com.android.settings")
    adb("shell", "settings", "put", "secure", "enabled_accessibility_services", "")
    adb("shell", "settings", "put", "secure", "accessibility_enabled", "0")
    time.sleep(1)
    adb("shell", "settings", "put", "secure", "enabled_accessibility_services", A11Y)
    adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
    time.sleep(2)
    adb(
        "shell",
        "am",
        "start",
        "-n",
        "ai.mobilerun.selfhosted/.MainActivity",
    )
    time.sleep(3)


def seed_contact() -> None:
    """Best-effort seed a Messages-friendly contact on the emulator."""
    ensure_a11y_bound()
    adb(
        "shell",
        "content",
        "insert",
        "--uri",
        "content://com.android.contacts/raw_contacts",
        "--bind",
        "account_type:s:null",
        "--bind",
        "account_name:s:null",
    )
    adb(
        "shell",
        "content",
        "insert",
        "--uri",
        "content://com.android.contacts/data",
        "--bind",
        "raw_contact_id:i:1",
        "--bind",
        "mimetype:s:vnd.android.cursor.item/name",
        "--bind",
        "data1:s:MacAITest",
    )
    adb(
        "shell",
        "content",
        "insert",
        "--uri",
        "content://com.android.contacts/data",
        "--bind",
        "raw_contact_id:i:1",
        "--bind",
        "mimetype:s:vnd.android.cursor.item/phone_v2",
        "--bind",
        "data1:s:5550100",
        "--bind",
        "data2:i:2",
    )
    adb("shell", "input", "keyevent", "KEYCODE_HOME")


def percentile(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return float(s[f] + (s[c] - s[f]) * (k - f))


def main() -> int:
    if not DEVICE_ID:
        raise RuntimeError("DEVICE_ID required")
    seed_contact()
    tok = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})[
        "access_token"
    ]
    instr = os.environ.get(
        "E2E_INSTRUCTION",
        "Open Messages. Search for contact MacAITest or number 5550100, open that "
        "chat (or start a new conversation), type hello from macai uitree recovery "
        "test into the compose field, send it, and confirm the message appears in "
        "the thread. Keep taking UI steps until send is confirmed.",
    )
    print("START", instr, flush=True)
    task = req(
        "POST",
        "/api/tasks",
        {
            "device_id": DEVICE_ID,
            "instruction": instr,
            "max_steps": 24,
            "mode": "normal",
            "speed_preset": "fast",
        },
        token=tok,
    )
    tid = task["task_id"]
    print("task", tid, flush=True)

    dropped = False
    last: Dict[str, Any] = {}
    for i in range(360):  # up to ~12 min with 2s poll
        try:
            last = req("GET", f"/api/tasks/{tid}", token=tok)
        except RuntimeError as e:
            print(f"  [{i}] poll error: {e}", flush=True)
            time.sleep(4)
            continue
        st = (last.get("status") or "").lower()
        steps = last.get("steps") or []
        print(
            f"  [{i}] {st} steps={len(steps)} result={str(last.get('result'))[:110]}",
            flush=True,
        )
        if DROP and not dropped and len(steps) >= 4 and st == "running":
            print("FORCE network drop 6s", flush=True)
            adb("shell", "svc", "wifi", "disable")
            adb("shell", "svc", "data", "disable")
            time.sleep(6)
            adb("shell", "svc", "wifi", "enable")
            adb("shell", "svc", "data", "enable")
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
            time.sleep(8)
        if st in ("completed", "failed", "stopped", "cancelled"):
            break
        if len(steps) >= 10 and st == "completed":
            break
        if len(steps) >= 12:
            break
        time.sleep(2)

    steps = last.get("steps") or []
    build_ms: List[float] = []
    for s in steps:
        t = s.get("timing") or {}
        if isinstance(t, dict) and t.get("build_ms") is not None:
            try:
                build_ms.append(float(t["build_ms"]))
            except (TypeError, ValueError):
                pass
        for blob in (str(s.get("verify") or ""), str(s.get("action") or "")):
            if "tree_ms=" in blob:
                try:
                    build_ms.append(
                        float(blob.split("tree_ms=")[1].split()[0].strip("·"))
                    )
                except Exception:
                    pass

    p50 = percentile(build_ms, 50)
    p95 = percentile(build_ms, 95)
    report = {
        "task_id": tid,
        "status": last.get("status"),
        "steps": len(steps),
        "dropped": dropped,
        "error": last.get("error"),
        "result": last.get("result"),
        "build_ms_samples": build_ms,
        "build_ms_p50": p50,
        "build_ms_p95": p95,
        "build_ms_n": len(build_ms),
        "actions": [str(s.get("action"))[:80] for s in steps],
        "timings": [s.get("timing") for s in steps if s.get("timing")],
    }
    ok = len(steps) >= 10 or (last.get("status") or "").lower() == "completed"
    if (
        dropped
        and (last.get("status") or "").lower() == "failed"
        and "offline" in str(last.get("error") or "").lower()
        and len(steps) < 4
    ):
        ok = False
    report["ok"] = ok
    open(f"{ARTIFACTS}/report.json", "w").write(json.dumps(report, indent=2))
    open(f"{ARTIFACTS}/task.json", "w").write(json.dumps(last, indent=2))
    print(
        "RESULT",
        "OK" if ok else "FAIL",
        f"steps={len(steps)} dropped={dropped} "
        f"build_ms_p50={p50} build_ms_p95={p95} n={len(build_ms)}",
    )
    print(json.dumps(report)[:1200])
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("RESULT FAIL", e)
        sys.exit(1)
