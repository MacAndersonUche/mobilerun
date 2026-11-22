import { Link } from 'react-router-dom';
import { useAuth } from '../auth';
import { Button, Card } from '../components/ui';
import { getBackendUrl } from '../config';

export default function AccountPage() {
  const { email, logout } = useAuth();

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
      </Card>

      <Card className="space-y-3">
        <div>
          <h2 className="font-medium">Link a phone</h2>
          <p className="text-sm text-mute">
            Open Devices → Connect phone and scan the QR with the MacMobileRun APK
            (or copy the link). No device code or in-app sign-in.
          </p>
        </div>
        <Link to="/devices" className="mr-btn-primary inline-block text-sm">
          Open Devices
        </Link>
      </Card>

      <Card className="divide-y divide-line text-sm !p-0 overflow-hidden">
        {[
          ['Workspace', '/settings'],
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

      <p className="pt-2 text-center text-xs text-mute">MacMobileRun</p>
    </div>
  );
}
