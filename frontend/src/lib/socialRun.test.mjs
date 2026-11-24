/**
 * Run: node --experimental-strip-types src/lib/socialRun.test.mjs
 */
import assert from 'node:assert/strict';
import { canMessageApp, isSocialPackage, socialRunBody } from './socialRun.ts';

assert.equal(isSocialPackage('com.whatsapp'), true);
assert.equal(isSocialPackage('com.snapchat.android'), true);
assert.equal(isSocialPackage('co.hinge.app'), false);
assert.equal(isSocialPackage('com.facebook.katana'), false); // Facebook Dating
assert.equal(canMessageApp('com.snapchat.android'), false);

const wa = socialRunBody({
  deviceId: 'd', app: 'com.whatsapp', action: 'message',
  contact: ' Jo ', message: ' hi ', dryRun: false,
});
assert.equal(wa.dry_run, false); // follows the toggle
assert.equal(socialRunBody({ deviceId: 'd', app: 'com.whatsapp', action: 'reply', message: 'hi', dryRun: true }).dry_run, true);
assert.equal(wa.contact, 'Jo');
assert.equal(wa.message, 'hi');
assert.equal('count' in wa, false);

const ig = socialRunBody({
  deviceId: '', app: 'com.instagram.android', action: 'reply',
  contact: 'ignored', message: 'hey', dryRun: false,
});
assert.equal(ig.dry_run, false);
assert.equal(ig.contact, undefined);
assert.equal(ig.device_id, undefined);
console.log('socialRun ok');
