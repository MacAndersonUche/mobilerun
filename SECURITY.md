# Security Overview

## Authentication & Authorization

### JWT Tokens

**Backend API Endpoints:**
- All REST API endpoints require JWT authentication via `Authorization: Bearer <token>` header
- JWT tokens are created with `create_access_token()` in `backend/auth.py`
- Default expiration: 7 days
- Algorithm: HS256

**Environment Variables:**
- `JWT_SECRET`: Must be set in production (defaults to `dev-secret-change-in-production` for local dev)
- `ALLOW_UNAUTHENTICATED`: Set to `false` in production (defaults to `false`)

**⚠️ CRITICAL: Production Deployment**
```bash
# Generate a secure random secret
export JWT_SECRET=$(openssl rand -hex 32)

# Ensure auth is required
export ALLOW_UNAUTHENTICATED=false
```

### Device Pairing Tokens

**Pairing Flow:**
1. Backend generates one-time pairing token via `/api/devices/pair`
2. Token expires after 10 minutes
3. QR code contains: `mobilerun://pair?token=<token>&backend=<backend_url>`
4. Phone scans QR and connects via WebSocket with token
5. Token is validated, checked for expiration, and consumed (deleted) on first use

**Security Features:**
- ✅ One-time use (token deleted after successful pairing)
- ✅ 10-minute expiration enforced
- ✅ Token stored in-memory only (not persisted)
- ✅ No credentials in QR code (only pairing token)

### WebSocket Authentication

**Device Connection (`/api/devices/connect`):**
- Requires valid pairing token in first message
- Token must not be expired (10 min window)
- Token is consumed on successful connection
- WebSocket remains authenticated for session lifetime

## Secrets Management

### What is NOT in APK or Frontend

✅ **Verified Clean:**
- ❌ No API keys (OpenAI, Anthropic, Gemini, xAI/Grok, AWS)
- ❌ No JWT secrets
- ❌ No AWS credentials
- ❌ No hardcoded passwords
- ❌ No backend credentials

### Backend URL Configuration

**Frontend (React):**
- Backend URL stored in browser `localStorage` (user-configurable in Settings)
- Default: `http://localhost:8000` or `VITE_BACKEND_URL` env var at build time
- No sensitive data in build artifacts

**Android App:**
- Backend URL obtained from QR code during pairing
- Stored in SharedPreferences after pairing
- Pairing token stored temporarily (deleted after connection)
- No hardcoded backend URLs or credentials

### Environment Variables (.env)

**Required for Production:**
```bash
# JWT secret (REQUIRED - generate with: openssl rand -hex 32)
JWT_SECRET=your-secure-random-secret-here

# Auth enforcement (REQUIRED)
ALLOW_UNAUTHENTICATED=false

# Backend URL for pairing QR codes
BACKEND_URL=https://your-lambda-url.amazonaws.com

# Optional: AWS credentials (if using Lambda)
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=eu-west-2
```

**⚠️ NEVER commit `.env` files** - already in `.gitignore`

## API Endpoint Security

### Public Endpoints (No Auth Required)

Only one endpoint is intentionally public:
- `GET /api/releases/latest` - APK download info

### Protected Endpoints (Auth Required)

All other endpoints require authentication:
- `/api/devices` - Device management
- `/api/tasks` - Task execution
- `/api/config` - Configuration
- `/api/dating/*` - Dating mode (all endpoints)

**Dating Mode Endpoints Protected:**
- ✅ `GET/POST /api/dating/config`
- ✅ `GET /api/dating/stats`
- ✅ `POST /api/dating/{start,stop,pause}`
- ✅ `GET /api/dating/status`
- ✅ `GET /api/dating/review-queue`
- ✅ `POST /api/dating/review/{id}/{approve,reject,edit}`

### Development vs Production

**Development Mode:**
```bash
# Optional auth (allows unauthenticated for testing)
ALLOW_UNAUTHENTICATED=true

# Start with:
mobilerun serve --allow-unauthenticated
```

**Production Mode:**
```bash
# Auth required (default)
ALLOW_UNAUTHENTICATED=false

# Or explicitly set:
export JWT_SECRET=$(openssl rand -hex 32)
mobilerun serve
```

## AWS Lambda Security

### Lambda Deployment

**Environment Variables (set via CDK or AWS Console):**
```typescript
// In infra/lib/mobilerun-stack.ts
lambdaFunction.addEnvironment('JWT_SECRET', process.env.JWT_SECRET!);
lambdaFunction.addEnvironment('ALLOW_UNAUTHENTICATED', 'false');
```

**IAM Permissions:**
- Lambda execution role has minimal permissions
- DynamoDB: read/write only to mobilerun-* tables
- S3: read/write only to mobilerun-screenshots bucket
- CloudWatch: log writing only

**API Gateway:**
- CORS configured with specific origins (update for production domain)
- Rate limiting recommended (not yet implemented)
- API keys optional (not yet implemented)

## Threat Model

### Protected Against

✅ **Unauthorized API Access:**
- JWT tokens required for all sensitive endpoints
- Tokens expire after 7 days

✅ **Pairing Token Replay:**
- One-time use tokens
- 10-minute expiration
- Consumed on first use

✅ **Credential Exposure:**
- No secrets in APK or frontend build
- Environment variables for all sensitive config
- `.env` files in `.gitignore`

✅ **Dating Mode Unauthorized Access:**
- All dating endpoints require authentication
- Configuration changes protected
- Review queue access controlled

### Not Yet Implemented

⚠️ **Rate Limiting:**
- Currently no rate limiting on API endpoints
- Recommended: Add rate limiting middleware for production

⚠️ **API Key Rotation:**
- JWT secret rotation not automated
- Manually update `JWT_SECRET` and restart backend

⚠️ **Device Revocation:**
- No mechanism to revoke paired devices
- Currently requires backend restart to clear connections

⚠️ **WebSocket Re-authentication:**
- WebSocket connections remain authenticated indefinitely
- Consider adding periodic re-authentication

## Security Checklist for Production

- [ ] Generate secure `JWT_SECRET` with `openssl rand -hex 32`
- [ ] Set `ALLOW_UNAUTHENTICATED=false`
- [ ] Use HTTPS for backend URL (not HTTP)
- [ ] Configure CORS with specific allowed origins
- [ ] Enable CloudWatch log retention limits (7 days configured)
- [ ] Set up AWS Budget alerts ($5/month configured)
- [ ] Review IAM permissions (least privilege)
- [ ] Add rate limiting middleware (recommended)
- [ ] Monitor pairing token usage
- [ ] Regularly rotate JWT secret
- [ ] Keep dependencies updated (`pip install -U`, `npm update`)

## Reporting Security Issues

For security vulnerabilities, please contact: macandersonuche@yahoo.com

Do not open public issues for security problems.

## Audit History

- **2026-11-16**: Initial security audit
  - ✅ Confirmed no API keys in APK or frontend
  - ✅ Added token expiration enforcement
  - ✅ Added one-time pairing token consumption
  - ✅ Added authentication to dating mode endpoints
  - ✅ Documented JWT secret requirements
