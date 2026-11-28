import { useState, useEffect } from 'react';
import { Clock, CheckCircle, XCircle, Loader } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import { formatDistanceToNow } from 'date-fns';
import axios from 'axios';
import TaskStepLog, { type RawStep } from '../components/TaskStepLog';

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
  steps?: RawStep[];
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
        Plain-language step log for Normal / Dating / Social jobs (live while running).
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

      {task.status === 'running' || open ? (
        <div className="mt-3" data-testid="history-steps">
          <TaskStepLog
            title={task.status === 'running' ? 'Live steps' : 'Steps'}
            status={task.status}
            taskId={task.task_id}
            instruction={undefined}
            result={task.result}
            error={task.error}
            steps={steps}
            loading={task.status === 'running'}
            emptyText="No per-step log yet."
            testId={`history-step-log-${task.task_id}`}
          />
        </div>
      ) : steps.length > 0 ? (
        <p className="mt-2 text-xs text-mute" data-testid="history-steps-summary">
          {steps.length} step{steps.length === 1 ? '' : 's'} - expand for the
          plain-language log
          {task.result ? ` · ${task.result}` : ''}
          {task.error ? ` · error: ${task.error}` : ''}
        </p>
      ) : null}
    </div>
  );
}
