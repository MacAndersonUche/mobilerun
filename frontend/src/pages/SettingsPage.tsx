import { useState, useEffect } from 'react';
import { Save, Download } from 'lucide-react';
import { getBackendUrl, setBackendUrl, getAuthToken, setAuthToken } from '../config';
import axios from 'axios';

export default function SettingsPage() {
  const [backendUrl, setBackendUrlState] = useState(getBackendUrl());
  const [authToken, setAuthTokenState] = useState(getAuthToken() || '');
  const [provider, setProvider] = useState('gemini');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [latestApkQr, setLatestApkQr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadLLMConfig();
    loadLatestApk();
  }, []);

  const loadLLMConfig = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/config/llm`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      setProvider(response.data.provider);
      setModel(response.data.model);
      setTemperature(response.data.temperature);
      setMaxTokens(response.data.max_tokens);
    } catch (error) {
      console.error('Failed to load LLM config:', error);
    }
  };

  const loadLatestApk = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/releases/latest`);
      setLatestApkQr(response.data.qr_code);
    } catch (error) {
      console.error('Failed to load APK info:', error);
    }
  };

  const saveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      // Save backend URL
      setBackendUrl(backendUrl);

      // Save auth token
      if (authToken) {
        setAuthToken(authToken);
      }

      // Save LLM config
      await axios.post(
        `${backendUrl}/api/config/llm`,
        {
          provider,
          model,
          api_key: apiKey,
          temperature,
          max_tokens: maxTokens,
        },
        {
          headers: { Authorization: `Bearer ${authToken}` },
        }
      );

      alert('Settings saved successfully!');
      window.location.reload();
    } catch (error) {
      console.error('Failed to save settings:', error);
      alert('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-3xl font-bold">Settings</h2>

      <form onSubmit={saveSettings} className="space-y-6">
        {/* Backend Configuration */}
        <section className="bg-gray-800 rounded-lg p-6 space-y-4">
          <h3 className="text-xl font-semibold mb-4">Backend Connection</h3>

          <div>
            <label className="block text-sm font-medium mb-2">
              Backend URL
            </label>
            <input
              type="url"
              value={backendUrl}
              onChange={(e) => setBackendUrlState(e.target.value)}
              placeholder="http://localhost:8000"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
            />
            <p className="text-xs text-gray-400 mt-1">
              Use localhost for local backend or your Lambda API URL for cloud
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Auth Token (JWT)
            </label>
            <input
              type="password"
              value={authToken}
              onChange={(e) => setAuthTokenState(e.target.value)}
              placeholder="Optional for local, required for cloud"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
            />
          </div>
        </section>

        {/* LLM Configuration */}
        <section className="bg-gray-800 rounded-lg p-6 space-y-4">
          <h3 className="text-xl font-semibold mb-4">LLM Provider</h3>

          <div>
            <label className="block text-sm font-medium mb-2">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
            >
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic (Claude)</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Model</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g., gemini-3.8-flash"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Leave empty to keep current key"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-2">
                Temperature
              </label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">
                Max Tokens
              </label>
              <input
                type="number"
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg"
              />
            </div>
          </div>
        </section>

        {/* Android APK */}
        {latestApkQr && (
          <section className="bg-gray-800 rounded-lg p-6">
            <h3 className="text-xl font-semibold mb-4">Install Android App</h3>
            <p className="text-sm text-gray-400 mb-4">
              Scan this QR code on your Android device to download and install the
              latest Mobilerun app
            </p>
            <div className="bg-white p-4 rounded-lg inline-block">
              <img
                src={`data:image/png;base64,${latestApkQr}`}
                alt="APK Download QR"
                className="w-48 h-48"
              />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              After installing, return to the Devices page to pair your phone
            </p>
          </section>
        )}

        <button
          type="submit"
          disabled={saving}
          className="w-full flex items-center justify-center space-x-2 bg-blue-600 hover:bg-blue-700 px-4 py-3 rounded-lg disabled:opacity-50 transition-colors"
        >
          <Save size={20} />
          <span>{saving ? 'Saving...' : 'Save Settings'}</span>
        </button>
      </form>
    </div>
  );
}
