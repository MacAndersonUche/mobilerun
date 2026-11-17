import { useState, useEffect } from 'react';
import { Clock, CheckCircle, XCircle, Loader } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import { formatDistanceToNow } from 'date-fns';
import axios from 'axios';

interface TaskStep {
  n: number;
  action: string;
  reason?: string;
  ok?: boolean;
  screenshot_url?: string;
  verify?: string;
}

interface Task {
  task_id: string;
  device_id: string;
  instruction: string;
  status: string;
  current_step: number;
  max_steps: number;
  result?: string;
  error?: string;
  started_at: string;
  completed_at?: string;
  planner?: string;
  llm_provider?: string;
  mode?: string;
  steps?: TaskStep[];
}

export default function HistoryPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    loadHistory();
    const interval = setInterval(loadHistory, 3000);
    return () => clearInterval(interval);
  }, []);

  const loadHistory = async () => {
    try {
      const response = await axios.get(`${getBackendUrl()}/api/tasks`, {
        headers: { Authorization: `Bearer ${getAuthToken()}` },
      });
      setTasks(response.data);
    } catch (error) {
      console.error('Failed to load history:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader className="animate-spin text-blue-400" size={32} />
      </div>
    );
  }

  return (
    <div className="mr-page space-y-6">
      <h2 className="text-2xl font-semibold">Task History</h2>
      <p className="text-mute text-sm">
        Live step list for Normal / Dating / Social agent jobs (polls every 3s).
      </p>

      <div className="space-y-3">
        {tasks.length === 0 ? (
          <div className="bg-surface rounded-lg p-8 text-center">
            <Clock size={48} className="mx-auto text-gray-600 mb-4" />
            <p className="text-mute">No task history yet</p>
          </div>
        ) : (
          tasks.map((task) => (
            <TaskCard
              key={task.task_id}
              task={task}
              open={expanded === task.task_id}
              onToggle={() =>
                setExpanded((id) => (id === task.task_id ? null : task.task_id))
              }
            />
          ))
        )}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  open,
  onToggle,
}: {
  task: Task;
  open: boolean;
  onToggle: () => void;
}) {
  const statusIcon = {
    running: <Loader className="animate-spin text-blue-400" size={20} />,
    completed: <CheckCircle className="text-green-400" size={20} />,
    failed: <XCircle className="text-red-400" size={20} />,
    stopped: <XCircle className="text-mute" size={20} />,
  }[task.status] || <Clock className="text-mute" size={20} />;

  const statusColor = {
    running: 'text-blue-400',
    completed: 'text-green-400',
    failed: 'text-red-400',
    stopped: 'text-mute',
  }[task.status] || 'text-mute';

  const steps = task.steps || [];

  return (
    <div className="bg-surface rounded-lg p-4 border border-line" data-testid="history-task">
      <button
        type="button"
        className="w-full text-left flex items-start justify-between mb-3 gap-3"
        onClick={onToggle}
      >
        <div className="flex-1 min-w-0">
          <p className="font-medium mb-1">{task.instruction}</p>
          <p className="text-sm text-mute">
            Started {formatDistanceToNow(new Date(task.started_at), { addSuffix: true })}
            {task.mode ? ` · ${task.mode}` : ''}
            {task.llm_provider ? ` · ${task.llm_provider}` : ''}
          </p>
        </div>
        <div className="flex items-center space-x-2 shrink-0">
          {statusIcon}
          <span className={`text-sm font-medium ${statusColor} capitalize`}>
            {task.status}
          </span>
        </div>
      </button>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-mute">Progress:</span>{' '}
          <span>
            {task.current_step} / {task.max_steps}
          </span>
        </div>
        <div className="truncate">
          <span className="text-mute">Device:</span> <span>{task.device_id}</span>
        </div>
      </div>

      {task.result && (
        <div className="mt-3 p-3 bg-gray-900 rounded text-sm">
          <span className="text-mute">Result: </span>
          {task.result}
        </div>
      )}

      {task.error && (
        <div className="mt-3 p-3 bg-red-900/20 border border-red-700 rounded text-sm text-red-400">
          {task.error}
        </div>
      )}

      {(open || task.status === 'running' || steps.length > 0) && steps.length > 0 && (
        <ol className="mt-3 space-y-2" data-testid="history-steps">
          {steps.map((s) => (
            <li
              key={`${task.task_id}-${s.n}`}
              className="rounded border border-line/60 bg-canvas px-3 py-2 text-sm"
            >
              <div className="flex gap-3">
                <span className="text-mute shrink-0">#{s.n}</span>
                <div className="min-w-0 flex-1">
                  <p className={s.ok === false ? 'text-red-300' : ''}>{s.action}</p>
                  {s.reason && <p className="text-mute text-xs mt-0.5">{s.reason}</p>}
                  {s.verify && <p className="text-mute text-xs mt-0.5">{s.verify}</p>}
                </div>
                {s.screenshot_url && (
                  <img
                    src={s.screenshot_url}
                    alt={`Step ${s.n}`}
                    className="h-16 w-10 object-cover rounded border border-line"
                  />
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
      {open && steps.length === 0 && (
        <p className="mt-3 text-mute text-sm">No per-step log yet.</p>
      )}
    </div>
  );
}
