import { Link } from 'react-router-dom';
import { Loader } from 'lucide-react';
import {
  formatStepLine,
  formatStepTime,
  stepStatusLabel,
  type RawStep,
} from '../lib/formatStep';

export type { RawStep };

type Props = {
  title?: string;
  status?: string;
  taskId?: string | null;
  instruction?: string | null;
  result?: string | null;
  error?: string | null;
  steps?: RawStep[] | null;
  loading?: boolean;
  /** Newest first for live feeds; oldest first for task progress */
  newestFirst?: boolean;
  emptyText?: string;
  linkToHistory?: boolean;
  testId?: string;
};

function StatusPill({
  label,
  testId,
}: {
  label: 'done' | 'failed' | 'running' | string;
  testId?: string;
}) {
  const tone =
    label === 'failed'
      ? 'border-red-700/50 bg-red-950/40 text-red-200'
      : label === 'running'
        ? 'border-sky-700/50 bg-sky-950/40 text-sky-200'
        : label === 'done' || label === 'completed'
          ? 'border-emerald-700/50 bg-emerald-950/40 text-emerald-200'
          : 'border-line bg-canvas text-mute';
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${tone}`}
      data-testid={testId}
    >
      {label}
    </span>
  );
}

export default function TaskStepLog({
  title = 'Live steps',
  status = 'idle',
  taskId,
  instruction,
  result,
  error,
  steps,
  loading,
  newestFirst = false,
  emptyText = 'Waiting for the first step…',
  linkToHistory = false,
  testId = 'task-step-log',
}: Props) {
  const list = [...(steps || [])];
  if (newestFirst) list.reverse();
  const st = String(status || 'idle').toLowerCase();

  return (
    <div
      className={
        title
          ? 'bg-surface border border-line rounded-lg p-4 space-y-3'
          : 'space-y-3'
      }
      data-testid={testId}
    >
      {title ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">{title}</h3>
          <div className="flex items-center gap-2 text-xs text-mute">
            {loading && <Loader className="animate-spin" size={14} />}
            <StatusPill label={st} testId="live-activity-status" />
            {typeof steps?.length === 'number' && steps.length > 0 ? (
              <span data-testid="live-activity-step-count">
                {steps.length} steps
              </span>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-mute">
          {loading && <Loader className="animate-spin" size={14} />}
          {typeof steps?.length === 'number' && steps.length > 0 ? (
            <span data-testid="live-activity-step-count">
              {steps.length} steps
            </span>
          ) : null}
        </div>
      )}

      {instruction ? (
        <p className="text-sm text-mute" data-testid="task-step-instruction">
          Task: <span className="text-white">{instruction}</span>
        </p>
      ) : null}

      {(taskId || linkToHistory) && (
        <p className="text-xs text-mute font-mono">
          {taskId ? <span data-testid="task-step-id">{taskId}</span> : null}
          {linkToHistory ? (
            <>
              {taskId ? ' · ' : null}
              <Link to="/history" className="text-accent underline font-sans">
                Open in Activity
              </Link>
              {' · '}
              <Link to="/tasks" className="text-accent underline font-sans">
                Tasks
              </Link>
            </>
          ) : null}
        </p>
      )}

      {list.length === 0 ? (
        <p className="text-sm text-mute" data-testid="task-step-empty">
          {emptyText}
        </p>
      ) : (
        <ol className="space-y-2 max-h-96 overflow-y-auto" data-testid="task-steps">
          {list.map((s, idx) => {
            const isLatest =
              newestFirst ? idx === 0 : s.n === Math.max(...list.map((x) => x.n));
            const pill = stepStatusLabel(s, { isLatest, taskStatus: st });
            const line = formatStepLine(s);
            const when = formatStepTime(s.ts);
            return (
              <li
                key={`${taskId || 'task'}-${s.n}-${s.ts || 0}`}
                className="rounded border border-line/60 bg-canvas px-3 py-2 text-sm"
                data-testid="live-activity-step"
              >
                <div className="flex gap-3 items-start">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p
                        className={
                          s.ok === false ? 'text-red-300' : 'text-white'
                        }
                        data-testid="step-line"
                      >
                        {line}
                      </p>
                      <StatusPill label={pill} />
                      {when ? (
                        <span className="text-[11px] text-mute">{when}</span>
                      ) : null}
                    </div>
                    {(s.screen || s.package) && (
                      <p className="text-mute text-xs mt-0.5">
                        on {s.screen || s.package}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {(result || error) && (
        <div
          className={`text-sm rounded border px-3 py-2 ${
            error
              ? 'border-red-700/50 bg-red-950/30 text-red-200'
              : 'border-line bg-canvas text-mute'
          }`}
          data-testid="task-step-result"
        >
          <span className="text-mute">{error ? 'Error: ' : 'Result: '}</span>
          {error || result}
        </div>
      )}
    </div>
  );
}
