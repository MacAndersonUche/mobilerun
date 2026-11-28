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

/** Dating / Social live feed — plain-language steps first; screenshots optional. */
export default function LiveActivityFeed({
  title = 'Live activity',
  activity,
  loading,
}: {
  title?: string;
  activity: ActivityPayload | null;
  loading?: boolean;
}) {
  return (
    <TaskStepLog
      title={title}
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
      showScreenshots
      linkToHistory
      testId="live-activity"
    />
  );
}
