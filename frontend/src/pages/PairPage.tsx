import { useEffect, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Card } from '../components/ui';

/**
 * HTTPS landing for pairing links (https://macsmobilerun.netlify.app/pair?token=…).
 * Tries to open the mobilerun:// deep link; falls back to install/connect instructions.
 */
export default function PairPage() {
  const [params] = useSearchParams();
  const deepLink = useMemo(() => {
    const qs = params.toString();
    return qs ? `mobilerun://pair?${qs}` : null;
  }, [params]);

  useEffect(() => {
    if (!deepLink) return;
    // Attempt to hand off to the installed APK
    window.location.href = deepLink;
  }, [deepLink]);

  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">Connect MobileRun</h1>
      <Card className="space-y-3">
        <p className="text-sm text-mute">
          Opening the MobileRun app… If nothing happens, install the APK from{' '}
          <Link to="/devices" className="text-accent">
            Devices
          </Link>
          , then tap Scan QR (or open this link again).
        </p>
        {deepLink && (
          <a href={deepLink} className="inline-block text-sm text-accent break-all">
            Open in MobileRun app
          </a>
        )}
      </Card>
    </div>
  );
}
