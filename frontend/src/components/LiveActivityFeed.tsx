import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { activityJobActive } from '../lib/liveActivity';
import TaskStepLog, { type RawStep } from './TaskStepLog';

export type ActivityStep = RawStep;

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

export { activityJobActive };

/** Dating / Social live feed: plain-language steps (no screenshot toggle). */
export default function LiveActivityFeed({
  title = 'Live activity',
  activity,
  loading,
  collapsible = false,
  jobActive = false,
}: {
  title?: string;
  activity: ActivityPayload | null;
  loading?: boolean;
  /** When true, section starts collapsed unless a job is active. */
  collapsible?: boolean;
  /** Expand by default when a job is running/queued (Dating). */
  jobActive?: boolean;
}) {
  const active = jobActive || activityJobActive(activity, loading);
  // null = follow auto (expanded when active); boolean = user override
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) setUserOpen(null);
    wasActive.current = active;
  }, [active]);
  const expanded = collapsible ? (userOpen ?? active) : true;

  const feed = (
    <TaskStepLog
      title={collapsible ? undefined : title}
      status={activity?.status || 'idle'}
      taskId={activity?.job_id}
      instruction={
        activity?.dry_run
          ? `${activity?.mode || 'mode'} · dry-run`
          : activity?.mode || undefined
      }
      result={activity?.last_action || undefined}
      steps={activity?.steps || []}
      loading={loading}
      newestFirst
      emptyText="No steps yet - start the mode to see each action in plain words as it happens."
      linkToHistory
      testId={collapsible ? 'live-activity-panel' : 'live-activity'}
    />
  );

  if (!collapsible) return feed;

  return (
    <div
      className="bg-surface border border-line rounded-lg overflow-hidden"
      data-testid="live-activity"
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-canvas-elev"
        aria-expanded={expanded}
        aria-controls="live-activity-panel"
        data-testid="live-activity-toggle"
        onClick={() => setUserOpen(!(userOpen ?? active))}
      >
        {expanded ? (
          <ChevronDown size={18} className="shrink-0 text-mute" aria-hidden />
        ) : (
          <ChevronRight size={18} className="shrink-0 text-mute" aria-hidden />
        )}
        <span className="min-w-0 flex-1 font-semibold">{title}</span>
        <span
          className="text-[10px] uppercase text-mute"
          data-testid="live-activity-status"
        >
          {String(activity?.status || 'idle').toLowerCase()}
        </span>
      </button>
      {expanded ? (
        <div id="live-activity-panel" className="border-t border-line">
          <div className="p-4 pt-3">{feed}</div>
        </div>
      ) : null}
    </div>
  );
}
