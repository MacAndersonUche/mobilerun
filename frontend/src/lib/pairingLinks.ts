/** Build deep-link / intent / https handoff URLs for same-phone pairing. */

export const MOBILERUN_PACKAGE = 'ai.mobilerun.selfhosted';

export function buildIntentUrl(opts: {
  token: string;
  httpsFallback: string;
  packageName?: string;
}): string {
  const pkg = opts.packageName || MOBILERUN_PACKAGE;
  const fallback = encodeURIComponent(opts.httpsFallback);
  // Custom-scheme intent that Chrome can open into the installed APK.
  return (
    `intent://pair?token=${encodeURIComponent(opts.token)}` +
    `#Intent;scheme=mobilerun;package=${pkg};` +
    `S.browser_fallback_url=${fallback};end`
  );
}

export function buildDeepLink(token: string): string {
  return `mobilerun://pair?token=${encodeURIComponent(token)}`;
}
