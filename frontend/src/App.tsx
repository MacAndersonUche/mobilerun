import { useEffect, useState } from 'react';
import {
  BrowserRouter,
  NavLink,
  Route,
  Routes,
  Navigate,
  Link,
  useLocation,
} from 'react-router-dom';
import {
  Heart,
  Smartphone,
  Settings,
  History,
  MessageCircle,
  Menu,
  X,
  User,
  BarChart3,
} from 'lucide-react';
import { AuthProvider, useAuth } from './auth';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import AccountPage from './pages/AccountPage';
import DevicesPage from './pages/DevicesPage';
import TasksPage from './pages/TasksPage';
import HistoryPage from './pages/HistoryPage';
import SettingsPage from './pages/SettingsPage';
import UsagePage from './pages/UsagePage';
import DatingPage from './pages/DatingPage';
import ChatPage from './pages/ChatPage';
import SocialPage from './pages/SocialPage';
import AuthCallbackPage from './pages/AuthCallbackPage';
import PairPage from './pages/PairPage';
import { cn } from './lib/cn';

function MobileMenu({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const location = useLocation();
  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  if (!open) return null;
  const links = [
    { to: '/dating', icon: Heart, label: 'Dating' },
    { to: '/social', icon: MessageCircle, label: 'Social' },
    { to: '/tasks', icon: History, label: 'Tasks' },
    { to: '/devices', icon: Smartphone, label: 'Devices' },
    { to: '/usage', icon: BarChart3, label: 'Usage' },
    { to: '/settings', icon: Settings, label: 'Settings' },
    { to: '/account', icon: User, label: 'Account' },
    { to: '/chat', icon: MessageCircle, label: 'Chat' },
  ];
  return (
    <div
      className="fixed inset-0 z-50 md:hidden"
      role="dialog"
      aria-modal="true"
      aria-label="Menu"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60"
        aria-label="Close menu backdrop"
        onClick={onClose}
      />
      <div className="absolute inset-x-0 top-0 border-b border-line bg-canvas-elev px-4 pb-4 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sheet">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-base font-semibold">Menu</p>
          <button
            type="button"
            className="tap-target inline-flex items-center justify-center rounded-xl text-mute hover:text-white"
            aria-label="Close menu"
            onClick={onClose}
          >
            <X size={22} />
          </button>
        </div>
        <nav className="space-y-1">
          {links.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className="tap-target flex items-center gap-3 rounded-xl px-3 text-sm text-white hover:bg-surface"
              onClick={onClose}
            >
              <l.icon size={18} />
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}

function Shell() {
  const { token } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const isHome = location.pathname === '/' || location.pathname === '';

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
    { to: '/dating', icon: Heart, label: 'Dating' },
    { to: '/devices', icon: Smartphone, label: 'Devices' },
    { to: '/history', icon: History, label: 'History' },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="min-h-screen bg-canvas text-white">
      <div className="mx-auto flex min-h-screen max-w-6xl">
        {/* Desktop sidebar — hidden on home (tiles are the nav) */}
        {!isHome && (
          <aside
            className="hidden w-60 shrink-0 border-r border-line bg-canvas-elev/80 p-4 md:block"
            data-testid="desktop-sidebar"
          >
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
              {/* Social stays secondary under Dating */}
              <Link
                to="/social"
                className="ml-8 flex items-center gap-2 rounded-xl px-3 py-2 text-xs text-mute hover:bg-surface hover:text-white"
              >
                <MessageCircle size={14} />
                Social
              </Link>
              <Link
                to="/usage"
                className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-mute hover:bg-surface hover:text-white"
              >
                <BarChart3 size={18} />
                Usage
              </Link>
            </nav>
          </aside>
        )}

        <main className="relative min-w-0 flex-1 overflow-x-clip">
          {/* Mobile top bar — brand + hamburger (not on home) */}
          {!isHome && (
            <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-canvas/95 px-4 py-2 backdrop-blur md:hidden pt-[max(0.5rem,env(safe-area-inset-top))]">
              <Link to="/" className="min-w-0">
                <p className="truncate text-base font-semibold tracking-tight">
                  MacMobileRun
                </p>
                <p className="text-[10px] uppercase tracking-[0.18em] text-mute">
                  Dating & social
                </p>
              </Link>
              <button
                type="button"
                className="tap-target inline-flex items-center justify-center rounded-xl border border-line bg-surface text-white"
                aria-label="Open menu"
                aria-expanded={menuOpen}
                data-testid="mobile-menu-button"
                onClick={() => setMenuOpen(true)}
              >
                <Menu size={22} />
              </button>
            </header>
          )}

          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/dating" element={<DatingPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/usage" element={<UsagePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/social" element={<SocialPage />} />
            {/* Kept for job-run / pairing deep links; not in primary nav */}
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/account" element={<AccountPage />} />
            {/* Legacy Needs you / Matches / Live View / Run URLs → Dating / home */}
            <Route path="/needs-you" element={<Navigate to="/dating" replace />} />
            <Route path="/matches" element={<Navigate to="/dating" replace />} />
            <Route path="/run" element={<Navigate to="/dating" replace />} />
            <Route path="/live" element={<Navigate to="/" replace />} />
            <Route path="/pair" element={<PairPage />} />
            <Route path="/p/:code" element={<PairPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>

      {!isHome && (
        <MobileMenu open={menuOpen} onClose={() => setMenuOpen(false)} />
      )}

      {/* Mobile bottom nav — hidden on home */}
      {!isHome && (
        <nav
          className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-canvas-elev/95 backdrop-blur md:hidden"
          data-testid="mobile-bottom-nav"
          aria-label="Primary"
        >
          <div className="mx-auto flex max-w-content justify-around px-1 pb-[env(safe-area-inset-bottom)]">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  cn(
                    'tap-target flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] leading-tight',
                    isActive ? 'text-accent' : 'text-mute'
                  )
                }
              >
                <t.icon size={22} aria-hidden />
                <span className="truncate">{t.label}</span>
              </NavLink>
            ))}
          </div>
        </nav>
      )}
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
