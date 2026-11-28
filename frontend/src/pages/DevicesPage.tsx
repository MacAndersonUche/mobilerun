import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Smartphone,
  Wifi,
  WifiOff,
  Download,
  QrCode,
  Copy,
  RefreshCw,
  ExternalLink,
  Trash2,
} from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';
import { Badge, Card, EmptyState, LoadingBlock } from '../components/ui';
import { buildDeepLink, buildIntentUrl, shortHttpsLink } from '../lib/pairingLinks';

interface DevicePermissions {
  accessibility?: boolean;
  notifications?: boolean;
  media_projection?: boolean;
  battery_optimization?: boolean;
  overlay?: boolean;
  query_packages?: boolean;
  foreground_service?: boolean;
  updated_at?: string;
}

interface Device {
  device_id: string;
  name: string;
  platform: string;
  connected: boolean;
  connection_type: string;
  last_seen: string;
  route?: string | null;
  latency_ms?: number | null;
  permissions?: DevicePermissions | null;
}

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [apkQr, setApkQr] = useState<string | null>(null);
  const [apkUrl, setApkUrl] = useState<string | null>(null);
  const [pairQr, setPairQr] = useState<string | null>(null);
  const [pairUrl, setPairUrl] = useState<string | null>(null);
  const [httpsLink, setHttpsLink] = useState<string | null>(null);
  const [pairToken, setPairToken] = useState<string | null>(null);
  const [pairExpires, setPairExpires] = useState<number | null>(null);
  const [pairErr, setPairErr] = useState<string | null>(null);
  const [pairBusy, setPairBusy] = useState(false);
  const [copied, setCopied] = useState<'link' | 'code' | null>(null);
  const [connectHint, setConnectHint] = useState<string | null>(null);
  const [revokeErr, setRevokeErr] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  const loadDevices = useCallback(async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      setDevices(response.data);
    } catch (error) {
      console.error('Failed to load devices:', error);
      setDevices([]);
    }
  }, []);

  const loadApk = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/releases/latest`);
      setApkQr(response.data.qr_code);
      setApkUrl(response.data.apk_url);
    } catch (error) {
      console.error('Failed to load APK QR:', error);
    }
  };

  const createPairQr = async () => {
    setPairErr(null);
    setPairBusy(true);
    try {
      const res = await axios.post(
        `${getBackendUrl()}/api/auth/pair/create`,
        { device_name: 'Android', platform: 'android' },
        { headers: { Authorization: `Bearer ${getAuthToken()}` } },
      );
      const token = String(res.data.code || res.data.token || '');
      setPairToken(token || null);
      setPairQr(res.data.qr_code);
      setPairUrl(res.data.pairing_url || (token ? buildDeepLink(token) : null));
      setHttpsLink(
        res.data.short_link ||
          res.data.https_link ||
          (token ? shortHttpsLink(token) : null),
      );
      setPairExpires(Date.now() + (res.data.expires_in || 600) * 1000);
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : 'Could not create pairing code';
      setPairErr(msg);
    } finally {
      setPairBusy(false);
    }
  };

  const deepLink = useMemo(() => {
    if (pairUrl?.startsWith('mobilerun://')) return pairUrl;
    if (pairToken) return buildDeepLink(pairToken);
    return null;
  }, [pairUrl, pairToken]);

  const intentLink = useMemo(() => {
    if (!pairToken || !httpsLink) return null;
    return buildIntentUrl({ token: pairToken, httpsFallback: httpsLink });
  }, [pairToken, httpsLink]);

  useEffect(() => {
    loadDevices();
    loadApk();
    // Do not auto-create a code — user taps Generate pairing code
    const interval = setInterval(loadDevices, 3000);
    return () => clearInterval(interval);
  }, [loadDevices]);

  useEffect(() => {
    if (pairExpires == null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [pairExpires]);

  const copyLink = async () => {
    const link = httpsLink || pairUrl;
    if (!link) return;
    await navigator.clipboard.writeText(link);
    setCopied('link');
    setTimeout(() => setCopied(null), 2000);
  };

  const copyCode = async () => {
    if (!pairToken) return;
    await navigator.clipboard.writeText(pairToken);
    setCopied('code');
    setTimeout(() => setCopied(null), 2000);
  };

  /** Same-phone handoff: try custom scheme, then intent://, then https. */
  const connectThisPhone = () => {
    setConnectHint(null);
    if (!pairToken) {
      setConnectHint('Generate a pairing code first.');
      return;
    }
    const https = httpsLink || shortHttpsLink(pairToken);
    const deep = deepLink || buildDeepLink(pairToken);
    const intent =
      intentLink ||
      buildIntentUrl({ token: pairToken, httpsFallback: https });

    window.location.href = deep;
    window.setTimeout(() => {
      window.location.href = intent;
    }, 400);
    window.setTimeout(() => {
      window.location.href = https;
    }, 1200);
    setConnectHint(
      'Opening PhonePilot… If nothing happens, install the APK first, then tap again - or type the code in the app.',
    );
  };

  const revoke = async (deviceId: string) => {
    setRevokeErr(null);
    try {
      await axios.delete(`${getBackendUrl()}/api/devices/${encodeURIComponent(deviceId)}`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      await loadDevices();
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : 'Could not remove device';
      setRevokeErr(msg);
    }
  };

  const secondsLeft =
    pairExpires != null ? Math.max(0, Math.round((pairExpires - now) / 1000)) : null;
  const expiresLabel =
    secondsLeft != null
      ? `Expires in ${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, '0')}`
      : null;

  return (
    <div className="mr-page space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Devices</h2>
        <p className="text-sm text-mute">
          Install the APK, then scan the connect QR or type the pairing code.
          No URL or sign-in on the phone.
        </p>
      </div>

      <Card elev className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <QrCode size={18} className="text-accent" />
            <h3 className="font-medium">Connect phone</h3>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1 text-sm text-accent"
            onClick={createPairQr}
            disabled={pairBusy}
            data-testid="generate-pairing-code"
          >
            <RefreshCw size={14} /> {pairToken ? 'Regenerate' : 'Generate pairing code'}
          </button>
        </div>
        <p className="text-sm text-mute">
          On this phone: tap <span className="text-white">Connect this phone</span>.
          On another device: scan the QR, or type the code in the app.
        </p>
        {pairErr && <p className="text-sm text-red-400">{pairErr}</p>}

        <div className="space-y-2 rounded-xl border border-accent/40 bg-accent/10 p-3">
          <button
            type="button"
            data-testid="connect-this-phone"
            className="mr-btn-primary w-full text-base"
            onClick={connectThisPhone}
            disabled={!pairToken}
          >
            <ExternalLink size={16} /> Connect this phone
          </button>
          <p className="text-xs text-mute">
            Opens the PhonePilot app with this pairing code (no camera needed).
          </p>
          {connectHint && (
            <p className="text-xs text-amber-200" data-testid="connect-hint">
              {connectHint}
            </p>
          )}
          <div className="flex flex-wrap gap-3 text-sm">
            {apkUrl && (
              <a
                href={apkUrl}
                className="inline-flex items-center gap-1 text-accent"
                target="_blank"
                rel="noreferrer"
                data-testid="download-app-first"
              >
                <Download size={14} /> Download app first
              </a>
            )}
            {httpsLink && (
              <a
                href={httpsLink}
                className="inline-flex items-center gap-1 text-accent"
                data-testid="https-pair-fallback"
              >
                HTTPS app link
              </a>
            )}
          </div>
        </div>

        {!pairToken && !pairBusy && (
          <button
            type="button"
            className="mr-btn-primary w-full"
            onClick={createPairQr}
            data-testid="generate-pairing-code-primary"
          >
            Generate pairing code
          </button>
        )}

        {pairBusy && !pairQr && <LoadingBlock label="Creating pairing code…" />}

        {pairQr && pairToken && (
          <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-start">
            {/* Large high-contrast QR - never hide on mobile */}
            <div
              className="mx-auto shrink-0 rounded-2xl bg-white p-4 sm:mx-0"
              data-testid="pair-qr"
            >
              <img
                src={`data:image/png;base64,${pairQr}`}
                alt="Connect phone QR"
                className="h-56 w-56 max-w-full sm:h-64 sm:w-64"
              />
            </div>
            <div className="min-w-0 flex-1 space-y-3 text-sm">
              {expiresLabel && (
                <p className="text-mute" data-testid="pairing-countdown">
                  {expiresLabel}
                </p>
              )}

              <div className="space-y-1">
                <p className="text-xs font-medium uppercase tracking-wide text-mute">
                  Pairing code (type in app)
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <code
                    data-testid="pairing-code"
                    className="rounded-lg bg-canvas-elev px-3 py-2 font-mono text-2xl tracking-[0.2em] text-white"
                  >
                    {pairToken}
                  </code>
                  <button
                    type="button"
                    onClick={copyCode}
                    className="inline-flex items-center gap-1 text-accent"
                    data-testid="copy-pairing-code"
                  >
                    <Copy size={14} /> {copied === 'code' ? 'Copied' : 'Copy code'}
                  </button>
                </div>
                <p className="text-xs text-mute">
                  No ambiguous characters - enter this code alone in PhonePilot.
                </p>
              </div>

              <button
                type="button"
                onClick={copyLink}
                className="inline-flex items-center gap-1 text-accent"
              >
                <Copy size={14} /> {copied === 'link' ? 'Copied' : 'Copy short link'}
              </button>
              {httpsLink && (
                <p className="break-all text-xs text-mute" data-testid="pairing-short-link">
                  {httpsLink}
                </p>
              )}
            </div>
          </div>
        )}
      </Card>

      <Card elev className="space-y-0 overflow-hidden p-0" data-testid="devices-install-apk">
        {(() => {
          const hasConnected = (devices ?? []).some((d) => d.connected);
          return (
            <details
              key={hasConnected ? 'apk-collapsed' : 'apk-open'}
              open={!hasConnected}
              className="group"
            >
              <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 [&::-webkit-details-marker]:hidden">
                <Download size={18} className="text-accent" />
                <h3 className="font-medium">Install APK</h3>
                {hasConnected && (
                  <span className="ml-auto text-xs text-mute">
                    Collapsed · phone connected
                  </span>
                )}
              </summary>
              <div className="space-y-3 border-t border-line px-4 pb-4 pt-3">
                <p className="text-sm text-mute">
                  Download-only QR for the latest GitHub release. After install,
                  use Connect phone above - not a separate login.
                </p>
                {apkQr ? (
                  <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
                    <div className="rounded-xl bg-white p-3">
                      <img
                        src={`data:image/png;base64,${apkQr}`}
                        alt="APK download QR"
                        className="h-40 w-40"
                      />
                    </div>
                    {apkUrl && (
                      <a
                        href={apkUrl}
                        className="text-sm text-accent break-all"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {apkUrl}
                      </a>
                    )}
                  </div>
                ) : (
                  <LoadingBlock label="Loading download QR…" />
                )}
              </div>
            </details>
          );
        })()}
      </Card>

      {revokeErr && (
        <p className="text-sm text-red-400" data-testid="revoke-error">
          {revokeErr}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {devices === null ? (
          <div className="col-span-full">
            <LoadingBlock />
          </div>
        ) : devices.length === 0 ? (
          <div className="col-span-full">
            <EmptyState
              title="No phones linked"
              hint="Install the APK, generate a pairing code, then scan or type it in the app."
              action={
                <button
                  type="button"
                  className="mr-btn-primary text-sm"
                  onClick={createPairQr}
                >
                  Generate pairing code
                </button>
              }
            />
          </div>
        ) : (
          devices.map((device) => (
            <DeviceCard
              key={device.device_id}
              device={device}
              onRevoke={() => revoke(device.device_id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function DeviceCard({
  device,
  onRevoke,
}: {
  device: Device;
  onRevoke: () => void;
}) {
  const perms = device.permissions || {};
  // Slim surface: only what onboarding still cares about.
  // MediaProjection / overlay / FGS are optional or automatic — omit from the card.
  const rows: [string, boolean | undefined][] = [
    ['Accessibility', perms.accessibility],
    ['Notifications', perms.notifications],
    ['Battery unrestricted', perms.battery_optimization],
  ];

  return (
    <div className="rounded-2xl border border-line bg-surface p-4" data-testid="device-card">
      <div className="mb-3 flex items-start justify-between">
        <div className="flex items-center gap-3">
          <Smartphone className="text-accent" size={24} />
          <div>
            <h3 className="font-semibold">{device.name}</h3>
            <p className="text-sm text-mute break-all">{device.device_id}</p>
          </div>
        </div>
        {device.connected ? (
          <Wifi className="text-green-400" size={20} />
        ) : (
          <WifiOff className="text-red-400" size={20} />
        )}
      </div>

      <div className="space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-mute">Route</span>
          <span className="uppercase">
            {device.route || device.connection_type || '-'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Latency</span>
          <span>
            {device.latency_ms != null
              ? `${Math.round(device.latency_ms)} ms`
              : '-'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Status</span>
          <Badge tone={device.connected ? 'ok' : 'mute'}>
            {device.connected ? 'Connected' : 'Offline'}
          </Badge>
        </div>
      </div>

      <div className="mt-4 border-t border-line pt-3">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-mute">
          Permissions
        </p>
        <ul className="space-y-1 text-sm">
          {rows.map(([label, ok]) => (
            <li key={label} className="flex justify-between gap-2">
              <span className="text-mute">{label}</span>
              <span className={ok ? 'text-ok' : 'text-amber-300'}>
                {ok == null ? '-' : ok ? 'OK' : 'Needed'}
              </span>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={onRevoke}
          data-testid="remove-device"
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-red-500/40 bg-red-950/30 px-3 py-2 text-sm text-red-300 hover:bg-red-950/50"
        >
          <Trash2 size={14} /> Remove device
        </button>
      </div>
    </div>
  );
}
