import { useState, useEffect } from 'react';
import { Play, Loader } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';

interface Device {
  device_id: string;
  name: string;
  connected: boolean;
}

export default function TasksPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [instruction, setInstruction] = useState('');
  const [maxSteps, setMaxSteps] = useState(15);
  const [reasoning, setReasoning] = useState(false);
  const [vision, setVision] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadDevices();
  }, []);

  const loadDevices = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
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

  const submitTask = async (e: React.FormEvent) => {
    e.preventDefault();

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
        },
        {
          headers: { Authorization: `Bearer ${getAuthToken()}` },
        }
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
      <h2 className="text-3xl font-bold">Run Automation Task</h2>

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
            disabled={submitting}
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
