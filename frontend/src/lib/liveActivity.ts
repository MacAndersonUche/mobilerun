/** True when a dating/social job is running or queued. */
export function activityJobActive(
  activity: { status?: string } | null | undefined,
  runningFlag?: boolean
): boolean {
  if (runningFlag) return true;
  const st = String(activity?.status || '').toLowerCase();
  return /^(running|queued|pending|active|in_progress)$/.test(st);
}
