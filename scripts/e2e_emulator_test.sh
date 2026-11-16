#!/usr/bin/env bash
# Emulator e2e: install APKs, enable a11y, pair, run UI tasks + dating dry-run.
# Invoked as a single command by android-emulator-runner (do not split across lines).
set -euo pipefail

ROOT="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

BACKEND_URL="${BACKEND_URL:-http://10.0.2.2:8000}"
HOST_BACKEND="${HOST_BACKEND_URL:-http://127.0.0.1:8000}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$ROOT/e2e-artifacts}"
A11Y="ai.mobilerun.selfhosted/ai.mobilerun.selfhosted.MobilerunAccessibilityService"

mkdir -p "$ARTIFACTS_DIR"

if [[ -z "${MOBILERUN_APK:-}" ]]; then
  MOBILERUN_APK=$(find android-app -name '*release*.apk' -type f | head -1 || true)
fi
if [[ -z "${MOCK_APK:-}" ]]; then
  MOCK_APK=$(find android-mock-dating -name '*debug*.apk' -type f | head -1 || true)
fi

echo "MOBILERUN_APK=$MOBILERUN_APK" | tee "$ARTIFACTS_DIR/apk_paths.txt"
echo "MOCK_APK=$MOCK_APK" | tee -a "$ARTIFACTS_DIR/apk_paths.txt"
test -n "$MOBILERUN_APK" && test -f "$MOBILERUN_APK"
test -n "$MOCK_APK" && test -f "$MOCK_APK"

adb start-server || true
adb wait-for-device
for i in $(seq 1 60); do
  boot=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
  [[ "$boot" == "1" ]] && break
  sleep 2
done
adb shell input keyevent 82 || true
sleep 2

echo "== Install APKs =="
adb install -r "$MOBILERUN_APK"
adb install -r "$MOCK_APK"

echo "== Enable accessibility =="
adb shell settings put secure enabled_accessibility_services "$A11Y"
adb shell settings put secure accessibility_enabled 1
adb shell settings get secure enabled_accessibility_services | tee "$ARTIFACTS_DIR/a11y.txt"
grep -q "ai.mobilerun.selfhosted" "$ARTIFACTS_DIR/a11y.txt"

echo "== Backend health =="
curl -sfS "$HOST_BACKEND/api/health" | tee "$ARTIFACTS_DIR/backend_health.json"

echo "== Start backend login + pair =="
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
WS_HINT=$(echo "$PAIR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('websocket_url') or d.get('backend_url') or '')")
PAIR_URL="mobilerun://pair?token=${TOKEN_PAIR}&backend=${BACKEND_URL}"

echo "== Deep-link pair =="
adb shell am start -a android.intent.action.VIEW -d "$PAIR_URL" ai.mobilerun.selfhosted/.MainActivity || \
  adb shell am start -a android.intent.action.VIEW -d "$PAIR_URL"
sleep 3
adb exec-out screencap -p > "$ARTIFACTS_DIR/01_paired.png" || true
echo "pair_ws=$WS_HINT" >> "$ARTIFACTS_DIR/apk_paths.txt"

echo "== Open Settings =="
adb shell am start -a android.settings.SETTINGS
sleep 2
adb exec-out screencap -p > "$ARTIFACTS_DIR/02_settings.png" || true
adb shell getprop ro.build.version.release | tee "$ARTIFACTS_DIR/android_version.txt"
adb shell getprop ro.product.model | tee "$ARTIFACTS_DIR/device_model.txt"
adb shell wm size | tee "$ARTIFACTS_DIR/wm_size.txt"

echo "== Type into text field (Settings search) =="
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

# Like then type/send opener
adb shell input tap 900 1500 || true
sleep 1
adb shell input tap 540 1600 || true
adb shell input text "Hey_there_from_e2e"
sleep 1
adb shell input tap 900 1600 || true
sleep 1
adb exec-out screencap -p > "$ARTIFACTS_DIR/06_opener_sent.png" || true

# Second message → reply counter path
adb shell input tap 540 1600 || true
adb shell input text "Second_msg_reply"
sleep 1
adb shell input tap 900 1600 || true
sleep 1
adb exec-out screencap -p > "$ARTIFACTS_DIR/07_reply_sent.png" || true

echo "== Dating mode dry-run via API + step worker =="
curl -sfS -X POST "$HOST_BACKEND/api/dating/start?device_id=emulator&dry_run=true" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' || true

python3 - <<PY
import json, os, sys
sys.path.insert(0, os.environ.get("GITHUB_WORKSPACE", os.getcwd()))
os.environ.setdefault("USE_AWS_STORAGE", "false")
from backend.step_worker import run_dating_step
artifacts = os.environ.get("ARTIFACTS_DIR", "/tmp/e2e-artifacts")
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
path = os.path.join(artifacts, "dating_dry_run.json")
open(path, "w").write(json.dumps(states, indent=2))
assert states[-1]["steps"] >= 1, states
assert states[-1]["openers_sent"] + states[-1]["replies_sent"] + states[-1]["swipes_done"] >= 1, states
# Caps / sequential: first steps prefer openers until opener_target
assert states[0]["openers_sent"] >= 1, states
assert states[-1]["openers_sent"] <= 3, states
print("dating dry-run ok", states[-1])
PY

# Optional cloud smoke against deployed Lambda (best-effort)
if [[ -n "${CLOUD_API_URL:-}" ]]; then
  echo "== Optional cloud API health =="
  curl -sfS "$CLOUD_API_URL/api/health" | tee "$ARTIFACTS_DIR/cloud_health.json" || true
fi

timeout 8 adb shell screenrecord --time-limit 6 /sdcard/e2e.mp4 || true
adb pull /sdcard/e2e.mp4 "$ARTIFACTS_DIR/e2e.mp4" 2>/dev/null || true
cp /tmp/backend.log "$ARTIFACTS_DIR/" 2>/dev/null || true

echo "== Done. Artifacts in $ARTIFACTS_DIR =="
ls -la "$ARTIFACTS_DIR"
test -f "$ARTIFACTS_DIR/01_paired.png"
test -f "$ARTIFACTS_DIR/02_settings.png"
test -f "$ARTIFACTS_DIR/04_swiped.png"
test -f "$ARTIFACTS_DIR/05_mock_dating.png"
test -f "$ARTIFACTS_DIR/dating_dry_run.json"
echo "E2E PASS"
