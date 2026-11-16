import { useState } from 'react';
import { useAuth } from '../auth';
import { cognitoAuthorizeUrl, getCognitoConfig } from '../cognito';
import { Button, Card, ErrorBanner, Input } from '../components/ui';

export default function LoginPage() {
  const { login, loading, error } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');
  const cognito = getCognitoConfig();

  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1">
          <p className="text-xs tracking-[0.2em] text-mute uppercase">MacAI</p>
          <h1 className="text-3xl font-semibold">MobileRun</h1>
          <p className="text-sm text-mute">Sign in to control your phone agents</p>
        </div>
        <Card elev className="space-y-3">
          {error && <ErrorBanner message={error} />}
          {cognito && (
            <div className="space-y-2">
              <Button
                className="w-full"
                onClick={async () => {
                  window.location.href = await cognitoAuthorizeUrl(cognito, 'COGNITO');
                }}
              >
                Sign in with email (Cognito)
              </Button>
              <Button
                variant="outline"
                className="w-full"
                onClick={async () => {
                  window.location.href = await cognitoAuthorizeUrl(cognito, 'Google');
                }}
              >
                Continue with Google
              </Button>
              <div className="relative py-2 text-center text-xs text-mute">
                <span className="bg-surface-elev px-2">or local</span>
              </div>
            </div>
          )}
          <label className="block text-sm text-mute">
            Email or username
            <Input
              className="mt-1"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
            />
          </label>
          <label className="block text-sm text-mute">
            Password
            <Input
              className="mt-1"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          <Button
            className="w-full"
            disabled={loading}
            onClick={() => login(username.trim(), password)}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </Button>
          <p className="text-xs text-mute text-center">
            Same Cognito account links the APK (no pairing QR after first login).
            QR remains for APK download only.
          </p>
        </Card>
      </div>
    </div>
  );
}
