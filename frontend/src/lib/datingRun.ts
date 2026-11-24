/** Run page Start / per-app Run → POST /api/dating/start body. */

// Apps with a verified auto run on the phone (backend/dating_run.py RUN_APPS)
export const RUNNABLE_APPS = [
  'co.hinge.app',
  'com.hily.app',
  'com.facebook.katana',
  'com.affinityapps.blk',
  'co.yellw.yellowapp',
  'com.bumble.app',
  'com.badoo.mobile',
];

export function canRunApp(pkg: string): boolean {
  return RUNNABLE_APPS.includes(pkg);
}

// Default per-run number for each app card (Hily: likes after its 5 messages)
export const DEFAULT_RUN_COUNT = 5;
export const RUN_COUNT_MAX = 500;

/** Per-app caps that stay fixed whatever the card says. */
export function runCountCap(pkg: string): number {
  if (pkg === 'com.facebook.katana') return 50;
  return RUN_COUNT_MAX;
}

/** What the number on each app card means. */
export function runCountLabel(pkg: string): string {
  if (pkg === 'com.bumble.app' || pkg === 'com.badoo.mobile') return 'Swipes per run';
  if (pkg === 'com.hily.app') return 'Likes per run (after 5 messages)';
  if (pkg === 'com.facebook.katana') return 'Messages per run (max 50)';
  return 'Messages per run';
}

/** Hint shown under a count box: the real cap only (no minimum clamp). */
export function runCountHint(pkg: string): string {
  if (pkg === 'com.facebook.katana') return 'Max 50 (Facebook Dating limit)';
  if (pkg === 'com.hily.app') return `Max ${RUN_COUNT_MAX} · Hily sends 5 messages, then likes`;
  return `Max ${RUN_COUNT_MAX}`;
}

export type CountParse = { ok: true; n: number } | { ok: false; error: string };

/**
 * r45: validate a typed count on submit. The box itself accepts anything
 * (it can be cleared while typing); only Start/Save checks it.
 */
export function parseCountInput(raw: unknown, cap: number, label = 'Number'): CountParse {
  const t = String(raw ?? '').trim();
  if (t === '') return { ok: false, error: `${label}: enter a number` };
  if (!/^\d+$/.test(t)) return { ok: false, error: `${label}: whole numbers only` };
  const n = Number(t);
  if (n < 1) return { ok: false, error: `${label}: must be 1 or more` };
  if (n > cap) return { ok: false, error: `${label}: max is ${cap}` };
  return { ok: true, n };
}

export function parseRunCount(pkg: string, raw: unknown, label?: string): CountParse {
  return parseCountInput(raw, runCountCap(pkg), label || runCountLabel(pkg));
}

export function clampRunCount(pkg: string, n: unknown): number {
  const v = Math.floor(Number(n));
  if (!Number.isFinite(v) || v < 1) return 1;
  return Math.min(runCountCap(pkg), v);
}

/** The card's own number, else the default. */
export function runCountFor(pkg: string, counts: Record<string, number>): number {
  return clampRunCount(pkg, counts[pkg] ?? DEFAULT_RUN_COUNT);
}

export function datingStartBody(opts: {
  deviceId: string;
  dryRun: boolean;
  contactScope: string;
  counts: Record<string, number>;
  apps: string[];
}) {
  const apps = opts.apps.filter(canRunApp);
  const counts: Record<string, number> = {};
  apps.forEach((a) => {
    counts[a] = runCountFor(a, opts.counts);
  });
  return {
    device_id: opts.deviceId || undefined,
    dry_run: opts.dryRun,
    contact_scope: opts.contactScope,
    // Each app's own per-run number (saved per app on the server)
    counts,
    // Real apps only — never the mock stand-in, never WhatsApp
    apps,
  };
}
