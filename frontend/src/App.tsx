import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import {
  Smartphone,
  Settings,
  History,
  Play,
  Heart,
  MonitorPlay,
  MessageSquare,
  MessageCircle,
  AlertTriangle,
} from 'lucide-react';
import DevicesPage from './pages/DevicesPage';
import TasksPage from './pages/TasksPage';
import HistoryPage from './pages/HistoryPage';
import SettingsPage from './pages/SettingsPage';
import DatingPage from './pages/DatingPage';
import LiveViewPage from './pages/LiveViewPage';
import ChatPage from './pages/ChatPage';
import SocialPage from './pages/SocialPage';
import NeedsYouPage from './pages/NeedsYouPage';

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-gray-100">
        <header className="bg-gray-800 border-b border-gray-700">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-bold text-blue-400">
                Mobilerun Control Center
              </h1>
              <div className="text-sm text-gray-400">Self-Hosted Edition</div>
            </div>
          </div>
        </header>

        <div className="flex">
          <nav className="w-64 bg-gray-800 min-h-[calc(100vh-73px)] p-4 border-r border-gray-700">
            <ul className="space-y-2">
              <NavItem to="/" icon={<Smartphone />} label="Devices" />
              <NavItem to="/live" icon={<MonitorPlay />} label="Live View" />
              <NavItem to="/chat" icon={<MessageSquare />} label="AI Chat" />
              <NavItem to="/tasks" icon={<Play />} label="Run Task" />
              <NavItem to="/dating" icon={<Heart />} label="Dating Mode" />
              <NavItem to="/social" icon={<MessageCircle />} label="Social Mode" />
              <NavItem to="/needs-you" icon={<AlertTriangle />} label="Needs you" />
              <NavItem to="/history" icon={<History />} label="History" />
              <NavItem to="/settings" icon={<Settings />} label="Settings" />
            </ul>
          </nav>

          <main className="flex-1 p-6">
            <Routes>
              <Route path="/" element={<DevicesPage />} />
              <Route path="/live" element={<LiveViewPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/dating" element={<DatingPage />} />
              <Route path="/social" element={<SocialPage />} />
              <Route path="/needs-you" element={<NeedsYouPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}

function NavItem({
  to,
  icon,
  label,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <li>
      <Link
        to={to}
        className="flex items-center space-x-3 px-4 py-3 rounded-lg hover:bg-gray-700 transition-colors"
      >
        <span className="text-blue-400">{icon}</span>
        <span>{label}</span>
      </Link>
    </li>
  );
}

export default App;
