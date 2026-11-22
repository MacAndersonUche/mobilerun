import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Heart, Smartphone, ChevronRight, Activity } from 'lucide-react';
import { getAuthToken, getBackendUrl } from '../config';
import { Badge, Card, EmptyState, LoadingBlock } from '../components/ui';
import AccountSheet from '../components/AccountSheet';
import { useAuth } from '../auth';

type Device = {
  device_id: string;
  name: string;
  connected: boolean;
  route?: string;
  latency_ms?: number;
};

export default function HomePage() {
  const { email } = useAuth();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [badge, setBadge] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const headers = { Authorization: `Bearer ${getAuthToken()}` };
        const [d, ny] = await Promise.all([
          axios.get(`${getBackendUrl()}/api/devices`, { headers }),
          axios.get(`${getBackendUrl()}/api/needs-you`, { headers }).catch(() => ({
            data: { badge: 0 },
          })),
        ]);
        if (!alive) return;
        setDevices(d.data || []);
        setBadge(ny.data.badge || 0);
        setError(null);
      } catch {
        if (!alive) return;
        setDevices([]);
        setError('Could not reach backend');
      }
    };
    load();
    const t = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const online = devices?.filter((d) => d.connected).length ?? 0;
  const offline = (devices?.length ?? 0) - online;

  return (
    <div className="mr-page space-y-5">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">MacMobileRun</h1>
          <p className="text-sm text-mute">Dating & social runs on your phone</p>
        </div>
        <button
          type="button"
          onClick={() => setAccountOpen(true)}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-sm font-semibold"
          title="Account"
          aria-label="Open account"
        >
          {(email || 'M').slice(0, 1).toUpperCase()}
        </button>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <Link to="/dating" className="block">
          <Card elev className="flex items-center gap-3">
            <Heart className="text-rose-400" size={22} />
            <div>
              <p className="font-medium">Run</p>
              <p className="text-sm text-mute">Dating openers, dry-run, activity</p>
            </div>
            <ChevronRight size={16} className="ml-auto text-mute" />
          </Card>
        </Link>
        <Link to="/devices" className="block">
          <Card elev className="flex items-center gap-3">
            <Smartphone className="text-accent" size={22} />
            <div>
              <p className="font-medium">Devices</p>
              <p className="text-sm text-mute">
                {devices === null
                  ? 'Loading…'
                  : devices.length === 0
                    ? 'Connect a phone'
                    : `${online} online · ${offline} offline`}
              </p>
            </div>
            <ChevronRight size={16} className="ml-auto text-mute" />
          </Card>
        </Link>
      </div>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Smartphone size={18} className="text-accent" />
            <h2 className="font-medium">Devices</h2>
          </div>
          <Link to="/devices" className="flex items-center gap-1 text-sm text-accent">
            Manage <ChevronRight size={14} />
          </Link>
        </div>
        {devices === null ? (
          <LoadingBlock />
        ) : error ? (
          <EmptyState title={error} hint="Check Settings → Backend URL" />
        ) : devices.length === 0 ? (
          <EmptyState
            title="No devices yet"
            hint="Scan the APK download QR, then sign in on the phone with the same account."
            action={
              <Link to="/devices" className="mr-btn-primary text-sm">
                Download APK
              </Link>
            }
          />
        ) : (
          <div className="flex flex-wrap gap-4 text-sm">
            <div>
              <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-ok" />
              Online {online}
            </div>
            <div>
              <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-red-500" />
              Offline {offline}
            </div>
          </div>
        )}
      </Card>

      <Link to="/needs-you" className="block">
        <Card elev className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity className="text-amber-300" size={20} />
            <div>
              <p className="font-medium">Needs you</p>
              <p className="text-sm text-mute">Escalated Social & Dating drafts</p>
            </div>
          </div>
          {badge > 0 ? <Badge tone="warn">{badge}</Badge> : <Badge>0</Badge>}
        </Card>
      </Link>

      <AccountSheet open={accountOpen} onClose={() => setAccountOpen(false)} />
    </div>
  );
}
