import { useState, useEffect } from 'react';
import { Play, Loader } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';
import ModeSpeedPicker from '../components/ModeSpeedPicker';

interface Device {
  device_id: string;
  name: string;
  connected: boolean;
}

type Mode = 'normal' | 'dating' | 'social';
type Speed = 'fast' | 'balanced' | 'careful';

export default function TasksPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [instruction, setInstruction] = useState('');
  const [maxSteps, setMaxSteps] = useState(15);
  const [reasoning, setReasoning] = useState(false);
  const [vision, setVision] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<Mode>('normal');
  const [speed, setSpeed] = useState<Speed>('balanced');
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>('');
  const [taskLog, setTaskLog] = useState<string>('');

  useEffect(() => {
    loadDevices();
    loadMode();
  }, []);

  useEffect(() => {
    if (!activeTaskId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await axios.get(
          `${getBackendUrl()}/api/tasks/${activeTaskId}`,
          { headers: authHeaders() }
        );
        if (cancelled) return;
        const d = res.data;
        const planner = d.planner ? ` · ${d.planner}` : '';
        const provider = d.llm_provider ? `/${d.llm_provider}` : '';
        setTaskStatus(
          `${d.status} · step ${d.current_step || 0}/${d.max_steps || '?'}${planner}${provider}`
        );
        const blob = [d.result, d.error].filter(Boolean).join(' — ') || 'Running…';
        setTaskLog(blob);
        if (['completed', 'failed', 'stopped'].includes(d.status)) {
          setActiveTaskId(null);
          setSubmitting(false);
        }
      } catch (e) {
        console.error(e);
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [activeTaskId]);

  const authHeaders = () => ({
    Authorization: `Bearer ${getAuthToken()}`,
  });

  const loadDevices = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: authHeaders(),
      });
      const connected = response.data.filter((d: Device) => d.connected);
      setDevices(connected);
      if (connected.length > 0 && !selectedDevice) {
        setSelectedDevice(connected[0].device_id);
      }
    } catch (error) {
      console.error('Failed to load devices:', error);
    }
  };

  const loadMode = async () => {
    try {
      const res = await axios.get(`${getBackendUrl()}/api/mode`, {
        headers: authHeaders(),
      });
      if (['normal', 'dating', 'social'].includes(res.data.mode)) {
        setMode(res.data.mode);
      }
      if (['fast', 'balanced', 'careful'].includes(res.data.speed_preset)) {
        setSpeed(res.data.speed_preset);
      }
    } catch {
      /* defaults ok */
    }
  };

  const persistMode = async (nextMode: Mode, nextSpeed: Speed) => {
    setMode(nextMode);
    setSpeed(nextSpeed);
    try {
      await axios.post(
        `${getBackendUrl()}/api/mode`,
        { mode: nextMode, speed_preset: nextSpeed },
        { headers: authHeaders() }
      );
    } catch (e) {
      console.error(e);
    }
  };

  const submitTask = async (e: React.FormEvent) => {
    e.preventDefault();

    if (mode === 'dating' || mode === 'social') {
      alert(
        mode === 'dating'
          ? 'Dating mode runs from the Dating page. Switch to Normal for one-shot tasks.'
          : 'Social mode runs from the Social page. Switch to Normal for one-shot tasks.'
      );
      return;
    }

    if (!selectedDevice) {
      alert('Please select a device');
      return;
    }

    if (!instruction.trim()) {
      alert('Please enter an instruction');
      return;
    }

    setSubmitting(true);
    setTaskStatus('starting…');
    setTaskLog('');
    try {
      const res = await axios.post(
        `${getBackendUrl()}/api/tasks`,
        {
          device_id: selectedDevice,
          instruction,
          max_steps: maxSteps,
          reasoning,
          vision,
          mode: 'normal',
          speed_preset: speed,
        },
        { headers: authHeaders() }
      );
      const tid = res.data?.task_id;
      if (tid) {
        setActiveTaskId(tid);
        setTaskStatus(res.data.status || 'running');
        setTaskLog(res.data.result || res.data.error || 'Cloud agent started');
      } else {
        setSubmitting(false);
        alert('Task submitted but no task_id returned');
      }
      setInstruction('');
    } catch (error: unknown) {
      console.error('Failed to submit task:', error);
      const detail =
        axios.isAxiosError(error)
          ? String(error.response?.data?.detail || error.message)
          : 'Failed to submit task';
      setTaskStatus('failed');
      setTaskLog(detail);
      setSubmitting(false);
      alert(detail);
    }
  };

  return (
    <div className="mr-page space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Run Automation Task</h2>
        <p className="text-mute text-sm mt-1">
          Normal mode: general-purpose phone agent (open apps, navigate, type, multi-step).
        </p>
      </div>

      <ModeSpeedPicker
        mode={mode}
        speed={speed}
        onModeChange={(m) => persistMode(m, speed)}
        onSpeedChange={(s) => persistMode(mode, s)}
      />

      {mode === 'dating' && (
        <div className="bg-rose-900/20 border border-rose-700 rounded-lg p-4 text-sm text-rose-100">
          Dating mode is active. Start the dating loop on the{' '}
          <Link to="/dating" className="underline text-rose-300">
            Dating page
          </Link>
          , or switch back to Normal for a one-shot task.
        </div>
      )}
      {mode === 'social' && (
        <div className="bg-emerald-900/20 border border-emerald-700 rounded-lg p-4 text-sm text-emerald-100">
          Social mode is active. Manage chats on the{' '}
          <Link to="/social" className="underline text-emerald-300">
            Social page
          </Link>{' '}
          or review{' '}
          <Link to="/needs-you" className="underline text-amber-300">
            Needs you
          </Link>
          .
        </div>
      )}

      {(taskStatus || taskLog) && (
        <div
          className="rounded-lg border border-line bg-canvas-elev p-4 text-sm"
          data-testid="task-progress"
        >
          <p className="font-medium text-white">{taskStatus || '…'}</p>
          {/LLM unavailable:\s*quota/i.test(taskLog) && (
            <p
              className="mt-2 rounded border border-amber-700/60 bg-amber-950/40 px-2 py-1 text-amber-200"
              data-testid="llm-unavailable-banner"
            >
              LLM unavailable: quota
            </p>
          )}
          {taskLog && <p className="mt-1 text-mute whitespace-pre-wrap">{taskLog}</p>}
        </div>
      )}

      {devices.length === 0 ? (
        <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4">
          <p className="text-yellow-400">
            No connected devices. Install the APK and sign in with your account.
          </p>
        </div>
      ) : (
        <form onSubmit={submitTask} className="bg-surface rounded-lg p-6 space-y-4">
          <div>
            <label htmlFor="task-device" className="mb-2 block text-sm font-medium">
              Select Device
            </label>
            <select
              id="task-device"
              value={selectedDevice}
              onChange={(e) => setSelectedDevice(e.target.value)}
              className="mr-input"
            >
              {devices.map((device) => (
                <option key={device.device_id} value={device.device_id}>
                  {device.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="task-instruction" className="mb-2 block text-sm font-medium">
              Instruction
            </label>
            <textarea
              id="task-instruction"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Open Settings and turn on dark mode"
              rows={4}
              className="mr-input"
            />
          </div>

          <div>
            <label htmlFor="task-max-steps" className="mb-2 block text-sm font-medium">
              Max Steps: {maxSteps}
            </label>
            <input
              id="task-max-steps"
              type="range"
              min="5"
              max="50"
              value={maxSteps}
              onChange={(e) => setMaxSteps(parseInt(e.target.value))}
              className="w-full"
            />
          </div>

          <div className="space-y-2">
            <label className="flex items-center space-x-2">
              <input
                type="checkbox"
                checked={vision}
                onChange={(e) => setVision(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm">Enable Vision</span>
            </label>

            <label className="flex items-center space-x-2">
              <input
                type="checkbox"
                checked={reasoning}
                onChange={(e) => setReasoning(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm">Enable Reasoning Mode</span>
            </label>
          </div>

          <button
            type="submit"
            disabled={submitting || mode === 'dating' || mode === 'social'}
            className="w-full flex items-center justify-center space-x-2 bg-accent hover:bg-accent-soft px-4 py-3 rounded-lg disabled:opacity-50 transition-colors"
          >
            {submitting ? (
              <>
                <Loader className="animate-spin" size={20} />
                <span>Running...</span>
              </>
            ) : (
              <>
                <Play size={20} />
                <span>Run Task</span>
              </>
            )}
          </button>
        </form>
      )}
    </div>
  );
}
