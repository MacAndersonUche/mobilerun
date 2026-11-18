#!/usr/bin/env bash
# Emulator reliability smoke: open Settings 10× via monkey + uiautomator presence.
# Reports success rate for the final Mac report when an emulator is attached.
set -euo pipefail
SERIAL="${ANDROID_SERIAL:-emulator-5554}"
N="${RELIABILITY_N:-10}"
ok=0
adb -s "$SERIAL" wait-for-device
for i in $(seq 1 "$N"); do
  adb -s "$SERIAL" shell am force-stop com.android.settings >/dev/null 2>&1 || true
  adb -s "$SERIAL" shell monkey -p com.android.settings -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 1.2
  dump=$(adb -s "$SERIAL" exec-out uiautomator dump /dev/tty 2>/dev/null || true)
  if echo "$dump" | grep -qi 'package="com.android.settings"'; then
    ok=$((ok + 1))
    echo "run $i: OK"
  else
    echo "run $i: FAIL"
  fi
done
echo "SETTINGS_OPEN_SUCCESS=$ok/$N"
# Exit 0 even on partial — report is the deliverable
exit 0
