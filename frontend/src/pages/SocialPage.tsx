import { useEffect, useState } from 'react';
import { MessageCircle, Play, Pause, Square } from 'lucide-react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { getAuthToken, getBackendUrl } from '../config';
import ModeSpeedPicker from '../components/ModeSpeedPicker';
import LiveActivityFeed, {
  ActivityPayload,
} from '../components/LiveActivityFeed';

type Speed = 'fast' | 'balanced' | 'careful';

type AppRow = {
  name: string;
  package_name: string;
  enabled: boolean;
  signature_enabled?: boolean | null;
};

export default function SocialPage() {
  const [apps, setApps] = useState<AppRow[]>([]);
  const [speed, setSpeed] = useState<Speed>('balanced');
  const [sigOn, setSigOn] = useState(true);
  const [sigText, setSigText] = useState('— from MacMobileRun');
  const [askNew, setAskNew] = useState(true);
  const [emailNotify, setEmailNotify] = useState(false);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [unread, setUnread] = useState(0);
  const [badge, setBadge] = useState(0);
  const [loading, setLoading] = useState(false);
  const [activity, setActivity] = useState<ActivityPayload | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [deviceId, setDeviceId] = useState('');
  const [devices, setDevices] = useState<
    Array<{ device_id: string; name?: string; connected?: boolean }>
  >([]);

  const headers = () => ({ Authorization: `Bearer ${getAuthToken()}` });

  const load = async () => {
    try {
      const [cfg, status, ny] = await Promise.all([
        axios.get(`${getBackendUrl()}/api/social/config`, { headers: headers() }),
        axios.get(`${getBackendUrl()}/api/social/status`, { headers: headers() }),
        axios.get(`${getBackendUrl()}/api/needs-you`, { headers: headers() }),
      ]);
      setApps(cfg.data.apps || []);
      setSpeed(cfg.data.speed_preset || 'balanced');
      setSigOn(cfg.data.signature?.enabled_global ?? true);
      setSigText(cfg.data.signature?.text || '— from MacMobileRun');
      setAskNew(cfg.data.escalation?.always_ask_new_contacts ?? true);
      setEmailNotify(!!cfg.data.email_notify);
      setRunning(!!status.data.running);
      setPaused(!!status.data.paused);
      setUnread(status.data.unread?.total_unread || 0);
      setBadge(ny.data.badge || 0);
      setActivity(status.data.activity || null);
    } catch (e) {
      console.error(e);
    }
  };

  const loadDevices = async () => {
    try {
      const res = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: headers(),
      });
      const list = (res.data || []) as Array<{
        device_id: string;
        name?: string;
        connected?: boolean;
      }>;
      setDevices(list);
      const online = list.find((d) => d.connected);
      if (online && !deviceId) setDeviceId(online.device_id);
    } catch {
      /* optional */
    }
  };

  useEffect(() => {
    load();
    loadDevices();
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, []);

  const save = async () => {
    setLoading(true);
    try {
      const perApp: Record<string, boolean> = {};
      apps.forEach((a) => {
        if (a.signature_enabled != null) perApp[a.package_name] = !!a.signature_enabled;
      });
      await axios.post(
        `${getBackendUrl()}/api/social/config`,
        {
          enabled_apps: apps.filter((a) => a.enabled).map((a) => a.package_name),
          speed_preset: speed,
          signature_enabled: sigOn,
          signature_text: sigText,
          per_app_signature: perApp,
          always_ask_new_contacts: askNew,
          email_notify: emailNotify,
          email_to: 'macandersonuche@yahoo.com',
        },
        { headers: headers() }
      );
      await axios.post(
        `${getBackendUrl()}/api/mode`,
        { mode: 'social', speed_preset: speed },
        { headers: headers() }
      );
      await load();
    } catch (e) {
      console.error(e);
      alert('Failed to save');
    } finally {
      setLoading(false);
    }
  };

  const control = async (action: 'start' | 'stop' | 'pause') => {
    setLoading(true);
    try {
      if (action === 'start') {
        try {
          await axios.post(
            `${getBackendUrl()}/api/social/stop`,
            {},
            { headers: headers() }
          );
        } catch {
          /* ok */
        }
      }
      const body =
        action === 'start'
          ? {
              device_id: deviceId || undefined,
              dry_run: dryRun,
              stand_in_package: 'com.google.android.apps.messaging',
              max_steps: 6,
            }
          : {};
      const res = await axios.post(
        `${getBackendUrl()}/api/social/${action}`,
        body,
        { headers: headers() }
      );
      // Apply start/stop response immediately — status may hit another Lambda
      const st = res.data?.state;
      if (st && typeof st === 'object') {
        setRunning(!!st.running);
        setPaused(!!st.paused);
      } else if (action === 'start') {
        setRunning(true);
      } else if (action === 'stop') {
        setRunning(false);
        setPaused(false);
      }
      if (res.data?.activity) setActivity(res.data.activity);
      await load();
    } catch (e) {
      const detail = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : `Failed to ${action}`;
      alert(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mr-page space-y-6">
      <div>
        <h2 className="text-2xl font-semibold flex items-center gap-2">
          <MessageCircle className="text-emerald-400" /> Social
        </h2>
        <p className="text-mute mt-1 text-sm">
          Secondary to{' '}
          <Link to="/dating" className="text-accent underline underline-offset-2">
            Run
          </Link>
          . WhatsApp, Messenger, X, Snapchat, Instagram — unread counts + replies
          with humanizer pacing. Sensitive drafts go to{' '}
          <Link to="/needs-you" className="text-amber-300 underline">
            Needs you
          </Link>
          {badge > 0 ? ` (${badge})` : ''}.
        </p>
      </div>

      <ModeSpeedPicker
        mode="social"
        speed={speed}
        hideMode
        onSpeedChange={setSpeed}
      />

      <div className="flex flex-wrap gap-3 items-center">
        <button
          disabled={loading}
          onClick={() => control('start')}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded"
          data-testid="social-start"
          title={running ? 'Restarts social mode (stops current job first)' : 'Start social mode'}
        >
          <Play size={16} /> {running ? 'Restart' : 'Start'}
        </button>
        <button
          disabled={loading || !running}
          onClick={() => control('pause')}
          className="flex items-center gap-2 px-4 py-2 bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 rounded"
        >
          <Pause size={16} /> {paused ? 'Resume' : 'Pause'}
        </button>
        <button
          disabled={loading || !running}
          onClick={() => control('stop')}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded"
          data-testid="social-stop"
        >
          <Square size={16} /> Stop
        </button>
        <label className="flex items-center gap-2 text-sm text-mute">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            data-testid="social-dry-run"
          />
          Dry-run (no real messages)
        </label>
        {devices.length > 0 && (
          <select
            className="mr-input text-sm max-w-xs"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            data-testid="social-device"
            aria-label="Social device"
          >
            <option value="">Select device…</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {(d.connected ? '● ' : '○ ') + (d.name || d.device_id)}
              </option>
            ))}
          </select>
        )}
        <span className="text-sm text-mute ml-auto">Unread · {unread}</span>
      </div>

      <LiveActivityFeed
        title="Social live activity"
        activity={activity}
        loading={running && !paused}
      />

      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">Apps</h3>
        <div className="flex flex-wrap gap-2">
          {apps.map((app) => (
            <button
              key={app.package_name}
              type="button"
              onClick={() =>
                setApps((prev) =>
                  prev.map((a) =>
                    a.package_name === app.package_name
                      ? { ...a, enabled: !a.enabled }
                      : a
                  )
                )
              }
              className={`px-3 py-1 rounded text-sm border ${
                app.enabled
                  ? 'bg-emerald-900/50 border-emerald-600 text-emerald-100'
                  : 'bg-canvas-elev border-line text-mute'
              }`}
            >
              {app.name}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">Signature</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={sigOn}
            onChange={(e) => setSigOn(e.target.checked)}
          />
          Append signature (default ON)
        </label>
        <label htmlFor="social-signature-text" className="block text-sm text-mute">
          Signature text
        </label>
        <input
          id="social-signature-text"
          value={sigText}
          onChange={(e) => setSigText(e.target.value)}
          className="mr-input"
          aria-label="Signature text"
        />
        <p className="text-xs text-mute">
          Per-app / per-contact overrides are stored with config; toggle apps above,
          then use API or chat for contact-level overrides.
        </p>
      </div>

      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">Escalation</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={askNew}
            onChange={(e) => setAskNew(e.target.checked)}
          />
          Always ask for new contacts
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={emailNotify}
            onChange={(e) => setEmailNotify(e.target.checked)}
          />
          Email notify (SES → macandersonuche@yahoo.com, off by default)
        </label>
        <p className="text-xs text-mute">
          Money, commitments, plans/times, personal info, and low confidence always
          escalate to Needs you (UI badge + APK push).
        </p>
      </div>

      <button
        onClick={save}
        disabled={loading}
        className="px-4 py-2 bg-accent hover:bg-accent-soft disabled:opacity-50 rounded"
      >
        Save config
      </button>
    </div>
  );
}
