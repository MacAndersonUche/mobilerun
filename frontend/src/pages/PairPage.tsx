import { useEffect, useMemo } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Card } from '../components/ui';

/**
 * HTTPS landing for pairing:
 * - https://…/p/ABC12345 (preferred short QR)
 * - https://…/pair?c=… or ?token=…
 * Tries to open the mobilerun:// deep link; falls back to install instructions.
 */
export default function PairPage() {
  const { code: pathCode } = useParams<{ code?: string }>();
  const [params] = useSearchParams();

  const code = useMemo(() => {
    const fromPath = (pathCode || '').trim();
    const fromQuery = (params.get('c') || params.get('token') || '').trim();
    return (fromPath || fromQuery).toUpperCase();
  }, [pathCode, params]);

  const deepLink = useMemo(() => {
    if (!code) return null;
    return `mobilerun://pair?c=${encodeURIComponent(code)}`;
  }, [code]);

  useEffect(() => {
    if (!deepLink) return;
    const t = window.setTimeout(() => {
      window.location.href = deepLink;
    }, 50);
    const t2 = window.setTimeout(() => {
      window.location.href = deepLink;
    }, 800);
    return () => {
      window.clearTimeout(t);
      window.clearTimeout(t2);
    };
  }, [deepLink]);

  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">Connect MacMobileRun</h1>
      <Card className="space-y-3">
        <p className="text-sm text-mute">
          Opening the MacMobileRun app… If nothing happens, install the APK from{' '}
          <Link to="/devices" className="text-accent">
            Devices
          </Link>
          , then enter the pairing code or scan again.
        </p>
        {code && (
          <p className="font-mono text-lg tracking-widest text-white" data-testid="pair-landing-code">
            {code}
          </p>
        )}
        {deepLink && (
          <a href={deepLink} className="inline-block text-sm text-accent break-all">
            Open in MacMobileRun app
          </a>
        )}
        {!code && (
          <p className="text-sm text-red-400">
            This link is missing a pairing code. Generate a new code on Devices.
          </p>
        )}
      </Card>
    </div>
  );
}
