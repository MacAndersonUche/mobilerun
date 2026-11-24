/** Socials: only "message this person" and "reply to messages" — no swipes. */

export const SOCIAL_PACKAGES = [
  'com.whatsapp',
  'com.instagram.android',
  'com.facebook.orca',
  'org.telegram.messenger',
  'com.snapchat.android',
  'com.twitter.android',
];

// Apps the backend can message today (backend/social_run.py SOCIAL_APPS)
export const SOCIAL_MESSAGE_APPS = [
  'com.whatsapp',
  'com.instagram.android',
  'com.facebook.orca',
  'org.telegram.messenger',
];

export function isSocialPackage(pkg: string): boolean {
  return SOCIAL_PACKAGES.includes((pkg || '').toLowerCase());
}

export function canMessageApp(pkg: string): boolean {
  return SOCIAL_MESSAGE_APPS.includes(pkg);
}

export function socialRunBody(opts: {
  deviceId: string;
  app: string;
  action: 'message' | 'reply';
  contact?: string;
  message: string;
  dryRun: boolean;
}) {
  return {
    device_id: opts.deviceId || undefined,
    app: opts.app,
    action: opts.action,
    contact: opts.action === 'message' ? (opts.contact || '').trim() : undefined,
    message: opts.message.trim(),
    // WhatsApp is dry-run only
    dry_run: opts.app === 'com.whatsapp' ? true : opts.dryRun,
  };
}
