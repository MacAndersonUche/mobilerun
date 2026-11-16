import { useState, useEffect } from 'react';
import { Clock, CheckCircle, XCircle, Loader } from 'lucide-react';
import { getBackendUrl, getAuthToken } from '../config';
import { formatDistanceToNow } from 'date-fns';
import axios from 'axios';

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
}

export default function HistoryPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadHistory();
    const interval = setInterval(loadHistory, 5000);
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
    <div className="space-y-6">
      <h2 className="text-3xl font-bold">Task History</h2>

      <div className="space-y-3">
        {tasks.length === 0 ? (
          <div className="bg-gray-800 rounded-lg p-8 text-center">
            <Clock size={48} className="mx-auto text-gray-600 mb-4" />
            <p className="text-gray-400">No task history yet</p>
          </div>
        ) : (
          tasks.map((task) => <TaskCard key={task.task_id} task={task} />)
        )}
      </div>
    </div>
  );
}

function TaskCard({ task }: { task: Task }) {
  const statusIcon = {
    running: <Loader className="animate-spin text-blue-400" size={20} />,
    completed: <CheckCircle className="text-green-400" size={20} />,
    failed: <XCircle className="text-red-400" size={20} />,
  }[task.status];

  const statusColor = {
    running: 'text-blue-400',
    completed: 'text-green-400',
    failed: 'text-red-400',
  }[task.status];

  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <p className="font-medium mb-1">{task.instruction}</p>
          <p className="text-sm text-gray-400">
            Started {formatDistanceToNow(new Date(task.started_at), { addSuffix: true })}
          </p>
        </div>
        <div className="flex items-center space-x-2">
          {statusIcon}
          <span className={`text-sm font-medium ${statusColor} capitalize`}>
            {task.status}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-gray-400">Progress:</span>{' '}
          <span>{task.current_step} / {task.max_steps}</span>
        </div>
        <div>
          <span className="text-gray-400">Device:</span>{' '}
          <span>{task.device_id}</span>
        </div>
      </div>

      {task.result && (
        <div className="mt-3 p-3 bg-gray-900 rounded text-sm">
          <span className="text-gray-400">Result: </span>
          {task.result}
        </div>
      )}

      {task.error && (
        <div className="mt-3 p-3 bg-red-900/20 border border-red-700 rounded text-sm text-red-400">
          {task.error}
        </div>
      )}
    </div>
  );
}
