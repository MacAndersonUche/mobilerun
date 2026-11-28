#!/usr/bin/env bash
# CI: pair emulator to PROD AWS only (no LAN) and run multi-step cloud agent tasks.
set -euo pipefail

API_URL="${API_URL:-https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com}"
WS_URL="${WS_URL:-wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-/tmp/prod-agent-e2e}"
mkdir -p "$ARTIFACTS_DIR"

export API_URL WS_URL ARTIFACTS_DIR
export E2E_USER="${E2E_USER:-ci-e2e}"
export E2E_PASSWORD="${E2E_PASSWORD:-admin}"
export E2E_INSTRUCTION="${E2E_INSTRUCTION:-open Settings, go to Display, and turn on dark theme}"

echo "== Install APK =="
APK="${APK_PATH:-}"
if [[ -z "$APK" ]]; then
  APK=$(find android-app/build/outputs/apk -name '*.apk' | head -1)
fi
test -n "$APK" && test -f "$APK"
adb install -r -g "$APK" | tee "$ARTIFACTS_DIR/install.txt"
# Enable accessibility service (Mobilerun)
adb shell settings put secure enabled_accessibility_services \
  ai.mobilerun.selfhosted/ai.mobilerun.selfhosted.MobilerunAccessibilityService || true
adb shell settings put secure accessibility_enabled 1 || true
adb shell am start -n ai.mobilerun.selfhosted/.MainActivity || true
sleep 3

echo "== Create AWS-only pair code =="
TOKEN=$(curl -sfS -X POST "$API_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$E2E_USER\",\"password\":\"$E2E_PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
export E2E_TOKEN="$TOKEN"

PAIR=$(curl -sfS -X POST "$API_URL/api/auth/pair/create" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"prod-ci-emu","platform":"android"}')
echo "$PAIR" | tee "$ARTIFACTS_DIR/pair.json"
CODE=$(echo "$PAIR" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('code') or d['token'])")

# AWS-only deep link — no LAN fields
DEEP=$(CODE="$CODE" API_URL="$API_URL" WS_URL="$WS_URL" python3 - <<'PY'
from urllib.parse import urlencode
import os
q = urlencode({
    "c": os.environ["CODE"],
    "cloud": os.environ["API_URL"],
    "cloud_ws": os.environ["WS_URL"],
    "backend": os.environ["API_URL"],
    "ws": os.environ["WS_URL"],
})
print("mobilerun://pair?" + q)
PY
)
echo "DEEP=$DEEP" | tee "$ARTIFACTS_DIR/deep.txt"
adb logcat -c || true
adb shell "am start -a android.intent.action.VIEW -d '$DEEP'"
sleep 15
adb logcat -d 2>/dev/null | grep -iE 'BackendClient|pair|claim|WebSocket' | tee "$ARTIFACTS_DIR/pair_logcat.txt" | tail -40 || true

echo "== Wait for device online on prod =="
DEVICE_ID=$(TOKEN="$TOKEN" API_URL="$API_URL" python3 - <<'PY'
import json, os, time, urllib.request
api = os.environ["API_URL"].rstrip("/")
token = os.environ["TOKEN"]
for i in range(60):
    req = urllib.request.Request(api + "/api/devices", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        devices = json.load(r)
    open(os.environ.get("ARTIFACTS_DIR","/tmp") + "/devices.json","w").write(json.dumps(devices, indent=2))
    for d in devices or []:
        if d.get("connected") or d.get("online") or d.get("status") == "online":
            print(d.get("device_id") or d.get("id"))
            raise SystemExit(0)
    time.sleep(2)
raise SystemExit("no online device")
PY
)
echo "DEVICE_ID=$DEVICE_ID" | tee "$ARTIFACTS_DIR/device_id.txt"

echo "== Dating endpoints (must be 200) =="
for path in /api/dating/status /api/dating/review-queue /api/mode; do
  code=$(curl -sS -o "$ARTIFACTS_DIR/dating_${path##*/}.json" -w '%{http_code}' \
    -H "Authorization: Bearer $TOKEN" "$API_URL$path")
  echo "HTTP $code $path"
  test "$code" = "200"
done

echo "== Run verify_prod_agent_e2e.py =="
export DEVICE_ID
python3 scripts/verify_prod_agent_e2e.py --device-id "$DEVICE_ID" --skip-pair \
  | tee "$ARTIFACTS_DIR/agent_e2e.txt"

# Cleanup CI device
curl -sfS -X DELETE "$API_URL/api/devices/$DEVICE_ID" -H "Authorization: Bearer $TOKEN" || true
echo "PROD_EMU_AGENT_E2E_OK"
