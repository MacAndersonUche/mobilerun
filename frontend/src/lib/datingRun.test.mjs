/**
 * Run: node --experimental-strip-types src/lib/datingRun.test.mjs
 */
import assert from 'node:assert/strict';
import { canRunApp, datingStartBody } from './datingRun.ts';

assert.equal(canRunApp('co.hinge.app'), true);
assert.equal(canRunApp('com.whatsapp'), false);
assert.equal(canRunApp('ai.mobilerun.mockdating'), false);

const all = datingStartBody({
  deviceId: 'android_x',
  dryRun: true,
  contactScope: 'new',
  count: 3,
  apps: ['com.whatsapp', 'co.hinge.app', 'com.hily.app', 'com.taggedapp'],
});
assert.deepEqual(all.apps, ['co.hinge.app', 'com.hily.app']);
assert.equal(all.count, 3);
assert.equal(all.device_id, 'android_x');
assert.equal('stand_in_package' in all, false);

const one = datingStartBody({
  deviceId: '',
  dryRun: false,
  contactScope: 'new',
  count: 5,
  apps: ['com.facebook.katana'],
});
assert.deepEqual(one.apps, ['com.facebook.katana']);
assert.equal(one.device_id, undefined);
console.log('datingRun ok');
