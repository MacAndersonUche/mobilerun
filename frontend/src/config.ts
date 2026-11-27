/**
 * Runtime configuration for backend URL.
 *
 * Priority:
 * 1. localStorage setting (user-configured in UI) — ignored when it is a
 *    private/LAN URL while the UI itself is hosted (Netlify / HTTPS prod),
 *    because that causes "Failed to fetch" (mixed content / unreachable LAN).
 * 2. VITE_API_URL (Netlify / cloud) or VITE_BACKEND_URL
 * 3. Default to localhost for development
 */

const DEFAULT_BACKEND_URL =
  import.meta.env.VITE_API_URL ||
  import.meta.env.VITE_BACKEND_URL ||
  'http://localhost:8000';

/** True when the UI is served from a public host (not local Vite). */
export const isHostedUi = (): boolean => {
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname || '';
  if (!host || host === 'localhost' || host === '127.0.0.1') return false;
  if (host.endsWith('.local')) return false;
  return true;
};

/** Reject LAN / loopback overrides that break the hosted Netlify UI. */
export const isUnreachableFromHosted = (url: string): boolean => {
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    if (h === 'localhost' || h === '127.0.0.1' || h === '0.0.0.0') return true;
    if (h.endsWith('.local')) return true;
    if (/^192\.168\.\d+\.\d+$/.test(h)) return true;
    if (/^10\.\d+\.\d+\.\d+$/.test(h)) return true;
    if (/^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$/.test(h)) return true;
    if (u.protocol === 'http:' && isHostedUi()) return true; // mixed content
    return false;
  } catch {
    return true;
  }
};

export const getBackendUrl = (): string => {
  const stored = localStorage.getItem('mobilerun_backend_url');
  if (stored) {
    if (isHostedUi() && isUnreachableFromHosted(stored)) {
      // Auto-heal stale LAN overrides left from local testing.
      try {
        localStorage.removeItem('mobilerun_backend_url');
      } catch {
        /* ignore */
      }
      return DEFAULT_BACKEND_URL.replace(/\/$/, '');
    }
    return stored.replace(/\/$/, '');
  }
  return DEFAULT_BACKEND_URL.replace(/\/$/, '');
};

export const setBackendUrl = (url: string): void => {
  const cleaned = url.trim().replace(/\/$/, '');
  if (isHostedUi() && isUnreachableFromHosted(cleaned)) {
    throw new Error(
      'Hosted UI cannot use a local/LAN backend URL. Use the AWS API URL instead.',
    );
  }
  localStorage.setItem('mobilerun_backend_url', cleaned);
};

/** Hosted AWS HTTP API (chat target toggle). */
export const getHostedBackendUrl = (): string => {
  return (
    localStorage.getItem('mobilerun_hosted_url') ||
    import.meta.env.VITE_API_URL ||
    'https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com'
  ).replace(/\/$/, '');
};

export const getAuthToken = (): string | null => {
  return localStorage.getItem('mobilerun_auth_token');
};

export const setAuthToken = (token: string): void => {
  localStorage.setItem('mobilerun_auth_token', token);
};

export const clearAuthToken = (): void => {
  localStorage.removeItem('mobilerun_auth_token');
};
