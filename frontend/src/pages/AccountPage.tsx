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
        <div>
          <p className="font-medium">{email || 'Mac'}</p>
          <p className="text-xs text-mute">Owner · self-hosted</p>
        </div>
      </Card>

      <Card className="divide-y divide-line text-sm">
        {[
          ['Workspace', '/settings'],
          ['Notifications', '/needs-you'],
          ['Preferences', '/settings'],
          ['AWS cost', '/settings'],
          ['Usage', '/history'],
          ['Connect AI tools', '/settings'],
        ].map(([label, to]) => (
          <Link key={label} to={to} className="block py-3 hover:text-accent">
            {label}
          </Link>
        ))}
      </Card>

      <Card className="text-sm text-mute space-y-2">
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

      <p className="text-center text-xs text-mute pt-2">MobileRun by MacAI</p>
    </div>
  );
}
