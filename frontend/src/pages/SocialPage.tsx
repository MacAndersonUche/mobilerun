import { useEffect, useState } from 'react';
import { MessageCircle, Play, Square } from 'lucide-react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { getAuthToken, getBackendUrl } from '../config';
import { canMessageApp, socialRunBody } from '../lib/socialRun';
import ModeSpeedPicker from '../components/ModeSpeedPicker';
import LiveActivityFeed, {
  ActivityPayload,
} from '../components/LiveActivityFeed';

type Speed = 'fast' | 'balanced' | 'careful';

type AppRow = {
  name: string;
  package_name: string;
  enabled: boolean;
};

export default function SocialPage() {
  const [apps, setApps] = useState<AppRow[]>([]);
  const [speed, setSpeed] = useState<Speed>('balanced');
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [activity, setActivity] = useState<ActivityPayload | null>(null);
  const [deviceId, setDeviceId] = useState('');
  const [runApp, setRunApp] = useState('com.whatsapp');
  const [contact, setContact] = useState('');
  const [msgText, setMsgText] = useState('');
  const [devices, setDevices] = useState<
    Array<{ device_id: string; name?: string; connected?: boolean }>
  >([]);

  const headers = () => ({ Authorization: `Bearer ${getAuthToken()}` });

  const load = async () => {
    try {
      const [cfg, status] = await Promise.all([
        axios.get(`${getBackendUrl()}/api/social/config`, { headers: headers() }),
        axios.get(`${getBackendUrl()}/api/social/status`, { headers: headers() }),
      ]);
      setApps(cfg.data.apps || []);
      setSpeed(cfg.data.speed_preset || 'balanced');
      setRunning(!!status.data.running);
      setPaused(!!status.data.paused);
      setUnread(status.data.unread?.total_unread || 0);
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
      await axios.post(
        `${getBackendUrl()}/api/social/config`,
        {
          enabled_apps: apps.filter((a) => a.enabled).map((a) => a.package_name),
          speed_preset: speed,
          // Signature / notifications removed from portal; keep backend off.
          signature_enabled: false,
          signature_text: '',
          per_app_signature: {},
          always_ask_new_contacts: false,
          email_notify: false,
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

  const runSocial = async (action: 'message' | 'reply') => {
    setLoading(true);
    try {
      const res = await axios.post(
        `${getBackendUrl()}/api/social/run`,
        socialRunBody({ deviceId, app: runApp, action, contact, message: msgText }),
        { headers: headers() }
      );
      setRunning(true);
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
              dry_run: false,
              stand_in_package: 'com.google.android.apps.messaging',
              max_steps: 40,
            }
          : {};
      const res = await axios.post(
        `${getBackendUrl()}/api/social/${action}`,
        body,
        { headers: headers() }
      );
      // Apply start/stop response immediately; status may hit another Lambda
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
            Dating
          </Link>
          . WhatsApp, Messenger, X, Snapchat, Instagram - unread counts + auto
          replies with humanizer pacing.
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
          disabled={loading || !running}
          onClick={() => control('stop')}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded"
          data-testid="social-stop"
        >
          <Square size={16} /> Stop
        </button>
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

      <div className="bg-surface border border-line rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">Message or reply</h3>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <select
            className="mr-input text-sm sm:max-w-xs"
            value={runApp}
            onChange={(e) => setRunApp(e.target.value)}
            data-testid="social-run-app"
            aria-label="Social app"
          >
            {apps
              .filter((a) => canMessageApp(a.package_name))
              .map((a) => (
                <option key={a.package_name} value={a.package_name}>
                  {a.name}
                </option>
              ))}
          </select>
          <input
            className="mr-input text-sm sm:max-w-xs"
            placeholder="Person's name (for Message this person)"
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            data-testid="social-run-contact"
            aria-label="Person's name"
          />
          <input
            className="mr-input text-sm sm:flex-1"
            placeholder="Message"
            value={msgText}
            onChange={(e) => setMsgText(e.target.value)}
            data-testid="social-run-message"
            aria-label="Message"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={loading || !contact.trim() || !msgText.trim()}
            onClick={() => runSocial('message')}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded text-sm"
            data-testid="social-message-person"
          >
            <Play size={16} /> Message this person
          </button>
          <button
            type="button"
            disabled={loading || !msgText.trim()}
            onClick={() => runSocial('reply')}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-800 hover:bg-emerald-700 disabled:opacity-50 rounded text-sm"
            data-testid="social-reply"
          >
            <MessageCircle size={16} /> Reply to messages
          </button>
        </div>
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

      <button
        onClick={save}
        disabled={loading}
        className="px-4 py-2 bg-accent hover:bg-accent-soft disabled:opacity-50 rounded"
        data-testid="social-save-config"
      >
        Save config
      </button>
    </div>
  );
}
