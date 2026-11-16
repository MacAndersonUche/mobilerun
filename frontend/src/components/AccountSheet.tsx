import { useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../auth';
import { Button, ErrorBanner, Input, Sheet } from './ui';
import { getAuthToken, getBackendUrl } from '../config';

export default function AccountSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
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

  const rows: [string, string][] = [
    ['Workspace', '/settings'],
    ['Notifications', '/needs-you'],
    ['Preferences', '/settings'],
    ['AWS cost', '/settings'],
    ['Usage', '/history'],
    ['Connect AI tools', '/settings'],
  ];

  return (
    <Sheet open={open} onClose={onClose} title="Account">
      <div className="space-y-4">
        <div className="rounded-2xl border border-line bg-canvas-elev p-4">
          <p className="text-xs uppercase tracking-wide text-mute">Developer platform</p>
          <Link
            to="/devices"
            onClick={onClose}
            className="mt-2 block py-2 text-sm hover:text-accent"
          >
            Devices
          </Link>
          <Link
            to="/settings"
            onClick={onClose}
            className="block py-2 text-sm hover:text-accent"
          >
            API keys and runs
          </Link>
        </div>

        <div className="flex items-center gap-3 rounded-2xl border border-line bg-surface p-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-lg font-semibold">
            {(email || 'M').slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{email || 'Mac'}</p>
            <p className="text-xs text-mute">
              <span className="mr-badge bg-accent/20 text-accent">Owner</span>
              <span className="ml-2">{email || 'self-hosted'}</span>
            </p>
          </div>
          <Link to="/account" onClick={onClose} className="text-sm text-accent">
            Edit
          </Link>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-4 space-y-3">
          <div>
            <h3 className="font-medium">Link a phone</h3>
            <p className="text-sm text-mute">
              Enter the 6-character code from the APK. QR is download-only.
            </p>
          </div>
          {linkErr && <ErrorBanner message={linkErr} />}
          {linkMsg && <p className="text-sm text-ok">{linkMsg}</p>}
          <Input
            className="uppercase tracking-widest"
            value={userCode}
            onChange={(e) => setUserCode(e.target.value.toUpperCase())}
            placeholder="A1B2C3"
            maxLength={8}
          />
          <Button
            className="w-full"
            disabled={linking || userCode.trim().length < 4}
            onClick={approvePhone}
          >
            {linking ? 'Linking…' : 'Approve phone'}
          </Button>
        </div>

        <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line text-sm">
          {rows.map(([label, to]) => (
            <Link
              key={label}
              to={to}
              onClick={onClose}
              className="block bg-surface px-4 py-3 hover:text-accent"
            >
              {label}
            </Link>
          ))}
        </div>

        <div className="space-y-2 px-1 text-sm text-mute">
          <p>Help & support · macandersonuche@yahoo.com</p>
          <button
            type="button"
            className="text-accent"
            onClick={() => navigator.clipboard.writeText(email || '')}
          >
            Copy user ID
          </button>
        </div>

        <Button
          variant="danger"
          className="w-full"
          onClick={() => {
            onClose();
            logout();
          }}
        >
          Log out
        </Button>

        <p className="pt-1 text-center text-xs text-mute">MobileRun by MacAI</p>
      </div>
    </Sheet>
  );
}
