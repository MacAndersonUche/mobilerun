#!/usr/bin/env python3
"""Drive the fake-chats emulator bench through POST /api/tasks.

Installs are done by the shell wrapper. This script:
  - discovers the paired emulator device
  - for each app × mode: clear SentLog, launch inbox, submit a REAL send task
    (dry_run=false) of exact bank text "hi baby" to Precious Achalugo
  - asserts SentLog gained a new outgoing line with exact text
  - also runs a keyboard-off SET_TEXT fallback pass on WhatsApp

Never targets Mac's real S21+ (android_46101066-...).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

API = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
MESSAGE = "hi baby"
CONTACT = "Precious Achalugo"
FORBIDDEN_DEVICE_PREFIX = "android_46101066"

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

PACKAGES = {
    "whatsapp": "com.whatsapp",
    "instagram": "com.instagram.android",
    "messenger": "com.facebook.orca",
    "telegram": "org.telegram.messenger",
    "tinder": "com.tinder",
    "bumble": "com.bumble.app",
    "hinge": "co.hinge.app",
}

OUT = Path(
    os.environ.get(
        "MATRIX_OUT",
        f"/tmp/fake_chats_matrix_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )
)


def req(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = 60,
    retries: int = 8,
) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last: Optional[Exception] = None
    for attempt in range(retries):
        r = urllib.request.Request(
            API + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            last = RuntimeError(f"{method} {path} -> {e.code}: {err[:500]}")
            if e.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(min(20, 2**attempt))
                continue
            raise last from e
        except Exception as e:
            last = e
            if attempt + 1 < retries:
                time.sleep(min(20, 2**attempt))
                continue
            raise
    raise last or RuntimeError("request failed")


def adb(*args: str, check: bool = True) -> str:
    cmd = ["adb", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and p.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} failed: {p.stderr or p.stdout}")
    return (p.stdout or "") + (p.stderr or "")


def clear_sent_log(pkg: str) -> None:
    adb(
        "shell",
        "am",
        "start",
        "-n",
        f"{pkg}/ai.mobilerun.fakechats.ClearLogActivity",
        check=False,
    )
    time.sleep(0.5)
    # Also truncate via run-as when possible
    adb(
        "shell",
        "run-as",
        pkg,
        "sh",
        "-c",
        "echo -n > files/sent_messages.jsonl",
        check=False,
    )


def read_sent_log(pkg: str) -> List[Dict[str, Any]]:
    out = adb(
        "shell",
        "run-as",
        pkg,
        "cat",
        "files/sent_messages.jsonl",
        check=False,
    )
    lines = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("run-as:"):
            continue
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lines


def launch_inbox(pkg: str) -> None:
    # Cold start each case so leftover ConversationActivity (seed "hi baby"
    # bubble + compose focus) cannot poison search→contact→send.
    adb("shell", "am", "force-stop", pkg, check=False)
    time.sleep(0.4)
    adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        f"{pkg}/ai.mobilerun.fakechats.InboxActivity",
        "-f",
        "0x10008000",  # NEW_TASK | CLEAR_TASK
        "--ez",
        "clear_log",
        "true",
    )
    time.sleep(1.2)
    adb("shell", "am", "broadcast", "-a", "android.intent.action.CLOSE_SYSTEM_DIALOGS", check=False)


def set_ime(enabled: bool) -> None:
    """Enable/disable Mobilerun Keyboard as default IME."""
    ime = "ai.mobilerun.selfhosted/.input.MobilerunKeyboardIME"
    if enabled:
        adb("shell", "ime", "enable", ime, check=False)
        adb("shell", "ime", "set", ime, check=False)
    else:
        # Fall back to Latin IME / whatever is available
        adb("shell", "ime", "disable", ime, check=False)
        adb("shell", "ime", "reset", check=False)
        # Prefer AOSP Latin if present
        for cand in (
            "com.google.android.inputmethod.latin/.LatinIME",
            "com.android.inputmethod.latin/.LatinIME",
        ):
            adb("shell", "ime", "enable", cand, check=False)
            adb("shell", "ime", "set", cand, check=False)


def login() -> str:
    d = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})
    return d["access_token"]


def pick_device(token: str, want: Optional[str]) -> Dict[str, Any]:
    devices = req("GET", "/api/devices", token=token) or []
    online = [
        d
        for d in devices
        if d.get("connected") or d.get("online") or d.get("status") == "online"
    ]
    for d in online:
        did = str(d.get("device_id") or "")
        if did.startswith(FORBIDDEN_DEVICE_PREFIX):
            raise RuntimeError(
                f"Refusing to drive Mac's real phone {did} — fake-chats bench only"
            )
    if want:
        for d in online:
            if d.get("device_id") == want:
                return d
        raise RuntimeError(f"device {want} not online")
    if not online:
        raise RuntimeError("no online emulator device")
    return online[0]


def submit_task(
    token: str,
    device_id: str,
    app: str,
    mode: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    instr = f"{app} find and message {CONTACT} tell her {MESSAGE}"
    return req(
        "POST",
        "/api/tasks",
        {
            "device_id": device_id,
            "instruction": instr,
            "max_steps": 24,
            "mode": mode,
            "speed_preset": "fast",
            "vision": False,  # deterministic selectors first
            "dry_run": dry_run,
        },
        token=token,
    )


def poll_task(token: str, task_id: str, timeout_s: int = 240) -> Dict[str, Any]:
    """Poll task; on local backends keep advancing via /api/jobs/{id}/tick."""
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        # Local/dev: keep advancing the job via tick until terminal.
        tick: Dict[str, Any] = {}
        try:
            tick = req(
                "POST",
                f"/api/jobs/{task_id}/tick",
                {},
                token=token,
                timeout=90,
                retries=3,
            )
        except Exception as e:
            print(f"    tick_err={e!s}"[:180], flush=True)
        last = req("GET", f"/api/tasks/{task_id}", token=token, timeout=45, retries=10)
        if isinstance(tick, dict) and tick.get("status"):
            last = {
                **last,
                "status": tick.get("status") or last.get("status"),
            }
            act = tick.get("activity") or {}
            if act.get("steps_detail"):
                last["steps"] = act["steps_detail"]
            if act.get("result"):
                last["result"] = act.get("result")
        status = (last.get("status") or "").lower()
        steps = last.get("steps") or []
        nsteps = len(steps) if isinstance(steps, list) else int(steps or 0)
        print(
            f"    {task_id} status={status} steps={nsteps} "
            f"result={str(last.get('result') or '')[:90]!r}",
            flush=True,
        )
        if status in ("completed", "failed", "cancelled", "stopped", "done"):
            return last
        time.sleep(1.0)
    raise RuntimeError(f"timeout: {last}")


def case_pass_from_log(pkg: str, before: int) -> bool:
    after = read_sent_log(pkg)
    new = [
        e
        for e in after[before:]
        if e.get("text") == MESSAGE
        and CONTACT.lower() in str(e.get("contact") or "").lower()
    ]
    return len(new) >= 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", default=",".join(APPS))
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--device-id", default=os.environ.get("DEVICE_ID", ""))
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--skip-keyboard-off", action="store_true")
    args = ap.parse_args()
    apps = [a.strip() for a in args.apps.split(",") if a.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    OUT.mkdir(parents=True, exist_ok=True)
    token = login()
    dev = pick_device(token, args.device_id or None)
    device_id = str(dev["device_id"])
    print(f"Using device {device_id} name={dev.get('name')}", flush=True)

    report: Dict[str, Any] = {
        "api": API,
        "device_id": device_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
        "message": MESSAGE,
        "contact": CONTACT,
    }
    passes = fails = 0

    set_ime(True)

    for app in apps:
        pkg = PACKAGES[app]
        for mode in modes:
            case_id = f"{app}__{mode}"
            print(f"\n== {case_id}", flush=True)
            clear_sent_log(pkg)
            before = len(read_sent_log(pkg))
            launch_inbox(pkg)
            case: Dict[str, Any] = {
                "id": case_id,
                "app": app,
                "mode": mode,
                "package": pkg,
                "ime": "on",
            }
            try:
                created = submit_task(token, device_id, app, mode, dry_run=False)
                tid = str(created.get("task_id") or created.get("job_id"))
                case["task_id"] = tid
                task = poll_task(token, tid, timeout_s=args.timeout)
                (OUT / f"{case_id}.json").write_text(
                    json.dumps(task, indent=2, default=str)
                )
                case["task_status"] = task.get("status")
                case["result"] = task.get("result")
                case["error"] = task.get("error")
                log_ok = case_pass_from_log(pkg, before)
                case["sent_log_ok"] = log_ok
                case["sent_log"] = read_sent_log(pkg)
                status_ok = (task.get("status") or "").lower() == "completed"
                # Prefer SentLog as ground truth; task may also confirm bubble
                if log_ok and status_ok:
                    case["status"] = "pass"
                    passes += 1
                elif log_ok:
                    case["status"] = "pass"
                    case["note"] = "sent_log ok but task status not completed"
                    passes += 1
                else:
                    case["status"] = "fail"
                    fails += 1
            except Exception as e:
                case["status"] = "fail"
                case["error"] = str(e)
                fails += 1
            print(f"  {case['status'].upper()} {case_id}", flush=True)
            report["cases"].append(case)

    # Keyboard-off SET_TEXT fallback (WhatsApp only)
    if not args.skip_keyboard_off and "whatsapp" in apps:
        case_id = "whatsapp__keyboard_off"
        print(f"\n== {case_id}", flush=True)
        pkg = PACKAGES["whatsapp"]
        set_ime(False)
        clear_sent_log(pkg)
        before = len(read_sent_log(pkg))
        launch_inbox(pkg)
        case = {
            "id": case_id,
            "app": "whatsapp",
            "mode": "normal",
            "package": pkg,
            "ime": "off",
        }
        try:
            created = submit_task(token, device_id, "whatsapp", "normal", dry_run=False)
            tid = str(created.get("task_id") or created.get("job_id"))
            case["task_id"] = tid
            task = poll_task(token, tid, timeout_s=args.timeout)
            (OUT / f"{case_id}.json").write_text(
                json.dumps(task, indent=2, default=str)
            )
            case["task_status"] = task.get("status")
            case["result"] = task.get("result")
            log_ok = case_pass_from_log(pkg, before)
            case["sent_log_ok"] = log_ok
            case["sent_log"] = read_sent_log(pkg)
            if log_ok:
                case["status"] = "pass"
                passes += 1
            else:
                case["status"] = "fail"
                fails += 1
        except Exception as e:
            case["status"] = "fail"
            case["error"] = str(e)
            fails += 1
        print(f"  {case['status'].upper()} {case_id}", flush=True)
        report["cases"].append(case)
        set_ime(True)

    report["summary"] = {
        "pass": passes,
        "fail": fails,
        "total": passes + fails,
        "verdict": "PASS" if fails == 0 and passes > 0 else "FAIL",
    }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(report["summary"], indent=2), flush=True)
    print(f"Report: {OUT / 'report.json'}", flush=True)
    return 0 if fails == 0 and passes > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
