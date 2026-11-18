# Samsung Secure Folder (One UI)

MobileRun’s AccessibilityService runs in the **main** Android user. Secure Folder
apps run in a Knox work profile (often user `150`).

## What we do
1. If `open_app` cannot resolve the package in the main profile, launch
   `com.samsung.knox.securefolder`.
2. Wait up to ~60s for fingerprint / PIN unlock (detect unlock UI via tree text).
3. Tap the app icon inside the Folder grid when visible, or retry PackageManager.
4. Mark the RPC with `a11y_cross_user_limited=true` so the cloud agent **forces
   screenshot + vision** on the next step.

## Limit (One UI)
A main-profile AccessibilityService often **cannot** see or click Secure Folder
windows. When trees come back empty/sparse after a Folder launch, MobileRun falls
back to **screenshot + vision + gesture dispatch** (`dispatchGesture`), which
still works at the display level. If both tree and screenshot fail, the task
surfaces a clear Secure Folder unlock / cross-user error — install MobileRun
*inside* Secure Folder only if you need full a11y there (not required for the
vision path).
