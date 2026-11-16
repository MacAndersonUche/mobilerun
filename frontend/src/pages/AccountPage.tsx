import { useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../auth';
import { Button, Card, ErrorBanner, Input } from '../components/ui';
import { getAuthToken, getBackendUrl } from '../config';

export default function AccountPage() {
  const { email, logout } = useAuth();
  const [userCode, setUserCode] = useState('');
  const [linkMsg, setLinkMsg] = useState<string | null>(null);
  const [linkErr, setLinkErr] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);

  const approvePhone = async () => {
    setLinking(true);
    setLinkErr(null);
    setLinkMsg(null);
    try {
      const res = await axios.post(
        `${getBackendUrl()}/api/auth/device/approve`,
        { user_code: userCode.trim().toUpperCase() },
        { headers: { Authorization: `Bearer ${getAuthToken()}` } }
      );
      setLinkMsg(`Phone linked · ${res.data.device_id}`);
      setUserCode('');
    } catch (e: unknown) {
      const msg = axios.isAxiosError(e)
        ? String(e.response?.data?.detail || e.message)
        : 'Approve failed';
      setLinkErr(msg);
    } finally {
      setLinking(false);
    }
  };

  return (
    <div className="mr-page space-y-4">
      <h1 className="text-2xl font-semibold">Account</h1>

      <Card elev className="space-y-1">
        <p className="text-xs uppercase tracking-wide text-mute">Developer platform</p>
        <Link to="/devices" className="block py-2 text-sm hover:text-accent">
          Devices
        </Link>
        <Link to="/settings" className="block py-2 text-sm hover:text-accent">
          API keys and runs
        </Link>
      </Card>

      <Card className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-lg font-semibold">
          {(email || 'M').slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{email || 'Mac'}</p>
          <p className="text-xs text-mute">
            <span className="mr-badge bg-accent/20 text-accent">Owner</span>
            <span className="ml-2 break-all">{email || 'self-hosted'}</span>
          </p>
        </div>
        <span className="text-sm text-mute">Edit</span>
      </Card>

      <Card className="space-y-3">
        <div>
          <h2 className="font-medium">Link a phone</h2>
          <p className="text-sm text-mute">
            Open the APK, tap Sign in and link phone, then type the 6-character
            code here. Same Cognito account auto-links the executor. QR is only
            for downloading the APK from Devices / Settings.
          </p>
        </div>
        {linkErr && <ErrorBanner message={linkErr} />}
        {linkMsg && <p className="text-sm text-ok">{linkMsg}</p>}
        <label className="block text-sm text-mute">
          Device code
          <Input
            className="mt-1 uppercase tracking-widest"
            value={userCode}
            onChange={(e) => setUserCode(e.target.value.toUpperCase())}
            placeholder="A1B2C3"
            maxLength={8}
          />
        </label>
        <Button
          className="w-full"
          disabled={linking || userCode.trim().length < 4}
          onClick={approvePhone}
        >
          {linking ? 'Linking…' : 'Approve phone'}
        </Button>
      </Card>

      <Card className="divide-y divide-line text-sm !p-0 overflow-hidden">
        {[
          ['Workspace', '/settings'],
          ['Notifications', '/needs-you'],
          ['Preferences', '/settings'],
          ['AWS cost', '/settings'],
          ['Usage', '/history'],
          ['Connect AI tools', '/settings'],
        ].map(([label, to]) => (
          <Link key={label} to={to} className="block px-4 py-3 hover:text-accent">
            {label}
          </Link>
        ))}
      </Card>

      <Card className="space-y-2 text-sm text-mute">
        <p>Backend: {getBackendUrl()}</p>
        <p>Help & support · macandersonuche@yahoo.com</p>
        <button
          type="button"
          className="text-accent"
          onClick={() => navigator.clipboard.writeText(email || '')}
        >
          Copy user ID
        </button>
      </Card>

      <Button variant="danger" className="w-full" onClick={logout}>
        Log out
      </Button>

      <p className="pt-2 text-center text-xs text-mute">MobileRun by MacAI</p>
    </div>
  );
}
