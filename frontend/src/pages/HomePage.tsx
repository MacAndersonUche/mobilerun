import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Plus, Smartphone, Activity, ChevronRight } from 'lucide-react';
import { getAuthToken, getBackendUrl } from '../config';
import { Badge, Card, EmptyState, LoadingBlock } from '../components/ui';
import { useAuth } from '../auth';

type Device = {
  device_id: string;
  name: string;
  connected: boolean;
  route?: string;
  latency_ms?: number;
};

const AGENTS = [
  { id: 'mac', name: 'Mac', color: 'bg-blue-500', focus: 'Everyday phone tasks' },
  { id: 'dating', name: 'Dating', color: 'bg-rose-500', focus: 'Openers & replies' },
  { id: 'social', name: 'Social', color: 'bg-emerald-500', focus: 'Chats & unread' },
];

export default function HomePage() {
  const { email } = useAuth();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [badge, setBadge] = useState(0);
  const [error, setError] = useState<string | null>(null);

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
      } catch (e: unknown) {
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
          <h1 className="text-2xl font-semibold tracking-tight">Your agents</h1>
          <p className="text-sm text-mute">MobileRun by MacAI</p>
        </div>
        <Link
          to="/account"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-sm font-semibold"
          title="Account"
        >
          {(email || 'M').slice(0, 1).toUpperCase()}
        </Link>
      </header>

      <Card className="border-accent/30 bg-accent/10">
        <p className="text-sm font-medium text-blue-200">
          Getting started · {Math.min(3, (devices?.length ? 1 : 0) + 1 + (badge ? 1 : 0))} of 3
        </p>
        <p className="mt-1 text-sm text-mute">
          Sign in, link a phone, then ask an agent to run a task.
        </p>
      </Card>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-medium text-mute">Agents</h2>
          <Link to="/chat" className="text-xs text-accent">
            Open chat
          </Link>
        </div>
        <div className="no-scrollbar flex gap-3 overflow-x-auto pb-1">
          {AGENTS.map((a) => (
            <Link
              key={a.id}
              to={a.id === 'mac' ? '/chat' : a.id === 'dating' ? '/dating' : '/social'}
              className="min-w-[112px] rounded-2xl border border-line bg-surface p-3"
            >
              <div
                className={`mb-3 flex h-12 w-12 items-center justify-center rounded-2xl ${a.color} text-lg font-bold`}
              >
                {a.name.slice(0, 1)}
              </div>
              <p className="text-sm font-medium">{a.name}</p>
              <p className="text-[11px] text-mute">{a.focus}</p>
            </Link>
          ))}
          <button
            type="button"
            className="min-w-[96px] rounded-2xl border border-dashed border-line bg-canvas-elev p-3 text-mute"
            title="New agent soon"
          >
            <Plus className="mx-auto mb-3" />
            <span className="text-sm">New</span>
          </button>
        </div>
      </section>

      <Card>
        <p className="text-xs font-medium uppercase tracking-wide text-mute">
          Coming up
        </p>
        <p className="mt-2 text-sm text-mute">
          No routine planned yet — Build one with{' '}
          <Link to="/chat" className="text-accent">
            Mac
          </Link>
          .
        </p>
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Smartphone size={18} className="text-accent" />
            <h2 className="font-medium">Devices</h2>
          </div>
          <Link to="/devices" className="text-sm text-accent flex items-center gap-1">
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
            hint="Install the APK and sign in on the phone — or use QR fallback."
            action={
              <Link to="/devices" className="mr-btn-primary text-sm">
                Pair / download APK
              </Link>
            }
          />
        ) : (
          <div className="flex gap-4 text-sm">
            <div>
              <span className="mr-1 inline-block h-2 w-2 rounded-full bg-ok" />
              Online {online}
            </div>
            <div>
              <span className="mr-1 inline-block h-2 w-2 rounded-full bg-mute" />
              Busy 0
            </div>
            <div>
              <span className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />
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
              <p className="text-sm text-mute">
                Escalated Social & Dating drafts
              </p>
            </div>
          </div>
          {badge > 0 ? <Badge tone="warn">{badge}</Badge> : <Badge>0</Badge>}
        </Card>
      </Link>

      <Link to="/history" className="block">
        <Card>
          <p className="font-medium">All activity</p>
          <p className="text-sm text-mute">Every run and chat of your agents</p>
        </Card>
      </Link>
    </div>
  );
}
