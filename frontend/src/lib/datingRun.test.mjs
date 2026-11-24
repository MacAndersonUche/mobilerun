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
  sortDatingApps,
  RUNNABLE_APPS,
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
// r45: Tagged is runnable now (auto swipe / auto message)
assert.deepEqual(all.apps, ['co.hinge.app', 'com.hily.app', 'com.taggedapp']);
// Each app its own number; unset apps use the default 5; no socials
assert.deepEqual(all.counts, { 'co.hinge.app': 3, 'com.hily.app': 5, 'com.taggedapp': 5 });
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
assert.match(runCountLabel('com.hily.app'), /max 5/); // r46: Hily messages
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

// r45: Tagged run mode
{
  const { datingStartBody, runModeFor, canRunApp } = await import('./datingRun.ts');
  const a = (c, m) => { if (!c) throw new Error(m); };
  a(canRunApp('com.taggedapp'), 'tagged runnable');
  a(runModeFor('com.taggedapp', {}) === 'swipe', 'default swipe');
  const b = datingStartBody({ deviceId: 'd', dryRun: false, contactScope: 'new',
    counts: { 'com.taggedapp': 7 }, apps: ['com.taggedapp', 'com.bumble.app'],
    modes: { 'com.taggedapp': 'message' } });
  a(b.modes['com.taggedapp'] === 'message' && !('com.bumble.app' in b.modes), 'modes body');
  a(b.counts['com.taggedapp'] === 7, 'tagged count');
  console.log('r45 tagged mode tests ok');
}

// r46: Hily Likes only / Message + likes, max likes per mode
{
  const m = await import('./datingRun.ts');
  const a = (c, msg) => { if (!c) throw new Error(msg); };
  a(m.hasRunMode('com.hily.app') && m.hasLikeCap('com.hily.app'), 'hily has modes + likes');
  a(!m.hasLikeCap('com.taggedapp'), 'tagged has no like cap');
  a(m.runModeFor('com.hily.app', {}) === 'message_likes', 'hily default message + likes');
  a(m.runModeFor('com.hily.app', { 'com.hily.app': 'swipe' }) === 'message_likes', 'tagged mode refused for hily');
  a(m.runModesOf('com.hily.app').map((x) => x.label).join('|') === 'Likes only|Message + likes', 'labels');
  a(!m.showsCount('com.hily.app', { 'com.hily.app': 'likes' }), 'no message box in Likes only');
  a(m.showsCount('com.hily.app', {}), 'message box in Message + likes');
  a(!m.parseRunCount('com.hily.app', '6').ok, 'hily messages max 5');
  a(!m.parseLikeCap('501').ok && m.parseLikeCap('120').ok, 'likes max 500');
  const b = m.datingStartBody({ deviceId: 'd', dryRun: false, contactScope: 'new',
    counts: { 'com.hily.app': 3 }, apps: ['com.hily.app', 'com.bumble.app'],
    modes: { 'com.hily.app': 'likes' }, likeCaps: { 'com.hily.app:likes': 80 } });
  a(b.modes['com.hily.app'] === 'likes', 'hily mode in body');
  a(b.like_caps['com.hily.app:likes'] === 80, 'likes-only cap');
  a(b.like_caps['com.hily.app:message_likes'] === 30, 'other mode keeps its own default');
  a(!Object.keys(b.like_caps).some((k) => k.startsWith('com.bumble')), 'no bumble caps');
  console.log('r46 hily mode tests ok');
}

// r49: Tinder and BLK at the bottom; everything else keeps its order
{
  const pk = (a) => a.p;
  const got = sortDatingApps(
    [{ p: 'com.tinder' }, { p: 'com.bumble.app' }, { p: 'com.affinityapps.blk' },
     { p: 'com.hily.app' }, { p: 'co.hinge.app' }],
    pk
  ).map(pk);
  assert.deepEqual(got, ['com.bumble.app', 'com.hily.app', 'co.hinge.app',
    'com.affinityapps.blk', 'com.tinder']);
  assert.deepEqual(RUNNABLE_APPS.slice(-2), ['com.affinityapps.blk', 'com.tinder']);
  assert.equal(canRunApp('com.tinder'), true);
}
