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

type Mode = 'normal' | 'dating';
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

  useEffect(() => {
    loadDevices();
    loadMode();
  }, []);

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
      if (res.data.mode === 'normal' || res.data.mode === 'dating') {
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

    if (mode === 'dating') {
      alert('Dating mode runs from the Dating page. Switch to Normal for one-shot tasks.');
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
    try {
      await axios.post(
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

      alert('Task submitted successfully!');
      setInstruction('');
    } catch (error) {
      console.error('Failed to submit task:', error);
      alert('Failed to submit task');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-3xl font-bold">Run Automation Task</h2>
        <p className="text-gray-400 text-sm mt-1">
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

      {devices.length === 0 ? (
        <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4">
          <p className="text-yellow-400">
            No connected devices. Please pair a device first.
          </p>
        </div>
      ) : (
        <form onSubmit={submitTask} className="bg-gray-800 rounded-lg p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Select Device</label>
            <select
              value={selectedDevice}
              onChange={(e) => setSelectedDevice(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
            >
              {devices.map((device) => (
                <option key={device.device_id} value={device.device_id}>
                  {device.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Instruction
            </label>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Open Settings and turn on dark mode"
              rows={4}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Max Steps: {maxSteps}
            </label>
            <input
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
            disabled={submitting || mode === 'dating'}
            className="w-full flex items-center justify-center space-x-2 bg-blue-600 hover:bg-blue-700 px-4 py-3 rounded-lg disabled:opacity-50 transition-colors"
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
