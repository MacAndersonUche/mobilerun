import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Send, Sparkles, Settings2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { getAuthToken, getBackendUrl, getHostedBackendUrl } from '../config';
import ModeSpeedPicker from '../components/ModeSpeedPicker';
import { Badge, Button, Card, Sheet } from '../components/ui';

type Mode = 'normal' | 'dating' | 'social';
type Speed = 'fast' | 'balanced' | 'careful';

type Msg = {
  id?: string;
  role: string;
  content: string;
  meta?: Record<string, unknown>;
};

export default function ChatPage() {
  const [target, setTarget] = useState<'pc' | 'hosted'>('hosted');
  const [deviceId, setDeviceId] = useState('');
  const [devices, setDevices] = useState<{ device_id: string; name?: string; connected?: boolean; latency_ms?: number }[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<{
    intent?: string;
    params?: Record<string, unknown>;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>('normal');
  const [speed, setSpeed] = useState<Speed>('balanced');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const apiBase = () =>
    target === 'hosted' ? getHostedBackendUrl() : getBackendUrl();

  useEffect(() => {
    (async () => {
      try {
        const res = await axios.get(`${apiBase()}/api/devices`, {
          headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        setDevices(res.data || []);
        if (res.data?.[0]?.device_id) setDeviceId(res.data[0].device_id);
      } catch {
        /* offline ok */
      }
      try {
        const modeRes = await axios.get(`${apiBase()}/api/mode`, {
          headers: { Authorization: `Bearer ${getAuthToken()}` },
        });
        if (['normal', 'dating', 'social'].includes(modeRes.data.mode)) {
          setMode(modeRes.data.mode);
        }
        if (['fast', 'balanced', 'careful'].includes(modeRes.data.speed_preset)) {
          setSpeed(modeRes.data.speed_preset);
        }
      } catch {
        /* defaults */
      }
    })();
  }, [target]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const persistMode = async (nextMode: Mode, nextSpeed: Speed) => {
    setMode(nextMode);
    setSpeed(nextSpeed);
    try {
      await axios.post(
        `${apiBase()}/api/mode`,
        { mode: nextMode, speed_preset: nextSpeed },
        { headers: { Authorization: `Bearer ${getAuthToken()}` } }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const send = async (confirmed = false) => {
    if (!input.trim() && !confirmed) return;
    const text = input.trim() || '(confirmed)';
    setBusy(true);
    try {
      const res = await axios.post(
        `${apiBase()}/api/chat`,
        {
          message: confirmed && pendingConfirm ? input || 'confirm' : text,
          session_id: sessionId,
          device_id: deviceId || null,
          target,
          confirmed,
        },
        { headers: { Authorization: `Bearer ${getAuthToken()}` } }
      );
      setSessionId(res.data.session_id);
      setMessages(res.data.history || []);
      if (res.data.needs_confirm) {
        setPendingConfirm({ intent: res.data.intent, params: res.data.params });
      } else {
        setPendingConfirm(null);
        setInput('');
      }
    } catch (e: unknown) {
      const detail = axios.isAxiosError(e)
        ? e.response?.data?.detail || e.message
        : 'Chat failed';
      setMessages((m) => [...m, { role: 'assistant', content: String(detail) }]);
    } finally {
      setBusy(false);
    }
  };

  const device = devices.find((d) => d.device_id === deviceId);

  return (
    <div className="mx-auto flex h-[100dvh] w-full max-w-content flex-col md:h-screen">
      <header className="flex items-center gap-3 border-b border-line px-4 py-3">
        <Link to="/" className="rounded-lg p-1 text-mute hover:bg-surface md:hidden">
          <ArrowLeft size={20} />
        </Link>
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent font-semibold">
          M
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">Mac</p>
          <p className="truncate text-xs text-mute">
            {target === 'hosted' ? 'Hosted' : 'My PC'} · {mode} · {speed}
          </p>
        </div>
        <button
          type="button"
          className="rounded-lg p-2 text-mute hover:bg-surface"
          onClick={() => setSettingsOpen(true)}
        >
          <Settings2 size={20} />
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {device && (
          <Card className="flex items-center justify-between gap-2 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {device.name || device.device_id}
              </p>
              <p className="text-xs text-mute">
                {device.latency_ms != null
                  ? `${Math.round(device.latency_ms)} ms`
                  : '—'}
              </p>
            </div>
            <Badge tone={device.connected ? 'ok' : 'mute'}>
              {device.connected ? 'Ready' : 'Offline'}
            </Badge>
          </Card>
        )}

        {messages.length === 0 && (
          <div className="rounded-2xl border border-line bg-surface p-4 text-sm text-mute">
            Ask Mac to open Settings, check unread, switch modes, or start dating
            dry. Try follow-ups below.
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={m.id || i}
            className={
              m.role === 'user'
                ? 'ml-auto max-w-[85%] rounded-2xl bg-surface-elev px-3 py-2 text-sm'
                : 'mr-auto max-w-[90%] space-y-2'
            }
          >
            {m.role === 'user' ? (
              m.content
            ) : (
              <Card className="text-sm whitespace-pre-wrap">{m.content}</Card>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {pendingConfirm && (
        <div className="mx-4 mb-2 flex items-center justify-between gap-2 rounded-xl border border-amber-800 bg-amber-950/40 px-3 py-2 text-sm">
          <span>Confirm `{String(pendingConfirm.intent)}`?</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setPendingConfirm(null)}>
              Cancel
            </Button>
            <Button onClick={() => send(true)} disabled={busy}>
              Confirm
            </Button>
          </div>
        </div>
      )}

      <div className="border-t border-line bg-canvas-elev px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 md:pb-3">
        <div className="no-scrollbar mb-2 flex gap-2 overflow-x-auto">
          {['device info', 'needs you', 'switch to social', 'open Settings'].map(
            (s) => (
              <button
                key={s}
                type="button"
                className="shrink-0 rounded-full border border-line px-3 py-1 text-xs text-mute"
                onClick={() => setInput(s)}
              >
                {s} →
              </button>
            )
          )}
        </div>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(false);
          }}
        >
          <div className="relative flex-1">
            <Sparkles
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-accent"
            />
            <input
              className="mr-input pl-9"
              placeholder="Ask Mac…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
            />
          </div>
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="flex h-11 w-11 items-center justify-center rounded-full bg-accent disabled:opacity-40"
          >
            <Send size={18} />
          </button>
        </form>
      </div>

      <Sheet
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        title="Mac · Settings"
      >
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-sm text-mute">Execute on</p>
            <div className="flex overflow-hidden rounded-xl border border-line">
              <button
                type="button"
                className={`flex-1 py-2 text-sm ${
                  target === 'pc' ? 'bg-accent' : 'bg-surface-elev'
                }`}
                onClick={() => setTarget('pc')}
              >
                My PC
              </button>
              <button
                type="button"
                className={`flex-1 py-2 text-sm ${
                  target === 'hosted' ? 'bg-accent' : 'bg-surface-elev'
                }`}
                onClick={() => setTarget('hosted')}
              >
                Hosted
              </button>
            </div>
          </div>
          <select
            className="mr-input"
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
          >
            <option value="">No device</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.name || d.device_id}
              </option>
            ))}
          </select>
          <ModeSpeedPicker
            mode={mode}
            speed={speed}
            onModeChange={(m) => persistMode(m, speed)}
            onSpeedChange={(s) => persistMode(mode, s)}
          />
          <p className="text-xs text-mute break-all">{apiBase()}</p>
        </div>
      </Sheet>
    </div>
  );
}
