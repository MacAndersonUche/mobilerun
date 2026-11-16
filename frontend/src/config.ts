/**
 * Runtime configuration for backend URL.
 *
 * Priority:
 * 1. localStorage setting (user-configured in UI)
 * 2. VITE_API_URL (Netlify / cloud) or VITE_BACKEND_URL
 * 3. Default to localhost for development
 */

const DEFAULT_BACKEND_URL =
  import.meta.env.VITE_API_URL ||
  import.meta.env.VITE_BACKEND_URL ||
  'http://localhost:8000';

export const getBackendUrl = (): string => {
  const stored = localStorage.getItem('mobilerun_backend_url');
  return stored || DEFAULT_BACKEND_URL;
};

export const setBackendUrl = (url: string): void => {
  localStorage.setItem('mobilerun_backend_url', url);
};

export const getWebSocketUrl = (): string => {
  const httpUrl = getBackendUrl();
  return httpUrl.replace(/^http/, 'ws');
};

/** UI live-view socket (local FastAPI path). */
export const getUiWebSocketUrl = (): string => {
  const explicit = localStorage.getItem('mobilerun_ui_ws_url');
  if (explicit) return explicit;
  // Prefer cloud WS API when backend is API Gateway HTTP API
  const hostedWs = import.meta.env.VITE_WS_URL as string | undefined;
  if (hostedWs && getBackendUrl().includes('execute-api')) {
    return hostedWs;
  }
  return `${getWebSocketUrl()}/api/ui/connect`;
};

/** Hosted AWS HTTP API (chat target toggle). */
export const getHostedBackendUrl = (): string => {
  return (
    localStorage.getItem('mobilerun_hosted_url') ||
    import.meta.env.VITE_API_URL ||
    'https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com'
  );
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
