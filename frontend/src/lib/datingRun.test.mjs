/**
 * Run: node --experimental-strip-types src/lib/datingRun.test.mjs
 */
import assert from 'node:assert/strict';
import {
  canRunApp,
  clampRunCount,
  datingStartBody,
  runCountFor,
  runCountLabel,
} from './datingRun.ts';

assert.equal(canRunApp('co.hinge.app'), true);
assert.equal(canRunApp('com.whatsapp'), false);
assert.equal(canRunApp('ai.mobilerun.mockdating'), false);

const all = datingStartBody({
  deviceId: 'android_x',
  dryRun: true,
  contactScope: 'new',
  counts: { 'co.hinge.app': 3, 'com.whatsapp': 9 },
  apps: ['com.whatsapp', 'co.hinge.app', 'com.hily.app', 'com.taggedapp'],
});
assert.deepEqual(all.apps, ['co.hinge.app', 'com.hily.app']);
// Each app its own number; unset apps use the default 5; no socials
assert.deepEqual(all.counts, { 'co.hinge.app': 3, 'com.hily.app': 5 });
assert.equal(all.device_id, 'android_x');
assert.equal('stand_in_package' in all, false);

const one = datingStartBody({
  deviceId: '',
  dryRun: false,
  contactScope: 'new',
  counts: { 'com.facebook.katana': 80, 'com.bumble.app': 20 },
  apps: ['com.facebook.katana'],
});
assert.deepEqual(one.apps, ['com.facebook.katana']);
assert.deepEqual(one.counts, { 'com.facebook.katana': 50 }); // FB cap 50
assert.equal(runCountFor('com.bumble.app', { 'com.bumble.app': 20 }), 20);
assert.equal(clampRunCount('com.badoo.mobile', 0), 1);
assert.equal(clampRunCount('com.badoo.mobile', 900), 500);
assert.equal(runCountLabel('com.bumble.app'), 'Swipes per run');
assert.match(runCountLabel('com.hily.app'), /after 5 messages/);
assert.equal(one.device_id, undefined);
console.log('datingRun ok');

// r45: free typing, validate on submit; caps kept
{
  const { parseCountInput, parseRunCount, runCountHint } = await import('./datingRun.ts');
  const a = (c, m) => { if (!c) throw new Error(m); };
  a(parseCountInput('', 10).ok === false, 'blank refused at submit');
  a(parseCountInput('abc', 10).ok === false, 'letters refused');
  a(parseCountInput('0', 10).ok === false, 'zero refused');
  a(parseCountInput('7', 10).ok && parseCountInput('7', 10).n === 7, '7 ok');
  a(parseCountInput('11', 10).ok === false, 'over cap refused');
  const fb = parseRunCount('com.facebook.katana', '60');
  a(!fb.ok && /50/.test(fb.error), 'FB cap 50 shown');
  a(parseRunCount('com.bumble.app', '250').ok, 'bumble 250 ok');
  a(/50/.test(runCountHint('com.facebook.katana')), 'FB hint');
  console.log('r45 count input tests ok');
}
