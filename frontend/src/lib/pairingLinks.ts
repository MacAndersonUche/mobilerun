/** Build deep-link / intent / https handoff URLs for same-phone pairing. */

export const MOBILERUN_PACKAGE = 'ai.mobilerun.selfhosted';
export const PAIR_FRONTEND =
  (typeof import.meta !== 'undefined' &&
    (import.meta as { env?: { VITE_FRONTEND_URL?: string } }).env?.VITE_FRONTEND_URL) ||
  'https://macsmobilerun.netlify.app';

export function shortPairPath(code: string): string {
  return `/p/${encodeURIComponent(code)}`;
}

export function shortHttpsLink(code: string, origin = PAIR_FRONTEND): string {
  return `${origin.replace(/\/$/, '')}${shortPairPath(code)}`;
}

export function buildIntentUrl(opts: {
  token: string;
  httpsFallback: string;
  packageName?: string;
}): string {
  const pkg = opts.packageName || MOBILERUN_PACKAGE;
  const fallback = encodeURIComponent(opts.httpsFallback);
  // Prefer short `c=` so intent URLs stay tiny
  return (
    `intent://pair?c=${encodeURIComponent(opts.token)}` +
    `#Intent;scheme=mobilerun;package=${pkg};` +
    `S.browser_fallback_url=${fallback};end`
  );
}

export function buildDeepLink(token: string): string {
  return `mobilerun://pair?c=${encodeURIComponent(token)}`;
}
