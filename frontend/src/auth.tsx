import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import axios from 'axios';
import {
  clearAuthToken,
  getAuthToken,
  getBackendUrl,
  setAuthToken,
} from './config';

type AuthState = {
  token: string | null;
  email: string | null;
  loading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
};

const AuthCtx = createContext<AuthState | null>(null);

/** True when a stored JWT is missing, unreadable or past its exp claim. */
export function isTokenExpired(token: string | null, nowMs = Date.now()): boolean {
  if (!token) return true;
  try {
    const part = token.split('.')[1];
    if (!part) return false; // not a JWT (opaque) - let the server decide
    const json = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof json.exp === 'number' && json.exp * 1000 <= nowMs;
  } catch {
    return false;
  }
}

function initialToken(): string | null {
  const t = getAuthToken();
  if (t && isTokenExpired(t)) {
    clearAuthToken();
    return null;
  }
  return t;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(initialToken());
  const [email, setEmail] = useState<string | null>(
    localStorage.getItem('mobilerun_user_email')
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stale/expired session: any 401 on an authed call signs out so the
  // login page shows instead of silently failing (e.g. Generate pairing code).
  useEffect(() => {
    const id = axios.interceptors.response.use(
      (r) => r,
      (err) => {
        const status = err?.response?.status;
        const authHeader =
          err?.config?.headers?.Authorization ?? err?.config?.headers?.authorization;
        const url = String(err?.config?.url || '');
        if (status === 401 && authHeader && !url.includes('/api/auth/login')) {
          clearAuthToken();
          localStorage.removeItem('mobilerun_user_email');
          setToken(null);
          setEmail(null);
          setError('Session expired - sign in again');
        }
        return Promise.reject(err);
      },
    );
    return () => axios.interceptors.response.eject(id);
  }, []);

  useEffect(() => {
    // Cognito hook: if VITE_COGNITO_DOMAIN is set, prefer that later.
    // For now local/JWT login remains the default.
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.post(`${getBackendUrl()}/api/auth/login`, {
        username,
        password,
      });
      const access = res.data.access_token as string;
      setAuthToken(access);
      setToken(access);
      const mail = username.includes('@') ? username : `${username}@local`;
      localStorage.setItem('mobilerun_user_email', mail);
      setEmail(mail);
      return true;
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : 'Login failed';
      setError(msg);
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    clearAuthToken();
    localStorage.removeItem('mobilerun_user_email');
    setToken(null);
    setEmail(null);
  }, []);

  const value = useMemo(
    () => ({ token, email, loading, error, login, logout }),
    [token, email, loading, error, login, logout]
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth outside provider');
  return ctx;
}
