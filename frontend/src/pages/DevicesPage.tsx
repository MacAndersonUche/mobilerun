import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Smartphone, Wifi, WifiOff, Download } from 'lucide-react';
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

  useEffect(() => {
    loadDevices();
    loadApk();
    const interval = setInterval(loadDevices, 3000);
    return () => clearInterval(interval);
  }, []);

  const loadDevices = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      setDevices(response.data);
    } catch (error) {
      console.error('Failed to load devices:', error);
      setDevices([]);
    }
  };

  const loadApk = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/releases/latest`);
      setApkQr(response.data.qr_code);
      setApkUrl(response.data.apk_url);
    } catch (error) {
      console.error('Failed to load APK QR:', error);
    }
  };

  return (
    <div className="mr-page space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Devices</h2>
        <p className="text-sm text-mute">
          Hosted UI manages agents · APK executes on the phone. Link by signing
          into the same Cognito account — QR is download-only.
        </p>
      </div>

      <Card elev className="space-y-3">
        <div className="flex items-center gap-2">
          <Download size={18} className="text-accent" />
          <h3 className="font-medium">Install APK</h3>
        </div>
        <p className="text-sm text-mute">
          Scan to download the latest GitHub release APK. After install, open
          MobileRun → complete permissions → Sign in and link phone (same
          account as this UI).
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
        <Link to="/account" className="inline-block text-sm text-accent">
          Approve a device code on Account →
        </Link>
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
              hint="Install via QR above, then sign in on the APK with your Cognito account."
              action={
                <Link to="/account" className="mr-btn-primary text-sm">
                  Open Account
                </Link>
              }
            />
          </div>
        ) : (
          devices.map((device) => (
            <DeviceCard key={device.device_id} device={device} />
          ))
        )}
      </div>
    </div>
  );
}

function DeviceCard({ device }: { device: Device }) {
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
      </div>
    </div>
  );
}
