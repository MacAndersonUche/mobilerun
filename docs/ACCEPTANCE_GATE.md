# Final acceptance gate

Nothing is done until verified. This document is updated as CI and local checks complete.

## CI runs

| Check | URL | Status |
|-------|-----|--------|
| Android build | _(filled after green)_ | |
| Emulator E2E | _(filled after green)_ | |
| Frontend Playwright | _(filled after green)_ | |
| Deploy / Netlify | _(filled after green)_ | |

## Flow matrix (emulator + API)

| Flow | How verified | Pass? |
|------|--------------|-------|
| Install APK | emulator `adb install` | |
| Login/link | pair deep-link + Cognito device-code path in unit tests | |
| Permissions onboarding | a11y enabled in CI; MediaProjection/overlay noted as manual | |
| LAN + cloud fallback | dual WS pair URL; route assert | |
| Normal tasks | Settings open/type/swipe + chat device info | |
| Live view frames | inject-frame + UI WS | |
| Chat PC / hosted | `/api/chat` targets | |
| Dating mock | MockDating APK + dry-run step worker + caps/pause/stop | |
| Social + Needs-you | signature on/off, draft escalate, approve/edit/reject | |
| Speed presets | `/api/mode` fast/balanced/careful | |

## Edge cases

| Case | Verifiable in emulator? | Result |
|------|-------------------------|--------|
| Network drop mid-task | Partial (LAN pair / reconnect soft) | |
| Backend restart | Not injected mid-CI job | |
| Permission revoked | Partial (cannot flaky-revoke MediaProjection) | |
| App not installed | Chat open missing package | |
| LLM invalid key | Chat intent path + pytest | |
| Caps reached | Dating step worker | |
| Empty inbox | `/api/social/unread` threads=[] | |
| Stop during action | `/api/dating/stop` | |
| Token expiry / bad JWT | pytest 401 | |
| Two devices | pair + connected_devices | |
| Unauthenticated rejected | pytest 401 | |
| Real dating/social apps | **No** — need real logins; mock + API only | |

## Artifacts

- Emulator: CI artifact `emulator-e2e-<run_id>` (screenshots, `e2e.mp4`, `acceptance_matrix.json`)
- UI: `docs/ui-screenshots/` + Netlify preview shots under `docs/ui-screenshots/netlify-preview/`
- a11y: `docs/a11y-reports/`

## APK pre-release

Published **only after** android-build + emulator-e2e + playwright (+ Netlify visual) pass.
