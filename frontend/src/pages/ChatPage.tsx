import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Send, Sparkles, Settings2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { getAuthToken, getBackendUrl, getHostedBackendUrl } from '../config';
import { Badge, Button } from '../components/ui';
import { PixelAvatar } from '../components/PixelAvatar';
import AgentSettingsSheet from '../components/AgentSettingsSheet';
import AgentMessageCard, {
  parseAgentContent,
  type AgentPayload,
} from '../components/AgentMessageCard';

type Mode = 'normal' | 'dating' | 'social';
type Speed = 'fast' | 'balanced' | 'careful';
type ModelTier = 'best' | 'balanced' | 'saver';

type Msg = {
  id?: string;
  role: string;
  content: string;
  meta?: Record<string, unknown>;
};

const FOLLOW_UPS = [
  'device info',
  'needs you',
  'switch to social',
  'open Settings',
  'dating dry run',
];

function todayLabel() {
  return new Date().toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

export default function ChatPage() {
  const [target, setTarget] = useState<'pc' | 'hosted'>('hosted');
  const [deviceId, setDeviceId] = useState('');
  const [devices, setDevices] = useState<
    { device_id: string; name?: string; connected?: boolean; latency_ms?: number }[]
  >([]);
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
  const [agentName, setAgentName] = useState('Mac');
  const [agentFocus, setAgentFocus] = useState('Everyday phone tasks, Settings, unread, dating dry-runs.');
  const [agentColor, setAgentColor] = useState('#3B82F6');
  const [modelTier, setModelTier] = useState<ModelTier>('balanced');
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

  const send = async (confirmed = false, override?: string) => {
    const text = (override ?? input).trim();
    if (!text && !confirmed) return;
    setBusy(true);
    try {
      const res = await axios.post(
        `${apiBase()}/api/chat`,
        {
          message: confirmed && pendingConfirm ? text || 'confirm' : text || '(confirmed)',
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

  const toPayload = (m: Msg): AgentPayload => {
    if (m.meta && typeof m.meta === 'object' && m.meta.answer) {
      return {
        deviceLabel: String(m.meta.deviceLabel || device?.name || 'Phone'),
        ready: Boolean(m.meta.ready ?? device?.connected),
        latencyMs:
          typeof m.meta.latencyMs === 'number'
            ? m.meta.latencyMs
            : device?.latency_ms ?? null,
        thoughts: m.meta.thoughts ? String(m.meta.thoughts) : undefined,
        steps: Array.isArray(m.meta.steps) ? (m.meta.steps as AgentPayload['steps']) : undefined,
        answer: String(m.meta.answer),
        suggestions: Array.isArray(m.meta.suggestions)
          ? (m.meta.suggestions as string[])
          : FOLLOW_UPS.slice(0, 3),
      };
    }
    return parseAgentContent(m.content, device);
  };

  return (
    <div className="mx-auto flex h-[100dvh] w-full max-w-content flex-col bg-canvas md:h-screen">
      <header className="flex shrink-0 items-center gap-3 border-b border-line px-4 py-3">
        <Link to="/" className="rounded-lg p-1 text-mute hover:bg-surface">
          <ArrowLeft size={20} />
        </Link>
        <PixelAvatar name={agentName} color={agentColor} size={36} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{agentName}</p>
          <p className="truncate text-xs text-mute">
            {target === 'hosted' ? 'Hosted server' : 'My PC'} · {mode} · {speed}
          </p>
        </div>
        <button
          type="button"
          className="rounded-lg p-2 text-mute hover:bg-surface"
          onClick={() => setSettingsOpen(true)}
          aria-label="Agent settings"
        >
          <Settings2 size={20} />
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4 pb-6">
        <div className="flex justify-center">
          <span className="rounded-full bg-surface-elev px-3 py-1 text-[11px] text-mute">
            {todayLabel()}
          </span>
        </div>

        {device && (
          <div className="flex items-center justify-between gap-2 rounded-2xl border border-line bg-surface px-3 py-2.5">
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
          </div>
        )}

        {messages.length === 0 && (
          <AgentMessageCard
            payload={{
              deviceLabel: device?.name || 'Phone',
              ready: device?.connected ?? false,
              latencyMs: device?.latency_ms ?? null,
              thoughts:
                'Waiting for your first ask. I can open Settings, check unread, switch modes, or start a dating dry-run.',
              steps: [
                {
                  title: 'Agent ready',
                  subtext: `${target === 'hosted' ? 'Hosted server' : 'My PC'} · ${mode}`,
                  done: true,
                  duration: '0.1s',
                },
              ],
              answer: `Ask ${agentName} anything about your phone.`,
              suggestions: FOLLOW_UPS,
            }}
            onSuggest={(s) => {
              setInput(s);
              void send(false, s);
            }}
          />
        )}

        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div
              key={m.id || i}
              className="ml-auto max-w-[85%] rounded-2xl bg-surface-elev px-3 py-2 text-sm"
            >
              {m.content}
            </div>
          ) : (
            <AgentMessageCard
              key={m.id || i}
              payload={toPayload(m)}
              onSuggest={(s) => {
                setInput(s);
              }}
            />
          )
        )}
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

      <div className="sticky bottom-0 shrink-0 border-t border-line bg-canvas-elev/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur">
        <div className="no-scrollbar mb-2 flex gap-2 overflow-x-auto">
          {FOLLOW_UPS.map((s) => (
            <button
              key={s}
              type="button"
              className="shrink-0 rounded-full border border-line px-3 py-1 text-xs text-mute"
              onClick={() => setInput(s)}
            >
              {s} →
            </button>
          ))}
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
              placeholder={`Ask ${agentName}…`}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
            />
          </div>
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent disabled:opacity-40"
            aria-label="Send"
          >
            <Send size={18} />
          </button>
        </form>
      </div>

      <AgentSettingsSheet
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        name={agentName}
        onNameChange={setAgentName}
        focus={agentFocus}
        onFocusChange={setAgentFocus}
        color={agentColor}
        onColorChange={setAgentColor}
        mode={mode}
        speed={speed}
        onModeChange={(m) => persistMode(m, speed)}
        onSpeedChange={(s) => persistMode(mode, s)}
        modelTier={modelTier}
        onModelTier={setModelTier}
        target={target}
        onTarget={setTarget}
        devices={devices}
        deviceId={deviceId}
        onDeviceId={setDeviceId}
      />
    </div>
  );
}
