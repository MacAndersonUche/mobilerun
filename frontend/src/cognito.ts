/**
 * Cognito hosted-UI helpers (PKCE).
 * Set VITE_COGNITO_DOMAIN, VITE_COGNITO_CLIENT_ID, VITE_COGNITO_REDIRECT_URI.
 * Falls back to local JWT login when unset.
 */

export type CognitoConfig = {
  domain: string;
  clientId: string;
  redirectUri: string;
  region?: string;
};

const PKCE_VERIFIER_KEY = 'mobilerun_pkce_verifier';

export function getCognitoConfig(): CognitoConfig | null {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined;
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
  const redirectUri =
    (import.meta.env.VITE_COGNITO_REDIRECT_URI as string | undefined) ||
    (typeof window !== 'undefined' ? `${window.location.origin}/auth/callback` : '');
  if (!domain || !clientId || !redirectUri) return null;
  return {
    domain: domain.replace(/\/$/, ''),
    clientId,
    redirectUri,
    region: import.meta.env.VITE_COGNITO_REGION as string | undefined,
  };
}

function randomVerifier(length = 64): string {
  const chars =
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => chars[b % chars.length]).join('');
}

async function sha256Base64Url(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest('SHA-256', data);
  const bytes = new Uint8Array(digest);
  let str = '';
  bytes.forEach((b) => {
    str += String.fromCharCode(b);
  });
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function cognitoAuthorizeUrl(
  cfg: CognitoConfig,
  identity?: 'Google' | 'COGNITO'
): Promise<string> {
  const verifier = randomVerifier();
  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  const challenge = await sha256Base64Url(verifier);
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    response_type: 'code',
    scope: 'openid email profile',
    redirect_uri: cfg.redirectUri,
    code_challenge_method: 'S256',
    code_challenge: challenge,
  });
  if (identity === 'Google') {
    params.set('identity_provider', 'Google');
  }
  return `https://${cfg.domain}/oauth2/authorize?${params.toString()}`;
}

export async function exchangeCodeForTokens(
  cfg: CognitoConfig,
  code: string
): Promise<{ id_token: string; access_token: string; refresh_token?: string }> {
  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY) || '';
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: cfg.clientId,
    code,
    redirect_uri: cfg.redirectUri,
  });
  if (verifier) body.set('code_verifier', verifier);
  const res = await fetch(`https://${cfg.domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) throw new Error(`Cognito token exchange failed: ${res.status}`);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  return res.json();
}
