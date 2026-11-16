import { useState, useEffect, useCallback } from 'react';
import { Smartphone, Wifi, WifiOff, Download, QrCode, Copy, RefreshCw } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';
import { Badge, Card, EmptyState, LoadingBlock } from '../components/ui';

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
  const [pairExpires, setPairExpires] = useState<number | null>(null);
  const [pairErr, setPairErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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
    try {
      const res = await axios.post(
        `${getBackendUrl()}/api/auth/pair/create`,
        { device_name: 'Android', platform: 'android' },
        { headers: { Authorization: `Bearer ${getAuthToken()}` } },
      );
      setPairQr(res.data.qr_code);
      setPairUrl(res.data.pairing_url);
      setHttpsLink(res.data.https_link);
      setPairExpires(Date.now() + (res.data.expires_in || 600) * 1000);
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : 'Could not create pairing QR';
      setPairErr(msg);
    }
  };

  useEffect(() => {
    loadDevices();
    loadApk();
    createPairQr();
    const interval = setInterval(loadDevices, 3000);
    return () => clearInterval(interval);
  }, [loadDevices]);

  const copyLink = async () => {
    const link = httpsLink || pairUrl;
    if (!link) return;
    await navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const revoke = async (deviceId: string) => {
    try {
      await axios.delete(`${getBackendUrl()}/api/devices/${encodeURIComponent(deviceId)}`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      await loadDevices();
    } catch (e) {
      console.error(e);
    }
  };

  const expiresLabel =
    pairExpires != null
      ? `Expires in ~${Math.max(0, Math.round((pairExpires - Date.now()) / 60000))} min`
      : null;

  return (
    <div className="mr-page space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Devices</h2>
        <p className="text-sm text-mute">
          Install the APK, then scan the connect QR below. No URL or sign-in on
          the phone — pairing is tied to this Cognito account.
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
          >
            <RefreshCw size={14} /> New QR
          </button>
        </div>
        <p className="text-sm text-mute">
          Short-lived single-use code (~10 min). Scan with the in-app Scan QR
          button, or with the phone camera (opens the HTTPS link → app). Copyable
          link works the same way after install.
        </p>
        {pairErr && <p className="text-sm text-red-400">{pairErr}</p>}
        {pairQr ? (
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <div className="rounded-xl bg-white p-3">
              <img
                src={`data:image/png;base64,${pairQr}`}
                alt="Connect phone QR"
                className="h-40 w-40"
              />
            </div>
            <div className="space-y-2 text-sm">
              {expiresLabel && <p className="text-mute">{expiresLabel}</p>}
              <button
                type="button"
                onClick={copyLink}
                className="inline-flex items-center gap-1 text-accent"
              >
                <Copy size={14} /> {copied ? 'Copied' : 'Copy link'}
              </button>
              {(httpsLink || pairUrl) && (
                <p className="break-all text-xs text-mute">{httpsLink || pairUrl}</p>
              )}
            </div>
          </div>
        ) : (
          <LoadingBlock label="Creating pairing QR…" />
        )}
      </Card>

      <Card elev className="space-y-3">
        <div className="flex items-center gap-2">
          <Download size={18} className="text-accent" />
          <h3 className="font-medium">Install APK</h3>
        </div>
        <p className="text-sm text-mute">
          Download-only QR for the latest GitHub release. After install, use
          Connect phone above — not a separate login.
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
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {devices === null ? (
          <div className="col-span-full">
            <LoadingBlock />
          </div>
        ) : devices.length === 0 ? (
          <div className="col-span-full">
            <EmptyState
              title="No phones linked"
              hint="Install the APK, then scan the Connect phone QR with the app."
              action={
                <button type="button" className="mr-btn-primary text-sm" onClick={createPairQr}>
                  Refresh connect QR
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
  const rows: [string, boolean | undefined][] = [
    ['Accessibility', perms.accessibility],
    ['Notifications', perms.notifications],
    ['Screen capture', perms.media_projection],
    ['Battery unrestricted', perms.battery_optimization],
    ['Overlay', perms.overlay],
    ['Query packages', perms.query_packages],
    ['Foreground service', perms.foreground_service],
  ];

  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <div className="mb-3 flex items-start justify-between">
        <div className="flex items-center gap-3">
          <Smartphone className="text-accent" size={24} />
          <div>
            <h3 className="font-semibold">{device.name}</h3>
            <p className="text-sm text-mute">{device.device_id}</p>
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
            {device.route || device.connection_type || '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Latency</span>
          <span>
            {device.latency_ms != null
              ? `${Math.round(device.latency_ms)} ms`
              : '—'}
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
                {ok == null ? '—' : ok ? 'OK' : 'Needed'}
              </span>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={onRevoke}
          className="mt-3 text-sm text-red-400 hover:underline"
        >
          Revoke access
        </button>
      </div>
    </div>
  );
}
