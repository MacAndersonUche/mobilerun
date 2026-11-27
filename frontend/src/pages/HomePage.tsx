import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Heart, Smartphone, ChevronRight } from 'lucide-react';
import { getAuthToken, getBackendUrl } from '../config';
import { Card } from '../components/ui';
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
  const [error, setError] = useState<string | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const headers = { Authorization: `Bearer ${getAuthToken()}` };
        const d = await axios.get(`${getBackendUrl()}/api/devices`, { headers });
        if (!alive) return;
        setDevices(d.data || []);
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
          className="tap-target flex items-center justify-center rounded-full bg-accent text-sm font-semibold"
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
              <p className="text-sm text-mute">
                Auto swipe, message new contacts, reply to chats
              </p>
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

      {error && (
        <p className="text-sm text-mute" role="status">
          {error} — check Settings → Backend URL
        </p>
      )}

      <AccountSheet open={accountOpen} onClose={() => setAccountOpen(false)} />
    </div>
  );
}
