#!/usr/bin/env python3
"""Drive Mac's real phone through the production API for DM dry-run matrix.

Runs WhatsApp / Instagram / Messenger / Telegram / Tinder / Bumble / Hinge
× Normal / Social / Dating modes, all with dry_run=True (fill compose, no Send).

Usage:
  API_URL=https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com \\
  DEVICE_ID=android_46101066-... \\
  E2E_USER=ci-e2e E2E_PASSWORD=... \\
  python3 scripts/real_device_dm_matrix.py [--apps whatsapp,instagram] [--modes normal]

Exit 0 only if every attempted case completed (dry_run done / compose filled).
Cases skipped because the device is offline are reported as SKIP — not PASS.
Never claims success for apps that were not run on a real online device.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

API = os.environ.get(
    "API_URL", "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
).rstrip("/")
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
# Mac's S21+ from the failing job — override with DEVICE_ID env
DEFAULT_DEVICE = "android_46101066-f6d8-4369-b058-0fe822b55361"
DEVICE_ID = os.environ.get("DEVICE_ID", DEFAULT_DEVICE)

APPS = (
    "whatsapp",
    "instagram",
    "messenger",
    "telegram",
    "tinder",
    "bumble",
    "hinge",
)
MODES = ("normal", "social", "dating")

# Prefer named contacts; if missing the agent should open first chat / fail clearly
CONTACTS = {
    "whatsapp": "Precious Achalugo",
    "instagram": "Precious Achalugo",
    "messenger": "Precious Achalugo",
    "telegram": "Precious Achalugo",
    "tinder": "Precious",
    "bumble": "Precious",
    "hinge": "Precious",
}
MESSAGE = "hi baby"

OUT_DIR = Path(
    os.environ.get(
        "MATRIX_OUT",
        f"/tmp/dm_matrix_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )
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
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:800]}") from e


def login() -> str:
    d = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})
    return d["access_token"]


def find_device(token: str, want: str) -> Optional[Dict[str, Any]]:
    devices = req("GET", "/api/devices", token=token) or []
    for d in devices:
        if str(d.get("device_id")) == want:
            return d
    return None


def device_online(d: Optional[Dict[str, Any]]) -> bool:
    if not d:
        return False
    return bool(d.get("connected") or d.get("online") or d.get("status") == "online")


def instruction_for(app: str) -> str:
    contact = CONTACTS.get(app, "Precious Achalugo")
    return f"{app} find and message {contact} tell her {MESSAGE}"


def submit_dry_run(
    token: str, device_id: str, instruction: str, mode: str, max_steps: int = 20
) -> Dict[str, Any]:
    return req(
        "POST",
        "/api/tasks",
        {
            "device_id": device_id,
            "instruction": instruction,
            "max_steps": max_steps,
            "mode": mode,
            "speed_preset": "fast",
            "vision": True,
            "dry_run": True,
        },
        token=token,
    )


def poll_task(token: str, task_id: str, timeout_s: int = 300) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = req("GET", f"/api/tasks/{task_id}", token=token)
        status = (last.get("status") or "").lower()
        steps = last.get("steps") or []
        print(
            f"    {task_id} status={status} steps={len(steps)} "
            f"result={str(last.get('result') or '')[:80]!r} "
            f"error={str(last.get('error') or '')[:80]!r}",
            flush=True,
        )
        if status in ("completed", "failed", "cancelled", "stopped"):
            return last
        time.sleep(3)
    raise RuntimeError(f"Task timeout: {last}")


def case_passed(task: Dict[str, Any]) -> bool:
    """Pass = completed dry_run with compose filled (send skipped) or explicit dry_run done."""
    status = (task.get("status") or "").lower()
    result = str(task.get("result") or "").lower()
    error = str(task.get("error") or "").lower()
    if status != "completed":
        return False
    if "offline" in error or "offline" in result:
        return False
    steps = task.get("steps") or []
    # Prefer explicit dry_run / compose-filled markers
    if "dry_run" in result and ("compose" in result or "send skipped" in result):
        return True
    # Or: typed the message body and never tapped send
    typed_msg = any(
        MESSAGE.lower() in str(s.get("action") or "").lower()
        or (
            "type message" in str(s.get("reason") or "").lower()
            and MESSAGE.lower() in str(s.get("reason") or "").lower()
        )
        for s in steps
    )
    tapped_send = any("tap send" in str(s.get("reason") or "").lower() for s in steps)
    fast = [s.get("fastpath_step") for s in steps if isinstance(s, dict)]
    if "dry_run_stop" in fast or "type_message" in fast:
        return typed_msg and not tapped_send
    return typed_msg and not tapped_send and len(steps) >= 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", default=",".join(APPS))
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--device-id", default=DEVICE_ID)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument(
        "--require-mac-device",
        action="store_true",
        help="Fail if Mac's S21+ id is not online (do not fall back to emu)",
    )
    args = ap.parse_args()
    apps = [a.strip() for a in args.apps.split(",") if a.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = login()
    want = args.device_id
    dev = find_device(token, want)
    online = device_online(dev)

    report: Dict[str, Any] = {
        "api": API,
        "device_id": want,
        "device_online": online,
        "device": {
            k: (dev or {}).get(k)
            for k in ("device_id", "name", "connected", "last_seen", "model")
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
        "real_device": want.startswith("android_46101066")
        or "s21" in str((dev or {}).get("name") or "").lower(),
        "note": (
            "PASS only means dry_run completed on an online device. "
            "SKIP = device offline / not attempted. FAIL = ran and did not fill compose."
        ),
    }

    if not online:
        print(f"DEVICE OFFLINE: {want}", flush=True)
        if args.require_mac_device or want == DEFAULT_DEVICE:
            report["summary"] = {
                "pass": 0,
                "fail": 0,
                "skip": len(apps) * len(modes),
                "verdict": "SKIPPED — Mac device offline; no real-device claims",
            }
            (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report["summary"], indent=2))
            print(f"Wrote {OUT_DIR / 'report.json'}")
            return 2
        print("Continuing would be against policy for Mac S21+ — aborting.", flush=True)
        return 2

    print(f"Online device {want} name={(dev or {}).get('name')}", flush=True)

    passes = fails = skips = 0
    for app in apps:
        for mode in modes:
            case_id = f"{app}__{mode}"
            instr = instruction_for(app)
            print(f"\n== {case_id}: {instr}", flush=True)
            case: Dict[str, Any] = {
                "id": case_id,
                "app": app,
                "mode": mode,
                "instruction": instr,
                "status": "pending",
            }
            try:
                # Re-check online each case
                if not device_online(find_device(token, want)):
                    case["status"] = "skip"
                    case["reason"] = "device went offline"
                    skips += 1
                    report["cases"].append(case)
                    continue
                created = submit_dry_run(token, want, instr, mode)
                task_id = created.get("task_id") or created.get("job_id")
                case["task_id"] = task_id
                task = poll_task(token, str(task_id), timeout_s=args.timeout)
                case["task"] = {
                    "status": task.get("status"),
                    "result": task.get("result"),
                    "error": task.get("error"),
                    "steps": task.get("steps"),
                }
                # Persist steps for debugging
                (OUT_DIR / f"{case_id}.json").write_text(
                    json.dumps(task, indent=2, default=str)
                )
                if case_passed(task):
                    case["status"] = "pass"
                    passes += 1
                    print(f"  PASS {case_id}", flush=True)
                else:
                    case["status"] = "fail"
                    fails += 1
                    print(f"  FAIL {case_id}", flush=True)
            except Exception as e:
                case["status"] = "fail"
                case["error"] = str(e)[:500]
                fails += 1
                print(f"  FAIL {case_id}: {e}", flush=True)
            report["cases"].append(case)
            time.sleep(2)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = {
        "pass": passes,
        "fail": fails,
        "skip": skips,
        "total": passes + fails + skips,
        "verdict": (
            "PASS"
            if fails == 0 and passes > 0
            else ("SKIPPED" if passes == 0 and skips > 0 else "FAIL")
        ),
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\n=== SUMMARY ===")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {OUT_DIR / 'report.json'}")
    return 0 if fails == 0 and passes > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
