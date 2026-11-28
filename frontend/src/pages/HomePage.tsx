import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import {
  Heart,
  Smartphone,
  MessageCircle,
  History,
  ChevronRight,
} from 'lucide-react';
import { getAuthToken, getBackendUrl } from '../config';
import { Card } from '../components/ui';
import { useAuth } from '../auth';

type Device = {
  device_id: string;
  name: string;
  connected: boolean;
  route?: string;
  latency_ms?: number;
};

const NAV_TILES: {
  to: string;
  title: string;
  subtitle: string;
  icon: typeof Heart;
  accent: string;
}[] = [
  {
    to: '/dating',
    title: 'Dating',
    subtitle: 'Auto swipe, first contact, likes',
    icon: Heart,
    accent: 'text-rose-400',
  },
  {
    to: '/social',
    title: 'Social',
    subtitle: 'Message or reply on social apps',
    icon: MessageCircle,
    accent: 'text-sky-400',
  },
  {
    to: '/tasks',
    title: 'Tasks',
    subtitle: 'One-off agent jobs on your phone',
    icon: History,
    accent: 'text-amber-300',
  },
  {
    to: '/devices',
    title: 'Devices',
    subtitle: 'Connect a phone · install APK',
    icon: Smartphone,
    accent: 'text-accent',
  },
];

export default function HomePage() {
  const { email } = useAuth();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    <div className="mr-page space-y-6" data-testid="home-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">MacMobileRun</h1>
          <p className="text-sm text-mute">Dating & social on your phone</p>
        </div>
        <Link
          to="/settings"
          className="tap-target flex items-center justify-center rounded-full bg-accent text-sm font-semibold"
          title="Settings"
          aria-label="Open settings"
        >
          {(email || 'M').slice(0, 1).toUpperCase()}
        </Link>
      </header>

      <div className="grid gap-3 sm:grid-cols-2" data-testid="home-nav-tiles">
        {NAV_TILES.map((tile) => {
          const Icon = tile.icon;
          const devicesSubtitle =
            tile.to === '/devices'
              ? devices === null
                ? 'Loading…'
                : devices.length === 0
                  ? 'Connect a phone'
                  : `${online} online · ${offline} offline`
              : tile.subtitle;
          return (
            <Link key={tile.to} to={tile.to} className="block">
              <Card elev className="flex items-center gap-3">
                <Icon className={tile.accent} size={22} />
                <div className="min-w-0">
                  <p className="font-medium">{tile.title}</p>
                  <p className="text-sm text-mute">{devicesSubtitle}</p>
                </div>
                <ChevronRight size={16} className="ml-auto shrink-0 text-mute" />
              </Card>
            </Link>
          );
        })}
      </div>

      {error && (
        <p className="text-sm text-mute" role="status">
          {error} - check Settings → Backend URL
        </p>
      )}
    </div>
  );
}
