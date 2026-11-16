#!/usr/bin/env bash
# Emulator e2e: install APKs, enable a11y, pair, run UI tasks + dating dry-run.
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://10.0.2.2:8000}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-/tmp/e2e-artifacts}"
MOBILERUN_APK="${MOBILERUN_APK:-}"
MOCK_APK="${MOCK_APK:-}"
A11Y="ai.mobilerun.selfhosted/ai.mobilerun.selfhosted.MobilerunAccessibilityService"

mkdir -p "$ARTIFACTS_DIR"
adb wait-for-device
adb shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'
sleep 3

echo "== Install APKs =="
adb install -r "$MOBILERUN_APK"
adb install -r "$MOCK_APK"

echo "== Enable accessibility =="
adb shell settings put secure enabled_accessibility_services "$A11Y"
adb shell settings put secure accessibility_enabled 1
adb shell settings get secure enabled_accessibility_services | tee "$ARTIFACTS_DIR/a11y.txt"

echo "== Start backend login + pair =="
# Backend must already be listening on host; emulator reaches host via 10.0.2.2
HOST_BACKEND="${HOST_BACKEND_URL:-http://127.0.0.1:8000}"
export ALLOW_UNAUTHENTICATED=true
TOKEN=$(curl -sfS -X POST "$HOST_BACKEND/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" || true)

PAIR_JSON=$(curl -sfS -X POST "$HOST_BACKEND/api/devices/pair" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"emulator","platform":"android"}' || curl -sfS -X POST "$HOST_BACKEND/api/devices/pair" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"emulator","platform":"android"}')
echo "$PAIR_JSON" | tee "$ARTIFACTS_DIR/pair.json"
TOKEN_PAIR=$(echo "$PAIR_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
PAIR_URL="mobilerun://pair?token=${TOKEN_PAIR}&backend=${BACKEND_URL}"

echo "== Deep-link pair =="
adb shell am start -a android.intent.action.VIEW -d "$PAIR_URL" ai.mobilerun.selfhosted/.MainActivity || \
  adb shell am start -a android.intent.action.VIEW -d "$PAIR_URL"
sleep 2
adb exec-out screencap -p > "$ARTIFACTS_DIR/01_paired.png" || true

echo "== Open Settings =="
adb shell am start -a android.settings.SETTINGS
sleep 2
adb exec-out screencap -p > "$ARTIFACTS_DIR/02_settings.png" || true
# Device info
adb shell getprop ro.build.version.release | tee "$ARTIFACTS_DIR/android_version.txt"
adb shell getprop ro.product.model | tee "$ARTIFACTS_DIR/device_model.txt"
adb shell wm size | tee "$ARTIFACTS_DIR/wm_size.txt"

echo "== Type into text field (Settings search) =="
# Open search if available; otherwise type via input
adb shell input keyevent KEYCODE_SEARCH || true
sleep 1
adb shell input text "Display"
sleep 1
adb exec-out screencap -p > "$ARTIFACTS_DIR/03_typed.png" || true

echo "== Swipe =="
adb shell input swipe 500 1400 500 400 400
sleep 1
adb exec-out screencap -p > "$ARTIFACTS_DIR/04_swiped.png" || true

echo "== Folder-like flow: home + mock dating =="
adb shell input keyevent KEYCODE_HOME
sleep 1
adb shell monkey -p ai.mobilerun.mockdating -c android.intent.category.LAUNCHER 1
sleep 2
adb exec-out screencap -p > "$ARTIFACTS_DIR/05_mock_dating.png" || true

# Like (swipe/right button via tap approx on Like)
adb shell input tap 800 900 || true
sleep 1
adb shell input tap 540 1100 || true  # focus input
adb shell input text "Hey_there_from_e2e"
sleep 1
adb shell input tap 540 1250 || true  # send
sleep 1
adb exec-out screencap -p > "$ARTIFACTS_DIR/06_opener_sent.png" || true

echo "== Dating mode dry-run via API =="
curl -sfS -X POST "$HOST_BACKEND/api/dating/start?device_id=emulator&dry_run=true" \
  -H "Authorization: Bearer ${TOKEN}" || \
curl -sfS -X POST "$HOST_BACKEND/api/dating/start?device_id=emulator&dry_run=true" \
  -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' || true
# Run step worker locally once
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
os.environ.setdefault("USE_AWS_STORAGE", "false")
from step_worker import run_dating_step
job = {
  "job_id": "e2e_dating",
  "kind": "dating",
  "status": "running",
  "device_id": "emulator",
  "dry_run": True,
  "caps": {"opener_target": 3, "global_message_max": 10, "swipe_cap": 5, "reply_cap": 5},
  "state": {"openers_sent": 0, "replies_sent": 0, "swipes_done": 0, "steps": 0},
}
states = []
for _ in range(5):
    job["status"] = "running"
    job = run_dating_step(job)
    states.append(dict(job["state"]))
    if job.get("status") == "completed":
        break
open("/tmp/e2e-artifacts/dating_dry_run.json","w").write(__import__("json").dumps(states, indent=2))
assert states[-1]["steps"] >= 1
assert states[-1]["openers_sent"] + states[-1]["replies_sent"] + states[-1]["swipes_done"] >= 1
print("dating dry-run ok", states[-1])
PY

# Screenrecord short clip (best-effort)
timeout 8 adb shell screenrecord --time-limit 6 /sdcard/e2e.mp4 || true
adb pull /sdcard/e2e.mp4 "$ARTIFACTS_DIR/e2e.mp4" 2>/dev/null || true

echo "== Done. Artifacts in $ARTIFACTS_DIR =="
ls -la "$ARTIFACTS_DIR"
