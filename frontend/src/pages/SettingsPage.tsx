import { useState, useEffect } from 'react';
import { Save } from 'lucide-react';
import { getBackendUrl, setBackendUrl, getAuthToken, setAuthToken } from '../config';
import axios from 'axios';

const DEFAULT_LLM_MODELS: Record<string, string> = {
  gemini: 'gemini-3.8-flash',
  openai: 'gpt-6-astra',
  anthropic: 'claude-sonnet-5',
  xai: 'grok-4.7', // current xAI docs flagship; configurable
};

export default function SettingsPage() {
  const [backendUrl, setBackendUrlState] = useState(getBackendUrl());
  const [authToken, setAuthTokenState] = useState(getAuthToken() || '');
  const [provider, setProvider] = useState('gemini');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [defaultModels, setDefaultModels] = useState(DEFAULT_LLM_MODELS);
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
      if (response.data.default_models) {
        setDefaultModels(response.data.default_models);
      }
    } catch (error) {
      console.error('Failed to load LLM config:', error);
    }
  };

  const onProviderChange = (next: string) => {
    setProvider(next);
    const suggested = defaultModels[next];
    if (suggested) {
      setModel(suggested);
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
      try {
        setBackendUrl(backendUrl);
      } catch (err) {
        alert(err instanceof Error ? err.message : String(err));
        setSaving(false);
        return;
      }
      if (authToken) {
        setAuthToken(authToken);
      }
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
    <div className="mr-page space-y-6">
      <h2 className="text-2xl font-semibold">Settings</h2>

      <form onSubmit={saveSettings} className="space-y-6">
        <section className="mr-card space-y-4">
          <h3 className="text-xl font-semibold">Backend Connection</h3>

          <div>
            <label htmlFor="settings-backend-url" className="mb-2 block text-sm font-medium">
              Backend URL
            </label>
            <input
              id="settings-backend-url"
              type="url"
              value={backendUrl}
              onChange={(e) => setBackendUrlState(e.target.value)}
              placeholder="http://localhost:8000"
              className="mr-input"
            />
            <p className="mt-1 text-xs text-mute">
              Use localhost for local backend or your Lambda API URL for cloud
            </p>
          </div>

          <div>
            <label htmlFor="settings-auth-token" className="mb-2 block text-sm font-medium">
              Auth Token (JWT)
            </label>
            <input
              id="settings-auth-token"
              type="password"
              value={authToken}
              onChange={(e) => setAuthTokenState(e.target.value)}
              placeholder="Optional for local, required for cloud"
              className="mr-input"
            />
          </div>
        </section>

        <section className="mr-card space-y-4">
          <h3 className="text-xl font-semibold">LLM Provider</h3>

          <div>
            <label htmlFor="settings-provider" className="mb-2 block text-sm font-medium">
              Provider
            </label>
            <select
              id="settings-provider"
              value={provider}
              onChange={(e) => onProviderChange(e.target.value)}
              className="mr-input"
            >
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="xai">xAI (Grok)</option>
            </select>
            <p className="mt-1 text-xs text-mute">
              Self-hosted: you pay AWS + LLM tokens only. xAI uses{' '}
              <code className="text-white/80">XAI_API_KEY</code> at{' '}
              <code className="text-white/80">https://api.x.ai/v1</code>.
            </p>
          </div>

          <div>
            <label htmlFor="settings-model" className="mb-2 block text-sm font-medium">
              Model
            </label>
            <input
              id="settings-model"
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={defaultModels[provider] || 'e.g., grok-4.7'}
              className="mr-input"
            />
            <p className="mt-1 text-xs text-mute">
              Configurable. xAI default is current docs flagship (
              {defaultModels.xai || 'grok-4.7'}); also try grok-4.6.
            </p>
          </div>

          <div>
            <label htmlFor="settings-api-key" className="mb-2 block text-sm font-medium">
              API Key
            </label>
            <input
              id="settings-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                provider === 'xai'
                  ? 'XAI_API_KEY (leave empty to keep current)'
                  : 'Leave empty to keep current key'
              }
              className="mr-input"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="settings-temperature" className="mb-2 block text-sm font-medium">
                Temperature
              </label>
              <input
                id="settings-temperature"
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="mr-input"
              />
            </div>

            <div>
              <label htmlFor="settings-max-tokens" className="mb-2 block text-sm font-medium">
                Max Tokens
              </label>
              <input
                id="settings-max-tokens"
                type="number"
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                className="mr-input"
              />
            </div>
          </div>
        </section>

        {latestApkQr && (
          <section className="mr-card">
            <h3 className="mb-4 text-xl font-semibold">Install Android App</h3>
            <p className="mb-4 text-sm text-mute">
              QR is download-only — scan to install the latest GitHub release APK.
              Then open the app, pair via Devices → Connect phone QR, and enable
              Accessibility (the only manual step). Notifications and battery are
              requested automatically.
            </p>
            <div className="inline-block rounded-lg bg-white p-4">
              <img
                src={`data:image/png;base64,${latestApkQr}`}
                alt="APK Download QR"
                className="h-48 w-48"
              />
            </div>
            <p className="mt-2 text-xs text-mute">
              After install: pair → Enable Accessibility (deep-linked) → accept the
              automatic notification + battery prompts. Live view capture is optional
              and only asked when you open Live View.
            </p>
          </section>
        )}

        <button
          type="submit"
          disabled={saving}
          className="mr-btn-primary w-full"
        >
          <Save size={20} />
          <span>{saving ? 'Saving...' : 'Save Settings'}</span>
        </button>
      </form>
    </div>
  );
}
