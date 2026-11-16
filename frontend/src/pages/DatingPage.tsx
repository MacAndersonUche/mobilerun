import { useState, useEffect } from 'react';
import { Heart, Play, Pause, Square, RefreshCw } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';
import ModeSpeedPicker from '../components/ModeSpeedPicker';

type Speed = 'fast' | 'balanced' | 'careful';

interface AppStats {
  name: string;
  package: string;
  today: {
    swipes: number;
    likes: number;
    openers: number;
    replies: number;
    total_messages: number;
  };
  targets: {
    opener_target: number;
    opener_progress: number;
  };
  total: {
    swipes: number;
    openers: number;
    replies: number;
    messages: number;
    matches: number;
  };
  inbox: {
    unread: number;
    new_matches: number;
  };
  last_active: string | null;
}

interface DatingStatus {
  running: boolean;
  paused: boolean;
  current_app: string | null;
  review_queue: ReviewMessage[];
}

interface ReviewMessage {
  id: string;
  app_name: string;
  package_name: string;
  conversation_id: string;
  profile_name: string;
  message: string;
  is_opener: boolean;
}

interface AppConfig {
  name: string;
  package_name: string;
  enabled: boolean;
  daily_swipe_cap: number;
  daily_opener_target_min?: number;
  daily_opener_target_max?: number;
}

function ProgressBar({
  value,
  max,
  label,
}: {
  value: number;
  max: number;
  label: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-gray-400">
        <span>{label}</span>
        <span>
          {value}/{max || '—'} ({pct}%)
        </span>
      </div>
      <div className="h-2 bg-gray-700 rounded overflow-hidden">
        <div
          className="h-full bg-rose-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function DatingPage() {
  const [status, setStatus] = useState<DatingStatus | null>(null);
  const [apps, setApps] = useState<AppStats[]>([]);
  const [configApps, setConfigApps] = useState<AppConfig[]>([]);
  const [persona, setPersona] = useState('');
  const [reviewBeforeSend, setReviewBeforeSend] = useState(true);
  const [reviewQueue, setReviewQueue] = useState<ReviewMessage[]>([]);
  const [globalMin, setGlobalMin] = useState(100);
  const [globalMax, setGlobalMax] = useState(500);
  const [todayMessages, setTodayMessages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speed, setSpeed] = useState<Speed>('balanced');

  const authHeaders = () => ({
    Authorization: `Bearer ${getAuthToken()}`,
  });

  const loadAll = async () => {
    try {
      const [statusRes, statsRes, configRes, queueRes] = await Promise.all([
        axios.get(`${getBackendUrl()}/api/dating/status`, {
          headers: authHeaders(),
        }),
        axios.get(`${getBackendUrl()}/api/dating/stats`, {
          headers: authHeaders(),
        }),
        axios.get(`${getBackendUrl()}/api/dating/config`, {
          headers: authHeaders(),
        }),
        axios.get(`${getBackendUrl()}/api/dating/review-queue`, {
          headers: authHeaders(),
        }),
      ]);
      setStatus(statusRes.data);
      setApps(statsRes.data.apps || []);
      setTodayMessages(statsRes.data.today?.messages || 0);
      setConfigApps(configRes.data.apps || []);
      setPersona(configRes.data.persona_prompt || '');
      setReviewBeforeSend(configRes.data.review_before_send ?? true);
      setGlobalMin(configRes.data.min_total_messages_per_day ?? 100);
      setGlobalMax(configRes.data.max_total_messages_per_day ?? 500);
      if (['fast', 'balanced', 'careful'].includes(configRes.data.speed_preset)) {
        setSpeed(configRes.data.speed_preset);
      }
      setReviewQueue(queueRes.data.messages || []);
      setError(null);
    } catch (e: unknown) {
      console.error(e);
      setError('Failed to load dating mode. Is the backend running and authenticated?');
    }
  };

  useEffect(() => {
    loadAll();
    const interval = setInterval(loadAll, 4000);
    return () => clearInterval(interval);
  }, []);

  const control = async (action: 'start' | 'stop' | 'pause') => {
    setLoading(true);
    try {
      await axios.post(
        `${getBackendUrl()}/api/dating/${action}`,
        {},
        { headers: authHeaders() }
      );
      await loadAll();
    } catch (e) {
      console.error(e);
      alert(`Failed to ${action} dating mode`);
    } finally {
      setLoading(false);
    }
  };

  const saveConfig = async () => {
    setLoading(true);
    try {
      await axios.post(
        `${getBackendUrl()}/api/dating/config`,
        {
          enabled_apps: configApps
            .filter((a) => a.enabled)
            .map((a) => a.package_name),
          round_robin: true,
          review_before_send: reviewBeforeSend,
          persona_prompt: persona,
          active_hours_start: '09:00',
          active_hours_end: '23:00',
          min_total_messages_per_day: globalMin,
          max_total_messages_per_day: globalMax,
          speed_preset: speed,
        },
        { headers: authHeaders() }
      );
      await axios.post(
        `${getBackendUrl()}/api/mode`,
        { mode: 'dating', speed_preset: speed },
        { headers: authHeaders() }
      );
      await loadAll();
    } catch (e) {
      console.error(e);
      alert('Failed to save config');
    } finally {
      setLoading(false);
    }
  };

  const onSpeedChange = async (next: Speed) => {
    setSpeed(next);
    try {
      await axios.post(
        `${getBackendUrl()}/api/mode`,
        { mode: 'dating', speed_preset: next },
        { headers: authHeaders() }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const toggleApp = (packageName: string) => {
    setConfigApps((prev) =>
      prev.map((a) =>
        a.package_name === packageName ? { ...a, enabled: !a.enabled } : a
      )
    );
  };

  const reviewAction = async (
    id: string,
    action: 'approve' | 'reject',
    edited?: string
  ) => {
    try {
      if (edited) {
        await axios.post(
          `${getBackendUrl()}/api/dating/review/${id}/edit`,
          {
            id,
            app_name: '',
            package_name: '',
            conversation_id: '',
            profile_name: '',
            message: edited,
            is_opener: false,
          },
          { headers: authHeaders() }
        );
      }
      await axios.post(
        `${getBackendUrl()}/api/dating/review/${id}/${action}`,
        {},
        { headers: authHeaders() }
      );
      await loadAll();
    } catch (e) {
      console.error(e);
      alert(`Failed to ${action} message`);
    }
  };

  const statusLabel = !status?.running
    ? 'Stopped'
    : status.paused
      ? 'Paused'
      : 'Running';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold flex items-center gap-2">
            <Heart className="text-rose-400" /> Dating Mode
          </h2>
          <p className="text-gray-400 mt-1">
            Sequential messaging · human-like pacing · per-app caps
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`px-3 py-1 rounded text-sm ${
              status?.running && !status.paused
                ? 'bg-green-900 text-green-300'
                : status?.paused
                  ? 'bg-yellow-900 text-yellow-300'
                  : 'bg-gray-700 text-gray-300'
            }`}
          >
            {statusLabel}
            {status?.current_app ? ` · ${status.current_app}` : ''}
          </span>
          <button
            onClick={() => loadAll()}
            className="p-2 rounded bg-gray-700 hover:bg-gray-600"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-200 px-4 py-3 rounded">
          {error}
        </div>
      )}

      <ModeSpeedPicker
        mode="dating"
        speed={speed}
        hideMode
        onSpeedChange={onSpeedChange}
      />

      {/* Controls */}
      <div className="flex gap-3">
        <button
          disabled={loading || status?.running}
          onClick={() => control('start')}
          className="flex items-center gap-2 px-4 py-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 rounded"
        >
          <Play size={16} /> Start
        </button>
        <button
          disabled={loading || !status?.running}
          onClick={() => control('pause')}
          className="flex items-center gap-2 px-4 py-2 bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 rounded"
        >
          <Pause size={16} /> {status?.paused ? 'Resume' : 'Pause'}
        </button>
        <button
          disabled={loading || !status?.running}
          onClick={() => control('stop')}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded"
        >
          <Square size={16} /> Stop
        </button>
      </div>

      {/* Global progress */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
        <h3 className="text-lg font-semibold">Today · All Apps</h3>
        <ProgressBar
          value={todayMessages}
          max={globalMax}
          label={`Auto messages (openers + replies) · target range ${globalMin}–${globalMax}`}
        />
        <div className="grid grid-cols-2 gap-4 pt-2">
          <label className="text-sm">
            Global min/day
            <input
              type="number"
              value={globalMin}
              onChange={(e) => setGlobalMin(Number(e.target.value))}
              className="mt-1 w-full bg-gray-900 border border-gray-600 rounded px-3 py-2"
            />
          </label>
          <label className="text-sm">
            Global max/day
            <input
              type="number"
              value={globalMax}
              onChange={(e) => setGlobalMax(Number(e.target.value))}
              className="mt-1 w-full bg-gray-900 border border-gray-600 rounded px-3 py-2"
            />
          </label>
        </div>
      </div>

      {/* Per-app stats */}
      <div className="grid md:grid-cols-2 gap-4">
        {(apps.length ? apps : configApps.map((a) => ({
          name: a.name,
          package: a.package_name,
          today: { swipes: 0, likes: 0, openers: 0, replies: 0, total_messages: 0 },
          targets: { opener_target: 75, opener_progress: 0 },
          total: { swipes: 0, openers: 0, replies: 0, messages: 0, matches: 0 },
          inbox: { unread: 0, new_matches: 0 },
          last_active: null,
        }))).map((app) => (
          <div
            key={app.package}
            className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3"
          >
            <div className="flex justify-between items-start">
              <div>
                <h4 className="font-semibold text-lg">{app.name}</h4>
                <p className="text-xs text-gray-500">{app.package}</p>
              </div>
              <div className="text-right text-sm text-gray-400">
                <div>{app.inbox.unread} unread</div>
                <div>{app.inbox.new_matches} new matches</div>
              </div>
            </div>
            <ProgressBar
              value={app.targets.opener_progress}
              max={app.targets.opener_target || 75}
              label="Openers vs daily target"
            />
            <div className="grid grid-cols-3 gap-2 text-sm">
              <div className="bg-gray-900 rounded p-2 text-center">
                <div className="text-gray-400 text-xs">Swipes</div>
                <div className="font-semibold">{app.today.swipes}</div>
              </div>
              <div className="bg-gray-900 rounded p-2 text-center">
                <div className="text-gray-400 text-xs">Openers</div>
                <div className="font-semibold">{app.today.openers}</div>
              </div>
              <div className="bg-gray-900 rounded p-2 text-center">
                <div className="text-gray-400 text-xs">Replies</div>
                <div className="font-semibold">{app.today.replies}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* App toggles + persona */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-4">
        <h3 className="text-lg font-semibold">Apps & Persona</h3>
        <div className="flex flex-wrap gap-2">
          {configApps.map((app) => (
            <button
              key={app.package_name}
              onClick={() => toggleApp(app.package_name)}
              className={`px-3 py-1 rounded text-sm border ${
                app.enabled
                  ? 'bg-rose-900/50 border-rose-600 text-rose-200'
                  : 'bg-gray-900 border-gray-600 text-gray-500'
              }`}
            >
              {app.name}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={reviewBeforeSend}
            onChange={(e) => setReviewBeforeSend(e.target.checked)}
          />
          Review before send (sequential queue)
        </label>
        <label className="block text-sm">
          Persona / style prompt
          <textarea
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            rows={6}
            className="mt-1 w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 font-mono text-sm"
          />
        </label>
        <button
          onClick={saveConfig}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded"
        >
          Save config
        </button>
      </div>

      {/* Review queue */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
        <h3 className="text-lg font-semibold">
          Review Queue ({reviewQueue.length})
        </h3>
        {reviewQueue.length === 0 ? (
          <p className="text-gray-500 text-sm">No messages waiting for review.</p>
        ) : (
          reviewQueue.map((msg) => (
            <div
              key={msg.id}
              className="bg-gray-900 border border-gray-700 rounded p-3 space-y-2"
            >
              <div className="flex justify-between text-sm">
                <span>
                  {msg.app_name} · {msg.profile_name}
                  {msg.is_opener ? ' · opener' : ' · reply'}
                </span>
                <span className="text-gray-500">{msg.id}</span>
              </div>
              <textarea
                defaultValue={msg.message}
                id={`msg-${msg.id}`}
                rows={2}
                className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    const el = document.getElementById(
                      `msg-${msg.id}`
                    ) as HTMLTextAreaElement;
                    reviewAction(msg.id, 'approve', el?.value);
                  }}
                  className="px-3 py-1 bg-green-700 hover:bg-green-600 rounded text-sm"
                >
                  Approve & send
                </button>
                <button
                  onClick={() => reviewAction(msg.id, 'reject')}
                  className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
                >
                  Reject
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
