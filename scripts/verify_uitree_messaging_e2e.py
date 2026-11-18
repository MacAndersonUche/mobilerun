#!/usr/bin/env python3
"""Real-APK emulator vs prod: messaging flow must complete with sent bubble.

Seeds SMS compose, runs until the cloud task status is completed/failed
(no step-count early exit), confirms the sent marker in a UI dump + screenshot,
and prints build_ms p50/p95 plus wall-clock task time.
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
SENT_MARKER = "hello from macai uitree recovery test"
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


def adb_out(*args: str) -> str:
    return subprocess.run(
        ["adb", "-s", SERIAL, *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def ensure_a11y_bound() -> None:
    """Ensure accessibility is enabled without tearing down a live WS session."""
    adb("shell", "dumpsys", "deviceidle", "whitelist", "+ai.mobilerun.selfhosted")
    dump = adb_out("shell", "dumpsys", "accessibility")
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
    adb("shell", "am", "start", "-n", "ai.mobilerun.selfhosted/.MainActivity")
    time.sleep(3)


def seed_contact() -> None:
    """Seed contact + leave SMS compose open with draft text."""
    ensure_a11y_bound()
    rid = "1"
    try:
        out = adb_out(
            "shell",
            "content",
            "query",
            "--uri",
            "content://com.android.contacts/raw_contacts",
            "--projection",
            "_id",
        )
        ids = []
        for line in out.splitlines():
            if "_id=" in line:
                try:
                    ids.append(int(line.split("_id=")[1].split(",")[0].split(" ")[0]))
                except ValueError:
                    pass
        if ids:
            rid = str(max(ids) + 1)
    except Exception:
        rid = "1"
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
        f"raw_contact_id:i:{rid}",
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
        f"raw_contact_id:i:{rid}",
        "--bind",
        "mimetype:s:vnd.android.cursor.item/phone_v2",
        "--bind",
        "data1:s:5550100",
        "--bind",
        "data2:i:2",
    )
    adb(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.SENDTO",
        "-d",
        "sms:5550100",
        "--es",
        "sms_body",
        SENT_MARKER,
    )
    time.sleep(2.0)


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


def wait_device_online(tok: str, seconds: float = 60.0) -> None:
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        try:
            devices = req("GET", "/api/devices", token=tok, retries=3)
            for d in devices if isinstance(devices, list) else []:
                if d.get("device_id") == DEVICE_ID:
                    last = d
                    if (
                        d.get("connected")
                        or d.get("online")
                        or d.get("status") == "online"
                    ):
                        return
        except RuntimeError as e:
            last = {"error": str(e)}
        adb("shell", "am", "start", "-n", "ai.mobilerun.selfhosted/.MainActivity")
        time.sleep(3)
    raise RuntimeError(f"Device {DEVICE_ID} still offline after seed: {last}")


def capture_sent_evidence() -> Dict[str, Any]:
    """Screenshot + uiautomator dump; confirm SENT_MARKER is on screen."""
    shot = f"{ARTIFACTS}/sent_bubble.png"
    dump_path = f"{ARTIFACTS}/ui_dump.xml"
    adb("shell", "screencap", "-p", "/sdcard/sent_bubble.png")
    adb("pull", "/sdcard/sent_bubble.png", shot)
    adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml")
    adb("pull", "/sdcard/uidump.xml", dump_path)
    xml = ""
    try:
        xml = open(dump_path, encoding="utf-8", errors="replace").read()
    except OSError:
        xml = adb_out("shell", "cat", "/sdcard/uidump.xml")
    marker_present = SENT_MARKER.lower() in xml.lower()
    # Prefer evidence the text is not only in an EditText (draft)
    in_edit = False
    if marker_present:
        low = xml.lower()
        # Rough: if marker appears inside a node whose class is EditText
        idx = low.find(SENT_MARKER.lower())
        window = low[max(0, idx - 400) : idx + 200]
        in_edit = "edittext" in window or 'password="true"' in window
    shot_ok = os.path.isfile(shot) and os.path.getsize(shot) > 1000
    return {
        "screenshot": shot if shot_ok else None,
        "ui_dump": dump_path if os.path.isfile(dump_path) else None,
        "marker_present": marker_present,
        "marker_in_edit_only": in_edit and marker_present,
        "sent_confirmed": marker_present and not in_edit,
    }


def main() -> int:
    if not DEVICE_ID:
        raise RuntimeError("DEVICE_ID required")
    tok = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})[
        "access_token"
    ]
    seed_contact()
    wait_device_online(tok, seconds=90.0)
    instr = os.environ.get(
        "E2E_INSTRUCTION",
        "You are already in Messages SMS compose to 5550100 with draft text "
        f"'{SENT_MARKER}'. Do NOT press Home, Back, or open_app. "
        "Tap the Send / SMS button now. After sending, wait until the same text "
        "appears as a sent bubble in the conversation (not in the compose box). "
        "When the sent bubble is visible, call done. If Send is missing, tap the "
        "message field, re-type the marker text, then Send. Keep going until the "
        "sent bubble is confirmed — never stop only because contacts look empty.",
    )
    print("START", instr, flush=True)
    t0 = time.time()
    task = req(
        "POST",
        "/api/tasks",
        {
            "device_id": DEVICE_ID,
            "instruction": instr,
            "max_steps": 40,
            "mode": "normal",
            "speed_preset": "fast",
        },
        token=tok,
    )
    tid = task["task_id"]
    print("task", tid, flush=True)

    dropped = False
    last: Dict[str, Any] = {}
    # ~15 min wall under AGENT_TASK_TIMEOUT_S=900
    for i in range(450):
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
        # No step-count early exit — wait for terminal status only
        if st in ("completed", "failed", "stopped", "cancelled", "done"):
            break
        time.sleep(2)

    elapsed_s = round(time.time() - t0, 1)
    created = last.get("created_at")
    completed = last.get("completed_at")
    if isinstance(created, (int, float)) and isinstance(completed, (int, float)):
        elapsed_s = round(float(completed) - float(created), 1)

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
    st = (last.get("status") or "").lower()
    result_blob = " ".join(
        [
            str(last.get("result") or ""),
            str(last.get("error") or ""),
            " ".join(str(s.get("action") or "") for s in steps),
        ]
    ).lower()

    # Bring the 5550100 thread forward WITHOUT injecting draft text into EditText
    adb(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        "sms:5550100",
    )
    time.sleep(2.0)
    evidence = capture_sent_evidence()

    status_done = st in ("completed", "done")
    result_claims_sent = (
        "sent message visible" in result_blob
        or "message appears sent" in result_blob
        or (
            SENT_MARKER.lower() in result_blob
            and ("done:" in result_blob or status_done)
        )
    )
    ok = bool(
        status_done
        and evidence.get("sent_confirmed")
        and (result_claims_sent or evidence.get("marker_present"))
    )

    report = {
        "task_id": tid,
        "status": last.get("status"),
        "steps": len(steps),
        "dropped": dropped,
        "elapsed_s": elapsed_s,
        "error": last.get("error"),
        "result": last.get("result"),
        "build_ms_samples": build_ms,
        "build_ms_p50": p50,
        "build_ms_p95": p95,
        "build_ms_n": len(build_ms),
        "actions": [str(s.get("action"))[:80] for s in steps],
        "timings": [s.get("timing") for s in steps if s.get("timing")],
        "evidence": evidence,
        "ok": ok,
    }
    open(f"{ARTIFACTS}/report.json", "w").write(json.dumps(report, indent=2))
    open(f"{ARTIFACTS}/task.json", "w").write(json.dumps(last, indent=2))
    print(
        "RESULT",
        "OK" if ok else "FAIL",
        f"status={last.get('status')} steps={len(steps)} dropped={dropped} "
        f"elapsed_s={elapsed_s} sent={evidence.get('sent_confirmed')} "
        f"shot={evidence.get('screenshot')} "
        f"build_ms_p50={p50} build_ms_p95={p95} n={len(build_ms)}",
    )
    print(json.dumps(report)[:1600])
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("RESULT FAIL", e)
        sys.exit(1)
