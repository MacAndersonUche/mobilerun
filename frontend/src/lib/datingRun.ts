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

export function datingStartBody(opts: {
  deviceId: string;
  dryRun: boolean;
  contactScope: string;
  count: number;
  apps: string[];
}) {
  return {
    device_id: opts.deviceId || undefined,
    dry_run: opts.dryRun,
    contact_scope: opts.contactScope,
    count: opts.count,
    // Real apps only — never the mock stand-in, never WhatsApp
    apps: opts.apps.filter(canRunApp),
  };
}
