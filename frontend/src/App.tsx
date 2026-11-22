import {
  BrowserRouter,
  NavLink,
  Route,
  Routes,
  Navigate,
  Link,
} from 'react-router-dom';
import {
  Heart,
  Smartphone,
  AlertTriangle,
  Settings,
  History,
  MessageCircle,
} from 'lucide-react';
import { AuthProvider, useAuth } from './auth';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import DevicesPage from './pages/DevicesPage';
import HistoryPage from './pages/HistoryPage';
import SettingsPage from './pages/SettingsPage';
import DatingPage from './pages/DatingPage';
import SocialPage from './pages/SocialPage';
import NeedsYouPage from './pages/NeedsYouPage';
import AuthCallbackPage from './pages/AuthCallbackPage';
import PairPage from './pages/PairPage';
import { cn } from './lib/cn';

function Shell() {
  const { token } = useAuth();
  // Cognito redirect + HTTPS pairing landing must render without a token
  if (
    typeof window !== 'undefined' &&
    (window.location.pathname.startsWith('/auth/') ||
      window.location.pathname.startsWith('/pair') ||
      window.location.pathname.startsWith('/p/'))
  ) {
    return (
      <Routes>
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/pair" element={<PairPage />} />
        <Route path="/p/:code" element={<PairPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }
  if (!token) return <LoginPage />;

  const tabs = [
    { to: '/dating', icon: Heart, label: 'Run' },
    { to: '/devices', icon: Smartphone, label: 'Devices' },
    { to: '/history', icon: History, label: 'History' },
    { to: '/settings', icon: Settings, label: 'Settings' },
    { to: '/needs-you', icon: AlertTriangle, label: 'Needs' },
  ];

  return (
    <div className="min-h-screen bg-canvas text-white">
      <div className="mx-auto flex min-h-screen max-w-6xl">
        {/* Desktop sidebar */}
        <aside className="hidden w-60 shrink-0 border-r border-line bg-canvas-elev/80 p-4 md:block">
          <Link to="/" className="mb-8 block px-2 hover:opacity-90">
            <p className="text-lg font-semibold tracking-tight">MacMobileRun</p>
            <p className="text-[10px] uppercase tracking-[0.22em] text-mute">
              Dating & social
            </p>
          </Link>
          <nav className="space-y-0.5">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition',
                    isActive
                      ? 'bg-surface-elev text-white'
                      : 'text-mute hover:bg-surface hover:text-white'
                  )
                }
              >
                <t.icon size={18} />
                {t.label}
              </NavLink>
            ))}
            {/* Social stays secondary under Run */}
            <Link
              to="/social"
              className="ml-8 flex items-center gap-2 rounded-xl px-3 py-2 text-xs text-mute hover:bg-surface hover:text-white"
            >
              <MessageCircle size={14} />
              Social
            </Link>
          </nav>
        </aside>

        <main className="relative min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/dating" element={<DatingPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/needs-you" element={<NeedsYouPage />} />
            <Route path="/social" element={<SocialPage />} />
            {/* Removed from nav — keep redirects */}
            <Route path="/matches" element={<Navigate to="/dating" replace />} />
            <Route path="/tasks" element={<Navigate to="/history" replace />} />
            <Route path="/live" element={<Navigate to="/devices" replace />} />
            <Route path="/chat" element={<Navigate to="/dating" replace />} />
            <Route path="/account" element={<Navigate to="/settings" replace />} />
            <Route path="/pair" element={<PairPage />} />
            <Route path="/p/:code" element={<PairPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-canvas-elev/95 backdrop-blur md:hidden">
        <div className="mx-auto flex max-w-content justify-around px-1 pb-[env(safe-area-inset-bottom)]">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) =>
                cn(
                  'flex flex-1 flex-col items-center gap-1 py-2 text-[10px]',
                  isActive ? 'text-accent' : 'text-mute'
                )
              }
            >
              <t.icon size={20} />
              {t.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </AuthProvider>
  );
}
