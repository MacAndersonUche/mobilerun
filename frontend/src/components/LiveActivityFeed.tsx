import { Loader } from 'lucide-react';

export type ActivityStep = {
  n: number;
  action: string;
  reason?: string;
  ok?: boolean;
  package?: string;
  screen?: string;
  screenshot_url?: string;
  verify?: string;
  dry_run?: boolean;
  ts?: number;
};

export type ActivityPayload = {
  job_id?: string | null;
  status?: string;
  mode?: string;
  dry_run?: boolean;
  device_id?: string;
  current_step?: number;
  package?: string | null;
  screen?: string | null;
  last_action?: string | null;
  last_reason?: string | null;
  steps?: ActivityStep[];
};

function fmtTs(ts?: number) {
  if (!ts) return '';
  try {
    return new Date(ts * 1000).toLocaleTimeString();
  } catch {
    return String(ts);
  }
}

export default function LiveActivityFeed({
  title = 'Live activity',
  activity,
  loading,
}: {
  title?: string;
  activity: ActivityPayload | null;
  loading?: boolean;
}) {
  const steps = activity?.steps || [];
  const status = activity?.status || 'idle';

  return (
    <div
      className="bg-surface border border-line rounded-lg p-4 space-y-3"
      data-testid="live-activity"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold">{title}</h3>
        <div className="flex items-center gap-2 text-xs text-mute">
          {loading && <Loader className="animate-spin" size={14} />}
          <span className="capitalize" data-testid="live-activity-status">
            {status}
          </span>
          {activity?.dry_run ? (
            <span className="rounded border border-amber-700/50 bg-amber-950/40 px-1.5 py-0.5 text-amber-200">
              dry-run
            </span>
          ) : null}
          {typeof activity?.current_step === 'number' ? (
            <span data-testid="live-activity-step-count">
              step {activity.current_step}
            </span>
          ) : null}
        </div>
      </div>

      {(activity?.package || activity?.last_action) && (
        <p className="text-sm text-mute" data-testid="live-activity-meta">
          {activity?.last_action ? (
            <>
              Last: <span className="text-white">{activity.last_action}</span>
            </>
          ) : null}
          {activity?.package ? (
            <>
              {' '}
              · app <span className="text-white">{activity.package}</span>
            </>
          ) : null}
          {activity?.job_id ? (
            <>
              {' '}
              · <span className="font-mono text-[11px]">{activity.job_id}</span>
            </>
          ) : null}
        </p>
      )}

      {steps.length === 0 ? (
        <p className="text-sm text-mute" data-testid="live-activity-empty">
          No steps yet — start the mode to see live actions, reasons, and screen
          thumbnails.
        </p>
      ) : (
        <ol className="space-y-2 max-h-96 overflow-y-auto" data-testid="live-activity-steps">
          {[...steps].reverse().map((s) => (
            <li
              key={`${activity?.job_id || 'job'}-${s.n}`}
              className="rounded border border-line/60 bg-canvas px-3 py-2 text-sm"
              data-testid="live-activity-step"
            >
              <div className="flex gap-3">
                <span className="text-mute shrink-0">#{s.n}</span>
                <div className="min-w-0 flex-1">
                  <p className={s.ok === false ? 'text-red-300' : ''}>
                    {s.action}
                    {s.dry_run ? (
                      <span className="ml-2 text-[10px] uppercase text-amber-300">
                        dry-run
                      </span>
                    ) : null}
                  </p>
                  {s.reason && (
                    <p className="text-mute text-xs mt-0.5">{s.reason}</p>
                  )}
                  <p className="text-mute text-xs mt-0.5">
                    {s.screen || s.package || '—'}
                    {s.ts ? ` · ${fmtTs(s.ts)}` : ''}
                    {s.verify ? ` · ${s.verify}` : ''}
                  </p>
                </div>
                {s.screenshot_url && (
                  <img
                    src={s.screenshot_url}
                    alt={`Step ${s.n}`}
                    className="h-16 w-10 object-cover rounded border border-line"
                    data-testid="live-activity-thumb"
                  />
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
