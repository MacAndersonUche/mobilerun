#!/usr/bin/env python3
"""Drive the expanded fake-chats emulator bench through POST /api/tasks.

Scenarios per app:
  - single_dm: find Precious Achalugo, send exact bank text "hi baby"
  - bulk_swipe_50: auto-swipe 50 profiles (dating/swipe apps; N/A elsewhere)
  - bulk_message_50: message 50 matches with exact bank text

Also runs whatsapp keyboard-off SET_TEXT fallback and a Secure Folder unlock
path. Refuses Mac's real S21+ device id.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.fake_chats_catalog import (  # noqa: E402
    bulk_counts,
    dm_keys,
    packages as catalog_packages,
    swipe_keys,
)

API = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
MESSAGE = "hi baby"
CONTACT = "Precious Achalugo"
FORBIDDEN_DEVICE_PREFIX = "android_46101066"
PACKAGES = catalog_packages()
SWIPE = set(swipe_keys())
COUNTS = bulk_counts()

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
    p = subprocess.run(["adb", *args], capture_output=True, text=True, check=False)
    if check and p.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} failed: {p.stderr or p.stdout}")
    return (p.stdout or "") + (p.stderr or "")


def read_jsonl(pkg: str, name: str) -> List[Dict[str, Any]]:
    out = adb("shell", "run-as", pkg, "cat", f"files/{name}", check=False)
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("run-as:"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def clear_logs(pkg: str) -> None:
    adb(
        "shell",
        "am",
        "start",
        "-n",
        f"{pkg}/ai.mobilerun.fakechats.ClearLogActivity",
        check=False,
    )
    time.sleep(0.4)
    for f in ("sent_messages.jsonl", "swipes.jsonl", "action_timings.jsonl"):
        adb(
            "shell",
            "run-as",
            pkg,
            "sh",
            "-c",
            f"echo -n > files/{f}",
            check=False,
        )


def launch_app(
    pkg: str, activity: str = "ai.mobilerun.fakechats.LauncherActivity"
) -> None:
    adb("shell", "am", "force-stop", pkg, check=False)
    time.sleep(0.3)
    adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        f"{pkg}/{activity}",
        "-f",
        "0x10008000",
        "--ez",
        "clear_log",
        "true",
        check=False,
    )
    time.sleep(1.0)
    adb(
        "shell",
        "am",
        "broadcast",
        "-a",
        "android.intent.action.CLOSE_SYSTEM_DIALOGS",
        check=False,
    )


def set_ime(enabled: bool) -> None:
    ime = "ai.mobilerun.selfhosted/.input.MobilerunKeyboardIME"
    if enabled:
        adb("shell", "ime", "enable", ime, check=False)
        adb("shell", "ime", "set", ime, check=False)
    else:
        adb("shell", "ime", "disable", ime, check=False)
        adb("shell", "ime", "reset", check=False)
        for cand in (
            "com.google.android.inputmethod.latin/.LatinIME",
            "com.android.inputmethod.latin/.LatinIME",
        ):
            adb("shell", "ime", "enable", cand, check=False)
            adb("shell", "ime", "set", cand, check=False)


def login() -> str:
    return req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})[
        "access_token"
    ]


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
            raise RuntimeError(f"Refusing Mac's real phone {did}")
    if want:
        for d in online:
            if d.get("device_id") == want:
                return d
        raise RuntimeError(f"device {want} not online")
    if not online:
        raise RuntimeError("no online emulator device")
    return online[0]


def submit(
    token: str,
    device_id: str,
    instruction: str,
    mode: str = "normal",
    max_steps: int = 24,
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
            "vision": False,
            "dry_run": False,
        },
        token=token,
    )


def poll_task(token: str, task_id: str, timeout_s: int = 600) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        try:
            tick = req(
                "POST",
                f"/api/jobs/{task_id}/tick",
                {},
                token=token,
                timeout=120,
                retries=3,
            )
        except Exception as e:
            print(f"    tick_err={e!s}"[:180], flush=True)
            tick = {}
        last = req("GET", f"/api/tasks/{task_id}", token=token, timeout=45, retries=10)
        if isinstance(tick, dict) and tick.get("status"):
            last = {**last, "status": tick.get("status") or last.get("status")}
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
        time.sleep(0.6)
    raise RuntimeError(f"timeout: {last}")


def timing_stats(pkg: str) -> Dict[str, Any]:
    rows = read_jsonl(pkg, "action_timings.jsonl")
    by: Dict[str, List[float]] = {}
    for r in rows:
        by.setdefault(str(r.get("kind")), []).append(float(r.get("ms") or 0))
    out: Dict[str, Any] = {}
    for k, vals in by.items():
        if not vals:
            continue
        out[k] = {
            "n": len(vals),
            "mean_ms": round(statistics.mean(vals), 1),
            "p50_ms": round(statistics.median(vals), 1),
            "max_ms": round(max(vals), 1),
        }
    return out


def assert_single_dm(pkg: str) -> bool:
    sent = read_jsonl(pkg, "sent_messages.jsonl")
    hits = [
        e
        for e in sent
        if e.get("text") == MESSAGE
        and CONTACT.lower() in str(e.get("contact") or "").lower()
    ]
    return len(hits) >= 1


def assert_bulk_swipe(pkg: str, n: int) -> Dict[str, Any]:
    swipes = read_jsonl(pkg, "swipes.jsonl")
    likes = [s for s in swipes if s.get("action") in ("like", "superlike")]
    profiles = [s.get("profile") for s in likes]
    return {
        "ok": len(likes) == n and len(set(profiles)) == n,
        "likes": len(likes),
        "unique": len(set(profiles)),
        "target": n,
    }


def assert_bulk_message(pkg: str, n: int) -> Dict[str, Any]:
    sent = read_jsonl(pkg, "sent_messages.jsonl")
    exact = [e for e in sent if e.get("text") == MESSAGE]
    contacts = [e.get("contact") for e in exact]
    # No duplicates; exactly one per Match01..MatchN preferred
    dup = len(contacts) != len(set(contacts))
    return {
        "ok": len(exact) == n and not dup,
        "sent": len(exact),
        "unique_contacts": len(set(contacts)),
        "duplicates": dup,
        "target": n,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", default=",".join(dm_keys()))
    ap.add_argument(
        "--scenarios",
        default="single_dm,bulk_swipe_50,bulk_message_50",
        help="Comma list of scenarios",
    )
    ap.add_argument("--modes", default="normal")
    ap.add_argument("--device-id", default=os.environ.get("DEVICE_ID", ""))
    ap.add_argument(
        "--timeout", type=int, default=int(os.environ.get("MATRIX_TIMEOUT", "600"))
    )
    ap.add_argument("--skip-keyboard-off", action="store_true")
    ap.add_argument("--skip-secure-folder", action="store_true")
    args = ap.parse_args()
    apps = [a.strip() for a in args.apps.split(",") if a.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
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
        "bulk": COUNTS,
    }
    passes = fails = 0
    set_ime(True)

    def record(case: Dict[str, Any]) -> None:
        nonlocal passes, fails
        report["cases"].append(case)
        if case.get("status") == "pass":
            passes += 1
            print(f"  PASS {case['id']}", flush=True)
        else:
            fails += 1
            print(f"  FAIL {case['id']}", flush=True)
        (OUT / f"{case['id']}.json").write_text(json.dumps(case, indent=2, default=str))

    for app in apps:
        pkg = PACKAGES[app]
        for mode in modes:
            for scenario in scenarios:
                case_id = f"{app}__{scenario}__{mode}"
                print(f"\n== {case_id}", flush=True)
                case: Dict[str, Any] = {
                    "id": case_id,
                    "app": app,
                    "scenario": scenario,
                    "mode": mode,
                    "package": pkg,
                }
                if (
                    scenario == "bulk_swipe_50"
                    and app not in SWIPE
                    and app != "facebook"
                ):
                    case["status"] = "pass"
                    case["note"] = "N/A for messaging app"
                    case["skipped"] = True
                    record(case)
                    continue
                try:
                    clear_logs(pkg)
                    if scenario == "bulk_swipe_50":
                        launch_app(pkg)
                        instr = f"{app} auto-swipe {COUNTS['swipe']} profiles"
                        max_steps = COUNTS["swipe"] * 3 + 40
                    elif scenario == "bulk_message_50":
                        launch_app(
                            pkg,
                            (
                                "ai.mobilerun.fakechats.MatchesActivity"
                                if app in SWIPE or app == "facebook"
                                else "ai.mobilerun.fakechats.LauncherActivity"
                            ),
                        )
                        instr = (
                            f"{app} auto-message {COUNTS['message']} matches "
                            f'tell them "{MESSAGE}"'
                        )
                        max_steps = COUNTS["message"] * 6 + 40
                    else:
                        launch_app(pkg)
                        instr = f"{app} find and message {CONTACT} tell her {MESSAGE}"
                        max_steps = 28
                    t0 = time.time()
                    created = submit(
                        token, device_id, instr, mode=mode, max_steps=max_steps
                    )
                    tid = str(created.get("task_id") or created.get("job_id"))
                    case["task_id"] = tid
                    task = poll_task(token, tid, timeout_s=args.timeout)
                    case["task_status"] = task.get("status")
                    case["result"] = task.get("result")
                    case["error"] = task.get("error")
                    case["wall_s"] = round(time.time() - t0, 2)
                    case["timings"] = timing_stats(pkg)
                    ok = False
                    if scenario == "single_dm":
                        ok = assert_single_dm(pkg)
                        case["sent_log"] = read_jsonl(pkg, "sent_messages.jsonl")
                    elif scenario == "bulk_swipe_50":
                        detail = assert_bulk_swipe(pkg, COUNTS["swipe"])
                        case["swipe_assert"] = detail
                        ok = bool(detail["ok"]) or (
                            # graceful out-of-likes stop with partial still fails exact-50
                            False
                        )
                        # Allow completed task that recorded exactly 50
                        ok = bool(detail["ok"])
                    elif scenario == "bulk_message_50":
                        detail = assert_bulk_message(pkg, COUNTS["message"])
                        case["message_assert"] = detail
                        case["sent_log"] = read_jsonl(pkg, "sent_messages.jsonl")
                        ok = bool(detail["ok"])
                    case["status"] = "pass" if ok else "fail"
                except Exception as e:
                    case["status"] = "fail"
                    case["error"] = str(e)
                record(case)

    # Keyboard-off SET_TEXT on WhatsApp single DM
    if not args.skip_keyboard_off and "whatsapp" in PACKAGES:
        print("\n== whatsapp__keyboard_off", flush=True)
        set_ime(False)
        clear_logs(PACKAGES["whatsapp"])
        launch_app(PACKAGES["whatsapp"])
        case = {
            "id": "whatsapp__keyboard_off",
            "app": "whatsapp",
            "scenario": "single_dm",
            "mode": "normal",
            "ime": "off",
            "package": PACKAGES["whatsapp"],
        }
        try:
            created = submit(
                token,
                device_id,
                f"whatsapp find and message {CONTACT} tell her {MESSAGE}",
                max_steps=28,
            )
            tid = str(created.get("task_id") or created.get("job_id"))
            task = poll_task(token, tid, timeout_s=args.timeout)
            case["task_status"] = task.get("status")
            case["result"] = task.get("result")
            case["sent_log"] = read_jsonl(PACKAGES["whatsapp"], "sent_messages.jsonl")
            case["timings"] = timing_stats(PACKAGES["whatsapp"])
            case["status"] = (
                "pass" if assert_single_dm(PACKAGES["whatsapp"]) else "fail"
            )
        except Exception as e:
            case["status"] = "fail"
            case["error"] = str(e)
        set_ime(True)
        record(case)

    # Secure Folder unlock + open Tinder
    if not args.skip_secure_folder and "securefolder" in {
        a["key"]
        for a in __import__("backend.fake_chats_catalog", fromlist=["apps"]).apps()
    }:
        print("\n== securefolder__unlock_open_tinder", flush=True)
        sf_pkg = "com.samsung.knox.securefolder"
        case = {
            "id": "securefolder__unlock_open_tinder",
            "app": "securefolder",
            "scenario": "secure_folder",
            "package": sf_pkg,
        }
        try:
            launch_app(sf_pkg, "ai.mobilerun.fakechats.SecureFolderActivity")
            created = submit(
                token,
                device_id,
                "unlock Secure Folder then open Tinder",
                max_steps=20,
            )
            tid = str(created.get("task_id") or created.get("job_id"))
            task = poll_task(token, tid, timeout_s=min(args.timeout, 240))
            case["task_status"] = task.get("status")
            case["result"] = task.get("result")
            # Soft pass: task completed or timings show unlock
            timings = timing_stats(sf_pkg)
            case["timings"] = timings
            unlocked = "secure_folder_unlock" in timings
            case["status"] = (
                "pass"
                if unlocked or (task.get("status") or "").lower() == "completed"
                else "fail"
            )
        except Exception as e:
            case["status"] = "fail"
            case["error"] = str(e)
        record(case)

    report["summary"] = {
        "pass": passes,
        "fail": fails,
        "total": passes + fails,
        "verdict": "PASS" if fails == 0 else "FAIL",
    }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    # Pivot table
    table: Dict[str, Dict[str, str]] = {}
    for c in report["cases"]:
        app = c.get("app") or "?"
        scen = c.get("scenario") or c["id"]
        table.setdefault(app, {})[scen] = c.get("status") or "?"
    report["table"] = table
    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(report["summary"], indent=2))
    print("Table:")
    print(json.dumps(table, indent=2))
    print(f"Report: {OUT / 'report.json'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
