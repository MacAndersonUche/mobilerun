/** Run page Start / per-app Run → POST /api/dating/start body. */

// Apps with a verified auto run on the phone (backend/dating_run.py RUN_APPS)
export const RUNNABLE_APPS = [
  'co.hinge.app',
  'com.hily.app',
  'com.facebook.katana',
  'co.yellw.yellowapp',
  'com.bumble.app',
  'com.badoo.mobile',
  'com.taggedapp',
  'com.takimi.android', // r50: Taimi auto like / message + like
  // r49: Mac — Tinder and BLK at the bottom of the list
  'com.affinityapps.blk',
  'com.tinder', // r49 (CA-24): fixed auto-swipe
  // r50: new apps at the very bottom
  'enterprises.dating.boo',
  'social.breeze.breeze_app',
  'com.getpure.pure',
  'com.threesome.swingers.threefun',
];
// r50: new apps (Boo, Breeze, Pure, 3Fun) — below BLK and Tinder
export const NEW_APPS_R50 = [
  'enterprises.dating.boo',
  'social.breeze.breeze_app',
  'com.getpure.pure',
  'com.threesome.swingers.threefun',
];
export const TAIMI_PKG = 'com.takimi.android';
export const BOO_PKG = 'enterprises.dating.boo';
export const PURE_PKG = 'com.getpure.pure';

// r49: Mac (24 Nov) — "move Tinder and BLK to the bottom of the portal"
export const BOTTOM_APPS = ['com.affinityapps.blk', 'com.tinder'];
function bottomRank(pkg: string): number {
  const p = (pkg || '').toLowerCase();
  if (p.startsWith('com.tinder') || p.includes('tinder')) return 2;
  if (NEW_APPS_R50.includes(p)) return 3; // r50: new apps at the very bottom
  if (p === 'com.affinityapps.blk' || p.endsWith('.blk')) return 1;
  return 0;
}
/** Stable sort: every other app keeps its order; BLK then Tinder go last. */
export function sortDatingApps<T>(items: T[], pkgOf: (item: T) => string): T[] {
  return items
    .map((item, i) => ({ item, i, r: bottomRank(pkgOf(item)) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((x) => x.item);
}

// r45: Tagged runs as auto swipe (free like) or auto message
export const TAGGED_PKG = 'com.taggedapp';
// r46: Hily runs as "Likes only" or "Message + likes"
export const HILY_PKG = 'com.hily.app';
export type RunMode = 'swipe' | 'message' | 'likes' | 'message_likes';
const LIKE_MSG_MODES: { value: RunMode; label: string }[] = [
  { value: 'likes', label: 'Auto like' },
  { value: 'message_likes', label: 'Auto message + like' },
];
export const RUN_MODES: Record<string, { value: RunMode; label: string }[]> = {
  [TAGGED_PKG]: [
    { value: 'swipe', label: 'Auto swipe' },
    { value: 'message', label: 'Auto message' },
  ],
  [HILY_PKG]: [
    { value: 'likes', label: 'Likes only' },
    { value: 'message_likes', label: 'Message + likes' },
  ],
  // r50
  [TAIMI_PKG]: LIKE_MSG_MODES,
  [BOO_PKG]: LIKE_MSG_MODES,
  [PURE_PKG]: [
    { value: 'likes', label: 'Auto tap' },
    { value: 'message', label: 'Auto message' },
  ],
};
export function hasRunMode(pkg: string): boolean {
  return pkg in RUN_MODES;
}
export function runModesOf(pkg: string): { value: RunMode; label: string }[] {
  return RUN_MODES[pkg] || [];
}
export function runModeFor(pkg: string, modes: Record<string, string>): RunMode {
  const opts = runModesOf(pkg);
  const hit = opts.find((o) => o.value === modes[pkg]);
  if (hit) return hit.value;
  if (pkg === HILY_PKG) return 'message_likes';
  if (opts.length) return opts[0].value; // r50: Taimi / Boo / Pure → first mode
  return 'swipe';
}

// r46: max likes per Hily mode, saved as "<pkg>:<mode>"
export const DEFAULT_LIKES = 30;
export const LIKES_MAX = 500;
export const HILY_MESSAGES_MAX = 5;
export function hasLikeCap(pkg: string, mode?: string): boolean {
  if (pkg === HILY_PKG) return true;
  // r50: Taimi / Boo — Max likes only in "Auto message + like"
  if (pkg === TAIMI_PKG || pkg === BOO_PKG) return mode === undefined || mode === 'message_likes';
  return false;
}
export function likeCapKey(pkg: string, mode: string): string {
  return `${pkg}:${mode}`;
}
export function likeCapFor(pkg: string, mode: string, caps: Record<string, number>): number {
  const v = Math.floor(Number(caps[likeCapKey(pkg, mode)] ?? DEFAULT_LIKES));
  if (!Number.isFinite(v) || v < 1) return DEFAULT_LIKES;
  return Math.min(LIKES_MAX, v);
}
export function parseLikeCap(raw: unknown): CountParse {
  return parseCountInput(raw, LIKES_MAX, 'Max likes');
}
export function likeCapHint(pkg: string, mode: string): string {
  if (pkg === TAIMI_PKG || pkg === BOO_PKG)
    return `Max ${LIKES_MAX} · likes after the messages to new matches`;
  if (pkg !== HILY_PKG) return '';
  return mode === 'likes'
    ? `Max ${LIKES_MAX} · free hearts from Finder`
    : `Max ${LIKES_MAX} · includes the likes before the messages`;
}
/** Hily in Likes only sends no messages, so its message box is hidden. */
export function showsCount(pkg: string, modes: Record<string, string>): boolean {
  return !(pkg === HILY_PKG && runModeFor(pkg, modes) === 'likes');
}

export function canRunApp(pkg: string): boolean {
  return RUNNABLE_APPS.includes(pkg);
}

// Default per-run number for each app card (Hily: likes after its 5 messages)
export const DEFAULT_RUN_COUNT = 5;
export const RUN_COUNT_MAX = 500;

/** Per-app caps that stay fixed whatever the card says. */
export function runCountCap(pkg: string): number {
  if (pkg === 'com.facebook.katana') return 50;
  if (pkg === HILY_PKG) return HILY_MESSAGES_MAX;
  return RUN_COUNT_MAX;
}

/** What the number on each app card means. */
export function runCountLabel(pkg: string): string {
  if (pkg === 'com.bumble.app' || pkg === 'com.badoo.mobile') return 'Swipes per run';
  if (pkg === 'com.hily.app') return 'Messages per run (max 5)';
  if (pkg === 'com.facebook.katana') return 'Messages per run (max 50)';
  if (pkg === TAGGED_PKG) return 'Swipes / messages per run';
  if (pkg === 'com.tinder') return 'Swipes per run';
  if (pkg === 'social.breeze.breeze_app' || pkg === 'com.threesome.swingers.threefun')
    return 'Likes per run';
  if (pkg === TAIMI_PKG || pkg === BOO_PKG || pkg === PURE_PKG)
    return 'Likes / messages per run';
  return 'Messages per run';
}

/** Hint shown under a count box: the real cap only (no minimum clamp). */
export function runCountHint(pkg: string): string {
  if (pkg === 'com.facebook.katana') return 'Max 50 (Facebook Dating limit)';
  if (pkg === 'com.hily.app')
    return `Max ${HILY_MESSAGES_MAX} · likes N in Finder, messages N from Likes sent, then likes`;
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
  modes?: Record<string, string>;
  likeCaps?: Record<string, number>;
}) {
  const apps = opts.apps.filter(canRunApp);
  const counts: Record<string, number> = {};
  const modes: Record<string, RunMode> = {};
  const like_caps: Record<string, number> = {};
  apps.forEach((a) => {
    counts[a] = runCountFor(a, opts.counts);
    if (hasRunMode(a)) modes[a] = runModeFor(a, opts.modes || {});
    if (hasLikeCap(a)) {
      runModesOf(a).forEach((m) => {
        like_caps[likeCapKey(a, m.value)] = likeCapFor(a, m.value, opts.likeCaps || {});
      });
    }
  });
  return {
    device_id: opts.deviceId || undefined,
    dry_run: opts.dryRun,
    contact_scope: opts.contactScope,
    // Each app's own per-run number (saved per app on the server)
    counts,
    // r45: per-app run mode (Tagged swipe / message)
    modes,
    // r46: max likes per Hily mode
    like_caps,
    // Real apps only — never the mock stand-in, never WhatsApp
    apps,
  };
}
