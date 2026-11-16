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

export const getAuthToken = (): string | null => {
  return localStorage.getItem('mobilerun_auth_token');
};

export const setAuthToken = (token: string): void => {
  localStorage.setItem('mobilerun_auth_token', token);
};

export const clearAuthToken = (): void => {
  localStorage.removeItem('mobilerun_auth_token');
};
