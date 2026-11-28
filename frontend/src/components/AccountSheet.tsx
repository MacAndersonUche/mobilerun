import { Link } from 'react-router-dom';
import { useAuth } from '../auth';
import { Button, Sheet } from './ui';

export default function AccountSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { email, logout } = useAuth();

  return (
    <Sheet open={open} onClose={onClose} title="Account">
      <div className="space-y-4">
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

        <p className="pt-1 text-center text-xs text-mute">MacMobileRun</p>
      </div>
    </Sheet>
  );
}
