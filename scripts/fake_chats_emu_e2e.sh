#!/usr/bin/env bash
# Fake-chats emulator bench: install Mobilerun + 7 fake chat APKs, enable a11y+IME,
# pair to local backend, run the send matrix. Never targets Mac's real phone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-/tmp/fake-chats-e2e}"
mkdir -p "$ARTIFACTS_DIR"
HOST_BACKEND="${HOST_BACKEND_URL:-http://127.0.0.1:8000}"
export API_URL="$HOST_BACKEND"
export MATRIX_OUT="${MATRIX_OUT:-$ARTIFACTS_DIR/matrix}"

MOBILERUN_APK="${MOBILERUN_APK:-}"
if [[ -z "$MOBILERUN_APK" ]]; then
  MOBILERUN_APK=$(ls -1 "$ROOT"/android-app/build/outputs/apk/release/*.apk 2>/dev/null | head -1 || true)
fi
if [[ -z "$MOBILERUN_APK" || ! -f "$MOBILERUN_APK" ]]; then
  echo "Building Mobilerun release APK..."
  (cd "$ROOT/android-app" && ./gradlew assembleRelease --no-daemon)
  MOBILERUN_APK=$(ls -1 "$ROOT"/android-app/build/outputs/apk/release/*.apk | head -1)
fi
echo "MOBILERUN_APK=$MOBILERUN_APK" | tee "$ARTIFACTS_DIR/apk_paths.txt"

echo "== Build fake-chats flavors =="
(cd "$ROOT/test-apps/fake-chats" && python3 scripts/generate_from_catalog.py && ./gradlew assembleDebug --no-daemon)
FAKE_DIR="$ROOT/test-apps/fake-chats/app/build/outputs/apk"

echo "== Install APKs =="
adb install -r "$MOBILERUN_APK"
# Install every product-flavor APK from catalog (skip missing)
while IFS= read -r apk; do
  echo "install $apk"
  adb install -r "$apk" || true
done < <(find "$FAKE_DIR" -path '*/debug/*.apk' | sort)
export FAKE_CHATS_FAST="${FAKE_CHATS_FAST:-1}"
export MATRIX_TIMEOUT="${MATRIX_TIMEOUT:-900}"

A11Y="ai.mobilerun.selfhosted/ai.mobilerun.selfhosted.MobilerunAccessibilityService"
IME="ai.mobilerun.selfhosted/.input.MobilerunKeyboardIME"
echo "== Enable accessibility + Mobilerun Keyboard =="
adb shell settings put secure enabled_accessibility_services "$A11Y"
adb shell settings put secure accessibility_enabled 1
# Grant WRITE_SECURE_SETTINGS so ensure_ime can switch without picker
adb shell pm grant ai.mobilerun.selfhosted android.permission.WRITE_SECURE_SETTINGS || true
adb shell ime enable "$IME" || true
adb shell ime set "$IME" || true
# Also put into enabled_input_methods list
EXISTING=$(adb shell settings get secure enabled_input_methods | tr -d '\r')
if [[ "$EXISTING" != *"$IME"* ]]; then
  if [[ -z "$EXISTING" || "$EXISTING" == "null" ]]; then
    adb shell settings put secure enabled_input_methods "$IME"
  else
    adb shell settings put secure enabled_input_methods "${EXISTING}:${IME}"
  fi
fi
adb shell settings put secure default_input_method "$IME" || true

echo "== Start local backend if needed =="
if ! curl -sfS "$HOST_BACKEND/api/health" >/dev/null 2>&1; then
  echo "Backend not up at $HOST_BACKEND — start with ALLOW_UNAUTHENTICATED=true"
  exit 1
fi
# Dismiss any leftover ANR / system dialogs before pairing
adb shell input keyevent KEYCODE_BACK || true
adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS || true

echo "== Pair emulator (short-code, LAN via adb reverse) =="
adb reverse tcp:8000 tcp:8000 || true
TOKEN=$(curl -sfS -X POST "$HOST_BACKEND/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${E2E_USER:-ci-e2e}\",\"password\":\"${E2E_PASSWORD:-admin}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
export E2E_TOKEN="$TOKEN"
PAIR=$(curl -sfS -X POST "$HOST_BACKEND/api/auth/pair/create" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"fake-chats-emu","platform":"android"}')
CODE=$(echo "$PAIR" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code') or d['token'])")
EMU_HTTP="http://127.0.0.1:8000"
EMU_WS="ws://127.0.0.1:8000/api/devices/connect"
PAIR_URL=$(CODE="$CODE" EMU_HTTP="$EMU_HTTP" EMU_WS="$EMU_WS" python3 - <<'PY'
from urllib.parse import urlencode
import os
print("mobilerun://pair?" + urlencode({
    "c": os.environ["CODE"],
    "cloud": os.environ["EMU_HTTP"],
    "cloud_ws": os.environ["EMU_WS"],
    "lan": os.environ["EMU_HTTP"],
    "lan_ws": os.environ["EMU_WS"],
}))
PY
)
# Pairing can race right after install — retry deep-link + kick ConnectionService.
DEVICE_ID=""
adb shell am start -n ai.mobilerun.selfhosted/.MainActivity || true
sleep 2
for attempt in 1 2 3; do
  echo "Pair attempt $attempt"
  adb shell "am start -a android.intent.action.VIEW -d '$PAIR_URL'" || true
  adb shell am startservice -n ai.mobilerun.selfhosted/.ConnectionService \
    -a ai.mobilerun.selfhosted.CONN_START || true
  sleep 6
  ONLINE=$(TOKEN="$TOKEN" HOST="$HOST_BACKEND" python3 - <<'PY'
import json, os, urllib.request
host=os.environ["HOST"]; token=os.environ["TOKEN"]
forbid="android_46101066"
req=urllib.request.Request(host+"/api/devices", headers={"Authorization":f"Bearer {token}"})
try:
    devices=json.load(urllib.request.urlopen(req, timeout=10))
except Exception:
    devices=[]
for d in devices or []:
    did=str(d.get("device_id") or "")
    if did.startswith(forbid):
        raise SystemExit("refusing Mac real phone in fake-chats bench")
    if d.get("connected") or d.get("online"):
        print(did); raise SystemExit
print("")
PY
  )
  if [[ -n "$ONLINE" ]]; then
    DEVICE_ID="$ONLINE"
    break
  fi
done
if [[ -z "${DEVICE_ID:-}" ]]; then
  # Final longer poll
  DEVICE_ID=$(TOKEN="$TOKEN" HOST="$HOST_BACKEND" python3 - <<'PY'
import json, os, time, urllib.request
host=os.environ["HOST"]; token=os.environ["TOKEN"]
forbid="android_46101066"
for _ in range(60):
    req=urllib.request.Request(host+"/api/devices", headers={"Authorization":f"Bearer {token}"})
    try:
        devices=json.load(urllib.request.urlopen(req, timeout=10))
    except Exception:
        devices=[]
    for d in devices or []:
        did=str(d.get("device_id") or "")
        if did.startswith(forbid):
            raise SystemExit("refusing Mac real phone in fake-chats bench")
        if d.get("connected") or d.get("online"):
            print(did); raise SystemExit
    time.sleep(1)
raise SystemExit("emulator did not come online")
PY
  )
fi
echo "DEVICE_ID=$DEVICE_ID" | tee -a "$ARTIFACTS_DIR/apk_paths.txt"
export DEVICE_ID

echo "== Run fake-chats matrix =="
python3 "$ROOT/scripts/fake_chats_emu_matrix.py" \
  --device-id "$DEVICE_ID" \
  --timeout "${MATRIX_TIMEOUT:-300}" \
  | tee "$ARTIFACTS_DIR/matrix_console.log"

cp -a "$MATRIX_OUT"/. "$ARTIFACTS_DIR/" 2>/dev/null || true
python3 - <<'PY'
import json, os, sys
p=os.path.join(os.environ["ARTIFACTS_DIR"], "report.json")
# matrix writes to MATRIX_OUT
alt=os.path.join(os.environ.get("MATRIX_OUT",""), "report.json")
path=alt if os.path.isfile(alt) else p
d=json.load(open(path))
print("VERDICT", d["summary"]["verdict"])
sys.exit(0 if d["summary"]["verdict"]=="PASS" else 1)
PY
