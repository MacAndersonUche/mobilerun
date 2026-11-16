import { BrowserRouter, NavLink, Route, Routes, Navigate } from 'react-router-dom';
import {
  Home,
  MessageSquare,
  Smartphone,
  Heart,
  MessageCircle,
  AlertTriangle,
  MonitorPlay,
  Settings,
  History,
} from 'lucide-react';
import { AuthProvider, useAuth } from './auth';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import AccountPage from './pages/AccountPage';
import DevicesPage from './pages/DevicesPage';
import TasksPage from './pages/TasksPage';
import HistoryPage from './pages/HistoryPage';
import SettingsPage from './pages/SettingsPage';
import DatingPage from './pages/DatingPage';
import LiveViewPage from './pages/LiveViewPage';
import ChatPage from './pages/ChatPage';
import SocialPage from './pages/SocialPage';
import NeedsYouPage from './pages/NeedsYouPage';
import { cn } from './lib/cn';

function Shell() {
  const { token } = useAuth();
  if (!token) return <LoginPage />;

  const tabs = [
    { to: '/', icon: Home, label: 'Home', end: true },
    { to: '/chat', icon: MessageSquare, label: 'Chat' },
    { to: '/devices', icon: Smartphone, label: 'Devices' },
    { to: '/needs-you', icon: AlertTriangle, label: 'Needs' },
    { to: '/settings', icon: Settings, label: 'More' },
  ];

  return (
    <div className="min-h-screen bg-canvas text-white">
      <div className="mx-auto flex min-h-screen max-w-6xl">
        {/* Desktop sidebar */}
        <aside className="hidden w-56 shrink-0 border-r border-line bg-canvas-elev p-4 md:block">
          <div className="mb-6 px-2">
            <p className="text-[10px] uppercase tracking-[0.2em] text-mute">MacAI</p>
            <p className="text-lg font-semibold">MobileRun</p>
          </div>
          <nav className="space-y-1">
            {[
              ...tabs,
              { to: '/live', icon: MonitorPlay, label: 'Live' },
              { to: '/dating', icon: Heart, label: 'Dating' },
              { to: '/social', icon: MessageCircle, label: 'Social' },
              { to: '/tasks', icon: Smartphone, label: 'Tasks' },
              { to: '/history', icon: History, label: 'Activity' },
              { to: '/account', icon: Settings, label: 'Account' },
            ].map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={'end' in t ? t.end : false}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm',
                    isActive
                      ? 'bg-accent/20 text-accent'
                      : 'text-mute hover:bg-surface hover:text-white'
                  )
                }
              >
                <t.icon size={18} />
                {t.label}
              </NavLink>
            ))}
          </nav>
        </aside>

        <main className="relative min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="/live" element={<LiveViewPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/dating" element={<DatingPage />} />
            <Route path="/social" element={<SocialPage />} />
            <Route path="/needs-you" element={<NeedsYouPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/account" element={<AccountPage />} />
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
              end={'end' in t ? t.end : false}
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
