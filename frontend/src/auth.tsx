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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(getAuthToken());
  const [email, setEmail] = useState<string | null>(
    localStorage.getItem('mobilerun_user_email')
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
