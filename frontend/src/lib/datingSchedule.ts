/** r44: dating run schedules (per app + combo) → /api/dating/schedules. */
import {
  DEFAULT_LIKES,
  LIKES_MAX,
  RUNNABLE_APPS,
  type RunMode,
  clampRunCount,
  hasLikeCap,
  hasRunMode,
  runModeFor,
} from './datingRun.ts';

export type ScheduleItem = {
  app: string;
  runs: number;
  count: number;
  mode?: RunMode;
  likes?: number; // r46: Hily max likes for the item's mode
};
export type DatingSchedule = {
  id?: string;
  name?: string;
  enabled: boolean;
  kind?: 'app' | 'combo';
  items: ScheduleItem[];
  time: string; // HH:MM London
  days: number[]; // Mon=0 … Sun=6; [] = every day
  dry_run: boolean;
  device_id?: string;
  next_run?: string | null;
  next_run_label?: string | null;
  last_result?: string | null;
};

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const MAX_RUNS_PER_APP = 10;

export function clampRuns(n: unknown): number {
  const v = Math.floor(Number(n));
  if (!Number.isFinite(v) || v < 1) return 1;
  return Math.min(MAX_RUNS_PER_APP, v);
}

export function daysLabel(days: number[]): string {
  if (!days || days.length === 0 || days.length === 7) return 'Every day';
  return [...days].sort().map((d) => DAY_LABELS[d]).join(', ');
}

export function validTime(t: string): boolean {
  return /^([01]?\d|2[0-3]):[0-5]\d$/.test((t || '').trim());
}

/** Body for create/update: runnable apps only, runs/count clamped. */
export function scheduleBody(s: DatingSchedule) {
  const items = s.items
    .filter((i) => RUNNABLE_APPS.includes(i.app))
    .map((i) => ({
      app: i.app,
      runs: clampRuns(i.runs),
      count: clampRunCount(i.app, i.count),
      ...(hasRunMode(i.app) ? { mode: runModeFor(i.app, { [i.app]: i.mode || '' }) } : {}),
      ...(hasLikeCap(i.app, runModeFor(i.app, { [i.app]: i.mode || '' }))
        ? { likes: Math.max(1, Math.min(LIKES_MAX, Math.floor(Number(i.likes) || DEFAULT_LIKES))) }
        : {}),
    }));
  return {
    name: s.name || undefined,
    enabled: s.enabled,
    items,
    time: s.time.trim(),
    days: s.days.length === 7 ? [] : [...s.days].sort(),
    // Portal no longer offers dry-run — clear any saved dry_run=true.
    dry_run: false,
    device_id: s.device_id || undefined,
  };
}

export function scheduleSummary(s: DatingSchedule, name: (pkg: string) => string): string {
  const parts = s.items.map(
    (i) =>
      `${name(i.app)}${i.mode ? ` ${i.mode}` : ''} ${i.runs > 1 ? `×${i.runs} ` : ''}(${i.count}/run${i.likes ? `, ${i.likes} likes` : ''})`
  );
  return `${parts.join(' → ')} · ${s.time} ${daysLabel(s.days)}${s.dry_run ? ' · dry run' : ''}`;
}
