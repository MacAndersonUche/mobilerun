# Fabs SSO Secret Setup Instructions

## Overview
The Fabs SSO integration requires a shared secret (`FABS_SSO_SECRET`) to be set in BOTH repositories:
- **MacAndersonUche/mobilerun** (portal/backend)
- **MacAndersonUche/Auto-Fab** (receiving side)

## Secret Generated
A strong 64-character secret has been generated for this integration.

**IMPORTANT**: The actual secret value is stored securely and should NEVER be committed to any repository or printed in logs.

## Setup Required

### 1. Mobilerun Repository (MacAndersonUche/mobilerun)

#### GitHub Actions Secret
Set the secret in GitHub repository settings:
```bash
# Using gh CLI (requires repo admin access):
gh secret set FABS_SSO_SECRET --repo MacAndersonUche/mobilerun
# Paste the secret value when prompted
```

Or manually in GitHub:
1. Go to https://github.com/MacAndersonUche/mobilerun/settings/secrets/actions
2. Click "New repository secret"
3. Name: `FABS_SSO_SECRET`
4. Value: (paste the generated 64-char secret)
5. Click "Add secret"

**Status**: Infrastructure updated ✓
- CDK stack reads from `process.env.FABS_SSO_SECRET`
- GitHub Actions workflow passes secret to CDK deploy
- Changes committed to PR #117

### 2. Auto-Fab Repository (MacAndersonUche/Auto-Fab)

#### If Auto-Fab deploys via Netlify:

**Option A - Netlify CLI** (requires Netlify auth token):
```bash
# Set as Netlify environment variable
netlify env:set FABS_SSO_SECRET "<secret-value>" --context production
```

**Option B - Netlify Dashboard**:
1. Go to Netlify site settings for fabswingerauto.netlify.app
2. Navigate to Site settings → Environment variables
3. Add variable:
   - Key: `FABS_SSO_SECRET`
   - Value: (paste the generated 64-char secret)
   - Scopes: Production (and Deploy Previews if needed)
4. Redeploy the site

#### If Auto-Fab uses GitHub Actions:
Set the same secret in Auto-Fab repository:
```bash
gh secret set FABS_SSO_SECRET --repo MacAndersonUche/Auto-Fab
# Paste the same secret value
```

**Status**: ⚠️ MANUAL ACTION REQUIRED
- Cannot access Auto-Fab repository from this agent
- Mac or someone with access needs to set `FABS_SSO_SECRET` there

### 3. Additional Secret: FABS_MAC_PASSWORD

The user mentioned `FABS_MAC_PASSWORD` which Mac provided in chat.

**Where to set it**:
- If this is for Auto-Fab backend authentication: Set in MacAndersonUche/Auto-Fab
- If this is for Mobilerun backend: Set in MacAndersonUche/mobilerun

**Setup method**: Same as above (GitHub Actions secret or Netlify environment variable)

## Verification

### After secrets are set in BOTH repos:

1. **Merge PR #117** in mobilerun
2. **Deploy triggers** (GitHub Actions deploys mobilerun backend to AWS Lambda)
3. **Test SSO flow**:
   - Log into https://macsmobilerun.netlify.app as Mac/admin
   - Click the "Fabs" tile on home page
   - Should redirect to `https://fabswingerauto.netlify.app/sso#token=<token>`
   - Auto-Fab should validate the token with the same `FABS_SSO_SECRET`
   - User should be logged in as "Mac" on Auto-Fab

### Troubleshooting:
- If tile shows "Fabs SSO is not configured": `FABS_SSO_SECRET` not set in mobilerun Lambda
- If Auto-Fab rejects token: `FABS_SSO_SECRET` mismatch between repos or not set in Auto-Fab
- If token expires: Normal (60-second expiry), click tile again

## Security Notes
- Secret is 64 characters (384 bits of entropy)
- Generated using `secrets.token_urlsafe(48)` (cryptographically secure)
- Must be identical in both repositories
- Never log or commit the secret value
- Tokens expire in 60 seconds (matches Auto-Fab contract)
- HMAC-SHA256 signature verification prevents tampering

## Current Status Summary

✅ **Completed**:
- Generated strong 64-char FABS_SSO_SECRET
- Updated mobilerun CDK stack to read FABS_SSO_SECRET
- Updated mobilerun GitHub Actions deploy workflow
- Code committed to PR #117

⚠️ **Manual Actions Required**:
1. Set `FABS_SSO_SECRET` in mobilerun GitHub Actions secrets (requires repo admin)
2. Set `FABS_SSO_SECRET` in Auto-Fab (Netlify env var or GitHub secret)
3. Optionally set `FABS_MAC_PASSWORD` in appropriate repo
4. Merge PR #117 after CI passes
5. Test SSO flow end-to-end

## Secret Storage Location
The actual secret value has been generated but NOT stored in any file or log. It needs to be:
- Retrieved from the secure generation context
- Set in GitHub/Netlify by someone with admin access
- Kept confidential

If the secret value was not captured during generation, regenerate it with:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```
Then set the SAME value in both mobilerun and Auto-Fab.
