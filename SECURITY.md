# Security Overview

## Authentication & Authorization

### AWS Cognito (preferred)

Mac’s hosted UI (Netlify) and APK share **one Cognito user pool**:

- **Email + password** and **Google** via Cognito Hosted UI
- Web: PKCE authorization code → `/auth/callback` stores the ID token
- APK: **device-code** flow (phone shows a code → approve on Account page) or Custom Tabs/AppAuth PKCE
- Backend validates Cognito JWTs (RS256 / JWKS) when `COGNITO_USER_POOL_ID` is set
- Local `mobilerun serve` can use the same Cognito pool **or** the HS256 fallback (`/api/auth/login`)

**Environment variables:**

```bash
COGNITO_REGION=eu-west-2
COGNITO_USER_POOL_ID=eu-west-2_xxxxxxxx
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
ALLOWED_USER_EMAILS=macandersonuche@yahoo.com,admin

# Frontend (Netlify build)
VITE_COGNITO_DOMAIN=your-domain.auth.eu-west-2.amazoncognito.com
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_REDIRECT_URI=https://deploy-preview-N--macsmobilerun.netlify.app/auth/callback
```

**Authorization:** only emails listed in `ALLOWED_USER_EMAILS` may control this instance. Devices auto-register to the signed-in account (`owner` on the device record). Listing and control are scoped to that owner — only Mac’s account sees Mac’s phones.

### Local JWT fallback

**Backend API Endpoints:**
- REST endpoints require `Authorization: Bearer <token>` (unless `ALLOW_UNAUTHENTICATED=true`)
- Local tokens from `create_access_token()` in `backend/auth.py` (HS256, 7-day expiry)
- Cognito ID/access tokens (RS256) accepted when the pool is configured

**Environment Variables:**
- `JWT_SECRET`: required in production for local tokens
- `ALLOW_UNAUTHENTICATED`: `false` in production

**⚠️ CRITICAL: Production Deployment**
```bash
export JWT_SECRET=$(openssl rand -hex 32)
export ALLOW_UNAUTHENTICATED=false
export COGNITO_USER_POOL_ID=...
export COGNITO_APP_CLIENT_ID=...
export ALLOWED_USER_EMAILS=macandersonuche@yahoo.com
```

### Device linking (Cognito — no pairing QR)

Architecture: **hosted UI** = management (dashboard, live view, chat, modes, Needs you). **APK** = wireless executor on the phone.

1. **QR codes are download-only** — `/api/releases/latest` returns a QR pointing at the GitHub release APK URL (shown on Devices + Settings + README). Never used for pairing.
2. **APK → Sign in & link phone** → 6-character device code → Mac approves on Account while signed in → phone gets `session_token` + JWT and appears under his account.
3. **Cognito Hosted UI / Custom Tabs:** same user pool; APK sends `auth_token` on WebSocket register and auto-binds to the account.
4. **Permissions onboarding (APK):** Accessibility (Android 13+ “Allow restricted settings” for sideloads), notifications, MediaProjection, battery unrestricted, overlay, query packages, foreground connection service. Checklist re-checks on resume and reports `permission_status` to the hosted Devices page.

### WebSocket Authentication

**Device Connection (`/api/devices/connect`):**
- Accepts `auth_token` (Cognito/local JWT) or `session_token` (reconnect)
- JWT / device-code path auto-registers the device to the account
- Foreground `ConnectionService` keeps the socket alive in background
- WebSocket remains authenticated for the session lifetime

## Secrets Management

### What is NOT in APK or Frontend

✅ **Verified Clean:**
- ❌ No API keys (OpenAI, Anthropic, Gemini, xAI/Grok, AWS)
- ❌ No JWT secrets / Cognito client secrets (public PKCE client only)
- ❌ No AWS credentials
- ❌ No hardcoded passwords

### Backend URL Configuration

**Frontend (React):**
- Backend URL in `localStorage` / Netlify `VITE_*` env
- Cognito domain + client id are public (PKCE); no client secret

**Android App:**
- Backend URL from device-code defaults, prefs, or QR
- Tokens in SharedPreferences after sign-in
- No hardcoded Cognito secrets

### Environment Variables (.env)

```bash
JWT_SECRET=your-secure-random-secret-here
ALLOW_UNAUTHENTICATED=false
BACKEND_URL=https://your-api.amazonaws.com
COGNITO_REGION=eu-west-2
COGNITO_USER_POOL_ID=...
COGNITO_APP_CLIENT_ID=...
ALLOWED_USER_EMAILS=macandersonuche@yahoo.com
FRONTEND_URL=https://macsmobilerun.netlify.app
```

**⚠️ NEVER commit `.env` files** — already in `.gitignore`

## API Endpoint Security

### Public Endpoints (No Auth Required)

- `GET /api/health`
- `GET /api/releases/latest`
- `POST /api/auth/login` (local fallback)
- `POST /api/auth/device/code` (starts link; no secrets returned)
- `POST /api/auth/device/token` (poll; returns tokens only after approve)

### Protected Endpoints (Auth Required)

- `/api/devices`, `/api/tasks`, `/api/config`, dating/social/needs-you/chat
- `POST /api/auth/device/approve` — must be signed in as an allowed user

## Threat Model

### Protected Against

✅ Unauthorized API access (JWT / Cognito)  
✅ Cross-account device control (`owner` scoping + `ALLOWED_USER_EMAILS`)  
✅ Pairing token replay (one-time + expiry)  
✅ Credential exposure (no secrets in APK/frontend)

### Not Yet Implemented

⚠️ Rate limiting on auth/device-code endpoints  
⚠️ Automated Cognito secret / JWT rotation  
⚠️ Device revocation UI (clear session + owner unlink)

## Security Checklist for Production

- [ ] Create Cognito user pool (email+password + Google IdP)
- [ ] Register Netlify + `mobilerun://` redirect URIs; public PKCE client
- [ ] Set `COGNITO_*` on Lambda and `VITE_COGNITO_*` on Netlify
- [ ] Set `ALLOWED_USER_EMAILS` to Mac’s email only
- [ ] `JWT_SECRET` + `ALLOW_UNAUTHENTICATED=false`
- [ ] HTTPS only for backend and UI
- [ ] CORS locked to Netlify domain when ready

## Reporting Security Issues

Contact: macandersonuche@yahoo.com — do not open public issues for security problems.

## Audit History

- **2026-11-16**: Initial security audit (JWT, pairing, dating auth)
- **2026-11-16**: Cognito + device-code linking; per-account device ownership
