import { useState, useEffect } from 'react';
import { Smartphone, Wifi, WifiOff, Plus } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import axios from 'axios';

interface Device {
  device_id: string;
  name: string;
  platform: string;
  connected: boolean;
  connection_type: string;
  last_seen: string;
  route?: string | null;
  latency_ms?: number | null;
}

interface PairingInfo {
  token: string;
  qr_code: string;
  pairing_url: string;
  expires_in: number;
  lan_ws?: string | null;
  cloud_ws?: string | null;
  mdns_service?: string;
}

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [pairingInfo, setPairingInfo] = useState<PairingInfo | null>(null);
  const [showPairing, setShowPairing] = useState(false);
  const [deviceName, setDeviceName] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadDevices();
    const interval = setInterval(loadDevices, 3000);
    return () => clearInterval(interval);
  }, []);

  const loadDevices = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/devices`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      setDevices(response.data);
    } catch (error) {
      console.error('Failed to load devices:', error);
    }
  };

  const startPairing = async () => {
    if (!deviceName.trim()) {
      alert('Please enter a device name');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(
        `${getBackendUrl()}/api/devices/pair`,
        {
          device_name: deviceName,
          platform: 'android',
        },
        {
          headers: { Authorization: `Bearer ${getAuthToken()}` },
        }
      );
      setPairingInfo(response.data);
      setShowPairing(true);
    } catch (error) {
      console.error('Failed to initiate pairing:', error);
      alert('Failed to start pairing. Please check backend connection.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mr-page space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Connected Devices</h2>
        <button
          onClick={() => {
            setShowPairing(false);
            setPairingInfo(null);
            setDeviceName('');
            const modal = document.getElementById('pair-modal');
            if (modal) (modal as any).showModal();
          }}
          className="flex items-center space-x-2 bg-accent hover:bg-accent-soft px-4 py-2 rounded-lg transition-colors"
        >
          <Plus size={20} />
          <span>Pair Device</span>
        </button>
      </div>

      {/* Devices Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {devices.length === 0 ? (
          <div className="col-span-full bg-surface rounded-lg p-8 text-center">
            <Smartphone size={48} className="mx-auto text-mute mb-4" />
            <p className="text-mute mb-2">No devices connected</p>
            <p className="text-sm text-mute">
              Click "Pair Device" to add your phone
            </p>
          </div>
        ) : (
          devices.map((device) => (
            <DeviceCard key={device.device_id} device={device} />
          ))
        )}
      </div>

      {/* Pairing Modal */}
      <dialog id="pair-modal" className="modal bg-surface rounded-lg p-6 max-w-md">
        <div className="space-y-4">
          <h3 className="text-xl font-bold">Pair New Device</h3>

          {!showPairing ? (
            <>
              <div>
                <label className="block text-sm font-medium mb-2">
                  Device Name
                </label>
                <input
                  type="text"
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  placeholder="My Phone"
                  className="w-full px-3 py-2 bg-surface-elev border border-line rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="flex justify-end space-x-3">
                <button
                  onClick={() => {
                    const modal = document.getElementById('pair-modal');
                    if (modal) (modal as any).close();
                  }}
                  className="px-4 py-2 bg-surface-elev hover:bg-gray-600 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  onClick={startPairing}
                  disabled={loading}
                  className="px-4 py-2 bg-accent hover:bg-accent-soft rounded-lg disabled:opacity-50"
                >
                  {loading ? 'Starting...' : 'Start Pairing'}
                </button>
              </div>
            </>
          ) : (
            pairingInfo && (
              <>
                <div className="text-center space-y-4">
                  <p className="text-mute">
                    Scan once — stores LAN + cloud WebSocket endpoints. No USB
                    cable. Phone prefers Wi‑Fi/mDNS, then falls back to AWS.
                  </p>
                  {(pairingInfo.lan_ws || pairingInfo.cloud_ws) && (
                    <p className="text-xs text-mute break-all">
                      {pairingInfo.lan_ws && (
                        <>
                          LAN: {pairingInfo.lan_ws}
                          <br />
                        </>
                      )}
                      {pairingInfo.cloud_ws && <>Cloud: {pairingInfo.cloud_ws}</>}
                    </p>
                  )}

                  <div className="bg-white p-4 rounded-lg inline-block">
                    <img
                      src={`data:image/png;base64,${pairingInfo.qr_code}`}
                      alt="Pairing QR Code"
                      className="w-64 h-64"
                    />
                  </div>

                  <p className="text-sm text-mute">
                    Expires in {Math.floor(pairingInfo.expires_in / 60)} minutes
                  </p>

                  <details className="text-left">
                    <summary className="text-sm text-mute cursor-pointer">
                      Manual pairing URL
                    </summary>
                    <code className="text-xs bg-gray-900 p-2 rounded block mt-2 break-all">
                      {pairingInfo.pairing_url}
                    </code>
                  </details>
                </div>

                <button
                  onClick={() => {
                    const modal = document.getElementById('pair-modal');
                    if (modal) (modal as any).close();
                    setShowPairing(false);
                    setPairingInfo(null);
                  }}
                  className="w-full px-4 py-2 bg-surface-elev hover:bg-gray-600 rounded-lg"
                >
                  Close
                </button>
              </>
            )
          )}
        </div>
      </dialog>
    </div>
  );
}

function DeviceCard({ device }: { device: Device }) {
  return (
    <div className="bg-surface rounded-lg p-4 border border-line">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center space-x-3">
          <Smartphone className="text-accent" size={24} />
          <div>
            <h3 className="font-semibold">{device.name}</h3>
            <p className="text-sm text-mute">{device.device_id}</p>
          </div>
        </div>
        {device.connected ? (
          <Wifi className="text-green-400" size={20} />
        ) : (
          <WifiOff className="text-red-400" size={20} />
        )}
      </div>

      <div className="space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-mute">Platform:</span>
          <span className="capitalize">{device.platform}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Route:</span>
          <span className="uppercase">
            {device.route || device.connection_type || '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Latency:</span>
          <span>
            {device.latency_ms != null
              ? `${Math.round(device.latency_ms)} ms`
              : '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-mute">Status:</span>
          <span
            className={
              device.connected ? 'text-green-400' : 'text-red-400'
            }
          >
            {device.connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>
    </div>
  );
}
