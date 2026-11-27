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
  'com.myyearbook.m', // MeetMe — Apps to come (no working driver yet)
];
// r50: new apps (Boo, Breeze, Pure, 3Fun) — below BLK and Tinder
export const NEW_APPS_R50 = [
  'enterprises.dating.boo',
  'social.breeze.breeze_app',
  'com.getpure.pure',
  'com.threesome.swingers.threefun',
];
export const MEETME_PKG = 'com.myyearbook.m';
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

/** Append any runnable app missing from a saved / API app list. */
export function ensureRunnableConfigApps<T extends { package_name: string }>(
  configApps: T[],
  seed: (pkg: string) => T
): T[] {
  const have = new Set((configApps || []).map((a) => a.package_name));
  const extra = RUNNABLE_APPS.filter((pkg) => !have.has(pkg)).map(seed);
  return [...(configApps || []), ...extra];
}

// Dating page groups: move an app between groups by moving its package
// between these three lists — nothing else needs to change.
// - works: apps that run all the time (top of the page)
// - needs-fixing: drivers exist but these still fail or need work; Taimi is
//   blocked (FLAG_SECURE makes its screenshots black) and must not be runnable
// - coming-soon: no working driver yet — cards show as coming soon, no Run
export type DatingAppGroupId = 'works' | 'needs-fixing' | 'coming-soon';
export interface DatingAppGroupDef {
  id: DatingAppGroupId;
  title: string;
  subtitle: string;
  packages: string[];
}
export const DATING_APP_GROUPS: DatingAppGroupDef[] = [
  {
    id: 'works',
    title: 'Working',
    subtitle: 'These run reliably — trigger them any time.',
    // Hily: verified live 5/5 via Activity > Likes sent (r53, 27 Nov 2026)
    // Yubo: verified live 5/5 Direct sends (r54, 27 Nov 2026)
    // Hinge: verified live 5/5 with r53n heart ladder (27 Nov 2026)
    // Tagged: Mac confirmed messages sending on phone (27 Nov 2026)
    packages: [
      'com.badoo.mobile',
      'com.bumble.app',
      'com.hily.app',
      'co.yellw.yellowapp',
      'co.hinge.app',
      'com.taggedapp',
    ],
  },
  {
    id: 'needs-fixing',
    title: 'Still needs fixing',
    subtitle: 'Drivers exist but these still fail or need work.',
    packages: [
      'com.facebook.katana',
      'com.takimi.android',
    ],
  },
  {
    id: 'coming-soon',
    title: 'Apps to come',
    subtitle: 'No working driver yet — coming soon, cannot run.',
    packages: [
      'com.tinder',
      'enterprises.dating.boo',
      'social.breeze.breeze_app',
      'com.getpure.pure',
      'com.threesome.swingers.threefun',
      'com.myyearbook.m',
      // Mac (27 Nov): move BLK out of Still needs fixing into Apps to come
      'com.affinityapps.blk',
    ],
  },
];

export function datingAppGroup(pkg: string): DatingAppGroupId | null {
  const hit = DATING_APP_GROUPS.find((g) => g.packages.includes(pkg));
  return hit ? hit.id : null;
}

/**
 * Legacy localStorage key from #94. Collapsible sections now always start
 * collapsed on every page load — never restore expanded from storage.
 */
export const APPS_TO_COME_EXPANDED_KEY = 'dating_apps_to_come_expanded';

/** Drop any remembered expanded preference so reloads stay collapsed. */
export function clearCollapsibleExpandedPrefs(
  storage: Pick<Storage, 'removeItem'> | null | undefined = globalThis.localStorage
): void {
  try {
    storage?.removeItem(APPS_TO_COME_EXPANDED_KEY);
  } catch {
    /* private mode / unavailable */
  }
}

/** Taimi is blocked: FLAG_SECURE makes its screenshots black, so the bot cannot see the screen. */
export const TAIMI_BLOCKED_NOTE =
  'Blocked — screenshots come out black (FLAG_SECURE), so the bot cannot see the screen.';
export function isBlockedApp(pkg: string): boolean {
  return pkg === TAIMI_PKG;
}

/** Whether this app's card gets working Run / count / mode controls. */
export function canRunFromCard(pkg: string): boolean {
  if (!canRunApp(pkg)) return false;
  if (isBlockedApp(pkg)) return false;
  if (datingAppGroup(pkg) === 'coming-soon') return false;
  return true;
}

/** Split cards into the three page groups, in group order; within a group
 * cards follow the group's package list. A card in no group (e.g. a new app
 * the backend adds later) falls into "Still needs fixing" so it never
 * vanishes from the page. */
export function groupDatingCards<T extends { package: string }>(
  cards: T[]
): { group: DatingAppGroupDef; apps: T[] }[] {
  const byPkg = new Map(cards.map((c) => [c.package, c]));
  const out = DATING_APP_GROUPS.map((group) => ({
    group,
    apps: group.packages
      .map((pkg) => byPkg.get(pkg))
      .filter((c): c is T => Boolean(c)),
  }));
  const grouped = new Set(DATING_APP_GROUPS.flatMap((g) => g.packages));
  const ungrouped = cards.filter((c) => !grouped.has(c.package));
  if (ungrouped.length) {
    out.find((g) => g.group.id === 'needs-fixing')?.apps.push(...ungrouped);
  }
  return out.filter((g) => g.apps.length > 0);
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
