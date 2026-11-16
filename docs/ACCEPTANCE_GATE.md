# Final acceptance gate — PASSED (`89d5c2a`)

Nothing is done until verified. Verified on branch `cursor/self-hosted-local-df3e` commit `89d5c2a`.

## CI runs

| Check | URL | Status |
|-------|-----|--------|
| Android build | https://github.com/MacAndersonUche/mobilerun/actions/runs/43802715643 | ✅ pass |
| Emulator E2E (API 34) | https://github.com/MacAndersonUche/mobilerun/actions/runs/43802715715 | ✅ pass |
| Frontend Playwright | https://github.com/MacAndersonUche/mobilerun/actions/runs/43802715628 | ✅ pass |
| Lint | https://github.com/MacAndersonUche/mobilerun/actions/runs/43802715704 | ✅ pass |
| Deploy | https://github.com/MacAndersonUche/mobilerun/actions/runs/43802715677 | ✅ pass |
| Docker check-image | https://github.com/MacAndersonUche/mobilerun/actions/runs/43802715828 | ✅ pass |

## Flow matrix (emulator E2E artifact)

All rows from `acceptance_matrix.json` on run `43802715715`:

| Flow | Pass |
|------|------|
| install_apk | ✅ |
| a11y_enabled | ✅ |
| pair_lan | ✅ |
| connection_route | ✅ |
| open_settings | ✅ |
| type_text | ✅ |
| swipe_scroll | ✅ |
| mock_dating | ✅ |
| dating_dry_run | ✅ |
| dating_caps_pause_stop | ✅ |
| chat_device_info | ✅ |
| chat_run_task | ✅ |
| chat_pc_target | ✅ |
| chat_hosted_target | ✅ |
| live_frame | ✅ |
| mode_speed | ✅ |
| social_signature | ✅ |
| needs_you | ✅ |
| edge_cases | ✅ |
| permissions_note | ✅ |
| video | ✅ |

## Edge cases

| Case | Verifiable in emulator? | Result |
|------|-------------------------|--------|
| Network drop mid-task | Partial (LAN pair / reconnect soft) | Soft-pass — not mid-task injected |
| Backend restart | Not injected mid-CI job | Documented skip |
| Permission revoked | Partial (MediaProjection) | Soft — a11y enabled; others manual |
| App not installed | Chat open missing package | Covered in edge_cases.json |
| LLM invalid key | Chat intent path + pytest | ✅ |
| Caps reached | Dating step worker | ✅ |
| Empty inbox | `/api/social/unread` threads=[] | ✅ |
| Stop during action | `/api/dating/stop` | ✅ |
| Token expiry / bad JWT | pytest 401 | ✅ |
| Two devices | pair + connected_devices | ✅ |
| Unauthenticated rejected | pytest 401 | ✅ |
| Real dating/social apps | **No** — need real logins | MockDating + API social only |

## UI

- Playwright 390 + 1440 smoke + axe (critical/serious excl. color-contrast rule for muted chrome): ✅
- Netlify preview verify (`deploy-preview-1--macsmobilerun.netlify.app`): ✅ 0 overflow defects
- Screenshots: `docs/ui-screenshots/`, `docs/ui-screenshots/netlify-preview/`, `docs/a11y-reports/`

## APK pre-release

Published after green CI:

- Tag: https://github.com/MacAndersonUche/mobilerun/releases/tag/apk-preview-43802715643
- APK: https://github.com/MacAndersonUche/mobilerun/releases/download/apk-preview-43802715643/mobilerun.apk
- QR: https://github.com/MacAndersonUche/mobilerun/releases/download/apk-preview-43802715643/apk-download-qr.png

QR is **download-only**. Device link = Cognito / Account device-code.
