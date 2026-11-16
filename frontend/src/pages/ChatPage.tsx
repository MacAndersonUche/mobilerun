import { useEffect, useRef, useState } from 'react';
import { MessageSquare, Send } from 'lucide-react';
import axios from 'axios';
import { getAuthToken, getBackendUrl, getHostedBackendUrl } from '../config';
import ModeSpeedPicker from '../components/ModeSpeedPicker';

type Mode = 'normal' | 'dating';
type Speed = 'fast' | 'balanced' | 'careful';

type Msg = {
  id?: string;
  role: string;
  content: string;
  meta?: Record<string, unknown>;
};

export default function ChatPage() {
  const [target, setTarget] = useState<'pc' | 'hosted'>('pc');
  const [deviceId, setDeviceId] = useState('');
  const [devices, setDevices] = useState<{ device_id: string; name?: string }[]>([]);
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
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const apiBase = () => {
    if (target === 'hosted') {
      return getHostedBackendUrl();
    }
    return getBackendUrl();
  };

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
        if (modeRes.data.mode === 'normal' || modeRes.data.mode === 'dating') {
          setMode(modeRes.data.mode);
        }
        if (['fast', 'balanced', 'careful'].includes(modeRes.data.speed_preset)) {
          setSpeed(modeRes.data.speed_preset);
        }
      } catch {
        /* defaults ok */
      }
    })();
  }, [target]);

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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (confirmed = false) => {
    if (!input.trim() && !confirmed) return;
    const text = input.trim() || '(confirmed)';
    setBusy(true);
    try {
      // When switching target, optionally remember PC URL already in localStorage.
      if (target === 'pc') {
        /* keep */
      }
      const res = await axios.post(
        `${apiBase()}/api/chat`,
        {
          message: confirmed && pendingConfirm ? input || 'confirm' : text,
          session_id: sessionId,
          device_id: deviceId || null,
          target,
          confirmed,
        },
        { headers: { Authorization: `Bearer ${getAuthToken()}` } },
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
      const detail =
        axios.isAxiosError(e) ? e.response?.data?.detail || e.message : 'Chat failed';
      setMessages((m) => [...m, { role: 'assistant', content: String(detail) }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-4 h-[calc(100vh-8rem)] flex flex-col">
      <div>
        <h2 className="text-3xl font-bold flex items-center gap-2">
          <MessageSquare className="text-blue-400" /> AI Chat Agent
        </h2>
        <p className="text-gray-400 text-sm mt-1">
          Talk to your assistant (Gemini / Claude / OpenAI / Grok). It can run phone tasks,
          control dating mode, and report device/stats. Destructive/bulk actions ask for confirm.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 items-center bg-gray-800 rounded-lg p-3">
        <span className="text-sm text-gray-400">Execute on</span>
        <div className="flex rounded-lg overflow-hidden border border-gray-600">
          <button
            className={`px-3 py-1.5 text-sm ${target === 'pc' ? 'bg-blue-600' : 'bg-gray-700'}`}
            onClick={() => setTarget('pc')}
          >
            My PC
          </button>
          <button
            className={`px-3 py-1.5 text-sm ${target === 'hosted' ? 'bg-blue-600' : 'bg-gray-700'}`}
            onClick={() => setTarget('hosted')}
          >
            Hosted server
          </button>
        </div>
        <select
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1.5 text-sm"
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
        <span className="text-xs text-gray-500 truncate max-w-[240px]">{apiBase()}</span>
      </div>

      <ModeSpeedPicker
        mode={mode}
        speed={speed}
        onModeChange={(m) => persistMode(m, speed)}
        onSpeedChange={(s) => persistMode(mode, s)}
      />

      <div className="flex-1 overflow-y-auto bg-gray-800/60 rounded-lg p-4 space-y-3">
        {messages.length === 0 && (
          <div className="text-gray-500 text-sm">
            Try: “device info”, “open Settings”, “switch to dating”, “speed careful”,
            “dating stats”, “start dating dry”.
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={m.id || i}
            className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
              m.role === 'user'
                ? 'ml-auto bg-blue-600/80'
                : 'mr-auto bg-gray-700'
            }`}
          >
            {m.content}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {pendingConfirm && (
        <div className="bg-amber-900/40 border border-amber-600 rounded-lg p-3 flex items-center justify-between gap-3">
          <span className="text-sm">
            Confirm `{String(pendingConfirm.intent)}` before running?
          </span>
          <div className="flex gap-2">
            <button
              className="px-3 py-1 rounded bg-gray-700"
              onClick={() => setPendingConfirm(null)}
            >
              Cancel
            </button>
            <button
              className="px-3 py-1 rounded bg-amber-600"
              onClick={() => send(true)}
              disabled={busy}
            >
              Confirm
            </button>
          </div>
        </div>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(false);
        }}
      >
        <input
          className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2"
          placeholder="Message the agent…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 px-4 py-2 rounded-lg flex items-center gap-2"
        >
          <Send size={16} /> Send
        </button>
      </form>
    </div>
  );
}
