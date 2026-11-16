import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play, Square, Smartphone } from 'lucide-react';
import axios from 'axios';
import { getAuthToken, getBackendUrl, getUiWebSocketUrl } from '../config';

type AgentState = {
  current_app?: string;
  step?: number;
  action?: string;
  logs?: string[];
};

type Overlay = { kind: 'tap' | 'swipe'; x: number; y: number; x2?: number; y2?: number };

export default function LiveViewPage() {
  const [devices, setDevices] = useState<{ device_id: string; name: string; connected: boolean }[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [state, setState] = useState<AgentState>({});
  const [logs, setLogs] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [fps, setFps] = useState(3);
  const [quality, setQuality] = useState(45);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [manualInput, setManualInput] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const loadDevices = useCallback(async () => {
    try {
      const res = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      setDevices(res.data || []);
      if (!deviceId && res.data?.[0]?.device_id) {
        setDeviceId(res.data[0].device_id);
      }
    } catch (e) {
      console.error(e);
    }
  }, [deviceId]);

  useEffect(() => {
    loadDevices();
    const t = setInterval(loadDevices, 5000);
    return () => clearInterval(t);
  }, [loadDevices]);

  const disconnect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'unsubscribe', device_id: deviceId }));
      wsRef.current.close();
    }
    wsRef.current = null;
    setConnected(false);
  }, [deviceId]);

  const connect = useCallback(() => {
    if (!deviceId) return;
    disconnect();
    const ws = new WebSocket(getUiWebSocketUrl());
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      ws.send(
        JSON.stringify({
          type: 'subscribe',
          device_id: deviceId,
          role: 'ui',
          fps,
          quality,
        }),
      );
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'frame' && msg.data) {
          setFrameUrl(`data:${msg.mime || 'image/jpeg'};base64,${msg.data}`);
        } else if (msg.type === 'agent_event') {
          const st = msg.state || msg;
          setState(st);
          if (Array.isArray(st.logs)) setLogs(st.logs.slice(-40));
          else if (msg.log) setLogs((prev) => [...prev.slice(-39), String(msg.log)]);
        } else if (msg.type === 'subscribed' && msg.state) {
          setState(msg.state);
          if (Array.isArray(msg.state.logs)) setLogs(msg.state.logs.slice(-40));
        }
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
  }, [deviceId, disconnect, fps, quality]);

  useEffect(() => () => disconnect(), [disconnect]);

  const sendTaskControl = (action: 'pause' | 'stop') => {
    wsRef.current?.send(
      JSON.stringify({ type: 'task_control', device_id: deviceId, action }),
    );
    setLogs((p) => [...p, `UI → ${action}`]);
  };

  const toDeviceCoords = (clientX: number, clientY: number) => {
    const img = imgRef.current;
    if (!img) return null;
    const rect = img.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * (img.naturalWidth || 540);
    const y = ((clientY - rect.top) / rect.height) * (img.naturalHeight || 960);
    return { x: Math.round(x), y: Math.round(y) };
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!manualInput || !connected) return;
    const pt = toDeviceCoords(e.clientX, e.clientY);
    if (!pt) return;
    dragRef.current = pt;
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (!manualInput || !connected || !dragRef.current) return;
    const end = toDeviceCoords(e.clientX, e.clientY);
    if (!end) return;
    const start = dragRef.current;
    dragRef.current = null;
    const dist = Math.hypot(end.x - start.x, end.y - start.y);
    if (dist < 12) {
      setOverlay({ kind: 'tap', x: start.x, y: start.y });
      wsRef.current?.send(
        JSON.stringify({ type: 'input', action: 'tap', device_id: deviceId, x: start.x, y: start.y }),
      );
    } else {
      setOverlay({ kind: 'swipe', x: start.x, y: start.y, x2: end.x, y2: end.y });
      wsRef.current?.send(
        JSON.stringify({
          type: 'input',
          action: 'swipe',
          device_id: deviceId,
          x1: start.x,
          y1: start.y,
          x2: end.x,
          y2: end.y,
          duration_ms: 280,
        }),
      );
    }
    setTimeout(() => setOverlay(null), 600);
  };

  const meta = useMemo(
    () => ({
      app: state.current_app || '—',
      step: state.step ?? '—',
      action: state.action || '—',
    }),
    [state],
  );

  return (
    <div className="mr-page space-y-6 !max-w-5xl">
      <div className="flex flex-wrap items-end gap-4 justify-between">
        <div>
          <h2 className="text-2xl font-semibold flex items-center gap-2 tracking-tight">
            <Smartphone className="text-accent" /> Live View
          </h2>
          <p className="text-mute text-sm mt-1">
            Device panel streams JPEG only while subscribed (~{fps} fps). Nothing is stored.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-end">
          <label htmlFor="live-device" className="text-sm">
            Device
            <select
              id="live-device"
              className="mr-input mt-1 block"
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
            >
              <option value="">Select…</option>
              {devices.map((d) => (
                <option key={d.device_id} value={d.device_id}>
                  {d.name || d.device_id} {d.connected ? '' : '(offline)'}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="live-fps" className="text-sm">
            FPS
            <input
              id="live-fps"
              type="number"
              min={1}
              max={8}
              value={fps}
              onChange={(e) => setFps(Number(e.target.value))}
              className="mr-input mt-1 block w-20"
            />
          </label>
          <label htmlFor="live-quality" className="text-sm">
            Quality
            <input
              id="live-quality"
              type="number"
              min={20}
              max={85}
              value={quality}
              onChange={(e) => setQuality(Number(e.target.value))}
              className="mr-input mt-1 block w-20"
            />
          </label>
          {!connected ? (
            <button
              onClick={connect}
              className="bg-accent hover:bg-blue-700 px-4 py-2 rounded-lg flex items-center gap-2"
            >
              <Play size={16} /> Start stream
            </button>
          ) : (
            <button
              onClick={disconnect}
              className="bg-surface-elev hover:bg-gray-600 px-4 py-2 rounded-lg flex items-center gap-2"
            >
              <Square size={16} /> Stop stream
            </button>
          )}
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(280px,340px)_1fr]">
        {/* Device panel — public embed docs: 9/19.5, radius 24px */}
        <div className="mx-auto w-full max-w-[320px]">
          <p className="mb-2 text-sm font-medium">
            {devices.find((d) => d.device_id === deviceId)?.name || 'Phone'}
          </p>
          <div className="device-panel overflow-hidden rounded-[24px] border border-line bg-black shadow-sheet">
            <div className="relative aspect-[9/19.5] w-full overflow-hidden bg-[#0e0e11]">
              <div className="absolute left-1/2 top-2 z-10 h-5 w-24 -translate-x-1/2 rounded-full bg-surface-elev" />
              {frameUrl ? (
                <img
                  ref={imgRef}
                  src={frameUrl}
                  alt="Live device"
                  className="h-full w-full select-none object-cover touch-none"
                  onPointerDown={onPointerDown}
                  onPointerUp={onPointerUp}
                  draggable={false}
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center p-6 text-center text-sm text-mute">
                  {connected
                    ? 'Waiting for frames… grant MediaProjection on the phone once.'
                    : 'Start stream to watch the phone.'}
                </div>
              )}
              {overlay && (
                <svg className="pointer-events-none absolute inset-0 h-full w-full">
                  {overlay.kind === 'tap' ? (
                    <circle
                      cx={`${(overlay.x / (imgRef.current?.naturalWidth || 540)) * 100}%`}
                      cy={`${(overlay.y / (imgRef.current?.naturalHeight || 960)) * 100}%`}
                      r="12"
                      fill="rgba(59,130,246,0.55)"
                      stroke="white"
                      strokeWidth="2"
                    />
                  ) : (
                    <line
                      x1={`${(overlay.x / (imgRef.current?.naturalWidth || 540)) * 100}%`}
                      y1={`${(overlay.y / (imgRef.current?.naturalHeight || 960)) * 100}%`}
                      x2={`${((overlay.x2 || 0) / (imgRef.current?.naturalWidth || 540)) * 100}%`}
                      y2={`${((overlay.y2 || 0) / (imgRef.current?.naturalHeight || 960)) * 100}%`}
                      stroke="rgba(250,204,21,0.9)"
                      strokeWidth="4"
                      strokeLinecap="round"
                    />
                  )}
                </svg>
              )}
            </div>
            <div className="flex items-center justify-around border-t border-line bg-canvas-elev py-3 text-mute">
              <span className="text-lg leading-none">‹</span>
              <span className="text-sm leading-none">⌂</span>
              <span className="text-sm leading-none">▦</span>
            </div>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-mute">
            <input
              type="checkbox"
              checked={manualInput}
              onChange={(e) => setManualInput(e.target.checked)}
            />
            Click/swipe on view to send taps
          </label>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3 rounded-2xl border border-line bg-surface p-4 text-sm">
            <div>
              <div className="text-mute">Current app</div>
              <div className="truncate font-medium">{meta.app}</div>
            </div>
            <div>
              <div className="text-mute">Step</div>
              <div className="font-medium">{meta.step}</div>
            </div>
            <div>
              <div className="text-mute">Action</div>
              <div className="truncate font-medium">{meta.action}</div>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => sendTaskControl('pause')}
              disabled={!connected}
              className="flex items-center gap-2 rounded-xl bg-amber-600/80 px-4 py-2 hover:bg-amber-600 disabled:opacity-40"
            >
              <Pause size={16} /> Pause
            </button>
            <button
              onClick={() => sendTaskControl('stop')}
              disabled={!connected}
              className="flex items-center gap-2 rounded-xl bg-red-600/80 px-4 py-2 hover:bg-red-600 disabled:opacity-40"
            >
              <Square size={16} /> Stop agent
            </button>
          </div>

          <div className="h-72 space-y-1 overflow-y-auto rounded-2xl border border-line bg-surface p-4 font-mono text-xs">
            <div className="mb-2 text-mute">Live log</div>
            {logs.length === 0 && <div className="text-mute">No events yet</div>}
            {logs.map((line, i) => (
              <div key={i} className="text-gray-200">
                {line}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
