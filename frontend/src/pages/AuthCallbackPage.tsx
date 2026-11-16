import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { exchangeCodeForTokens, getCognitoConfig } from '../cognito';
import { setAuthToken } from '../config';
import { Card, ErrorBanner, LoadingBlock } from '../components/ui';

export default function AuthCallbackPage() {
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const cfg = getCognitoConfig();
      if (!cfg) {
        setError('Cognito is not configured');
        return;
      }
      const params = new URLSearchParams(window.location.search);
      const code = params.get('code');
      if (!code) {
        setError('Missing authorization code');
        return;
      }
      try {
        const tokens = await exchangeCodeForTokens(cfg, code);
        setAuthToken(tokens.id_token || tokens.access_token);
        // Decode email from id token payload (unverified client-side display only)
        try {
          const payload = JSON.parse(atob(tokens.id_token.split('.')[1]));
          if (payload.email) {
            localStorage.setItem('mobilerun_user_email', payload.email);
          }
        } catch {
          /* ignore */
        }
        nav('/', { replace: true });
        window.location.reload();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Login failed');
      }
    })();
  }, [nav]);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm space-y-3">
        {error ? <ErrorBanner message={error} /> : <LoadingBlock label="Signing in…" />}
      </Card>
    </div>
  );
}
