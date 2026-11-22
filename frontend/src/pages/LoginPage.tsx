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
    <div className="min-h-screen bg-canvas text-white md:grid md:grid-cols-2">
      {/* Form column — mirrors cloud.mobilerun.ai split login */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm space-y-6">
          <div className="space-y-1">
            <p className="text-[10px] uppercase tracking-[0.22em] text-mute">MacMobileRun</p>
            <h1 className="text-3xl font-semibold tracking-tight">Welcome to MacMobileRun</h1>
            <p className="text-sm text-mute">
              Sign in to run dating & social on your phone. The APK uses the same account.
            </p>
          </div>

          <Card elev className="space-y-3 border-line/80">
            {error && <ErrorBanner message={error} />}
            {cognito && (
              <div className="space-y-2">
                <Button
                  variant="outline"
                  className="w-full justify-center"
                  onClick={async () => {
                    window.location.href = await cognitoAuthorizeUrl(cognito, 'Google');
                  }}
                >
                  Continue with Google
                </Button>
                <Button
                  variant="outline"
                  className="w-full justify-center"
                  onClick={async () => {
                    window.location.href = await cognitoAuthorizeUrl(cognito, 'COGNITO');
                  }}
                >
                  Continue with email
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
              {loading ? 'Signing in…' : 'Continue'}
            </Button>
            <p className="text-center text-xs text-mute">
              QR codes download the APK only — linking is Cognito, not pairing.
            </p>
          </Card>
        </div>
      </div>

      {/* Brand panel */}
      <div className="relative hidden overflow-hidden bg-[#0e0e11] md:flex md:flex-col md:justify-between md:p-10">
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              'radial-gradient(circle at 30% 40%, rgba(59,130,246,0.25), transparent 55%), radial-gradient(circle at 80% 20%, rgba(59,130,246,0.12), transparent 40%)',
          }}
        />
        <div className="relative">
          <p className="text-[10px] uppercase tracking-[0.25em] text-mute">MacMobileRun</p>
        </div>
        <div className="relative space-y-4">
          <p className="font-mono text-3xl font-semibold uppercase leading-tight tracking-wide text-white">
            Dating &
            <br />
            social
            <br />
            on your phone
          </p>
          <p className="max-w-sm text-sm text-mute">
            Run openers and chats · APK executes wirelessly · same Cognito account.
          </p>
          <div className="mt-8 flex gap-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-40 w-[72px] rounded-[18px] border border-line bg-canvas-elev/80 shadow-sheet"
                style={{ transform: `translateY(${i * 8}px)` }}
              />
            ))}
          </div>
        </div>
        <p className="relative text-xs text-mute">Self-hosted · AWS + LLM tokens only</p>
      </div>
    </div>
  );
}
